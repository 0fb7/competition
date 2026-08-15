"""JSON-backed persistence for historical MatchResults and their battle
event timelines. Same atomic-write pattern established in Phases 1-4
(write to .tmp, os.replace) — see tournament/tournament_repository.py.

Deliberately has NO update method for either collection. A MatchResult or
an event timeline, once written, cannot be edited through this repository
at all — immutability (spec section 4) is enforced by the absence of the
capability, not just a runtime check. `create_match_result` additionally
refuses a second write for the same id (spec section 19: match_id is the
uniqueness boundary).

Events are written once, in a single batch, when the match completes —
never incrementally per tick — so a running battle never touches disk
(spec section 28: live battle updates stay separate from historical
persistence, and the live Battle Arena must not slow down while results
are stored).
"""

from __future__ import annotations

import os
import threading

from storage import read_json_file, write_json_file_atomic
from .match_result import DuplicateResultError, MatchEvent, MatchResult


class ResultRepository:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._lock = threading.RLock()
        os.makedirs(data_dir, exist_ok=True)
        self._results_path = os.path.join(data_dir, "match_results.json")
        self._events_path = os.path.join(data_dir, "match_events.json")
        for path in (self._results_path, self._events_path):
            if not os.path.exists(path):
                self._write_raw(path, {})

    # ---- internal ----
    def _read_raw(self, path: str) -> dict:
        return read_json_file(path)

    def _write_raw(self, path: str, raw: dict) -> None:
        write_json_file_atomic(path, raw)

    # ============================================================= results
    def create_match_result(self, result: MatchResult) -> MatchResult:
        with self._lock:
            raw = self._read_raw(self._results_path)
            if result.id in raw:
                raise DuplicateResultError(result.id)
            raw[result.id] = result.to_dict()
            self._write_raw(self._results_path, raw)
            return result

    def get_match_result(self, match_id: str) -> MatchResult | None:
        with self._lock:
            raw = self._read_raw(self._results_path)
            d = raw.get(match_id)
            return MatchResult.from_dict(d) if d else None

    def get_all_match_results(self) -> list[MatchResult]:
        with self._lock:
            raw = self._read_raw(self._results_path)
            return [MatchResult.from_dict(d) for d in raw.values()]

    def get_competition_results(self, competition_id: str) -> list[MatchResult]:
        with self._lock:
            raw = self._read_raw(self._results_path)
            return [MatchResult.from_dict(d) for d in raw.values() if d.get("competition_id") == competition_id]

    # ============================================================== events
    def save_match_events(self, match_id: str, events: list[MatchEvent]) -> None:
        with self._lock:
            raw = self._read_raw(self._events_path)
            if match_id in raw:
                return  # already persisted — never overwritten (immutability + duplicate protection)
            raw[match_id] = [e.to_dict() for e in events]
            self._write_raw(self._events_path, raw)

    def get_match_events(self, match_id: str) -> list[MatchEvent]:
        with self._lock:
            raw = self._read_raw(self._events_path)
            return [MatchEvent.from_dict(d) for d in raw.get(match_id, [])]
