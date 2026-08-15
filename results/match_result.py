"""Historical result models for Phase 5.

A MatchResult is the permanent, immutable record of what a completed
tournament/match.py Match actually did. It does NOT replace Match — Match
stays the operational record (spec section 3: "A completed Match remains
the operational competition record"). MatchResult adds only what Match
does not already carry: real battle telemetry (HP remaining, damage
dealt/received) and immutable display-snapshot metadata (team/submission/
challenge names *as they were* at match completion, per section 5), so
history stays readable after a rename/new version/rules edit without
re-resolving anything current.

`id == match_id` by construction — this is the single natural uniqueness
boundary duplicate-result protection is built on (spec section 19).

Every numeric field here is either read straight off a real
BattleRunner.snapshot() (hp remaining) or summed from real, persisted
engine.events.Event objects emitted by BattleEngine.step() (damage dealt/
received) — nothing here is invented (spec section 3). For a BYE match,
or any match that reached ERROR before a battle ever produced telemetry,
these fields are left as None rather than fabricated zeros.

MatchEvent is a lightweight, JSON-friendly mirror of engine.events.Event
(same fields except `id`, which is battle-local and not meaningful once
persisted) — only event *kinds* the engine actually emits are ever stored;
see result_service.py's EVENT_KIND_KEYS map.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DuplicateResultError(ValueError):
    """Raised when a MatchResult already exists for a match_id — the
    duplicate-result-protection guard (spec section 19)."""


@dataclass
class MatchEvent:
    kind: str
    team: str
    message: str
    timestamp: float
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "MatchEvent":
        return MatchEvent(
            kind=d["kind"], team=d.get("team", ""), message=d.get("message", ""),
            timestamp=d.get("timestamp", 0.0), data=dict(d.get("data", {})),
        )


@dataclass
class MatchResult:
    id: str  # == match_id
    match_id: str
    competition_id: str
    round_id: str

    team_a_id: str
    team_b_id: str | None

    submission_a_id: str
    submission_b_id: str | None

    challenge_id: str

    outcome: str
    winner_team_id: str | None

    duration: float | None

    team_a_hp_remaining: float | None
    team_b_hp_remaining: float | None

    team_a_damage_dealt: float | None
    team_b_damage_dealt: float | None
    team_a_damage_received: float | None
    team_b_damage_received: float | None

    started_at: str | None
    ended_at: str | None

    # ---- immutable display-snapshot metadata (spec section 5) ----
    team_a_name_at_match: str
    team_b_name_at_match: str | None
    submission_a_version: int | None
    submission_b_version: int | None
    challenge_name_at_match: str
    challenge_difficulty_at_match: str | None

    is_bye: bool = False
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "MatchResult":
        return MatchResult(
            id=d["id"], match_id=d["match_id"], competition_id=d["competition_id"], round_id=d["round_id"],
            team_a_id=d["team_a_id"], team_b_id=d.get("team_b_id"),
            submission_a_id=d["submission_a_id"], submission_b_id=d.get("submission_b_id"),
            challenge_id=d["challenge_id"], outcome=d["outcome"], winner_team_id=d.get("winner_team_id"),
            duration=d.get("duration"),
            team_a_hp_remaining=d.get("team_a_hp_remaining"), team_b_hp_remaining=d.get("team_b_hp_remaining"),
            team_a_damage_dealt=d.get("team_a_damage_dealt"), team_b_damage_dealt=d.get("team_b_damage_dealt"),
            team_a_damage_received=d.get("team_a_damage_received"), team_b_damage_received=d.get("team_b_damage_received"),
            started_at=d.get("started_at"), ended_at=d.get("ended_at"),
            team_a_name_at_match=d.get("team_a_name_at_match", d["team_a_id"]),
            team_b_name_at_match=d.get("team_b_name_at_match"),
            submission_a_version=d.get("submission_a_version"), submission_b_version=d.get("submission_b_version"),
            challenge_name_at_match=d.get("challenge_name_at_match", ""),
            challenge_difficulty_at_match=d.get("challenge_difficulty_at_match"),
            is_bye=d.get("is_bye", False), created_at=d.get("created_at", utc_now_iso()),
        )
