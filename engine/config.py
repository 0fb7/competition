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

import math
from dataclasses import dataclass, field

# Arena size is not a per-Challenge "rule" (movement/attack/range/damage/
# cooldown/energy/sensor_range/battle_duration are) — it stays a fixed
# constant, unconfigured, exactly as before.
ARENA_WIDTH = 40.0
ARENA_HEIGHT = 22.5

# Canonical world-space ship footprint, derived from the renderer's fixed
# hull sprite (sim/ship_renderer.py: HULL_LEN=132px at scale=1.0) via a
# reference scale close to the admin Battle Arena's default panel size —
# not an arbitrary number. Used for two things that must agree with each
# other: (1) engine/ship.py's minimum-separation check, so ships can
# never visually overlap, and (2) sim/renderer.py's per-panel scale
# factor, so a ship occupies the same proportion of the arena whether
# it's drawn in the admin's Battle Arena or the Practice Console's
# smaller embed. Not part of BattleConfig — this is a fixed physical/
# visual constant, not something a Challenge's rules configure.
SHIP_LENGTH_WORLD = 6.0

# Minimum center-to-center distance the two ships are allowed to close
# to. Roughly one hull-length, which leaves a real (if small) visible
# gap between hulls rather than just touching bow-to-bow. Capped at
# runtime against a fraction of the active attack_range (see
# engine/ship.py::enforce_minimum_separation) so an unusually small
# Challenge-configured attack_range can never make this distance
# unreachable and block combat.
SHIP_MIN_SEPARATION = 6.0

# Half of the ship's world-space footprint along its longer axis (length)
# and shorter axis (width) — derived from the same hull proportions
# sim/ship_renderer.py's sprite uses (132:40 length:width) applied to
# SHIP_LENGTH_WORLD. Kept as a plain constant here rather than importing
# from sim/ship_renderer.py, so engine/ never depends on the rendering
# package — the engine must stay headless-safe (submissions/test_runner.py
# and every engine test run it with no pygame/display at all).
_HULL_LENGTH_PX = 132.0
_HULL_WIDTH_PX = 40.0
SHIP_HALF_LENGTH_WORLD = SHIP_LENGTH_WORLD / 2
SHIP_HALF_WIDTH_WORLD = SHIP_LENGTH_WORLD * (_HULL_WIDTH_PX / _HULL_LENGTH_PX) / 2

# Conservative single margin — the half-diagonal of the hull's real
# footprint — that keeps the FULL hull inside the arena bounds at any
# heading/rotation, not just when facing an axis. Used to keep a ship's
# center far enough from every edge that its entire visible body always
# stays inside the frame, never partially clipped, regardless of which
# Battle Arena panel is drawing it.
SHIP_BOUNDARY_MARGIN = math.hypot(SHIP_HALF_LENGTH_WORLD, SHIP_HALF_WIDTH_WORLD)

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
    # Energy drained per world-unit of ACTUAL movement (engine/ship.py's
    # Ship.move_toward() reuses its own already-computed `step` distance
    # — no duplicate distance math). Defaults to 0.0 so every existing
    # Challenge/test is byte-for-byte unaffected unless it explicitly
    # opts in. Movement itself is NEVER blocked by low/zero energy —
    # this only drains the pool (floored at 0), it never gates whether
    # move_toward() can run, unlike attack_energy_cost which does gate
    # can_attack().
    movement_energy_cost: float = 0.0
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
        if self.movement_energy_cost < 0:
            raise ValueError("movement_energy_cost must be >= 0")
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
