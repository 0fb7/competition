"""Automated tests for Phase 5 (Results, History & Analytics), per
prompt.md section 29. Uses temp directories for every JSON store so it
never touches the real data/*.json. Run with:

    python tests/test_results.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from challenges.challenge import Rules
from challenges.challenge_repository import ChallengeRepository
from challenges.challenge_service import ChallengeService
from engine import events as ev
from engine.battle import BattleEngine
from results.match_result import DuplicateResultError
from results.result_repository import ResultRepository
from results.result_service import ResultService
from roster.team_repository import TeamRepository
from roster.team_service import TeamService
from submissions.submission_repository import SubmissionRepository
from submissions.submission_service import SubmissionService
from tournament.competition import STATUS_DRAFT
from tournament.match import (
    OUTCOME_DRAW, OUTCOME_ERROR, OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN,
    STATUS_CANCELLED as M_CANCELLED, STATUS_COMPLETED as M_COMPLETED, STATUS_READY as M_READY,
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


def _fresh_env(n_teams=4):
    tmp = tempfile.mkdtemp(prefix="battleship_results_test_")
    team_repo = TeamRepository(os.path.join(tmp, "teams.json"))
    team_svc = TeamService(team_repo, os.path.join(tmp, "team_submissions"))
    team_svc.ensure_default_teams(ALPHA_PATH, BETA_PATH)

    names = ["Team Gamma", "Team Delta", "Team Epsilon", "Team Zeta"]
    ids = ["team-gamma", "team-delta", "team-epsilon", "team-zeta"]
    for i in range(max(0, n_teams - 2)):
        team_svc.create_team(names[i], team_id=ids[i])

    ch_repo = ChallengeRepository(os.path.join(tmp, "challenges.json"))
    ch_svc = ChallengeService(ch_repo)
    ch_svc.ensure_default_challenge()
    challenge = ch_svc.get_active_challenge()

    sub_repo = SubmissionRepository(os.path.join(tmp, "submissions.json"))
    sub_svc = SubmissionService(sub_repo, team_svc, ch_svc)

    all_team_ids = ["team-alpha", "team-beta"] + ids[:max(0, n_teams - 2)]
    for tid in all_team_ids[:n_teams]:
        sub = sub_svc.create_draft(tid, challenge.id, AGGRESSIVE_CODE)
        sub_svc.submit_submission(sub.id)

    t_repo = TournamentRepository(os.path.join(tmp, "tournament"))
    r_repo = ResultRepository(os.path.join(tmp, "results"))
    t_svc = TournamentService(t_repo, team_svc, ch_svc, sub_svc)
    r_svc = ResultService(r_repo, t_svc, team_svc, ch_svc, sub_svc)
    t_svc.result_service = r_svc  # same wiring order as ui/app.py

    return tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, all_team_ids[:n_teams]


def _competition_with_teams(t_svc, challenge, team_ids, comp_id="champ"):
    comp = t_svc.create_competition(comp_id, "Championship", description="test", challenge_id=challenge.id)
    for tid in team_ids:
        t_svc.add_team(comp_id, tid)
    return comp


def _run_real_battle(code_a, code_b, config, name_a, name_b, max_ticks=1800):
    """Runs a real, throwaway BattleEngine to completion (mirrors exactly
    what ui/app.py's live BattleRunner produces) and returns
    (engine, battle_stats, events) — the same battle_stats shape
    ui/app.py._record_match_result() builds from a real snapshot, and the
    same events list it accumulates from runner.snapshot() each tick."""
    engine = BattleEngine(code_a, code_b, team_a_name=name_a, team_b_name=name_b, config=config)
    engine.start()
    dt = 1 / 30
    for _ in range(max_ticks):
        engine.step(dt)
        if engine.ended:
            break
    events = engine.events.all()

    def _dealt(team_name):
        return sum(e.data.get("amount", 0.0) for e in events if e.kind == ev.DAMAGE and e.team == team_name)

    def _received(team_name):
        return sum(e.data.get("amount", 0.0) for e in events if e.kind == ev.DAMAGE and e.data.get("target_team") == team_name)

    battle_stats = {
        "team_a_hp_remaining": engine.ship_a.hp, "team_b_hp_remaining": engine.ship_b.hp,
        "team_a_damage_dealt": _dealt(name_a), "team_b_damage_dealt": _dealt(name_b),
        "team_a_damage_received": _received(name_a), "team_b_damage_received": _received(name_b),
    }
    return engine, battle_stats, events


def _play_match(t_svc, r_svc, match):
    """Prepares, runs and completes one Match through the exact same
    prepare_match_for_start -> BattleEngine -> complete_match ->
    record_from_match sequence ui/app.py drives, and returns the
    (Match, MatchResult)."""
    code_a, code_b, config, name_a, name_b = t_svc.prepare_match_for_start(match.id)
    engine, battle_stats, events = _run_real_battle(code_a, code_b, config, name_a, name_b)
    if engine.outcome == "TIME_LIMIT_DRAW" or (engine.outcome == "DESTROY_ENEMY" and engine.winner is None):
        outcome, winner_team_id = OUTCOME_DRAW, None
    elif engine.winner == name_a:
        outcome, winner_team_id = OUTCOME_TEAM_A_WIN, match.team_a_id
    elif engine.winner == name_b:
        outcome, winner_team_id = OUTCOME_TEAM_B_WIN, match.team_b_id
    else:
        outcome, winner_team_id = OUTCOME_ERROR, None
    completed = t_svc.complete_match(match.id, outcome, winner_team_id, engine.elapsed)
    result = r_svc.record_from_match(completed, battle_stats, events)
    return completed, result


def _one_match_setup(n_teams=2):
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams = _fresh_env(n_teams)
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    return tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches


# ============================================================ result creation
def test_match_result_creation():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    assert result is not None
    assert result.id == match.id == result.match_id
    shutil.rmtree(tmp)


def test_match_result_persistence():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    reloaded_repo = ResultRepository(os.path.join(tmp, "results"))
    reloaded = reloaded_repo.get_match_result(match.id)
    assert reloaded is not None and reloaded.outcome == result.outcome
    shutil.rmtree(tmp)


def test_match_result_immutability():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    assert not hasattr(r_svc.repo, "update_match_result")  # no mutation path exists at all
    before = r_svc.repo.get_match_result(match.id)
    # a second record attempt for the same match must not change anything
    r_svc.record_from_match(match, {"team_a_hp_remaining": 999.0}, [])
    after = r_svc.repo.get_match_result(match.id)
    assert before.to_dict() == after.to_dict()
    shutil.rmtree(tmp)


def test_duplicate_result_protection():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    from results.match_result import MatchResult
    duplicate = MatchResult.from_dict({**result.to_dict()})
    try:
        r_svc.repo.create_match_result(duplicate)
        raise AssertionError("duplicate MatchResult write was accepted")
    except DuplicateResultError:
        pass
    all_results = r_svc.repo.get_all_match_results()
    assert len([x for x in all_results if x.match_id == match.id]) == 1
    shutil.rmtree(tmp)


# ==================================================================== outcomes
def test_winner_result():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    assert result.outcome in (OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN)
    assert result.winner_team_id in (match.team_a_id, match.team_b_id)
    shutil.rmtree(tmp)


def test_draw_result():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams = _fresh_env(n_teams=2)
    quick_draw = ch_svc.create_challenge("blitz", "Blitz", description="instant draw", rules=Rules(battle_duration=0.03))
    t_svc.create_competition("draws", "Draws", challenge_id=quick_draw.id)
    for tid in ("team-alpha", "team-beta"):
        sub = sub_svc.create_draft(tid, quick_draw.id, AGGRESSIVE_CODE)
        sub_svc.submit_submission(sub.id)
        t_svc.add_team("draws", tid)
    t_svc.mark_ready("draws")
    r = t_svc.create_round("draws", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.start_competition("draws")
    match, result = _play_match(t_svc, r_svc, matches[0])
    assert result.outcome == OUTCOME_DRAW
    assert result.winner_team_id is None  # no winner ever assigned to a draw
    shutil.rmtree(tmp)


def test_error_result():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    m = matches[0]
    t_svc.prepare_match_for_start(m.id)
    completed = t_svc.complete_match(m.id, OUTCOME_ERROR, None, 5.0)
    result = r_svc.record_from_match(completed, None, [])
    assert result.outcome == OUTCOME_ERROR
    assert result.winner_team_id is None
    assert result.team_a_hp_remaining is None  # no real telemetry was handed in — not fabricated
    shutil.rmtree(tmp)


def test_cancelled_result():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    m = matches[0]
    cancelled = t_svc.cancel_match(m.id)
    assert cancelled.status == M_CANCELLED
    # a match cancelled before it ever ran must not produce a MatchResult
    assert r_svc.get_match_result(m.id) is None
    shutil.rmtree(tmp)


# =============================================================== bye handling
def test_bye_result_recorded_without_battle():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams = _fresh_env(n_teams=3)
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_SINGLE_ELIMINATION)
    matches = t_svc.generate_single_elimination(r.id)
    bye = next(m for m in matches if m.is_bye)
    result = r_svc.get_match_result(bye.id)
    assert result is not None
    assert result.is_bye is True
    assert result.duration is None
    assert result.team_a_hp_remaining is None and result.team_a_damage_dealt is None
    shutil.rmtree(tmp)


# ============================================================ snapshot metadata
def test_snapshot_metadata():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    assert result.team_a_name_at_match == "Team Alpha"
    assert result.team_b_name_at_match == "Team Beta"
    assert result.submission_a_version == 1
    assert result.challenge_name_at_match == challenge.name
    assert result.challenge_difficulty_at_match == challenge.difficulty
    shutil.rmtree(tmp)


# ============================================================= event history
def test_event_persistence():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    events = r_svc.get_match_events(match.id)
    assert len(events) > 0
    assert all(e.kind in (ev.CODE_EXECUTED, ev.CODE_ERROR, ev.TARGET_ACQUIRED, ev.ATTACK, ev.DAMAGE, ev.DESTROYED, ev.BATTLE_WON, ev.BATTLE_DRAW) for e in events)
    shutil.rmtree(tmp)


def test_event_ordering():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    events = r_svc.get_match_events(match.id)
    timestamps = [e.timestamp for e in events]
    assert timestamps == sorted(timestamps)
    assert events[-1].kind in (ev.BATTLE_WON, ev.DESTROYED, ev.BATTLE_DRAW)  # battle concludes the timeline
    shutil.rmtree(tmp)


# ======================================================= data integrity/history
def test_historical_team_rename_behavior():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    team_svc.update_team("team-alpha", name="Team Alpha Renamed")
    reloaded = r_svc.get_match_result(match.id)
    assert reloaded.team_a_name_at_match == "Team Alpha"  # historical snapshot untouched by the rename
    assert team_svc.get_team("team-alpha").name == "Team Alpha Renamed"
    shutil.rmtree(tmp)


def test_historical_submission_version_behavior():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    new_v2 = sub_svc.create_new_version("team-alpha", challenge.id)
    sub_svc.update_draft(new_v2.id, AGGRESSIVE_CODE + "\n# v2\n")
    sub_svc.submit_submission(new_v2.id)
    reloaded = r_svc.get_match_result(match.id)
    assert reloaded.submission_a_version == 1  # still points at the version that actually fought
    assert sub_svc.get_active_submission("team-alpha", challenge.id).version == 2
    shutil.rmtree(tmp)


def test_historical_challenge_behavior():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    original_name = result.challenge_name_at_match
    ch_svc.update_challenge(challenge.id, name="Renamed Challenge")
    reloaded = r_svc.get_match_result(match.id)
    assert reloaded.challenge_name_at_match == original_name  # untouched by the later rename
    shutil.rmtree(tmp)


# =========================================================== leaderboard/stats
def test_leaderboard_aggregation():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    _play_match(t_svc, r_svc, matches[0])
    board = r_svc.leaderboard("champ")
    assert len(board) == 2
    assert board[0]["rank"] == 1 and board[1]["rank"] == 2
    shutil.rmtree(tmp)


def test_win_loss_draw_counts():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    board = {row["team_id"]: row for row in r_svc.leaderboard("champ")}
    winner_id = result.winner_team_id
    loser_id = match.team_b_id if winner_id == match.team_a_id else match.team_a_id
    assert board[winner_id]["wins"] == 1 and board[winner_id]["losses"] == 0
    assert board[loser_id]["wins"] == 0 and board[loser_id]["losses"] == 1
    shutil.rmtree(tmp)


def test_score_aggregation():
    from engine.competition import TeamRecord
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    board = {row["team_id"]: row for row in r_svc.leaderboard("champ")}
    winner_row = board[result.winner_team_id]
    expected = TeamRecord(team="x", wins=1, losses=0, damage_dealt=winner_row["damage_dealt"]).score
    assert winner_row["score"] == expected  # same formula as engine.competition.TeamRecord, not a second one
    shutil.rmtree(tmp)


def test_damage_aggregation():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    board = {row["team_id"]: row for row in r_svc.leaderboard("champ")}
    assert board[match.team_a_id]["damage_dealt"] == result.team_a_damage_dealt
    assert board[match.team_b_id]["damage_dealt"] == result.team_b_damage_dealt
    shutil.rmtree(tmp)


def test_win_rate():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    perf = r_svc.team_performance(result.winner_team_id, "champ")
    assert perf["played"] == 1 and perf["win_rate"] == 1.0
    shutil.rmtree(tmp)


def test_average_duration():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    perf = r_svc.team_performance(match.team_a_id, "champ")
    assert perf["avg_duration"] is not None and perf["avg_duration"] > 0
    shutil.rmtree(tmp)


# ==================================================================== summaries
def test_competition_summary():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    _play_match(t_svc, r_svc, matches[0])
    t_svc.complete_competition("champ")
    summary = r_svc.competition_summary("champ")
    assert summary["total_teams"] == 2
    assert summary["total_matches"] == 1
    assert summary["completed_matches"] == 1
    assert len(summary["leaderboard"]) == 2
    shutil.rmtree(tmp)


def test_round_summary():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    summary = r_svc.round_summary(r.id)
    assert len(summary["matches"]) == 1
    assert len(summary["winners"]) == 1
    assert summary["standings"] is not None  # round-robin -> aggregate standings, not invented advancement
    shutil.rmtree(tmp)


# ================================================================ match history
def test_match_history_filtering():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    by_comp = r_svc.match_history(competition_id="champ")
    assert len(by_comp) == 1
    by_team = r_svc.match_history(team_id=match.team_a_id)
    assert len(by_team) == 1
    by_outcome = r_svc.match_history(outcome=result.outcome)
    assert len(by_outcome) == 1
    by_wrong_team = r_svc.match_history(team_id="does-not-exist")
    assert len(by_wrong_team) == 0
    shutil.rmtree(tmp)


def test_match_detail_retrieval():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    match, result = _play_match(t_svc, r_svc, matches[0])
    fetched = r_svc.get_match_result(match.id)
    events = r_svc.get_match_events(match.id)
    assert fetched.match_id == match.id
    assert len(events) > 0
    shutil.rmtree(tmp)


# =========================================================== existing systems
def test_existing_tournament_tests():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams, r, matches = _one_match_setup()
    assert t_svc.get_competition("champ").status != STATUS_DRAFT
    assert matches[0].status == M_READY
    shutil.rmtree(tmp)


def test_existing_submission_tests():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams = _fresh_env()
    active = sub_svc.get_active_submission("team-alpha", challenge.id)
    assert active is not None and active.status == "SUBMITTED"
    shutil.rmtree(tmp)


def test_existing_challenge_tests():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams = _fresh_env()
    assert challenge.id == "tactical-battleship"
    shutil.rmtree(tmp)


def test_existing_team_tests():
    tmp, team_svc, ch_svc, sub_svc, t_svc, r_svc, challenge, teams = _fresh_env()
    assert team_svc.get_team("team-alpha").name == "Team Alpha"
    shutil.rmtree(tmp)


def test_existing_engine_tests():
    engine = BattleEngine(AGGRESSIVE_CODE, BETA_CODE)
    engine.start()
    for _ in range(30 * 60):
        engine.step(1 / 30)
        if engine.winner:
            break
    assert engine.winner is not None


def test_existing_competition_tracker_tests():
    from engine.competition import CompetitionTracker
    tracker = CompetitionTracker(["Team Alpha", "Team Beta"])
    tracker.records["Team Alpha"].wins = 2
    assert tracker.ranked()[0].team == "Team Alpha"


if __name__ == "__main__":
    tests = [
        test_match_result_creation, test_match_result_persistence, test_match_result_immutability,
        test_duplicate_result_protection,
        test_winner_result, test_draw_result, test_error_result, test_cancelled_result,
        test_bye_result_recorded_without_battle,
        test_snapshot_metadata,
        test_event_persistence, test_event_ordering,
        test_historical_team_rename_behavior, test_historical_submission_version_behavior, test_historical_challenge_behavior,
        test_leaderboard_aggregation, test_win_loss_draw_counts, test_score_aggregation, test_damage_aggregation,
        test_win_rate, test_average_duration,
        test_competition_summary, test_round_summary,
        test_match_history_filtering, test_match_detail_retrieval,
        test_existing_tournament_tests, test_existing_submission_tests, test_existing_challenge_tests,
        test_existing_team_tests, test_existing_engine_tests, test_existing_competition_tracker_tests,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print(f"\nALL {len(tests)} RESULTS TESTS PASSED")
