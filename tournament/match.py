"""Match data model for Phase 4.

Stores the EXACT submission ids used (never just team ids) — this is
what gives a completed match historical determinism: even after a team
submits v4, a completed Match record still shows precisely which version
(e.g. v3) it actually fought with.

A BYE match (section 19) has team_b_id/submission_b_id = None and
is_bye = True; it is never handed to BattleEngine — team_a advances
immediately at creation time.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

from .competition import utc_now_iso

STATUS_PENDING = "PENDING"
STATUS_READY = "READY"
STATUS_RUNNING = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELLED = "CANCELLED"
STATUS_ERROR = "ERROR"
STATUSES = (STATUS_PENDING, STATUS_READY, STATUS_RUNNING, STATUS_COMPLETED, STATUS_CANCELLED, STATUS_ERROR)

OUTCOME_TEAM_A_WIN = "TEAM_A_WIN"
OUTCOME_TEAM_B_WIN = "TEAM_B_WIN"
OUTCOME_DRAW = "DRAW"
OUTCOME_ERROR = "ERROR"
OUTCOME_CANCELLED = "CANCELLED"
OUTCOMES = (OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN, OUTCOME_DRAW, OUTCOME_ERROR, OUTCOME_CANCELLED)


@dataclass
class Match:
    id: str
    competition_id: str
    round_id: str
    match_number: int
    team_a_id: str
    team_b_id: str | None
    submission_a_id: str
    submission_b_id: str | None
    challenge_id: str
    status: str = STATUS_PENDING
    winner_team_id: str | None = None
    outcome: str | None = None
    created_at: str = None
    started_at: str | None = None
    ended_at: str | None = None
    battle_duration: float | None = None
    is_bye: bool = False

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = utc_now_iso()

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Match":
        return Match(
            id=d["id"], competition_id=d["competition_id"], round_id=d["round_id"],
            match_number=d["match_number"], team_a_id=d["team_a_id"], team_b_id=d.get("team_b_id"),
            submission_a_id=d["submission_a_id"], submission_b_id=d.get("submission_b_id"),
            challenge_id=d["challenge_id"], status=d.get("status", STATUS_PENDING),
            winner_team_id=d.get("winner_team_id"), outcome=d.get("outcome"),
            created_at=d.get("created_at", utc_now_iso()), started_at=d.get("started_at"),
            ended_at=d.get("ended_at"), battle_duration=d.get("battle_duration"),
            is_bye=d.get("is_bye", False),
        )
