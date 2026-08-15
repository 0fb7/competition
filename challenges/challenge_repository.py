"""JSON-backed persistence for Challenges. Pure CRUD, same pattern as
roster/team_repository.py — no validation, no engine knowledge. UI code
must never touch data/challenges.json directly; it goes through
ChallengeService, which goes through this repository.
"""

from __future__ import annotations

import os
import threading

from storage import read_json_file, write_json_file_atomic
from .challenge import Challenge


class ChallengeRepository:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            self._write({})

    def _read(self) -> dict:
        raw = read_json_file(self.path)
        return {cid: Challenge.from_dict(c) for cid, c in raw.items()}

    def _write(self, challenges: dict) -> None:
        raw = {cid: c.to_dict() if isinstance(c, Challenge) else c for cid, c in challenges.items()}
        write_json_file_atomic(self.path, raw)

    def create_challenge(self, challenge: Challenge) -> Challenge:
        with self._lock:
            challenges = self._read()
            if challenge.id in challenges:
                raise ValueError(f"challenge id already exists: {challenge.id}")
            challenges[challenge.id] = challenge
            self._write(challenges)
            return challenge

    def get_challenge(self, challenge_id: str) -> Challenge | None:
        with self._lock:
            return self._read().get(challenge_id)

    def get_all_challenges(self) -> list[Challenge]:
        with self._lock:
            return list(self._read().values())

    def update_challenge(self, challenge_id: str, **fields) -> Challenge:
        with self._lock:
            challenges = self._read()
            if challenge_id not in challenges:
                raise KeyError(challenge_id)
            challenge = challenges[challenge_id]
            for key, value in fields.items():
                if not hasattr(challenge, key):
                    raise ValueError(f"unknown challenge field: {key}")
                setattr(challenge, key, value)
            challenges[challenge_id] = challenge
            self._write(challenges)
            return challenge

    def delete_challenge(self, challenge_id: str) -> None:
        with self._lock:
            challenges = self._read()
            if challenge_id not in challenges:
                raise KeyError(challenge_id)
            del challenges[challenge_id]
            self._write(challenges)
