"""Teams & Members management view — makes the sidebar's "Teams" /
"الفرق" nav item functional (previously it just showed the same combined
dashboard as every other implemented tab).

Reuses the existing visual system (theme.Tokens, theme.font, the same
panel/panel_2/accent colors and corner radii every other panel uses) —
no new color system, no new fonts. Talks only to TeamService (never
roster/team_repository.py or data/teams.json directly) and to a small
stats/status lookup the app injects, which itself only reads from the
existing CompetitionTracker + BattleRunner snapshot — no second scoring
system, no UI-side battle state.
"""

import tkinter.messagebox as messagebox

import customtkinter as ctk

from . import theme
from .localization import t, is_rtl
from roster.team import ValidationError, SHIP_SLOTS, STATUS_READY, STATUS_IN_BATTLE, STATUS_DISABLED, STATUS_NOT_READY

STATUS_LABEL_KEY = {
    STATUS_READY: "ready",
    STATUS_IN_BATTLE: "in_battle",
    STATUS_DISABLED: "disabled_status",
    STATUS_NOT_READY: "not_ready",
}

ERROR_KEY = {
    "empty_name": "error_empty_name",
    "empty_id": "error_empty_id",
    "invalid_id": "error_invalid_id",
    "duplicate_id": "error_duplicate_id",
    "ship_already_assigned": "error_ship_taken",
    "invalid_ship": "error_ship_taken",
    "empty_member_name": "error_empty_name",
}


class TeamsView(ctk.CTkFrame):
    def __init__(self, master, tokens: theme.Tokens, team_service, get_stats, on_changed=None):
        super().__init__(master, fg_color="transparent")
        self.tokens = tokens
        self.service = team_service
        self.get_stats = get_stats          # (team_name: str) -> TeamRecord-like
        self.on_changed = on_changed or (lambda: None)
        self.mode = "list"                  # "list" | "create" | "detail"
        self.selected_id = None
        self._build_shell()
        self.refresh()

    # ------------------------------------------------------------- shell
    def _build_shell(self):
        anchor = "e" if is_rtl() else "w"

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", pady=(0, 8))
        self.title_lbl = ctk.CTkLabel(head, text=t("teams_title"), font=theme.font(16, "bold"), text_color=self.tokens.text)
        self.title_lbl.pack(side="left")
        self.create_btn = ctk.CTkButton(
            head, text="+  " + t("create_team"), fg_color=self.tokens.accent,
            command=self._show_create_form,
        )
        self.create_btn.pack(side="right")

        self.error_lbl = ctk.CTkLabel(self, text="", font=theme.font(11), text_color=self.tokens.danger, anchor=anchor)
        self.error_lbl.pack(fill="x", pady=(0, 4))

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

    def apply_language(self):
        self.title_lbl.configure(text=t("teams_title"))
        self.create_btn.configure(text="+  " + t("create_team"))
        self.refresh()

    def _clear_error(self):
        self.error_lbl.configure(text="")

    def _show_error(self, code: str):
        key = ERROR_KEY.get(code, "error_generic")
        self.error_lbl.configure(text=t(key))

    # ------------------------------------------------------------ refresh
    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()

        if self.mode == "create":
            self._build_create_form()
        elif self.mode == "detail" and self.selected_id:
            team = self.service.get_team(self.selected_id)
            if team is None:
                self.mode = "list"
                self.refresh()
                return
            self._build_detail(team)
        else:
            self._build_list()

    # -------------------------------------------------------------- list
    def _build_list(self):
        teams = self.service.get_all_teams()
        if not teams:
            empty = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
            empty.pack(fill="x", pady=20, padx=4)
            ctk.CTkLabel(empty, text=t("no_teams_title"), font=theme.font(13, "bold"), text_color=self.tokens.text).pack(pady=(20, 4))
            ctk.CTkLabel(empty, text=t("no_teams_body"), font=theme.font(11), text_color=self.tokens.text_faint).pack(pady=(0, 14))
            ctk.CTkButton(empty, text=t("create_team"), fg_color=self.tokens.accent, command=self._show_create_form).pack(pady=(0, 20))
            return

        for team in teams:
            status = self.service.compute_status(team)
            stats = self.get_stats(team.name)
            self._build_team_card(team, status, stats)

    def _build_team_card(self, team, status, stats):
        card = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        card.pack(fill="x", pady=5, padx=2)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text=team.name, font=theme.font(13, "bold"), text_color=self.tokens.text, anchor="w").pack(fill="x")
        sub = f"{team.id}  ·  {len(team.members)} {t('member_count')}  ·  {t('ship') }: {team.ship_id.upper() if team.ship_id else t('unassigned')}"
        ctk.CTkLabel(left, text=sub, font=theme.font(10), text_color=self.tokens.text_faint, anchor="w").pack(fill="x")

        mid = ctk.CTkFrame(row, fg_color="transparent")
        mid.pack(side="left", padx=20)
        for label_key, value in ((t("score"), stats.score), (t("wins"), stats.wins), (t("losses"), stats.losses)):
            col = ctk.CTkFrame(mid, fg_color="transparent")
            col.pack(side="left", padx=8)
            ctk.CTkLabel(col, text=str(value), font=theme.font(13, "bold"), text_color=self.tokens.text).pack()
            ctk.CTkLabel(col, text=label_key, font=theme.font(9), text_color=self.tokens.text_faint).pack()

        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right")
        color = {
            STATUS_READY: self.tokens.success, STATUS_IN_BATTLE: self.tokens.accent_glow,
            STATUS_DISABLED: self.tokens.text_faint, STATUS_NOT_READY: self.tokens.warning,
        }[status]
        ctk.CTkLabel(
            right, text=t(STATUS_LABEL_KEY[status]), font=theme.font(9, "bold"), fg_color=color,
            text_color="#0B1017", corner_radius=999, width=90, height=20,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            right, text=t("details"), width=76, fg_color=self.tokens.panel_2,
            hover_color=self.tokens.border, command=lambda tid=team.id: self._show_detail(tid),
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

        ctk.CTkLabel(form, text=t("create_team"), font=theme.font(13, "bold"), text_color=self.tokens.text).pack(anchor="w", **pad)

        ctk.CTkLabel(form, text=t("team_name"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=14)
        self.name_entry = ctk.CTkEntry(form, fg_color=self.tokens.panel_2)
        self.name_entry.pack(fill="x", padx=14, pady=(2, 8))

        ctk.CTkLabel(form, text=t("team_id"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=14)
        self.id_entry = ctk.CTkEntry(form, fg_color=self.tokens.panel_2, placeholder_text="auto")
        self.id_entry.pack(fill="x", padx=14, pady=(2, 8))

        ctk.CTkLabel(form, text=t("ship"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=14)
        ship_values = [t("unassigned")] + [s.upper() for s in SHIP_SLOTS]
        self.ship_menu = ctk.CTkOptionMenu(form, values=ship_values, fg_color=self.tokens.panel_2, button_color=self.tokens.accent)
        self.ship_menu.set(ship_values[0])
        self.ship_menu.pack(fill="x", padx=14, pady=(2, 10))

        btn_row = ctk.CTkFrame(form, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(btn_row, text=t("create_team"), fg_color=self.tokens.accent, command=self._submit_create).pack(side="left")
        ctk.CTkButton(
            btn_row, text=t("cancel"), fg_color="transparent", border_width=1,
            border_color=self.tokens.border, text_color=self.tokens.text_dim, command=self._cancel_create,
        ).pack(side="left", padx=8)

    def _cancel_create(self):
        self._clear_error()
        self.mode = "list"
        self.refresh()

    def _submit_create(self):
        self._clear_error()
        name = self.name_entry.get()
        team_id = self.id_entry.get().strip() or None
        ship_choice = self.ship_menu.get()
        ship_id = None if ship_choice == t("unassigned") else ship_choice.lower()
        try:
            self.service.create_team(name, team_id=team_id, ship_id=ship_id)
        except ValidationError as e:
            self._show_error(str(e))
            return
        self.mode = "list"
        self.refresh()
        self.on_changed()

    # ------------------------------------------------------------ detail
    def _show_detail(self, team_id: str):
        self._clear_error()
        self.selected_id = team_id
        self.mode = "detail"
        self.refresh()

    def _build_detail(self, team):
        status = self.service.compute_status(team)
        stats = self.get_stats(team.name)

        back = ctk.CTkButton(
            self.body, text=("→ " if is_rtl() else "← ") + t("back"), fg_color="transparent",
            text_color=self.tokens.text_dim, hover_color=self.tokens.panel_2,
            command=self._back_to_list, anchor="w", width=80,
        )
        back.pack(anchor="w", pady=(0, 8))

        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.pack(fill="x", pady=4, padx=2)

        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(head, text=team.name, font=theme.font(15, "bold"), text_color=self.tokens.text).pack(side="left")
        color = {
            STATUS_READY: self.tokens.success, STATUS_IN_BATTLE: self.tokens.accent_glow,
            STATUS_DISABLED: self.tokens.text_faint, STATUS_NOT_READY: self.tokens.warning,
        }[status]
        ctk.CTkLabel(
            head, text=t(STATUS_LABEL_KEY[status]), font=theme.font(9, "bold"), fg_color=color,
            text_color="#0B1017", corner_radius=999, width=90, height=20,
        ).pack(side="right")

        # ---- editable fields ----
        ctk.CTkLabel(panel, text=t("team_name"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=16)
        self.detail_name_entry = ctk.CTkEntry(panel, fg_color=self.tokens.panel_2)
        self.detail_name_entry.insert(0, team.name)
        self.detail_name_entry.pack(fill="x", padx=16, pady=(2, 8))

        ctk.CTkLabel(panel, text=t("ship"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=16)
        ship_values = [t("unassigned")] + [s.upper() for s in SHIP_SLOTS]
        self.detail_ship_menu = ctk.CTkOptionMenu(panel, values=ship_values, fg_color=self.tokens.panel_2, button_color=self.tokens.accent)
        self.detail_ship_menu.set(team.ship_id.upper() if team.ship_id else t("unassigned"))
        self.detail_ship_menu.pack(fill="x", padx=16, pady=(2, 10))

        btn_row = ctk.CTkFrame(panel, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(btn_row, text=t("save"), fg_color=self.tokens.accent, command=lambda: self._save_detail(team.id)).pack(side="left")
        ctk.CTkButton(
            btn_row, text=t("delete_team"), fg_color="transparent", border_width=1,
            border_color=self.tokens.danger, text_color=self.tokens.danger,
            command=lambda: self._confirm_delete(team.id),
        ).pack(side="left", padx=8)

        # ---- stats (read-only, from CompetitionTracker) ----
        stats_frame = ctk.CTkFrame(panel, fg_color=self.tokens.panel_2, corner_radius=8)
        stats_frame.pack(fill="x", padx=16, pady=(0, 14))
        for label_key, value in (
            (t("score"), stats.score), (t("wins"), stats.wins), (t("losses"), stats.losses),
            (t("damage"), f"{stats.damage_dealt:.0f}"), (t("damage_received"), f"{stats.damage_received:.0f}"),
        ):
            col = ctk.CTkFrame(stats_frame, fg_color="transparent")
            col.pack(side="left", expand=True, fill="x", pady=10)
            ctk.CTkLabel(col, text=str(value), font=theme.font(14, "bold"), text_color=self.tokens.text).pack()
            ctk.CTkLabel(col, text=label_key, font=theme.font(9), text_color=self.tokens.text_faint).pack()

        # ---- members ----
        members_panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        members_panel.pack(fill="x", pady=4, padx=2)
        ctk.CTkLabel(
            members_panel, text=f"{t('members')} ({len(team.members)})",
            font=theme.font(12, "bold"), text_color=self.tokens.text,
        ).pack(anchor="w", padx=16, pady=(12, 6))

        for member in team.members:
            mrow = ctk.CTkFrame(members_panel, fg_color="transparent")
            mrow.pack(fill="x", padx=16, pady=2)
            ctk.CTkLabel(mrow, text=member.name, font=theme.font(11), text_color=self.tokens.text_dim, anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                mrow, text=t("remove_member"), width=70, height=22, font=theme.font(9),
                fg_color="transparent", border_width=1, border_color=self.tokens.border,
                text_color=self.tokens.text_faint,
                command=lambda tid=team.id, mid=member.member_id: self._remove_member(tid, mid),
            ).pack(side="right")

        add_row = ctk.CTkFrame(members_panel, fg_color="transparent")
        add_row.pack(fill="x", padx=16, pady=(6, 14))
        self.member_entry = ctk.CTkEntry(add_row, fg_color=self.tokens.panel_2, placeholder_text=t("member_name"))
        self.member_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            add_row, text=t("add_member"), width=110, fg_color=self.tokens.panel_2,
            hover_color=self.tokens.border, command=lambda tid=team.id: self._add_member(tid),
        ).pack(side="left")

    def _back_to_list(self):
        self._clear_error()
        self.mode = "list"
        self.selected_id = None
        self.refresh()

    def _save_detail(self, team_id: str):
        self._clear_error()
        team_before = self.service.get_team(team_id)
        name = self.detail_name_entry.get()
        ship_choice = self.detail_ship_menu.get()
        ship_id = None if ship_choice == t("unassigned") else ship_choice.lower()

        # Phase 7: a ship reassignment never corrupts the live battle —
        # BattleEngine keeps ticking whatever ship identity it already
        # loaded until the next Reset (App._sync_engine_state() already
        # skips re-syncing while a battle is genuinely ongoing, unchanged
        # since Phase 1). This just makes that deferral visible instead
        # of silent, per spec section 13.
        ship_changing = team_before is not None and ship_id != team_before.ship_id
        was_in_battle = (
            ship_changing and team_before is not None
            and self.service.compute_status(team_before) == STATUS_IN_BATTLE
        )

        try:
            self.service.update_team(team_id, name=name, ship_id=ship_id)
        except ValidationError as e:
            self._show_error(str(e))
            return

        if was_in_battle:
            messagebox.showinfo(t("assign_ship"), t("ship_change_pending_reset"))

        self.refresh()
        self.on_changed()

    def _confirm_delete(self, team_id: str):
        if not messagebox.askyesno(t("confirm_delete_title"), t("confirm_delete_body")):
            return
        try:
            self.service.delete_team(team_id)
        except ValidationError:
            messagebox.showwarning(t("delete_team"), t("cannot_delete_active"))
            return
        self.mode = "list"
        self.selected_id = None
        self.refresh()
        self.on_changed()

    def _add_member(self, team_id: str):
        self._clear_error()
        name = self.member_entry.get()
        try:
            self.service.add_member(team_id, name)
        except ValidationError as e:
            self._show_error(str(e))
            return
        self.refresh()
        self.on_changed()

    def _remove_member(self, team_id: str, member_id: str):
        self.service.remove_member(team_id, member_id)
        self.refresh()
        self.on_changed()
