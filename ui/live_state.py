"""Phase 6 — pure runtime-state logic, no Tk/UI dependencies whatsoever so
it can be unit-tested directly (tests/test_live_control.py) without a
CTk root. Every function here is a pure derivation over data that already
exists in a real BattleRunner.snapshot() / engine.events.Event / the
app's own active_match_id bookkeeping — nothing here invents telemetry
the engine never produced (spec sections 3/5/6).

This module is intentionally the ONLY place that decides what the
runtime "means" — ui/app.py calls these functions from its single
authoritative _tick() drain point and hands the results to whichever
widgets need them; no widget re-derives state on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine import events as ev

# ---------------------------------------------------------------- runtime states
IDLE = "IDLE"
PREPARING = "PREPARING"
RUNNING = "RUNNING"
PAUSED = "PAUSED"
COMPLETED = "COMPLETED"
ERROR = "ERROR"
STOPPED = "STOPPED"
RUNTIME_STATES = (IDLE, PREPARING, RUNNING, PAUSED, COMPLETED, ERROR, STOPPED)


def compute_runtime_state(
    snap: dict | None, active_match_id: str | None, admin_stopped: bool, thread_crashed: bool,
) -> str:
    """The one function that turns real BattleRunner state into a runtime
    state label. Every branch is backed by a real, already-existing
    signal:

      - thread_crashed / snap["engine_alive"] is False -> the background
        thread genuinely died (spec section 34).
      - admin_stopped -> the admin genuinely pressed Stop on a match this
        engine cycle (cleared the next time a match starts preparing).
      - snap["ended"] -> the real BattleEngine reached a real conclusion.
      - snap["running"] -> the real BattleEngine is genuinely ticking.
      - tick_count == 0 while a match is queued -> genuinely prepared
        (ships/config loaded via reset_battle) but start_battle() has not
        been called yet.
      - tick_count > 0, not running, not ended -> genuinely paused (the
        exact `running or (tick_count > 0 and not ended)` idiom already
        used throughout ui/app.py since Phase 4, reused here rather than
        reinvented).
    """
    if snap is None:
        return IDLE
    if thread_crashed or not snap.get("engine_alive", False):
        return ERROR
    if admin_stopped:
        return STOPPED
    if snap["ended"]:
        return COMPLETED
    if snap["running"]:
        return RUNNING
    if active_match_id is not None and snap["tick_count"] == 0:
        return PREPARING
    if snap["tick_count"] > 0:
        return PAUSED
    return IDLE


# ------------------------------------------------------------- team code status
READY = "READY"
CODE_RUNNING = "RUNNING"
CODE_ERROR = "ERROR"
CODE_TIMEOUT_STATUS = "TIMEOUT"
FINISHED = "FINISHED"
TEAM_CODE_STATUSES = (READY, CODE_RUNNING, CODE_ERROR, CODE_TIMEOUT_STATUS, FINISHED)


def compute_team_code_status(snap: dict, team_name: str, last_status_kind: str | None) -> str:
    """"Ready/Running/Executed/Error/Timeout/Finished" per spec sections
    10 and Phase 7 section 5 ("CODE_ERROR, CODE_TIMEOUT, ENGINE_ERROR...
    must NOT be treated as the same thing"). "Executed" is not a
    separate displayed state: decide() runs every single tick while
    RUNNING (30Hz), so a per-tick "just executed" flash has no real,
    distinct, persistent engine state behind it the way ERROR/TIMEOUT do
    (both persist as the team's most recent real outcome until a later
    tick succeeds, or forever once a worker is dead) — showing a fake,
    separate "Executed" state would violate section 3's "do not create
    fake states" for a label that would just flicker in sync with
    RUNNING. RUNNING already means "this team's code is executing every
    tick, successfully."

    `last_status_kind` is the most recent CODE_EXECUTED/CODE_ERROR/
    CODE_TIMEOUT event kind seen for this team in the live event buffer
    (None if none yet). CODE_TIMEOUT is checked before CODE_ERROR so a
    timed-out (killed) worker never gets relabeled as a plain error —
    they are genuinely different failure modes with different causes.
    """
    if snap["ended"]:
        return FINISHED
    if not snap["running"] and snap["tick_count"] == 0:
        return READY
    if last_status_kind == ev.CODE_TIMEOUT:
        return CODE_TIMEOUT_STATUS
    if last_status_kind == ev.CODE_ERROR:
        return CODE_ERROR
    return CODE_RUNNING


# ------------------------------------------------------------------ event severity
SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"
SEVERITY_SUCCESS = "SUCCESS"

_EVENT_SEVERITY = {
    ev.CODE_EXECUTED: SEVERITY_INFO,
    ev.CODE_ERROR: SEVERITY_ERROR,
    ev.CODE_TIMEOUT: SEVERITY_ERROR,
    ev.TARGET_ACQUIRED: SEVERITY_INFO,
    ev.ATTACK: SEVERITY_WARNING,
    ev.DAMAGE: SEVERITY_WARNING,
    ev.DESTROYED: SEVERITY_ERROR,
    ev.BATTLE_WON: SEVERITY_SUCCESS,
    ev.BATTLE_DRAW: SEVERITY_WARNING,
}


def event_severity(kind: str) -> str:
    """UI-presentation categorization only (spec section 9) — does not
    change what the event means or how it's persisted/aggregated
    anywhere else (results/, engine/competition.py's CompetitionTracker
    are both untouched by this)."""
    return _EVENT_SEVERITY.get(kind, SEVERITY_INFO)


def is_draw_outcome(snap: dict) -> bool:
    """The one place "is this snapshot a draw" is decided — reused by
    ui/app.py (feeds TeamPanel/Scoreboard), ui/topbar.py, and
    ui/live_monitor_view.py so all three surfaces agree with each other
    and with the real engine.outcome value (spec section 18/24)."""
    return bool(snap["ended"] and snap.get("outcome") == "TIME_LIMIT_DRAW" and snap.get("winner") is None)


# ------------------------------------------------------------------ match queue
def classify_match_queue(rounds: list, matches: list):
    """Pure classification over real tournament.round.Round / .match.Match
    records (spec section 18) — no invented scheduling. Returns
    (current, next_match, upcoming[]): `current` is the one RUNNING
    match (if any); `next_match` is the first non-bye PENDING/READY match
    in round/match-number order; `upcoming` is up to 3 more after that."""
    order_map = {r.id: r.order for r in rounds}
    ordered = sorted(
        (m for m in matches if not m.is_bye),
        key=lambda m: (order_map.get(m.round_id, 0), m.match_number),
    )
    current = next((m for m in ordered if m.status == "RUNNING"), None)
    remaining = [m for m in ordered if m.status in ("PENDING", "READY")]
    next_match = remaining[0] if remaining else None
    upcoming = remaining[1:4]
    return current, next_match, upcoming


# --------------------------------------------------------------------- alerts
@dataclass
class Alert:
    severity: str
    key: str  # localization key template, e.g. "alert_match_completed"
    context: dict = field(default_factory=dict)
    timestamp: float = 0.0


def alerts_from_events(new_events: list, team_a_name: str, team_b_name: str) -> list[Alert]:
    """Derives Alert objects from real events in this tick's new_events
    batch only — never a second, independent scan of engine state (spec
    section 25: one authoritative drain point calls this once per tick
    with exactly the events it already pulled)."""
    alerts = []
    for e in new_events:
        if e.kind == ev.CODE_TIMEOUT:
            # Deliberately its own alert — never folded into the generic
            # code-error alert (Phase 7 section 5: CODE_ERROR/CODE_TIMEOUT
            # must not be treated as the same thing).
            alerts.append(Alert(SEVERITY_ERROR, "alert_team_code_timeout", {"team": e.team, "message": e.message}, e.timestamp))
        elif e.kind == ev.CODE_ERROR:
            alerts.append(Alert(SEVERITY_ERROR, "alert_team_code_error", {"team": e.team, "message": e.message}, e.timestamp))
        elif e.kind == ev.BATTLE_WON:
            alerts.append(Alert(SEVERITY_SUCCESS, "alert_match_completed", {"winner": e.team}, e.timestamp))
        elif e.kind == ev.BATTLE_DRAW:
            alerts.append(Alert(SEVERITY_WARNING, "alert_match_draw", {}, e.timestamp))
    return alerts
