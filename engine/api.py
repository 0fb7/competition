"""The action surface handed to team code as `api`.

Every function here only *requests* an action; the engine (battle.py)
still enforces range, cooldown and energy rules when the request is
resolved, so team code cannot cheat by calling move_toward/attack directly
against engine internals.
"""

import math

from .config import BattleConfig, ALL_API_FUNCTIONS


class ForbiddenAPIError(Exception):
    """Phase 7: raised (with a clear, structured message) when team code
    CALLS a disallowed api[...] function. Distinct from a raw KeyError:
    before Phase 7, a disallowed function name was simply absent from
    the dict, so `api["attack"](...)` surfaced as a bare
    `KeyError: 'attack'` — accurate but unfriendly, and easy to mistake
    for an engine bug rather than a challenge-configuration rule. Still
    caught by the same sandbox.run_decide() try/except as any other
    team-code runtime error (spec section 8: "no engine crash"), so no
    new failure path is introduced — only the message participants see
    is improved."""


def build_api(pending: dict, config: BattleConfig | None = None) -> dict:
    """`pending` is a small mutable dict the engine reads after decide()
    returns: {"move_target": (x, y) | None, "attack_target_id": str | None}

    `config` (a challenges/-configured BattleConfig) controls two things
    here, both real engine behavior, not decoration:
      - sensor_range: find_nearest() only considers enemies within it.
        Default (BattleConfig().sensor_range = 100, larger than the arena
        diagonal) means "everyone is visible", identical to pre-Phase-2
        behavior.
      - allowed_api: only the listed function names are included in the
        returned dict at all. A call to a disallowed function is simply
        a missing dict key from team code's point of view, which the
        existing sandbox.run_decide() already catches as a normal runtime
        error — no second enforcement mechanism, no sandbox bypass.
    """

    def move_toward(x: float, y: float) -> None:
        pending["move_target"] = (float(x), float(y))

    def hold_position() -> None:
        pending["move_target"] = None

    def attack(target: dict) -> None:
        if not isinstance(target, dict) or "id" not in target:
            return
        pending["attack_target_id"] = target["id"]

    def find_nearest(enemies: list) -> dict | None:
        alive = [e for e in enemies if e.get("alive")]
        if not alive:
            return None
        friendly = pending["_self"]
        if config is not None:
            alive = [
                e for e in alive
                if math.hypot(e["x"] - friendly["x"], e["y"] - friendly["y"]) <= config.sensor_range
            ]
            if not alive:
                return None
        return min(
            alive,
            key=lambda e: math.hypot(e["x"] - friendly["x"], e["y"] - friendly["y"]),
        )

    def distance_to(target: dict) -> float:
        friendly = pending["_self"]
        return math.hypot(target["x"] - friendly["x"], target["y"] - friendly["y"])

    def log(*parts) -> None:
        pending["log"].append(" ".join(str(p) for p in parts))

    full_api = {
        "move_toward": move_toward,
        "hold_position": hold_position,
        "attack": attack,
        "find_nearest": find_nearest,
        "distance_to": distance_to,
        "log": log,
    }

    if config is not None and config.allowed_api is not None:
        # Phase 7: every function name from ALL_API_FUNCTIONS is still
        # present as a dict key — a disallowed one now maps to a stub
        # that raises ForbiddenAPIError with a clear message the MOMENT
        # it's called, instead of vanishing from the dict entirely (which
        # made `api["attack"](...)` fail as a bare KeyError at the
        # subscript, before team code even got to call anything). This
        # also means a static "is this key present" check some team
        # code might write no longer silently mis-detects availability.
        allowed = set(config.allowed_api)
        return {
            name: (full_api[name] if name in allowed else _forbidden_stub(name))
            for name in ALL_API_FUNCTIONS
        }
    return full_api


def _forbidden_stub(name: str):
    def _stub(*_args, **_kwargs):
        raise ForbiddenAPIError(f"API function '{name}' is not available in this challenge.")
    return _stub
