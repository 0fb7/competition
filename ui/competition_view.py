"""Competition management view — makes the "Competition" / "المسابقة"
nav item functional. Reuses the same visual system as every other panel
(theme.Tokens, theme.font, panel/panel_2/accent colors). Talks only to
TournamentService (never tournament_repository.py / data/tournament/*
directly), plus read-only TeamService/ChallengeService/SubmissionService
lookups for display.

Match execution itself is NOT done here — `on_start_match(match_id)` is
a callback into ui/app.py, the one place allowed to touch BattleRunner
(same bridging pattern as roster/challenges/submissions before it).
"""

import tkinter.messagebox as messagebox

import customtkinter as ctk

from . import theme, status_style
from .localization import t, is_rtl
from tournament.competition import STATUS_DRAFT, STATUS_READY, STATUS_ACTIVE, STATUS_PAUSED, STATUS_COMPLETED, STATUS_ARCHIVED, ValidationError
from tournament.round import TYPE_ROUND_ROBIN, TYPE_SINGLE_ELIMINATION, TYPE_CUSTOM, STATUS_COMPLETED as ROUND_COMPLETED
from tournament.match import (
    STATUS_PENDING as M_PENDING, STATUS_READY as M_READY, STATUS_RUNNING as M_RUNNING,
    STATUS_COMPLETED as M_COMPLETED, STATUS_CANCELLED as M_CANCELLED, STATUS_ERROR as M_ERROR,
    OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN, OUTCOME_DRAW,
)

# Phase 8: competition status label now comes from ui/status_style.py (the
# one place this project keeps it) instead of a second copy that used to
# live here AND in live_monitor_view.py.
COMP_STATUS_KEY = status_style.COMPETITION_STATUS_LABEL_KEY
MATCH_STATUS_KEY = {
    M_PENDING: "pending", M_READY: "ready", M_RUNNING: "running",
    M_COMPLETED: "completed", M_CANCELLED: "cancelled", M_ERROR: "error_status",
}
ROUND_TYPE_KEY = {TYPE_ROUND_ROBIN: "round_robin", TYPE_SINGLE_ELIMINATION: "single_elimination", TYPE_CUSTOM: "custom_round"}

ERROR_KEY = {
    "empty_id": "error_empty_challenge_id", "invalid_id": "error_invalid_challenge_id",
    "duplicate_id": "error_duplicate_challenge_id", "empty_name": "error_empty_name",
    "challenge_not_found": "select_challenge", "not_enough_teams": "error_not_enough_teams",
    "team_not_eligible": "error_team_not_eligible", "team_already_added": "error_team_already_added",
    "team_disabled": "error_team_disabled", "team_not_found": "error_team_not_eligible",
    "no_rounds": "error_no_rounds", "cannot_edit_locked_structure": "cannot_edit_locked_structure",
    "cannot_delete_active": "cannot_delete_active_competition",
    "cannot_delete_historical": "cannot_delete_historical_competition",
}


class CompetitionView(ctk.CTkFrame):
    def __init__(
        self, master, tokens: theme.Tokens, tournament_service, team_service,
        challenge_service, submission_service, on_start_match, on_changed=None,
    ):
        super().__init__(master, fg_color="transparent")
        self.tokens = tokens
        self.service = tournament_service
        self.team_service = team_service
        self.challenge_service = challenge_service
        self.submission_service = submission_service
        self.on_start_match = on_start_match
        self.on_changed = on_changed or (lambda: None)

        self.mode = "list"
        self.selected_id = None
        self._build_shell()
        self.refresh()

    # ------------------------------------------------------------- shell
    def _build_shell(self):
        for w in self.winfo_children():
            w.destroy()
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", pady=(0, 8))
        self.title_lbl = ctk.CTkLabel(head, text=t("competitions_title"), font=theme.font(16, "bold"), text_color=self.tokens.text)
        self.title_lbl.pack(side="left")
        self.create_btn = ctk.CTkButton(head, text="+  " + t("create_competition"), fg_color=self.tokens.accent, command=self._show_create_form)
        self.create_btn.pack(side="right")

        self.error_lbl = ctk.CTkLabel(self, text="", font=theme.font(11), text_color=self.tokens.danger)
        self.error_lbl.pack(fill="x", pady=(0, 4))

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

    def apply_language(self):
        self._build_shell()
        self.refresh()

    def _clear_error(self):
        self.error_lbl.configure(text="")

    def _show_error(self, code: str):
        key = ERROR_KEY.get(code)
        self.error_lbl.configure(text=t(key) if key else code)

    def _status_color(self, status):
        return getattr(self.tokens, status_style.COMPETITION_STATUS_COLOR_ATTR[status])

    def _match_status_color(self, status):
        return {
            M_PENDING: self.tokens.text_faint, M_READY: self.tokens.warning, M_RUNNING: self.tokens.accent_glow,
            M_COMPLETED: self.tokens.success, M_CANCELLED: self.tokens.text_faint, M_ERROR: self.tokens.danger,
        }[status]

    # ------------------------------------------------------------ refresh
    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        if self.mode == "create":
            self._build_create_form()
        elif self.mode == "detail" and self.selected_id:
            comp = self.service.get_competition(self.selected_id)
            if comp is None:
                self.mode = "list"
                self.refresh()
                return
            self._build_detail(comp)
        else:
            self._build_list()

    # -------------------------------------------------------------- list
    def _build_list(self):
        competitions = self.service.get_all_competitions()
        if not competitions:
            empty = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
            empty.pack(fill="x", pady=20, padx=4)
            ctk.CTkLabel(empty, text=t("no_competitions_title"), font=theme.font(13, "bold"), text_color=self.tokens.text).pack(pady=(20, 4))
            ctk.CTkLabel(empty, text=t("no_competitions_body"), font=theme.font(11), text_color=self.tokens.text_faint).pack(pady=(0, 14))
            ctk.CTkButton(empty, text=t("create_competition"), fg_color=self.tokens.accent, command=self._show_create_form).pack(pady=(0, 20))
            return

        for comp in competitions:
            self._build_card(comp)

    def _build_card(self, comp):
        card = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        card.pack(fill="x", pady=5, padx=2)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text=comp.name, font=theme.font(13, "bold"), text_color=self.tokens.text, anchor="w").pack(fill="x")
        challenge = self.challenge_service.get_challenge(comp.challenge_id) if comp.challenge_id else None
        rounds = self.service.get_competition_rounds(comp.id)
        sub = (
            f"{t('challenge_label')}: {challenge.name if challenge else '-'}  ·  "
            f"{len(comp.team_ids)} {t('participants')}  ·  {len(rounds)} {t('rounds')}  ·  "
            f"{comp.created_at[:10]}"
        )
        ctk.CTkLabel(left, text=sub, font=theme.font(10), text_color=self.tokens.text_faint, anchor="w").pack(fill="x")

        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right")
        ctk.CTkLabel(
            right, text=t(COMP_STATUS_KEY[comp.status]), font=theme.font(9, "bold"),
            fg_color=self._status_color(comp.status), text_color="#0B1017",
            corner_radius=999, width=90, height=20,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            right, text=t("details"), width=76, fg_color=self.tokens.panel_2,
            hover_color=self.tokens.border, command=lambda cid=comp.id: self._show_detail(cid),
        ).pack(side="right")

    # ------------------------------------------------------------ create
    def _show_create_form(self):
        self._clear_error()
        self.mode = "create"
        self.refresh()

    def _build_create_form(self):
        form = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        form.pack(fill="x", pady=6, padx=2)
        pad = dict(padx=14, pady=(10, 2))
        ctk.CTkLabel(form, text=t("create_competition"), font=theme.font(13, "bold"), text_color=self.tokens.text).pack(anchor="w", **pad)

        ctk.CTkLabel(form, text=t("competition_id"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=14)
        self.id_entry = ctk.CTkEntry(form, fg_color=self.tokens.panel_2)
        self.id_entry.pack(fill="x", padx=14, pady=(2, 8))

        ctk.CTkLabel(form, text=t("competition_name"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=14)
        self.name_entry = ctk.CTkEntry(form, fg_color=self.tokens.panel_2)
        self.name_entry.pack(fill="x", padx=14, pady=(2, 8))

        ctk.CTkLabel(form, text=t("description"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=14)
        self.description_entry = ctk.CTkEntry(form, fg_color=self.tokens.panel_2)
        self.description_entry.pack(fill="x", padx=14, pady=(2, 8))

        ctk.CTkLabel(form, text=t("challenge_label"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=14)
        challenges = self.challenge_service.get_all_challenges()
        self._challenge_name_to_id = {c.name: c.id for c in challenges}
        values = list(self._challenge_name_to_id) or ["-"]
        self.challenge_menu = ctk.CTkOptionMenu(form, values=values, fg_color=self.tokens.panel_2, button_color=self.tokens.accent)
        self.challenge_menu.set(values[0])
        self.challenge_menu.pack(fill="x", padx=14, pady=(2, 10))

        btn_row = ctk.CTkFrame(form, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(btn_row, text=t("create_competition"), fg_color=self.tokens.accent, command=self._submit_create).pack(side="left")
        ctk.CTkButton(
            btn_row, text=t("cancel"), fg_color="transparent", border_width=1,
            border_color=self.tokens.border, text_color=self.tokens.text_dim, command=self._back_to_list,
        ).pack(side="left", padx=8)

    def _submit_create(self):
        self._clear_error()
        challenge_id = self._challenge_name_to_id.get(self.challenge_menu.get())
        try:
            comp = self.service.create_competition(
                self.id_entry.get().strip(), self.name_entry.get(),
                description=self.description_entry.get(), challenge_id=challenge_id,
            )
        except ValidationError as e:
            self._show_error(str(e))
            return
        self._show_detail(comp.id)
        self.on_changed()

    def _back_to_list(self):
        self._clear_error()
        self.mode = "list"
        self.selected_id = None
        self.refresh()

    # ------------------------------------------------------------ detail
    def _show_detail(self, competition_id: str):
        self._clear_error()
        self.selected_id = competition_id
        self.mode = "detail"
        self.refresh()

    def _build_detail(self, comp):
        back = ctk.CTkButton(
            self.body, text=("→ " if is_rtl() else "← ") + t("back"), fg_color="transparent",
            text_color=self.tokens.text_dim, hover_color=self.tokens.panel_2,
            command=self._back_to_list, anchor="w", width=80,
        )
        back.pack(anchor="w", pady=(0, 8))

        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.pack(fill="x", pady=4, padx=2)
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(head, text=comp.name, font=theme.font(15, "bold"), text_color=self.tokens.text).pack(side="left")
        ctk.CTkLabel(
            head, text=t(COMP_STATUS_KEY[comp.status]), font=theme.font(9, "bold"),
            fg_color=self._status_color(comp.status), text_color="#0B1017",
            corner_radius=999, width=90, height=20,
        ).pack(side="right")

        if comp.description:
            ctk.CTkLabel(panel, text=comp.description, font=theme.font(11), text_color=self.tokens.text_dim, anchor="w", wraplength=440, justify="left").pack(fill="x", padx=16, pady=(4, 8))

        challenge = self.challenge_service.get_challenge(comp.challenge_id) if comp.challenge_id else None
        ctk.CTkLabel(panel, text=f"{t('challenge_label')}: {challenge.name if challenge else '-'}", font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=16, pady=(0, 10))

        # ---- lifecycle actions ----
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 14))
        if comp.status == STATUS_DRAFT:
            ctk.CTkButton(actions, text=t("mark_ready"), fg_color=self.tokens.accent, command=lambda: self._lifecycle_action(comp.id, self.service.mark_ready)).pack(side="left", padx=(0, 6))
        if comp.status == STATUS_READY:
            ctk.CTkButton(actions, text=t("start_competition"), fg_color=self.tokens.accent, command=lambda: self._lifecycle_action(comp.id, self.service.start_competition)).pack(side="left", padx=(0, 6))
        if comp.status == STATUS_ACTIVE:
            ctk.CTkButton(actions, text=t("pause_competition"), fg_color=self.tokens.panel_2, hover_color=self.tokens.border, command=lambda: self._lifecycle_action(comp.id, self.service.pause_competition)).pack(side="left", padx=(0, 6))
            ctk.CTkButton(actions, text=t("complete_competition"), fg_color=self.tokens.panel_2, hover_color=self.tokens.border, command=lambda: self._lifecycle_action(comp.id, self.service.complete_competition)).pack(side="left", padx=(0, 6))
        if comp.status == STATUS_PAUSED:
            ctk.CTkButton(actions, text=t("resume_competition"), fg_color=self.tokens.accent, command=lambda: self._lifecycle_action(comp.id, self.service.resume_competition)).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions, text=t("delete_competition"), fg_color="transparent", border_width=1,
            border_color=self.tokens.danger, text_color=self.tokens.danger,
            command=lambda: self._confirm_delete(comp.id),
        ).pack(side="left", padx=(0, 6))

        self._build_participants(comp)
        self._build_rounds(comp)

    def _lifecycle_action(self, competition_id, fn):
        self._clear_error()
        try:
            fn(competition_id)
        except ValidationError as e:
            self._show_error(str(e))
            return
        self.refresh()
        self.on_changed()

    def _confirm_delete(self, competition_id):
        if not messagebox.askyesno(t("confirm_delete_competition_title"), t("confirm_delete_body")):
            return
        try:
            self.service.delete_competition(competition_id)
        except ValidationError as e:
            key = ERROR_KEY.get(str(e), None)
            messagebox.showwarning(t("delete_competition"), t(key) if key else str(e))
            return
        self._back_to_list()
        self.on_changed()

    # -------------------------------------------------------- participants
    def _build_participants(self, comp):
        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.pack(fill="x", pady=4, padx=2)
        ctk.CTkLabel(panel, text=t("participants"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=16, pady=(12, 6))

        for team_id in comp.team_ids:
            team = self.team_service.get_team(team_id)
            row = ctk.CTkFrame(panel, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=2)
            name = team.name if team else team_id
            eligible = comp.challenge_id and self.service.is_team_eligible(team_id, comp.challenge_id)
            color = self.tokens.success if eligible else self.tokens.danger
            ctk.CTkLabel(row, text=name, font=theme.font(11), text_color=color, anchor="w").pack(side="left", fill="x", expand=True)
            if comp.status == STATUS_DRAFT:
                ctk.CTkButton(
                    row, text=t("remove_team"), width=70, height=22, font=theme.font(9),
                    fg_color="transparent", border_width=1, border_color=self.tokens.border, text_color=self.tokens.text_faint,
                    command=lambda tid=team_id: self._remove_team(comp.id, tid),
                ).pack(side="right")

        if comp.status == STATUS_DRAFT:
            add_row = ctk.CTkFrame(panel, fg_color="transparent")
            add_row.pack(fill="x", padx=16, pady=(6, 14))
            all_teams = self.team_service.get_all_teams()
            available = [team for team in all_teams if team.id not in comp.team_ids]
            self._addable_team_name_to_id = {team.name: team.id for team in available}
            values = list(self._addable_team_name_to_id) or ["-"]
            self.add_team_menu = ctk.CTkOptionMenu(add_row, values=values, fg_color=self.tokens.panel_2, button_color=self.tokens.accent)
            self.add_team_menu.set(values[0])
            self.add_team_menu.pack(side="left", padx=(0, 8))
            ctk.CTkButton(add_row, text=t("add_team"), fg_color=self.tokens.panel_2, hover_color=self.tokens.border, command=lambda: self._add_team(comp.id)).pack(side="left")

    def _add_team(self, competition_id):
        self._clear_error()
        team_id = self._addable_team_name_to_id.get(self.add_team_menu.get())
        if not team_id:
            return
        try:
            self.service.add_team(competition_id, team_id)
        except ValidationError as e:
            self._show_error(str(e))
            return
        self.refresh()
        self.on_changed()

    def _remove_team(self, competition_id, team_id):
        self._clear_error()
        try:
            self.service.remove_team(competition_id, team_id)
        except ValidationError as e:
            self._show_error(str(e))
            return
        self.refresh()
        self.on_changed()

    # -------------------------------------------------------------- rounds
    def _build_rounds(self, comp):
        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.pack(fill="x", pady=4, padx=2)
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(head, text=t("rounds"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(side="left")

        rounds = self.service.get_competition_rounds(comp.id)
        for round_obj in rounds:
            self._build_round_block(panel, comp, round_obj)

        if comp.status not in (STATUS_COMPLETED, STATUS_ARCHIVED):
            self._build_round_creation_form(panel, comp)

    def _build_round_creation_form(self, panel, comp):
        row = ctk.CTkFrame(panel, fg_color=self.tokens.panel_2, corner_radius=8)
        row.pack(fill="x", padx=16, pady=(4, 14))
        self.round_name_entry = ctk.CTkEntry(row, fg_color=self.tokens.panel, placeholder_text=t("round"))
        self.round_name_entry.pack(side="left", padx=(10, 6), pady=8)
        type_values = [t(ROUND_TYPE_KEY[TYPE_ROUND_ROBIN]), t(ROUND_TYPE_KEY[TYPE_SINGLE_ELIMINATION]), t(ROUND_TYPE_KEY[TYPE_CUSTOM])]
        self._round_type_by_label = {
            t(ROUND_TYPE_KEY[TYPE_ROUND_ROBIN]): TYPE_ROUND_ROBIN,
            t(ROUND_TYPE_KEY[TYPE_SINGLE_ELIMINATION]): TYPE_SINGLE_ELIMINATION,
            t(ROUND_TYPE_KEY[TYPE_CUSTOM]): TYPE_CUSTOM,
        }
        self.round_type_menu = ctk.CTkOptionMenu(row, values=type_values, fg_color=self.tokens.panel, button_color=self.tokens.accent)
        self.round_type_menu.set(type_values[0])
        self.round_type_menu.pack(side="left", padx=6, pady=8)
        ctk.CTkButton(row, text=t("create_round"), fg_color=self.tokens.accent, command=lambda: self._create_round(comp.id)).pack(side="left", padx=6, pady=8)

    def _create_round(self, competition_id):
        self._clear_error()
        round_type = self._round_type_by_label.get(self.round_type_menu.get(), TYPE_CUSTOM)
        name = self.round_name_entry.get().strip()
        try:
            self.service.create_round(competition_id, name, round_type)
        except ValidationError as e:
            self._show_error(str(e))
            return
        self.refresh()
        self.on_changed()

    def _build_round_block(self, panel, comp, round_obj):
        block = ctk.CTkFrame(panel, fg_color=self.tokens.panel_2, corner_radius=8)
        block.pack(fill="x", padx=16, pady=4)
        head = ctk.CTkFrame(block, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(head, text=f"{round_obj.name}  ·  {t(ROUND_TYPE_KEY[round_obj.round_type])}", font=theme.font(11, "bold"), text_color=self.tokens.text).pack(side="left")
        ctk.CTkLabel(head, text=t(MATCH_STATUS_KEY.get(round_obj.status, "pending")) if round_obj.status in MATCH_STATUS_KEY else round_obj.status, font=theme.font(9), text_color=self.tokens.text_faint).pack(side="right")

        matches = self.service.get_round_matches(round_obj.id)
        if not matches:
            gen_row = ctk.CTkFrame(block, fg_color="transparent")
            gen_row.pack(fill="x", padx=12, pady=(0, 10))
            if round_obj.round_type == TYPE_ROUND_ROBIN:
                ctk.CTkButton(gen_row, text=t("generate_matches"), fg_color=self.tokens.accent, command=lambda: self._generate(round_obj.id, self.service.generate_round_robin)).pack(side="left")
            elif round_obj.round_type == TYPE_SINGLE_ELIMINATION:
                ctk.CTkButton(gen_row, text=t("generate_matches"), fg_color=self.tokens.accent, command=lambda: self._generate(round_obj.id, self.service.generate_single_elimination)).pack(side="left")
            else:
                self._build_custom_match_form(gen_row, comp, round_obj)
        else:
            for match in matches:
                self._build_match_card(block, comp, match)

    def _generate(self, round_id, generator_fn):
        self._clear_error()
        try:
            generator_fn(round_id)
        except ValidationError as e:
            self._show_error(str(e))
            return
        self.refresh()
        self.on_changed()

    def _build_custom_match_form(self, parent, comp, round_obj):
        names = {self.team_service.get_team(tid).name: tid for tid in comp.team_ids if self.team_service.get_team(tid)}
        values = list(names) or ["-"]
        a_menu = ctk.CTkOptionMenu(parent, values=values, fg_color=self.tokens.panel, button_color=self.tokens.accent, width=140)
        a_menu.set(values[0])
        a_menu.pack(side="left", padx=(0, 4))
        ctk.CTkLabel(parent, text=t("vs"), font=theme.font(10), text_color=self.tokens.text_faint).pack(side="left", padx=4)
        b_menu = ctk.CTkOptionMenu(parent, values=values, fg_color=self.tokens.panel, button_color=self.tokens.accent, width=140)
        b_menu.set(values[-1] if len(values) > 1 else values[0])
        b_menu.pack(side="left", padx=4)

        def _create():
            self._clear_error()
            try:
                self.service.create_custom_match(round_obj.id, names.get(a_menu.get()), names.get(b_menu.get()))
            except ValidationError as e:
                self._show_error(str(e))
                return
            self.refresh()
            self.on_changed()

        ctk.CTkButton(parent, text=t("create_round"), fg_color=self.tokens.accent, command=_create).pack(side="left", padx=8)

    def _build_match_card(self, parent, comp, match):
        card = ctk.CTkFrame(parent, fg_color=self.tokens.panel, corner_radius=8)
        card.pack(fill="x", padx=12, pady=3)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=8)

        team_a = self.team_service.get_team(match.team_a_id)
        team_b = self.team_service.get_team(match.team_b_id) if match.team_b_id else None
        sub_a = self.submission_service.get_submission(match.submission_a_id)
        sub_b = self.submission_service.get_submission(match.submission_b_id) if match.submission_b_id else None

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        a_name = team_a.name if team_a else match.team_a_id
        a_ver = f" · v{sub_a.version}" if sub_a else ""
        if match.is_bye:
            label = f"#{match.match_number}  {a_name}{a_ver}  —  {t('bye')}"
        else:
            b_name = team_b.name if team_b else match.team_b_id
            b_ver = f" · v{sub_b.version}" if sub_b else ""
            label = f"#{match.match_number}  {a_name}{a_ver}   {t('vs')}   {b_name}{b_ver}"
        ctk.CTkLabel(left, text=label, font=theme.font(10, mono=True), text_color=self.tokens.text_dim, anchor="w").pack(fill="x")

        if match.status == M_COMPLETED and not match.is_bye:
            if match.outcome == OUTCOME_DRAW:
                result = t("draw")
            else:
                winner = self.team_service.get_team(match.winner_team_id)
                result = f"{t('winner')}: {winner.name if winner else match.winner_team_id}"
            duration = f"  ·  {match.battle_duration:.1f}s" if match.battle_duration else ""
            ctk.CTkLabel(left, text=result + duration, font=theme.font(9), text_color=self.tokens.text_faint).pack(anchor="w")

        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right")
        ctk.CTkLabel(
            right, text=t(MATCH_STATUS_KEY[match.status]), font=theme.font(9, "bold"),
            fg_color=self._match_status_color(match.status), text_color="#0B1017",
            corner_radius=999, width=80, height=20,
        ).pack(side="right", padx=(8, 0))

        if not match.is_bye and match.status == M_READY:
            can_start, _reason = self.service.can_start_match(match.id)
            ctk.CTkButton(
                right, text=t("start_match"), width=90, height=22, font=theme.font(9),
                fg_color=self.tokens.accent if can_start else self.tokens.panel_2,
                state="normal" if can_start else "disabled",
                command=lambda mid=match.id: self.on_start_match(mid),
            ).pack(side="right")

        # Phase 7: TournamentService.cancel_match() only ever accepted
        # PENDING/READY matches (a match that's already RUNNING or
        # COMPLETED was never cancellable — that guard is unchanged) but
        # had no UI path at all before this. A cancelled match is a
        # distinct, non-fake outcome — never a WIN/DRAW/ERROR — and
        # never produces a MatchResult (spec section 14; no battle ever
        # happened, exactly like a never-started match has no history).
        if not match.is_bye and match.status in (M_PENDING, M_READY):
            ctk.CTkButton(
                right, text=t("cancel_match"), width=90, height=22, font=theme.font(9),
                fg_color="transparent", border_width=1, border_color=self.tokens.danger,
                text_color=self.tokens.danger,
                command=lambda mid=match.id: self._confirm_cancel_match(mid),
            ).pack(side="right", padx=(0, 6))

    def _confirm_cancel_match(self, match_id: str):
        if not messagebox.askyesno(t("cancel_match"), t("confirm_cancel_match")):
            return
        self._clear_error()
        try:
            self.service.cancel_match(match_id)
        except ValidationError as e:
            self._show_error(str(e))
            return
        self.refresh()
        self.on_changed()
