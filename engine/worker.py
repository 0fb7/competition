"""Process-isolated execution of a participant's decide() (spec Phase 7
section 6).

ARCHITECTURE DECISION — one persistent worker process per side, reused
for every tick, not one process per decision:

BattleRunner ticks at 30Hz. Spawning a fresh OS process per decide() call
(twice per tick) was measured on this machine at ~0.12s per spawn (see
the Phase 7 audit) — at 60 spawns/second that overhead alone would
dwarf the entire tick budget and stall every battle even when team code
is perfectly well-behaved. A persistent worker — started once when a
side's code is (re)loaded and reused until it times out, crashes, or the
engine shuts down — keeps the steady-state cost to one Pipe round-trip
per tick (sub-millisecond locally) while still providing a REAL,
OS-enforced timeout: `Connection.poll(timeout)` does not depend on the
worker cooperating in any way, and `Process.terminate()`/`.kill()`
forcibly ends it regardless of what it's doing — including a genuine
`while True: pass` (verified directly against this exact mechanism
before building the rest of Phase 7 on top of it).

SECURITY NOTE (spec section 23) — this is real OS-level PROCESS
isolation for CRASH/HANG containment: a stuck or crashed worker can
never hang or crash BattleRunner/the main app, and it is force-killed on
timeout. It is NOT a hardened security boundary against a malicious
actor: the worker runs as the same OS user with the same filesystem/
network access as the main process, on top of (not instead of) the
existing AST-level sandbox (engine/sandbox.py) restricting imports/
builtins/dunder access. Appropriate for classroom/internal competitions
where the threat model is "buggy code," not "code deliberately written
to escape isolation." Untrusted code from hostile strangers on the
public internet would need real containerization (e.g. a locked-down
container/VM per worker, dropped privileges, no network) — out of scope
here, and not claimed.
"""

from __future__ import annotations

import multiprocessing as mp
from dataclasses import dataclass

from .config import BattleConfig

STATUS_OK = "ok"
STATUS_TIMEOUT = "timeout"
STATUS_UNAVAILABLE = "unavailable"  # worker already dead from a prior timeout/crash this battle


def _worker_main(code: str, conn) -> None:
    """Entry point for the child process (spawned via the 'spawn' start
    method, so this re-imports the engine package fresh — deliberate:
    the child never inherits any live state from the parent, only the
    plain-text `code` string). Compiles the team's code ONCE, then
    answers (friendly, enemies, config) requests until the pipe closes
    or the process is killed."""
    from .api import build_api
    from .sandbox import SandboxError, compile_team_module, run_decide

    try:
        decide_fn = compile_team_module(code)
    except SandboxError as e:
        conn.send(("compile_error", str(e)))
        return
    except Exception as e:  # never let an unexpected error hang the handshake
        conn.send(("compile_error", f"worker init failed: {e}"))
        return

    conn.send(("ready", None))

    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return  # explicit shutdown signal
        friendly, enemies, config = msg
        pending = {"move_target": None, "attack_target_id": None, "log": [], "_self": friendly}
        try:
            api = build_api(pending, config)
            status = run_decide(decide_fn, friendly, enemies, api)
        except Exception as e:  # a bug in build_api/run_decide itself, not team code
            status = f"error: {e}"
        pending.pop("_self", None)
        try:
            conn.send(("result", (status, pending)))
        except (BrokenPipeError, OSError):
            return


@dataclass
class DecideOutcome:
    status: str            # STATUS_OK / STATUS_TIMEOUT / STATUS_UNAVAILABLE
    run_status: str = "ok"  # "ok" or "error: ..." (only meaningful when status == STATUS_OK)
    pending: dict = None


class DecideWorker:
    """One persistent isolated process for one ship's decide() calls."""

    def __init__(self, code: str, timeout: float):
        self.timeout = max(0.05, float(timeout))
        self.dead = False
        self._dead_reason: str | None = None
        self._proc = None
        self._conn = None
        self._start(code)

    def _start(self, code: str) -> None:
        ctx = mp.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe()
        proc = ctx.Process(target=_worker_main, args=(code, child_conn), daemon=True)
        proc.start()
        child_conn.close()  # the parent only ever needs its own end
        self._proc, self._conn = proc, parent_conn

        if not parent_conn.poll(self.timeout):
            self._mark_dead("worker startup timed out")
            return
        try:
            kind, payload = parent_conn.recv()
        except (EOFError, OSError):
            self._mark_dead("worker crashed during startup")
            return
        if kind != "ready":
            self._mark_dead(str(payload) if payload else "worker failed to start")

    def request(self, friendly: dict, enemies: list, config: BattleConfig | None) -> DecideOutcome:
        """Blocks for at most self.timeout seconds. Returns a DecideOutcome
        — never raises, never blocks longer than the configured timeout,
        regardless of what the worker is doing."""
        if self.dead:
            return DecideOutcome(status=STATUS_UNAVAILABLE)
        try:
            self._conn.send((friendly, enemies, config))
        except (BrokenPipeError, OSError):
            self._mark_dead("pipe closed while sending request")
            return DecideOutcome(status=STATUS_UNAVAILABLE)

        if not self._conn.poll(self.timeout):
            self._mark_dead("decide() exceeded code_execution_timeout")
            return DecideOutcome(status=STATUS_TIMEOUT)

        try:
            kind, payload = self._conn.recv()
        except (EOFError, OSError):
            self._mark_dead("pipe closed while receiving result")
            return DecideOutcome(status=STATUS_UNAVAILABLE)

        if kind != "result":
            self._mark_dead(str(payload))
            return DecideOutcome(status=STATUS_UNAVAILABLE)

        run_status, pending = payload
        return DecideOutcome(status=STATUS_OK, run_status=run_status, pending=pending)

    def _mark_dead(self, reason: str) -> None:
        self.dead = True
        self._dead_reason = reason
        self._kill()

    def _kill(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=1.0)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=1.0)
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass

    def shutdown(self) -> None:
        """Graceful-then-forced teardown — always safe to call, including
        on an already-dead worker (idempotent)."""
        if not self.dead and self._conn is not None:
            try:
                self._conn.send(None)
            except Exception:
                pass
        self._kill()
