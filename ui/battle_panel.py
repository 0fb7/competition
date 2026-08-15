"""Battle Arena panel: tries to embed the real Pygame renderer directly
inside the CustomTkinter window using the SDL_WINDOWID technique (SDL
attaches its output to an existing native window handle instead of
creating its own). This is a genuine, commonly-used embedding technique
on Windows, but it is not guaranteed by SDL/pygame and behaves
inconsistently across platforms/drivers — so if it fails for any reason
we fall back to the "managed child window" the spec explicitly allows:
a button that launches sim/main.py as its own process.

Important: the fallback child window runs its OWN BattleEngine/
BattleRunner — it is a separate battle, not a mirror of the dashboard's.
It exists so the user still has a way to watch a battle if embedding is
unavailable on their machine, not as a second view of the same state.
"""

import os
import subprocess
import sys

import customtkinter as ctk
import tkinter as tk

from . import theme
from .localization import t

try:
    import pygame
    from sim.renderer import ArenaRenderer
    _PYGAME_OK = True
except Exception:
    _PYGAME_OK = False


class BattlePanel(ctk.CTkFrame):
    def __init__(self, master, tokens: theme.Tokens, runner, width=820, height=560):
        super().__init__(master, fg_color=tokens.panel, corner_radius=10)
        self.tokens = tokens
        self.runner = runner
        self.canvas_w = width
        self.canvas_h = height
        self.embedded = False
        self.last_fps = None
        self._child_proc = None
        self._pg_screen = None
        self._pg_clock = None
        self._arena_renderer = None
        self._render_job = None
        self._embed_retry_job = None
        self._font_small = None
        self._shutting_down = False
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 4))
        self.header = ctk.CTkLabel(head, text=t("battle_arena"), font=theme.font(12, "bold"), text_color=self.tokens.text)
        self.header.pack(side="left")

        self.fallback_btn = ctk.CTkButton(
            head, text=t("open_arena_window"), width=150, height=24, font=theme.font(10),
            fg_color=self.tokens.panel_2, hover_color=self.tokens.border, command=self._open_child_window,
        )
        # only shown once embedding is confirmed unavailable

        self.embed_holder = tk.Frame(self, width=self.canvas_w, height=self.canvas_h, bg="#0F151E", highlightthickness=0)
        self.embed_holder.pack(padx=10, pady=(0, 10))
        self.embed_holder.pack_propagate(False)

        self.status_label = ctk.CTkLabel(
            self.embed_holder, text="", font=theme.font(11), text_color=self.tokens.text_faint,
        )

        if not _PYGAME_OK:
            self.status_label.configure(text="pygame-ce not available")
            self.status_label.place(relx=0.5, rely=0.5, anchor="center")
            self._show_fallback_button()
            return

        self._embed_attempts = 0
        self._embed_retry_job = self.after(150, self._try_embed)

    def _show_fallback_button(self):
        self.fallback_btn.pack(side="right")

    def _try_embed(self):
        self._embed_retry_job = None
        if self._shutting_down:
            return
        self.embed_holder.update_idletasks()
        w, h = self.embed_holder.winfo_width(), self.embed_holder.winfo_height()
        if (w <= 1 or h <= 1) and self._embed_attempts < 20:
            # window manager hasn't given the holder real screen geometry
            # yet (e.g. right at startup, before the toplevel is mapped) —
            # retry briefly instead of giving up and hiding the arena.
            self._embed_attempts += 1
            self._embed_retry_job = self.after(150, self._try_embed)
            return
        try:
            wid = self.embed_holder.winfo_id()
            if not wid:
                raise RuntimeError("no native window id available yet")

            os.environ["SDL_WINDOWID"] = str(wid)
            if sys.platform == "win32":
                os.environ.pop("SDL_VIDEODRIVER", None)  # let SDL pick the native Windows driver

            if not pygame.get_init():
                pygame.init()
            else:
                pygame.display.quit()
            self._pg_screen = pygame.display.set_mode((self.canvas_w, self.canvas_h))
            actual_w, actual_h = self._pg_screen.get_size()  # OS may not honor the exact request
            self._pg_clock = pygame.time.Clock()
            self._font_small = pygame.font.SysFont("Segoe UI", 12)
            self._arena_renderer = ArenaRenderer(pygame.Rect(0, 0, actual_w, actual_h))
            self.embedded = True
            self._render_frame()
        except Exception as e:
            self.embedded = False
            self.status_label.configure(
                text=f"{t('open_arena_window')}\n({type(e).__name__})",
            )
            self.status_label.place(relx=0.5, rely=0.5, anchor="center")
            self._show_fallback_button()

    def _render_frame(self):
        if self._shutting_down or not self.embedded or self._pg_screen is None:
            return
        try:
            # Phase 7: snapshot_for_render(), never snapshot() — this
            # runs on its own ~60fps after() loop, independent of
            # ui/app.py's _tick(); sharing the draining snapshot() here
            # was a real, pre-existing event-stealing race (see
            # BattleRunner.snapshot_for_render()'s docstring).
            snap = self.runner.snapshot_for_render()
            self._pg_screen.fill((20, 28, 37))
            self._arena_renderer.draw(self._pg_screen, snap, font_small=self._font_small)
            pygame.display.flip()
            self._pg_clock.tick(60)
            self.last_fps = self._pg_clock.get_fps()
        except Exception:
            self.embedded = False
            return
        self._render_job = self.after(16, self._render_frame)

    def _open_child_window(self):
        if self._child_proc and self._child_proc.poll() is None:
            return
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._child_proc = subprocess.Popen([sys.executable, "-m", "sim.main"], cwd=root)

    def apply_language(self):
        self.header.configure(text=t("battle_arena"))
        self.fallback_btn.configure(text=t("open_arena_window"))

    def shutdown(self):
        self._shutting_down = True
        if self._render_job:
            self.after_cancel(self._render_job)
            self._render_job = None
        if self._embed_retry_job:
            self.after_cancel(self._embed_retry_job)
            self._embed_retry_job = None
        if self.embedded:
            try:
                pygame.display.quit()
            except Exception:
                pass
            self.embedded = False
        if self._child_proc and self._child_proc.poll() is None:
            self._child_proc.terminate()
