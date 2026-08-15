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
        # Phase 7: no isolated worker process may outlive the runner —
        # covers both a clean app shutdown and simply stopping/replacing
        # this runner. Safe/no-op when isolate_execution is False.
        self.engine.shutdown_workers()

    def _loop(self):
        period = 1.0 / self.tick_hz
        last = time.perf_counter()
        while not self._stop.is_set():
            now = time.perf_counter()
            dt = now - last
            last = now
            try:
                step_start = time.perf_counter()
                if self.engine.isolate_execution and self.engine.running and not self.engine.ended:
                    # Phase 7: the potentially-slow part (waiting on an
                    # isolated worker, up to config.code_execution_timeout)
                    # happens WITHOUT holding self._lock, so a hung
                    # participant can never block snapshot() — and
                    # therefore the Tk UI thread — for that duration
                    # (spec sections 6/22). See BattleEngine.gather_
                    # decisions()'s docstring for why this is safe.
                    gen, decision_a, decision_b = self.engine.gather_decisions(min(dt, 0.1))
                    with self._lock:
                        self.engine.apply_decisions(min(dt, 0.1), gen, decision_a, decision_b)
                else:
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
            # Phase 7: keep the isolated worker (if any) in sync with the
            # code it actually needs to run — code was already validated
            # synchronously above, so this only ever restarts a worker
            # with known-good code. No-op when isolate_execution is False.
            self.engine.set_worker_code(side, code)

    def set_difficulty(self, level: int) -> None:
        with self._lock:
            self.engine.difficulty = level

    # ---- read-only state for the UI ----
    def _build_snapshot(self, events: list) -> dict:
        e = self.engine
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
            "new_events": events,
            "engine_alive": bool(self._thread and self._thread.is_alive()),
            "engine_tick_ms": round(avg_step_ms, 2),
            "attack_range": e.config.attack_range,
            "battle_duration": e.config.battle_duration,
            "time_remaining": time_remaining,
        }

    def snapshot(self) -> dict:
        """THE single authoritative event-drain call (spec Phase 4/6/7:
        "only ONE application-level consumer should drain new_events").
        Exactly one caller in the whole codebase may call this:
        ui/app.py's _tick(). Every other component that needs live state
        must be fed from what _tick() already computed (see
        ui/app.py's docstrings) or, if it independently needs to see
        recent battle events for its own purposes (sim/renderer.py's
        projectile/explosion animation timing), must call
        snapshot_for_render() instead — never this method."""
        with self._lock:
            new_events = self.engine.events.since(self._last_event_id)
            if new_events:
                self._last_event_id = new_events[-1].id
            return self._build_snapshot(new_events)

    def snapshot_for_render(self) -> dict:
        """Phase 7 fix: a second, NON-DRAINING read-only view for
        BattlePanel's own ~60fps pygame render loop (ui/battle_panel.py),
        which used to call snapshot() directly — a genuine, pre-existing
        instance of exactly the race this project's docstrings have
        warned against since Phase 4: two independent callers sharing
        one `_last_event_id` pointer meant whichever of _tick() (~15Hz)
        or the render loop (~60Hz) happened to call snapshot() first
        would silently steal events from the other. Discovered while
        verifying Phase 7's CODE_TIMEOUT event reliably reaches
        ui/app.py's team-code-status tracking — a rare, one-shot event
        made the pre-existing race actually visible instead of being
        masked by high-frequency events like DAMAGE.

        Returns the same shape as snapshot(), but `new_events` is a
        bounded recent window (not "new since last call") and
        `_last_event_id` is never touched. sim/renderer.py's
        ArenaRenderer already deduplicates by event id
        (`_seen_event_ids`), so seeing the same event across multiple
        render frames is safe and expected — this was true even before
        this fix, it just wasn't being relied on correctly."""
        with self._lock:
            recent = self.engine.events.all()[-50:]
            return self._build_snapshot(recent)
