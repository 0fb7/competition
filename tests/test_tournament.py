"""Automated tests for Phase 4 (Competition, Rounds & Match Management),
per prompt.md section 37. Uses temp directories for every JSON store so
it never touches the real data/*.json. Run with:

    python tests/test_tournament.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from challenges.challenge import Rules
from challenges.challenge_repository import ChallengeRepository
from challenges.challenge_service import ChallengeService
from engine.battle import BattleEngine
from roster.team_repository import TeamRepository
from roster.team_service import TeamService
from submissions.submission_repository import SubmissionRepository
from submissions.submission_service import SubmissionService
from tournament.competition import STATUS_ACTIVE, STATUS_DRAFT, STATUS_READY, ValidationError
from tournament.match import (
    OUTCOME_DRAW, OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN,
    STATUS_COMPLETED as M_COMPLETED, STATUS_READY as M_READY,
)
from tournament.round import STATUS_COMPLETED as R_COMPLETED, TYPE_ROUND_ROBIN, TYPE_SINGLE_ELIMINATION
from tournament.tournament_repository import TournamentRepository
from tournament.tournament_service import TournamentService

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALPHA_PATH = os.path.join(ROOT, "teams", "team_alpha.py")
BETA_PATH = os.path.join(ROOT, "teams", "team_beta.py")

with open(ALPHA_PATH, encoding="utf-8") as f:
    AGGRESSIVE_CODE = f.read()


def _fresh_env(n_teams=4):
    tmp = tempfile.mkdtemp(prefix="battleship_tournament_test_")
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
    t_svc = TournamentService(t_repo, team_svc, ch_svc, sub_svc)

    return tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, all_team_ids[:n_teams]


def _competition_with_teams(t_svc, challenge, team_ids, comp_id="champ"):
    comp = t_svc.create_competition(comp_id, "Championship", description="test", challenge_id=challenge.id)
    for tid in team_ids:
        t_svc.add_team(comp_id, tid)
    return comp


# ============================================================== competitions
def test_create_competition():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    comp = t_svc.create_competition("champ", "Championship", description="d", challenge_id=challenge.id)
    assert comp.status == STATUS_DRAFT and comp.challenge_id == challenge.id
    shutil.rmtree(tmp)


def test_get_competition():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    assert t_svc.get_competition("champ").name == "Championship"
    assert t_svc.get_competition("nope") is None
    shutil.rmtree(tmp)


def test_update_competition():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    updated = t_svc.update_competition("champ", name="Championship 2026")
    assert updated.name == "Championship 2026"
    shutil.rmtree(tmp)


def test_delete_competition():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    t_svc.delete_competition("champ")
    assert t_svc.get_competition("champ") is None
    shutil.rmtree(tmp)


def test_competition_persistence():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    t_svc.create_competition("champ", "Championship", challenge_id=challenge.id)
    repo2 = TournamentRepository(os.path.join(tmp, "tournament"))
    reloaded = repo2.get_competition("champ")
    assert reloaded is not None and reloaded.name == "Championship"
    shutil.rmtree(tmp)


def test_team_eligibility():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    assert t_svc.is_team_eligible("team-alpha", challenge.id) is True
    team_svc.create_team("Team NoSub", team_id="team-nosub")
    assert t_svc.is_team_eligible("team-nosub", challenge.id) is False
    shutil.rmtree(tmp)


def test_duplicate_team_prevention():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, ["team-alpha"])
    try:
        t_svc.add_team("champ", "team-alpha")
        raise AssertionError("duplicate team accepted")
    except ValidationError as e:
        assert str(e) == "team_already_added"
    shutil.rmtree(tmp)


def test_challenge_validation():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    try:
        t_svc.create_competition("bad", "Bad", challenge_id="does-not-exist")
        raise AssertionError("nonexistent challenge accepted")
    except ValidationError as e:
        assert str(e) == "challenge_not_found"
    shutil.rmtree(tmp)


def test_competition_status_transitions():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    comp = _competition_with_teams(t_svc, challenge, teams)
    assert comp.status == STATUS_DRAFT
    ready = t_svc.mark_ready("champ")
    assert ready.status == STATUS_READY
    t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    active = t_svc.start_competition("champ")
    assert active.status == STATUS_ACTIVE
    try:
        t_svc.mark_ready("champ")  # ACTIVE -> READY directly is not a valid transition
        raise AssertionError("invalid transition accepted")
    except ValidationError:
        pass
    shutil.rmtree(tmp)


# ===================================================================== rounds
def test_create_round():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    assert r.competition_id == "champ" and r.round_type == TYPE_ROUND_ROBIN
    shutil.rmtree(tmp)


def test_round_ordering():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, teams)
    r1 = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    r2 = t_svc.create_round("champ", "Round 2", TYPE_ROUND_ROBIN)
    assert r1.order == 1 and r2.order == 2
    ordered = t_svc.get_competition_rounds("champ")
    assert [r.id for r in ordered] == [r1.id, r2.id]
    shutil.rmtree(tmp)


# ===================================================================== matches
def test_create_match():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    assert len(matches) > 0
    assert all(m.challenge_id == challenge.id for m in matches)
    shutil.rmtree(tmp)


def test_match_team_validation():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Custom", "CUSTOM")
    try:
        t_svc.create_custom_match(r.id, "team-alpha", "not-a-real-team")
        raise AssertionError("nonexistent team accepted")
    except ValidationError as e:
        assert str(e) == "team_not_in_competition"
    shutil.rmtree(tmp)


def test_match_submission_validation():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    m = matches[0]
    ok, reason = t_svc.can_start_match(m.id)
    assert ok is True, reason
    # corrupt the pinned submission id -> must be caught, not silently ignored
    t_repo = t_svc.repo
    t_repo.update_match(m.id, submission_a_id="does-not-exist")
    ok2, reason2 = t_svc.can_start_match(m.id)
    assert ok2 is False and reason2 == "submission_missing"
    shutil.rmtree(tmp)


def test_match_challenge_validation():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    m = matches[0]
    # Simulate the referenced Challenge having been removed entirely (bypassing
    # ChallengeService's own active-challenge delete protection, which isn't
    # what's under test here) so match.challenge_id/submission.challenge_id
    # stay mutually consistent and only the "does the Challenge still exist"
    # check is exercised.
    ch_svc.repo.delete_challenge(challenge.id)
    ok, reason = t_svc.can_start_match(m.id)
    assert ok is False and reason == "challenge_not_found"
    shutil.rmtree(tmp)


def test_match_status_transitions():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    m = matches[0]
    assert m.status == M_READY
    t_svc.prepare_match_for_start(m.id)
    assert t_svc.get_match(m.id).status == "RUNNING"
    completed = t_svc.complete_match(m.id, OUTCOME_TEAM_A_WIN, m.team_a_id, 10.0)
    assert completed.status == M_COMPLETED
    try:
        t_svc.complete_match(m.id, OUTCOME_TEAM_A_WIN, m.team_a_id, 10.0)
        raise AssertionError("completing an already-completed match was accepted")
    except ValidationError:
        pass
    shutil.rmtree(tmp)


def test_match_snapshot_creation():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    m = matches[0]
    sub_a = sub_svc.get_active_submission(m.team_a_id, challenge.id)
    sub_b = sub_svc.get_active_submission(m.team_b_id, challenge.id)
    assert m.submission_a_id == sub_a.id
    assert m.submission_b_id == sub_b.id
    assert m.challenge_id == challenge.id
    shutil.rmtree(tmp)


def test_match_uses_exact_submission_versions():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    m = matches[0]
    pinned_sub_id = m.submission_a_id

    # team_a submits a v2 AFTER the match was created
    new_v2 = sub_svc.create_new_version(m.team_a_id, challenge.id)
    sub_svc.update_draft(new_v2.id, AGGRESSIVE_CODE + "\n# v2\n")
    sub_svc.submit_submission(new_v2.id)
    assert sub_svc.get_active_submission(m.team_a_id, challenge.id).id == new_v2.id

    # the already-created match must still point at the original submission
    reloaded_match = t_svc.get_match(m.id)
    assert reloaded_match.submission_a_id == pinned_sub_id
    assert reloaded_match.submission_a_id != new_v2.id
    shutil.rmtree(tmp)


def test_match_uses_exact_challenge_configuration():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    m = matches[0]
    _, _, config, _, _ = t_svc.prepare_match_for_start(m.id)
    assert config.attack_range == challenge.rules.attack_range == 10.0
    shutil.rmtree(tmp)


def test_match_execution_through_existing_battle_engine():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    m = matches[0]
    code_a, code_b, config, name_a, name_b = t_svc.prepare_match_for_start(m.id)

    engine = BattleEngine(code_a, code_b, team_a_name=name_a, team_b_name=name_b, config=config)
    engine.start()
    dt = 1 / 30
    for _ in range(30 * 60):
        engine.step(dt)
        if engine.ended:
            break
    assert engine.ended is True
    assert engine.winner is not None
    shutil.rmtree(tmp)


def test_match_result_from_real_battle_engine_outcome():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    m = matches[0]
    code_a, code_b, config, name_a, name_b = t_svc.prepare_match_for_start(m.id)
    engine = BattleEngine(code_a, code_b, team_a_name=name_a, team_b_name=name_b, config=config)
    engine.start()
    dt = 1 / 30
    for _ in range(30 * 60):
        engine.step(dt)
        if engine.ended:
            break
    outcome = OUTCOME_TEAM_A_WIN if engine.winner == name_a else OUTCOME_TEAM_B_WIN
    winner_team_id = m.team_a_id if outcome == OUTCOME_TEAM_A_WIN else m.team_b_id
    completed = t_svc.complete_match(m.id, outcome, winner_team_id, engine.elapsed)
    assert completed.winner_team_id == winner_team_id
    assert completed.outcome == outcome
    shutil.rmtree(tmp)


def test_draw_handling():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    # a near-zero time limit guarantees a time-limit draw regardless of strategy
    quick_draw_challenge = ch_svc.create_challenge(
        "blitz", "Blitz", description="instant draw", rules=Rules(battle_duration=0.03),
    )
    comp = t_svc.create_competition("draws", "Draws", challenge_id=quick_draw_challenge.id)
    for tid in ("team-alpha", "team-beta"):
        sub = sub_svc.create_draft(tid, quick_draw_challenge.id, AGGRESSIVE_CODE)
        sub_svc.submit_submission(sub.id)
        t_svc.add_team("draws", tid)
    t_svc.mark_ready("draws")
    r = t_svc.create_round("draws", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.start_competition("draws")
    m = matches[0]
    code_a, code_b, config, name_a, name_b = t_svc.prepare_match_for_start(m.id)
    engine = BattleEngine(code_a, code_b, team_a_name=name_a, team_b_name=name_b, config=config)
    engine.start()
    dt = 1 / 30
    for _ in range(60):
        engine.step(dt)
        if engine.ended:
            break
    assert engine.outcome == "TIME_LIMIT_DRAW"
    assert engine.winner is None
    completed = t_svc.complete_match(m.id, OUTCOME_DRAW, None, engine.elapsed)
    assert completed.outcome == OUTCOME_DRAW
    assert completed.winner_team_id is None
    shutil.rmtree(tmp)


# ============================================================== round robin
def test_round_robin_pair_generation():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env(n_teams=4)
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    pairs = {frozenset([m.team_a_id, m.team_b_id]) for m in matches}
    expected = {frozenset([a, b]) for i, a in enumerate(teams) for b in teams[i + 1:]}
    assert pairs == expected
    assert len(matches) == 6  # C(4,2)
    shutil.rmtree(tmp)


def test_no_duplicate_round_robin_pairs():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env(n_teams=4)
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    pairs = [frozenset([m.team_a_id, m.team_b_id]) for m in matches]
    assert len(pairs) == len(set(pairs))
    shutil.rmtree(tmp)


def test_no_self_match():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env(n_teams=4)
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    assert all(m.team_a_id != m.team_b_id for m in matches)
    shutil.rmtree(tmp)


# ========================================================= single elimination
def test_single_elimination_bracket_generation():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env(n_teams=4)
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_SINGLE_ELIMINATION)
    matches = t_svc.generate_single_elimination(r.id)
    assert len(matches) == 2  # 4 teams, no byes needed
    assert all(not m.is_bye for m in matches)
    shutil.rmtree(tmp)


def test_winner_advancement():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env(n_teams=4)
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_SINGLE_ELIMINATION)
    matches = t_svc.generate_single_elimination(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    for m in matches:
        t_svc.prepare_match_for_start(m.id)
        t_svc.complete_match(m.id, OUTCOME_TEAM_A_WIN, m.team_a_id, 10.0)
    comp = t_svc.get_competition("champ")
    assert len(comp.round_ids) == 2
    final_round = t_svc.get_round(comp.round_ids[-1])
    final_matches = t_svc.get_round_matches(final_round.id)
    assert len(final_matches) == 1
    advanced_ids = {final_matches[0].team_a_id, final_matches[0].team_b_id}
    assert advanced_ids == {m.team_a_id for m in matches}  # both round-1 winners (team_a in each, since A always won)
    shutil.rmtree(tmp)


def test_bye_handling():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env(n_teams=3)
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_SINGLE_ELIMINATION)
    matches = t_svc.generate_single_elimination(r.id)
    byes = [m for m in matches if m.is_bye]
    reals = [m for m in matches if not m.is_bye]
    assert len(byes) == 1 and len(reals) == 1
    bye = byes[0]
    assert bye.status == M_COMPLETED
    assert bye.winner_team_id == bye.team_a_id
    assert bye.team_b_id is None
    assert bye.team_a_id == teams[0]  # top seed (first added) gets the bye — documented, deterministic
    shutil.rmtree(tmp)


def test_competition_completion():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env(n_teams=2)
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    for m in matches:
        t_svc.prepare_match_for_start(m.id)
        t_svc.complete_match(m.id, OUTCOME_TEAM_A_WIN, m.team_a_id, 10.0)
    assert t_svc.get_round(r.id).status == R_COMPLETED
    completed = t_svc.complete_competition("champ")
    assert completed.status == "COMPLETED"
    assert completed.ended_at is not None
    shutil.rmtree(tmp)


def test_active_competition_edit_protection():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env(n_teams=2)
    _competition_with_teams(t_svc, challenge, teams)
    t_svc.mark_ready("champ")
    t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    t_svc.start_competition("champ")
    try:
        t_svc.update_competition("champ", challenge_id="some-other-id")
        raise AssertionError("structural edit on ACTIVE competition was accepted")
    except ValidationError as e:
        assert str(e) == "cannot_edit_locked_structure"
    try:
        t_svc.add_team("champ", "team-alpha")
        raise AssertionError("team roster edit on ACTIVE competition was accepted")
    except ValidationError as e:
        assert str(e) == "cannot_edit_locked_structure"
    shutil.rmtree(tmp)


def test_historical_match_reference_protection():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env(n_teams=2)
    _competition_with_teams(t_svc, challenge, teams)
    r = t_svc.create_round("champ", "Round 1", TYPE_ROUND_ROBIN)
    matches = t_svc.generate_round_robin(r.id)
    t_svc.mark_ready("champ")
    t_svc.start_competition("champ")
    t_svc.prepare_match_for_start(matches[0].id)
    t_svc.complete_match(matches[0].id, OUTCOME_TEAM_A_WIN, matches[0].team_a_id, 10.0)
    t_svc.pause_competition("champ")
    try:
        t_svc.delete_competition("champ")
        raise AssertionError("competition with completed match history was deleted")
    except ValidationError as e:
        assert str(e) == "cannot_delete_active"  # PAUSED still blocks delete
    shutil.rmtree(tmp)


# =========================================================== existing systems
def test_existing_engine_tests():
    engine = BattleEngine(AGGRESSIVE_CODE, open(BETA_PATH, encoding="utf-8").read())
    engine.start()
    for _ in range(30 * 60):
        engine.step(1 / 30)
        if engine.winner:
            break
    assert engine.winner is not None


def test_existing_team_tests():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    assert team_svc.get_team("team-alpha").name == "Team Alpha"
    shutil.rmtree(tmp)


def test_existing_challenge_tests():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    assert challenge.id == "tactical-battleship"
    shutil.rmtree(tmp)


def test_existing_submission_tests():
    tmp, team_svc, ch_svc, sub_svc, t_svc, challenge, teams = _fresh_env()
    active = sub_svc.get_active_submission("team-alpha", challenge.id)
    assert active is not None and active.status == "SUBMITTED"
    shutil.rmtree(tmp)


def test_existing_competition_tracker_tests():
    from engine.competition import CompetitionTracker
    tracker = CompetitionTracker(["Team Alpha", "Team Beta"])
    tracker.records["Team Alpha"].wins = 2
    assert tracker.ranked()[0].team == "Team Alpha"


if __name__ == "__main__":
    tests = [
        test_create_competition, test_get_competition, test_update_competition,
        test_delete_competition, test_competition_persistence, test_team_eligibility,
        test_duplicate_team_prevention, test_challenge_validation, test_competition_status_transitions,
        test_create_round, test_round_ordering, test_create_match,
        test_match_team_validation, test_match_submission_validation, test_match_challenge_validation,
        test_match_status_transitions, test_match_snapshot_creation, test_match_uses_exact_submission_versions,
        test_match_uses_exact_challenge_configuration, test_match_execution_through_existing_battle_engine,
        test_match_result_from_real_battle_engine_outcome, test_draw_handling,
        test_round_robin_pair_generation, test_no_duplicate_round_robin_pairs, test_no_self_match,
        test_single_elimination_bracket_generation, test_winner_advancement, test_bye_handling,
        test_competition_completion, test_active_competition_edit_protection, test_historical_match_reference_protection,
        test_existing_engine_tests, test_existing_team_tests, test_existing_challenge_tests,
        test_existing_submission_tests, test_existing_competition_tracker_tests,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print(f"\nALL {len(tests)} TOURNAMENT TESTS PASSED")
