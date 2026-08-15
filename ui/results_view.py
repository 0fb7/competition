"""Results & History view — Phase 5. Makes the sidebar's "Results" /
"النتائج" nav item (formerly an unwired "Leaderboard" stub that silently
fell through to the dashboard placeholder branch) functional.

Reuses the exact visual system every other panel uses (theme.Tokens,
theme.font, panel/panel_2/accent colors, status pills) — no new palette,
no redesign. Talks only to ResultService (historical aggregation) plus
read-only TournamentService/TeamService/ChallengeService lookups for
display — never touches BattleRunner and never writes anything; this
view is purely a read/query surface over already-persisted history.
"""

import customtkinter as ctk

from . import theme
from .localization import t, is_rtl

from tournament.match import (
    OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN, OUTCOME_DRAW, OUTCOME_ERROR,
)
from tournament.round import TYPE_ROUND_ROBIN, TYPE_SINGLE_ELIMINATION, TYPE_CUSTOM

ROUND_TYPE_KEY = {TYPE_ROUND_ROBIN: "round_robin", TYPE_SINGLE_ELIMINATION: "single_elimination", TYPE_CUSTOM: "custom_round"}

RESULT_FILTER_ALL = "all"
RESULT_FILTER_WIN = "win"
RESULT_FILTER_DRAW = "draw"
RESULT_FILTER_ERROR = "error"
RESULT_FILTER_BYE = "bye"
RESULT_FILTER_KEYS = {
    RESULT_FILTER_ALL: "all_results", RESULT_FILTER_WIN: "winner", RESULT_FILTER_DRAW: "draw",
    RESULT_FILTER_ERROR: "error_status", RESULT_FILTER_BYE: "bye",
}


class ResultsView(ctk.CTkFrame):
    def __init__(self, master, tokens: theme.Tokens, result_service, tournament_service, team_service, challenge_service):
        super().__init__(master, fg_color="transparent")
        self.tokens = tokens
        self.result_service = result_service
        self.tournament_service = tournament_service
        self.team_service = team_service
        self.challenge_service = challenge_service

        self.mode = "dashboard"
        self.selected_match_id = None
        self.summary_competition_id = None
        self.hist_competition_id = None  # None == all competitions
        self.hist_team_id = None
        self.hist_result = RESULT_FILTER_ALL

        self._build_shell()
        self.refresh()

    # ------------------------------------------------------------- shell
    def _build_shell(self):
        for w in self.winfo_children():
            w.destroy()
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", pady=(0, 8))
        self.title_lbl = ctk.CTkLabel(head, text=t("results_title"), font=theme.font(16, "bold"), text_color=self.tokens.text)
        self.title_lbl.pack(side="left")

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

    def apply_language(self):
        self._build_shell()
        self.refresh()

    # ------------------------------------------------------------ status colors (mirrors competition_view.py's convention)
    def _outcome_color(self, outcome, is_bye):
        if is_bye:
            return self.tokens.text_faint
        return {
            OUTCOME_TEAM_A_WIN: self.tokens.success, OUTCOME_TEAM_B_WIN: self.tokens.success,
            OUTCOME_DRAW: self.tokens.warning, OUTCOME_ERROR: self.tokens.danger,
        }.get(outcome, self.tokens.text_faint)

    def _outcome_label(self, result):
        """DRAW gets its own distinct label/color — never reuses WIN/LOSS
        styling (spec section 9/24: draw must be a first-class, clearly
        distinct result, not just another win-colored row)."""
        if result.is_bye:
            return t("bye")
        if result.outcome == OUTCOME_DRAW:
            return t("draw")
        if result.outcome == OUTCOME_ERROR:
            return t("error_status")
        winner_name = result.team_a_name_at_match if result.winner_team_id == result.team_a_id else result.team_b_name_at_match
        return f"{t('winner')}: {winner_name or '-'}"

    # ------------------------------------------------------------ refresh
    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        if self.mode == "match_detail" and self.selected_match_id:
            result = self.result_service.get_match_result(self.selected_match_id)
            if result is None:
                self.mode = "dashboard"
                self.refresh()
                return
            self._build_match_detail(result)
        else:
            self._build_dashboard()

    # =========================================================== dashboard
    def _build_dashboard(self):
        self._build_competition_selector()
        if self.summary_competition_id:
            self._build_competition_summary(self.summary_competition_id)
            self._build_rounds(self.summary_competition_id)
        self._build_recent_matches()
        self._build_match_history()

    def _build_competition_selector(self):
        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.pack(fill="x", pady=4, padx=2)
        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(row, text=t("competition_summary"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(side="left")

        competitions = self.tournament_service.get_all_competitions()
        self._comp_name_to_id = {c.name: c.id for c in competitions}
        values = list(self._comp_name_to_id) or ["-"]
        current_name = next((n for n, i in self._comp_name_to_id.items() if i == self.summary_competition_id), values[0])
        self.summary_menu = ctk.CTkOptionMenu(
            row, values=values, fg_color=self.tokens.panel_2, button_color=self.tokens.accent,
            command=self._on_summary_competition_change,
        )
        self.summary_menu.set(current_name)
        self.summary_menu.pack(side="right")

        if not competitions:
            ctk.CTkLabel(panel, text=t("no_competitions_title"), font=theme.font(11), text_color=self.tokens.text_faint).pack(anchor="w", padx=14, pady=(0, 12))
        elif self.summary_competition_id is None:
            self.summary_competition_id = self._comp_name_to_id.get(values[0])

    def _on_summary_competition_change(self, name):
        self.summary_competition_id = self._comp_name_to_id.get(name)
        self.refresh()

    # ---------------------------------------------------- competition summary
    def _build_competition_summary(self, competition_id):
        summary = self.result_service.competition_summary(competition_id)
        if summary is None:
            return
        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.pack(fill="x", pady=4, padx=2)
        ctk.CTkLabel(panel, text=summary["competition"].name, font=theme.font(14, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=16, pady=(14, 8))

        stats_row = ctk.CTkFrame(panel, fg_color="transparent")
        stats_row.pack(fill="x", padx=16, pady=(0, 12))
        stats = [
            ("champion", summary["champion"] or t("no_champion_yet")),
            ("total_teams", str(summary["total_teams"])),
            ("total_matches", str(summary["total_matches"])),
            ("completed_matches", str(summary["completed_matches"])),
            ("draw", str(summary["draws"])),
            ("duration", f"{summary['duration']:.0f}s" if summary["duration"] else "-"),
        ]
        for i, (key, value) in enumerate(stats):
            cell = ctk.CTkFrame(stats_row, fg_color=self.tokens.panel_2, corner_radius=8)
            cell.grid(row=0, column=i, sticky="nsew", padx=4)
            stats_row.columnconfigure(i, weight=1)
            ctk.CTkLabel(cell, text=t(key), font=theme.font(9), text_color=self.tokens.text_faint).pack(anchor="w", padx=10, pady=(8, 0))
            ctk.CTkLabel(cell, text=value, font=theme.font(13, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=10, pady=(0, 8))

        self._build_leaderboard_table(panel, summary["leaderboard"])

    def _build_leaderboard_table(self, parent, rows):
        ctk.CTkLabel(parent, text=t("leaderboard"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=16, pady=(4, 6))
        if not rows:
            ctk.CTkLabel(parent, text=t("no_results_body"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=16, pady=(0, 14))
            return

        table = ctk.CTkFrame(parent, fg_color="transparent")
        table.pack(fill="x", padx=16, pady=(0, 14))
        columns = ["rank", "team", "matches_played", "wins", "losses", "draw", "win_rate", "damage_dealt", "damage_received", "score"]
        for c in range(len(columns)):
            table.columnconfigure(c, weight=1)
        for c, key in enumerate(columns):
            ctk.CTkLabel(table, text=t(key), font=theme.font(9, "bold"), text_color=self.tokens.text_faint).grid(row=0, column=c, sticky="w", padx=6, pady=(0, 4))
        for r, row in enumerate(rows, start=1):
            values = [
                str(row["rank"]), row["team_name"], str(row["played"]), str(row["wins"]), str(row["losses"]),
                str(row["draws"]), f"{row['win_rate'] * 100:.0f}%", f"{row['damage_dealt']:.0f}",
                f"{row['damage_received']:.0f}", str(row["score"]),
            ]
            for c, v in enumerate(values):
                ctk.CTkLabel(table, text=v, font=theme.font(10, mono=(c == 0)), text_color=self.tokens.text).grid(row=r, column=c, sticky="w", padx=6, pady=2)

    # -------------------------------------------------------------- rounds
    def _build_rounds(self, competition_id):
        rounds = self.tournament_service.get_competition_rounds(competition_id)
        if not rounds:
            return
        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.pack(fill="x", pady=4, padx=2)
        ctk.CTkLabel(panel, text=t("rounds"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=16, pady=(12, 6))

        for round_obj in rounds:
            summary = self.result_service.round_summary(round_obj.id)
            if summary is None:
                continue
            block = ctk.CTkFrame(panel, fg_color=self.tokens.panel_2, corner_radius=8)
            block.pack(fill="x", padx=16, pady=4)
            head = ctk.CTkFrame(block, fg_color="transparent")
            head.pack(fill="x", padx=12, pady=(10, 4))
            ctk.CTkLabel(head, text=f"{round_obj.name}  ·  {t(ROUND_TYPE_KEY.get(round_obj.round_type, 'custom_round'))}", font=theme.font(11, "bold"), text_color=self.tokens.text).pack(side="left")
            ctk.CTkLabel(head, text=t(round_obj.status.lower()) if round_obj.status.lower() in ("pending", "ready", "active", "completed", "cancelled") else round_obj.status, font=theme.font(9), text_color=self.tokens.text_faint).pack(side="right")

            if round_obj.round_type == TYPE_ROUND_ROBIN and summary["standings"]:
                ctk.CTkLabel(block, text=t("round_standings"), font=theme.font(9, "bold"), text_color=self.tokens.text_faint).pack(anchor="w", padx=12, pady=(2, 0))
                self._build_leaderboard_table(block, summary["standings"])
            else:
                info = f"{t('advanced_teams')}: " + (", ".join(summary["winners"]) if summary["winners"] else "-")
                if summary["draws"]:
                    info += f"   ·   {t('draw')}: {summary['draws']}"
                ctk.CTkLabel(block, text=info, font=theme.font(10), text_color=self.tokens.text_dim, anchor="w").pack(anchor="w", padx=12, pady=(2, 10))

    # -------------------------------------------------------- recent matches
    def _build_recent_matches(self):
        recent = self.result_service.match_history(competition_id=self.summary_competition_id)[:5]
        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.pack(fill="x", pady=4, padx=2)
        ctk.CTkLabel(panel, text=t("recent_matches"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=16, pady=(12, 6))
        if not recent:
            ctk.CTkLabel(panel, text=t("no_results_title"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=16, pady=(0, 14))
            return
        for result in recent:
            self._build_match_row(panel, result)
        ctk.CTkFrame(panel, fg_color="transparent", height=6).pack()

    # ------------------------------------------------------------ history
    def _build_match_history(self):
        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.pack(fill="x", pady=4, padx=2)
        ctk.CTkLabel(panel, text=t("match_history_title"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=16, pady=(12, 6))

        filters = ctk.CTkFrame(panel, fg_color="transparent")
        filters.pack(fill="x", padx=16, pady=(0, 8))

        competitions = self.tournament_service.get_all_competitions()
        self._hist_comp_name_to_id = {t("all_competitions"): None, **{c.name: c.id for c in competitions}}
        comp_values = list(self._hist_comp_name_to_id)
        comp_current = next((n for n, i in self._hist_comp_name_to_id.items() if i == self.hist_competition_id), comp_values[0])
        self.hist_comp_menu = ctk.CTkOptionMenu(
            filters, values=comp_values, fg_color=self.tokens.panel_2, button_color=self.tokens.accent,
            width=170, command=self._on_hist_filter_change,
        )
        self.hist_comp_menu.set(comp_current)
        self.hist_comp_menu.pack(side="left", padx=(0, 6))

        teams = self.team_service.get_all_teams()
        self._hist_team_name_to_id = {t("all_teams"): None, **{team.name: team.id for team in teams}}
        team_values = list(self._hist_team_name_to_id)
        team_current = next((n for n, i in self._hist_team_name_to_id.items() if i == self.hist_team_id), team_values[0])
        self.hist_team_menu = ctk.CTkOptionMenu(
            filters, values=team_values, fg_color=self.tokens.panel_2, button_color=self.tokens.accent,
            width=150, command=self._on_hist_filter_change,
        )
        self.hist_team_menu.set(team_current)
        self.hist_team_menu.pack(side="left", padx=6)

        self._hist_result_label_to_key = {t(v): k for k, v in RESULT_FILTER_KEYS.items()}
        result_values = list(self._hist_result_label_to_key)
        result_current = t(RESULT_FILTER_KEYS[self.hist_result])
        self.hist_result_menu = ctk.CTkOptionMenu(
            filters, values=result_values, fg_color=self.tokens.panel_2, button_color=self.tokens.accent,
            width=130, command=self._on_hist_filter_change,
        )
        self.hist_result_menu.set(result_current)
        self.hist_result_menu.pack(side="left", padx=6)

        ctk.CTkButton(filters, text=t("clear_filters"), fg_color="transparent", border_width=1, border_color=self.tokens.border, text_color=self.tokens.text_faint, command=self._clear_hist_filters).pack(side="left", padx=6)

        results = self._filtered_history()
        if not results:
            ctk.CTkLabel(panel, text=t("no_results_title"), font=theme.font(11, "bold"), text_color=self.tokens.text).pack(padx=16, pady=(4, 4))
            ctk.CTkLabel(panel, text=t("no_results_body"), font=theme.font(10), text_color=self.tokens.text_faint).pack(padx=16, pady=(0, 14))
            return
        for result in results:
            self._build_match_row(panel, result)
        ctk.CTkFrame(panel, fg_color="transparent", height=6).pack()

    def _filtered_history(self):
        results = self.result_service.match_history(competition_id=self.hist_competition_id, team_id=self.hist_team_id)
        if self.hist_result == RESULT_FILTER_BYE:
            results = [r for r in results if r.is_bye]
        elif self.hist_result == RESULT_FILTER_DRAW:
            results = [r for r in results if r.outcome == OUTCOME_DRAW]
        elif self.hist_result == RESULT_FILTER_ERROR:
            results = [r for r in results if r.outcome == OUTCOME_ERROR]
        elif self.hist_result == RESULT_FILTER_WIN:
            results = [r for r in results if not r.is_bye and r.outcome in (OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN)]
        return results

    def _on_hist_filter_change(self, _value=None):
        self.hist_competition_id = self._hist_comp_name_to_id.get(self.hist_comp_menu.get())
        self.hist_team_id = self._hist_team_name_to_id.get(self.hist_team_menu.get())
        self.hist_result = self._hist_result_label_to_key.get(self.hist_result_menu.get(), RESULT_FILTER_ALL)
        self.refresh()

    def _clear_hist_filters(self):
        self.hist_competition_id = None
        self.hist_team_id = None
        self.hist_result = RESULT_FILTER_ALL
        self.refresh()

    # --------------------------------------------------------------- rows
    def _build_match_row(self, parent, result):
        card = ctk.CTkFrame(parent, fg_color=self.tokens.panel_2, corner_radius=8)
        card.pack(fill="x", padx=16, pady=3)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=8)

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        a_ver = f" v{result.submission_a_version}" if result.submission_a_version else ""
        if result.is_bye:
            label = f"#{result.match_id.split('__m')[-1]}  {result.team_a_name_at_match}{a_ver}  —  {t('bye')}"
        else:
            b_ver = f" v{result.submission_b_version}" if result.submission_b_version else ""
            label = f"#{result.match_id.split('__m')[-1]}  {result.team_a_name_at_match}{a_ver}   {t('vs')}   {result.team_b_name_at_match}{b_ver}"
        ctk.CTkLabel(left, text=label, font=theme.font(10, mono=True), text_color=self.tokens.text_dim, anchor="w").pack(fill="x")

        sub = f"{t('challenge_label')}: {result.challenge_name_at_match}"
        if result.duration:
            sub += f"   ·   {t('duration')}: {result.duration:.1f}s"
        ctk.CTkLabel(left, text=sub, font=theme.font(9), text_color=self.tokens.text_faint, anchor="w").pack(fill="x")

        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right")
        ctk.CTkLabel(
            right, text=self._outcome_label(result), font=theme.font(9, "bold"),
            fg_color=self._outcome_color(result.outcome, result.is_bye), text_color="#0B1017",
            corner_radius=999, padx=8, height=20,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            right, text=t("view_details"), width=90, height=22, font=theme.font(9),
            fg_color=self.tokens.panel, hover_color=self.tokens.border,
            command=lambda mid=result.match_id: self._show_match_detail(mid),
        ).pack(side="right")

    # =========================================================== detail
    def _show_match_detail(self, match_id):
        self.selected_match_id = match_id
        self.mode = "match_detail"
        self.refresh()

    def _back_to_dashboard(self):
        self.mode = "dashboard"
        self.selected_match_id = None
        self.refresh()

    def _build_match_detail(self, result):
        back = ctk.CTkButton(
            self.body, text=("→ " if is_rtl() else "← ") + t("back"), fg_color="transparent",
            text_color=self.tokens.text_dim, hover_color=self.tokens.panel_2,
            command=self._back_to_dashboard, anchor="w", width=80,
        )
        back.pack(anchor="w", pady=(0, 8))

        comp = self.tournament_service.get_competition(result.competition_id)
        round_obj = self.tournament_service.get_round(result.round_id)

        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.pack(fill="x", pady=4, padx=2)
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(head, text=f"{t('match')} #{result.match_id}", font=theme.font(15, "bold"), text_color=self.tokens.text).pack(side="left")
        ctk.CTkLabel(
            head, text=self._outcome_label(result), font=theme.font(9, "bold"),
            fg_color=self._outcome_color(result.outcome, result.is_bye), text_color="#0B1017",
            corner_radius=999, padx=10, height=22,
        ).pack(side="right")

        context = f"{comp.name if comp else result.competition_id}  ·  {round_obj.name if round_obj else result.round_id}"
        ctk.CTkLabel(panel, text=context, font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=16, pady=(0, 10))

        if result.is_bye:
            ctk.CTkLabel(panel, text=t("bye_no_battle"), font=theme.font(11), text_color=self.tokens.text_dim).pack(anchor="w", padx=16, pady=(0, 16))
        else:
            self._build_sides(panel, result)
            self._build_facts(panel, result)

        self._build_timeline(result)

    def _build_sides(self, parent, result):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(4, 10))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)

        for col, (label, name, ver, hp, dealt, received) in enumerate([
            (t("team_a"), result.team_a_name_at_match, result.submission_a_version,
             result.team_a_hp_remaining, result.team_a_damage_dealt, result.team_a_damage_received),
            (t("team_b"), result.team_b_name_at_match, result.submission_b_version,
             result.team_b_hp_remaining, result.team_b_damage_dealt, result.team_b_damage_received),
        ]):
            cell = ctk.CTkFrame(row, fg_color=self.tokens.panel_2, corner_radius=8)
            cell.grid(row=0, column=col, sticky="nsew", padx=4)
            ctk.CTkLabel(cell, text=label, font=theme.font(9), text_color=self.tokens.text_faint).pack(anchor="w", padx=12, pady=(10, 0))
            ctk.CTkLabel(cell, text=f"{name}  ·  v{ver}" if ver else (name or "-"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=12)
            hp_text = f"{t('hp_remaining')}: {hp:.0f}" if hp is not None else "-"
            ctk.CTkLabel(cell, text=hp_text, font=theme.font(10), text_color=self.tokens.text_dim).pack(anchor="w", padx=12, pady=(4, 0))
            dmg_text = f"{t('damage_dealt')}: {dealt:.0f}   {t('damage_received')}: {received:.0f}" if dealt is not None else "-"
            ctk.CTkLabel(cell, text=dmg_text, font=theme.font(10), text_color=self.tokens.text_dim).pack(anchor="w", padx=12, pady=(0, 10))

    def _build_facts(self, parent, result):
        facts = ctk.CTkFrame(parent, fg_color="transparent")
        facts.pack(fill="x", padx=16, pady=(0, 14))
        lines = [
            f"{t('challenge_label')}: {result.challenge_name_at_match}",
            f"{t('duration')}: {result.duration:.1f}s" if result.duration else f"{t('duration')}: -",
            f"{result.started_at or '-'}  →  {result.ended_at or '-'}",
        ]
        for line in lines:
            ctk.CTkLabel(facts, text=line, font=theme.font(10), text_color=self.tokens.text_faint, anchor="w").pack(fill="x")

    def _build_timeline(self, result):
        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.pack(fill="x", pady=4, padx=2)
        ctk.CTkLabel(panel, text=t("battle_timeline"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=16, pady=(12, 6))

        events = self.result_service.get_match_events(result.match_id)
        if not events:
            ctk.CTkLabel(panel, text=t("no_events_recorded"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=16, pady=(0, 14))
            return

        t0 = events[0].timestamp
        lines_frame = ctk.CTkFrame(panel, fg_color="transparent")
        lines_frame.pack(fill="x", padx=16, pady=(0, 14))
        for evt in events:
            elapsed = max(0.0, evt.timestamp - t0)
            mm, ss = divmod(int(elapsed), 60)
            stamp = f"{mm:02d}:{ss:02d}"
            prefix = f"{evt.team}: " if evt.team else ""
            line = ctk.CTkFrame(lines_frame, fg_color="transparent")
            line.pack(fill="x", pady=1)
            ctk.CTkLabel(line, text=stamp, font=theme.font(9, mono=True), text_color=self.tokens.text_faint, width=50, anchor="w").pack(side="left")
            ctk.CTkLabel(line, text=f"{prefix}{evt.message}", font=theme.font(10, mono=True), text_color=self.tokens.text_dim, anchor="w").pack(side="left", fill="x", expand=True)
