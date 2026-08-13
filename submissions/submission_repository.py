"""JSON-backed persistence for Submissions. Same pattern as
roster/team_repository.py and challenges/challenge_repository.py.

Unlike those two, this repository also enforces immutability of
SUBMITTED submissions itself — not just SubmissionService — per spec
section 14 ("The repository should also prevent accidental mutation
where practical. Never rely only on UI restrictions."). update_draft()
refuses to touch a submission whose current persisted status is
SUBMITTED, independent of whatever the caller thinks the status is.
"""

from __future__ import annotations

import json
import os
import threading

from .submission import ImmutableSubmissionError, STATUS_SUBMITTED, Submission


class SubmissionRepository:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            self._write({})

    def _read(self) -> dict:
        with open(self.path, encoding="utf-8") as f:
            raw = json.load(f)
        return {sid: Submission.from_dict(s) for sid, s in raw.items()}

    def _write(self, submissions: dict) -> None:
        raw = {sid: s.to_dict() if isinstance(s, Submission) else s for sid, s in submissions.items()}
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.path)

    # ---- create / read ----
    def create_submission(self, submission: Submission) -> Submission:
        with self._lock:
            submissions = self._read()
            if submission.id in submissions:
                raise ValueError(f"submission id already exists: {submission.id}")
            submissions[submission.id] = submission
            self._write(submissions)
            return submission

    def get_submission(self, submission_id: str) -> Submission | None:
        with self._lock:
            return self._read().get(submission_id)

    def get_all_submissions(self) -> list[Submission]:
        with self._lock:
            return list(self._read().values())

    def get_team_submissions(self, team_id: str) -> list[Submission]:
        with self._lock:
            return [s for s in self._read().values() if s.team_id == team_id]

    def get_challenge_submissions(self, challenge_id: str) -> list[Submission]:
        with self._lock:
            return [s for s in self._read().values() if s.challenge_id == challenge_id]

    def get_team_challenge_submissions(self, team_id: str, challenge_id: str) -> list[Submission]:
        with self._lock:
            return [
                s for s in self._read().values()
                if s.team_id == team_id and s.challenge_id == challenge_id
            ]

    # ---- mutation (drafts only — SUBMITTED is frozen here too) ----
    def update_draft(self, submission_id: str, **fields) -> Submission:
        with self._lock:
            submissions = self._read()
            if submission_id not in submissions:
                raise KeyError(submission_id)
            existing = submissions[submission_id]
            if existing.status == STATUS_SUBMITTED:
                raise ImmutableSubmissionError(
                    f"submission {submission_id} is SUBMITTED and immutable"
                )
            for key, value in fields.items():
                if not hasattr(existing, key):
                    raise ValueError(f"unknown submission field: {key}")
                setattr(existing, key, value)
            submissions[submission_id] = existing
            self._write(submissions)
            return existing

    def submit_submission(self, submission_id: str, **fields) -> Submission:
        """The one write path allowed to move a submission INTO
        STATUS_SUBMITTED (fields must include status=STATUS_SUBMITTED).
        Separate from update_draft so a caller can't accidentally submit
        through the "just editing a draft" code path."""
        with self._lock:
            submissions = self._read()
            if submission_id not in submissions:
                raise KeyError(submission_id)
            existing = submissions[submission_id]
            if existing.status == STATUS_SUBMITTED:
                raise ImmutableSubmissionError(
                    f"submission {submission_id} is already SUBMITTED"
                )
            for key, value in fields.items():
                if not hasattr(existing, key):
                    raise ValueError(f"unknown submission field: {key}")
                setattr(existing, key, value)
            submissions[submission_id] = existing
            self._write(submissions)
            return existing

    def delete_draft(self, submission_id: str) -> None:
        with self._lock:
            submissions = self._read()
            if submission_id not in submissions:
                raise KeyError(submission_id)
            if submissions[submission_id].status == STATUS_SUBMITTED:
                raise ImmutableSubmissionError(
                    f"submission {submission_id} is SUBMITTED and cannot be deleted"
                )
            del submissions[submission_id]
            self._write(submissions)
