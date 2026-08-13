"""Cross-battle competition stats (wins/losses/damage/score), driven only
by real BATTLE_WON / DAMAGE events out of engine/events.py. This is what
ui/scoreboard.py reads — it never invents standings.

Score formula is a deliberate, disclosed design choice (not a fabricated
number): 50 points per win + 1 point per point of damage dealt, accrued
across resets for the lifetime of the app/session.
"""

from dataclasses import dataclass, field

from . import events as ev


@dataclass
class TeamRecord:
    team: str
    wins: int = 0
    losses: int = 0
    damage_dealt: float = 0.0
    damage_received: float = 0.0

    @property
    def score(self) -> int:
        return int(self.wins * 50 + self.damage_dealt)


class CompetitionTracker:
    def __init__(self, team_names: list[str]):
        self.records: dict[str, TeamRecord] = {name: TeamRecord(name) for name in team_names}

    def ingest(self, new_events: list[ev.Event]) -> None:
        for evt in new_events:
            if evt.kind == ev.DAMAGE:
                if evt.team in self.records:
                    self.records[evt.team].damage_dealt += evt.data.get("amount", 0.0)
                target_team = evt.data.get("target_team")
                if target_team in self.records:
                    self.records[target_team].damage_received += evt.data.get("amount", 0.0)
            elif evt.kind == ev.BATTLE_WON:
                winner = evt.team
                if winner in self.records:
                    self.records[winner].wins += 1
                for name, rec in self.records.items():
                    if name != winner:
                        rec.losses += 1

    def ranked(self) -> list[TeamRecord]:
        return sorted(self.records.values(), key=lambda r: r.score, reverse=True)

    def rename_team(self, old_name: str, new_name: str) -> None:
        """Migrates an accumulated record to a new key when a team is
        renamed (roster/team_service.py), so wins/losses/damage survive
        the rename instead of silently starting a fresh record under the
        new name. Not a new scoring mechanism — just a key migration."""
        if old_name == new_name or old_name not in self.records:
            return
        rec = self.records.pop(old_name)
        rec.team = new_name
        if new_name in self.records:
            existing = self.records[new_name]
            rec.wins += existing.wins
            rec.losses += existing.losses
            rec.damage_dealt += existing.damage_dealt
            rec.damage_received += existing.damage_received
        self.records[new_name] = rec

    def ensure_team(self, name: str) -> None:
        """Registers a team that didn't exist when the tracker was
        constructed (e.g. created after the app started), so it appears
        in the leaderboard with a zeroed record instead of being absent
        until its first event."""
        if name not in self.records:
            self.records[name] = TeamRecord(name)
