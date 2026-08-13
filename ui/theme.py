"""Color tokens and fonts for the CustomTkinter dashboard.

Palette is the exact spec palette (background/panel/accent/glow/text),
extended with derived tints only where the spec allows ("darker/lighter
variations... only when necessary") and the three semantic status colors.
Both a dark and a light mode are defined; dark is primary per the brief.
"""

import customtkinter as ctk

# ---- exact spec palette ----
BG = "#141C25"
PANEL = "#19243C"
PANEL_2 = "#20304F"
ACCENT = "#4663DE"
ACCENT_GLOW = "#3494EB"
TEXT = "#E8E8EA"
WHITE = "#FFFFFF"

TEXT_DIM = "#9BA6C2"
TEXT_FAINT = "#6E7996"
BORDER = "#2A3A5C"

SUCCESS = "#3FCB86"
WARNING = "#E0B24A"
DANGER = "#E0654A"
ORANGE = "#E28A3D"

# ---- light mode: same hierarchy/philosophy, not a naive inversion ----
LIGHT_BG = "#F3F5F9"
LIGHT_PANEL = "#FFFFFF"
LIGHT_PANEL_2 = "#EBEEF5"
LIGHT_TEXT = "#141C25"
LIGHT_TEXT_DIM = "#4A5470"
LIGHT_TEXT_FAINT = "#7C879E"
LIGHT_BORDER = "#DBE0EC"
# accent/glow/status colors stay identical in both modes — brand consistency

FONT_UI = "Segoe UI"
FONT_MONO = "Consolas"

_FONT_CACHE = {}


def font(size: int, weight: str = "normal", mono: bool = False) -> ctk.CTkFont:
    family = FONT_MONO if mono else FONT_UI
    key = (family, size, weight)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ctk.CTkFont(family=family, size=size, weight=weight)
    return _FONT_CACHE[key]


class Tokens:
    """A live palette object so the app can flip dark/light at runtime
    without rebuilding every widget's color literals by hand."""

    def __init__(self, mode: str = "dark"):
        self.set_mode(mode)

    def set_mode(self, mode: str):
        self.mode = mode
        if mode == "light":
            self.bg = LIGHT_BG
            self.panel = LIGHT_PANEL
            self.panel_2 = LIGHT_PANEL_2
            self.text = LIGHT_TEXT
            self.text_dim = LIGHT_TEXT_DIM
            self.text_faint = LIGHT_TEXT_FAINT
            self.border = LIGHT_BORDER
        else:
            self.bg = BG
            self.panel = PANEL
            self.panel_2 = PANEL_2
            self.text = TEXT
            self.text_dim = TEXT_DIM
            self.text_faint = TEXT_FAINT
            self.border = BORDER
        self.accent = ACCENT
        self.accent_glow = ACCENT_GLOW
        self.success = SUCCESS
        self.warning = WARNING
        self.danger = DANGER
        self.orange = ORANGE
        self.white = WHITE
