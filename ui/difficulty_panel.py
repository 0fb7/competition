import customtkinter as ctk

from . import theme
from .localization import t

LEVELS = [
    (1, "level1", "success"),
    (2, "level2", "warning"),
    (3, "level3", "danger"),
]


class DifficultyPanel(ctk.CTkFrame):
    """Configuration-only, by design: the engine does not currently vary
    AI behavior by difficulty (opponents are whatever Python code a team
    submits, not an engine-controlled bot). Selecting a level here stores
    it on the engine (BattleRunner.set_difficulty) and displays it — it
    is intentionally not wired to any behavior change, per spec section 26
    ("implement the configuration layer without pretending the behavior
    already changes").
    """

    def __init__(self, master, tokens: theme.Tokens, on_change):
        super().__init__(master, fg_color=tokens.panel, corner_radius=10)
        self.tokens = tokens
        self.on_change = on_change
        self.selected = 2
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()

        self.header = ctk.CTkLabel(self, text=t("difficulty"), font=theme.font(12, "bold"), text_color=self.tokens.text)
        self.header.pack(anchor="w", padx=14, pady=(10, 2))
        self.note = ctk.CTkLabel(
            self, text=t("difficulty_note"), font=theme.font(9), text_color=self.tokens.text_faint,
            wraplength=220, justify="left",
        )
        self.note.pack(anchor="w", padx=14, pady=(0, 8))

        self._items = {}
        for level, label_key, color_attr in LEVELS:
            row = ctk.CTkButton(
                self, text="●  " + t(label_key), anchor="w", font=theme.font(11, "bold"),
                fg_color=self.tokens.panel_2, hover_color=self.tokens.border,
                text_color=getattr(self.tokens, color_attr),
                border_width=2,
                border_color=self.tokens.accent_glow if level == self.selected else self.tokens.panel_2,
                command=lambda lv=level: self._select(lv),
                height=34,
            )
            row.pack(fill="x", padx=12, pady=3)
            self._items[level] = row

    def _select(self, level: int):
        self.selected = level
        for lv, btn in self._items.items():
            btn.configure(border_color=self.tokens.accent_glow if lv == level else self.tokens.panel_2)
        self.on_change(level)

    def apply_language(self):
        self._build()
