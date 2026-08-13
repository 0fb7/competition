"""The Python code editor widget — reused as-is (same class, same
highlighting mechanics) by ui/submission_workspace.py (Phase 3). Its
toolbar is now driven by submission status rather than a fixed
Run/Validate/Stop set, and it no longer has any way to hot-swap the live
battle's code directly — that old "Run" button called
BattleRunner.set_team_code() straight from the editor, bypassing the
whole submission/versioning/immutability system Phase 3 introduces.
Editing now only ever writes to a draft submission through
SubmissionService; only a SUBMITTED version can ever reach a battle.
"""

import re

import customtkinter as ctk

from . import theme
from .localization import t

KEYWORDS = r"\b(def|if|elif|else|for|while|return|and|or|not|in|is|True|False|None|break|continue|pass)\b"
STRINGS = r"(\".*?\"|'.*?')"
COMMENTS = r"(#.*)"
NUMBERS = r"\b(\d+\.?\d*)\b"
CALLS = r"\b([a-zA-Z_][a-zA-Z0-9_]*)(?=\()"


class CodeEditor(ctk.CTkFrame):
    """A plain, reusable code-editing surface: line highlighting, get/set
    code, and a toolbar area that the owner (SubmissionWorkspace) fills in
    via set_toolbar_buttons() — it has no opinion of its own about what
    Save/Validate/Test/Submit should do."""

    def __init__(self, master, tokens: theme.Tokens, on_change=None):
        super().__init__(master, fg_color=tokens.panel, corner_radius=10)
        self.tokens = tokens
        self.on_change = on_change or (lambda: None)
        self.read_only = False
        self._toolbar_specs = []
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 4))
        self.header = ctk.CTkLabel(head, text=t("python_code"), font=theme.font(12, "bold"), text_color=self.tokens.text)
        self.header.pack(side="left")
        self.status_lbl = ctk.CTkLabel(head, text="", font=theme.font(10, "bold"), text_color=self.tokens.text_faint)
        self.status_lbl.pack(side="right")

        self.filename_lbl = ctk.CTkLabel(
            self, text="", font=theme.font(10, mono=True), text_color=self.tokens.text_faint,
        )
        self.filename_lbl.pack(anchor="w", padx=14)

        self.text = ctk.CTkTextbox(
            self, fg_color="#0F151E", text_color=self.tokens.text, font=theme.font(11, mono=True),
            wrap="none",
        )
        self.text.pack(fill="both", expand=True, padx=10, pady=8)
        self._setup_tags()
        self.text.bind("<KeyRelease>", self._on_key_release)

        self.toolbar = ctk.CTkFrame(self, fg_color="transparent")
        self.toolbar.pack(fill="x", padx=10, pady=(0, 10))
        self._render_toolbar()

    def _setup_tags(self):
        self.text.tag_config("kw", foreground="#8AA6F0")
        self.text.tag_config("str", foreground="#9FE6A8")
        self.text.tag_config("cm", foreground=self.tokens.text_faint)
        self.text.tag_config("num", foreground=self.tokens.warning)
        self.text.tag_config("call", foreground="#7FD6E0")

    # ---------------------------------------------------------- content
    def load_code(self, code: str, filename: str, read_only: bool = False):
        self.filename_lbl.configure(text=filename)
        self.read_only = read_only
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", code)
        self._highlight()
        if read_only:
            self.text.configure(state="disabled")

    def get_code(self) -> str:
        return self.text.get("1.0", "end-1c")

    def _on_key_release(self, _event=None):
        self._highlight()
        self.on_change()

    def _highlight(self):
        for tag in ("kw", "str", "cm", "num", "call"):
            self.text.tag_remove(tag, "1.0", "end")
        content = self.get_code()
        for pattern, tag in ((KEYWORDS, "kw"), (CALLS, "call"), (NUMBERS, "num"), (STRINGS, "str"), (COMMENTS, "cm")):
            for m in re.finditer(pattern, content):
                start = f"1.0+{m.start()}c"
                end = f"1.0+{m.end()}c"
                self.text.tag_add(tag, start, end)

    # ---------------------------------------------------------- toolbar
    def set_toolbar_buttons(self, specs: list[dict]):
        """`specs`: list of {text, command, kind} where kind is one of
        "primary" | "neutral" | "danger" | "outline" — the owner decides
        which buttons exist for the current submission status."""
        self._toolbar_specs = specs
        self._render_toolbar()

    def _render_toolbar(self):
        for w in self.toolbar.winfo_children():
            w.destroy()
        for spec in self._toolbar_specs:
            kind = spec.get("kind", "neutral")
            if kind == "primary":
                btn = ctk.CTkButton(self.toolbar, text=spec["text"], fg_color=self.tokens.accent, command=spec["command"])
            elif kind == "danger":
                btn = ctk.CTkButton(
                    self.toolbar, text=spec["text"], fg_color="transparent", border_width=1,
                    border_color=self.tokens.danger, text_color=self.tokens.danger, command=spec["command"],
                )
            elif kind == "outline":
                btn = ctk.CTkButton(
                    self.toolbar, text=spec["text"], fg_color="transparent", border_width=1,
                    border_color=self.tokens.border, text_color=self.tokens.text_dim, command=spec["command"],
                )
            else:
                btn = ctk.CTkButton(self.toolbar, text=spec["text"], fg_color=self.tokens.panel_2, hover_color=self.tokens.border, command=spec["command"])
            btn.pack(side="left", padx=3)

    def set_status_text(self, text: str, color: str):
        self.status_lbl.configure(text=text, text_color=color)

    def apply_language(self):
        code = self.get_code()
        fname = self.filename_lbl.cget("text")
        read_only = self.read_only
        specs = self._toolbar_specs
        status_text = self.status_lbl.cget("text")
        status_color = self.status_lbl.cget("text_color")
        self._build()
        self.load_code(code, fname, read_only=read_only)
        self.set_toolbar_buttons(specs)
        self.set_status_text(status_text, status_color)
