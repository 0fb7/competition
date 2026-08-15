"""Submission workspace — makes the "Python Code" / "كود بايثون" nav item
a real submission workflow: pick a Team + Challenge, see that pair's
version history, and Save/Validate/Test/Submit through
SubmissionService. Reuses ui/code_editor.py's CodeEditor (same class,
same syntax highlighting) rather than building a second editor; only the
toolbar and read-only state change with submission status.
"""

import threading
import tkinter.messagebox as messagebox

import customtkinter as ctk

from . import theme
from .localization import t, is_rtl
from .code_editor import CodeEditor
from submissions.submission import (
    STATUS_DRAFT, STATUS_VALIDATED, STATUS_SUBMITTED, STATUS_REJECTED,
    TEST_PASSED, TEST_FAILED, TEST_TIMEOUT, TEST_ERROR,
    ImmutableSubmissionError,
)
from submissions.submission_service import ValidationError

STATUS_LABEL_KEY = {
    STATUS_DRAFT: "draft", STATUS_VALIDATED: "validated",
    STATUS_SUBMITTED: "submitted", STATUS_REJECTED: "rejected",
}

TEST_RESULT_LABEL_KEY = {
    TEST_PASSED: "test_passed", TEST_FAILED: "test_failed",
    TEST_TIMEOUT: "test_timeout", TEST_ERROR: "test_error",
}


class SubmissionWorkspace(ctk.CTkFrame):
    def __init__(
        self, master, tokens: theme.Tokens, team_service, challenge_service,
        submission_service, get_starter_code, on_changed=None,
    ):
        super().__init__(master, fg_color="transparent")
        self.tokens = tokens
        self.team_service = team_service
        self.challenge_service = challenge_service
        self.submission_service = submission_service
        self.get_starter_code = get_starter_code
        self.on_changed = on_changed or (lambda: None)

        self.selected_team_id = None
        self.selected_challenge_id = None
        self.selected_submission_id = None
        self._team_name_to_id = {}
        self._challenge_name_to_id = {}
        self._testing = False

        self._build_shell()
        self._select_defaults()

    # ------------------------------------------------------------- shell
    def _build_shell(self):
        for w in self.winfo_children():
            w.destroy()

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", pady=(0, 8))
        self.title_lbl = ctk.CTkLabel(head, text=t("submissions_title"), font=theme.font(16, "bold"), text_color=self.tokens.text)
        self.title_lbl.pack(side="left")

        selectors = ctk.CTkFrame(self, fg_color=self.tokens.panel, corner_radius=10)
        selectors.pack(fill="x", pady=(0, 8))
        team_col = ctk.CTkFrame(selectors, fg_color="transparent")
        team_col.pack(side="left", padx=14, pady=10)
        ctk.CTkLabel(team_col, text=t("team"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w")
        self.team_menu = ctk.CTkOptionMenu(
            team_col, values=["-"], command=self._on_team_change,
            fg_color=self.tokens.panel_2, button_color=self.tokens.accent, width=200,
        )
        self.team_menu.pack(anchor="w")

        challenge_col = ctk.CTkFrame(selectors, fg_color="transparent")
        challenge_col.pack(side="left", padx=14, pady=10)
        ctk.CTkLabel(challenge_col, text=t("challenges_title"), font=theme.font(10), text_color=self.tokens.text_faint).pack(anchor="w")
        self.challenge_menu = ctk.CTkOptionMenu(
            challenge_col, values=["-"], command=self._on_challenge_change,
            fg_color=self.tokens.panel_2, button_color=self.tokens.accent, width=220,
        )
        self.challenge_menu.pack(anchor="w")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_columnconfigure(1, weight=2)
        self.body.grid_rowconfigure(0, weight=1)

    def apply_language(self):
        self._build_shell()
        self._populate_selectors()
        self.refresh()

    # --------------------------------------------------------- selection
    def _select_defaults(self):
        self._populate_selectors()
        teams = self.team_service.get_all_teams()
        challenges = self.challenge_service.get_all_challenges()
        active_challenge = self.challenge_service.get_active_challenge()
        if teams:
            self.selected_team_id = teams[0].id
            self.team_menu.set(teams[0].name)
        if active_challenge:
            self.selected_challenge_id = active_challenge.id
            self.challenge_menu.set(active_challenge.name)
        elif challenges:
            self.selected_challenge_id = challenges[0].id
            self.challenge_menu.set(challenges[0].name)
        self._load_default_submission()
        self.refresh()

    def _populate_selectors(self):
        teams = self.team_service.get_all_teams()
        challenges = self.challenge_service.get_all_challenges()
        self._team_name_to_id = {team.name: team.id for team in teams}
        self._challenge_name_to_id = {c.name: c.id for c in challenges}
        self.team_menu.configure(values=list(self._team_name_to_id) or ["-"])
        self.challenge_menu.configure(values=list(self._challenge_name_to_id) or ["-"])

    def _on_team_change(self, name: str):
        self.selected_team_id = self._team_name_to_id.get(name)
        self._load_default_submission()
        self.refresh()

    def _on_challenge_change(self, name: str):
        self.selected_challenge_id = self._challenge_name_to_id.get(name)
        self._load_default_submission()
        self.refresh()

    def _load_default_submission(self):
        if not (self.selected_team_id and self.selected_challenge_id):
            self.selected_submission_id = None
            return
        team = self.team_service.get_team(self.selected_team_id)
        existing = self.submission_service.get_team_challenge_submissions(self.selected_team_id, self.selected_challenge_id)
        if not existing:
            starter = self.get_starter_code(team) if team else ""
            sub = self.submission_service.ensure_starter_draft(self.selected_team_id, self.selected_challenge_id, starter)
        else:
            sub = self.submission_service.get_active_or_latest(self.selected_team_id, self.selected_challenge_id)
        self.selected_submission_id = sub.id if sub else None

    def refresh_selectors_and_defaults(self):
        """Called when Teams/Challenges change elsewhere so the dropdowns
        and the loaded submission stay in sync."""
        self._populate_selectors()
        if self.selected_team_id not in self._team_name_to_id.values():
            self._select_defaults()
            return
        self.refresh()

    # ------------------------------------------------------------ refresh
    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()

        if not self.selected_team_id:
            ctk.CTkLabel(self.body, text=t("select_team"), font=theme.font(13), text_color=self.tokens.text_faint).grid(row=0, column=0, columnspan=2, pady=40)
            return
        if not self.selected_challenge_id:
            ctk.CTkLabel(self.body, text=t("select_challenge"), font=theme.font(13), text_color=self.tokens.text_faint).grid(row=0, column=0, columnspan=2, pady=40)
            return

        self._build_history_panel()
        self._build_editor_panel()

    def _status_color(self, status):
        return {
            STATUS_DRAFT: self.tokens.text_faint, STATUS_VALIDATED: self.tokens.accent_glow,
            STATUS_SUBMITTED: self.tokens.success, STATUS_REJECTED: self.tokens.danger,
        }[status]

    def _build_history_panel(self):
        panel = ctk.CTkFrame(self.body, fg_color=self.tokens.panel, corner_radius=10)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ctk.CTkLabel(panel, text=t("submission_history"), font=theme.font(12, "bold"), text_color=self.tokens.text).pack(anchor="w", padx=14, pady=(12, 6))

        history = self.submission_service.get_team_challenge_submissions(self.selected_team_id, self.selected_challenge_id)
        active = self.submission_service.get_active_submission(self.selected_team_id, self.selected_challenge_id)
        active_id = active.id if active else None

        scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        if not history:
            ctk.CTkLabel(scroll, text=t("no_submissions_title"), font=theme.font(11), text_color=self.tokens.text_faint).pack(pady=10)
            ctk.CTkLabel(scroll, text=t("no_submissions_body"), font=theme.font(10), text_color=self.tokens.text_faint).pack()
            return

        for sub in reversed(history):
            selected = sub.id == self.selected_submission_id
            row = ctk.CTkButton(
                scroll, text=f"v{sub.version}   {t(STATUS_LABEL_KEY[sub.status])}" + ("  ★" if sub.id == active_id else ""),
                anchor="w", font=theme.font(11, "bold" if selected else "normal"),
                fg_color=self.tokens.accent if selected else self.tokens.panel_2,
                text_color=self.tokens.white if selected else self._status_color(sub.status),
                hover_color=self.tokens.border, height=32,
                command=lambda sid=sub.id: self._select_version(sid),
            )
            row.pack(fill="x", pady=2)

    def _select_version(self, submission_id: str):
        self.selected_submission_id = submission_id
        self.refresh()

    # ------------------------------------------------------------- editor
    def _build_editor_panel(self):
        container = ctk.CTkFrame(self.body, fg_color="transparent")
        container.grid(row=0, column=1, sticky="nsew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        submission = self.submission_service.get_submission(self.selected_submission_id) if self.selected_submission_id else None
        if submission is None:
            ctk.CTkLabel(container, text=t("no_submissions_title"), font=theme.font(12), text_color=self.tokens.text_faint).grid(row=0, column=0)
            return

        self.editor = CodeEditor(container, self.tokens)
        self.editor.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        read_only = submission.status == STATUS_SUBMITTED
        filename = f"{self.selected_team_id} · v{submission.version}"
        self.editor.load_code(submission.code, filename, read_only=read_only)

        if read_only:
            self.editor.set_status_text(t("submitted_read_only"), self.tokens.success)
            self.editor.set_toolbar_buttons([
                {"text": t("new_version"), "kind": "primary", "command": self._new_version},
            ])
        else:
            status_key = STATUS_LABEL_KEY[submission.status]
            self.editor.set_status_text(f"{t(status_key)} — {t('draft_editable')}", self._status_color(submission.status))
            self.editor.set_toolbar_buttons([
                {"text": t("save"), "kind": "neutral", "command": lambda: self._save(submission.id)},
                {"text": t("validate"), "kind": "neutral", "command": lambda: self._validate(submission.id)},
                {"text": t("test"), "kind": "neutral", "command": lambda: self._start_test(submission.id)},
                {"text": t("submit"), "kind": "primary", "command": lambda: self._submit(submission.id)},
            ])

        results = ctk.CTkFrame(container, fg_color=self.tokens.panel, corner_radius=10)
        results.grid(row=1, column=0, sticky="ew")
        self._build_results(results, submission)

    def _build_results(self, parent, submission):
        if submission.validation_result and submission.validation_result.errors:
            box = ctk.CTkFrame(parent, fg_color="transparent")
            box.pack(fill="x", padx=14, pady=(10, 4))
            ctk.CTkLabel(box, text=t("validation_errors"), font=theme.font(11, "bold"), text_color=self.tokens.danger).pack(anchor="w")
            for issue in submission.validation_result.errors[:5]:
                line_part = f"{t('line')} {issue.line}: " if issue.line else ""
                ctk.CTkLabel(
                    box, text=f"  ❌ {line_part}{issue.message}", font=theme.font(10, mono=True),
                    text_color=self.tokens.text_dim, anchor="w", justify="left",
                ).pack(anchor="w")

        if submission.test_result:
            tr = submission.test_result
            box = ctk.CTkFrame(parent, fg_color="transparent")
            box.pack(fill="x", padx=14, pady=(6, 10))
            color = {
                TEST_PASSED: self.tokens.success, TEST_FAILED: self.tokens.danger,
                TEST_TIMEOUT: self.tokens.warning, TEST_ERROR: self.tokens.danger,
            }[tr.status]
            ctk.CTkLabel(
                box, text=f"{t('test_results')}: {t(TEST_RESULT_LABEL_KEY[tr.status])}",
                font=theme.font(11, "bold"), text_color=color,
            ).pack(anchor="w")
            detail = (
                f"{t('winner')}: {tr.winner or '-'}   {t('final_hp')}: {tr.final_hp:.0f}   "
                f"{t('duration')}: {tr.duration:.2f}s   {t('events')}: {tr.events_count}"
            )
            ctk.CTkLabel(box, text=detail, font=theme.font(10, mono=True), text_color=self.tokens.text_dim, anchor="w").pack(anchor="w")
            for err in tr.errors[:3]:
                ctk.CTkLabel(box, text=f"  ❌ {err}", font=theme.font(10, mono=True), text_color=self.tokens.text_dim, anchor="w").pack(anchor="w")

    # ------------------------------------------------------------ actions
    def _save(self, submission_id: str):
        code = self.editor.get_code()
        try:
            self.submission_service.update_draft(submission_id, code)
        except ImmutableSubmissionError:
            messagebox.showwarning(t("save"), t("submitted_read_only"))
            return
        self.refresh()
        self.on_changed()

    def _validate(self, submission_id: str):
        self._save(submission_id)
        result = self.submission_service.validate_submission(submission_id)
        self.refresh()
        if not result.valid:
            messagebox.showwarning(t("validate"), t("validation_failed"))

    def _start_test(self, submission_id: str):
        if self._testing:
            return
        self._save(submission_id)
        self._testing = True
        if hasattr(self, "editor"):
            self.editor.set_status_text(t("testing_in_progress"), self.tokens.accent_glow)

        result_box = {}

        def worker():
            try:
                result_box["result"] = self.submission_service.test_submission(submission_id)
            except Exception as e:  # a bug in the test runner, not the candidate code
                result_box["error"] = str(e)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.after(150, lambda: self._poll_test(thread, result_box, submission_id))

    def _poll_test(self, thread, result_box, submission_id):
        if thread.is_alive():
            self.after(150, lambda: self._poll_test(thread, result_box, submission_id))
            return
        self._testing = False
        # Phase 8 (Step 10): this used to be captured into result_box["error"]
        # and never read anywhere — a genuine silent failure (the "Testing..."
        # status would just disappear with no result AND no explanation if
        # test_submission() ever raised something unexpected). Never a
        # candidate-code error (those become a TIMEOUT/ERROR TestResult, not
        # an exception here) — this is a real bug in the test runner itself,
        # so it's shown, not swallowed.
        if "error" in result_box:
            messagebox.showerror(t("test"), t("test_runner_internal_error").format(detail=result_box["error"]))
        if self.selected_submission_id == submission_id:
            self.refresh()
        self.on_changed()

    def _submit(self, submission_id: str):
        self._save(submission_id)
        try:
            self.submission_service.submit_submission(submission_id)
        except ValidationError as e:
            msg = t("submit_blocked_validation") if str(e) == "validation_failed" else t("submit_blocked_test")
            messagebox.showwarning(t("submit"), msg)
            self.refresh()
            return
        self.refresh()
        self.on_changed()

    def _new_version(self):
        team = self.team_service.get_team(self.selected_team_id)
        starter = self.get_starter_code(team) if team else ""
        new_sub = self.submission_service.create_new_version(self.selected_team_id, self.selected_challenge_id, starter)
        self.selected_submission_id = new_sub.id
        self.refresh()
        self.on_changed()
