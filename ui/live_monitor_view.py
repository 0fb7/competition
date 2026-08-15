"""Live Competition Control & Real-Time Monitoring screen — Phase 6.

Reuses the exact visual system every other panel uses (theme.Tokens,
theme.font, panel/panel_2/accent colors, the same status-pill convention
established in competition_view.py/results_view.py) — no new palette.

This view NEVER calls BattleRunner.snapshot() itself and schedules NO
`after()` callbacks of its own — every piece of live data it shows is
pushed into it once per tick via update_from_tick(), called from
ui/app.py's single authoritative _tick() drain point (spec section 25).
That also means there is nothing here for App._on_close() to cancel or
shut down — closing the app just stops re-calling update_from_tick().

Controls (Pause/Resume/Reset/Stop, competition lifecycle, Start Match)
are thin callbacks into ui/app.py / TournamentService — this view holds
no battle state and makes no engine/tournament decisions of its own.
"""

import time

import customtkinter as ctk

from . import theme, status_style
from .localization import t, is_rtl

from engine import events as ev
from ui import live_state
from tournament.competition import STATUS_DRAFT, STATUS_READY, STATUS_ACTIVE, STATUS_PAUSED, STATUS_COMPLETED, STATUS_ARCHIVED, ValidationError
from tournament.match import (
    STATUS_PENDING as M_PENDING, STATUS_READY as M_READY, STATUS_RUNNING as M_RUNNING,
    STATUS_COMPLETED as M_COMPLETED, STATUS_CANCELLED as M_CANCELLED, STATUS_ERROR as M_ERROR,
)

# Phase 8: competition/runtime-state label+color now come from
# ui/status_style.py (the one place this project keeps them) instead of a
# second copy that used to live here AND in topbar.py/competition_view.py.
COMP_STATUS_KEY = status_style.COMPETITION_STATUS_LABEL_KEY
MATCH_STATUS_KEY = {
    M_PENDING: "pending", M_READY: "ready", M_RUNNING: "running",
    M_COMPLETED: "completed", M_CANCELLED: "cancelled", M_ERROR: "error_status",
}
RUNTIME_STATE_KEY = status_style.RUNTIME_STATE_LABEL_KEY
TEAM_CODE_STATUS_KEY = {
    live_state.READY: "ready", live_state.CODE_RUNNING: "running",
    live_state.CODE_ERROR: "error_status", live_state.CODE_TIMEOUT_STATUS: "timeout_status",
    live_state.FINISHED: "completed",
}
SEVERITY_COLOR_ATTR = {
    live_state.SEVERITY_INFO: "text_dim", live_state.SEVERITY_WARNING: "warning",
    live_state.SEVERITY_ERROR: "danger", live_state.SEVERITY_SUCCESS: "success",
}
MAX_EVENT_ROWS = 60   # spec section 27: bounded on-screen list; full 200-event buffer stays in self.live_events
MAX_ALERT_ROWS = 20


class LiveMonitorView(ctk.CTkFrame):
    def __init__(
        self, master, tokens: theme.Tokens, tournament_service, team_service, challenge_service, result_service,
        on_start_match, on_pause, on_resume, on_confirm_reset, on_confirm_stop, on_acknowledge_error,
    ):
        super().__init__(master, fg_color="transparent")
        self.tokens = tokens
        self.tournament_service = tournament_service
        self.team_service = team_service
        self.challenge_service = challenge_service
        self.result_service = result_service
        self.on_start_match = on_start_match
        self.on_pause = on_pause
        self.on_resume = on_resume
        self.on_confirm_reset = on_confirm_reset
        self.on_confirm_stop = on_confirm_stop
        self.on_acknowledge_error = on_acknowledge_error

        self.selected_competition_id = None
        self._last_alert_count = 0

        self._build_shell()
        self.refresh()

    # ------------------------------------------------------------- shell
    def _build_shell(self):
        for w in self.winfo_children():
            w.destroy()

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(head, text=t("live_monitoring_title"), font=theme.font(16, "bold"), text_color=self.tokens.text).pack(side="left")

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

    def apply_language(self):
        self._build_shell()
        self.refresh()

    def notify_alert(self):
        pass  # hook point for a future toast/sound; alerts are already rendered every tick

    # ------------------------------------------------------------ refresh
    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        self._build_competition_control()
        self._build_match_monitor_row()
        self._build_event_stream_and_alerts()

    # =========================================================== competition control (spec section 17)
    def _build_competition_control(self):
        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.pack(fill="x", pady=4, padx=2)
        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(row, text=t("competition_status_title"), font=theme.font(13, "bold"), text_color=self.tokens.text).pack(side="left")

        competitions = self.tournament_service.get_all_competitions()
        self._comp_name_to_id = {c.name: c.id for c in competitions}
        values = list(self._comp_name_to_id) or ["-"]
        if self.selected_competition_id is None and competitions:
            active = next((c for c in competitions if c.status == STATUS_ACTIVE), competitions[0])
            self.selected_competition_id = active.id
        current_name = next((n for n, i in self._comp_name_to_id.items() if i == self.selected_competition_id), values[0])
        self.comp_menu = ctk.CTkOptionMenu(
            row, values=values, fg_color=self.tokens.panel_2, button_color=self.tokens.accent,
            command=self._on_competition_change,
        )
        self.comp_menu.set(current_name)
        self.comp_menu.pack(side="right")

        if not competitions:
            ctk.CTkLabel(panel, text=t("no_competitions_title"), font=theme.font(11), text_color=self.tokens.text_faint).pack(anchor="w", padx=14, pady=(0, 14))
            return

        comp = self.tournament_service.get_competition(self.selected_competition_id)
        if comp is None:
            return

        info = ctk.CTkFrame(panel, fg_color="transparent")
        info.pack(fill="x", padx=14, pady=(0, 6))
        ctk.CTkLabel(
            info, text=t(COMP_STATUS_KEY[comp.status]), font=theme.font(9, "bold"),
            fg_color=self._comp_status_color(comp.status), text_color="#0B1017",
            corner_radius=999, padx=10, height=20,
        ).pack(side="left")

        rounds = self.tournament_service.get_competition_rounds(comp.id)
        matches = self.tournament_service.get_competition_matches(comp.id)
        active_round = next((r for r in rounds if r.status == "ACTIVE"), None)
        completed = sum(1 for m in matches if m.status == M_COMPLETED)
        remaining = sum(1 for m in matches if m.status in (M_PENDING, M_READY))
        current = next((m for m in matches if m.status == M_RUNNING), None)

        stats_row = ctk.CTkFrame(panel, fg_color="transparent")
        stats_row.pack(fill="x", padx=14, pady=(2, 10))
        stats = [
            ("round", active_round.name if active_round else "-"),
            ("current_match_label", f"#{current.match_number}" if current else "-"),
            ("completed_matches", str(completed)),
            ("matches_remaining", str(remaining)),
        ]
        for i, (key, value) in enumerate(stats):
            cell = ctk.CTkFrame(stats_row, fg_color=self.tokens.panel_2, corner_radius=8)
            cell.grid(row=0, column=i, sticky="nsew", padx=4)
            stats_row.columnconfigure(i, weight=1)
            ctk.CTkLabel(cell, text=t(key), font=theme.font(9), text_color=self.tokens.text_faint).pack(anchor="w", padx=10, pady=(8, 0))
            ctk.CTkLabel(cell, text=value, font=theme.font(13, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=10, pady=(0, 8))

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(0, 6))
        if comp.status == STATUS_READY:
            ctk.CTkButton(actions, text=t("start_competition"), fg_color=self.tokens.accent, command=lambda: self._lifecycle(comp.id, self.tournament_service.start_competition)).pack(side="left", padx=(0, 6))
        if comp.status == STATUS_ACTIVE:
            ctk.CTkButton(actions, text=t("pause_competition"), fg_color=self.tokens.panel_2, hover_color=self.tokens.border, command=lambda: self._lifecycle(comp.id, self.tournament_service.pause_competition)).pack(side="left", padx=(0, 6))
            ctk.CTkButton(actions, text=t("complete_competition"), fg_color=self.tokens.panel_2, hover_color=self.tokens.border, command=lambda: self._lifecycle(comp.id, self.tournament_service.complete_competition)).pack(side="left", padx=(0, 6))
        if comp.status == STATUS_PAUSED:
            ctk.CTkButton(actions, text=t("resume_competition"), fg_color=self.tokens.accent, command=lambda: self._lifecycle(comp.id, self.tournament_service.resume_competition)).pack(side="left", padx=(0, 6))

        self._build_mini_leaderboard(panel, comp.id)
        self._build_match_queue(panel, rounds, matches)

    def _comp_status_color(self, status):
        return getattr(self.tokens, status_style.COMPETITION_STATUS_COLOR_ATTR[status])

    def _on_competition_change(self, name):
        self.selected_competition_id = self._comp_name_to_id.get(name)
        self.refresh()

    def _lifecycle(self, competition_id, fn):
        try:
            fn(competition_id)
        except ValidationError:
            pass
        self.refresh()

    def _build_mini_leaderboard(self, parent, competition_id):
        board = self.result_service.leaderboard(competition_id)
        if not board:
            return
        ctk.CTkLabel(parent, text=t("leaderboard"), font=theme.font(11, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=14, pady=(6, 4))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 10))
        for i, r in enumerate(board[:5]):
            ctk.CTkLabel(
                row, text=f"#{r['rank']} {r['team_name']} · {r['score']}", font=theme.font(10, mono=True),
                text_color=self.tokens.text_dim,
            ).pack(anchor="w")

    # ------------------------------------------------------- match queue (spec section 18)
    def _build_match_queue(self, parent, rounds, matches):
        ctk.CTkLabel(parent, text=t("match_queue"), font=theme.font(11, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=14, pady=(4, 4))

        current_m, next_m, upcoming = live_state.classify_match_queue(rounds, matches)

        rows_frame = ctk.CTkFrame(parent, fg_color="transparent")
        rows_frame.pack(fill="x", padx=14, pady=(0, 12))
        for label_key, m in (("current", current_m), ("next_match", next_m)):
            if m is None:
                continue
            self._queue_row(rows_frame, label_key, m)
        for m in upcoming[:3]:
            self._queue_row(rows_frame, "upcoming", m)

    def _queue_row(self, parent, label_key, match):
        team_a = self.team_service.get_team(match.team_a_id)
        team_b = self.team_service.get_team(match.team_b_id) if match.team_b_id else None
        row = ctk.CTkFrame(parent, fg_color=self.tokens.panel_2, corner_radius=8)
        row.pack(fill="x", pady=2)
        text = f"{t(label_key)} · #{match.match_number}  {team_a.name if team_a else '-'}  {t('vs')}  {team_b.name if team_b else '-'}"
        ctk.CTkLabel(row, text=text, font=theme.font(10), text_color=self.tokens.text_dim, anchor="w").pack(side="left", padx=10, pady=6, fill="x", expand=True)
        ctk.CTkLabel(
            row, text=t(MATCH_STATUS_KEY.get(match.status, "pending")), font=theme.font(9, "bold"),
            text_color=self.tokens.text_faint,
        ).pack(side="right", padx=10)
        if match.status == M_READY:
            can_start, _reason = self.tournament_service.can_start_match(match.id)
            ctk.CTkButton(
                row, text=t("start_match"), width=90, height=22, font=theme.font(9),
                fg_color=self.tokens.accent if can_start else self.tokens.panel, state="normal" if can_start else "disabled",
                command=lambda mid=match.id: self.on_start_match(mid),
            ).pack(side="right", padx=(0, 6))

    # =========================================================== live match monitor + engine health
    def _build_match_monitor_row(self):
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", pady=4, padx=2)
        row.columnconfigure(0, weight=3)
        row.columnconfigure(1, weight=2)

        self.monitor_panel = ctk.CTkFrame(row, fg_color=self.tokens.panel, corner_radius=10)
        self.monitor_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._build_monitor_contents(self.monitor_panel)

        self.health_panel = ctk.CTkFrame(row, fg_color=self.tokens.panel, corner_radius=10)
        self.health_panel.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._build_health_contents(self.health_panel)

    def _build_monitor_contents(self, panel):
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(head, text=t("live_match_monitor"), font=theme.font(13, "bold"), text_color=self.tokens.text).pack(side="left")
        self.runtime_pill = ctk.CTkLabel(
            head, text=t("idle"), font=theme.font(9, "bold"), fg_color=self.tokens.text_faint,
            text_color="#0B1017", corner_radius=999, padx=10, height=20,
        )
        self.runtime_pill.pack(side="right")

        self.context_lbl = ctk.CTkLabel(panel, text="-", font=theme.font(10), text_color=self.tokens.text_faint, anchor="w")
        self.context_lbl.pack(fill="x", padx=14)

        controls = ctk.CTkFrame(panel, fg_color="transparent")
        controls.pack(fill="x", padx=14, pady=(8, 8))
        self.pause_btn = ctk.CTkButton(controls, text=t("pause"), fg_color=self.tokens.panel_2, hover_color=self.tokens.border, command=self.on_pause)
        self.pause_btn.pack(side="left", padx=(0, 4))
        self.resume_btn = ctk.CTkButton(controls, text=t("resume"), fg_color=self.tokens.accent, command=self.on_resume)
        self.resume_btn.pack(side="left", padx=4)
        self.reset_btn = ctk.CTkButton(
            controls, text=t("reset"), fg_color="transparent", border_width=1,
            border_color=self.tokens.warning, text_color=self.tokens.warning, command=self.on_confirm_reset,
        )
        self.reset_btn.pack(side="left", padx=4)
        self.stop_btn = ctk.CTkButton(
            controls, text=t("stop"), fg_color="transparent", border_width=1,
            border_color=self.tokens.danger, text_color=self.tokens.danger, command=self.on_confirm_stop,
        )
        self.stop_btn.pack(side="left", padx=4)

        time_row = ctk.CTkFrame(panel, fg_color="transparent")
        time_row.pack(fill="x", padx=14, pady=(0, 8))
        self.elapsed_lbl = ctk.CTkLabel(time_row, text=f"{t('duration')}: -", font=theme.font(10), text_color=self.tokens.text_dim)
        self.elapsed_lbl.pack(side="left")
        self.remaining_lbl = ctk.CTkLabel(time_row, text="", font=theme.font(10), text_color=self.tokens.text_dim)
        self.remaining_lbl.pack(side="left", padx=(12, 0))

        sides = ctk.CTkFrame(panel, fg_color="transparent")
        sides.pack(fill="x", padx=14, pady=(0, 14))
        sides.columnconfigure(0, weight=1)
        sides.columnconfigure(1, weight=1)
        self.side_widgets = {}
        for col, side in enumerate(("alpha", "beta")):
            cell = ctk.CTkFrame(sides, fg_color=self.tokens.panel_2, corner_radius=8)
            cell.grid(row=0, column=col, sticky="nsew", padx=4)
            name_lbl = ctk.CTkLabel(cell, text="-", font=theme.font(12, "bold"), text_color=self.tokens.text)
            name_lbl.pack(anchor="w", padx=10, pady=(8, 0))
            code_pill = ctk.CTkLabel(
                cell, text=t("ready"), font=theme.font(8, "bold"), fg_color=self.tokens.text_faint,
                text_color="#0B1017", corner_radius=999, padx=8, height=16,
            )
            code_pill.pack(anchor="w", padx=10, pady=(2, 4))
            hp_lbl = ctk.CTkLabel(cell, text=f"{t('health')} -", font=theme.font(9), text_color=self.tokens.text_faint)
            hp_lbl.pack(anchor="w", padx=10)
            hp_bar = ctk.CTkProgressBar(cell, height=6, progress_color=self.tokens.success)
            hp_bar.pack(fill="x", padx=10, pady=(2, 4))
            en_lbl = ctk.CTkLabel(cell, text=f"{t('energy')} -", font=theme.font(9), text_color=self.tokens.text_faint)
            en_lbl.pack(anchor="w", padx=10)
            en_bar = ctk.CTkProgressBar(cell, height=6, progress_color=self.tokens.accent_glow)
            en_bar.pack(fill="x", padx=10, pady=(2, 6))
            detail_lbl = ctk.CTkLabel(cell, text="-", font=theme.font(9), text_color=self.tokens.text_faint, anchor="w", justify="left")
            detail_lbl.pack(fill="x", padx=10, pady=(0, 10))
            self.side_widgets[side] = {
                "name": name_lbl, "code_pill": code_pill, "hp_lbl": hp_lbl, "hp_bar": hp_bar,
                "en_lbl": en_lbl, "en_bar": en_bar, "detail": detail_lbl,
            }

    def _build_health_contents(self, panel):
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 8))
        ctk.CTkLabel(head, text=t("engine_health_title"), font=theme.font(13, "bold"), text_color=self.tokens.text).pack(side="left")
        # Phase 7 section 15: only ever enabled when App.can_acknowledge_error()
        # says the runtime has demonstrably kept ticking since the fault —
        # see update_from_tick(). Clicking it while disabled does nothing;
        # the command itself (on_acknowledge_error) independently refuses
        # to clear the latch unless still healthy, so this is defense in
        # depth, not the only guard.
        self.ack_error_btn = ctk.CTkButton(
            head, text=t("acknowledge_error"), width=90, height=22, font=theme.font(9),
            fg_color=self.tokens.panel_2, hover_color=self.tokens.border,
            state="disabled", command=self.on_acknowledge_error,
        )
        self.ack_error_btn.pack(side="right")
        self.health_rows = {}
        specs = [
            ("engine_status", "engine_status_label"), ("runner_status", "runner_status_label"),
            ("thread_status", "thread_status_label"), ("fps", "fps"), ("tick_count", "tick_count"),
            ("sim_time", "simulation_time"), ("ui_rate", "ui_update_rate"),
            ("last_event", "last_event"), ("last_event_time", "last_event_time"),
        ]
        for key, label_key in specs:
            row = ctk.CTkFrame(panel, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=1)
            ctk.CTkLabel(row, text=t(label_key), font=theme.font(9), text_color=self.tokens.text_faint).pack(side="left")
            val = ctk.CTkLabel(row, text="-", font=theme.font(9, "bold"), text_color=self.tokens.text)
            val.pack(side="right")
            self.health_rows[key] = val
        ctk.CTkFrame(panel, fg_color="transparent", height=8).pack()

    # ---------------------------------------------------- event stream + alerts
    def _build_event_stream_and_alerts(self):
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", pady=4, padx=2)
        row.columnconfigure(0, weight=3)
        row.columnconfigure(1, weight=2)

        stream_panel = ctk.CTkFrame(row, fg_color=self.tokens.panel, corner_radius=10)
        stream_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        ctk.CTkLabel(stream_panel, text=t("event_stream_title"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=14, pady=(10, 4))
        self.event_box = ctk.CTkTextbox(
            stream_panel, height=180, fg_color=self.tokens.panel_2, text_color=self.tokens.text_dim,
            font=theme.font(10, mono=True), wrap="word", state="disabled",
        )
        self.event_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for sev, attr in SEVERITY_COLOR_ATTR.items():
            self.event_box.tag_config(sev, foreground=getattr(self.tokens, attr))

        alerts_panel = ctk.CTkFrame(row, fg_color=self.tokens.panel, corner_radius=10)
        alerts_panel.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        ctk.CTkLabel(alerts_panel, text=t("alerts_title"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=14, pady=(10, 4))
        self.alerts_box = ctk.CTkTextbox(
            alerts_panel, height=180, fg_color=self.tokens.panel_2, text_color=self.tokens.text_dim,
            font=theme.font(10, mono=True), wrap="word", state="disabled",
        )
        self.alerts_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for sev, attr in SEVERITY_COLOR_ATTR.items():
            self.alerts_box.tag_config(sev, foreground=getattr(self.tokens, attr))

        self._last_rendered_event_ids = set()
        self._last_alert_len = 0

    # ============================================================== per-tick
    def update_from_tick(
        self, snap, runtime_state, active_match_id, match_context, team_code_status,
        last_target, live_events, alerts, runtime_log, ui_update_hz, embedded_fps, engine_faults,
        can_acknowledge_error=False,
    ):
        if not hasattr(self, "runtime_pill") or not self.winfo_exists():
            return

        label_key = RUNTIME_STATE_KEY.get(runtime_state, "idle")
        color = getattr(self.tokens, status_style.RUNTIME_STATE_COLOR_ATTR.get(runtime_state, "text_faint"))
        self.runtime_pill.configure(text=t(label_key), fg_color=color)
        self.ack_error_btn.configure(state="normal" if can_acknowledge_error else "disabled")

        self.pause_btn.configure(state="normal" if runtime_state == live_state.RUNNING else "disabled")
        self.resume_btn.configure(state="normal" if runtime_state == live_state.PAUSED else "disabled")
        self.stop_btn.configure(state="normal" if active_match_id is not None else "disabled")

        if runtime_state == live_state.PREPARING:
            # Phase 8 (BACKLOG #17): make the bounded worker-spawn pause an
            # explicit, visible message instead of a silent freeze — this
            # is real text shown for the real window App._on_start_match()
            # holds `_match_preparing`, not a cosmetic-only label.
            self.context_lbl.configure(text=t("preparing_workers_message"))
        elif match_context:
            ctx = match_context
            self.context_lbl.configure(text=f"{ctx['competition'].name} · {ctx['round'].name} · #{ctx['match'].match_number}")
        else:
            self.context_lbl.configure(text=t("no_active_match"))

        self.elapsed_lbl.configure(text=f"{t('duration')}: {snap['elapsed']:.1f}s")
        remaining = snap.get("time_remaining")
        self.remaining_lbl.configure(text=f"{t('remaining_time')}: {remaining:.1f}s" if remaining is not None else "")

        for side, ship_key in (("alpha", "ship_a"), ("beta", "ship_b")):
            ship = snap[ship_key]
            w = self.side_widgets[side]
            w["name"].configure(text=ship["team"].upper())
            code_status = team_code_status.get(side, live_state.READY)
            code_color = {
                live_state.READY: self.tokens.text_faint, live_state.CODE_RUNNING: self.tokens.success,
                live_state.CODE_ERROR: self.tokens.danger, live_state.CODE_TIMEOUT_STATUS: self.tokens.danger,
                live_state.FINISHED: self.tokens.accent_glow,
            }.get(code_status, self.tokens.text_faint)
            w["code_pill"].configure(text=t(TEAM_CODE_STATUS_KEY.get(code_status, "ready")), fg_color=code_color)
            w["hp_lbl"].configure(text=f"{t('health')} {ship['hp_pct']*100:.0f}%")
            w["hp_bar"].set(max(0.0, ship["hp_pct"]))
            w["en_lbl"].configure(text=f"{t('energy')} {ship['energy_pct']*100:.0f}%")
            w["en_bar"].set(max(0.0, ship["energy_pct"]))
            target = last_target.get(side)
            cooldown = ship.get("attack_cooldown", 0.0)
            detail = (
                f"{t('position')}: ({ship['x']:.0f}, {ship['y']:.0f})   "
                f"{t('attack_cooldown_label')}: {cooldown:.1f}s\n"
                f"{t('current_target')}: {target or '-'}"
            )
            w["detail"].configure(text=detail)

        # ---- engine health (spec section 6) ----
        self.health_rows["engine_status"].configure(text=t(label_key))
        self.health_rows["runner_status"].configure(
            text=t("online") if snap["engine_alive"] else t("error_status"),
        )
        self.health_rows["thread_status"].configure(
            text=t("running") if snap["engine_alive"] else t("stopped"),
        )
        self.health_rows["fps"].configure(text=f"{embedded_fps:.0f}" if embedded_fps else t("not_available"))
        self.health_rows["tick_count"].configure(text=str(snap["tick_count"]))
        self.health_rows["sim_time"].configure(text=f"{snap['elapsed']:.1f}s")
        self.health_rows["ui_rate"].configure(text=f"{ui_update_hz:.1f} Hz" if ui_update_hz else t("not_available"))
        if live_events:
            last = live_events[-1]
            self.health_rows["last_event"].configure(text=last.kind)
            self.health_rows["last_event_time"].configure(text=time.strftime("%H:%M:%S", time.localtime(last.timestamp)))
        else:
            self.health_rows["last_event"].configure(text=t("not_available"))
            self.health_rows["last_event_time"].configure(text="-")

        self._render_events(live_events)
        self._render_alerts(alerts)

    # ------------------------------------------------------------- rendering
    def _render_events(self, live_events: list):
        # Only re-render when the tail actually changed — avoids
        # rebuilding a scrolling textbox every single tick when nothing
        # new happened (spec section 26: UI must stay responsive).
        tail = live_events[-MAX_EVENT_ROWS:]
        ids = tuple(id(e) for e in tail)
        if ids == getattr(self, "_last_event_ids", None):
            return
        self._last_event_ids = ids

        self.event_box.configure(state="normal")
        self.event_box.delete("1.0", "end")
        for e in tail:
            sev = live_state.event_severity(e.kind)
            stamp = time.strftime("%H:%M:%S", time.localtime(e.timestamp))
            prefix = f"{e.team}: " if e.team else ""
            self.event_box.insert("end", f"[{stamp}] {e.kind}  {prefix}{e.message}\n", sev)
        self.event_box.see("end")
        self.event_box.configure(state="disabled")

    def _render_alerts(self, alerts: list):
        tail = alerts[-MAX_ALERT_ROWS:]
        if len(tail) == self._last_alert_len:
            return
        self._last_alert_len = len(tail)

        self.alerts_box.configure(state="normal")
        self.alerts_box.delete("1.0", "end")
        for a in tail:
            stamp = time.strftime("%H:%M:%S", time.localtime(a.timestamp)) if a.timestamp else "-"
            message = t(a.key)
            if a.context.get("team"):
                message = f"{a.context['team']} — {message}"
            # Phase 8 (BACKLOG #6): surface the actual detail (e.g. the
            # forbidden API function name, or "exceeded 2.0s") alongside
            # the generic localized label instead of only the label —
            # this is exactly the real event.message ForbiddenAPIError/
            # CODE_TIMEOUT already carry (engine/api.py, engine/battle.py),
            # never a fabricated string. Strip the internal "error: "
            # prefix engine/sandbox.py's run_decide() adds — a UI-facing
            # detail, not a Python traceback.
            detail = (a.context.get("message") or "").strip()
            if detail.startswith("error: "):
                detail = detail[len("error: "):]
            if detail:
                message = f"{message}: {detail}"
            self.alerts_box.insert("end", f"[{stamp}] {message}\n", a.severity)
        self.alerts_box.see("end")
        self.alerts_box.configure(state="disabled")
