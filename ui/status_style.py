"""Phase 8 (Step 8) — the single source of truth for status label/color
mappings that were previously copy-pasted, byte-for-byte, across multiple
UI modules (competition status in competition_view.py AND
live_monitor_view.py; team status in teams_view.py's list AND detail
cards; runtime state color in topbar.py AND live_monitor_view.py; the
ship battle status derivation in ui/app.py AND team_panel.py). Every
mapping here reuses the EXACT colors/labels those modules already agreed
on — this is a consolidation, not a redesign; no screen's visible status
pill changes color or text as a result of this module existing.

Every function/dict here returns a `theme.Tokens` ATTRIBUTE NAME (a
string like "success"), not a resolved color, so callers still do
`getattr(tokens, attr)` against their own tokens instance — this module
holds no CTk widgets and no theme.Tokens reference of its own.
"""

from __future__ import annotations

from roster.team import STATUS_READY as T_READY, STATUS_IN_BATTLE as T_IN_BATTLE, \
    STATUS_DISABLED as T_DISABLED, STATUS_NOT_READY as T_NOT_READY
from tournament.competition import (
    STATUS_DRAFT as C_DRAFT, STATUS_READY as C_READY, STATUS_ACTIVE as C_ACTIVE,
    STATUS_PAUSED as C_PAUSED, STATUS_COMPLETED as C_COMPLETED, STATUS_ARCHIVED as C_ARCHIVED,
)
from . import live_state

# --------------------------------------------------------------- team status
TEAM_STATUS_LABEL_KEY = {
    T_READY: "ready", T_IN_BATTLE: "in_battle",
    T_DISABLED: "disabled_status", T_NOT_READY: "not_ready",
}
TEAM_STATUS_COLOR_ATTR = {
    T_READY: "success", T_IN_BATTLE: "accent_glow",
    T_DISABLED: "text_faint", T_NOT_READY: "warning",
}

# ---------------------------------------------------------- competition status
COMPETITION_STATUS_LABEL_KEY = {
    C_DRAFT: "draft", C_READY: "ready", C_ACTIVE: "active",
    C_PAUSED: "paused", C_COMPLETED: "completed", C_ARCHIVED: "archived",
}
COMPETITION_STATUS_COLOR_ATTR = {
    C_DRAFT: "text_faint", C_READY: "warning", C_ACTIVE: "success",
    C_PAUSED: "warning", C_COMPLETED: "accent_glow", C_ARCHIVED: "text_faint",
}

# --------------------------------------------------------------- runtime state
RUNTIME_STATE_LABEL_KEY = {
    live_state.IDLE: "idle", live_state.PREPARING: "preparing", live_state.RUNNING: "live",
    live_state.PAUSED: "paused", live_state.COMPLETED: "completed", live_state.ERROR: "error_status",
    live_state.STOPPED: "stopped",
}
RUNTIME_STATE_COLOR_ATTR = {
    live_state.IDLE: "text_faint", live_state.PREPARING: "warning", live_state.RUNNING: "danger",
    live_state.PAUSED: "text_faint", live_state.COMPLETED: "accent_glow", live_state.ERROR: "danger",
    live_state.STOPPED: "text_faint",
}

# ------------------------------------------------------------ ship battle status
# The one derivation of "what is this ship's on-screen status" — WIN/LOSS
# come from BattleEngine.winner elsewhere; this is only the live
# ACTIVE/DAMAGED/DESTROYED/DRAW label shown while a battle is in progress
# or just ended. DRAW is always checked first — it must never be
# overridden by a per-ship alive/hp reading (spec: DRAW is a distinct,
# first-class result, never folded into ACTIVE/DESTROYED/DAMAGED).
SHIP_STATUS_COLOR_ATTR = {
    "active": "success", "damaged": "warning", "destroyed": "danger", "draw": "warning",
}


def ship_battle_status(ship: dict, is_draw: bool = False) -> str:
    if is_draw:
        return "draw"
    if not ship["alive"]:
        return "destroyed"
    if ship["hp_pct"] < 0.5:
        return "damaged"
    return "active"
