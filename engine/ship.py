"""Mutable battle-side ship state. Only the engine touches this directly."""

from dataclasses import dataclass, field
import math

from .config import (
    ARENA_WIDTH, ARENA_HEIGHT, SHIP_LENGTH_WORLD, SHIP_MIN_SEPARATION,
    SHIP_BOUNDARY_MARGIN, BattleConfig,
)

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
        # Clamped to SHIP_BOUNDARY_MARGIN in from each edge, not 0 — the
        # ship's CENTER reaching the raw arena edge would let its real
        # visual hull (a nonzero footprint, not a point) extend past the
        # frame and be clipped. This keeps the entire hull inside the
        # frame at any heading, in both Battle Arena panels, since both
        # read these same world coordinates.
        self.x = max(SHIP_BOUNDARY_MARGIN, min(ARENA_WIDTH - SHIP_BOUNDARY_MARGIN, self.x + dx / dist * step))
        self.y = max(SHIP_BOUNDARY_MARGIN, min(ARENA_HEIGHT - SHIP_BOUNDARY_MARGIN, self.y + dy / dist * step))

        # Reuses `step` (the actual distance just moved this tick) rather
        # than recomputing anything. Floored at 0, never blocks movement:
        # unlike attack_energy_cost (which gates whether can_attack() is
        # even True), this only drains the pool — a ship at 0 energy still
        # moves at full speed next tick, it simply can't fire until
        # tick_cooldowns()'s regen brings it back above attack_energy_cost.
        if self.config.movement_energy_cost:
            self.energy = max(0.0, self.energy - step * self.config.movement_energy_cost)

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


def enforce_minimum_separation(ship_a: "Ship", ship_b: "Ship", config: BattleConfig) -> None:
    """Prevents the two ships from visually overlapping. A real, physical
    constraint on the actual ship coordinates — not a rendering trick —
    so the same (x, y) engine/battle.py's attack-range checks use, and
    every Battle Arena panel draws, always agree with each other (the
    engine stays the single source of truth).

    Called once per tick from BattleEngine.apply_decisions(), AFTER both
    ships have moved for the tick: if they ended up closer than the
    minimum separation, both are pushed apart by a single symmetric
    correction along the real line between them, back out to exactly the
    minimum distance, then re-clamped to the arena bounds. This is not an
    iterative bounce and not a teleport to an arbitrary spot — it is a
    stable "cannot get closer than X" wall, applied the same deterministic
    way every tick, so a participant's own movement decisions (computed
    from the *previous* tick's already-corrected positions, per
    gather_decisions()'s snapshot-before-mutate ordering) never see
    sudden unexplained jumps.

    Destroyed ships are skipped — a wreck's position is frozen, not
    something that should be shoved around by a still-moving opponent.

    The minimum is capped at a fraction of the configured attack_range so
    an unusually small Challenge-configured attack_range can never make
    this distance unreachable and permanently block combat — ships must
    always be able to close to within attack range and fire."""
    if not (ship_a.alive and ship_b.alive):
        return

    min_sep = min(SHIP_MIN_SEPARATION, config.attack_range * 0.8)
    dx, dy = ship_b.x - ship_a.x, ship_b.y - ship_a.y
    dist = math.hypot(dx, dy)

    if dist >= min_sep:
        return

    if dist < 1e-6:
        # Exact same point (e.g. both spawned there) — there is no
        # defined direction to push along, so pick a fixed arbitrary
        # axis rather than dividing by zero.
        nx, ny = 1.0, 0.0
    else:
        nx, ny = dx / dist, dy / dist

    def _clamp_xy(x: float, y: float) -> tuple:
        # Same margin-aware bounds move_toward() uses — a ship pushed
        # apart near an edge must still end up with its full hull inside
        # the frame, not just its center inside the raw arena.
        return (
            max(SHIP_BOUNDARY_MARGIN, min(ARENA_WIDTH - SHIP_BOUNDARY_MARGIN, x)),
            max(SHIP_BOUNDARY_MARGIN, min(ARENA_HEIGHT - SHIP_BOUNDARY_MARGIN, y)),
        )

    push = (min_sep - dist) / 2.0
    ship_a.x, ship_a.y = _clamp_xy(ship_a.x - nx * push, ship_a.y - ny * push)
    ship_b.x, ship_b.y = _clamp_xy(ship_b.x + nx * push, ship_b.y + ny * push)

    # Near an arena edge, one side's push above can be cut short by the
    # boundary clamp, leaving the pair still short of min_sep even though
    # the arena (40 x 22.5 world units, comfortably larger than
    # SHIP_MIN_SEPARATION) has room elsewhere along this axis for the
    # OTHER ship to take up the slack. Top up whichever ship still has
    # room to move, rather than leaving the pair under-separated just
    # because the 50/50 split wasn't achievable for one of them.
    remaining = min_sep - math.hypot(ship_b.x - ship_a.x, ship_b.y - ship_a.y)
    if remaining > 1e-9:
        moved_ax, moved_ay = _clamp_xy(ship_a.x - nx * remaining, ship_a.y - ny * remaining)
        room_a = math.hypot(moved_ax - ship_a.x, moved_ay - ship_a.y)
        take_a = min(remaining, room_a)
        ship_a.x, ship_a.y = _clamp_xy(ship_a.x - nx * take_a, ship_a.y - ny * take_a)
        remaining -= take_a
        if remaining > 1e-9:
            ship_b.x, ship_b.y = _clamp_xy(ship_b.x + nx * remaining, ship_b.y + ny * remaining)
