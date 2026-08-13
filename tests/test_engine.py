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


if __name__ == "__main__":
    tests = [
        test_battle_resolves,
        test_events_emitted,
        test_sandbox_rejects_dangerous_code,
        test_runner_thread_ticks_and_stops_cleanly,
        test_competition_tracker_accumulates_from_real_events,
        test_default_challenge_config_preserves_legacy_behavior,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print("\nALL TESTS PASSED")
