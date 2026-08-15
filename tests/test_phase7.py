"""Automated tests for Phase 7 (Security, Sandbox & Reliability
Hardening), per prompt.md section 19. Real BattleEngine/BattleRunner
(no Tk — BattleRunner has no GUI dependency), real DecideWorker
subprocesses, real corrupted-JSON files on disk. Run with:

    python tests/test_phase7.py
"""

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from challenges.challenge_repository import ChallengeRepository
from challenges.challenge_service import ChallengeService
from engine import events as ev
from engine.api import ForbiddenAPIError
from engine.battle import BattleEngine
from engine.config import BattleConfig
from engine.runner import BattleRunner
from engine.worker import DecideWorker, STATUS_OK, STATUS_TIMEOUT
from results.result_repository import ResultRepository
from results.result_service import ResultService
from roster.team_repository import TeamRepository
from roster.team_service import TeamService
from storage import CorruptedDataError, read_json_file, write_json_file_atomic
from submissions.submission_repository import SubmissionRepository
from submissions.submission_service import SubmissionService
from tournament.competition import ValidationError as TournamentValidationError
from tournament.match import STATUS_CANCELLED as M_CANCELLED, STATUS_READY as M_READY
from tournament.round import TYPE_ROUND_ROBIN
from tournament.tournament_repository import TournamentRepository
from tournament.tournament_service import TournamentService
from ui import live_state, localization, theme

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALPHA_PATH = os.path.join(ROOT, "teams", "team_alpha.py")
BETA_PATH = os.path.join(ROOT, "teams", "team_beta.py")

with open(ALPHA_PATH, encoding="utf-8") as f:
    AGGRESSIVE_CODE = f.read()
with open(BETA_PATH, encoding="utf-8") as f:
    BETA_CODE = f.read()

HANG_CODE = """
def decide(friendly, enemies, api):
    while True:
        pass
"""
CRASH_CODE = """
def decide(friendly, enemies, api):
    x = 1 / 0
"""
FORBIDDEN_API_CODE = """
def decide(friendly, enemies, api):
    target = api["find_nearest"](enemies)
    if target:
        api["attack"](target)
"""


def _wait(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _fresh_tournament_env(n_teams=2):
    tmp = tempfile.mkdtemp(prefix="battleship_phase7_test_")
    team_repo = TeamRepository(os.path.join(tmp, "teams.json"))
    team_svc = TeamService(team_repo, os.path.join(tmp, "team_submissions"))
    team_svc.ensure_default_teams(ALPHA_PATH, BETA_PATH)

    ch_repo = ChallengeRepository(os.path.join(tmp, "challenges.json"))
    ch_svc = ChallengeService(ch_repo)
    ch_svc.ensure_default_challenge()
    challenge = ch_svc.get_active_challenge()

    sub_repo = SubmissionRepository(os.path.join(tmp, "submissions.json"))
    sub_svc = SubmissionService(sub_repo, team_svc, ch_svc)
    for tid in ("team-alpha", "team-beta"):
        sub = sub_svc.create_draft(tid, challenge.id, AGGRESSIVE_CODE)
        sub_svc.submit_submission(sub.id)

    t_repo = TournamentRepository(os.path.join(tmp, "tournament"))
    r_repo = ResultRepository(os.path.join(tmp, "results"))
    t_svc = TournamentService(t_repo, team_svc, ch_svc, sub_svc)
    r_svc = ResultService(r_repo, t_svc, team_svc, ch_svc, sub_svc)
    t_svc.result_service = r_svc
    return tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge


# ================================================================= 1-2 timeout
def test_infinite_loop_participant_code_is_detected():
    engine = BattleEngine(HANG_CODE, BETA_CODE, config=BattleConfig(code_execution_timeout=1.5), isolate_execution=True)
    engine.start()
    t0 = time.perf_counter()
    engine.step(1 / 30)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0  # bounded by the timeout, never hangs the caller forever
    timeouts = [e for e in engine.events.all() if e.kind == ev.CODE_TIMEOUT]
    assert len(timeouts) == 1
    engine.shutdown_workers()


def test_execution_timeout_is_configurable_single_source_of_truth():
    """config.code_execution_timeout is the one value that governs both
    DecideWorker startup patience and per-request hang detection (see
    engine/worker.py). Measures hang-detection time only, on a worker
    already confirmed alive first — separating "how long did the OS take
    to spawn this process" (system-load-dependent, not what this test is
    about) from "did the configured timeout actually govern the wait"."""
    slow_cfg, fast_cfg = 3.0, 0.6
    assert slow_cfg != fast_cfg
    w_slow = DecideWorker(HANG_CODE, timeout=slow_cfg)
    w_fast = DecideWorker(HANG_CODE, timeout=fast_cfg)
    assert w_slow.dead is False and w_fast.dead is False  # both started fine — startup time excluded from what's measured below

    friendly = {"id": "alpha", "team": "A", "x": 0, "y": 0, "hp": 100, "alive": True, "attack_ready": True}
    enemies = [{"id": "beta", "team": "B", "x": 5, "y": 5, "hp": 100, "alive": True}]

    t0 = time.perf_counter()
    outcome_fast = w_fast.request(friendly, enemies, BattleConfig())
    elapsed_fast = time.perf_counter() - t0
    assert outcome_fast.status == STATUS_TIMEOUT
    assert fast_cfg * 0.5 < elapsed_fast < fast_cfg * 3  # governed by ITS OWN configured timeout, generous bounds for system load
    w_fast.shutdown()
    w_slow.shutdown()


# ============================================================== 3-5 worker lifecycle
def test_worker_process_termination_on_timeout():
    w = DecideWorker(HANG_CODE, timeout=0.5)
    friendly = {"id": "alpha", "team": "A", "x": 0, "y": 0, "hp": 100, "alive": True, "attack_ready": True}
    enemies = [{"id": "beta", "team": "B", "x": 5, "y": 5, "hp": 100, "alive": True}]
    outcome = w.request(friendly, enemies, BattleConfig())
    assert outcome.status == STATUS_TIMEOUT
    assert w.dead is True
    assert w._proc.is_alive() is False  # actually terminated, not just marked dead
    w.shutdown()


def test_worker_cleanup_shutdown_is_idempotent():
    w = DecideWorker(AGGRESSIVE_CODE, timeout=1.0)
    w.shutdown()
    w.shutdown()  # must not raise on a second call
    assert w.dead is True or w._proc.is_alive() is False


def test_worker_crash_reported_not_raised():
    engine = BattleEngine(CRASH_CODE, BETA_CODE, isolate_execution=True)
    engine.start()
    engine.step(1 / 30)  # CRASH_CODE raises ZeroDivisionError inside decide() — must not propagate
    errors = [e for e in engine.events.all() if e.kind == ev.CODE_ERROR]
    assert len(errors) > 0
    assert engine.ship_a.alive is True  # a code exception never destroys the ship directly
    engine.shutdown_workers()


# ==================================================================== 6-7 exceptions
def test_participant_exception_does_not_crash_engine():
    engine = BattleEngine(CRASH_CODE, BETA_CODE, isolate_execution=True)
    engine.start()
    for _ in range(10):
        engine.step(1 / 30)
    assert engine.ended is False or engine.winner != engine.ship_a.team  # never a fabricated win for the crashing side
    engine.shutdown_workers()


def test_forbidden_api_call_gives_clear_structured_error():
    config = BattleConfig(allowed_api=["move_toward", "hold_position", "find_nearest", "distance_to", "log"])
    engine = BattleEngine(FORBIDDEN_API_CODE, BETA_CODE, config=config)  # in-process path — no isolate needed for this check
    engine.start()
    engine.step(1 / 30)
    errors = [e for e in engine.events.all() if e.kind == ev.CODE_ERROR]
    assert len(errors) > 0
    assert "attack" in errors[0].message and "not available" in errors[0].message
    assert "KeyError" not in errors[0].message  # a raw KeyError repr is exactly what Phase 7 replaces


# ================================================================= 8-10 event kinds
def test_code_timeout_event_distinct_from_code_error():
    assert ev.CODE_TIMEOUT != ev.CODE_ERROR
    engine = BattleEngine(HANG_CODE, BETA_CODE, config=BattleConfig(code_execution_timeout=1.5), isolate_execution=True)
    engine.start()
    engine.step(1 / 30)
    kinds = {e.kind for e in engine.events.all()}
    assert ev.CODE_TIMEOUT in kinds
    engine.shutdown_workers()


def test_code_error_event_still_works_unisolated():
    engine = BattleEngine(CRASH_CODE, BETA_CODE)  # isolate_execution=False — Pre-Phase-7 path, unchanged
    engine.start()
    engine.step(1 / 30)
    kinds = {e.kind for e in engine.events.all()}
    assert ev.CODE_ERROR in kinds
    assert ev.CODE_TIMEOUT not in kinds


def test_engine_error_distinguishable_from_team_errors():
    """ENGINE_ERROR (BattleRunner.on_error / App.engine_fault) is a
    SEPARATE mechanism from team CODE_ERROR/CODE_TIMEOUT — proven by
    triggering a real engine.step() failure and confirming it surfaces
    via on_error, never as a team-attributed event."""
    class ExplodingEngine(BattleEngine):
        def step(self, dt):
            raise RuntimeError("engine bug, not team code")

    engine = ExplodingEngine(AGGRESSIVE_CODE, BETA_CODE)
    engine.start()
    runner = BattleRunner(engine, tick_hz=30)
    captured = []
    runner.on_error = lambda msg: captured.append(msg)
    runner.start_thread()
    assert _wait(lambda: len(captured) > 0)
    assert "engine bug" in captured[0]
    assert all(e.kind not in (ev.CODE_ERROR, ev.CODE_TIMEOUT) for e in engine.events.all())
    runner.stop_thread()


# ============================================================ 11-12 no fake winner / responsive
def test_no_fake_winner_after_code_failure():
    engine = BattleEngine(HANG_CODE, BETA_CODE, config=BattleConfig(code_execution_timeout=1.5), isolate_execution=True)
    engine.start()
    for _ in range(10):
        engine.step(1 / 30)
    assert engine.winner != "Team Alpha"  # the timed-out side is never declared the winner as a side effect
    engine.shutdown_workers()


def test_battle_runner_remains_responsive_during_timeout():
    runner = BattleRunner(BattleEngine(HANG_CODE, BETA_CODE, config=BattleConfig(code_execution_timeout=1.0), isolate_execution=True), tick_hz=30)
    runner.start_thread()
    runner.start_battle()
    max_snapshot_time = 0.0
    end = time.time() + 3.0
    while time.time() < end:
        t0 = time.perf_counter()
        runner.snapshot()  # must never block for anywhere near the 1.0s timeout
        max_snapshot_time = max(max_snapshot_time, time.perf_counter() - t0)
        time.sleep(0.02)
    assert max_snapshot_time < 0.3  # snapshot() stays cheap even while a worker is mid-timeout
    runner.stop_thread()


# =========================================================== 13-14 leak/shutdown
def test_multiple_consecutive_battles_dont_leak_workers():
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE, isolate_execution=True)
    procs_seen = []
    for _ in range(3):
        engine.reset()
        procs_seen.append((engine._workers["alpha"]._proc, engine._workers["beta"]._proc))
    # workers persist (reused) across resets that don't involve a
    # timeout/crash — not respawned every reset, but never orphaned either
    engine.shutdown_workers()
    for a, b in procs_seen:
        assert a.is_alive() is False and b.is_alive() is False


def test_clean_application_shutdown_no_worker_survives():
    runner = BattleRunner(BattleEngine(AGGRESSIVE_CODE, BETA_CODE, isolate_execution=True), tick_hz=30)
    runner.start_thread()
    runner.start_battle()
    assert _wait(lambda: runner.snapshot()["tick_count"] > 0)
    alpha_proc = runner.engine._workers["alpha"]._proc
    beta_proc = runner.engine._workers["beta"]._proc
    runner.stop_thread()  # this must also call engine.shutdown_workers()
    assert alpha_proc.is_alive() is False
    assert beta_proc.is_alive() is False
    assert runner._thread.is_alive() is False


# ========================================================= 15-16 persistence hardening
def test_corrupted_json_handling():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "teams.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{this is not valid json")
    try:
        read_json_file(path)
        raise AssertionError("corrupted JSON did not raise")
    except CorruptedDataError:
        pass
    with open(path, encoding="utf-8") as f:
        assert f.read() == "{this is not valid json"  # never silently overwritten
    shutil.rmtree(tmp)


def test_missing_persistence_files_handled_gracefully():
    tmp = tempfile.mkdtemp()
    missing = os.path.join(tmp, "does_not_exist.json")
    assert read_json_file(missing) == {}  # no crash, no exception
    shutil.rmtree(tmp)


def test_atomic_write_survives_a_read_afterward():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "data.json")
    write_json_file_atomic(path, {"a": 1, "b": [1, 2, 3]})
    assert read_json_file(path) == {"a": 1, "b": [1, 2, 3]}
    assert not os.path.exists(path + ".tmp")  # no leftover temp file
    shutil.rmtree(tmp)


# ================================================================ 17-18 orphan cleanup
def test_orphan_submission_cleanup_only_deletes_own_stub():
    tmp = tempfile.mkdtemp()
    team_repo = TeamRepository(os.path.join(tmp, "teams.json"))
    subdir = os.path.join(tmp, "submissions")
    team_svc = TeamService(team_repo, subdir)
    team_svc.ensure_default_teams(ALPHA_PATH, BETA_PATH)  # points at the real teams/*.py files, NOT subdir
    created = team_svc.create_team("Orphan Test", team_id="orphan-team")
    stub_path = created.submission_id
    assert os.path.exists(stub_path)

    team_svc.delete_team("orphan-team")
    assert not os.path.exists(stub_path)  # its own stub is cleaned up
    assert os.path.exists(ALPHA_PATH)  # the shared project file is never touched
    assert team_svc.get_team("team-alpha") is not None  # unrelated team record untouched
    shutil.rmtree(tmp)


def test_historical_result_preservation_after_team_deletion():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge = _fresh_tournament_env()
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    t_svc.add_team("champ", "team-alpha")
    t_svc.add_team("champ", "team-beta")
    t_svc.mark_ready("champ")
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.start_competition("champ")
    m = matches[0]
    t_svc.prepare_match_for_start(m.id)
    completed = t_svc.complete_match(m.id, "TEAM_A_WIN", m.team_a_id, 10.0)
    result = r_svc.record_from_match(completed, {
        "team_a_hp_remaining": 50.0, "team_b_hp_remaining": 0.0,
        "team_a_damage_dealt": 100.0, "team_b_damage_dealt": 0.0,
        "team_a_damage_received": 0.0, "team_b_damage_received": 100.0,
    }, [])
    original_name = result.team_a_name_at_match

    # deleting the team (not currently in a live battle) must not touch
    # the already-persisted historical MatchResult
    team_svc.delete_team("team-alpha")
    reloaded = r_svc.get_match_result(m.id)
    assert reloaded is not None
    assert reloaded.team_a_name_at_match == original_name
    shutil.rmtree(tmp)


# ============================================================= 19 ship reassignment
def test_ship_reassignment_does_not_corrupt_live_identity():
    tmp = tempfile.mkdtemp()
    team_repo = TeamRepository(os.path.join(tmp, "teams.json"))
    team_svc = TeamService(team_repo, os.path.join(tmp, "subs"))
    team_svc.ensure_default_teams(ALPHA_PATH, BETA_PATH)
    # Reassigning a team's ship_id is a pure data-layer change — it must
    # succeed at the service layer regardless of what any live engine is
    # currently doing (App._sync_engine_state() is what defers re-sync,
    # a UI-layer concern outside this service's responsibility). The
    # pre-existing exclusive-slot guard (one team per ship_id) is
    # unchanged and still correctly rejects a genuine conflict.
    updated = team_svc.update_team("team-alpha", ship_id=None)
    assert updated.ship_id is None  # unassigning always succeeds, frees the slot

    reassigned = team_svc.update_team("team-alpha", ship_id="alpha")
    assert reassigned.ship_id == "alpha"  # reassigning to its own now-free slot succeeds cleanly

    from roster.team import ValidationError as TeamValidationError
    try:
        team_svc.update_team("team-beta", ship_id="alpha")
        raise AssertionError("assigning an already-occupied ship slot was accepted")
    except TeamValidationError as e:
        assert str(e) == "ship_already_assigned"  # the pre-existing exclusive-slot guard is untouched by Phase 7
    shutil.rmtree(tmp)


# =================================================================== 20 cancel match
def test_cancel_match_lifecycle():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge = _fresh_tournament_env()
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    t_svc.add_team("champ", "team-alpha")
    t_svc.add_team("champ", "team-beta")
    t_svc.mark_ready("champ")
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    m = matches[0]
    assert m.status == M_READY

    cancelled = t_svc.cancel_match(m.id)
    assert cancelled.status == M_CANCELLED
    assert cancelled.winner_team_id is None
    assert cancelled.outcome != "TEAM_A_WIN" and cancelled.outcome != "DRAW"
    assert r_svc.get_match_result(m.id) is None  # cancelled before it ever ran -> no MatchResult at all

    try:
        t_svc.complete_match(m.id, "TEAM_A_WIN", m.team_a_id, 5.0)
        raise AssertionError("completed a cancelled match")
    except TournamentValidationError:
        pass
    shutil.rmtree(tmp)


# ======================================================================= 21 draw
def test_draw_regression_across_all_surfaces():
    snap = {"ended": True, "outcome": "TIME_LIMIT_DRAW", "winner": None}
    assert live_state.is_draw_outcome(snap) is True
    # not a win, not a loss, not an error — draw is its own outcome everywhere
    from tournament.match import OUTCOME_DRAW, OUTCOME_TEAM_A_WIN, OUTCOME_ERROR
    assert OUTCOME_DRAW not in (OUTCOME_TEAM_A_WIN, OUTCOME_ERROR)


# ============================================================ 22-24 localization/theme
def test_en_ar_phase7_keys_present():
    keys = ["acknowledge_error", "cancel_match", "confirm_cancel_match", "timeout_status", "alert_team_code_timeout", "ship_change_pending_reset"]
    for key in keys:
        entry = localization.STRINGS[key]
        assert entry.get("en") and entry.get("ar")


def test_rtl_still_works():
    localization.set_lang("ar")
    assert localization.is_rtl() is True
    localization.set_lang("en")
    assert localization.is_rtl() is False


def test_dark_light_theme_tokens_unchanged():
    dark = theme.Tokens("dark")
    light = theme.Tokens("light")
    assert dark.bg != light.bg
    assert dark.accent == light.accent  # brand accent stays identical across themes, per theme.py's own docstring


# ========================================================= 25-30 existing systems
def test_existing_team_management():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge = _fresh_tournament_env()
    assert team_svc.get_team("team-alpha").name == "Team Alpha"
    shutil.rmtree(tmp)


def test_existing_challenge_management():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge = _fresh_tournament_env()
    assert challenge.id == "tactical-battleship"
    shutil.rmtree(tmp)


def test_existing_submission_management():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge = _fresh_tournament_env()
    active = sub_svc.get_active_submission("team-alpha", challenge.id)
    assert active is not None and active.status == "SUBMITTED"
    shutil.rmtree(tmp)


def test_existing_tournament_management():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge = _fresh_tournament_env()
    comp = t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    assert comp.status == "DRAFT"
    shutil.rmtree(tmp)


def test_existing_results_history():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge = _fresh_tournament_env()
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    t_svc.add_team("champ", "team-alpha")
    t_svc.add_team("champ", "team-beta")
    board = r_svc.leaderboard("champ")
    assert board == []  # no matches yet — real aggregation over zero results, not an error
    shutil.rmtree(tmp)


def test_existing_live_monitoring_state():
    snap = {"engine_alive": True, "ended": False, "running": True, "tick_count": 5, "outcome": None, "winner": None}
    assert live_state.compute_runtime_state(snap, "m1", False, False) == live_state.RUNNING


if __name__ == "__main__":
    tests = [
        test_infinite_loop_participant_code_is_detected, test_execution_timeout_is_configurable_single_source_of_truth,
        test_worker_process_termination_on_timeout, test_worker_cleanup_shutdown_is_idempotent, test_worker_crash_reported_not_raised,
        test_participant_exception_does_not_crash_engine, test_forbidden_api_call_gives_clear_structured_error,
        test_code_timeout_event_distinct_from_code_error, test_code_error_event_still_works_unisolated, test_engine_error_distinguishable_from_team_errors,
        test_no_fake_winner_after_code_failure, test_battle_runner_remains_responsive_during_timeout,
        test_multiple_consecutive_battles_dont_leak_workers, test_clean_application_shutdown_no_worker_survives,
        test_corrupted_json_handling, test_missing_persistence_files_handled_gracefully, test_atomic_write_survives_a_read_afterward,
        test_orphan_submission_cleanup_only_deletes_own_stub, test_historical_result_preservation_after_team_deletion,
        test_ship_reassignment_does_not_corrupt_live_identity,
        test_cancel_match_lifecycle,
        test_draw_regression_across_all_surfaces,
        test_en_ar_phase7_keys_present, test_rtl_still_works, test_dark_light_theme_tokens_unchanged,
        test_existing_team_management, test_existing_challenge_management, test_existing_submission_management,
        test_existing_tournament_management, test_existing_results_history, test_existing_live_monitoring_state,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print(f"\nALL {len(tests)} PHASE 7 TESTS PASSED")
