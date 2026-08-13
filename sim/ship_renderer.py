"""Realistic top-down military-vessel rendering.

Ship geometry is baked once per (team, damage-tier) into a cached
pygame.Surface (`_surface_cache`) and reused every frame — only rotation +
blit happens per frame, plus a few cheap dynamic overlays (sparks, smoke,
turret aim, sensor sweep) drawn on top. This keeps per-frame cost low even
though the hull itself has real detail (hull plating, bridge, mast,
turrets, missile hatches, nav lights).

This module is purely visual. It reads a ship snapshot (from
engine/ship.py's Ship.snapshot()) and draws it — it never mutates battle
state. HP/energy/position/heading rules live in engine/ship.py and are
untouched here.
"""

import math
import random

import pygame

# ---- canvas the hull is baked onto, before rotation ----
CANVAS = 200
HULL_LEN = 132
HULL_WID = 40

TEAM_COLORS = {
    "alpha": {
        "hull": (46, 54, 70),
        "hull_light": (58, 68, 88),
        "trim": (52, 148, 235),   # secondary blue / active glow
        "trim2": (70, 99, 222),   # primary accent
    },
    "beta": {
        "hull": (58, 61, 68),
        "hull_light": (72, 76, 84),
        "trim": (226, 138, 61),   # orange identification
        "trim2": (150, 110, 70),
    },
}

WINDOW_COLOR = (14, 18, 24)
METAL = (110, 116, 128)
DARK_METAL = (34, 38, 46)

_surface_cache: dict[tuple, pygame.Surface] = {}


def _hull_polygon():
    """Bow-right silhouette: pointed bow, wide midship, flat stern."""
    L, W = HULL_LEN, HULL_WID
    hw = W / 2
    return [
        (L / 2, 0),                    # bow tip
        (L / 2 - 20, -hw * 0.62),
        (L * 0.12, -hw),
        (-L / 2 + 10, -hw * 0.92),
        (-L / 2, -hw * 0.55),
        (-L / 2, hw * 0.55),
        (-L / 2 + 10, hw * 0.92),
        (L * 0.12, hw),
        (L / 2 - 20, hw * 0.62),
    ]


def _build_ship_surface(team_key: str, tier: int) -> pygame.Surface:
    colors = TEAM_COLORS[team_key]
    surf = pygame.Surface((CANVAS, CANVAS), pygame.SRCALPHA)
    cx, cy = CANVAS / 2, CANVAS / 2

    def pt(p):
        return (cx + p[0], cy + p[1])

    hull_pts = [pt(p) for p in _hull_polygon()]

    # hull base + light gradient by drawing two overlapping polygons
    pygame.draw.polygon(surf, colors["hull"], hull_pts)
    inset = [pt((p[0] * 0.94, p[1] * 0.8)) for p in _hull_polygon()]
    pygame.draw.polygon(surf, colors["hull_light"], inset)
    pygame.draw.polygon(surf, (10, 12, 16), hull_pts, width=2)

    # panel seams
    for frac in (-0.3, -0.1, 0.1, 0.3):
        y = cy + frac * HULL_WID
        pygame.draw.line(
            surf, (0, 0, 0, 70),
            (cx - HULL_LEN / 2 + 14, y), (cx + HULL_LEN / 2 - 22, y), 1,
        )

    # bow identification trim (thin colored strip near the bow, not the whole hull)
    trim_pts = [pt(p) for p in [
        (HULL_LEN / 2 - 4, 0), (HULL_LEN / 2 - 24, -HULL_WID * 0.5),
        (HULL_LEN / 2 - 30, -HULL_WID * 0.42), (HULL_LEN / 2 - 10, 0),
        (HULL_LEN / 2 - 30, HULL_WID * 0.42), (HULL_LEN / 2 - 24, HULL_WID * 0.5),
    ]]
    pygame.draw.polygon(surf, colors["trim"], trim_pts, width=2)

    # navigation lights (naval convention: red = port/left, green = starboard/right)
    pygame.draw.circle(surf, (210, 60, 60), pt((HULL_LEN * 0.2, -HULL_WID * 0.46)), 2)
    pygame.draw.circle(surf, (70, 200, 110), pt((HULL_LEN * 0.2, HULL_WID * 0.46)), 2)

    # command bridge (raised deck structure, ~35% back from bow)
    bridge_w, bridge_h = 26, 20
    bridge_x = cx + HULL_LEN * 0.06
    bridge_rect = pygame.Rect(0, 0, bridge_w, bridge_h)
    bridge_rect.center = (bridge_x, cy)
    pygame.draw.rect(surf, colors["hull_light"], bridge_rect, border_radius=3)
    pygame.draw.rect(surf, (12, 14, 18), bridge_rect, width=1, border_radius=3)
    window = pygame.Rect(0, 0, bridge_w - 8, 4)
    window.center = (bridge_x, cy - 4)
    pygame.draw.rect(surf, WINDOW_COLOR, window, border_radius=1)
    # bridge ID light
    pygame.draw.circle(surf, colors["trim"], (int(bridge_x), int(cy + 8)), 2)

    # sensor mast (behind bridge)
    mast_x = bridge_x - 4
    pygame.draw.line(surf, METAL, (mast_x, cy), (mast_x, cy - 14), 2)
    pygame.draw.circle(surf, DARK_METAL, (int(mast_x), int(cy - 16)), 4)
    pygame.draw.circle(surf, colors["trim"], (int(mast_x), int(cy - 16)), 1)

    # main turret base near bow (barrel drawn dynamically so it can aim independently)
    turret_x = cx + HULL_LEN * 0.28
    pygame.draw.circle(surf, DARK_METAL, (int(turret_x), int(cy)), 8)
    pygame.draw.circle(surf, METAL, (int(turret_x), int(cy)), 8, width=1)

    # secondary turret near stern
    sec_x = cx - HULL_LEN * 0.3
    pygame.draw.circle(surf, DARK_METAL, (int(sec_x), int(cy)), 5)
    pygame.draw.circle(surf, METAL, (int(sec_x), int(cy)), 5, width=1)

    # missile hatch covers (small rectangles along the deck)
    for i in range(3):
        hx = cx - HULL_LEN * 0.02 + i * 12
        hatch = pygame.Rect(0, 0, 8, 5)
        hatch.center = (hx, cy - HULL_WID * 0.28)
        pygame.draw.rect(surf, DARK_METAL, hatch, border_radius=1)
        pygame.draw.rect(surf, METAL, hatch, width=1, border_radius=1)

    # propulsion vents at stern
    for oy in (-8, 0, 8):
        pygame.draw.circle(surf, (16, 18, 22), (int(cx - HULL_LEN / 2 + 6), int(cy + oy)), 3)

    # ---- damage baked into the hull (structural, not animated) ----
    if tier >= 1:
        scorch = pygame.Rect(0, 0, 22, 14)
        scorch.center = pt((HULL_LEN * 0.18, HULL_WID * 0.15))
        pygame.draw.ellipse(surf, (0, 0, 0, 90), scorch)
    if tier >= 2:
        scorch2 = pygame.Rect(0, 0, 28, 16)
        scorch2.center = pt((-HULL_LEN * 0.12, -HULL_WID * 0.1))
        pygame.draw.ellipse(surf, (0, 0, 0, 110), scorch2)
        # a missing/broken hatch
        pygame.draw.rect(surf, (0, 0, 0, 130), pygame.Rect(bridge_rect.right - 4, bridge_rect.top, 6, 6))
    if tier >= 3:
        pygame.draw.polygon(
            surf, (0, 0, 0, 140),
            [pt((HULL_LEN * 0.32, -HULL_WID * 0.1)), pt((HULL_LEN * 0.4, -HULL_WID * 0.35)),
             pt((HULL_LEN * 0.22, -HULL_WID * 0.3))],
        )
        # bent mast
        pygame.draw.line(surf, (0, 0, 0, 160), (mast_x, cy - 6), (mast_x + 5, cy - 15), 2)
    if tier >= 4:
        # destroyed hulk: desaturated, heavy scorching, dark
        dark_overlay = pygame.Surface((CANVAS, CANVAS), pygame.SRCALPHA)
        dark_overlay.fill((5, 5, 8, 130))
        surf.blit(dark_overlay, (0, 0))
        for _ in range(6):
            rx = cx + random.uniform(-HULL_LEN / 2, HULL_LEN / 2)
            ry = cy + random.uniform(-HULL_WID / 2, HULL_WID / 2)
            pygame.draw.circle(surf, (0, 0, 0, 160), (int(rx), int(ry)), random.randint(3, 6))

    return surf


def _tier_for(hp_pct: float) -> int:
    if hp_pct >= 0.9:
        return 0
    if hp_pct >= 0.65:
        return 1
    if hp_pct >= 0.35:
        return 2
    if hp_pct > 0.0:
        return 3
    return 4


def get_ship_surface(team_key: str, hp_pct: float) -> pygame.Surface:
    tier = _tier_for(hp_pct)
    key = (team_key, tier)
    if key not in _surface_cache:
        # tier 4 bakes in randomness (debris scatter) — cache once, don't
        # regenerate every frame, so it stays visually stable while dead.
        random.seed(hash(team_key) & 0xFFFF)
        _surface_cache[key] = _build_ship_surface(team_key, tier)
    return _surface_cache[key]


def draw_ship(dest, screen_x, screen_y, heading, team_key, hp_pct, t,
              aim_angle=None, scale=1.0):
    """Draws one ship at (screen_x, screen_y), hull rotated to `heading`
    (radians, 0 = +x/east). `aim_angle` optionally points the main turret
    barrel independently of the hull, matching how real turreted vessels
    track a target while the hull is moving on a different course."""
    base = get_ship_surface(team_key, hp_pct)
    deg = -math.degrees(heading)
    rotated = pygame.transform.rotozoom(base, deg, scale)
    rect = rotated.get_rect(center=(screen_x, screen_y))
    dest.blit(rotated, rect)

    tier = _tier_for(hp_pct)
    colors = TEAM_COLORS[team_key]

    # sensor sweep — a faint rotating line off the mast, always active
    sweep_r = 15 * scale
    sweep_angle = (t * 1.6) % (2 * math.pi)
    sx = screen_x + math.cos(sweep_angle) * sweep_r
    sy = screen_y + math.sin(sweep_angle) * sweep_r
    pygame.draw.line(dest, colors["trim"], (screen_x, screen_y), (sx, sy), 1)

    # turret barrel — dynamically aimed, independent of hull rotation
    turret_offset = 8 * scale
    tx = screen_x + math.cos(heading) * turret_offset
    ty = screen_y + math.sin(heading) * turret_offset
    barrel_angle = aim_angle if aim_angle is not None else heading
    bx = tx + math.cos(barrel_angle) * 10 * scale
    by = ty + math.sin(barrel_angle) * 10 * scale
    pygame.draw.line(dest, METAL, (tx, ty), (bx, by), 2)

    if hp_pct <= 0:
        return  # destroyed hulks don't spark/smoke, they're just wreckage

    # dynamic sparks (tier 1+)
    if tier >= 1:
        n_sparks = tier
        for i in range(n_sparks):
            phase = (t * 7 + i * 2.3) % 1.0
            if phase < 0.15:
                ox = math.sin(i * 12.9) * HULL_LEN * 0.25 * scale
                oy = math.cos(i * 7.3) * HULL_WID * 0.3 * scale
                pygame.draw.circle(
                    dest, (255, 220, 140),
                    (int(screen_x + ox), int(screen_y + oy)), 2,
                )

    # drifting smoke (tier 2+)
    if tier >= 2:
        smoke_alpha = min(140, 40 * tier)
        for i in range(tier - 1):
            drift = (t * 10 + i * 3.7) % 20
            ox = -math.cos(heading) * HULL_LEN * 0.15 * scale
            oy = -math.sin(heading) * HULL_LEN * 0.15 * scale - drift
            smoke = pygame.Surface((16, 16), pygame.SRCALPHA)
            pygame.draw.circle(smoke, (90, 90, 96, max(0, smoke_alpha - int(drift * 4))), (8, 8), 6)
            dest.blit(smoke, (screen_x + ox - 8, screen_y + oy - 8))
