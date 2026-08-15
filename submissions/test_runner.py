"""Isolated test execution for a draft submission.

Reuses the existing BattleEngine directly — no second battle engine, no
new simulation logic — but on a throwaway instance that is never handed
to BattleRunner, never touches the live engine, competition stats, or
the leaderboard (spec section 12). The candidate's code fights a fixed,
deterministic built-in opponent under the Challenge's own BattleConfig,
so "Test" tells you how the code behaves under the actual rules it would
compete under.

Phase 8: this throwaway engine now also runs with `isolate_execution=True`
— the exact same DecideWorker/process-isolation mechanism Phase 7 built
for the live engine (engine/worker.py), reused rather than duplicated, and
governed by the same single `config.code_execution_timeout` source of
truth (BACKLOG #16). An infinite-looping candidate now times out and is
force-terminated instead of hanging the background test thread forever.

Call run_test() from a background thread, not the UI thread — even with
isolation, `engine.step()` can still block for up to
config.code_execution_timeout while a worker is detected as hung, so
running it inline would freeze the whole dashboard on a bad submission.
"""

from __future__ import annotations

import time as _time

from engine import events as ev
from engine.battle import BattleEngine
from engine.config import BattleConfig
from engine.sandbox import SandboxError
from .submission import TestResult, TEST_ERROR, TEST_FAILED, TEST_PASSED, TEST_TIMEOUT

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
            isolate_execution=True,
        )
    except SandboxError as e:
        return TestResult(passed=False, status=TEST_ERROR, errors=[str(e)], duration=0.0)

    try:
        engine.start()
        dt = 1 / 30
        max_ticks = int(DEFAULT_MAX_DURATION_S / dt)
        for _ in range(max_ticks):
            engine.step(dt)
            if engine.ended:
                break

        events = engine.events.all()
        candidate_timed_out = any(
            e.kind == ev.CODE_TIMEOUT and e.team == CANDIDATE_TEAM_NAME for e in events
        )
        candidate_errors = [e.message for e in events if e.kind == ev.CODE_ERROR and e.team == CANDIDATE_TEAM_NAME]
        damage_dealt = sum(
            e.data.get("amount", 0.0) for e in events if e.kind == ev.DAMAGE and e.team == CANDIDATE_TEAM_NAME
        )

        # A timeout never counts as a valid submission verdict — it is
        # neither PASSED nor a genuine battle FAILED, and must never be
        # confused with a raised-exception ERROR (spec: TIMEOUT != ERROR,
        # same distinction Phase 7 established for the live engine).
        result_errors = candidate_errors[:5]
        if candidate_timed_out:
            status = TEST_TIMEOUT
            result_errors = [f"decide() exceeded {config.code_execution_timeout:.1f}s and was terminated"]
        elif candidate_errors:
            status = TEST_ERROR
        elif engine.ship_a.alive:
            status = TEST_PASSED
            result_errors = []
        else:
            status = TEST_FAILED
            result_errors = []

        return TestResult(
            passed=(status == TEST_PASSED),
            status=status,
            winner=engine.winner,
            duration=_time.perf_counter() - start,
            errors=result_errors,
            final_hp=engine.ship_a.hp,
            damage_dealt=damage_dealt,
            events_count=len(events),
        )
    finally:
        # No worker may outlive a single Test run — this throwaway engine
        # is never shared, never reset, and never referenced again after
        # this function returns, so its workers must be torn down here
        # and not left for garbage collection to (never) do.
        engine.shutdown_workers()
