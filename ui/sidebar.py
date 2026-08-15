import customtkinter as ctk

from . import theme
from .localization import t, is_rtl

NAV_ITEMS = [
    ("dashboard", "nav_dashboard"),
    ("arena", "nav_arena"),
    ("teams", "nav_teams"),
    ("code", "nav_code"),
    ("challenges", "nav_challenges"),
    ("competition", "nav_competition"),
    ("live", "nav_live_monitor"),
    ("leaderboard", "nav_results"),
    ("logs", "nav_logs"),
    ("settings", "nav_settings"),
]

# Only these route to real, populated content; the rest show an honest
# "not built yet" placeholder rather than faking data for a tab with no
# backing feature.
IMPLEMENTED_TABS = {"dashboard", "arena", "teams", "code", "challenges", "competition", "live", "leaderboard", "logs"}


class Sidebar(ctk.CTkFrame):
    def __init__(self, master, tokens: theme.Tokens, on_select, width=200):
        super().__init__(master, fg_color=tokens.panel, corner_radius=0, width=width)
        self.tokens = tokens
        self.on_select = on_select
        self.active = "dashboard"
        self.grid_propagate(False)
        self._buttons = {}
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()
        self._buttons = {}

        anchor = "e" if is_rtl() else "w"
        justify = "right" if is_rtl() else "left"

        brand = ctk.CTkLabel(
            self, text=t("app_name"), font=theme.font(13, "bold"),
            text_color=self.tokens.text, anchor=anchor, justify=justify,
        )
        brand.pack(fill="x", padx=16, pady=(18, 14))

        for key, label_key in NAV_ITEMS:
            btn = ctk.CTkButton(
                self, text=t(label_key), anchor=anchor,
                font=theme.font(12, "bold" if key == self.active else "normal"),
                fg_color=self.tokens.accent if key == self.active else "transparent",
                text_color=self.tokens.white if key == self.active else self.tokens.text_dim,
                hover_color=self.tokens.panel_2,
                corner_radius=8, height=36,
                command=lambda k=key: self._select(k),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self._buttons[key] = btn

    def _select(self, key: str):
        self.active = key
        for k, btn in self._buttons.items():
            is_active = k == key
            btn.configure(
                fg_color=self.tokens.accent if is_active else "transparent",
                text_color=self.tokens.white if is_active else self.tokens.text_dim,
                font=theme.font(12, "bold" if is_active else "normal"),
            )
        self.on_select(key, key in IMPLEMENTED_TABS)

    def apply_language(self):
        self._build()
