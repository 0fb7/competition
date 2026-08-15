"""Phase 7: shared, minimal JSON persistence helpers.

Every repository (roster/, challenges/, submissions/, tournament/,
results/) already used the same hand-rolled pattern independently: read
the whole file, mutate the in-memory dict, atomic-write it back
(.tmp + os.replace). This module doesn't change that pattern — it just
gives it ONE shared implementation so "what happens when the file is
missing" and "what happens when the file is corrupted" are answered
identically everywhere, instead of five slightly-different copies that
could drift (spec section 11: "malformed persistence data must fail
gracefully... application should not crash with an opaque traceback").

Deliberately NOT overengineered (spec section 11: "do not overengineer"):
no schema validation, no versioning, no automatic repair. A corrupted
file raises one clearly-typed exception that repositories can catch and
turn into a controlled, attributable error — it is never silently
overwritten, and valid data is never touched just because loading it
happened to fail once.
"""

from __future__ import annotations

import json
import os
import threading

_write_lock = threading.RLock()


class CorruptedDataError(Exception):
    """Raised when a JSON data file exists but cannot be parsed as valid
    JSON, or does not contain a JSON object at the top level. Repository
    callers should let this propagate (or catch it to show a controlled,
    attributable message) rather than silently discarding/overwriting
    the file — the whole point is that a corrupted file is a real
    problem an administrator should know about, not something to paper
    over automatically."""


def read_json_file(path: str) -> dict:
    """Returns {} for a file that does not exist yet (spec section 11:
    "missing persistence files" must not crash). Raises
    CorruptedDataError — never a raw json.JSONDecodeError/OSError — for
    a file that exists but can't be read as a JSON object, so every
    repository's failure mode is the same, catchable type."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        raise CorruptedDataError(f"{path} is corrupted or unreadable: {e}") from e
    if not isinstance(data, dict):
        raise CorruptedDataError(f"{path} does not contain a JSON object at the top level")
    return data


def write_json_file_atomic(path: str, data: dict) -> None:
    """Write-to-.tmp-then-os.replace — the exact pattern every
    repository already used independently, now shared. os.replace() is
    atomic on both Windows and POSIX, so a process interrupted mid-write
    (spec section 11: "application interruption during write") leaves
    either the old file intact or the new one complete — never a
    half-written file in the real path."""
    with _write_lock:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
