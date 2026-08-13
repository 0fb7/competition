"""JSON-backed persistence for teams. Pure CRUD — no validation, no
business rules (those live in team_service.py), no knowledge of the
battle engine. UI code must never touch data/teams.json directly; it
goes through TeamService, which goes through this repository.
"""

from __future__ import annotations

import json
import os
import threading

from .team import Member, Team


class TeamRepository:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            self._write({})

    # ---- internal ----
    def _read(self) -> dict:
        with open(self.path, encoding="utf-8") as f:
            raw = json.load(f)
        return {tid: Team.from_dict(t) for tid, t in raw.items()}

    def _write(self, teams: dict) -> None:
        raw = {tid: team.to_dict() if isinstance(team, Team) else team for tid, team in teams.items()}
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.path)

    # ---- team CRUD ----
    def create_team(self, team: Team) -> Team:
        with self._lock:
            teams = self._read()
            if team.id in teams:
                raise ValueError(f"team id already exists: {team.id}")
            teams[team.id] = team
            self._write(teams)
            return team

    def get_team(self, team_id: str) -> Team | None:
        with self._lock:
            return self._read().get(team_id)

    def get_all_teams(self) -> list[Team]:
        with self._lock:
            return list(self._read().values())

    def update_team(self, team_id: str, **fields) -> Team:
        with self._lock:
            teams = self._read()
            if team_id not in teams:
                raise KeyError(team_id)
            team = teams[team_id]
            for key, value in fields.items():
                if not hasattr(team, key):
                    raise ValueError(f"unknown team field: {key}")
                setattr(team, key, value)
            teams[team_id] = team
            self._write(teams)
            return team

    def delete_team(self, team_id: str) -> None:
        with self._lock:
            teams = self._read()
            if team_id not in teams:
                raise KeyError(team_id)
            del teams[team_id]
            self._write(teams)

    # ---- member CRUD ----
    def add_member(self, team_id: str, member: Member) -> Team:
        with self._lock:
            teams = self._read()
            if team_id not in teams:
                raise KeyError(team_id)
            team = teams[team_id]
            if any(m.member_id == member.member_id for m in team.members):
                raise ValueError(f"member id already exists on team: {member.member_id}")
            team.members.append(member)
            self._write(teams)
            return team

    def remove_member(self, team_id: str, member_id: str) -> Team:
        with self._lock:
            teams = self._read()
            if team_id not in teams:
                raise KeyError(team_id)
            team = teams[team_id]
            team.members = [m for m in team.members if m.member_id != member_id]
            self._write(teams)
            return team

    def update_member(self, team_id: str, member_id: str, **fields) -> Team:
        with self._lock:
            teams = self._read()
            if team_id not in teams:
                raise KeyError(team_id)
            team = teams[team_id]
            for m in team.members:
                if m.member_id == member_id:
                    for key, value in fields.items():
                        if not hasattr(m, key):
                            raise ValueError(f"unknown member field: {key}")
                        setattr(m, key, value)
                    self._write(teams)
                    return team
            raise KeyError(member_id)
