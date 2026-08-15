"""Mutable battle-side ship state. Only the engine touches this directly."""

from dataclasses import dataclass, field
import math

from .config import ARENA_WIDTH, ARENA_HEIGHT, BattleConfig

# Backward-compat re-exports: these used to be the only source of truth
# (plain module constants); they're now BattleConfig's defaults, kept
# here too since sim/renderer.py and others import them from engine.ship.
MAX_HP = BattleConfig.max_hp
MAX_ENERGY = BattleConfig.max_energy
MAX_SPEED = BattleConfig.movement_speed
ATTACK_RANGE = BattleConfig.attack_range
ATTACK_DAMAGE = BattleConfig.attack_damage
ATTACK_ENERGY_COST = BattleConfig.attack_energy_cost
ATTACK_COOLDOWN = BattleConfig.attack_cooldown
ENERGY_REGEN_RATE = BattleConfig.energy_regen_rate


@dataclass
class Ship:
    id: str
    team: str
    name: str
    x: float
    y: float
    config: BattleConfig = field(default_factory=BattleConfig)
    heading: float = 0.0
    hp: float | None = None
    energy: float | None = None
    attack_cooldown: float = 0.0
    alive: bool = True
    last_action: str = "idle"

    def __post_init__(self):
        if self.hp is None:
            self.hp = self.config.max_hp
        if self.energy is None:
            self.energy = self.config.max_energy

    def distance_to(self, other: "Ship") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def tick_cooldowns(self, dt: float) -> None:
        if self.attack_cooldown > 0:
            self.attack_cooldown = max(0.0, self.attack_cooldown - dt)
        self.energy = min(self.config.max_energy, self.energy + self.config.energy_regen_rate * dt)

    def move_toward(self, tx: float, ty: float, dt: float) -> None:
        dx, dy = tx - self.x, ty - self.y
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return
        self.heading = math.atan2(dy, dx)
        step = min(self.config.movement_speed * dt, dist)
        self.x = max(0.0, min(ARENA_WIDTH, self.x + dx / dist * step))
        self.y = max(0.0, min(ARENA_HEIGHT, self.y + dy / dist * step))

    def can_attack(self, target: "Ship") -> bool:
        return (
            self.config.attack_enabled
            and self.alive
            and target.alive
            and self.attack_cooldown <= 0
            and self.energy >= self.config.attack_energy_cost
            and self.distance_to(target) <= self.config.attack_range
        )

    def fire_at(self, target: "Ship") -> float:
        """Applies cost/cooldown and returns damage dealt (caller applies it)."""
        self.attack_cooldown = self.config.attack_cooldown
        self.energy -= self.config.attack_energy_cost
        return self.config.attack_damage

    def take_damage(self, amount: float) -> None:
        self.hp = max(0.0, self.hp - amount)
        if self.hp <= 0:
            self.alive = False

    def snapshot_after_cooldown_tick(self, dt: float) -> dict:
        """Phase 7: a PURE projection of what snapshot() would return
        after tick_cooldowns(dt) — same arithmetic, but does not mutate
        this Ship. Lets BattleEngine.gather_decisions() compute exactly
        what decide() should see (same values team code always saw,
        cooldown/energy already ticked) WITHOUT touching real engine
        state outside BattleRunner's lock; the real tick_cooldowns(dt)
        call still happens later, under the lock, in apply_decisions()."""
        cooldown = max(0.0, self.attack_cooldown - dt) if self.attack_cooldown > 0 else self.attack_cooldown
        energy = min(self.config.max_energy, self.energy + self.config.energy_regen_rate * dt)
        snap = self.snapshot()
        snap["energy"] = energy
        snap["energy_pct"] = energy / self.config.max_energy
        snap["attack_cooldown"] = cooldown
        snap["attack_ready"] = cooldown <= 0 and energy >= self.config.attack_energy_cost
        return snap

    def snapshot(self) -> dict:
        """Read-only view handed to team code — no engine references leak out."""
        return {
            "id": self.id,
            "team": self.team,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "heading": self.heading,
            "hp": self.hp,
            "hp_pct": self.hp / self.config.max_hp,
            "energy": self.energy,
            "energy_pct": self.energy / self.config.max_energy,
            "alive": self.alive,
            "attack_ready": self.attack_cooldown <= 0 and self.energy >= self.config.attack_energy_cost,
            "attack_cooldown": self.attack_cooldown,
        }
