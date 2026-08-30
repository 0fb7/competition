"""Shared application branding (logo + window icon) — used by both the
main admin dashboard (ui/app.py) and the standalone Practice Console
(practice_console.py), so both windows carry the same official logo
without duplicating asset-loading logic.
"""

import os
import sys
import tkinter as tk

import customtkinter as ctk
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGO_PATH = os.path.join(ROOT, "assets", "logo.png")
ICO_PATH = os.path.join(ROOT, "assets", "logo.ico")

_ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _resolve(path: str | None, default: str) -> str:
    if not path:
        return default
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def _ensure_ico(png_path: str, ico_path: str) -> bool:
    """Generates (or regenerates, if the source .png changed) a
    multi-resolution .ico next to the source .png. Returns True if a
    usable .ico exists afterward. Windows' actual title-bar/taskbar icon
    is drawn from this — iconphoto() alone (a .png/.gif PhotoImage)
    reliably updates some contexts but NOT that top-left title-bar icon
    on Windows, which is why setting only iconphoto() left the default
    system icon showing."""
    if not os.path.exists(png_path):
        return False
    try:
        if not os.path.exists(ico_path) or os.path.getmtime(png_path) > os.path.getmtime(ico_path):
            img = Image.open(png_path).convert("RGBA")
            img.save(ico_path, format="ICO", sizes=_ICO_SIZES)
        return True
    except Exception:
        return False


def set_window_icon(window, path: str | None = None) -> None:
    """Sets the title-bar/taskbar icon for `window` (any tk.Tk/ctk.CTk
    root), from the given logo .png (defaults to assets/logo.png; a
    relative path is resolved against the project root). On Windows this
    generates/reuses a matching .ico and applies it via iconbitmap() —
    the mechanism that actually controls that corner icon — and also
    calls iconphoto() for other platforms/contexts. Safe no-op if the
    resolved file doesn't exist, rather than crashing app startup over a
    cosmetic asset."""
    png_path = _resolve(path, LOGO_PATH)
    if not os.path.exists(png_path):
        return

    if sys.platform == "win32":
        ico_path = os.path.join(os.path.dirname(png_path), os.path.splitext(os.path.basename(png_path))[0] + ".ico")
        try:
            if _ensure_ico(png_path, ico_path):
                window.iconbitmap(default=ico_path)
        except Exception:
            pass

    try:
        icon_image = tk.PhotoImage(file=png_path)
        window.iconphoto(True, icon_image)
        # Tk only keeps a weak reference to the PhotoImage internally —
        # without holding our own reference here, Python's GC can collect
        # it and the icon silently reverts to blank.
        window._branding_icon_ref = icon_image
    except Exception:
        pass


def load_logo_ctkimage(height: int = 32):
    """A CTkImage of the logo scaled to `height` px tall (aspect-ratio
    preserved), for display in a header/toolbar. Returns None if the
    logo asset is missing, so a caller can skip showing it gracefully."""
    if not os.path.exists(LOGO_PATH):
        return None
    img = Image.open(LOGO_PATH)
    w, h = img.size
    width = int(w * (height / h))
    return ctk.CTkImage(light_image=img, dark_image=img, size=(width, height))
