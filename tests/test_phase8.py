"""Automated tests for Phase 8 (Production Polish, UX Completion & Final
Backlog Closure). Real BattleEngine/BattleRunner/DecideWorker subprocesses
(no Tk — none of the UI classes exercised here need a display). Run with:

    python tests/test_phase8.py
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
from engine.battle import BattleEngine
from engine.config import BattleConfig
from engine.runner import BattleRunner
from results.result_repository import ResultRepository
from results.result_service import ResultService
from roster.team_repository import TeamRepository
from roster.team_service import TeamService
from submissions.submission_repository import SubmissionRepository
from submissions.submission_service import SubmissionService, ValidationError as SubValidationError
from submissions.submission import TEST_PASSED, TEST_FAILED, TEST_TIMEOUT, TEST_ERROR
from submissions.test_runner import run_test
from tournament.competition import ValidationError as TournamentValidationError
from tournament.match import OUTCOME_TEAM_A_WIN
from tournament.round import TYPE_SINGLE_ELIMINATION, TYPE_ROUND_ROBIN, STATUS_COMPLETED as R_COMPLETED
from tournament.tournament_repository import TournamentRepository
from tournament.tournament_service import TournamentService
from ui import live_state, localization, status_style

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
RUNTIME_ERROR_CODE = """
def decide(friendly, enemies, api):
    x = 1 / 0
"""
SYNTAX_ERROR_CODE = """
def decide(friendly, enemies, api):
    import os
"""
PASSIVE_CODE = """
def decide(friendly, enemies, api):
    api["hold_position"]()
"""


def _fresh_tournament_env(n_teams=2):
    tmp = tempfile.mkdtemp(prefix="battleship_phase8_test_")
    team_repo = TeamRepository(os.path.join(tmp, "teams.json"))
    team_svc = TeamService(team_repo, os.path.join(tmp, "team_submissions"))
    team_svc.ensure_default_teams(ALPHA_PATH, BETA_PATH)
    extra_names = ["Team Gamma", "Team Delta"]
    extra_ids = ["team-gamma", "team-delta"]
    for i in range(max(0, n_teams - 2)):
        team_svc.create_team(extra_names[i], team_id=extra_ids[i])

    ch_repo = ChallengeRepository(os.path.join(tmp, "challenges.json"))
    ch_svc = ChallengeService(ch_repo)
    ch_svc.ensure_default_challenge()
    challenge = ch_svc.get_active_challenge()

    sub_repo = SubmissionRepository(os.path.join(tmp, "submissions.json"))
    sub_svc = SubmissionService(sub_repo, team_svc, ch_svc)
    all_ids = ["team-alpha", "team-beta"] + extra_ids[:max(0, n_teams - 2)]
    for tid in all_ids[:n_teams]:
        sub = sub_svc.create_draft(tid, challenge.id, AGGRESSIVE_CODE)
        sub_svc.submit_submission(sub.id)

    t_repo = TournamentRepository(os.path.join(tmp, "tournament"))
    r_repo = ResultRepository(os.path.join(tmp, "results"))
    t_svc = TournamentService(t_repo, team_svc, ch_svc, sub_svc)
    r_svc = ResultService(r_repo, t_svc, team_svc, ch_svc, sub_svc)
    t_svc.result_service = r_svc

    return tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, all_ids[:n_teams]


# ==================================================== 1-7 submission Test isolation (BACKLOG #16)
def test_submission_test_normal_success():
    result = run_test(AGGRESSIVE_CODE, BattleConfig(code_execution_timeout=2.0))
    assert result.status == TEST_PASSED
    assert result.passed is True


def test_submission_test_normal_failure():
    # A passive candidate that never fights back reliably loses to the
    # built-in aggressive test opponent before any time cap matters.
    result = run_test(PASSIVE_CODE, BattleConfig(code_execution_timeout=2.0))
    assert result.status == TEST_FAILED
    assert result.passed is False


def test_submission_test_syntax_validation_error():
    result = run_test(SYNTAX_ERROR_CODE, BattleConfig())
    assert result.status == TEST_ERROR
    assert result.passed is False
    assert result.errors  # a concrete message, not silence


def test_submission_test_runtime_error_is_distinct_from_timeout():
    result = run_test(RUNTIME_ERROR_CODE, BattleConfig(code_execution_timeout=1.5))
    assert result.status == TEST_ERROR
    assert result.status != TEST_TIMEOUT
    assert "division" in result.errors[0] or "error" in result.errors[0].lower()


def test_submission_test_timeout_detected_and_never_a_pass():
    start = time.perf_counter()
    result = run_test(HANG_CODE, BattleConfig(code_execution_timeout=0.6))
    elapsed = time.perf_counter() - start
    assert result.status == TEST_TIMEOUT
    assert result.passed is False  # a timeout must never be interpreted as a valid submission
    assert elapsed < 10.0  # detected promptly, not stuck for the full sim-time cap


def test_submission_test_worker_cleanup_after_timeout_no_leak():
    import multiprocessing as mp
    before = len(mp.active_children())
    run_test(HANG_CODE, BattleConfig(code_execution_timeout=0.5))
    after = len(mp.active_children())
    assert after <= before  # the throwaway engine's workers must not outlive run_test()


def test_submission_test_repeated_timeout_stays_responsive():
    start = time.perf_counter()
    for _ in range(3):
        result = run_test(HANG_CODE, BattleConfig(code_execution_timeout=0.4))
        assert result.status == TEST_TIMEOUT
    assert time.perf_counter() - start < 15.0  # three consecutive hangs never compound into a stall


def test_submission_service_timeout_never_creates_eligible_submission():
    # code_execution_timeout is a BattleConfig-only field (not exposed via
    # Challenge/Rules — a pre-existing, unchanged boundary), so this uses
    # the real default (2.0s) rather than trying to configure a faster one.
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _fresh_tournament_env()
    sub = sub_svc.create_draft("team-alpha", challenge.id, HANG_CODE)
    result = sub_svc.test_submission(sub.id)
    assert result.status == TEST_TIMEOUT
    try:
        sub_svc.submit_submission(sub.id)
        raise AssertionError("a timed-out submission must never be submittable")
    except SubValidationError as e:
        assert str(e) == "test_failed"
    shutil.rmtree(tmp)


# ==================================================== 8-11 PREPARING / worker startup UX (BACKLOG #17)
def test_preparing_state_computed_when_flag_set():
    assert live_state.compute_runtime_state(None, "m1", False, False, preparing=True) == live_state.PREPARING


def test_preparing_takes_precedence_over_stale_snapshot():
    stale_snap = {"engine_alive": True, "ended": True, "running": False, "tick_count": 40, "outcome": "DESTROY_ENEMY", "winner": "Team X"}
    assert live_state.compute_runtime_state(stale_snap, "m1", False, False, preparing=True) == live_state.PREPARING


def test_preparing_defaults_to_false_unchanged_behavior():
    snap = {"engine_alive": True, "ended": False, "running": True, "tick_count": 5, "outcome": None, "winner": None}
    assert live_state.compute_runtime_state(snap, "m1", False, False) == live_state.RUNNING


def test_worker_health_reports_dead_worker_immediately():
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE, isolate_execution=True)
    runner = BattleRunner(engine, tick_hz=30)
    health = runner.worker_health()
    assert health == {"alpha": False, "beta": False}  # both started cleanly
    engine._workers["alpha"].dead = True  # simulate a startup failure
    health = runner.worker_health()
    assert health["alpha"] is True
    engine.shutdown_workers()


def test_worker_health_empty_when_not_isolated():
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE, isolate_execution=False)
    runner = BattleRunner(engine, tick_hz=30)
    assert runner.worker_health() == {}


# ==================================================== 12-14 Team Performance (BACKLOG #13)
def test_team_performance_reports_errors_competitions_score():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _fresh_tournament_env(n_teams=2)
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    for tid in ids:
        t_svc.add_team("champ", tid)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    m = matches[0]
    t_svc.prepare_match_for_start(m.id)
    completed = t_svc.complete_match(m.id, OUTCOME_TEAM_A_WIN, m.team_a_id, 8.0)
    r_svc.record_from_match(completed, {
        "team_a_hp_remaining": 40.0, "team_b_hp_remaining": 0.0,
        "team_a_damage_dealt": 120.0, "team_b_damage_dealt": 10.0,
        "team_a_damage_received": 10.0, "team_b_damage_received": 120.0,
    }, [])
    perf = r_svc.team_performance(m.team_a_id)
    assert perf["wins"] == 1 and perf["losses"] == 0
    assert perf["errors"] == 0
    assert perf["competitions"] == 1
    assert perf["score"] == 50 + 120  # TeamRecord.score formula, reused verbatim
    shutil.rmtree(tmp)


def test_team_performance_counts_errors_without_polluting_win_rate():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _fresh_tournament_env(n_teams=2)
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    for tid in ids:
        t_svc.add_team("champ", tid)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    m = matches[0]
    t_svc.prepare_match_for_start(m.id)
    errored = t_svc.error_match(m.id, "engine_fault", duration=3.0)
    r_svc.record_from_match(errored, None, [])
    perf = r_svc.team_performance(m.team_a_id)
    assert perf["played"] == 0  # ERROR is not a real battle result — unchanged Phase 5 rule
    assert perf["errors"] == 1  # but it IS visible for the profile
    assert perf["win_rate"] == 0.0
    shutil.rmtree(tmp)


def test_team_performance_historical_survives_team_rename():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _fresh_tournament_env(n_teams=2)
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    for tid in ids:
        t_svc.add_team("champ", tid)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    m = matches[0]
    t_svc.prepare_match_for_start(m.id)
    completed = t_svc.complete_match(m.id, OUTCOME_TEAM_A_WIN, m.team_a_id, 5.0)
    result = r_svc.record_from_match(completed, {
        "team_a_hp_remaining": 10.0, "team_b_hp_remaining": 0.0,
        "team_a_damage_dealt": 50.0, "team_b_damage_dealt": 0.0,
        "team_a_damage_received": 0.0, "team_b_damage_received": 50.0,
    }, [])
    original_snapshot_name = result.team_a_name_at_match
    team_svc.update_team(m.team_a_id, name="Renamed Squad")
    reread = r_svc.get_match_result(m.id)
    assert reread.team_a_name_at_match == original_snapshot_name  # immutable snapshot, never mutated
    # team_performance()'s "team_name" is derived from the historical
    # snapshot too (deliberate — see result_service.py's docstring: never
    # mutate historical records). Current identity is what TeamService
    # itself reports, checked separately here.
    perf = r_svc.team_performance(m.team_a_id)
    assert perf["team_name"] == original_snapshot_name
    assert team_svc.get_team(m.team_a_id).name == "Renamed Squad"
    shutil.rmtree(tmp)


# ==================================================== 15-16 cancelled match policy (BACKLOG #7)
def test_cancelled_match_blocks_single_elimination_advancement():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _fresh_tournament_env(n_teams=4)
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    for tid in ids:
        t_svc.add_team("champ", tid)
    r = t_svc.create_round("champ", "Round 1", TYPE_SINGLE_ELIMINATION)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    matches = t_svc.generate_single_elimination(r.id)
    assert len(matches) == 2
    m0, m1 = matches
    t_svc.cancel_match(m0.id)
    t_svc.prepare_match_for_start(m1.id)
    t_svc.complete_match(m1.id, OUTCOME_TEAM_A_WIN, m1.team_a_id, 5.0)
    round_after = t_svc.get_round(r.id)
    assert round_after.status != R_COMPLETED  # blocked, not silently resolved
    assert len(t_svc.get_competition_rounds("champ")) == 1  # no bogus next round / champion
    shutil.rmtree(tmp)


def test_cancelled_match_round_robin_still_completes():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _fresh_tournament_env(n_teams=3)
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    for tid in ids:
        t_svc.add_team("champ", tid)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    matches = t_svc.generate_round_robin(r.id)
    t_svc.cancel_match(matches[0].id)
    for m in matches[1:]:
        t_svc.prepare_match_for_start(m.id)
        t_svc.complete_match(m.id, OUTCOME_TEAM_A_WIN, m.team_a_id, 4.0)
    assert t_svc.get_round(r.id).status == R_COMPLETED  # round-robin has no bracket to protect
    shutil.rmtree(tmp)


def test_cancelled_match_never_produces_result_or_winner():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _fresh_tournament_env(n_teams=2)
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    for tid in ids:
        t_svc.add_team("champ", tid)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    cancelled = t_svc.cancel_match(matches[0].id)
    assert cancelled.winner_team_id is None
    assert r_svc.get_match_result(matches[0].id) is None
    shutil.rmtree(tmp)


# ==================================================== 17-19 forbidden API UX (BACKLOG #6)
def test_forbidden_api_message_has_team_and_function_name():
    config = BattleConfig(allowed_api=["move_toward", "hold_position", "find_nearest", "distance_to", "log"])
    code = """
def decide(friendly, enemies, api):
    target = api["find_nearest"](enemies)
    if target:
        api["attack"](target)
"""
    engine = BattleEngine(code, BETA_CODE, config=config, team_a_name="Team Alpha")
    engine.start()
    engine.step(1 / 30)
    errors = [e for e in engine.events.all() if e.kind == ev.CODE_ERROR]
    assert errors and errors[0].team == "Team Alpha"
    assert "attack" in errors[0].message

    alerts = live_state.alerts_from_events(errors, "Team Alpha", "Team Beta")
    assert alerts and alerts[0].context["team"] == "Team Alpha"
    assert "attack" in alerts[0].context["message"]


def test_forbidden_api_multiple_functions_each_report_clearly():
    config = BattleConfig(allowed_api=["move_toward", "hold_position", "find_nearest", "distance_to"])
    for forbidden_fn in ("attack", "log"):
        code = f"""
def decide(friendly, enemies, api):
    api["{forbidden_fn}"]()
"""
        engine = BattleEngine(code, BETA_CODE, config=config)
        engine.start()
        engine.step(1 / 30)
        errors = [e for e in engine.events.all() if e.kind == ev.CODE_ERROR]
        assert errors, f"expected a CODE_ERROR for forbidden fn {forbidden_fn}"
        assert forbidden_fn in errors[0].message
        assert "not available" in errors[0].message


def test_forbidden_api_never_fakes_a_winner():
    config = BattleConfig(allowed_api=["move_toward", "hold_position", "find_nearest", "distance_to", "log"])
    code = """
def decide(friendly, enemies, api):
    api["attack"](None)
"""
    engine = BattleEngine(code, BETA_CODE, config=config)
    engine.start()
    for _ in range(10):
        engine.step(1 / 30)
    assert engine.winner != engine.ship_a.team


# ==================================================== 20-21 centralized status vocabulary (Step 8)
def test_status_style_ship_battle_status_draw_priority():
    ship = {"alive": False, "hp_pct": 0.0}
    assert status_style.ship_battle_status(ship, is_draw=True) == "draw"


def test_status_style_ship_battle_status_active_damaged_destroyed():
    assert status_style.ship_battle_status({"alive": True, "hp_pct": 0.9}) == "active"
    assert status_style.ship_battle_status({"alive": True, "hp_pct": 0.3}) == "damaged"
    assert status_style.ship_battle_status({"alive": False, "hp_pct": 0.0}) == "destroyed"


def test_status_style_tables_cover_every_state():
    for state in live_state.RUNTIME_STATES:
        assert state in status_style.RUNTIME_STATE_LABEL_KEY
        assert state in status_style.RUNTIME_STATE_COLOR_ATTR
    from roster.team import STATUS_READY, STATUS_IN_BATTLE, STATUS_DISABLED, STATUS_NOT_READY
    for state in (STATUS_READY, STATUS_IN_BATTLE, STATUS_DISABLED, STATUS_NOT_READY):
        assert state in status_style.TEAM_STATUS_LABEL_KEY
        assert state in status_style.TEAM_STATUS_COLOR_ATTR


# ==================================================== 22 data integrity / startup crash handling (Step 9/10)
def test_corrupted_json_raises_typed_error_not_raw_exception():
    from storage import CorruptedDataError, write_json_file_atomic
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "teams.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json!!")
    try:
        TeamRepository(path).get_all_teams()
        raise AssertionError("corrupted JSON must raise CorruptedDataError, not silently succeed")
    except CorruptedDataError:
        pass
    shutil.rmtree(tmp)


def test_app_main_shows_controlled_dialog_not_raw_traceback():
    """main() must never let CorruptedDataError propagate as an unhandled
    exception — it should be caught and turned into a controlled exit."""
    import ui.app as appmod
    from storage import CorruptedDataError as CDE

    class FakeApp:
        def __init__(self):
            raise CDE("data/teams.json is corrupted or unreadable: test")

    original_app = appmod.App
    original_showerror = appmod.messagebox.showerror
    calls = []
    appmod.App = FakeApp
    appmod.messagebox.showerror = lambda *a, **k: calls.append((a, k))
    try:
        try:
            appmod.main()
            raised_system_exit = False
        except SystemExit:
            raised_system_exit = True
        assert raised_system_exit
        assert len(calls) == 1  # a real dialog was shown, not a swallowed/raw crash
    finally:
        appmod.App = original_app
        appmod.messagebox.showerror = original_showerror


# ==================================================== 23-24 EN/AR + regression
def test_en_ar_phase8_keys_present():
    keys = [
        "test_timeout", "test_error", "preparing_workers_message", "worker_start_failed",
        "team_performance_title", "team_id_label", "assigned_ship", "performance_stats",
        "pending_next_battle", "not_built_yet", "startup_corrupted_data_title",
        "startup_corrupted_data_body", "test_runner_internal_error",
    ]
    for key in keys:
        entry = localization.STRINGS.get(key)
        assert entry is not None, f"missing localization key: {key}"
        assert entry.get("en") and entry.get("ar"), f"key {key} missing en or ar text"


def test_existing_engine_tests_still_pass():
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE)
    engine.start()
    for _ in range(30 * 30):
        engine.step(1 / 30)
        if engine.winner:
            break
    assert engine.winner is not None


def test_existing_tournament_and_results_still_pass():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _fresh_tournament_env()
    comp = t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    assert comp.status == "DRAFT"
    board = r_svc.leaderboard("champ")
    assert board == []
    shutil.rmtree(tmp)


if __name__ == "__main__":
    tests = [
        test_submission_test_normal_success, test_submission_test_normal_failure,
        test_submission_test_syntax_validation_error, test_submission_test_runtime_error_is_distinct_from_timeout,
        test_submission_test_timeout_detected_and_never_a_pass, test_submission_test_worker_cleanup_after_timeout_no_leak,
        test_submission_test_repeated_timeout_stays_responsive, test_submission_service_timeout_never_creates_eligible_submission,
        test_preparing_state_computed_when_flag_set, test_preparing_takes_precedence_over_stale_snapshot,
        test_preparing_defaults_to_false_unchanged_behavior, test_worker_health_reports_dead_worker_immediately,
        test_worker_health_empty_when_not_isolated,
        test_team_performance_reports_errors_competitions_score, test_team_performance_counts_errors_without_polluting_win_rate,
        test_team_performance_historical_survives_team_rename,
        test_cancelled_match_blocks_single_elimination_advancement, test_cancelled_match_round_robin_still_completes,
        test_cancelled_match_never_produces_result_or_winner,
        test_forbidden_api_message_has_team_and_function_name, test_forbidden_api_multiple_functions_each_report_clearly,
        test_forbidden_api_never_fakes_a_winner,
        test_status_style_ship_battle_status_draw_priority, test_status_style_ship_battle_status_active_damaged_destroyed,
        test_status_style_tables_cover_every_state,
        test_corrupted_json_raises_typed_error_not_raw_exception, test_app_main_shows_controlled_dialog_not_raw_traceback,
        test_en_ar_phase8_keys_present,
        test_existing_engine_tests_still_pass, test_existing_tournament_and_results_still_pass,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print(f"\nALL {len(tests)} PHASE 8 TESTS PASSED")
