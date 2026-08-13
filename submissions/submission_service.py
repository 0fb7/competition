"""Validation + orchestration on top of SubmissionRepository. This is
what the UI talks to — never the repository directly.

Depends on TeamService and ChallengeService (read-only: "team must
exist", "challenge must exist and be usable") — a one-directional
dependency (Submission reads Team/Challenge; neither reads back), not a
cycle, so this doesn't break the section-30-style layering rule from
Phase 2. It deliberately does NOT import engine/runner.py or hold a
BattleRunner reference — validate/test/submit never touch live battle
state; see submissions/test_runner.py for how testing stays isolated.
"""

from __future__ import annotations

from typing import Optional

from challenges.challenge import STATUS_ARCHIVED as CHALLENGE_ARCHIVED
from engine.sandbox import collect_validation_issues

from .submission import (
    ImmutableSubmissionError, STATUS_DRAFT, STATUS_REJECTED, STATUS_SUBMITTED,
    STATUS_VALIDATED, Submission, TestResult, ValidationIssue, ValidationResult, utc_now_iso,
)
from .submission_repository import SubmissionRepository
from .test_runner import run_test


class ValidationError(ValueError):
    pass


class SubmissionService:
    def __init__(self, repository: SubmissionRepository, team_service, challenge_service):
        self.repo = repository
        self.team_service = team_service
        self.challenge_service = challenge_service

    # -------------------------------------------------------------- guards
    def _require_team(self, team_id: str):
        team = self.team_service.get_team(team_id)
        if team is None:
            raise ValidationError("team_not_found")
        return team

    def _require_usable_challenge(self, challenge_id: str):
        challenge = self.challenge_service.get_challenge(challenge_id)
        if challenge is None:
            raise ValidationError("challenge_not_found")
        if challenge.status == CHALLENGE_ARCHIVED:
            raise ValidationError("challenge_not_usable")
        return challenge

    def _next_version(self, team_id: str, challenge_id: str) -> int:
        existing = self.repo.get_team_challenge_submissions(team_id, challenge_id)
        return max((s.version for s in existing), default=0) + 1

    # ------------------------------------------------------------- reads
    def get_submission(self, submission_id: str) -> Optional[Submission]:
        return self.repo.get_submission(submission_id)

    def get_team_submissions(self, team_id: str) -> list[Submission]:
        return self.repo.get_team_submissions(team_id)

    def get_challenge_submissions(self, challenge_id: str) -> list[Submission]:
        return self.repo.get_challenge_submissions(challenge_id)

    def get_team_challenge_submissions(self, team_id: str, challenge_id: str) -> list[Submission]:
        return sorted(self.repo.get_team_challenge_submissions(team_id, challenge_id), key=lambda s: s.version)

    def get_active_submission(self, team_id: str, challenge_id: str) -> Optional[Submission]:
        """The version a real battle uses: the highest-version SUBMITTED
        submission for this (team, challenge). Derived at read time rather
        than a stored is_active flag — older SUBMITTED versions stay
        immutable history without needing to be "demoted" on every new
        submit (spec section 23's "choose the cleaner architecture")."""
        submitted = [
            s for s in self.repo.get_team_challenge_submissions(team_id, challenge_id)
            if s.status == STATUS_SUBMITTED
        ]
        return max(submitted, key=lambda s: s.version) if submitted else None

    def get_latest_submission(self, team_id: str, challenge_id: str) -> Optional[Submission]:
        all_subs = self.repo.get_team_challenge_submissions(team_id, challenge_id)
        return max(all_subs, key=lambda s: s.version) if all_subs else None

    def get_active_or_latest(self, team_id: str, challenge_id: str) -> Optional[Submission]:
        return self.get_active_submission(team_id, challenge_id) or self.get_latest_submission(team_id, challenge_id)

    # ------------------------------------------------------------ create
    def create_draft(self, team_id: str, challenge_id: str, code: str) -> Submission:
        self._require_team(team_id)
        self._require_usable_challenge(challenge_id)
        version = self._next_version(team_id, challenge_id)
        submission = Submission(
            id=f"{team_id}__{challenge_id}__v{version}", team_id=team_id,
            challenge_id=challenge_id, version=version, code=code, status=STATUS_DRAFT,
        )
        return self.repo.create_submission(submission)

    def ensure_starter_draft(self, team_id: str, challenge_id: str, starter_code: str) -> Submission:
        """Idempotent, and only for a (team, challenge) pair with no
        submissions at all yet. Starter code is always a DRAFT — never
        auto-submitted (spec section 25)."""
        existing = self.repo.get_team_challenge_submissions(team_id, challenge_id)
        if existing:
            return self.get_active_or_latest(team_id, challenge_id)
        return self.create_draft(team_id, challenge_id, starter_code)

    def create_new_version(self, team_id: str, challenge_id: str, starter_code: str = "") -> Submission:
        base = self.get_active_or_latest(team_id, challenge_id)
        code = base.code if base else starter_code
        return self.create_draft(team_id, challenge_id, code)

    # ------------------------------------------------------------- edit
    def update_draft(self, submission_id: str, code: str) -> Submission:
        submission = self.repo.get_submission(submission_id)
        if submission is None:
            raise KeyError(submission_id)
        if submission.status == STATUS_SUBMITTED:
            raise ImmutableSubmissionError("submitted code is immutable")
        if submission.code == code:
            # Nothing actually changed (e.g. the UI calls this to persist
            # the editor's current content before Test/Submit even when
            # the admin only just ran Validate) — a no-op save must not
            # wipe out a still-valid validation/test result for identical
            # code.
            return submission
        # The code DID change: any prior validate/test result was for
        # different code and is now stale.
        return self.repo.update_draft(
            submission_id, code=code, status=STATUS_DRAFT,
            validation_result=None, test_result=None, updated_at=utc_now_iso(),
        )

    def delete_draft(self, submission_id: str) -> None:
        submission = self.repo.get_submission(submission_id)
        if submission is None:
            raise KeyError(submission_id)
        if submission.status == STATUS_SUBMITTED:
            raise ImmutableSubmissionError("submitted code cannot be deleted")
        self.repo.delete_draft(submission_id)

    # --------------------------------------------------------- validate
    def validate_submission(self, submission_id: str) -> ValidationResult:
        submission = self.repo.get_submission(submission_id)
        if submission is None:
            raise KeyError(submission_id)
        if submission.status == STATUS_SUBMITTED:
            raise ImmutableSubmissionError("submitted code cannot be re-validated in place")

        challenge = self.challenge_service.get_challenge(submission.challenge_id)
        allowed_api = challenge.allowed_api if challenge else None
        raw_issues = collect_validation_issues(submission.code, allowed_api)
        result = ValidationResult(
            valid=not raw_issues,
            errors=[ValidationIssue(type=i["type"], message=i["message"], line=i["line"], column=i["column"]) for i in raw_issues],
        )
        new_status = STATUS_VALIDATED if result.valid else STATUS_REJECTED
        self.repo.update_draft(submission_id, validation_result=result, status=new_status, updated_at=utc_now_iso())
        return result

    # -------------------------------------------------------------- test
    def test_submission(self, submission_id: str) -> TestResult:
        submission = self.repo.get_submission(submission_id)
        if submission is None:
            raise KeyError(submission_id)
        if submission.status == STATUS_SUBMITTED:
            raise ImmutableSubmissionError("submitted code cannot be re-tested in place")

        challenge = self.challenge_service.get_challenge(submission.challenge_id)
        config = challenge.to_battle_config() if challenge else None
        result = run_test(submission.code, config)

        new_status = submission.status if result.passed else STATUS_REJECTED
        self.repo.update_draft(submission_id, test_result=result, status=new_status, updated_at=utc_now_iso())
        return result

    # ------------------------------------------------------------ submit
    def submit_submission(self, submission_id: str) -> Submission:
        """Validate -> Test -> Submit, always re-run fresh (never trusts a
        stale prior result) so a submission can't slip through on results
        computed against different code. Either failure blocks submission
        and leaves the record REJECTED with the failing result stored."""
        submission = self.repo.get_submission(submission_id)
        if submission is None:
            raise KeyError(submission_id)
        if submission.status == STATUS_SUBMITTED:
            raise ImmutableSubmissionError("already submitted")

        validation = self.validate_submission(submission_id)
        if not validation.valid:
            raise ValidationError("validation_failed")

        test_result = self.test_submission(submission_id)
        if not test_result.passed:
            raise ValidationError("test_failed")

        return self.repo.submit_submission(
            submission_id, status=STATUS_SUBMITTED, submitted_at=utc_now_iso(), updated_at=utc_now_iso(),
        )
