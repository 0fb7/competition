"""Headless smoke tests for the battle engine, event bus, background
runner, sandbox restrictions, and competition tracker — none of these
need pygame or a display. Run with:

    python tests/test_engine.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.battle import BattleEngine
from engine.competition import CompetitionTracker
from engine.runner import BattleRunner
from engine.sandbox import SandboxError, validate_source

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, "teams", name), encoding="utf-8") as f:
        return f.read()


TEAM_A_CODE = _read("team_alpha.py")
TEAM_B_CODE = _read("team_beta.py")


def test_battle_resolves():
    engine = BattleEngine(TEAM_A_CODE, TEAM_B_CODE)
    engine.start()
    dt = 1 / 30
    for _ in range(30 * 60):
        engine.step(dt)
        if engine.winner:
            break
    assert engine.winner is not None, "battle did not resolve within the time cap"
    assert engine.tick_count > 0
    print(f"  battle resolved: winner={engine.winner} ticks={engine.tick_count} elapsed={engine.elapsed:.1f}s")


def test_events_emitted():
    engine = BattleEngine(TEAM_A_CODE, TEAM_B_CODE)
    engine.start()
    dt = 1 / 30
    for _ in range(30 * 60):
        engine.step(dt)
        if engine.winner:
            break
    kinds = {e.kind for e in engine.events.all()}
    for required in ("attack", "damage", "destroyed", "battle_won"):
        assert required in kinds, f"missing event kind: {required}"
    print(f"  event kinds observed: {sorted(kinds)}")


def test_sandbox_rejects_dangerous_code():
    for bad_code in (
        "import os\ndef decide(friendly, enemies, api):\n    pass\n",
        "def decide(friendly, enemies, api):\n    eval('1')\n",
        "def decide(friendly, enemies, api):\n    open('x')\n",
    ):
        try:
            validate_source(bad_code)
            raise AssertionError(f"sandbox accepted dangerous code:\n{bad_code}")
        except SandboxError:
            pass
    print("  sandbox correctly rejects import/eval/open")


def test_runner_thread_ticks_and_stops_cleanly():
    engine = BattleEngine(TEAM_A_CODE, TEAM_B_CODE)
    runner = BattleRunner(engine, tick_hz=30)
    runner.start_thread()
    runner.start_battle()
    time.sleep(0.5)
    snap = runner.snapshot()
    assert snap["tick_count"] > 0, "runner did not tick"
    runner.stop_thread(timeout=2.0)
    assert not runner._thread.is_alive(), "engine thread did not stop"
    print(f"  runner ticked {snap['tick_count']} times in 0.5s and stopped cleanly")


def test_competition_tracker_accumulates_from_real_events():
    engine = BattleEngine(TEAM_A_CODE, TEAM_B_CODE)
    engine.start()
    dt = 1 / 30
    for _ in range(30 * 60):
        engine.step(dt)
        if engine.winner:
            break
    tracker = CompetitionTracker(["Team Alpha", "Team Beta"])
    tracker.ingest(engine.events.all())
    ranked = tracker.ranked()
    assert ranked[0].team == engine.winner
    assert ranked[0].wins == 1
    assert any(r.damage_dealt > 0 for r in ranked)
    print(f"  competition tracker: {[(r.team, r.score, r.wins, r.losses) for r in ranked]}")


def test_default_challenge_config_preserves_legacy_behavior():
    """Phase 2 regression test (spec section 20): engine/config.py's
    BattleConfig() defaults must reproduce the exact pre-Phase-2 hardcoded
    ship.py constants, and challenges/challenge.py's Rules() (what the
    default "Tactical Battleship" Challenge uses) must produce a battle
    that behaves identically to no config being passed at all."""
    from engine.config import BattleConfig
    from challenges.challenge import Rules
    from engine.config import WIN_DESTROY_ENEMY, ALL_API_FUNCTIONS

    legacy = BattleConfig()
    assert legacy.max_hp == 100.0
    assert legacy.max_energy == 100.0
    assert legacy.movement_speed == 6.0
    assert legacy.attack_range == 10.0
    assert legacy.attack_damage == 12.0
    assert legacy.attack_cooldown == 1.2
    assert legacy.attack_energy_cost == 18.0
    assert legacy.energy_regen_rate == 8.0
    assert legacy.battle_duration is None
    assert legacy.win_condition == WIN_DESTROY_ENEMY
    assert legacy.allowed_api is None

    default_rules_config = Rules().to_battle_config(WIN_DESTROY_ENEMY, list(ALL_API_FUNCTIONS))

    baseline = BattleEngine(TEAM_A_CODE, TEAM_B_CODE)  # no config = legacy BattleConfig()
    configured = BattleEngine(TEAM_A_CODE, TEAM_B_CODE, config=default_rules_config)
    baseline.start()
    configured.start()
    dt = 1 / 30
    for _ in range(30 * 60):
        if not baseline.winner:
            baseline.step(dt)
        if not configured.winner:
            configured.step(dt)
        if baseline.winner and configured.winner:
            break

    assert baseline.winner == configured.winner
    assert baseline.tick_count == configured.tick_count
    assert abs(baseline.elapsed - configured.elapsed) < 1e-9
    assert baseline.ship_a.hp == configured.ship_a.hp
    assert baseline.ship_b.hp == configured.ship_b.hp
    print(
        f"  legacy vs default-Challenge battle identical: "
        f"winner={baseline.winner} ticks={baseline.tick_count}"
    )


def test_enforce_minimum_separation_pushes_ships_apart_symmetrically():
    """Direct unit test of the new overlap-prevention constraint (added
    per the Battle Arena visualization request): two ships placed at the
    exact same point must end up pushed apart, symmetrically, to exactly
    the configured minimum separation — not teleported to an arbitrary
    spot, not left overlapping."""
    import math
    from engine.config import BattleConfig, SHIP_MIN_SEPARATION
    from engine.ship import Ship, enforce_minimum_separation

    config = BattleConfig()
    a = Ship(id="a", team="A", name="A", x=20.0, y=10.0, config=config)
    b = Ship(id="b", team="B", name="B", x=20.0, y=10.0, config=config)  # exact same point

    enforce_minimum_separation(a, b, config)

    dist = math.hypot(a.x - b.x, a.y - b.y)
    assert abs(dist - SHIP_MIN_SEPARATION) < 1e-6, f"expected exactly {SHIP_MIN_SEPARATION}, got {dist}"
    # symmetric: both ships moved the same distance from the original point
    da = math.hypot(a.x - 20.0, a.y - 10.0)
    db = math.hypot(b.x - 20.0, b.y - 10.0)
    assert abs(da - db) < 1e-9

    # already far enough apart -> no-op (nothing pushed)
    a2 = Ship(id="a", team="A", name="A", x=0.0, y=0.0, config=config)
    b2 = Ship(id="b", team="B", name="B", x=30.0, y=20.0, config=config)
    enforce_minimum_separation(a2, b2, config)
    assert (a2.x, a2.y) == (0.0, 0.0)
    assert (b2.x, b2.y) == (30.0, 20.0)

    # a destroyed ship's wreck position must never be pushed
    a3 = Ship(id="a", team="A", name="A", x=5.0, y=5.0, config=config)
    b3 = Ship(id="b", team="B", name="B", x=5.0, y=5.0, config=config)
    a3.alive = False
    enforce_minimum_separation(a3, b3, config)
    assert (a3.x, a3.y) == (5.0, 5.0)
    assert (b3.x, b3.y) == (5.0, 5.0)


def test_enforce_minimum_separation_never_blocks_attack_range():
    """The minimum separation must never exceed a fraction of the
    configured attack_range — otherwise two ships could never close to
    within range of each other and combat would be permanently blocked.
    Exercises a Challenge configured with an unusually small attack_range."""
    from engine.config import BattleConfig
    from engine.ship import Ship, enforce_minimum_separation

    small_range_config = BattleConfig(attack_range=2.0)  # much smaller than SHIP_MIN_SEPARATION
    a = Ship(id="a", team="A", name="A", x=10.0, y=10.0, config=small_range_config)
    b = Ship(id="b", team="B", name="B", x=10.0, y=10.0, config=small_range_config)
    enforce_minimum_separation(a, b, small_range_config)

    import math
    dist = math.hypot(a.x - b.x, a.y - b.y)
    assert dist < small_range_config.attack_range, (
        f"minimum separation ({dist}) must stay reachable within attack_range "
        f"({small_range_config.attack_range}), or combat could never start"
    )


def test_ships_never_overlap_during_a_real_battle():
    """Real end-to-end regression: run an actual battle (aggressive
    pursuit code on both sides, so the ships genuinely try to close
    distance and would previously have been able to fully overlap) and
    assert the two ships are never closer than SHIP_MIN_SEPARATION on any
    tick, from start to conclusion."""
    import math
    from engine.config import SHIP_MIN_SEPARATION

    engine = BattleEngine(TEAM_A_CODE, TEAM_B_CODE)
    engine.start()
    dt = 1 / 30
    min_seen = float("inf")
    for _ in range(30 * 60):
        engine.step(dt)
        if engine.ship_a.alive and engine.ship_b.alive:
            dist = math.hypot(engine.ship_a.x - engine.ship_b.x, engine.ship_a.y - engine.ship_b.y)
            min_seen = min(min_seen, dist)
        if engine.winner:
            break
    assert engine.winner is not None, "battle did not resolve within the time cap"
    assert min_seen >= SHIP_MIN_SEPARATION - 1e-6, f"ships got closer than the minimum separation: {min_seen}"
    print(f"  closest approach across the whole battle: {min_seen:.2f} world units (min allowed: {SHIP_MIN_SEPARATION})")


def test_move_toward_keeps_full_hull_inside_the_frame():
    """New requirement: a ship's CENTER must never come closer to any
    edge than SHIP_BOUNDARY_MARGIN — not 0 — so its real visual hull
    (drawn centered on that point with a nonzero footprint) never pokes
    outside the Battle Arena frame, in either interface."""
    from engine.config import BattleConfig, ARENA_WIDTH, ARENA_HEIGHT, SHIP_BOUNDARY_MARGIN
    from engine.ship import Ship

    config = BattleConfig()

    # drive the ship hard toward each corner in turn and confirm it stops
    # at the margin, never at the raw 0/ARENA_WIDTH/ARENA_HEIGHT edge
    for target in ((-100.0, -100.0), (1000.0, -100.0), (-100.0, 1000.0), (1000.0, 1000.0)):
        ship = Ship(id="a", team="A", name="A", x=20.0, y=11.0, config=config)
        for _ in range(2000):  # far more ticks than needed to reach the wall
            ship.move_toward(target[0], target[1], 1 / 30)
        assert SHIP_BOUNDARY_MARGIN - 1e-6 <= ship.x <= ARENA_WIDTH - SHIP_BOUNDARY_MARGIN + 1e-6, ship.x
        assert SHIP_BOUNDARY_MARGIN - 1e-6 <= ship.y <= ARENA_HEIGHT - SHIP_BOUNDARY_MARGIN + 1e-6, ship.y


def test_ship_never_leaves_the_frame_during_a_real_battle():
    """Real end-to-end regression, same spirit as the min-separation
    battle test: run an actual battle with real (aggressive, edge-
    seeking) team code and assert both ships' positions stay within the
    margin-aware bounds on every single tick, not just at the end."""
    from engine.config import ARENA_WIDTH, ARENA_HEIGHT, SHIP_BOUNDARY_MARGIN

    engine = BattleEngine(TEAM_A_CODE, TEAM_B_CODE)
    engine.start()
    dt = 1 / 30
    for _ in range(30 * 60):
        engine.step(dt)
        for ship in (engine.ship_a, engine.ship_b):
            assert SHIP_BOUNDARY_MARGIN - 1e-6 <= ship.x <= ARENA_WIDTH - SHIP_BOUNDARY_MARGIN + 1e-6, (
                f"{ship.team} left the frame horizontally: x={ship.x}"
            )
            assert SHIP_BOUNDARY_MARGIN - 1e-6 <= ship.y <= ARENA_HEIGHT - SHIP_BOUNDARY_MARGIN + 1e-6, (
                f"{ship.team} left the frame vertically: y={ship.y}"
            )
        if engine.winner:
            break
    assert engine.winner is not None, "battle did not resolve within the time cap"


def test_movement_energy_cost_zero_preserves_existing_behavior():
    """Default (movement_energy_cost=0.0, e.g. every existing Challenge
    that doesn't opt in) must leave energy completely unaffected by
    movement — byte-identical to the pre-this-change formula, which only
    ever changed energy via tick_cooldowns()'s regen."""
    from engine.config import BattleConfig
    from engine.ship import Ship

    config = BattleConfig()  # movement_energy_cost defaults to 0.0
    assert config.movement_energy_cost == 0.0
    ship = Ship(id="a", team="A", name="A", x=10.0, y=10.0, config=config)
    energy_before = ship.energy
    for _ in range(60):
        ship.move_toward(35.0, 10.0, 1 / 30)
    assert ship.energy == energy_before, "movement must not touch energy when movement_energy_cost is 0"


def test_movement_energy_cost_drains_proportional_to_actual_distance_moved():
    """movement_energy_cost > 0 must drain energy by exactly
    (actual distance moved) * movement_energy_cost — using move_toward()'s
    own already-computed step, not a separately-derived distance."""
    from engine.config import BattleConfig
    from engine.ship import Ship

    config = BattleConfig(movement_energy_cost=0.5, movement_speed=6.0)
    ship = Ship(id="a", team="A", name="A", x=10.0, y=10.0, config=config)
    dt = 1 / 30
    expected_step = config.movement_speed * dt  # well short of the target, so step == full speed*dt

    ship.move_toward(35.0, 10.0, dt)  # far target: one tick moves exactly movement_speed*dt
    expected_energy = config.max_energy - expected_step * config.movement_energy_cost
    assert abs(ship.energy - expected_energy) < 1e-9

    # a second tick drains proportionally again
    ship.move_toward(35.0, 10.0, dt)
    expected_energy -= expected_step * config.movement_energy_cost
    assert abs(ship.energy - expected_energy) < 1e-9


def test_movement_energy_cost_never_goes_below_zero_and_never_blocks_movement():
    """Even with energy fully drained, movement must continue at full
    speed — only attacking is ever gated by energy, never movement."""
    from engine.config import BattleConfig
    from engine.ship import Ship

    config = BattleConfig(movement_energy_cost=1000.0)  # deliberately huge, drains to 0 in one tick
    ship = Ship(id="a", team="A", name="A", x=10.0, y=10.0, config=config)
    dt = 1 / 30

    ship.move_toward(35.0, 10.0, dt)
    assert ship.energy == 0.0, "energy must be clamped at exactly 0, never negative"
    x_after_first_move = ship.x
    assert x_after_first_move > 10.0, "ship must have actually moved on the tick that drained it to 0"

    # keep moving at 0 energy — must keep moving at full normal speed, not get stuck
    ship.move_toward(35.0, 10.0, dt)
    assert ship.x > x_after_first_move, "movement must continue normally even at 0 energy"
    assert ship.energy == 0.0


def test_movement_energy_cost_does_not_interfere_with_regeneration_or_attack_cost():
    """Regeneration (tick_cooldowns) must keep working exactly as before,
    and attacking must still cost exactly the configured
    attack_energy_cost (18.0 by default) — movement cost is a separate,
    additive drain, not a replacement for either mechanism."""
    from engine.config import BattleConfig
    from engine.ship import Ship

    config = BattleConfig(movement_energy_cost=0.5)
    assert config.attack_energy_cost == 18.0  # unchanged from the existing default
    ship = Ship(id="a", team="A", name="A", x=10.0, y=10.0, config=config)
    ship.energy = 50.0

    # regen still works normally (movement_energy_cost doesn't touch tick_cooldowns)
    ship.tick_cooldowns(1.0)
    assert abs(ship.energy - min(config.max_energy, 50.0 + config.energy_regen_rate * 1.0)) < 1e-9

    # attacking still costs exactly attack_energy_cost, unaffected by movement_energy_cost
    energy_before_attack = ship.energy
    target = Ship(id="b", team="B", name="B", x=15.0, y=10.0, config=config)
    dmg = ship.fire_at(target)
    assert dmg == config.attack_damage
    assert abs(ship.energy - (energy_before_attack - config.attack_energy_cost)) < 1e-9


def test_movement_energy_cost_applied_to_tactical_battleship_challenge():
    """The specific requirement: the seeded "Tactical Battleship"
    challenge carries movement_energy_cost=0.5, while a fresh Rules()
    (and therefore every other/new Challenge) still defaults to 0.0."""
    from challenges.challenge import Rules
    from challenges.challenge_repository import ChallengeRepository
    from challenges.challenge_service import ChallengeService, DEFAULT_CHALLENGE_ID
    import tempfile

    assert Rules().movement_energy_cost == 0.0

    tmp = tempfile.mkdtemp(prefix="battleship_energy_test_")
    svc = ChallengeService(ChallengeRepository(os.path.join(tmp, "challenges.json")))
    svc.ensure_default_challenge()
    config = svc.get_challenge(DEFAULT_CHALLENGE_ID).to_battle_config()
    assert config.movement_energy_cost == 0.5
    import shutil
    shutil.rmtree(tmp)


if __name__ == "__main__":
    tests = [
        test_battle_resolves,
        test_events_emitted,
        test_sandbox_rejects_dangerous_code,
        test_runner_thread_ticks_and_stops_cleanly,
        test_competition_tracker_accumulates_from_real_events,
        test_default_challenge_config_preserves_legacy_behavior,
        test_enforce_minimum_separation_pushes_ships_apart_symmetrically,
        test_enforce_minimum_separation_never_blocks_attack_range,
        test_ships_never_overlap_during_a_real_battle,
        test_move_toward_keeps_full_hull_inside_the_frame,
        test_ship_never_leaves_the_frame_during_a_real_battle,
        test_movement_energy_cost_zero_preserves_existing_behavior,
        test_movement_energy_cost_drains_proportional_to_actual_distance_moved,
        test_movement_energy_cost_never_goes_below_zero_and_never_blocks_movement,
        test_movement_energy_cost_does_not_interfere_with_regeneration_or_attack_cost,
        test_movement_energy_cost_applied_to_tactical_battleship_challenge,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print("\nALL TESTS PASSED")
