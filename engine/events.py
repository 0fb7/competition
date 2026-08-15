"""Structured battle events.

engine/battle.py already keeps a human-readable `self.log: list[str]` for
the pygame console. This module adds a *typed* companion so UI code (the
CustomTkinter dashboard, the code->battle pipeline visualization) can react
to specific event kinds instead of parsing log strings.

This is additive only: nothing that already reads `engine.log` is affected.
"""

from dataclasses import dataclass, field
import itertools
import time
from typing import Any


_id_counter = itertools.count(1)

# Event kinds emitted by BattleEngine.step()
CODE_EXECUTED = "code_executed"
CODE_ERROR = "code_error"
# Phase 7: a participant's decide() exceeded engine.config.code_execution_timeout
# and its isolated worker was forcibly terminated — deliberately a
# DIFFERENT kind from CODE_ERROR (a raised exception) so the two are
# never conflated in events/alerts/team-status (spec section 5/9).
CODE_TIMEOUT = "code_timeout"
TARGET_ACQUIRED = "target_acquired"
ATTACK = "attack"
DAMAGE = "damage"
DESTROYED = "destroyed"
BATTLE_WON = "battle_won"
BATTLE_DRAW = "battle_draw"


@dataclass
class Event:
    id: int
    kind: str
    team: str
    message: str
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Append-only event list with a hard cap so long battles don't leak
    memory. Not thread-safe by itself — BattleRunner (engine/runner.py)
    is responsible for only ever calling engine.step() from one thread."""

    def __init__(self, max_events: int = 500):
        self._events: list[Event] = []
        self._max = max_events

    def emit(self, kind: str, team: str, message: str, **data) -> Event:
        evt = Event(id=next(_id_counter), kind=kind, team=team, message=message, data=data)
        self._events.append(evt)
        if len(self._events) > self._max:
            self._events = self._events[-self._max:]
        return evt

    def all(self) -> list[Event]:
        return list(self._events)

    def since(self, last_id: int) -> list[Event]:
        return [e for e in self._events if e.id > last_id]

    def clear(self) -> None:
        self._events.clear()
