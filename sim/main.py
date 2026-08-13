"""Standalone Pygame launcher for the Code Battleship arena.

This is also the "managed child window" fallback used by the CustomTkinter
dashboard (ui/battle_panel.py) when embedding pygame directly into the Tk
window isn't available on the current platform — see ui/battle_panel.py
for the embedding attempt and its fallback to spawning this file.

Controls:
  S — start / resume
  P — pause
  R — reset
  Esc / close window — quit

Run from the project root:
  python -m sim.main
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from engine.battle import BattleEngine
from engine.runner import BattleRunner
from sim.renderer import ArenaRenderer

BG = (20, 28, 37)
PANEL = (25, 36, 60)
TEXT = (232, 232, 234)
TEXT_DIM = (155, 166, 194)
TEXT_FAINT = (110, 121, 150)
ACCENT_GLOW = (52, 148, 235)
SUCCESS = (63, 203, 134)
DANGER = (224, 101, 74)
ORANGE = (226, 138, 61)

WINDOW_W, WINDOW_H = 1280, 720
ARENA_RECT = pygame.Rect(20, 20, 860, 640)
LOG_RECT = pygame.Rect(900, 20, 360, 500)
HUD_RECT = pygame.Rect(900, 540, 360, 120)

FPS = 60


def wrap_text(text, font, max_width):
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if font.size(trial)[0] <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def main():
    pygame.init()
    pygame.display.set_caption("Code Battleship - Battle Arena")
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    clock = pygame.time.Clock()

    font_ui = pygame.font.SysFont("Segoe UI", 16, bold=True)
    font_body = pygame.font.SysFont("Segoe UI", 14)
    font_mono = pygame.font.SysFont("Consolas", 13)
    font_small = pygame.font.SysFont("Segoe UI", 12)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "teams", "team_alpha.py"), encoding="utf-8") as f:
        team_a_code = f.read()
    with open(os.path.join(root, "teams", "team_beta.py"), encoding="utf-8") as f:
        team_b_code = f.read()

    engine = BattleEngine(team_a_code, team_b_code)
    runner = BattleRunner(engine, tick_hz=30)
    runner.start_thread()

    arena = ArenaRenderer(ARENA_RECT)

    running = True
    log_lines: list[str] = []
    while running:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_s:
                    runner.start_battle()
                elif event.key == pygame.K_p:
                    runner.pause_battle()
                elif event.key == pygame.K_r:
                    runner.reset_battle()

        snap = runner.snapshot()
        log_lines = snap["log_tail"]

        screen.fill(BG)

        # ---- arena panel ----
        pygame.draw.rect(screen, (15, 21, 30), ARENA_RECT, border_radius=8)
        arena.draw(screen, snap, font_small=font_small)
        pygame.draw.rect(screen, (232, 232, 234, 60), ARENA_RECT, width=1, border_radius=8)

        title = font_ui.render("BATTLE ARENA", True, TEXT)
        screen.blit(title, (ARENA_RECT.x, ARENA_RECT.y - 24))

        status_text = (
            f"WINNER: {snap['winner']}" if snap["winner"]
            else ("RUNNING" if snap["running"] else "PAUSED")
        )
        status_color = SUCCESS if snap["winner"] else (ACCENT_GLOW if snap["running"] else TEXT_FAINT)
        status = font_body.render(status_text, True, status_color)
        screen.blit(status, (ARENA_RECT.right - status.get_width(), ARENA_RECT.y - 24))

        # ---- HUD (team panel) ----
        pygame.draw.rect(screen, PANEL, HUD_RECT, border_radius=8)
        pygame.draw.rect(screen, (232, 232, 234, 30), HUD_RECT, width=1, border_radius=8)
        for i, (key, ship) in enumerate((("alpha", snap["ship_a"]), ("beta", snap["ship_b"]))):
            cx = HUD_RECT.x + 16 + i * (HUD_RECT.width // 2)
            name_color = ACCENT_GLOW if key == "alpha" else ORANGE
            name = font_ui.render(ship["team"], True, name_color)
            screen.blit(name, (cx, HUD_RECT.y + 10))
            hp = font_small.render(f"HP {ship['hp']:.0f}%   ENERGY {ship['energy']:.0f}%", True, TEXT_DIM)
            screen.blit(hp, (cx, HUD_RECT.y + 34))
            act = font_small.render(f"alive: {ship['alive']}", True, TEXT_FAINT)
            screen.blit(act, (cx, HUD_RECT.y + 54))

        controls = font_small.render("S start   P pause   R reset   Esc quit", True, TEXT_FAINT)
        screen.blit(controls, (HUD_RECT.x + 16, HUD_RECT.bottom - 24))

        # ---- log panel ----
        pygame.draw.rect(screen, PANEL, LOG_RECT, border_radius=8)
        pygame.draw.rect(screen, (232, 232, 234, 30), LOG_RECT, width=1, border_radius=8)
        log_title = font_ui.render("BATTLE LOG", True, TEXT)
        screen.blit(log_title, (LOG_RECT.x + 14, LOG_RECT.y + 10))

        y = LOG_RECT.y + 38
        max_w = LOG_RECT.width - 28
        for line in log_lines[-14:]:
            for wrapped in wrap_text(line, font_mono, max_w):
                if y > LOG_RECT.bottom - 20:
                    break
                color = DANGER if "HP -" in wrapped or "error" in wrapped else TEXT_DIM
                surf = font_mono.render(wrapped, True, color)
                screen.blit(surf, (LOG_RECT.x + 14, y))
                y += 17

        pygame.display.flip()

    runner.stop_thread()
    pygame.quit()


if __name__ == "__main__":
    main()
