"""Isolated test execution for a draft submission.

Reuses the existing BattleEngine directly — no second battle engine, no
new simulation logic — but on a throwaway instance that is never handed
to BattleRunner, never touches the live engine, competition stats, or
the leaderboard (spec section 12). The candidate's code fights a fixed,
deterministic built-in opponent under the Challenge's own BattleConfig,
so "Test" tells you how the code behaves under the actual rules it would
compete under.

Call run_test() from a background thread, not the UI thread — like
BattleRunner, this has no way to force-stop a candidate's decide() if it
hangs (engine/sandbox.py has no CPU/timeout enforcement; documented
limitation, unchanged by Phase 3), so running it inline would freeze the
whole dashboard on a bad submission.
"""

from __future__ import annotations

import time as _time

from engine import events as ev
from engine.battle import BattleEngine
from engine.config import BattleConfig
from engine.sandbox import SandboxError
from .submission import TestResult

TEST_OPPONENT_CODE = '''# Built-in deterministic test opponent used only by the isolated test
# runner. Never part of a real competition, never persisted as a team's
# submission.
def decide(friendly, enemies, api):
    target = api["find_nearest"](enemies)
    if target is None:
        api["hold_position"]()
        return
    if friendly["attack_ready"] and api["distance_to"](target) <= 10.0:
        api["attack"](target)
    else:
        api["move_toward"](target["x"], target["y"])
'''

CANDIDATE_TEAM_NAME = "Candidate"
OPPONENT_TEAM_NAME = "Test Opponent"

DEFAULT_MAX_DURATION_S = 30.0  # sim-time cap, not wall-clock


def run_test(candidate_code: str, config: BattleConfig | None = None) -> TestResult:
    start = _time.perf_counter()
    config = config or BattleConfig()

    try:
        engine = BattleEngine(
            candidate_code, TEST_OPPONENT_CODE, config=config,
            team_a_name=CANDIDATE_TEAM_NAME, team_b_name=OPPONENT_TEAM_NAME,
        )
    except SandboxError as e:
        return TestResult(passed=False, errors=[str(e)], duration=0.0)

    engine.start()
    dt = 1 / 30
    max_ticks = int(DEFAULT_MAX_DURATION_S / dt)
    for _ in range(max_ticks):
        engine.step(dt)
        if engine.ended:
            break

    events = engine.events.all()
    candidate_errors = [e.message for e in events if e.kind == ev.CODE_ERROR and e.team == CANDIDATE_TEAM_NAME]
    damage_dealt = sum(
        e.data.get("amount", 0.0) for e in events if e.kind == ev.DAMAGE and e.team == CANDIDATE_TEAM_NAME
    )

    passed = engine.ship_a.alive and not candidate_errors

    return TestResult(
        passed=passed,
        winner=engine.winner,
        duration=_time.perf_counter() - start,
        errors=candidate_errors[:5],
        final_hp=engine.ship_a.hp,
        damage_dealt=damage_dealt,
        events_count=len(events),
    )
