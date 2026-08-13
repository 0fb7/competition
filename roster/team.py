"""Team/Member data model for Phase 1 (team management).

Deliberately named `roster/`, not `competition/` as the brief's example
suggested — this project already has `engine/competition.py`
(CompetitionTracker, battle win/loss/damage stats), and reusing that name
for a *different* concept (team roster persistence) would be confusing in
a codebase that already gives "competition" a specific meaning. `roster/`
sits next to the existing `teams/` (raw strategy scripts) without
colliding with either.

Score/wins/losses/damage_dealt/damage_received are part of the Team's
public shape (per spec section 3) but are NOT persisted here — they are
always populated live from the existing CompetitionTracker at read time
(see ui/teams_view.py). Persisting a second copy would create exactly the
duplicate scoring system the brief prohibits. `to_dict`/`from_dict` only
round-trip the identity/roster/assignment fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import re

TEAM_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{2,32}$")

STATUS_READY = "READY"
STATUS_NOT_READY = "NOT_READY"
STATUS_IN_BATTLE = "IN_BATTLE"
STATUS_DISABLED = "DISABLED"

# The engine only ever has two live ship slots (see engine/battle.py:
# ship_a/ship_b). Ship assignment maps a team onto one of these two real
# slots rather than inventing a separate ship catalog.
SHIP_SLOTS = ("alpha", "beta")


class ValidationError(ValueError):
    pass


@dataclass
class Member:
    member_id: str
    name: str
    email: str | None = None
    role: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Member":
        return Member(
            member_id=d["member_id"], name=d["name"],
            email=d.get("email"), role=d.get("role"),
        )


@dataclass
class Team:
    id: str
    name: str
    members: list[Member] = field(default_factory=list)
    ship_id: str | None = None          # "alpha" | "beta" | None
    submission_id: str | None = None    # path to the team's strategy file
    disabled: bool = False

    # Populated live from CompetitionTracker by the UI layer — never
    # persisted, never computed here. Defaults are display-only fallbacks
    # for a team that hasn't fought yet.
    score: int = 0
    wins: int = 0
    losses: int = 0
    damage_dealt: float = 0.0
    damage_received: float = 0.0
    status: str = STATUS_NOT_READY

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "members": [m.to_dict() for m in self.members],
            "ship_id": self.ship_id,
            "submission_id": self.submission_id,
            "disabled": self.disabled,
        }

    @staticmethod
    def from_dict(d: dict) -> "Team":
        return Team(
            id=d["id"],
            name=d["name"],
            members=[Member.from_dict(m) for m in d.get("members", [])],
            ship_id=d.get("ship_id"),
            submission_id=d.get("submission_id"),
            disabled=d.get("disabled", False),
        )
