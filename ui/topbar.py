import customtkinter as ctk

from . import theme, live_state
from .localization import t


class TopBar(ctk.CTkFrame):
    def __init__(self, master, tokens: theme.Tokens, on_lang_change, on_theme_toggle):
        super().__init__(master, fg_color=tokens.panel, corner_radius=0, height=56)
        self.tokens = tokens
        self.on_lang_change = on_lang_change
        self.on_theme_toggle = on_theme_toggle
        self.grid_propagate(False)
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()

        pad = 16
        self.name_label = ctk.CTkLabel(
            self, text=t("app_name"), font=theme.font(15, "bold"), text_color=self.tokens.text,
        )
        self.name_label.pack(side="left", padx=(pad, 6), pady=10)

        self.comp_label = ctk.CTkLabel(
            self, text=t("competition"), font=theme.font(12), text_color=self.tokens.text_dim,
        )
        self.comp_label.pack(side="left", padx=6)

        self.status_pill = ctk.CTkLabel(
            self, text="●  " + t("idle"), font=theme.font(11, "bold"),
            text_color=self.tokens.text_faint, fg_color=self.tokens.panel_2,
            corner_radius=999, width=90, height=24,
        )
        self.status_pill.pack(side="left", padx=12)

        # right-aligned controls
        self.admin_label = ctk.CTkLabel(
            self, text=f"{t('admin')} · Sarah K.", font=theme.font(12),
            text_color=self.tokens.text_dim,
        )
        self.admin_label.pack(side="right", padx=(6, pad))

        self.theme_btn = ctk.CTkButton(
            self, text="◐", width=32, height=28, font=theme.font(13),
            fg_color=self.tokens.panel_2, hover_color=self.tokens.border,
            command=self.on_theme_toggle,
        )
        self.theme_btn.pack(side="right", padx=4)

        lang_frame = ctk.CTkFrame(self, fg_color=self.tokens.panel_2, corner_radius=999)
        lang_frame.pack(side="right", padx=6)
        self.en_btn = ctk.CTkButton(
            lang_frame, text="EN", width=36, height=24, corner_radius=999,
            fg_color=self.tokens.accent, font=theme.font(11, "bold"),
            command=lambda: self.on_lang_change("en"),
        )
        self.en_btn.pack(side="left", padx=2, pady=2)
        self.ar_btn = ctk.CTkButton(
            lang_frame, text="AR", width=36, height=24, corner_radius=999,
            fg_color="transparent", text_color=self.tokens.text_faint, font=theme.font(11, "bold"),
            command=lambda: self.on_lang_change("ar"),
        )
        self.ar_btn.pack(side="left", padx=2, pady=2)

    def apply_language(self, lang: str):
        self._build()
        if lang == "ar":
            self.en_btn.configure(fg_color="transparent", text_color=self.tokens.text_faint)
            self.ar_btn.configure(fg_color=self.tokens.accent, text_color=self.tokens.white)
        else:
            self.ar_btn.configure(fg_color="transparent", text_color=self.tokens.text_faint)
            self.en_btn.configure(fg_color=self.tokens.accent, text_color=self.tokens.white)

    # Runtime-state -> (localization key, color) — the single source of
    # truth for "what state are we in" is live_state.compute_runtime_state()
    # (called once per tick in ui/app.py); this just maps that real state
    # to a label, it never re-derives the state itself (spec section 25).
    _STATE_STYLE = {
        "IDLE": ("idle", "text_faint"), "PREPARING": ("preparing", "warning"),
        "RUNNING": ("live", "danger"), "PAUSED": ("paused", "text_faint"),
        "COMPLETED": ("completed", "accent_glow"), "ERROR": ("error_status", "danger"),
        "STOPPED": ("stopped", "text_faint"),
    }

    def update_status(self, snapshot: dict, runtime_state: str = "IDLE"):
        if snapshot["winner"]:
            self.status_pill.configure(text="●  " + snapshot["winner"], text_color=self.tokens.success)
            return
        if live_state.is_draw_outcome(snapshot):
            self.status_pill.configure(text="●  " + t("draw"), text_color=self.tokens.warning)
            return
        label_key, color_attr = self._STATE_STYLE.get(runtime_state, ("idle", "text_faint"))
        self.status_pill.configure(text="●  " + t(label_key), text_color=getattr(self.tokens, color_attr))
