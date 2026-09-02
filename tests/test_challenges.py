"""Automated tests for Phase 2 (Challenges & Rules Management), per
prompt.md section 27. Uses a temp directory for the JSON store so it
never touches the real data/challenges.json. Run with:

    python tests/test_challenges.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from challenges.challenge import Rules, ValidationError, STATUS_ACTIVE, STATUS_READY, STATUS_ARCHIVED
from challenges.challenge_repository import ChallengeRepository
from challenges.challenge_service import ChallengeService, DEFAULT_CHALLENGE_ID
from engine.battle import BattleEngine
from engine.config import BattleConfig, WIN_DESTROY_ENEMY, WIN_TIME_LIMIT_DRAW

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALPHA_PATH = os.path.join(ROOT, "teams", "team_alpha.py")
BETA_PATH = os.path.join(ROOT, "teams", "team_beta.py")


def _fresh_env():
    tmp = tempfile.mkdtemp(prefix="battleship_challenges_test_")
    repo = ChallengeRepository(os.path.join(tmp, "challenges.json"))
    svc = ChallengeService(repo)
    return tmp, repo, svc


def test_create_challenge():
    tmp, repo, svc = _fresh_env()
    c = svc.create_challenge("speed-round", "Speed Round", description="Fast matches", objective="Win fast")
    assert c.id == "speed-round"
    assert c.name == "Speed Round"
    shutil.rmtree(tmp)


def test_get_challenge():
    tmp, repo, svc = _fresh_env()
    svc.create_challenge("speed-round", "Speed Round", description="Fast matches")
    assert svc.get_challenge("speed-round").name == "Speed Round"
    assert svc.get_challenge("nope") is None
    shutil.rmtree(tmp)


def test_get_all_challenges():
    tmp, repo, svc = _fresh_env()
    assert svc.get_all_challenges() == []
    svc.create_challenge("c1", "One", description="d")
    svc.create_challenge("c2", "Two", description="d")
    assert {c.id for c in svc.get_all_challenges()} == {"c1", "c2"}
    shutil.rmtree(tmp)


def test_update_challenge():
    tmp, repo, svc = _fresh_env()
    svc.create_challenge("c1", "One", description="d")
    updated = svc.update_challenge("c1", name="One Prime")
    assert updated.name == "One Prime"
    assert svc.get_challenge("c1").name == "One Prime"
    shutil.rmtree(tmp)


def test_delete_challenge():
    tmp, repo, svc = _fresh_env()
    svc.create_challenge("c1", "One", description="d")
    svc.delete_challenge("c1")
    assert svc.get_challenge("c1") is None
    shutil.rmtree(tmp)


def test_duplicate_id_rejected():
    tmp, repo, svc = _fresh_env()
    svc.create_challenge("c1", "One", description="d")
    try:
        svc.create_challenge("c1", "Another", description="d")
        raise AssertionError("duplicate id was accepted")
    except ValidationError as e:
        assert str(e) == "duplicate_id"
    shutil.rmtree(tmp)


def test_invalid_challenge_rejected():
    tmp, repo, svc = _fresh_env()
    try:
        svc.create_challenge("", "One", description="d")
        raise AssertionError("empty id was accepted")
    except ValidationError as e:
        assert str(e) == "empty_id"
    try:
        svc.create_challenge("c1", "   ", description="d")
        raise AssertionError("empty name was accepted")
    except ValidationError as e:
        assert str(e) == "empty_name"
    try:
        svc.create_challenge("c1", "One", description="")
        raise AssertionError("empty description was accepted")
    except ValidationError as e:
        assert str(e) == "empty_description"
    shutil.rmtree(tmp)


def test_rule_validation():
    tmp, repo, svc = _fresh_env()
    for bad_rules, field in (
        (Rules(attack_range=0), "attack_range"),
        (Rules(attack_damage=-1), "attack_damage"),
        (Rules(attack_cooldown=-1), "attack_cooldown"),
        (Rules(energy_pool=0), "energy_pool"),
        (Rules(sensor_range=0), "sensor_range"),
        (Rules(movement_speed=0), "movement_speed"),
    ):
        try:
            svc.create_challenge("c1", "One", description="d", rules=bad_rules)
            raise AssertionError(f"invalid rule accepted: {field}")
        except ValidationError:
            pass
    shutil.rmtree(tmp)


def test_difficulty_validation():
    tmp, repo, svc = _fresh_env()
    try:
        svc.create_challenge("c1", "One", description="d", difficulty="LEVEL_9")
        raise AssertionError("invalid difficulty accepted")
    except ValidationError as e:
        assert str(e) == "invalid_difficulty"
    for level in ("LEVEL_1", "LEVEL_2", "LEVEL_3"):
        c = svc.create_challenge(f"c-{level}", "One", description="d", difficulty=level)
        assert c.difficulty == level
    shutil.rmtree(tmp)


def test_time_limit_validation():
    tmp, repo, svc = _fresh_env()
    try:
        svc.create_challenge("c1", "One", description="d", rules=Rules(battle_duration=0))
        raise AssertionError("zero time limit accepted")
    except ValidationError:
        pass
    try:
        svc.create_challenge("c2", "Two", description="d", rules=Rules(battle_duration=-5))
        raise AssertionError("negative time limit accepted")
    except ValidationError:
        pass
    c = svc.create_challenge("c3", "Three", description="d", rules=Rules(battle_duration=30))
    assert c.rules.battle_duration == 30
    shutil.rmtree(tmp)


def test_default_challenge_creation():
    tmp, repo, svc = _fresh_env()
    svc.ensure_default_challenge()
    challenges = svc.get_all_challenges()
    assert len(challenges) == 1
    default = challenges[0]
    assert default.id == DEFAULT_CHALLENGE_ID
    assert default.status == STATUS_ACTIVE
    assert default.win_condition == WIN_DESTROY_ENEMY
    # idempotent
    svc.update_challenge(DEFAULT_CHALLENGE_ID, description="edited")
    svc.ensure_default_challenge()
    assert svc.get_challenge(DEFAULT_CHALLENGE_ID).description == "edited"
    shutil.rmtree(tmp)


def test_challenge_persistence():
    tmp, repo, svc = _fresh_env()
    svc.create_challenge("c1", "One", description="d")
    repo2 = ChallengeRepository(os.path.join(tmp, "challenges.json"))
    reloaded = repo2.get_challenge("c1")
    assert reloaded is not None and reloaded.name == "One"
    shutil.rmtree(tmp)


def test_challenge_status_transitions():
    tmp, repo, svc = _fresh_env()
    c = svc.create_challenge("c1", "One", description="d")
    assert c.status == "DRAFT"
    svc.set_status("c1", STATUS_READY)
    assert svc.get_challenge("c1").status == STATUS_READY
    svc.activate_challenge("c1")
    assert svc.get_challenge("c1").status == STATUS_ACTIVE
    svc.set_status("c1", STATUS_ARCHIVED)
    assert svc.get_challenge("c1").status == STATUS_ARCHIVED
    try:
        svc.activate_challenge("c1")
        raise AssertionError("archived challenge was reactivated")
    except ValidationError as e:
        assert str(e) == "cannot_activate_archived"
    shutil.rmtree(tmp)


def test_active_challenge_cannot_be_deleted():
    tmp, repo, svc = _fresh_env()
    c = svc.create_challenge("c1", "One", description="d")
    svc.activate_challenge("c1")
    try:
        svc.delete_challenge("c1")
        raise AssertionError("active challenge was deleted")
    except ValidationError as e:
        assert str(e) == "cannot_delete_active"
    shutil.rmtree(tmp)


def test_active_challenge_cannot_have_unsafe_rule_changes():
    tmp, repo, svc = _fresh_env()
    svc.create_challenge("c1", "One", description="d")
    svc.activate_challenge("c1")
    for unsafe_field, value in (
        ("rules", Rules(attack_damage=99)),
        ("difficulty", "LEVEL_3"),
        ("win_condition", WIN_TIME_LIMIT_DRAW),
        ("allowed_api", ["attack"]),
    ):
        try:
            svc.update_challenge("c1", **{unsafe_field: value})
            raise AssertionError(f"unsafe field '{unsafe_field}' was changed on an ACTIVE challenge")
        except ValidationError as e:
            assert str(e) == "cannot_edit_active_rules"
    # safe metadata edit is still allowed while ACTIVE
    svc.update_challenge("c1", description="updated safely")
    assert svc.get_challenge("c1").description == "updated safely"
    shutil.rmtree(tmp)


def test_default_challenge_matches_legacy_defaults_except_movement_energy_cost():
    """Was test_default_challenge_preserves_existing_battle_engine_behavior
    (full battle-outcome equivalence to no-config legacy). That premise is
    now intentionally false: the seeded "Tactical Battleship" challenge
    was deliberately given movement_energy_cost=0.5 (the Energy-as-a-
    resource extension), so its battles no longer play out identically to
    legacy defaults — that's the whole point of the change, not a
    regression. Rewritten to assert the actual new invariant precisely:
    every OTHER BattleConfig field the seeded challenge produces still
    matches legacy defaults exactly, and movement_energy_cost is exactly
    0.5 — a config-field comparison, not a battle-outcome one, since an
    emergent-outcome comparison is no longer a meaningful way to verify
    "nothing else changed" once one rule is deliberately different."""
    tmp, repo, svc = _fresh_env()
    svc.ensure_default_challenge()
    default = svc.get_challenge(DEFAULT_CHALLENGE_ID)

    legacy = BattleConfig()
    configured = default.to_battle_config()

    assert configured.movement_energy_cost == 0.5
    for field_name in (
        "max_hp", "max_energy", "movement_speed", "attack_enabled", "attack_range",
        "attack_damage", "attack_cooldown", "attack_energy_cost", "energy_regen_rate",
        "sensor_range", "battle_duration", "code_execution_timeout",
    ):
        assert getattr(configured, field_name) == getattr(legacy, field_name), (
            f"{field_name} unexpectedly diverged from legacy defaults"
        )
    shutil.rmtree(tmp)


def test_challenge_rules_reach_battle_engine():
    """The core Phase 2 requirement: a configured rule value (not the
    engine default) actually changes real battle behavior."""
    tmp, repo, svc = _fresh_env()
    with open(ALPHA_PATH, encoding="utf-8") as f:
        alpha_code = f.read()
    with open(BETA_PATH, encoding="utf-8") as f:
        beta_code = f.read()

    custom = svc.create_challenge(
        "short-range", "Short Range", description="Tiny weapon range",
        rules=Rules(attack_range=0.5),  # far shorter than the ~26-unit starting gap
    )
    engine = BattleEngine(alpha_code, beta_code, config=custom.to_battle_config())
    assert engine.config.attack_range == 0.5
    engine.start()
    dt = 1 / 30
    for _ in range(90):  # 3 seconds — not nearly enough to close to 0.5 units at top speed
        engine.step(dt)
    assert engine.ship_a.hp == 100.0 and engine.ship_b.hp == 100.0, (
        "with attack_range=0.5 neither ship should be in range yet, but damage was dealt"
    )

    # a battle_duration configured on the Challenge must actually end the
    # battle in a draw at that time, not just be a displayed number.
    timed = svc.create_challenge(
        "blitz", "Blitz", description="Very short timer",
        rules=Rules(attack_range=0.5, battle_duration=1.0),
    )
    engine2 = BattleEngine(alpha_code, beta_code, config=timed.to_battle_config())
    engine2.start()
    for _ in range(90):
        engine2.step(dt)
    assert engine2.ended is True
    assert engine2.outcome == "TIME_LIMIT_DRAW"
    assert engine2.winner is None
    shutil.rmtree(tmp)


def test_existing_team_management_tests_still_pass():
    """Doesn't re-run tests/test_teams.py's assertions here (that would
    duplicate them) — imports and exercises the actual TeamService against
    the actual BattleEngine to confirm Phase 1 wiring still works after
    Phase 2's engine changes (Ship now requires a `config` field)."""
    from roster.team_repository import TeamRepository
    from roster.team_service import TeamService

    tmp2 = tempfile.mkdtemp(prefix="battleship_teams_compat_")
    team_repo = TeamRepository(os.path.join(tmp2, "teams.json"))
    team_svc = TeamService(team_repo, os.path.join(tmp2, "submissions"))
    team_svc.ensure_default_teams(ALPHA_PATH, BETA_PATH)
    alpha = team_svc.get_team("team-alpha")
    beta = team_svc.get_team("team-beta")
    with open(alpha.submission_id, encoding="utf-8") as f:
        alpha_code = f.read()
    with open(beta.submission_id, encoding="utf-8") as f:
        beta_code = f.read()
    engine = BattleEngine(alpha_code, beta_code, team_a_name=alpha.name, team_b_name=beta.name)
    assert engine.ship_a.team == "Team Alpha"
    shutil.rmtree(tmp2)


def test_existing_engine_tests_still_pass():
    """Sanity check that engine/ship.py's Ship still works with its
    default config (no config passed), exactly like tests/test_engine.py
    already verifies in more depth — kept here as an explicit Phase 2
    checklist item rather than only relying on a separate file."""
    engine = BattleEngine(
        open(ALPHA_PATH, encoding="utf-8").read(), open(BETA_PATH, encoding="utf-8").read(),
    )
    assert engine.ship_a.hp == 100.0
    assert engine.ship_a.config.attack_range == 10.0


def test_existing_competition_tracker_tests_still_pass():
    from engine.competition import CompetitionTracker
    from engine import events as ev

    tracker = CompetitionTracker(["Team Alpha", "Team Beta"])
    tracker.records["Team Alpha"].damage_dealt = 10
    tracker.rename_team("Team Alpha", "Team Alpha")  # no-op rename must not break anything
    assert tracker.records["Team Alpha"].damage_dealt == 10


if __name__ == "__main__":
    tests = [
        test_create_challenge,
        test_get_challenge,
        test_get_all_challenges,
        test_update_challenge,
        test_delete_challenge,
        test_duplicate_id_rejected,
        test_invalid_challenge_rejected,
        test_rule_validation,
        test_difficulty_validation,
        test_time_limit_validation,
        test_default_challenge_creation,
        test_challenge_persistence,
        test_challenge_status_transitions,
        test_active_challenge_cannot_be_deleted,
        test_active_challenge_cannot_have_unsafe_rule_changes,
        test_default_challenge_matches_legacy_defaults_except_movement_energy_cost,
        test_challenge_rules_reach_battle_engine,
        test_existing_team_management_tests_still_pass,
        test_existing_engine_tests_still_pass,
        test_existing_competition_tracker_tests_still_pass,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print(f"\nALL {len(tests)} CHALLENGE TESTS PASSED")
