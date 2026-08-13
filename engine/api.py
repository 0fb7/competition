"""The action surface handed to team code as `api`.

Every function here only *requests* an action; the engine (battle.py)
still enforces range, cooldown and energy rules when the request is
resolved, so team code cannot cheat by calling move_toward/attack directly
against engine internals.
"""

import math

from .config import BattleConfig


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
        return {name: fn for name, fn in full_api.items() if name in config.allowed_api}
    return full_api
