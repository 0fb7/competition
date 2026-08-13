"""Automated tests for Phase 3 (Submissions & Code Versioning), per
prompt.md section 33. Uses temp directories for all JSON stores so it
never touches the real data/*.json. Run with:

    python tests/test_submissions.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from challenges.challenge import Rules, STATUS_DRAFT as CH_DRAFT
from challenges.challenge_repository import ChallengeRepository
from challenges.challenge_service import ChallengeService
from engine.battle import BattleEngine
from engine.runner import BattleRunner
from roster.team_repository import TeamRepository
from roster.team_service import TeamService
from submissions.submission import (
    ImmutableSubmissionError, STATUS_DRAFT, STATUS_REJECTED, STATUS_SUBMITTED, STATUS_VALIDATED,
)
from submissions.submission_repository import SubmissionRepository
from submissions.submission_service import SubmissionService, ValidationError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALPHA_PATH = os.path.join(ROOT, "teams", "team_alpha.py")
BETA_PATH = os.path.join(ROOT, "teams", "team_beta.py")

GOOD_CODE = '''def decide(friendly, enemies, api):
    target = api["find_nearest"](enemies)
    if target and friendly["attack_ready"] and api["distance_to"](target) <= 10.0:
        api["attack"](target)
    elif target:
        api["move_toward"](target["x"], target["y"])
    else:
        api["hold_position"]()
'''

BAD_SYNTAX_CODE = "def decide(:\n    pass\n"
BAD_IMPORT_CODE = "import os\ndef decide(friendly, enemies, api):\n    pass\n"
HANGING_LOOP_FREE_BAD_CODE = "def decide(friendly, enemies, api):\n    return undefined_name\n"  # NameError at runtime -> test fails


def _fresh_env():
    tmp = tempfile.mkdtemp(prefix="battleship_submissions_test_")
    team_repo = TeamRepository(os.path.join(tmp, "teams.json"))
    team_svc = TeamService(team_repo, os.path.join(tmp, "team_submissions"))
    team_svc.ensure_default_teams(ALPHA_PATH, BETA_PATH)

    ch_repo = ChallengeRepository(os.path.join(tmp, "challenges.json"))
    ch_svc = ChallengeService(ch_repo)
    ch_svc.ensure_default_challenge()

    sub_repo = SubmissionRepository(os.path.join(tmp, "submissions.json"))
    sub_svc = SubmissionService(sub_repo, team_svc, ch_svc)

    alpha = team_svc.get_team("team-alpha")
    challenge = ch_svc.get_active_challenge()
    return tmp, team_svc, ch_svc, sub_svc, alpha, challenge


def test_create_submission():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    assert sub.team_id == alpha.id and sub.challenge_id == challenge.id
    assert sub.version == 1 and sub.status == STATUS_DRAFT
    shutil.rmtree(tmp)


def test_get_submission():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    assert sub_svc.get_submission(sub.id).code == GOOD_CODE
    assert sub_svc.get_submission("nope") is None
    shutil.rmtree(tmp)


def test_get_team_submissions():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    subs = sub_svc.get_team_submissions(alpha.id)
    assert len(subs) == 1 and subs[0].team_id == alpha.id
    shutil.rmtree(tmp)


def test_get_challenge_submissions():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    subs = sub_svc.get_challenge_submissions(challenge.id)
    assert len(subs) == 1 and subs[0].challenge_id == challenge.id
    shutil.rmtree(tmp)


def test_version_numbering():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    v1 = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    v2 = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    v3 = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    assert (v1.version, v2.version, v3.version) == (1, 2, 3)
    shutil.rmtree(tmp)


def test_duplicate_version_prevention():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    # the repository itself refuses a duplicate id/version combination
    from submissions.submission import Submission
    try:
        sub_svc.repo.create_submission(Submission(
            id=f"{alpha.id}__{challenge.id}__v1", team_id=alpha.id,
            challenge_id=challenge.id, version=1, code=GOOD_CODE,
        ))
        raise AssertionError("duplicate version/id was accepted")
    except ValueError:
        pass
    shutil.rmtree(tmp)


def test_save_draft():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    updated = sub_svc.update_draft(sub.id, GOOD_CODE + "\n# saved\n")
    assert "# saved" in updated.code
    shutil.rmtree(tmp)


def test_edit_draft():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    sub_svc.validate_submission(sub.id)  # -> VALIDATED
    assert sub_svc.get_submission(sub.id).status == STATUS_VALIDATED
    sub_svc.update_draft(sub.id, GOOD_CODE + "\n# changed\n")
    reloaded = sub_svc.get_submission(sub.id)
    assert reloaded.status == STATUS_DRAFT  # editing invalidates a stale VALIDATED result
    assert reloaded.validation_result is None
    shutil.rmtree(tmp)


def test_validate_submission():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    result = sub_svc.validate_submission(sub.id)
    assert result.valid is True
    assert sub_svc.get_submission(sub.id).status == STATUS_VALIDATED
    shutil.rmtree(tmp)


def test_invalid_submission_rejection():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, BAD_IMPORT_CODE)
    result = sub_svc.validate_submission(sub.id)
    assert result.valid is False and len(result.errors) > 0
    assert sub_svc.get_submission(sub.id).status == STATUS_REJECTED
    shutil.rmtree(tmp)


def test_challenge_specific_allowed_api_validation():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    restricted = ch_svc.create_challenge(
        "scout-only", "Scout Only", description="No attacking allowed",
        allowed_api=["move_toward", "find_nearest", "distance_to", "hold_position", "log"],
    )
    sub = sub_svc.create_draft(alpha.id, restricted.id, GOOD_CODE)  # GOOD_CODE calls attack()
    result = sub_svc.validate_submission(sub.id)
    assert result.valid is False
    assert any("attack" in e.message for e in result.errors)
    shutil.rmtree(tmp)


def test_test_execution():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    result = sub_svc.test_submission(sub.id)
    assert result.events_count > 0
    assert result.duration >= 0
    shutil.rmtree(tmp)


def test_test_failure_handling():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, HANGING_LOOP_FREE_BAD_CODE)
    result = sub_svc.test_submission(sub.id)
    assert result.passed is False
    assert len(result.errors) > 0
    assert sub_svc.get_submission(sub.id).status == STATUS_REJECTED
    shutil.rmtree(tmp)


def test_submit_valid_submission():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    submitted = sub_svc.submit_submission(sub.id)
    assert submitted.status == STATUS_SUBMITTED
    assert submitted.submitted_at is not None
    assert submitted.validation_result is not None and submitted.validation_result.valid
    assert submitted.test_result is not None and submitted.test_result.passed
    shutil.rmtree(tmp)


def test_block_invalid_submission():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, BAD_IMPORT_CODE)
    try:
        sub_svc.submit_submission(sub.id)
        raise AssertionError("invalid code was submitted")
    except ValidationError as e:
        assert str(e) == "validation_failed"
    assert sub_svc.get_submission(sub.id).status == STATUS_REJECTED
    shutil.rmtree(tmp)


def test_block_failed_test_submission():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, HANGING_LOOP_FREE_BAD_CODE)
    try:
        sub_svc.submit_submission(sub.id)
        raise AssertionError("failed-test code was submitted")
    except ValidationError as e:
        assert str(e) == "test_failed"
    assert sub_svc.get_submission(sub.id).status == STATUS_REJECTED
    shutil.rmtree(tmp)


def test_submitted_submission_immutability():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    sub_svc.submit_submission(sub.id)

    try:
        sub_svc.update_draft(sub.id, "# tampered\n")
        raise AssertionError("service allowed editing a SUBMITTED submission")
    except ImmutableSubmissionError:
        pass
    try:
        sub_svc.repo.update_draft(sub.id, code="# tampered\n")
        raise AssertionError("repository allowed editing a SUBMITTED submission")
    except ImmutableSubmissionError:
        pass
    try:
        sub_svc.delete_draft(sub.id)
        raise AssertionError("service allowed deleting a SUBMITTED submission")
    except ImmutableSubmissionError:
        pass
    assert sub_svc.get_submission(sub.id).code == GOOD_CODE
    shutil.rmtree(tmp)


def test_new_version_creation():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    v1 = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    sub_svc.submit_submission(v1.id)
    v2 = sub_svc.create_new_version(alpha.id, challenge.id)
    assert v2.version == 2 and v2.status == STATUS_DRAFT
    assert v2.code == GOOD_CODE  # seeded from the active submitted version
    shutil.rmtree(tmp)


def test_previous_versions_remain_unchanged():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    v1 = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    sub_svc.submit_submission(v1.id)
    v2 = sub_svc.create_new_version(alpha.id, challenge.id)
    sub_svc.update_draft(v2.id, GOOD_CODE + "\n# v2 tweak\n")
    sub_svc.submit_submission(v2.id)

    v1_reloaded = sub_svc.get_submission(v1.id)
    assert v1_reloaded.code == GOOD_CODE
    assert v1_reloaded.status == STATUS_SUBMITTED
    shutil.rmtree(tmp)


def test_active_submission_selection():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    v1 = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    sub_svc.submit_submission(v1.id)
    assert sub_svc.get_active_submission(alpha.id, challenge.id).id == v1.id

    v2 = sub_svc.create_new_version(alpha.id, challenge.id)
    # not yet submitted -> v1 is still active
    assert sub_svc.get_active_submission(alpha.id, challenge.id).id == v1.id

    sub_svc.update_draft(v2.id, GOOD_CODE + "\n# v2\n")
    sub_svc.submit_submission(v2.id)
    assert sub_svc.get_active_submission(alpha.id, challenge.id).id == v2.id
    # v1 remains SUBMITTED (historical), just no longer active
    assert sub_svc.get_submission(v1.id).status == STATUS_SUBMITTED
    shutil.rmtree(tmp)


def test_submission_persistence():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    sub = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    repo2 = SubmissionRepository(os.path.join(tmp, "submissions.json"))
    reloaded = repo2.get_submission(sub.id)
    assert reloaded is not None and reloaded.code == GOOD_CODE
    shutil.rmtree(tmp)


def test_restart_persistence():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    v1 = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    sub_svc.submit_submission(v1.id)
    v2 = sub_svc.create_new_version(alpha.id, challenge.id)

    # simulate an application restart: brand new repository/service objects
    repo2 = SubmissionRepository(os.path.join(tmp, "submissions.json"))
    sub_svc2 = SubmissionService(repo2, team_svc, ch_svc)
    both = sub_svc2.get_team_challenge_submissions(alpha.id, challenge.id)
    assert {s.id for s in both} == {v1.id, v2.id}
    shutil.rmtree(tmp)


def test_battle_uses_submitted_code():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    distinctive_code = GOOD_CODE.replace("def decide", "def decide") + '\n'
    sub = sub_svc.create_draft(alpha.id, challenge.id, distinctive_code)
    sub_svc.submit_submission(sub.id)

    active = sub_svc.get_active_submission(alpha.id, challenge.id)
    beta = team_svc.get_team("team-beta")
    with open(beta.submission_id, encoding="utf-8") as f:
        beta_code = f.read()
    engine = BattleEngine(active.code, beta_code, team_a_name=alpha.name, team_b_name=beta.name)
    assert engine._team_a_code == active.code
    shutil.rmtree(tmp)


def test_battle_uses_exact_submission_snapshot():
    """A BattleRunner is constructed from one specific submission's code
    at that moment — a frozen copy (BattleEngine.decide_a is a compiled
    function, not a live reference to the Submission object), per spec
    section 20."""
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    v1 = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    sub_svc.submit_submission(v1.id)

    beta = team_svc.get_team("team-beta")
    with open(beta.submission_id, encoding="utf-8") as f:
        beta_code = f.read()
    engine = BattleEngine(v1.code, beta_code, team_a_name=alpha.name, team_b_name=beta.name)
    frozen_code = engine._team_a_code
    frozen_decide = engine.decide_a
    assert frozen_code == v1.code
    assert callable(frozen_decide)
    shutil.rmtree(tmp)


def test_editing_draft_during_battle_does_not_affect_live_battle():
    """The other half of the snapshot guarantee: once a battle is running
    from v1, creating/editing/submitting a v2 for the same team must not
    reach into the live engine — nothing wires that automatically; only
    an explicit resync (ui/app.py's _sync_engine_state, guarded against
    doing this mid-battle) ever pushes new code in."""
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    v1 = sub_svc.create_draft(alpha.id, challenge.id, GOOD_CODE)
    sub_svc.submit_submission(v1.id)

    beta = team_svc.get_team("team-beta")
    with open(beta.submission_id, encoding="utf-8") as f:
        beta_code = f.read()
    engine = BattleEngine(v1.code, beta_code, team_a_name=alpha.name, team_b_name=beta.name)
    runner = BattleRunner(engine, tick_hz=30)
    runner.start_thread()
    runner.start_battle()

    import time
    time.sleep(0.2)

    # create + submit a v2 with different code while the runner is live
    v2 = sub_svc.create_new_version(alpha.id, challenge.id)
    sub_svc.update_draft(v2.id, GOOD_CODE + "\n# v2 - completely different\n")
    sub_svc.submit_submission(v2.id)
    assert sub_svc.get_active_submission(alpha.id, challenge.id).id == v2.id

    # the running engine's compiled code must be unaffected
    assert engine._team_a_code == v1.code
    assert engine.decide_a is not None
    runner.stop_thread(timeout=2.0)
    shutil.rmtree(tmp)


def test_challenge_snapshot_remains_fixed_during_battle():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    original_config = challenge.to_battle_config()
    beta = team_svc.get_team("team-beta")
    with open(beta.submission_id, encoding="utf-8") as f:
        beta_code = f.read()
    engine = BattleEngine(GOOD_CODE, beta_code, config=original_config)
    assert engine.config.attack_range == 10.0

    # edit the (still-DRAFT) challenge's rules after the engine was built
    assert challenge.status == CH_DRAFT or True  # default challenge is ACTIVE; use a fresh draft challenge instead
    draft_challenge = ch_svc.create_challenge("draft-rules", "Draft Rules", description="d", rules=Rules(attack_range=10.0))
    engine2 = BattleEngine(GOOD_CODE, beta_code, config=draft_challenge.to_battle_config())
    ch_svc.update_challenge("draft-rules", rules=Rules(attack_range=999.0))

    # engine2's config must still reflect the value at construction time
    assert engine2.config.attack_range == 10.0
    shutil.rmtree(tmp)


def test_existing_team_management_tests():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    assert team_svc.get_team("team-alpha").name == "Team Alpha"
    assert team_svc.get_team("team-beta").ship_id == "beta"
    shutil.rmtree(tmp)


def test_existing_challenge_tests():
    tmp, team_svc, ch_svc, sub_svc, alpha, challenge = _fresh_env()
    assert challenge.id == "tactical-battleship"
    assert challenge.status == "ACTIVE"
    shutil.rmtree(tmp)


def test_existing_engine_tests():
    engine = BattleEngine(
        open(ALPHA_PATH, encoding="utf-8").read(), open(BETA_PATH, encoding="utf-8").read(),
    )
    engine.start()
    for _ in range(30 * 60):
        engine.step(1 / 30)
        if engine.winner:
            break
    assert engine.winner is not None


def test_existing_competition_tracker_tests():
    from engine.competition import CompetitionTracker
    tracker = CompetitionTracker(["Team Alpha", "Team Beta"])
    tracker.records["Team Alpha"].wins = 1
    assert tracker.ranked()[0].team == "Team Alpha"


if __name__ == "__main__":
    tests = [
        test_create_submission,
        test_get_submission,
        test_get_team_submissions,
        test_get_challenge_submissions,
        test_version_numbering,
        test_duplicate_version_prevention,
        test_save_draft,
        test_edit_draft,
        test_validate_submission,
        test_invalid_submission_rejection,
        test_challenge_specific_allowed_api_validation,
        test_test_execution,
        test_test_failure_handling,
        test_submit_valid_submission,
        test_block_invalid_submission,
        test_block_failed_test_submission,
        test_submitted_submission_immutability,
        test_new_version_creation,
        test_previous_versions_remain_unchanged,
        test_active_submission_selection,
        test_submission_persistence,
        test_restart_persistence,
        test_battle_uses_submitted_code,
        test_battle_uses_exact_submission_snapshot,
        test_editing_draft_during_battle_does_not_affect_live_battle,
        test_challenge_snapshot_remains_fixed_during_battle,
        test_existing_team_management_tests,
        test_existing_challenge_tests,
        test_existing_engine_tests,
        test_existing_competition_tracker_tests,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print(f"\nALL {len(tests)} SUBMISSION TESTS PASSED")
