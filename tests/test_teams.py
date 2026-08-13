"""Automated tests for Phase 1 (Teams & Members Management), per
prompt.md section 22. Uses a temp directory for the JSON store and
submissions so it never touches the real data/teams.json. Run with:

    python tests/test_teams.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.battle import BattleEngine
from engine.competition import CompetitionTracker
from roster.team import Member, Team, ValidationError
from roster.team_repository import TeamRepository
from roster.team_service import TeamService

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALPHA_PATH = os.path.join(ROOT, "teams", "team_alpha.py")
BETA_PATH = os.path.join(ROOT, "teams", "team_beta.py")


def _fresh_env():
    tmp = tempfile.mkdtemp(prefix="battleship_teams_test_")
    repo = TeamRepository(os.path.join(tmp, "teams.json"))
    comp = CompetitionTracker([])
    svc = TeamService(repo, os.path.join(tmp, "submissions"), competition_tracker=comp)
    return tmp, repo, svc, comp


def test_create_team():
    tmp, repo, svc, comp = _fresh_env()
    team = svc.create_team("Team Gamma", team_id="team-gamma")
    assert team.id == "team-gamma"
    assert team.name == "Team Gamma"
    assert os.path.exists(team.submission_id), "submission stub was not created"
    shutil.rmtree(tmp)


def test_get_team():
    tmp, repo, svc, comp = _fresh_env()
    svc.create_team("Team Gamma", team_id="team-gamma")
    fetched = svc.get_team("team-gamma")
    assert fetched is not None and fetched.name == "Team Gamma"
    assert svc.get_team("does-not-exist") is None
    shutil.rmtree(tmp)


def test_get_all_teams():
    tmp, repo, svc, comp = _fresh_env()
    assert svc.get_all_teams() == []
    svc.create_team("Team Gamma", team_id="team-gamma")
    svc.create_team("Team Delta", team_id="team-delta")
    all_teams = {t.id for t in svc.get_all_teams()}
    assert all_teams == {"team-gamma", "team-delta"}
    shutil.rmtree(tmp)


def test_update_team():
    tmp, repo, svc, comp = _fresh_env()
    svc.create_team("Team Gamma", team_id="team-gamma")
    updated = svc.update_team("team-gamma", name="Team Gamma Prime")
    assert updated.name == "Team Gamma Prime"
    assert svc.get_team("team-gamma").name == "Team Gamma Prime"
    shutil.rmtree(tmp)


def test_delete_team():
    tmp, repo, svc, comp = _fresh_env()
    svc.create_team("Team Gamma", team_id="team-gamma")
    svc.delete_team("team-gamma")
    assert svc.get_team("team-gamma") is None
    shutil.rmtree(tmp)


def test_duplicate_team_id_rejected():
    tmp, repo, svc, comp = _fresh_env()
    svc.create_team("Team Gamma", team_id="team-gamma")
    try:
        svc.create_team("Another Team", team_id="team-gamma")
        raise AssertionError("duplicate team id was accepted")
    except ValidationError as e:
        assert str(e) == "duplicate_id"
    shutil.rmtree(tmp)


def test_invalid_team_rejected():
    tmp, repo, svc, comp = _fresh_env()
    try:
        svc.create_team("   ")  # empty name after strip
        raise AssertionError("empty name was accepted")
    except ValidationError as e:
        assert str(e) == "empty_name"
    try:
        svc.create_team("Valid Name", team_id="bad id with spaces!")
        raise AssertionError("invalid team id characters were accepted")
    except ValidationError as e:
        assert str(e) == "invalid_id"
    shutil.rmtree(tmp)


def test_add_member():
    tmp, repo, svc, comp = _fresh_env()
    svc.create_team("Team Gamma", team_id="team-gamma")
    team = svc.add_member("team-gamma", "Sara")
    assert [m.name for m in team.members] == ["Sara"]
    try:
        svc.add_member("team-gamma", "   ")
        raise AssertionError("empty member name was accepted")
    except ValidationError:
        pass
    shutil.rmtree(tmp)


def test_remove_member():
    tmp, repo, svc, comp = _fresh_env()
    svc.create_team("Team Gamma", team_id="team-gamma")
    team = svc.add_member("team-gamma", "Sara")
    member_id = team.members[0].member_id
    team = svc.remove_member("team-gamma", member_id)
    assert team.members == []
    shutil.rmtree(tmp)


def test_ship_assignment():
    tmp, repo, svc, comp = _fresh_env()
    svc.create_team("Team Gamma", team_id="team-gamma")
    svc.create_team("Team Delta", team_id="team-delta")
    svc.assign_ship("team-gamma", "alpha")
    assert svc.get_team("team-gamma").ship_id == "alpha"
    try:
        svc.assign_ship("team-delta", "alpha")
        raise AssertionError("assigning an already-taken slot was accepted")
    except ValidationError as e:
        assert str(e) == "ship_already_assigned"
    svc.assign_ship("team-gamma", None)
    svc.assign_ship("team-delta", "alpha")  # now free
    assert svc.get_team("team-delta").ship_id == "alpha"
    shutil.rmtree(tmp)


def test_persistence_across_repository_instances():
    tmp, repo, svc, comp = _fresh_env()
    svc.create_team("Team Gamma", team_id="team-gamma")
    svc.add_member("team-gamma", "Sara")

    repo2 = TeamRepository(os.path.join(tmp, "teams.json"))
    reloaded = repo2.get_team("team-gamma")
    assert reloaded is not None
    assert reloaded.name == "Team Gamma"
    assert [m.name for m in reloaded.members] == ["Sara"]
    shutil.rmtree(tmp)


def test_initial_alpha_beta_migration():
    tmp, repo, svc, comp = _fresh_env()
    svc.ensure_default_teams(ALPHA_PATH, BETA_PATH)
    teams = {t.id: t for t in svc.get_all_teams()}
    assert set(teams) == {"team-alpha", "team-beta"}
    assert teams["team-alpha"].name == "Team Alpha"
    assert teams["team-alpha"].ship_id == "alpha"
    assert teams["team-alpha"].submission_id == ALPHA_PATH
    assert teams["team-beta"].ship_id == "beta"

    # idempotent: calling again must not duplicate or reset edits
    svc.update_team("team-alpha", name="Renamed Alpha")
    svc.ensure_default_teams(ALPHA_PATH, BETA_PATH)
    assert svc.get_team("team-alpha").name == "Renamed Alpha"
    shutil.rmtree(tmp)


def test_existing_battle_engine_compatibility():
    """The migrated teams' code must still run unmodified through the
    existing, untouched BattleEngine/sandbox — team management must not
    require rewriting team_alpha.py/team_beta.py."""
    tmp, repo, svc, comp = _fresh_env()
    svc.ensure_default_teams(ALPHA_PATH, BETA_PATH)
    alpha = svc.get_team("team-alpha")
    beta = svc.get_team("team-beta")
    with open(alpha.submission_id, encoding="utf-8") as f:
        alpha_code = f.read()
    with open(beta.submission_id, encoding="utf-8") as f:
        beta_code = f.read()

    engine = BattleEngine(alpha_code, beta_code, team_a_name=alpha.name, team_b_name=beta.name)
    assert engine.ship_a.team == "Team Alpha"
    assert engine.ship_b.team == "Team Beta"
    engine.start()
    for _ in range(30 * 60):
        engine.step(1 / 30)
        if engine.winner:
            break
    assert engine.winner in ("Team Alpha", "Team Beta")
    shutil.rmtree(tmp)


def test_existing_competition_statistics_compatibility():
    """Team Management must consume CompetitionTracker, not duplicate it:
    renaming a team must migrate its accumulated record (not reset it),
    and the scoring formula must be untouched."""
    tmp, repo, svc, comp = _fresh_env()
    svc.ensure_default_teams(ALPHA_PATH, BETA_PATH)
    comp.ensure_team("Team Alpha")
    comp.ensure_team("Team Beta")
    comp.records["Team Alpha"].wins = 2
    comp.records["Team Alpha"].damage_dealt = 40.0

    svc.update_team("team-alpha", name="Alpha Squadron")

    assert "Alpha Squadron" in comp.records
    assert "Team Alpha" not in comp.records
    rec = comp.records["Alpha Squadron"]
    assert rec.wins == 2
    assert rec.damage_dealt == 40.0
    assert rec.score == 2 * 50 + 40  # unchanged scoring formula
    shutil.rmtree(tmp)


if __name__ == "__main__":
    tests = [
        test_create_team,
        test_get_team,
        test_get_all_teams,
        test_update_team,
        test_delete_team,
        test_duplicate_team_id_rejected,
        test_invalid_team_rejected,
        test_add_member,
        test_remove_member,
        test_ship_assignment,
        test_persistence_across_repository_instances,
        test_initial_alpha_beta_migration,
        test_existing_battle_engine_compatibility,
        test_existing_competition_statistics_compatibility,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print(f"\nALL {len(tests)} TEAM TESTS PASSED")
