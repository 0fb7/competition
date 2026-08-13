"""Runs a BattleEngine on its own background thread so the CustomTkinter
main loop is never blocked by engine ticking (or by a stuck team-code
call — sandbox.py does not enforce a timeout, so a team's decide()
looping forever will hang the thread it runs on, not the whole app).

The UI must never touch Tkinter widgets from this thread. Instead it
calls `runner.snapshot()` (cheap, lock-protected) from a Tk `after()`
callback on the main thread and updates widgets there.
"""

import threading
import time
from typing import Callable, Optional

from .battle import BattleEngine
from .config import BattleConfig
from .sandbox import SandboxError, compile_team_module


class BattleRunner:
    def __init__(self, engine: BattleEngine, tick_hz: float = 30.0):
        self.engine = engine
        self.tick_hz = tick_hz
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_event_id = 0
        self.on_error: Optional[Callable[[str], None]] = None
        self._step_ms_samples: list[float] = []

    # ---- lifecycle ----
    def start_thread(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="BattleEngineThread")
        self._thread.start()

    def stop_thread(self, timeout: float = 2.0):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _loop(self):
        period = 1.0 / self.tick_hz
        last = time.perf_counter()
        while not self._stop.is_set():
            now = time.perf_counter()
            dt = now - last
            last = now
            try:
                step_start = time.perf_counter()
                with self._lock:
                    self.engine.step(min(dt, 0.1))
                step_ms = (time.perf_counter() - step_start) * 1000.0
                self._step_ms_samples.append(step_ms)
                if len(self._step_ms_samples) > 60:
                    self._step_ms_samples = self._step_ms_samples[-60:]
            except Exception as e:  # a bug in the engine, not team code
                if self.on_error:
                    self.on_error(str(e))
            time.sleep(max(0.0, period - (time.perf_counter() - now)))

    # ---- controls (safe to call from the UI thread) ----
    def start_battle(self):
        with self._lock:
            self.engine.start()

    def pause_battle(self):
        with self._lock:
            self.engine.pause()

    def reset_battle(
        self, team_a_name: str | None = None, team_b_name: str | None = None,
        config: BattleConfig | None = None,
    ):
        with self._lock:
            self.engine.reset(team_a_name, team_b_name, config)
            self._last_event_id = 0

    def set_team_code(self, side: str, code: str) -> None:
        """Validates and hot-swaps one team's strategy. Raises SandboxError
        (caught by the caller/UI) instead of touching the running battle
        if the code doesn't compile — a bad submission must not crash the
        competition."""
        decide_fn = compile_team_module(code)  # validate outside the lock
        with self._lock:
            if side == "alpha":
                self.engine.decide_a = decide_fn
                self.engine._team_a_code = code
            elif side == "beta":
                self.engine.decide_b = decide_fn
                self.engine._team_b_code = code
            else:
                raise ValueError(f"unknown side: {side}")

    def set_difficulty(self, level: int) -> None:
        with self._lock:
            self.engine.difficulty = level

    # ---- read-only state for the UI ----
    def snapshot(self) -> dict:
        with self._lock:
            e = self.engine
            new_events = e.events.since(self._last_event_id)
            if new_events:
                self._last_event_id = new_events[-1].id
            avg_step_ms = (
                sum(self._step_ms_samples) / len(self._step_ms_samples)
                if self._step_ms_samples else 0.0
            )
            time_remaining = (
                max(0.0, e.config.battle_duration - e.elapsed)
                if e.config.battle_duration else None
            )
            return {
                "running": e.running,
                "winner": e.winner,
                "ended": e.ended,
                "outcome": e.outcome,
                "tick_count": e.tick_count,
                "elapsed": e.elapsed,
                "difficulty": e.difficulty,
                "ship_a": e.ship_a.snapshot(),
                "ship_b": e.ship_b.snapshot(),
                "ship_a_heading": e.ship_a.heading,
                "ship_b_heading": e.ship_b.heading,
                "log_tail": list(e.log[-40:]),
                "new_events": new_events,
                "engine_alive": bool(self._thread and self._thread.is_alive()),
                "engine_tick_ms": round(avg_step_ms, 2),
                "attack_range": e.config.attack_range,
                "battle_duration": e.config.battle_duration,
                "time_remaining": time_remaining,
            }
