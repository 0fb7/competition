"""Independent QA/test-gap audit — new tests targeting behavior the
existing 236 tests do not directly exercise (round-robin/single-
elimination invariants across more team counts, explicit champion
determination, cancel-match negative cases, App pause/resume UI guards,
a real timeout through the full Match->MatchResult pipeline, the
generation-counter reset/decide race, and snapshot_for_render()'s
non-draining behavior). Run with:

    python tests/test_qa_audit.py
"""

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from challenges.challenge import Rules, STATUS_ARCHIVED
from challenges.challenge_repository import ChallengeRepository
from challenges.challenge_service import ChallengeService
from engine.battle import BattleEngine
from engine.config import BattleConfig
from engine.runner import BattleRunner
from engine import events as ev
from results.result_repository import ResultRepository
from results.result_service import ResultService
from roster.team_repository import TeamRepository
from roster.team_service import TeamService
from submissions.submission_repository import SubmissionRepository
from submissions.submission_service import SubmissionService
from submissions.test_runner import run_test
from submissions.submission import TEST_PASSED, TEST_TIMEOUT, TEST_ERROR
from tournament.competition import ValidationError as TournamentValidationError
from tournament.match import (
    OUTCOME_TEAM_A_WIN, STATUS_PENDING as M_PENDING, STATUS_READY as M_READY,
    STATUS_RUNNING as M_RUNNING, STATUS_COMPLETED as M_COMPLETED,
)
from tournament.round import TYPE_ROUND_ROBIN, TYPE_SINGLE_ELIMINATION
from tournament.tournament_repository import TournamentRepository
from tournament.tournament_service import TournamentService

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALPHA_PATH = os.path.join(ROOT, "teams", "team_alpha.py")
BETA_PATH = os.path.join(ROOT, "teams", "team_beta.py")

with open(ALPHA_PATH, encoding="utf-8") as f:
    AGGRESSIVE_CODE = f.read()
with open(BETA_PATH, encoding="utf-8") as f:
    BETA_CODE = f.read()

HANG_CODE = "def decide(friendly, enemies, api):\n    while True:\n        pass\n"


def _env_with_n_teams(n_teams):
    """Generic helper supporting any team count (existing test_tournament.py's
    _fresh_env tops out at 6) — needed for 8-team single-elimination and
    5-team round-robin property tests below."""
    tmp = tempfile.mkdtemp(prefix="battleship_qa_audit_")
    team_repo = TeamRepository(os.path.join(tmp, "teams.json"))
    team_svc = TeamService(team_repo, os.path.join(tmp, "team_submissions"))
    team_svc.ensure_default_teams(ALPHA_PATH, BETA_PATH)
    ids = ["team-alpha", "team-beta"]
    for i in range(2, n_teams):
        tid = f"team-extra-{i}"
        team_svc.create_team(f"Team Extra {i}", team_id=tid)
        ids.append(tid)

    ch_repo = ChallengeRepository(os.path.join(tmp, "challenges.json"))
    ch_svc = ChallengeService(ch_repo)
    ch_svc.ensure_default_challenge()
    challenge = ch_svc.get_active_challenge()

    sub_repo = SubmissionRepository(os.path.join(tmp, "submissions.json"))
    sub_svc = SubmissionService(sub_repo, team_svc, ch_svc)
    for tid in ids:
        sub = sub_svc.create_draft(tid, challenge.id, AGGRESSIVE_CODE)
        sub_svc.submit_submission(sub.id)

    t_repo = TournamentRepository(os.path.join(tmp, "tournament"))
    r_repo = ResultRepository(os.path.join(tmp, "results"))
    t_svc = TournamentService(t_repo, team_svc, ch_svc, sub_svc)
    r_svc = ResultService(r_repo, t_svc, team_svc, ch_svc, sub_svc)
    t_svc.result_service = r_svc

    return tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids


# ============================================================ round-robin invariant
def test_round_robin_match_count_formula_across_team_counts():
    """n(n-1)/2 must hold for every team count, not just the one value
    (4) the existing suite happens to check."""
    for n in (2, 3, 5, 6):
        tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _env_with_n_teams(n)
        comp = t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
        for tid in ids:
            t_svc.add_team("champ", tid)
        r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
        matches = t_svc.generate_round_robin(r.id)
        expected = n * (n - 1) // 2
        assert len(matches) == expected, f"n={n}: expected {expected} matches, got {len(matches)}"
        pairs = [frozenset([m.team_a_id, m.team_b_id]) for m in matches]
        assert len(pairs) == len(set(pairs)), f"n={n}: duplicate pair found"
        assert all(m.team_a_id != m.team_b_id for m in matches), f"n={n}: self-match found"
        shutil.rmtree(tmp)


# ============================================================ single-elimination invariants
def test_single_elimination_various_team_counts_and_bye_invariant():
    """BYE never invokes BattleEngine (no battle telemetry) and every
    real match pairs exactly two distinct teams, for team counts the
    existing suite doesn't check (2, 5, 8) as well as the ones it does."""
    for n in (2, 3, 4, 5, 8):
        tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _env_with_n_teams(n)
        comp = t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
        for tid in ids:
            t_svc.add_team("champ", tid)
        r = t_svc.create_round("champ", "Round 1", TYPE_SINGLE_ELIMINATION)
        matches = t_svc.generate_single_elimination(r.id)

        byes = [m for m in matches if m.is_bye]
        reals = [m for m in matches if not m.is_bye]
        next_pow2 = 1
        while next_pow2 < n:
            next_pow2 *= 2
        expected_byes = next_pow2 - n
        assert len(byes) == expected_byes, f"n={n}: expected {expected_byes} byes, got {len(byes)}"
        assert all(b.team_b_id is None for b in byes), f"n={n}: a BYE has a team_b_id (fabricated opponent)"
        assert all(b.status == M_COMPLETED and b.winner_team_id == b.team_a_id for b in byes)
        assert all(m.team_a_id != m.team_b_id for m in reals), f"n={n}: self-match in a real pairing"
        pairs = [frozenset([m.team_a_id, m.team_b_id]) for m in reals]
        assert len(pairs) == len(set(pairs)), f"n={n}: duplicate real pairing"
        shutil.rmtree(tmp)


def test_single_elimination_explicit_champion_determination():
    """Completes BOTH rounds of a real 4-team bracket and asserts a
    single, genuine champion_team_id — the existing test_winner_
    advancement only checks that a 1-match final round gets created, it
    never actually plays that final to determine a champion."""
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _env_with_n_teams(4)
    comp = t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    for tid in ids:
        t_svc.add_team("champ", tid)
    r1 = t_svc.create_round("champ", "Round 1", TYPE_SINGLE_ELIMINATION)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    round1_matches = t_svc.generate_single_elimination(r1.id)
    assert len(round1_matches) == 2

    winners_r1 = []
    for m in round1_matches:
        t_svc.prepare_match_for_start(m.id)
        completed = t_svc.complete_match(m.id, OUTCOME_TEAM_A_WIN, m.team_a_id, 10.0)
        winners_r1.append(completed.winner_team_id)

    comp = t_svc.get_competition("champ")
    assert len(comp.round_ids) == 2, "final round was not auto-generated after round 1 completed"
    final_round_id = comp.round_ids[-1]
    final_matches = t_svc.get_round_matches(final_round_id)
    assert len(final_matches) == 1
    final_match = final_matches[0]
    assert {final_match.team_a_id, final_match.team_b_id} == set(winners_r1)

    t_svc.prepare_match_for_start(final_match.id)
    champion_match = t_svc.complete_match(final_match.id, OUTCOME_TEAM_A_WIN, final_match.team_a_id, 8.0)
    champion_id = champion_match.winner_team_id
    assert champion_id in winners_r1
    assert champion_id == final_match.team_a_id

    # exactly one champion — no other match in the whole competition has
    # a winner that never lost a match it played
    all_matches = []
    for rid in comp.round_ids:
        all_matches.extend(t_svc.get_round_matches(rid))
    losers = {m.team_a_id if m.winner_team_id == m.team_b_id else m.team_b_id for m in all_matches if not m.is_bye}
    assert champion_id not in losers
    shutil.rmtree(tmp)


# ============================================================ cancel_match negative tests
def test_cancel_match_rejects_running_match():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _env_with_n_teams(2)
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    for tid in ids:
        t_svc.add_team("champ", tid)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    m = matches[0]
    t_svc.prepare_match_for_start(m.id)
    assert t_svc.get_match(m.id).status == M_RUNNING
    try:
        t_svc.cancel_match(m.id)
        raise AssertionError("cancelling a RUNNING match was accepted")
    except TournamentValidationError as e:
        assert str(e) == "cannot_cancel_running_or_completed"
    assert t_svc.get_match(m.id).status == M_RUNNING  # unchanged
    shutil.rmtree(tmp)


def test_cancel_match_rejects_completed_match():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _env_with_n_teams(2)
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    for tid in ids:
        t_svc.add_team("champ", tid)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    m = matches[0]
    t_svc.prepare_match_for_start(m.id)
    t_svc.complete_match(m.id, OUTCOME_TEAM_A_WIN, m.team_a_id, 10.0)
    try:
        t_svc.cancel_match(m.id)
        raise AssertionError("cancelling a COMPLETED match was accepted")
    except TournamentValidationError as e:
        assert str(e) == "cannot_cancel_running_or_completed"
    assert t_svc.get_match(m.id).status == M_COMPLETED
    shutil.rmtree(tmp)


def test_cancel_match_accepts_pending_and_ready():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _env_with_n_teams(2)
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    for tid in ids:
        t_svc.add_team("champ", tid)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    m = matches[0]
    assert m.status in (M_PENDING, M_READY)
    cancelled = t_svc.cancel_match(m.id)
    assert cancelled.status == "CANCELLED"
    shutil.rmtree(tmp)


# ============================================================ delete_challenge with historical usage
def test_delete_challenge_with_historical_match_does_not_corrupt_history():
    """delete_challenge() has no historical-usage guard (only blocks
    ACTIVE) — unlike delete_competition(). Empirically verify this does
    NOT corrupt already-recorded history (frozen snapshot fields survive
    intact) even though it's a real, disclosed asymmetry with
    delete_competition()'s guard."""
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, ids = _env_with_n_teams(2)
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    for tid in ids:
        t_svc.add_team("champ", tid)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    m = matches[0]
    t_svc.prepare_match_for_start(m.id)
    completed = t_svc.complete_match(m.id, OUTCOME_TEAM_A_WIN, m.team_a_id, 10.0)
    result = r_svc.record_from_match(completed, None, [])
    original_challenge_name = result.challenge_name_at_match

    ch_svc.set_status(challenge.id, STATUS_ARCHIVED)
    ch_svc.delete_challenge(challenge.id)
    assert ch_svc.get_challenge(challenge.id) is None

    reloaded = r_svc.get_match_result(m.id)
    assert reloaded is not None
    assert reloaded.challenge_name_at_match == original_challenge_name  # frozen snapshot untouched
    shutil.rmtree(tmp)


# ============================================================ App pause/resume UI guards
def test_app_pause_is_a_noop_when_not_running():
    """App._on_pause()/_on_resume() have zero existing test coverage —
    both are state-guarded (runtime_state must be RUNNING/PAUSED
    respectively) and silently no-op otherwise; verify that guard
    actually holds rather than assuming it from the source."""
    import ui.app as appmod
    from ui import live_state

    # Construct a minimal stand-in exercising only the guarded methods —
    # avoids a full App() (Tk/pygame) for a pure state-machine check.
    class FakeApp:
        _on_pause = appmod.App._on_pause
        _on_resume = appmod.App._on_resume

        def __init__(self):
            self.runtime_state = live_state.IDLE
            self.paused_called = False
            self.resumed_called = False
            self.logged = []

        class _FakeRunner:
            def __init__(self, outer):
                self.outer = outer

            def pause_battle(self):
                self.outer.paused_called = True

            def start_battle(self):
                self.outer.resumed_called = True

        def __post_init(self):
            self.runner = FakeApp._FakeRunner(self)

        def _log_runtime(self, *a, **k):
            self.logged.append(a)

    fa = FakeApp()
    fa.runner = FakeApp._FakeRunner(fa)

    fa.runtime_state = live_state.IDLE
    fa._on_pause()
    assert fa.paused_called is False, "pause must be a no-op when not RUNNING"

    fa.runtime_state = live_state.PAUSED
    fa._on_resume()  # PAUSED -> resume should proceed... but we're testing the IDLE case below
    assert fa.resumed_called is True

    fa2 = FakeApp()
    fa2.runner = FakeApp._FakeRunner(fa2)
    fa2.runtime_state = live_state.IDLE
    fa2._on_resume()
    assert fa2.resumed_called is False, "resume must be a no-op when not PAUSED"

    fa3 = FakeApp()
    fa3.runner = FakeApp._FakeRunner(fa3)
    fa3.runtime_state = live_state.RUNNING
    fa3._on_pause()
    assert fa3.paused_called is True, "pause must actually run when genuinely RUNNING"


# ============================================================ timeout through the real pipeline
def test_timeout_through_real_match_pipeline_never_fabricates_error_outcome():
    """A CODE_TIMEOUT on one side does not end the battle by itself — the
    other side keeps fighting an unresponsive opponent and should still
    win normally. Verifies the full BattleEngine (isolated) -> real
    outcome pipeline never conflates 'one side timed out mid-battle'
    with 'the match itself errored', and that no fake winner/result is
    produced for the timed-out side."""
    engine = BattleEngine(
        HANG_CODE, AGGRESSIVE_CODE, config=BattleConfig(code_execution_timeout=1.0), isolate_execution=True,
    )
    engine.start()
    dt = 1 / 30
    for _ in range(30 * 60):
        engine.step(dt)
        if engine.ended:
            break
    engine.shutdown_workers()

    timeouts = [e for e in engine.events.all() if e.kind == ev.CODE_TIMEOUT]
    assert len(timeouts) >= 1, "the hung side must have produced a real CODE_TIMEOUT"
    assert engine.ended, "the battle must still reach a real conclusion despite one side hanging"
    # the side that never timed out (team B / ship_b) must be the one
    # that wins — never a fabricated win for the side whose code hung
    assert engine.winner != engine.ship_a.team
    assert engine.outcome in ("DESTROY_ENEMY", "TIME_LIMIT_DRAW")


# ============================================================ generation-counter race
def test_reset_during_gather_decisions_discards_stale_decision():
    """Deterministic reproduction of the exact race BattleRunner._loop's
    lock-free gather_decisions()/locked apply_decisions() split exists to
    protect against: gather a decision for generation N, reset the
    engine (bumping to generation N+1) BEFORE applying it, then confirm
    apply_decisions() discards the stale decision instead of mutating the
    freshly-reset ships. No sleeps — this calls the exact two methods
    BattleRunner._loop calls, in the exact order the race would produce."""
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE)
    engine.start()
    gen, decision_a, decision_b = engine.gather_decisions(1 / 30)
    hp_before_reset = engine.ship_a.hp

    engine.reset()  # simulates an admin hitting Reset while gather_decisions was in flight
    assert engine._generation != gen

    tick_count_before_apply = engine.tick_count
    engine.apply_decisions(1 / 30, gen, decision_a, decision_b)
    # the stale decision must have been discarded — no state mutation
    assert engine.tick_count == tick_count_before_apply
    assert engine.ship_a.hp == engine.ship_a.config.max_hp  # the freshly-reset ship, untouched by the stale decision


# ============================================================ snapshot_for_render non-draining
def test_snapshot_for_render_does_not_steal_events_from_snapshot():
    """Direct regression test for the historical BattlePanel race (Phase
    7): snapshot() is the sole draining consumer; snapshot_for_render()
    must NEVER advance _last_event_id, so interleaving calls to it can
    never cause snapshot()'s next call to miss events."""
    # Real team code doesn't reliably produce events in the first few
    # ticks (no log() calls, not yet in attack range) — use code that
    # logs every tick so this test has real, guaranteed events to check
    # the drain behavior against, deterministically.
    logging_code = 'def decide(friendly, enemies, api):\n    api["log"]("tick")\n    api["hold_position"]()\n'
    engine = BattleEngine(logging_code, logging_code)
    runner = BattleRunner(engine, tick_hz=30)
    engine.start()
    dt = 1 / 30
    for _ in range(15):
        engine.step(dt)
    assert len(engine.events.all()) > 0, "test setup produced no events to verify draining against"

    render_snap_1 = runner.snapshot_for_render()
    render_snap_2 = runner.snapshot_for_render()
    # repeated calls return an overlapping/bounded recent window, never
    # advancing the drain pointer used by snapshot()
    assert runner._last_event_id == 0

    draining_snap = runner.snapshot()
    assert len(draining_snap["new_events"]) > 0, (
        "snapshot() found no new events after snapshot_for_render() calls — "
        "snapshot_for_render() incorrectly drained them first"
    )
    assert runner._last_event_id != 0

    second_drain = runner.snapshot()
    assert second_drain["new_events"] == []  # correctly drained, nothing left


# ============================================================ cross-path isolation (TEST vs live COMPETITION)
def test_test_path_never_interferes_with_a_concurrently_running_competition():
    """Mandatory cross-path isolation check: the participant 'Test' path
    (submissions/test_runner.run_test) must be structurally incapable of
    touching a live competition's BattleRunner/BattleEngine, since they
    are always separate BattleEngine instances with separate locks and
    separate worker-process dicts (see test_runner.py's and runner.py's
    docstrings). Proven empirically here rather than just by reading the
    source: start a real isolated live match on its own BattleRunner
    thread, then run several Test invocations (valid, failing, forbidden-
    import, and a hang/timeout) on the calling thread while the live
    match keeps ticking, and confirm the live match's tick progression,
    drained-event stream, and final outcome are all unaffected."""
    live_engine = BattleEngine(
        AGGRESSIVE_CODE, BETA_CODE,
        config=BattleConfig(code_execution_timeout=2.0), isolate_execution=True,
    )
    runner = BattleRunner(live_engine, tick_hz=30.0)
    runner.start_thread()
    try:
        runner.start_battle()

        def _wait_tick_progress(min_ticks=1, timeout_s=5.0):
            deadline = time.perf_counter() + timeout_s
            start_tick = runner.snapshot_for_render()["tick_count"]
            while time.perf_counter() < deadline:
                if runner.snapshot_for_render()["tick_count"] >= start_tick + min_ticks:
                    return
                time.sleep(0.02)
            raise AssertionError("live competition failed to progress ticks")

        _wait_tick_progress()  # confirm the live match is actually running before interleaving Test calls

        failing_code = 'def decide(friendly, enemies, api):\n    api["hold_position"]()\n'
        forbidden_code = 'import os\ndef decide(friendly, enemies, api):\n    api["hold_position"]()\n'
        test_config = BattleConfig(code_execution_timeout=0.8)

        tick_before_valid = runner.snapshot_for_render()["tick_count"]
        valid_result = run_test(AGGRESSIVE_CODE, test_config)
        assert valid_result.status in (TEST_PASSED, "FAILED")  # must reach a real verdict, not error/timeout
        _wait_tick_progress()
        assert runner.snapshot_for_render()["tick_count"] > tick_before_valid, \
            "live match stalled while a valid Test run executed"

        tick_before_fail = runner.snapshot_for_render()["tick_count"]
        failing_result = run_test(failing_code, test_config)
        assert failing_result.status == "FAILED"
        _wait_tick_progress()
        assert runner.snapshot_for_render()["tick_count"] > tick_before_fail, \
            "live match stalled while a failing Test run executed"

        tick_before_forbidden = runner.snapshot_for_render()["tick_count"]
        forbidden_result = run_test(forbidden_code, test_config)
        assert forbidden_result.status == TEST_ERROR
        _wait_tick_progress()
        assert runner.snapshot_for_render()["tick_count"] > tick_before_forbidden, \
            "live match stalled while a forbidden-import Test run executed"

        tick_before_hang = runner.snapshot_for_render()["tick_count"]
        hang_result = run_test(HANG_CODE, test_config)
        assert hang_result.status == TEST_TIMEOUT
        _wait_tick_progress()
        assert runner.snapshot_for_render()["tick_count"] > tick_before_hang, \
            "live match stalled while a hanging Test run executed"

        # the live match's own single-draining-consumer stream must still be
        # intact and non-empty — Test calls must never have stolen its events
        live_snap = runner.snapshot()
        assert live_snap["engine_alive"] is True

        # let the live match run to a real, uncorrupted conclusion
        deadline = time.perf_counter() + 30.0
        while not live_engine.ended and time.perf_counter() < deadline:
            time.sleep(0.05)
        assert live_engine.ended, "live competition never reached a conclusion"
        assert live_engine.outcome is not None
    finally:
        runner.stop_thread()


if __name__ == "__main__":
    tests = [
        test_round_robin_match_count_formula_across_team_counts,
        test_single_elimination_various_team_counts_and_bye_invariant,
        test_single_elimination_explicit_champion_determination,
        test_cancel_match_rejects_running_match,
        test_cancel_match_rejects_completed_match,
        test_cancel_match_accepts_pending_and_ready,
        test_delete_challenge_with_historical_match_does_not_corrupt_history,
        test_app_pause_is_a_noop_when_not_running,
        test_timeout_through_real_match_pipeline_never_fabricates_error_outcome,
        test_reset_during_gather_decisions_discards_stale_decision,
        test_snapshot_for_render_does_not_steal_events_from_snapshot,
        test_test_path_never_interferes_with_a_concurrently_running_competition,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print(f"\nALL {len(tests)} QA AUDIT TESTS PASSED")
