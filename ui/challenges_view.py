"""Challenges & Rules management view — makes the sidebar's "Challenges" /
"التحديات" nav item functional.

Reuses the same visual system as ui/teams_view.py (same tokens, fonts,
panel colors, corner radii). Talks only to ChallengeService — never
challenges/challenge_repository.py or data/challenges.json directly.
"""

import tkinter.messagebox as messagebox

import customtkinter as ctk

from . import theme
from .localization import t, is_rtl
from challenges.challenge import (
    ValidationError, DIFFICULTY_LEVELS, STATUS_DRAFT, STATUS_READY,
    STATUS_ACTIVE, STATUS_ARCHIVED, Rules,
)
from engine.config import ALL_API_FUNCTIONS, WIN_CONDITIONS, WIN_DESTROY_ENEMY, WIN_TIME_LIMIT_DRAW

STATUS_LABEL_KEY = {
    STATUS_DRAFT: "draft", STATUS_READY: "ready",
    STATUS_ACTIVE: "active", STATUS_ARCHIVED: "archived",
}
DIFFICULTY_LABEL_KEY = {"LEVEL_1": "level1", "LEVEL_2": "level2", "LEVEL_3": "level3"}
WIN_LABEL_KEY = {WIN_DESTROY_ENEMY: "win_destroy_enemy", WIN_TIME_LIMIT_DRAW: "win_time_limit_draw"}

ERROR_KEY = {
    "empty_id": "error_empty_challenge_id",
    "invalid_id": "error_invalid_challenge_id",
    "duplicate_id": "error_duplicate_challenge_id",
    "empty_name": "error_empty_challenge_name",
    "empty_description": "error_empty_description",
    "invalid_difficulty": "error_invalid_difficulty",
    "invalid_win_condition": "error_invalid_win_condition",
    "cannot_edit_active_rules": "cannot_edit_active_rules",
    "cannot_delete_active": "cannot_delete_active_challenge",
}

RULE_FIELDS = [
    ("movement_speed", "rule_movement_speed", "number"),
    ("attack_enabled", "rule_attack_enabled", "toggle"),
    ("attack_range", "rule_attack_range", "number"),
    ("attack_damage", "rule_attack_damage", "number"),
    ("attack_cooldown", "rule_attack_cooldown", "number"),
    ("energy_pool", "rule_energy_pool", "number"),
    ("sensor_range", "rule_sensor_range", "number"),
    ("battle_duration", "rule_battle_duration", "number_optional"),
    ("movement_energy_cost", "rule_movement_energy_cost", "number"),
]


class ChallengesView(ctk.CTkFrame):
    def __init__(self, master, tokens: theme.Tokens, service, on_changed=None):
        super().__init__(master, fg_color="transparent")
        self.tokens = tokens
        self.service = service
        self.on_changed = on_changed or (lambda: None)
        self.mode = "list"
        self.selected_id = None
        self._build_shell()
        self.refresh()

    # ------------------------------------------------------------- shell
    def _build_shell(self):
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", pady=(0, 8))
        self.title_lbl = ctk.CTkLabel(head, text=t("challenges_title"), font=theme.font(16, "bold"), text_color=self.tokens.text)
        self.title_lbl.pack(side="left")
        self.create_btn = ctk.CTkButton(
            head, text="+  " + t("create_challenge"), fg_color=self.tokens.accent,
            command=self._show_create_form,
        )
        self.create_btn.pack(side="right")

        self.error_lbl = ctk.CTkLabel(self, text="", font=theme.font(11), text_color=self.tokens.danger)
        self.error_lbl.pack(fill="x", pady=(0, 4))

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

    def apply_language(self):
        self.title_lbl.configure(text=t("challenges_title"))
        self.create_btn.configure(text="+  " + t("create_challenge"))
        self.refresh()

    def _clear_error(self):
        self.error_lbl.configure(text="")

    def _show_error(self, code: str):
        if code in ERROR_KEY:
            self.error_lbl.configure(text=t(ERROR_KEY[code]))
        else:
            # Falls back to the raw engine validation message (e.g.
            # "attack_damage must be > 0") for BattleConfig.validate()
            # errors, which aren't individually localized.
            self.error_lbl.configure(text=f"{t('error_invalid_rule')} ({code})")

    # ------------------------------------------------------------ refresh
    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        if self.mode == "create":
            self._build_form(challenge=None)
        elif self.mode == "detail" and self.selected_id:
            challenge = self.service.get_challenge(self.selected_id)
            if challenge is None:
                self.mode = "list"
                self.refresh()
                return
            self._build_detail(challenge)
        else:
            self._build_list()

    # -------------------------------------------------------------- list
    def _build_list(self):
        challenges = self.service.get_all_challenges()
        if not challenges:
            empty = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
            empty.pack(fill="x", pady=20, padx=4)
            ctk.CTkLabel(empty, text=t("no_challenges_title"), font=theme.font(13, "bold"), text_color=self.tokens.text).pack(pady=(20, 4))
            ctk.CTkLabel(empty, text=t("no_challenges_body"), font=theme.font(11), text_color=self.tokens.text_faint).pack(pady=(0, 14))
            ctk.CTkButton(empty, text=t("create_challenge"), fg_color=self.tokens.accent, command=self._show_create_form).pack(pady=(0, 20))
            return

        for challenge in challenges:
            self._build_card(challenge)

    def _status_color(self, status):
        return {
            STATUS_DRAFT: self.tokens.text_faint, STATUS_READY: self.tokens.warning,
            STATUS_ACTIVE: self.tokens.success, STATUS_ARCHIVED: self.tokens.text_faint,
        }[status]

    def _build_card(self, challenge):
        card = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        card.pack(fill="x", pady=5, padx=2)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text=challenge.name, font=theme.font(13, "bold"), text_color=self.tokens.text, anchor="w").pack(fill="x")
        duration = f"{challenge.rules.battle_duration:.0f}{t('seconds_short')}" if challenge.rules.battle_duration else t("no_time_limit")
        sub = f"{t(DIFFICULTY_LABEL_KEY[challenge.difficulty])}  ·  {duration}  ·  {t(WIN_LABEL_KEY[challenge.win_condition])}"
        ctk.CTkLabel(left, text=sub, font=theme.font(10), text_color=self.tokens.text_faint, anchor="w").pack(fill="x")

        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right")
        ctk.CTkLabel(
            right, text=t(STATUS_LABEL_KEY[challenge.status]), font=theme.font(9, "bold"),
            fg_color=self._status_color(challenge.status), text_color="#0B1017",
            corner_radius=999, width=90, height=20,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            right, text=t("details"), width=76, fg_color=self.tokens.panel_2,
            hover_color=self.tokens.border, command=lambda cid=challenge.id: self._show_detail(cid),
        ).pack(side="right")

    # --------------------------------------------------------- form (shared)
    def _show_create_form(self):
        self._clear_error()
        self.mode = "create"
        self.selected_id = None
        self.refresh()

    def _build_form(self, challenge):
        editing = challenge is not None
        active_locked = editing and challenge.status == STATUS_ACTIVE

        form = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        form.pack(fill="x", pady=6, padx=2)
        pad = dict(padx=14, pady=(10, 2))

        title = t("edit_challenge") if editing else t("create_challenge")
        ctk.CTkLabel(form, text=title, font=theme.font(13, "bold"), text_color=self.tokens.text).pack(anchor="w", **pad)
        if active_locked:
            ctk.CTkLabel(
                form, text=t("cannot_edit_active_rules"), font=theme.font(9),
                text_color=self.tokens.warning, wraplength=420, justify="left",
            ).pack(anchor="w", padx=14, pady=(0, 4))

        if not editing:
            ctk.CTkLabel(form, text=t("challenge_id"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=14)
            self.id_entry = ctk.CTkEntry(form, fg_color=self.tokens.panel_2)
            self.id_entry.pack(fill="x", padx=14, pady=(2, 8))

        ctk.CTkLabel(form, text=t("challenge_name"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=14)
        self.name_entry = ctk.CTkEntry(form, fg_color=self.tokens.panel_2)
        if editing:
            self.name_entry.insert(0, challenge.name)
        self.name_entry.pack(fill="x", padx=14, pady=(2, 8))

        ctk.CTkLabel(form, text=t("description"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=14)
        self.description_entry = ctk.CTkEntry(form, fg_color=self.tokens.panel_2)
        if editing:
            self.description_entry.insert(0, challenge.description)
        self.description_entry.pack(fill="x", padx=14, pady=(2, 8))

        ctk.CTkLabel(form, text=t("objective"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w", padx=14)
        self.objective_entry = ctk.CTkEntry(form, fg_color=self.tokens.panel_2)
        if editing:
            self.objective_entry.insert(0, challenge.objective)
        self.objective_entry.pack(fill="x", padx=14, pady=(2, 8))

        diff_row = ctk.CTkFrame(form, fg_color="transparent")
        diff_row.pack(fill="x", padx=14, pady=(2, 8))
        ctk.CTkLabel(diff_row, text=t("difficulty"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w")
        diff_values = [t(DIFFICULTY_LABEL_KEY[lvl]) for lvl in DIFFICULTY_LEVELS]
        self.difficulty_menu = ctk.CTkOptionMenu(
            diff_row, values=diff_values, fg_color=self.tokens.panel_2, button_color=self.tokens.accent,
            state="disabled" if active_locked else "normal",
        )
        self.difficulty_menu.set(t(DIFFICULTY_LABEL_KEY[challenge.difficulty]) if editing else diff_values[1])
        self.difficulty_menu.pack(fill="x")

        win_row = ctk.CTkFrame(form, fg_color="transparent")
        win_row.pack(fill="x", padx=14, pady=(2, 8))
        ctk.CTkLabel(win_row, text=t("win_condition"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w")
        win_values = [t(WIN_LABEL_KEY[wc]) for wc in WIN_CONDITIONS]
        self.win_menu = ctk.CTkOptionMenu(
            win_row, values=win_values, fg_color=self.tokens.panel_2, button_color=self.tokens.accent,
            state="disabled" if active_locked else "normal",
        )
        self.win_menu.set(t(WIN_LABEL_KEY[challenge.win_condition]) if editing else win_values[0])
        self.win_menu.pack(fill="x")

        # ---- rules ----
        ctk.CTkLabel(form, text=t("rules"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=14, pady=(6, 4))
        rules = challenge.rules if editing else Rules()
        self.rule_widgets = {}
        for field_name, label_key, kind in RULE_FIELDS:
            row = ctk.CTkFrame(form, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=3)
            ctk.CTkLabel(row, text=t(label_key), font=theme.font(10), text_color=self.tokens.text_dim, width=160, anchor="w").pack(side="left")
            value = getattr(rules, field_name)
            if kind == "toggle":
                var = ctk.BooleanVar(value=bool(value))
                widget = ctk.CTkSwitch(row, text="", variable=var, state="disabled" if active_locked else "normal")
                widget.pack(side="left")
                self.rule_widgets[field_name] = ("toggle", var)
            else:
                entry = ctk.CTkEntry(row, fg_color=self.tokens.panel_2, width=120, state="disabled" if active_locked else "normal")
                entry.insert(0, "" if value is None else str(value))
                entry.pack(side="left")
                self.rule_widgets[field_name] = (kind, entry)

        # ---- allowed API ----
        ctk.CTkLabel(form, text=t("allowed_api"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=14, pady=(8, 4))
        allowed = set(challenge.allowed_api) if editing else set(ALL_API_FUNCTIONS)
        self.api_vars = {}
        api_row = ctk.CTkFrame(form, fg_color="transparent")
        api_row.pack(fill="x", padx=14, pady=(0, 8))
        for fn in ALL_API_FUNCTIONS:
            var = ctk.BooleanVar(value=fn in allowed)
            cb = ctk.CTkCheckBox(
                api_row, text=fn, variable=var, font=theme.font(10, mono=True),
                state="disabled" if active_locked else "normal",
            )
            cb.pack(side="left", padx=(0, 10), pady=2)
            self.api_vars[fn] = var

        btn_row = ctk.CTkFrame(form, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(8, 14))
        save_text = t("save") if editing else t("create_challenge")
        ctk.CTkButton(
            btn_row, text=save_text, fg_color=self.tokens.accent,
            command=(lambda: self._submit_edit(challenge.id)) if editing else self._submit_create,
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text=t("cancel"), fg_color="transparent", border_width=1,
            border_color=self.tokens.border, text_color=self.tokens.text_dim,
            command=(lambda: self._show_detail(challenge.id)) if editing else self._back_to_list,
        ).pack(side="left", padx=8)

    def _read_rules_from_form(self) -> Rules:
        kwargs = {}
        for field_name, _, kind in RULE_FIELDS:
            widget_kind, widget = self.rule_widgets[field_name]
            if widget_kind == "toggle":
                kwargs[field_name] = bool(widget.get())
            elif widget_kind == "number_optional":
                raw = widget.get().strip()
                kwargs[field_name] = float(raw) if raw else None
            else:
                raw = widget.get().strip()
                kwargs[field_name] = float(raw) if raw else 0.0
        return Rules(**kwargs)

    def _read_difficulty_from_form(self) -> str:
        label = self.difficulty_menu.get()
        for level, key in DIFFICULTY_LABEL_KEY.items():
            if t(key) == label:
                return level
        return "LEVEL_2"

    def _read_win_condition_from_form(self) -> str:
        label = self.win_menu.get()
        for wc, key in WIN_LABEL_KEY.items():
            if t(key) == label:
                return wc
        return WIN_DESTROY_ENEMY

    def _read_allowed_api_from_form(self) -> list:
        return [fn for fn, var in self.api_vars.items() if var.get()]

    def _submit_create(self):
        self._clear_error()
        try:
            rules = self._read_rules_from_form()
        except ValueError:
            self._show_error("invalid_rule_input")
            return
        try:
            self.service.create_challenge(
                self.id_entry.get().strip(), self.name_entry.get(),
                description=self.description_entry.get(), objective=self.objective_entry.get(),
                difficulty=self._read_difficulty_from_form(), rules=rules,
                win_condition=self._read_win_condition_from_form(),
                allowed_api=self._read_allowed_api_from_form(),
            )
        except ValidationError as e:
            self._show_error(str(e))
            return
        self.mode = "list"
        self.refresh()
        self.on_changed()

    def _submit_edit(self, challenge_id: str):
        self._clear_error()
        try:
            rules = self._read_rules_from_form()
        except ValueError:
            self._show_error("invalid_rule_input")
            return
        try:
            self.service.update_challenge(
                challenge_id,
                name=self.name_entry.get(), description=self.description_entry.get(),
                objective=self.objective_entry.get(), difficulty=self._read_difficulty_from_form(),
                rules=rules, win_condition=self._read_win_condition_from_form(),
                allowed_api=self._read_allowed_api_from_form(),
            )
        except ValidationError as e:
            self._show_error(str(e))
            return
        self._show_detail(challenge_id)
        self.on_changed()

    # ------------------------------------------------------------ detail
    def _show_detail(self, challenge_id: str):
        self._clear_error()
        self.selected_id = challenge_id
        self.mode = "detail"
        self.refresh()

    def _back_to_list(self):
        self._clear_error()
        self.mode = "list"
        self.selected_id = None
        self.refresh()

    def _build_detail(self, challenge):
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
        ctk.CTkLabel(head, text=challenge.name, font=theme.font(15, "bold"), text_color=self.tokens.text).pack(side="left")
        ctk.CTkLabel(
            head, text=t(STATUS_LABEL_KEY[challenge.status]), font=theme.font(9, "bold"),
            fg_color=self._status_color(challenge.status), text_color="#0B1017",
            corner_radius=999, width=90, height=20,
        ).pack(side="right")

        ctk.CTkLabel(
            panel, text=challenge.description, font=theme.font(11), text_color=self.tokens.text_dim,
            wraplength=440, justify="left", anchor="w",
        ).pack(fill="x", padx=16, pady=(4, 4))
        ctk.CTkLabel(
            panel, text=f"{t('objective')}: {challenge.objective}", font=theme.font(10),
            text_color=self.tokens.text_faint, wraplength=440, justify="left", anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 10))

        meta_row = ctk.CTkFrame(panel, fg_color=self.tokens.panel_2, corner_radius=8)
        meta_row.pack(fill="x", padx=16, pady=(0, 12))
        duration = f"{challenge.rules.battle_duration:.0f}{t('seconds_short')}" if challenge.rules.battle_duration else t("no_time_limit")
        for label_key, value in (
            (t("difficulty"), t(DIFFICULTY_LABEL_KEY[challenge.difficulty])),
            (t("time_limit"), duration),
            (t("win_condition"), t(WIN_LABEL_KEY[challenge.win_condition])),
        ):
            col = ctk.CTkFrame(meta_row, fg_color="transparent")
            col.pack(side="left", expand=True, fill="x", pady=10)
            ctk.CTkLabel(col, text=value, font=theme.font(12, "bold"), text_color=self.tokens.text).pack()
            ctk.CTkLabel(col, text=label_key, font=theme.font(9), text_color=self.tokens.text_faint).pack()

        # ---- rules readout ----
        ctk.CTkLabel(panel, text=t("rules"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=16, pady=(0, 4))
        rules_grid = ctk.CTkFrame(panel, fg_color="transparent")
        rules_grid.pack(fill="x", padx=16, pady=(0, 10))
        for field_name, label_key, _ in RULE_FIELDS:
            value = getattr(challenge.rules, field_name)
            row = ctk.CTkFrame(rules_grid, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=t(label_key), font=theme.font(10), text_color=self.tokens.text_faint, anchor="w", width=160).pack(side="left")
            ctk.CTkLabel(row, text=str(value) if value is not None else t("no_time_limit"), font=theme.font(10, "bold"), text_color=self.tokens.text).pack(side="left")

        ctk.CTkLabel(panel, text=t("allowed_api"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=16, pady=(4, 4))
        api_text = ", ".join(challenge.allowed_api)
        ctk.CTkLabel(panel, text=api_text, font=theme.font(10, mono=True), text_color=self.tokens.text_dim, wraplength=440, justify="left", anchor="w").pack(fill="x", padx=16, pady=(0, 12))

        btn_row = ctk.CTkFrame(panel, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(btn_row, text=t("edit_challenge"), fg_color=self.tokens.panel_2, hover_color=self.tokens.border, command=lambda: self._edit(challenge)).pack(side="left")
        if challenge.status != STATUS_ACTIVE:
            ctk.CTkButton(
                btn_row, text=t("activate"), fg_color=self.tokens.accent,
                command=lambda: self._activate(challenge.id),
            ).pack(side="left", padx=8)
        ctk.CTkButton(
            btn_row, text=t("delete_challenge"), fg_color="transparent", border_width=1,
            border_color=self.tokens.danger, text_color=self.tokens.danger,
            command=lambda: self._confirm_delete(challenge.id),
        ).pack(side="left", padx=8)

    def _edit(self, challenge):
        self._clear_error()
        for w in self.body.winfo_children():
            w.destroy()
        back = ctk.CTkButton(
            self.body, text=("→ " if is_rtl() else "← ") + t("back"), fg_color="transparent",
            text_color=self.tokens.text_dim, hover_color=self.tokens.panel_2,
            command=lambda: self._show_detail(challenge.id), anchor="w", width=80,
        )
        back.pack(anchor="w", pady=(0, 8))
        self._build_form(challenge)

    def _activate(self, challenge_id: str):
        self._clear_error()
        try:
            self.service.activate_challenge(challenge_id)
        except ValidationError as e:
            self._show_error(str(e))
            return
        self._show_detail(challenge_id)
        self.on_changed()

    def _confirm_delete(self, challenge_id: str):
        if not messagebox.askyesno(t("confirm_delete_challenge_title"), t("confirm_delete_body")):
            return
        try:
            self.service.delete_challenge(challenge_id)
        except ValidationError:
            messagebox.showwarning(t("delete_challenge"), t("cannot_delete_active_challenge"))
            return
        self.mode = "list"
        self.selected_id = None
        self.refresh()
        self.on_changed()
