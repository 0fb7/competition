"""Submission data model for Phase 3.

A Submission is one immutable-once-locked version of a Team's strategy
code for a specific Challenge. Versions are numbered per (team, challenge)
pair starting at 1. Once SUBMITTED, a submission's `code` never changes
again — see submission_service.py's guards, enforced independently at
both the service and repository layers (never relying on the UI alone).

`validation_result` / `test_result` are structured objects (ValidationResult
/ TestResult below), not free-form UI strings, per spec section 3.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

STATUS_DRAFT = "DRAFT"
STATUS_VALIDATED = "VALIDATED"
STATUS_SUBMITTED = "SUBMITTED"
STATUS_REJECTED = "REJECTED"
STATUSES = (STATUS_DRAFT, STATUS_VALIDATED, STATUS_SUBMITTED, STATUS_REJECTED)

# A SUBMITTED submission's code/status/version/team/challenge are frozen.
IMMUTABLE_FIELDS = {"code", "status", "version", "team_id", "challenge_id", "submitted_at"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_now = utc_now_iso


class ImmutableSubmissionError(ValueError):
    pass


@dataclass
class ValidationIssue:
    type: str
    message: str
    line: int | None = None
    column: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ValidationIssue":
        return ValidationIssue(type=d["type"], message=d["message"], line=d.get("line"), column=d.get("column"))


@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }

    @staticmethod
    def from_dict(d: dict) -> "ValidationResult":
        return ValidationResult(
            valid=d["valid"],
            errors=[ValidationIssue.from_dict(e) for e in d.get("errors", [])],
            warnings=[ValidationIssue.from_dict(w) for w in d.get("warnings", [])],
        )


# Phase 8: structured outcome distinguishing a genuine battle loss (FAILED)
# from the candidate's code never running to a real verdict at all (TIMEOUT,
# ERROR). `passed` stays as a derived bool (True only for PASSED) so every
# pre-Phase-8 caller that only ever looked at `.passed` keeps working
# unchanged.
TEST_PASSED = "PASSED"
TEST_FAILED = "FAILED"
TEST_TIMEOUT = "TIMEOUT"
TEST_ERROR = "ERROR"
TEST_STATUSES = (TEST_PASSED, TEST_FAILED, TEST_TIMEOUT, TEST_ERROR)


@dataclass
class TestResult:
    passed: bool
    status: str = TEST_FAILED
    winner: str | None = None
    duration: float = 0.0
    errors: list[str] = field(default_factory=list)
    final_hp: float | None = None
    damage_dealt: float = 0.0
    events_count: int = 0

    def __post_init__(self):
        # A result built with only `passed=True` and no explicit status
        # (e.g. by older/simpler call sites) should still read as PASSED.
        if self.passed and self.status == TEST_FAILED:
            self.status = TEST_PASSED

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "TestResult":
        passed = d["passed"]
        status = d.get("status") or (TEST_PASSED if passed else TEST_FAILED)
        return TestResult(
            passed=passed, status=status, winner=d.get("winner"), duration=d.get("duration", 0.0),
            errors=list(d.get("errors", [])), final_hp=d.get("final_hp"),
            damage_dealt=d.get("damage_dealt", 0.0), events_count=d.get("events_count", 0),
        )


@dataclass
class Submission:
    id: str
    team_id: str
    challenge_id: str
    version: int
    code: str
    status: str = STATUS_DRAFT
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    validation_result: ValidationResult | None = None
    test_result: TestResult | None = None
    submitted_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "challenge_id": self.challenge_id,
            "version": self.version,
            "code": self.code,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "validation_result": self.validation_result.to_dict() if self.validation_result else None,
            "test_result": self.test_result.to_dict() if self.test_result else None,
            "submitted_at": self.submitted_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "Submission":
        return Submission(
            id=d["id"], team_id=d["team_id"], challenge_id=d["challenge_id"], version=d["version"],
            code=d["code"], status=d.get("status", STATUS_DRAFT),
            created_at=d.get("created_at", _now()), updated_at=d.get("updated_at", _now()),
            validation_result=ValidationResult.from_dict(d["validation_result"]) if d.get("validation_result") else None,
            test_result=TestResult.from_dict(d["test_result"]) if d.get("test_result") else None,
            submitted_at=d.get("submitted_at"),
        )
