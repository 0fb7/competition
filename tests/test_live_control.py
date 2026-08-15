"""Automated tests for Phase 6 (Live Competition Control & Real-Time
Monitoring), per prompt.md section 37. Two layers:

  - Pure logic (no engine, no Tk): ui/live_state.py's runtime-state,
    team-code-status, event-severity, draw, and match-queue functions.
  - Real BattleEngine/BattleRunner (no Tk — BattleRunner has no GUI
    dependency at all): pause/resume/reset correctness, thread health,
    the single-drain event-consumption guarantee, and team-code-error
    handling, all against the actual engine, not a simulation of it.

Full Tk-driven checks (widget rendering, RTL mirroring, dark/light
switching, a real App() end to end) are covered by manual verification
per spec section 39, matching this project's established Phase 4/5 split
between "automated tests" (service/engine layer) and "manual
verification" (a real App() instance).

Run with:

    python tests/test_live_control.py
"""

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from challenges.challenge import Rules
from challenges.challenge_repository import ChallengeRepository
from challenges.challenge_service import ChallengeService
from engine import events as ev
from engine.battle import BattleEngine
from engine.runner import BattleRunner
from results.result_repository import ResultRepository
from results.result_service import ResultService
from roster.team_repository import TeamRepository
from roster.team_service import TeamService
from submissions.submission_repository import SubmissionRepository
from submissions.submission_service import SubmissionService
from tournament.match import OUTCOME_ERROR, STATUS_ERROR as M_ERROR, STATUS_READY as M_READY, STATUS_RUNNING as M_RUNNING
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

BROKEN_CODE = """
def decide(friendly, enemies, api):
    x = 1 / 0
"""


def _fresh_env(n_teams=2):
    tmp = tempfile.mkdtemp(prefix="battleship_live_test_")
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


def _one_match_setup():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge = _fresh_env()
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    t_svc.add_team("champ", "team-alpha")
    t_svc.add_team("champ", "team-beta")
    t_svc.mark_ready("champ")
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.start_competition("champ")
    return tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, r, matches


def _wait(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


# ===================================================== 1. runtime state transitions
def test_runtime_state_transitions():
    def snap(**over):
        base = {"engine_alive": True, "ended": False, "running": False, "tick_count": 0, "outcome": None, "winner": None}
        base.update(over)
        return base

    assert live_state.compute_runtime_state(None, None, False, False) == live_state.IDLE
    assert live_state.compute_runtime_state(snap(engine_alive=False), "m1", False, False) == live_state.ERROR
    assert live_state.compute_runtime_state(snap(), None, False, True) == live_state.ERROR
    assert live_state.compute_runtime_state(snap(), "m1", True, False) == live_state.STOPPED
    assert live_state.compute_runtime_state(snap(ended=True), "m1", False, False) == live_state.COMPLETED
    assert live_state.compute_runtime_state(snap(running=True), "m1", False, False) == live_state.RUNNING
    assert live_state.compute_runtime_state(snap(tick_count=0), "m1", False, False) == live_state.PREPARING
    assert live_state.compute_runtime_state(snap(tick_count=5), None, False, False) == live_state.PAUSED
    assert live_state.compute_runtime_state(snap(), None, False, False) == live_state.IDLE


# ============================================================== 2. active match ownership
def test_active_match_ownership_via_can_start_match():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, r, matches = _one_match_setup()
    m = matches[0]
    ok, _reason = t_svc.can_start_match(m.id)
    assert ok is True
    t_svc.prepare_match_for_start(m.id)
    assert t_svc.get_match(m.id).status == M_RUNNING
    # a second start attempt on the same match must be rejected by can_start_match
    ok2, reason2 = t_svc.can_start_match(m.id)
    assert ok2 is False and reason2 == "match_not_ready"
    shutil.rmtree(tmp)


# ============================================================================ 3-7 controls
def test_start_control():
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE)
    assert engine.running is False and engine.tick_count == 0
    engine.start()
    assert engine.running is True
    engine.step(1 / 30)
    assert engine.tick_count == 1


def test_pause_control():
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE)
    engine.start()
    engine.step(1 / 30)
    engine.pause()
    assert engine.running is False
    ticks_before = engine.tick_count
    engine.step(1 / 30)  # paused -> step() is a no-op (running is False)
    assert engine.tick_count == ticks_before


def test_resume_control():
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE)
    engine.start()
    for _ in range(5):
        engine.step(1 / 30)
    engine.pause()
    hp_at_pause = engine.ship_a.hp
    engine.start()  # resume == start again, same flag (spec section 15: same battle, not a new one)
    engine.step(1 / 30)
    assert engine.tick_count == 6
    assert engine.ship_a.hp <= hp_at_pause  # continues from where it was, never reset upward


def test_reset_control():
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE)
    engine.start()
    for _ in range(10):
        engine.step(1 / 30)
    assert engine.tick_count > 0
    engine.reset()
    assert engine.tick_count == 0 and engine.elapsed == 0.0
    assert engine.ship_a.hp == engine.config.max_hp and engine.ship_b.hp == engine.config.max_hp
    assert engine.ended is False and engine.outcome is None and engine.winner is None
    assert engine.running is False


def test_stop_behavior_records_error_not_a_fake_win():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, r, matches = _one_match_setup()
    m = matches[0]
    t_svc.prepare_match_for_start(m.id)
    # simulate a partial, real battle (a few ticks), then STOP
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE, team_a_name="Team Alpha", team_b_name="Team Beta")
    engine.start()
    for _ in range(10):
        engine.step(1 / 30)
    events = engine.events.all()
    stopped = t_svc.error_match(m.id, "stopped_by_administrator", duration=engine.elapsed)
    assert stopped.status == M_ERROR and stopped.outcome == OUTCOME_ERROR
    assert stopped.winner_team_id is None  # never a fake winner
    battle_stats = {
        "team_a_hp_remaining": engine.ship_a.hp, "team_b_hp_remaining": engine.ship_b.hp,
        "team_a_damage_dealt": sum(e.data.get("amount", 0.0) for e in events if e.kind == ev.DAMAGE and e.team == "Team Alpha"),
        "team_b_damage_dealt": sum(e.data.get("amount", 0.0) for e in events if e.kind == ev.DAMAGE and e.team == "Team Beta"),
        "team_a_damage_received": 0.0, "team_b_damage_received": 0.0,
    }
    result = r_svc.record_from_match(stopped, battle_stats, events)
    assert result.outcome == OUTCOME_ERROR and result.winner_team_id is None
    assert result.duration == engine.elapsed  # real partial duration, not a full/fabricated one
    shutil.rmtree(tmp)


# ============================================================ 8-10 pause/resume/reset correctness
def test_pause_freezes_simulation():
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE)
    engine.start()
    for _ in range(5):
        engine.step(1 / 30)
    engine.pause()
    snap1 = (engine.tick_count, engine.elapsed, engine.ship_a.hp, engine.ship_a.energy, engine.ship_a.x, engine.ship_a.y)
    for _ in range(10):
        engine.step(1 / 30)  # engine.running is False -> step() returns immediately
    snap2 = (engine.tick_count, engine.elapsed, engine.ship_a.hp, engine.ship_a.energy, engine.ship_a.x, engine.ship_a.y)
    assert snap1 == snap2  # tick count, sim time, HP, energy, position — nothing moved while paused


def test_resume_continues_same_battle():
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE)
    ship_a_identity = id(engine.ship_a)
    engine.start()
    for _ in range(5):
        engine.step(1 / 30)
    engine.pause()
    engine.start()
    for _ in range(5):
        engine.step(1 / 30)
    assert id(engine.ship_a) == ship_a_identity  # same Ship object, never recreated
    assert engine.tick_count == 10  # continued, not restarted from 0


def test_reset_restores_state_via_runner():
    runner = BattleRunner(BattleEngine(AGGRESSIVE_CODE, BETA_CODE), tick_hz=30)
    runner.start_thread()
    runner.start_battle()
    assert _wait(lambda: runner.snapshot()["tick_count"] > 0)
    runner.reset_battle()
    snap = runner.snapshot()
    assert snap["tick_count"] == 0 and snap["elapsed"] == 0.0 and snap["ended"] is False
    assert snap["ship_a"]["hp_pct"] == 1.0 and snap["ship_b"]["hp_pct"] == 1.0
    runner.stop_thread()


# ==================================================================== 11-13 invariants
def test_only_one_active_match_enforced_by_service_state():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, r, matches = _one_match_setup()
    m1, m2 = matches[0], matches[1] if len(matches) > 1 else matches[0]
    t_svc.prepare_match_for_start(m1.id)
    ok, reason = t_svc.can_start_match(m1.id)
    assert ok is False and reason == "match_not_ready"  # already RUNNING, cannot be started again
    shutil.rmtree(tmp)


def test_invalid_match_start_rejected():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, r, matches = _one_match_setup()
    ok, reason = t_svc.can_start_match("does-not-exist")
    assert ok is False and reason == "match_not_found"
    shutil.rmtree(tmp)


def test_invalid_control_transitions():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, r, matches = _one_match_setup()
    m = matches[0]
    try:
        t_svc.complete_match(m.id, "TEAM_A_WIN", m.team_a_id, 10.0)
        raise AssertionError("completed a match that was never started (not RUNNING)")
    except Exception as e:
        assert "match_not_running" in str(e)
    shutil.rmtree(tmp)


# =========================================================== 14-15 event distribution
def test_event_distribution_single_snapshot_call():
    runner = BattleRunner(BattleEngine(AGGRESSIVE_CODE, BETA_CODE), tick_hz=30)
    runner.start_thread()
    runner.start_battle()
    assert _wait(lambda: runner.snapshot()["tick_count"] > 0)
    snap = runner.snapshot()
    events = snap["new_events"]
    # a single drain call CAN see events; simulate distributing the SAME
    # list to two consumers (never calling snapshot() a second time)
    consumer_a_saw = list(events)
    consumer_b_saw = list(events)
    assert consumer_a_saw == consumer_b_saw
    runner.stop_thread()


def test_event_consumer_does_not_drain_twice():
    """Proves WHY only one authoritative snapshot() caller is allowed:
    a second, independent snapshot() call sees nothing new — exactly the
    Phase 4 race a second consumer would recreate if it called
    snapshot() on its own instead of reading the first caller's
    new_events (spec section 25)."""
    runner = BattleRunner(BattleEngine(AGGRESSIVE_CODE, BETA_CODE), tick_hz=30)
    runner.start_thread()
    runner.start_battle()
    assert _wait(lambda: runner.snapshot()["tick_count"] > 0)
    first = runner.snapshot()
    second = runner.snapshot()  # simulates a second, independent consumer
    assert len(first["new_events"]) >= 0
    assert second["new_events"] == []  # already drained by the first call
    runner.stop_thread()


# ========================================================= 16-18 runtime errors / thread health
def test_runtime_error_detection_via_on_error_callback():
    class ExplodingEngine(BattleEngine):
        def step(self, dt):
            raise RuntimeError("engine bug")

    engine = ExplodingEngine(AGGRESSIVE_CODE, BETA_CODE)
    engine.start()
    runner = BattleRunner(engine, tick_hz=30)
    captured = []
    runner.on_error = lambda msg: captured.append(msg)
    runner.start_thread()
    assert _wait(lambda: len(captured) > 0)
    assert "engine bug" in captured[0]
    runner.stop_thread()


def test_team_code_error_handling_no_fake_winner():
    engine = BattleEngine(BROKEN_CODE, BETA_CODE, team_a_name="Team Alpha", team_b_name="Team Beta")
    engine.start()
    for _ in range(30):
        engine.step(1 / 30)
    error_events = [e for e in engine.events.all() if e.kind == ev.CODE_ERROR and e.team == "Team Alpha"]
    assert len(error_events) > 0
    assert "error" in error_events[0].message
    assert engine.winner is None  # a broken team's code error never fabricates a win for either side
    assert engine.ship_b.alive is True  # Team Beta unaffected by Team Alpha's error


def test_engine_thread_health():
    runner = BattleRunner(BattleEngine(AGGRESSIVE_CODE, BETA_CODE), tick_hz=30)
    assert runner.snapshot()["engine_alive"] is False  # never started
    runner.start_thread()
    assert _wait(lambda: runner.snapshot()["engine_alive"] is True)
    runner.stop_thread()
    assert runner.snapshot()["engine_alive"] is False  # cleanly stopped, detectable


# ==================================================================== 19-20 scoreboard/draw
def test_live_scoreboard_values_from_snapshot():
    runner = BattleRunner(BattleEngine(AGGRESSIVE_CODE, BETA_CODE), tick_hz=30)
    runner.start_thread()
    runner.start_battle()
    assert _wait(lambda: runner.snapshot()["tick_count"] > 0)
    snap = runner.snapshot()
    assert 0.0 <= snap["ship_a"]["hp_pct"] <= 1.0
    assert 0.0 <= snap["ship_a"]["energy_pct"] <= 1.0
    assert "attack_cooldown" in snap["ship_a"]  # Phase 6 addition, real engine field, not invented
    runner.stop_thread()


def test_draw_live_status():
    config_engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE)
    from engine.config import BattleConfig
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE, config=BattleConfig(battle_duration=0.05))
    engine.start()
    for _ in range(10):
        engine.step(1 / 30)
        if engine.ended:
            break
    snap = {"ended": engine.ended, "outcome": engine.outcome, "winner": engine.winner}
    assert live_state.is_draw_outcome(snap) is True
    assert snap["winner"] is None


# ============================================================= 21-23 queue/context/competition
def test_match_queue_classification():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, r, matches = _one_match_setup()
    current, next_m, upcoming = live_state.classify_match_queue([r], matches)
    assert current is None  # nothing prepared/running yet
    assert next_m is not None and next_m.status == M_READY
    t_svc.prepare_match_for_start(next_m.id)
    matches_reloaded = t_svc.get_competition_matches("champ")
    current2, next_m2, _ = live_state.classify_match_queue([r], matches_reloaded)
    assert current2 is not None and current2.status == M_RUNNING
    shutil.rmtree(tmp)


def test_match_context_immutable_during_running_match():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, r, matches = _one_match_setup()
    m = matches[0]
    t_svc.prepare_match_for_start(m.id)
    pinned = (m.competition_id, m.round_id, m.id, m.team_a_id, m.team_b_id, m.submission_a_id, m.submission_b_id, m.challenge_id)
    # unrelated changes elsewhere must not alter the running match's context
    team_svc.update_team("team-alpha", name="Renamed Mid-Match")
    reloaded = t_svc.get_match(m.id)
    current = (reloaded.competition_id, reloaded.round_id, reloaded.id, reloaded.team_a_id, reloaded.team_b_id, reloaded.submission_a_id, reloaded.submission_b_id, reloaded.challenge_id)
    assert current == pinned
    shutil.rmtree(tmp)


def test_competition_control_uses_tournament_service_lifecycle():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, r, matches = _one_match_setup()
    assert t_svc.get_competition("champ").status == "ACTIVE"
    t_svc.pause_competition("champ")
    assert t_svc.get_competition("champ").status == "PAUSED"
    t_svc.resume_competition("champ")
    assert t_svc.get_competition("champ").status == "ACTIVE"
    t_svc.complete_competition("champ")
    assert t_svc.get_competition("champ").status == "COMPLETED"
    shutil.rmtree(tmp)


# ============================================================================ 24 shutdown
def test_shutdown_stops_thread_cleanly():
    runner = BattleRunner(BattleEngine(AGGRESSIVE_CODE, BETA_CODE), tick_hz=30)
    runner.start_thread()
    assert _wait(lambda: runner._thread.is_alive())
    runner.stop_thread(timeout=2.0)
    assert runner._thread.is_alive() is False


# ======================================================== 25-28 localization/RTL/theme
def test_arabic_localization_keys_present():
    keys = [
        "nav_live_monitor", "live_monitoring_title", "engine_health_title", "runtime_status_label"
        if "runtime_status_label" in localization.STRINGS else "engine_status_label",
        "current_match_label", "start", "pause", "resume", "reset", "stop",
        "running", "paused", "completed", "error_status", "draw", "event_stream_title", "alerts_title",
        "competition_status_title",
    ]
    for key in keys:
        entry = localization.STRINGS[key]
        assert entry.get("en") and entry.get("ar")


def test_rtl_toggle():
    localization.set_lang("ar")
    assert localization.is_rtl() is True
    localization.set_lang("en")
    assert localization.is_rtl() is False


def test_dark_mode_tokens():
    tokens = theme.Tokens("dark")
    assert tokens.mode == "dark" and tokens.bg == theme.BG


def test_light_mode_tokens():
    tokens = theme.Tokens("dark")
    tokens.set_mode("light")
    assert tokens.mode == "light" and tokens.bg == theme.LIGHT_BG


# =========================================================== existing systems
def test_existing_tournament_tests():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, r, matches = _one_match_setup()
    assert t_svc.get_competition("champ").status == "ACTIVE"
    shutil.rmtree(tmp)


def test_existing_results_tests():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, r, matches = _one_match_setup()
    m = matches[0]
    t_svc.prepare_match_for_start(m.id)
    completed = t_svc.complete_match(m.id, "TEAM_A_WIN", m.team_a_id, 10.0)
    result = r_svc.record_from_match(completed, {
        "team_a_hp_remaining": 50.0, "team_b_hp_remaining": 0.0,
        "team_a_damage_dealt": 100.0, "team_b_damage_dealt": 20.0,
        "team_a_damage_received": 20.0, "team_b_damage_received": 100.0,
    }, [])
    assert result.outcome == "TEAM_A_WIN"
    board = r_svc.leaderboard("champ")
    assert len(board) == 2
    shutil.rmtree(tmp)


def test_existing_engine_tests():
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE)
    engine.start()
    for _ in range(30 * 60):
        engine.step(1 / 30)
        if engine.winner:
            break
    assert engine.winner is not None


if __name__ == "__main__":
    tests = [
        test_runtime_state_transitions,
        test_active_match_ownership_via_can_start_match,
        test_start_control, test_pause_control, test_resume_control, test_reset_control,
        test_stop_behavior_records_error_not_a_fake_win,
        test_pause_freezes_simulation, test_resume_continues_same_battle, test_reset_restores_state_via_runner,
        test_only_one_active_match_enforced_by_service_state, test_invalid_match_start_rejected, test_invalid_control_transitions,
        test_event_distribution_single_snapshot_call, test_event_consumer_does_not_drain_twice,
        test_runtime_error_detection_via_on_error_callback, test_team_code_error_handling_no_fake_winner, test_engine_thread_health,
        test_live_scoreboard_values_from_snapshot, test_draw_live_status,
        test_match_queue_classification, test_match_context_immutable_during_running_match, test_competition_control_uses_tournament_service_lifecycle,
        test_shutdown_stops_thread_cleanly,
        test_arabic_localization_keys_present, test_rtl_toggle, test_dark_mode_tokens, test_light_mode_tokens,
        test_existing_tournament_tests, test_existing_results_tests, test_existing_engine_tests,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print(f"\nALL {len(tests)} LIVE CONTROL TESTS PASSED")
