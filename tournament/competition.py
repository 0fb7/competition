"""Competition data model for Phase 4.

Named `tournament/`, not `competition/` as the brief's example structure
suggested — this project already has `engine/competition.py`
(CompetitionTracker, battle win/loss/damage stats) and reusing that name
for a different concept (the orchestration layer above Teams/Challenges/
Submissions/BattleEngine) would collide semantically, same reasoning
Phase 1 used for `roster/` over `competition/`.

A Competition never duplicates Challenge rules or Submission code — it
only stores references (challenge_id, team_ids) that tournament_service.py
resolves through the existing ChallengeService/SubmissionService.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import re

COMPETITION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{2,48}$")

STATUS_DRAFT = "DRAFT"
STATUS_READY = "READY"
STATUS_ACTIVE = "ACTIVE"
STATUS_PAUSED = "PAUSED"
STATUS_COMPLETED = "COMPLETED"
STATUS_ARCHIVED = "ARCHIVED"
STATUSES = (STATUS_DRAFT, STATUS_READY, STATUS_ACTIVE, STATUS_PAUSED, STATUS_COMPLETED, STATUS_ARCHIVED)

# Structural fields that must not change once a competition has left DRAFT
# (spec section 14: "Do not allow changing: Challenge, Participating
# teams, Existing matches while ACTIVE" — extended here to also cover
# READY, since READY's whole definition is "teams/challenge/rounds are
# already validated and locked in").
STRUCTURAL_FIELDS = {"challenge_id", "team_ids"}
LOCKED_STATUSES = (STATUS_READY, STATUS_ACTIVE, STATUS_PAUSED, STATUS_COMPLETED, STATUS_ARCHIVED)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ValidationError(ValueError):
    pass


@dataclass
class Competition:
    id: str
    name: str
    description: str = ""
    challenge_id: str | None = None
    team_ids: list[str] = field(default_factory=list)
    round_ids: list[str] = field(default_factory=list)
    status: str = STATUS_DRAFT
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    started_at: str | None = None
    ended_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Competition":
        return Competition(
            id=d["id"], name=d["name"], description=d.get("description", ""),
            challenge_id=d.get("challenge_id"), team_ids=list(d.get("team_ids", [])),
            round_ids=list(d.get("round_ids", [])), status=d.get("status", STATUS_DRAFT),
            created_at=d.get("created_at", utc_now_iso()), updated_at=d.get("updated_at", utc_now_iso()),
            started_at=d.get("started_at"), ended_at=d.get("ended_at"),
        )
