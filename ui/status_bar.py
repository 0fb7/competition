import customtkinter as ctk

from . import theme
from .localization import t


class StatusBar(ctk.CTkFrame):
    """Real technical status only. Values that have no real source behind
    them (e.g. render FPS when the arena isn't embedded) show N/A instead
    of an invented number — see spec section 29.
    """

    def __init__(self, master, tokens: theme.Tokens):
        super().__init__(master, fg_color=tokens.panel, corner_radius=10)
        self.tokens = tokens
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()

        header = ctk.CTkLabel(
            self, text=t("system_status"), font=theme.font(12, "bold"), text_color=self.tokens.text,
        )
        header.pack(side="left", padx=(14, 18), pady=10)

        self.items = {}
        specs = [
            ("engine", "simulation_engine", True),
            ("runtime", "python_runtime", True),
            ("validation", "code_validation", True),
            ("server", "battle_server", True),
            ("fps", None, None),
            ("latency", None, None),
        ]
        for key, label_key, _ in specs:
            item = ctk.CTkLabel(self, text="…", font=theme.font(11), text_color=self.tokens.text_dim)
            item.pack(side="left", padx=10)
            self.items[key] = item

    def apply_language(self):
        self._build()
        self.update_values(self._last_snapshot if hasattr(self, "_last_snapshot") else None)

    def update_values(self, snapshot: dict | None, code_valid: bool | None, embedded_fps: float | None):
        self._last_snapshot = snapshot
        ok = self.tokens.success

        self.items["engine"].configure(
            text=f"{t('simulation_engine')}: {t('online') if snapshot and snapshot['engine_alive'] else t('not_available')}",
            text_color=ok if snapshot and snapshot["engine_alive"] else self.tokens.text_faint,
        )
        self.items["runtime"].configure(text=f"{t('python_runtime')}: {t('ready')}", text_color=ok)

        if code_valid is None:
            val_text, val_color = t("not_available"), self.tokens.text_faint
        elif code_valid:
            val_text, val_color = t("passed"), ok
        else:
            val_text, val_color = t("invalid"), self.tokens.danger
        self.items["validation"].configure(text=f"{t('code_validation')}: {val_text}", text_color=val_color)

        self.items["server"].configure(
            text=f"{t('battle_server')}: {t('connected') if snapshot else t('not_available')}",
            text_color=ok if snapshot else self.tokens.text_faint,
        )

        fps_text = f"{embedded_fps:.0f}" if embedded_fps else t("not_available")
        self.items["fps"].configure(text=f"FPS: {fps_text}", text_color=self.tokens.text_dim)

        lat_text = f"{snapshot['engine_tick_ms']:.1f} ms" if snapshot else t("not_available")
        self.items["latency"].configure(text=f"Latency: {lat_text}", text_color=self.tokens.text_dim)
