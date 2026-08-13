import customtkinter as ctk

from . import theme
from .localization import t


class BattleLog(ctk.CTkFrame):
    def __init__(self, master, tokens: theme.Tokens):
        super().__init__(master, fg_color=tokens.panel, corner_radius=10)
        self.tokens = tokens
        self._last_rendered: list[str] = []
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()
        self.header = ctk.CTkLabel(self, text=t("battle_log"), font=theme.font(12, "bold"), text_color=self.tokens.text)
        self.header.pack(anchor="w", padx=14, pady=(10, 4))

        self.box = ctk.CTkTextbox(
            self, fg_color=self.tokens.panel_2, text_color=self.tokens.text_dim,
            font=theme.font(10, mono=True), wrap="word", state="disabled",
        )
        self.box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.box.tag_config("dmg", foreground=self.tokens.danger)
        self.box.tag_config("attack", foreground="#9FB4FF")
        self.box.tag_config("normal", foreground=self.tokens.text_dim)

    def apply_language(self):
        lines = self._last_rendered
        self._build()
        self._render(lines)

    def update_lines(self, lines: list[str]):
        if lines == self._last_rendered:
            return
        self._render(lines)

    def _render(self, lines: list[str]):
        self._last_rendered = list(lines)
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        for line in lines:
            tag = "dmg" if ("HP -" in line or "error" in line) else ("attack" if "attacked" in line else "normal")
            self.box.insert("end", line + "\n", tag)
        self.box.see("end")
        self.box.configure(state="disabled")
