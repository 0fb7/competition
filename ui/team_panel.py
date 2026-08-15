import customtkinter as ctk

from . import theme
from .localization import t

# Roster flavor metadata — not battle telemetry. HP/energy/status below
# always come from the live engine snapshot.
ROSTER = {
    "alpha": {"player": "Ahmed", "color_key": "accent_glow"},
    "beta": {"player": "Mohammed", "color_key": "orange"},
}


class TeamCard(ctk.CTkFrame):
    def __init__(self, master, tokens: theme.Tokens, side_key: str):
        super().__init__(master, fg_color=tokens.panel_2, corner_radius=8)
        self.tokens = tokens
        self.side_key = side_key
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()
        accent = getattr(self.tokens, ROSTER[self.side_key]["color_key"])

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 4))
        self.name_lbl = ctk.CTkLabel(head, text="—", font=theme.font(13, "bold"), text_color=accent)
        self.name_lbl.pack(side="left")
        self.status_pill = ctk.CTkLabel(
            head, text=t("active"), font=theme.font(9, "bold"), fg_color=self.tokens.success,
            text_color="#0B1017", corner_radius=999, width=64, height=18,
        )
        self.status_pill.pack(side="right")

        self.rows = {}
        for key, label_key in (("player", "player"), ("ship", "ship"), ("score", "score"), ("action", "action")):
            row = ctk.CTkFrame(self, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=1)
            k = ctk.CTkLabel(row, text=t(label_key), font=theme.font(10), text_color=self.tokens.text_faint)
            k.pack(side="left")
            v = ctk.CTkLabel(row, text="—", font=theme.font(10, "bold"), text_color=self.tokens.text)
            v.pack(side="right")
            self.rows[key] = (k, v, label_key)

        self.hp_label = ctk.CTkLabel(self, text=f"{t('health')} 0%", font=theme.font(10), text_color=self.tokens.text_faint)
        self.hp_label.pack(fill="x", padx=12, pady=(6, 0))
        self.hp_bar = ctk.CTkProgressBar(self, height=6, progress_color=self.tokens.success)
        self.hp_bar.pack(fill="x", padx=12, pady=(2, 6))

        self.en_label = ctk.CTkLabel(self, text=f"{t('energy')} 0%", font=theme.font(10), text_color=self.tokens.text_faint)
        self.en_label.pack(fill="x", padx=12, pady=(0, 0))
        self.en_bar = ctk.CTkProgressBar(self, height=6, progress_color=self.tokens.accent_glow)
        self.en_bar.pack(fill="x", padx=12, pady=(2, 12))

    def apply_language(self):
        prev_values = {k: v[1].cget("text") for k, v in self.rows.items()}
        self._build()

    def update_from(self, ship: dict, score: int, is_draw: bool = False):
        self.name_lbl.configure(text=ship["team"].upper())
        alive = ship["alive"]
        if is_draw:
            # DRAW is a distinct, first-class status — never rendered as
            # ACTIVE/DAMAGED/DESTROYED (spec sections 9/21/24).
            status_key, color = "draw", self.tokens.warning
        else:
            status_key = "active" if alive else "destroyed"
            color = self.tokens.success if alive else self.tokens.danger
            if alive and ship["hp_pct"] < 0.5:
                status_key, color = "damaged", self.tokens.warning
        self.status_pill.configure(text=t(status_key), fg_color=color)

        values = {
            "player": ROSTER[self.side_key]["player"],
            "ship": ship["name"],
            "score": str(score),
            "action": ship.get("last_action", "-"),
        }
        for key, (k_lbl, v_lbl, label_key) in self.rows.items():
            k_lbl.configure(text=t(label_key))
            v_lbl.configure(text=values[key])

        self.hp_label.configure(text=f"{t('health')} {ship['hp_pct']*100:.0f}%")
        self.hp_bar.set(max(0.0, ship["hp_pct"]))
        self.hp_bar.configure(
            progress_color=self.tokens.success if ship["hp_pct"] > 0.5
            else (self.tokens.warning if ship["hp_pct"] > 0.2 else self.tokens.danger)
        )
        self.en_label.configure(text=f"{t('energy')} {ship['energy_pct']*100:.0f}%")
        self.en_bar.set(max(0.0, ship["energy_pct"]))


class TeamPanel(ctk.CTkFrame):
    def __init__(self, master, tokens: theme.Tokens):
        super().__init__(master, fg_color=tokens.panel, corner_radius=10)
        self.tokens = tokens
        self._build_header()
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)
        self.card_a = TeamCard(row, tokens, "alpha")
        self.card_a.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.card_b = TeamCard(row, tokens, "beta")
        self.card_b.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

    def _build_header(self):
        self.header = ctk.CTkLabel(self, text=t("team"), font=theme.font(12, "bold"), text_color=self.tokens.text)
        self.header.pack(anchor="w", padx=14, pady=(10, 6))

    def apply_language(self):
        self.header.configure(text=t("team"))
        self.card_a.apply_language()
        self.card_b.apply_language()

    def update_from_snapshot(self, snapshot: dict, score_a: int, score_b: int, is_draw: bool = False):
        self.card_a.update_from(snapshot["ship_a"], score_a, is_draw)
        self.card_b.update_from(snapshot["ship_b"], score_b, is_draw)
