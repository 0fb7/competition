import customtkinter as ctk

from . import theme, status_style
from .localization import t

COLUMNS = ["rank", "team", "score", "wins", "losses", "damage", "status"]


class Scoreboard(ctk.CTkFrame):
    def __init__(self, master, tokens: theme.Tokens):
        super().__init__(master, fg_color=tokens.panel, corner_radius=10)
        self.tokens = tokens
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()

        self.header = ctk.CTkLabel(self, text=t("leaderboard"), font=theme.font(12, "bold"), text_color=self.tokens.text)
        self.header.pack(anchor="w", padx=14, pady=(10, 4))

        self.table = ctk.CTkFrame(self, fg_color="transparent")
        self.table.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for i in range(len(COLUMNS)):
            self.table.columnconfigure(i, weight=1)

        self.header_labels = []
        for col, key in enumerate(COLUMNS):
            lbl = ctk.CTkLabel(self.table, text=t(key), font=theme.font(10, "bold"), text_color=self.tokens.text_faint)
            lbl.grid(row=0, column=col, sticky="w", padx=6, pady=(0, 4))
            self.header_labels.append(lbl)

        self._row_widgets = []

    def apply_language(self):
        self._build()

    def update_rows(self, rows: list[dict]):
        needed = len(rows)
        while len(self._row_widgets) < needed:
            r = len(self._row_widgets) + 1
            widgets = []
            for col in range(len(COLUMNS)):
                lbl = ctk.CTkLabel(self.table, text="", font=theme.font(11), text_color=self.tokens.text)
                lbl.grid(row=r, column=col, sticky="w", padx=6, pady=3)
                widgets.append(lbl)
            self._row_widgets.append(widgets)

        for i, row in enumerate(rows):
            widgets = self._row_widgets[i]
            values = [
                str(row["rank"]), row["team"], str(row["score"]), str(row["wins"]),
                str(row["losses"]), f"{row['damage']:.0f}", t(row["status_key"]),
            ]
            colors = [self.tokens.text_faint, self.tokens.text] + [self.tokens.text] * 4
            # DRAW gets its own distinct color — never reuses the ACTIVE
            # (success/green) or DESTROYED (danger/red) styling (spec
            # sections 9/21/24; closes backlog item 6 in the LIVE
            # scoreboard specifically, not just the historical one).
            # Phase 8: the color itself now comes from the single shared
            # ui/status_style.py table instead of a copy of this same
            # active/damaged/draw/destroyed mapping.
            colors[-1] = getattr(
                self.tokens, status_style.SHIP_STATUS_COLOR_ATTR.get(row["status_key"], "danger"),
            )
            for w, v, c in zip(widgets, values, colors):
                w.configure(text=v, text_color=c)
