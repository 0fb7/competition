"""Central battle configuration.

Before Phase 2 these values were hardcoded module constants in
engine/ship.py (MAX_HP, ATTACK_RANGE, ATTACK_DAMAGE, ...). They're
collected here into one dataclass so a Challenge (challenges/) can
describe a different battle without editing engine code, per one
BattleConfig per battle rather than global constants.

`BattleConfig()` with no arguments reproduces the exact numeric values
Code Battleship shipped with before Phase 2 — this is what makes the
default Challenge backward-compatible: nothing about existing behavior
changes unless a Challenge explicitly configures different values.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Arena size is not a per-Challenge "rule" (movement/attack/range/damage/
# cooldown/energy/sensor_range/battle_duration are) — it stays a fixed
# constant, unconfigured, exactly as before.
ARENA_WIDTH = 40.0
ARENA_HEIGHT = 22.5

ALL_API_FUNCTIONS = ("move_toward", "hold_position", "attack", "find_nearest", "distance_to", "log")

WIN_DESTROY_ENEMY = "DESTROY_ENEMY"
WIN_TIME_LIMIT_DRAW = "TIME_LIMIT_DRAW"
WIN_CONDITIONS = (WIN_DESTROY_ENEMY, WIN_TIME_LIMIT_DRAW)


@dataclass
class BattleConfig:
    max_hp: float = 100.0
    max_energy: float = 100.0
    movement_speed: float = 6.0
    attack_enabled: bool = True
    attack_range: float = 10.0
    attack_damage: float = 12.0
    attack_cooldown: float = 1.2
    attack_energy_cost: float = 18.0
    energy_regen_rate: float = 8.0
    # Effectively unlimited by default (arena diagonal is ~45.9) so a
    # Challenge that doesn't set this gets today's unlimited-detection
    # find_nearest() behavior, unchanged.
    sensor_range: float = 100.0
    # None/0 = no time limit (today's behavior: fight until one ship dies).
    battle_duration: float | None = None
    win_condition: str = WIN_DESTROY_ENEMY
    # None = every engine API function is available, same as before
    # Phase 2 (no filtering happened at all).
    allowed_api: list[str] | None = None
    # Phase 7: the single source of truth for how long a participant's
    # decide() is allowed to run before its isolated worker process is
    # forcibly terminated (engine/worker.py). Only enforced when a
    # BattleEngine is constructed with isolate_execution=True (live
    # BattleRunner battles) — see engine/battle.py's docstring for why
    # this is opt-in rather than a global default.
    code_execution_timeout: float = 2.0

    def validate(self) -> None:
        if self.max_hp <= 0:
            raise ValueError("max_hp must be > 0")
        if self.max_energy <= 0:
            raise ValueError("energy_pool must be > 0")
        if self.movement_speed <= 0:
            raise ValueError("movement_speed must be > 0")
        if self.attack_range <= 0:
            raise ValueError("attack_range must be > 0")
        if self.attack_damage <= 0:
            raise ValueError("attack_damage must be > 0")
        if self.attack_cooldown < 0:
            raise ValueError("attack_cooldown must be >= 0")
        if self.attack_energy_cost < 0:
            raise ValueError("attack_energy_cost must be >= 0")
        if self.energy_regen_rate < 0:
            raise ValueError("energy_regen_rate must be >= 0")
        if self.sensor_range <= 0:
            raise ValueError("sensor_range must be > 0")
        if self.battle_duration is not None and self.battle_duration <= 0:
            raise ValueError("battle_duration must be > 0 or None")
        if self.code_execution_timeout <= 0:
            raise ValueError("code_execution_timeout must be > 0")
        if self.win_condition not in WIN_CONDITIONS:
            raise ValueError(f"invalid win_condition: {self.win_condition}")
        if self.allowed_api is not None:
            if not self.allowed_api:
                raise ValueError("allowed_api must not be empty")
            unknown = set(self.allowed_api) - set(ALL_API_FUNCTIONS)
            if unknown:
                raise ValueError(f"unknown API function(s): {sorted(unknown)}")
