"""Core battle loop: ticks both ships' team code, resolves movement and
attacks, and tracks the event log + win condition."""

import time

from .api import build_api
from .config import BattleConfig
from .sandbox import compile_team_module, run_decide
from .ship import Ship
from . import events as ev
from .events import EventBus
from .worker import DecideWorker, STATUS_OK, STATUS_TIMEOUT


class BattleEngine:
    def __init__(
        self, team_a_code: str, team_b_code: str, difficulty: int = 2,
        team_a_name: str | None = None, team_b_name: str | None = None,
        config: BattleConfig | None = None, isolate_execution: bool = False,
    ):
        self._team_a_code = team_a_code
        self._team_b_code = team_b_code
        self.decide_a = compile_team_module(team_a_code)
        self.decide_b = compile_team_module(team_b_code)
        # Configuration only — see difficulty.py / ui/difficulty_panel.py.
        # No engine behavior currently changes based on this value; it exists
        # so the UI has something real to persist and display rather than a
        # value that silently does nothing with no acknowledgement anywhere.
        self.difficulty = difficulty
        # The active Challenge's rules (challenges/challenge.py), converted
        # to a BattleConfig. Defaulting to BattleConfig() reproduces the
        # exact numeric values this project shipped with before Phase 2 —
        # that's what makes "no Challenge selected" behave identically to
        # the old hardcoded engine.
        self.config = config or BattleConfig()

        # Phase 7: OFF by default so every existing direct BattleEngine
        # user (all pre-Phase-7 tests, submissions/test_runner.py's
        # throwaway "Test" battles) is byte-for-byte unaffected. Only
        # ui/app.py's one live engine instance turns this on — see
        # engine/worker.py's module docstring for the full architecture
        # reasoning (persistent worker per side, real OS-enforced
        # timeout, not a per-tick process spawn).
        self.isolate_execution = isolate_execution
        self._workers: dict[str, DecideWorker | None] = {"alpha": None, "beta": None}
        self._worker_dead_reported = {"alpha": False, "beta": False}
        self._generation = 0
        if self.isolate_execution:
            self._workers["alpha"] = DecideWorker(team_a_code, self.config.code_execution_timeout)
            self._workers["beta"] = DecideWorker(team_b_code, self.config.code_execution_timeout)

        self._reset_state(team_a_name, team_b_name)

    def _reset_state(
        self, team_a_name: str | None = None, team_b_name: str | None = None,
        config: BattleConfig | None = None,
    ):
        # roster/team_service.py (Phase 1 team management) can rename a
        # team; passing the new name through here is how that rename
        # reaches the live ship without a second, UI-side battle state.
        # With no override, keep whatever name the engine already had
        # (or the original defaults, on first construction).
        prev_a = getattr(self, "ship_a", None)
        prev_b = getattr(self, "ship_b", None)
        ta = team_a_name or (prev_a.team if prev_a else "Team Alpha")
        tb = team_b_name or (prev_b.team if prev_b else "Team Beta")

        if config is not None:
            self.config = config

        # Phase 7: Reset is a real recovery path (spec section 10) — a
        # worker that died from a timeout/crash in the PREVIOUS battle
        # must not stay dead forever just because this BattleEngine
        # object (and its workers) persist across resets. Revive with
        # the same code that was already running; a genuinely broken
        # submission will simply time out/error again on its own merits,
        # never silently "fixed" by this.
        if self.isolate_execution:
            for side, code in (("alpha", self._team_a_code), ("beta", self._team_b_code)):
                worker = self._workers.get(side)
                if worker is None or worker.dead:
                    if worker is not None:
                        worker.shutdown()
                    self._workers[side] = DecideWorker(code, self.config.code_execution_timeout)
            self._worker_dead_reported = {"alpha": False, "beta": False}

        # Bumped on every reset so a decision gathered lock-free for the
        # PREVIOUS generation (spec section 6: gather_decisions() may run
        # without BattleRunner's lock held) is detected as stale and
        # discarded by apply_decisions() instead of being misapplied to
        # freshly-reset ships (see apply_decisions()'s docstring).
        self._generation += 1

        self.ship_a = Ship(id="alpha", team=ta, name="Falcon-01", x=6.0, y=16.0, config=self.config)
        self.ship_b = Ship(id="beta", team=tb, name="Titan-02", x=32.0, y=6.0, config=self.config)

        self.log: list[str] = []
        self.events = EventBus()
        self.tick_count = 0
        self.elapsed = 0.0
        self.running = False
        self.winner: str | None = None
        self.ended = False
        self.outcome: str | None = None

    @property
    def ships(self):
        return (self.ship_a, self.ship_b)

    def start(self):
        self.running = True

    def pause(self):
        self.running = False

    def reset(
        self, team_a_name: str | None = None, team_b_name: str | None = None,
        config: BattleConfig | None = None,
    ):
        self._reset_state(team_a_name, team_b_name, config)

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.append(f"{ts}  {msg}")
        if len(self.log) > 200:
            self.log = self.log[-200:]

    # ------------------------------------------------------------ decisions
    def _run_side_inprocess(self, mover_snap: dict, opponent_snap: dict, decide_fn) -> tuple[str, dict]:
        """The original, unchanged synchronous path — used whenever
        isolate_execution is False (every pre-Phase-7 caller). Operates
        on already-computed snapshot dicts (see gather_decisions()) so
        its numeric behavior is identical to before Phase 7 — it's the
        exact same read-only values team code always saw, just no longer
        computed via a fresh Ship.snapshot() call inside this function."""
        pending = {
            "move_target": None,
            "attack_target_id": None,
            "log": [],
            "_self": mover_snap,
        }
        api = build_api(pending, self.config)
        status = run_decide(decide_fn, mover_snap, [opponent_snap], api)
        return status, pending

    def _run_side_isolated(self, side: str, mover_snap: dict, opponent_snap: dict) -> tuple[str, dict]:
        """Phase 7: runs decide() in this side's persistent worker
        process instead of in-process. Returns ("timeout", {}) if the
        worker didn't answer within config.code_execution_timeout — the
        worker is already terminated by DecideWorker.request() itself by
        the time this returns, so there is never a lingering hung
        process to clean up later."""
        worker = self._workers[side]
        if worker is None or worker.dead:
            # Already known dead (a prior timeout/crash this battle) —
            # report it via events/log at most ONCE, per _worker_dead_reported,
            # never every tick (spec section 27: don't flood the event buffer).
            if not self._worker_dead_reported[side]:
                self._worker_dead_reported[side] = True
                return "unavailable", {}
            return "ok", {"move_target": None, "attack_target_id": None, "log": []}

        outcome = worker.request(mover_snap, [opponent_snap], self.config)
        if outcome.status == STATUS_TIMEOUT:
            self._worker_dead_reported[side] = True
            return "timeout", {}
        if outcome.status != STATUS_OK:
            self._worker_dead_reported[side] = True
            return "unavailable", {}
        return outcome.run_status, outcome.pending

    def _decide_side(self, side: str, mover_snap: dict, opponent_snap: dict, decide_fn) -> tuple[str, dict]:
        if self.isolate_execution:
            return self._run_side_isolated(side, mover_snap, opponent_snap)
        return self._run_side_inprocess(mover_snap, opponent_snap, decide_fn)

    def gather_decisions(self, dt: float):
        """Phase 7: computes what both sides' decide() produced this
        tick. THIS is the only part of a tick that can block for up to
        config.code_execution_timeout (when isolate_execution and a
        worker hangs) — BattleRunner calls this WITHOUT holding its
        lock, specifically so a hung participant never blocks
        runner.snapshot() (and therefore the Tk UI thread) for that
        duration (spec sections 6/22).

        No real engine state is mutated here — cooldown/energy are only
        PROJECTED (Ship.snapshot_after_cooldown_tick), never actually
        ticked, so this is safe to call without a lock even though
        another thread might concurrently call reset_battle(). The
        returned generation number lets apply_decisions() detect and
        discard a decision computed against a battle that was reset in
        the meantime, rather than misapplying it to the new ships."""
        gen = self._generation
        snap_a = self.ship_a.snapshot_after_cooldown_tick(dt)
        snap_b = self.ship_b.snapshot_after_cooldown_tick(dt)
        decision_a = self._decide_side("alpha", snap_a, snap_b, self.decide_a)
        decision_b = self._decide_side("beta", snap_b, snap_a, self.decide_b)
        return gen, decision_a, decision_b

    def _finalize_side_events(self, mover_team: str, opponent_id: str, opponent_name: str, status: str, pending: dict):
        pending.setdefault("move_target", None)
        pending.setdefault("attack_target_id", None)
        pending.setdefault("log", [])

        if status == "timeout":
            self._log(f"{mover_team} code timeout - exceeded {self.config.code_execution_timeout:.1f}s")
            self.events.emit(
                ev.CODE_TIMEOUT, mover_team,
                f"decide() exceeded {self.config.code_execution_timeout:.1f}s and was terminated",
            )
        elif status == "unavailable":
            self._log(f"{mover_team} worker unavailable - no further actions this battle")
            self.events.emit(ev.CODE_ERROR, mover_team, "worker unavailable (previously timed out or crashed)")
        elif status != "ok":
            self._log(f"{mover_team} code error - {status}")
            self.events.emit(ev.CODE_ERROR, mover_team, status)
        for line in pending["log"]:
            self._log(f"{mover_team}: {line}")
            self.events.emit(ev.CODE_EXECUTED, mover_team, line)
        if pending["attack_target_id"] == opponent_id:
            self.events.emit(
                ev.TARGET_ACQUIRED, mover_team, f"Target acquired: {opponent_name}",
                target_id=opponent_id,
            )

    def apply_decisions(self, dt: float, gen: int, decision_a: tuple, decision_b: tuple) -> None:
        """The fast, state-mutating half of a tick — always safe (and
        expected) to call under BattleRunner's lock. Discards `decision_a`
        /`decision_b` if `gen` no longer matches the current generation
        (a reset happened while gather_decisions() was in flight — see
        its docstring) instead of applying stale movement/attack
        decisions to freshly-reset ships."""
        if not self.running or self.ended or gen != self._generation:
            return

        for ship in self.ships:
            ship.tick_cooldowns(dt)

        status_a, pending_a = decision_a
        status_b, pending_b = decision_b
        self._finalize_side_events(self.ship_a.team, self.ship_b.id, self.ship_b.name, status_a, pending_a)
        self._finalize_side_events(self.ship_b.team, self.ship_a.id, self.ship_a.name, status_b, pending_b)

        for ship, pending in ((self.ship_a, pending_a), (self.ship_b, pending_b)):
            if pending["move_target"] is not None and pending["attack_target_id"] is None:
                tx, ty = pending["move_target"]
                ship.move_toward(tx, ty, dt)
                ship.last_action = "move"

        for ship, opponent, pending in (
            (self.ship_a, self.ship_b, pending_a),
            (self.ship_b, self.ship_a, pending_b),
        ):
            if pending["attack_target_id"] == opponent.id and ship.can_attack(opponent):
                dmg = ship.fire_at(opponent)
                opponent.take_damage(dmg)
                ship.last_action = "attack"
                self._log(f"{ship.team} attacked {opponent.name} - {opponent.name} HP -{dmg:.0f}")
                self.events.emit(ev.ATTACK, ship.team, "Attack successful", target_id=opponent.id)
                self.events.emit(
                    ev.DAMAGE, ship.team, f"{opponent.name} HP -{dmg:.0f}",
                    target_id=opponent.id, target_team=opponent.team, amount=dmg, hp_after=opponent.hp,
                )
                if not opponent.alive:
                    self._log(f"{opponent.name} destroyed. {ship.team} wins.")
                    self.events.emit(ev.DESTROYED, opponent.team, f"{opponent.name} destroyed")
                    self.events.emit(ev.BATTLE_WON, ship.team, f"{ship.team} wins")
                    self.winner = ship.team
                    self.outcome = "DESTROY_ENEMY"
                    self.ended = True
                    self.running = False

        self.tick_count += 1
        self.elapsed += dt

        # Time-limit draw (challenges/ Rules.battle_duration). Only checked
        # once at the end of the tick that crosses the threshold — no
        # separate timer loop, the existing tick loop is unchanged.
        if not self.ended and self.config.battle_duration and self.elapsed >= self.config.battle_duration:
            self._log(f"Time limit reached ({self.config.battle_duration:.0f}s). Battle ends in a draw.")
            self.events.emit(ev.BATTLE_DRAW, "", "Time limit reached - draw")
            self.outcome = "TIME_LIMIT_DRAW"
            self.ended = True
            self.running = False

    def step(self, dt: float) -> None:
        """Convenience wrapper — gather then apply in one call, exactly
        as every direct BattleEngine caller (all pre-Phase-7 tests,
        submissions/test_runner.py) already expects. BattleRunner is the
        only caller that ever calls gather_decisions()/apply_decisions()
        separately (see engine/runner.py), so this method's behavior is
        completely unchanged from before Phase 7."""
        if not self.running or self.ended:
            return
        gen, decision_a, decision_b = self.gather_decisions(dt)
        self.apply_decisions(dt, gen, decision_a, decision_b)

    # ------------------------------------------------------- worker lifecycle
    def set_worker_code(self, side: str, code: str) -> None:
        """Phase 7: restarts the given side's isolated worker with new
        code — called by BattleRunner.set_team_code() (engine/runner.py)
        AFTER compile_team_module(code) has already validated it
        synchronously in the caller's process, so a bad submission still
        raises SandboxError to the UI immediately, exactly as before;
        this only ever runs with already-known-good code. No-op when
        isolate_execution is False."""
        if not self.isolate_execution:
            return
        old = self._workers[side]
        if old is not None:
            old.shutdown()
        self._workers[side] = DecideWorker(code, self.config.code_execution_timeout)
        self._worker_dead_reported[side] = False

    def shutdown_workers(self) -> None:
        """Terminates both isolated workers, if any. Safe to call
        multiple times and safe to call when isolate_execution is False
        (no-op). Called from BattleRunner.stop_thread() and
        ui/app.py._on_close() so no worker process ever outlives the
        engine (spec section 6: application shutdown cleans up active
        workers)."""
        for side, worker in self._workers.items():
            if worker is not None:
                worker.shutdown()
            self._workers[side] = None
