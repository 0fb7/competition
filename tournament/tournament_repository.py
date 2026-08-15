"""JSON-backed persistence for Competitions, Rounds, and Matches.

One repository class managing three separate JSON files (they're one
tightly-coupled bounded context — a round-robin generation call creates
matches in the same breath a round is created), each with the same
atomic-write pattern established in Phases 1-3 (write to .tmp,
os.replace). Pure CRUD — no business rules, no engine knowledge; that's
tournament_service.py.
"""

from __future__ import annotations

import os
import threading

from storage import read_json_file, write_json_file_atomic
from .competition import Competition
from .match import Match
from .round import Round


class TournamentRepository:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._lock = threading.RLock()
        os.makedirs(data_dir, exist_ok=True)
        self._competitions_path = os.path.join(data_dir, "competitions.json")
        self._rounds_path = os.path.join(data_dir, "rounds.json")
        self._matches_path = os.path.join(data_dir, "matches.json")
        for path in (self._competitions_path, self._rounds_path, self._matches_path):
            if not os.path.exists(path):
                self._write(path, {})

    # ---- internal ----
    def _read(self, path: str, cls) -> dict:
        raw = read_json_file(path)
        return {k: cls.from_dict(v) for k, v in raw.items()}

    def _write(self, path: str, items: dict) -> None:
        raw = {k: (v.to_dict() if hasattr(v, "to_dict") else v) for k, v in items.items()}
        write_json_file_atomic(path, raw)

    # ============================================================ competitions
    def create_competition(self, competition: Competition) -> Competition:
        with self._lock:
            items = self._read(self._competitions_path, Competition)
            if competition.id in items:
                raise ValueError(f"competition id already exists: {competition.id}")
            items[competition.id] = competition
            self._write(self._competitions_path, items)
            return competition

    def get_competition(self, competition_id: str) -> Competition | None:
        with self._lock:
            return self._read(self._competitions_path, Competition).get(competition_id)

    def get_all_competitions(self) -> list[Competition]:
        with self._lock:
            return list(self._read(self._competitions_path, Competition).values())

    def update_competition(self, competition_id: str, **fields) -> Competition:
        with self._lock:
            items = self._read(self._competitions_path, Competition)
            if competition_id not in items:
                raise KeyError(competition_id)
            comp = items[competition_id]
            for key, value in fields.items():
                if not hasattr(comp, key):
                    raise ValueError(f"unknown competition field: {key}")
                setattr(comp, key, value)
            items[competition_id] = comp
            self._write(self._competitions_path, items)
            return comp

    def delete_competition(self, competition_id: str) -> None:
        with self._lock:
            items = self._read(self._competitions_path, Competition)
            if competition_id not in items:
                raise KeyError(competition_id)
            del items[competition_id]
            self._write(self._competitions_path, items)

    # ================================================================== rounds
    def create_round(self, round_obj: Round) -> Round:
        with self._lock:
            items = self._read(self._rounds_path, Round)
            if round_obj.id in items:
                raise ValueError(f"round id already exists: {round_obj.id}")
            items[round_obj.id] = round_obj
            self._write(self._rounds_path, items)
            return round_obj

    def get_round(self, round_id: str) -> Round | None:
        with self._lock:
            return self._read(self._rounds_path, Round).get(round_id)

    def get_all_rounds(self) -> list[Round]:
        with self._lock:
            return list(self._read(self._rounds_path, Round).values())

    def get_competition_rounds(self, competition_id: str) -> list[Round]:
        with self._lock:
            rounds = [r for r in self._read(self._rounds_path, Round).values() if r.competition_id == competition_id]
            return sorted(rounds, key=lambda r: r.order)

    def update_round(self, round_id: str, **fields) -> Round:
        with self._lock:
            items = self._read(self._rounds_path, Round)
            if round_id not in items:
                raise KeyError(round_id)
            r = items[round_id]
            for key, value in fields.items():
                if not hasattr(r, key):
                    raise ValueError(f"unknown round field: {key}")
                setattr(r, key, value)
            items[round_id] = r
            self._write(self._rounds_path, items)
            return r

    # ================================================================== matches
    def create_match(self, match: Match) -> Match:
        with self._lock:
            items = self._read(self._matches_path, Match)
            if match.id in items:
                raise ValueError(f"match id already exists: {match.id}")
            items[match.id] = match
            self._write(self._matches_path, items)
            return match

    def get_match(self, match_id: str) -> Match | None:
        with self._lock:
            return self._read(self._matches_path, Match).get(match_id)

    def get_all_matches(self) -> list[Match]:
        with self._lock:
            return list(self._read(self._matches_path, Match).values())

    def get_round_matches(self, round_id: str) -> list[Match]:
        with self._lock:
            matches = [m for m in self._read(self._matches_path, Match).values() if m.round_id == round_id]
            return sorted(matches, key=lambda m: m.match_number)

    def get_competition_matches(self, competition_id: str) -> list[Match]:
        with self._lock:
            return [m for m in self._read(self._matches_path, Match).values() if m.competition_id == competition_id]

    def update_match(self, match_id: str, **fields) -> Match:
        with self._lock:
            items = self._read(self._matches_path, Match)
            if match_id not in items:
                raise KeyError(match_id)
            m = items[match_id]
            for key, value in fields.items():
                if not hasattr(m, key):
                    raise ValueError(f"unknown match field: {key}")
                setattr(m, key, value)
            items[match_id] = m
            self._write(self._matches_path, items)
            return m
