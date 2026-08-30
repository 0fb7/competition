"""Arena rendering: grid, tactical zones, trajectories, and event-driven
projectile/explosion animations layered on top of sim/ship_renderer.py.

This module only reads state — a snapshot dict from engine/runner.py's
BattleRunner.snapshot() (or, for the standalone launcher, an engine
directly) — and draws. It never mutates battle state. The engine's
ATTACK/DAMAGE/DESTROYED events (engine/events.py) drive short playback
animations here (projectile travel, explosion flash) so the *visual*
timing can feel weighty even though the engine resolves combat instantly
on the tick it happens.
"""

import math
import time

import pygame

from . import ship_renderer as sr
from engine import events as ev
from engine.ship import ARENA_WIDTH, ARENA_HEIGHT, ATTACK_RANGE as _DEFAULT_ATTACK_RANGE

BG_TOP = (19, 27, 39)
BG_BOTTOM = (11, 16, 23)
GRID_ALPHA = 16
ZONE_ALPHA = 14
BORDER = (232, 232, 234, 60)

PROJECTILE_DURATION = 0.22
EXPLOSION_DURATION = 0.55

TEAM_KEY = {"Team Alpha": "alpha", "Team Beta": "beta"}


class ArenaRenderer:
    def __init__(self, rect: pygame.Rect):
        self.rect = rect
        self._bg_cache = None
        self._projectiles = []   # list of dict(start, from, to, team)
        self._explosions = []    # list of dict(start, pos, team)
        self._seen_event_ids = set()

    def resize(self, rect: pygame.Rect):
        self.rect = rect
        self._bg_cache = None

    def world_to_screen(self, x, y):
        sx = self.rect.x + (x / ARENA_WIDTH) * self.rect.width
        sy = self.rect.y + (y / ARENA_HEIGHT) * self.rect.height
        return sx, sy

    def _build_background(self):
        surf = pygame.Surface(self.rect.size)
        for y in range(self.rect.height):
            frac = y / max(1, self.rect.height)
            color = tuple(
                int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * frac) for i in range(3)
            )
            pygame.draw.line(surf, color, (0, y), (self.rect.width, y))

        cols, rows = 16, 9
        for i in range(1, cols):
            x = i * self.rect.width / cols
            line = pygame.Surface((1, self.rect.height), pygame.SRCALPHA)
            line.fill((255, 255, 255, GRID_ALPHA))
            surf.blit(line, (x, 0))
        for j in range(1, rows):
            y = j * self.rect.height / rows
            line = pygame.Surface((self.rect.width, 1), pygame.SRCALPHA)
            line.fill((255, 255, 255, GRID_ALPHA))
            surf.blit(line, (0, y))

        zone = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        zone.fill((226, 138, 61, ZONE_ALPHA))
        surf.blit(zone, (self.rect.width * 0.62, 0), pygame.Rect(0, 0, self.rect.width * 0.38, self.rect.height * 0.55))
        zone2 = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        zone2.fill((70, 99, 222, ZONE_ALPHA))
        surf.blit(zone2, (0, self.rect.height * 0.5), pygame.Rect(0, 0, self.rect.width * 0.42, self.rect.height * 0.5))

        self._bg_cache = surf

    def _ingest_events(self, new_events, ship_a_pos, ship_b_pos, team_a_name, team_b_name):
        # Real competition matches use whatever names the admin gave the
        # teams (e.g. "Team A"/"Team B"), not always the default "Team
        # Alpha"/"Team Beta" — this must key off the actual snapshot names,
        # never hardcoded literals, or an evt.team lookup below raises
        # KeyError and (since draw() is called from battle_panel.py's
        # try/except-and-stop-rendering loop) silently kills the arena's
        # render loop the instant the first real attack/damage event fires.
        pos_by_team = {team_a_name: ship_a_pos, team_b_name: ship_b_pos}
        now = time.perf_counter()
        for evt in new_events:
            if evt.id in self._seen_event_ids:
                continue
            self._seen_event_ids.add(evt.id)
            if evt.team not in pos_by_team:
                continue
            opponent_team = team_b_name if evt.team == team_a_name else team_a_name
            if evt.kind == ev.ATTACK:
                self._projectiles.append({
                    "start": now, "team": evt.team,
                    "from": pos_by_team[evt.team], "to": pos_by_team[opponent_team],
                })
            elif evt.kind == ev.DAMAGE:
                self._explosions.append({
                    "start": now, "pos": pos_by_team[opponent_team], "team": evt.team,
                })

    def draw(self, dest: pygame.Surface, snapshot: dict, font_small=None):
        if self._bg_cache is None or self._bg_cache.get_size() != self.rect.size:
            self._build_background()
        dest.blit(self._bg_cache, self.rect.topleft)

        a, b = snapshot["ship_a"], snapshot["ship_b"]
        pos_a = self.world_to_screen(a["x"], a["y"])
        pos_b = self.world_to_screen(b["x"], b["y"])

        self._ingest_events(snapshot.get("new_events", []), pos_a, pos_b, a["team"], b["team"])

        # Challenges (Phase 2) can configure a different attack_range than
        # the engine default — read the live value off the snapshot so the
        # crosshair/trajectory always matches actual engine behavior
        # instead of a stale hardcoded import.
        attack_range = snapshot.get("attack_range", _DEFAULT_ATTACK_RANGE)
        dist = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
        in_range = dist <= attack_range and a["alive"] and b["alive"]
        if in_range:
            pygame.draw.line(dest, (232, 232, 234, 50), pos_a, pos_b, 1)
            self._crosshair(dest, pos_b, (224, 101, 74))

        t = time.perf_counter()
        aim_a = math.atan2(pos_b[1] - pos_a[1], pos_b[0] - pos_a[0]) if in_range else None
        aim_b = math.atan2(pos_a[1] - pos_b[1], pos_a[0] - pos_b[0]) if in_range else None

        sr.draw_ship(dest, *pos_a, a["heading"], "alpha", a["hp_pct"], t, aim_angle=aim_a)
        sr.draw_ship(dest, *pos_b, b["heading"], "beta", b["hp_pct"], t, aim_angle=aim_b)

        self._draw_projectiles(dest, t)
        self._draw_explosions(dest, t)

        if font_small:
            self._draw_status(dest, font_small, pos_a, a, "alpha")
            self._draw_status(dest, font_small, pos_b, b, "beta")

    def _crosshair(self, dest, pos, color):
        x, y = pos
        r = 11
        pygame.draw.line(dest, color, (x - r, y), (x - r * 0.35, y), 1)
        pygame.draw.line(dest, color, (x + r * 0.35, y), (x + r, y), 1)
        pygame.draw.line(dest, color, (x, y - r), (x, y - r * 0.35), 1)
        pygame.draw.line(dest, color, (x, y + r * 0.35), (x, y + r), 1)
        pygame.draw.circle(dest, color, (int(x), int(y)), r, width=1)

    def _draw_projectiles(self, dest, now):
        alive = []
        for p in self._projectiles:
            progress = (now - p["start"]) / PROJECTILE_DURATION
            if progress >= 1.0:
                continue
            fx, fy = p["from"]
            tx, ty = p["to"]
            x = fx + (tx - fx) * progress
            y = fy + (ty - fy) * progress
            glow = pygame.Surface((16, 16), pygame.SRCALPHA)
            pygame.draw.circle(glow, (255, 255, 255, 220), (8, 8), 5)
            pygame.draw.circle(glow, (52, 148, 235, 90), (8, 8), 8)
            dest.blit(glow, (x - 8, y - 8))
            alive.append(p)
        self._projectiles = alive

    def _draw_explosions(self, dest, now):
        alive = []
        for e in self._explosions:
            progress = (now - e["start"]) / EXPLOSION_DURATION
            if progress >= 1.0:
                continue
            x, y = e["pos"]
            radius = 6 + progress * 20
            alpha = int(200 * (1 - progress))
            burst = pygame.Surface((60, 60), pygame.SRCALPHA)
            pygame.draw.circle(burst, (255, 200, 120, alpha), (30, 30), int(radius))
            pygame.draw.circle(burst, (226, 138, 61, alpha), (30, 30), int(radius * 0.6))
            dest.blit(burst, (x - 30, y - 30))
            alive.append(e)
        self._explosions = alive

    # Fixed by requirement: Health is always green, Energy is always blue —
    # no tiered/warning colors. Distinctness between the two bars (not
    # ship condition) is what the color is communicating here.
    HP_BAR_COLOR = (46, 204, 113)
    ENERGY_BAR_COLOR = (52, 148, 235)

    def _draw_bar(self, dest, font, cx, top_y, pct, fill_color, label_char):
        """One labeled status bar (HP or Energy), centered on cx, growing
        left-to-right from empty (0%) to full (100%) — always drawn at a
        fixed track size so a participant can compare HP vs Energy at a
        glance, not just read a number. Sized to be prominent, not a
        small/subtle readout."""
        pct = max(0.0, min(1.0, pct))
        bar_w, bar_h = 64, 9
        track = pygame.Rect(0, 0, bar_w, bar_h)
        track.midtop = (cx, top_y)
        pygame.draw.rect(dest, (10, 14, 20), track, border_radius=3)
        if pct > 0:
            fill = pygame.Rect(track.left, track.top, max(3, int(bar_w * pct)), bar_h)
            pygame.draw.rect(dest, fill_color, fill, border_radius=3)
        pygame.draw.rect(dest, (232, 232, 234, 140), track, width=1, border_radius=3)

        label_surf = font.render(f"{label_char} {int(round(pct * 100))}%", True, (232, 232, 234))
        dest.blit(label_surf, (track.right + 6, track.top - 2))

    def _draw_status(self, dest, font, pos, ship, team_key):
        """Ship name plus distinct HP and Energy bars, always visible
        above the ship — this is the participant's primary at-a-glance
        readout of their ship's condition during a live battle."""
        name_color = (159, 180, 255) if team_key == "alpha" else (240, 185, 138)
        x, y = pos
        name_surf = font.render(ship["name"], True, name_color)
        name_y = y - 62
        dest.blit(name_surf, (x - name_surf.get_width() / 2, name_y))

        hp_y = name_y + name_surf.get_height() + 4
        self._draw_bar(dest, font, x, hp_y, ship["hp_pct"], self.HP_BAR_COLOR, "HP")

        energy_y = hp_y + 12
        self._draw_bar(dest, font, x, energy_y, ship.get("energy_pct", 0.0), self.ENERGY_BAR_COLOR, "EN")
