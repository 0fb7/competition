"""Round data model for Phase 4. A Round belongs to exactly one
Competition and holds an ordered list of Match ids."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

from .competition import utc_now_iso

STATUS_PENDING = "PENDING"
STATUS_READY = "READY"
STATUS_ACTIVE = "ACTIVE"
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELLED = "CANCELLED"
STATUSES = (STATUS_PENDING, STATUS_READY, STATUS_ACTIVE, STATUS_COMPLETED, STATUS_CANCELLED)

TYPE_ROUND_ROBIN = "ROUND_ROBIN"
TYPE_SINGLE_ELIMINATION = "SINGLE_ELIMINATION"
TYPE_CUSTOM = "CUSTOM"
ROUND_TYPES = (TYPE_ROUND_ROBIN, TYPE_SINGLE_ELIMINATION, TYPE_CUSTOM)


@dataclass
class Round:
    id: str
    competition_id: str
    name: str
    order: int
    round_type: str = TYPE_CUSTOM
    status: str = STATUS_PENDING
    match_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    started_at: str | None = None
    ended_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Round":
        return Round(
            id=d["id"], competition_id=d["competition_id"], name=d["name"], order=d["order"],
            round_type=d.get("round_type", TYPE_CUSTOM), status=d.get("status", STATUS_PENDING),
            match_ids=list(d.get("match_ids", [])), created_at=d.get("created_at", utc_now_iso()),
            started_at=d.get("started_at"), ended_at=d.get("ended_at"),
        )
