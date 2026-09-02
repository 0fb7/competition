"""Regression test for the Battle Arena rendering bug found during manual
QA: ArenaRenderer._ingest_events() used to hardcode "Team Alpha"/"Team
Beta" as the only recognized team names. Any real Competition match using
different team names (e.g. "Team A"/"Team B") produced a KeyError the
instant the first ATTACK/DAMAGE event fired, which battle_panel.py's
render loop silently swallows and never recovers from — freezing the
Battle Arena panel with no error shown anywhere.

Run with:

    python tests/test_renderer.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from engine import events as ev
from sim.renderer import ArenaRenderer, PROJECTILE_DURATION, EXPLOSION_DURATION


def _ship(team: str, name: str, x: float, y: float) -> dict:
    return {
        "id": team, "team": team, "name": name, "x": x, "y": y, "heading": 0.0,
        "hp": 100.0, "hp_pct": 1.0, "energy": 100.0, "energy_pct": 1.0,
        "alive": True, "attack_ready": True, "attack_cooldown": 0.0,
    }


def _snapshot(team_a_name: str, team_b_name: str, new_events: list) -> dict:
    return {
        "ship_a": _ship(team_a_name, "Ship A", 10.0, 10.0),
        "ship_b": _ship(team_b_name, "Ship B", 20.0, 20.0),
        "new_events": new_events,
        "attack_range": 15.0,
    }


def test_draw_survives_custom_team_names_through_attack_and_damage():
    """The exact reproduction: custom team names ("Team A"/"Team B", not
    the defaults) with a real ATTACK then DAMAGE event, exactly as a real
    Competition match's event log looks. Before the fix this raised
    KeyError inside _ingest_events()."""
    renderer = ArenaRenderer(pygame.Rect(0, 0, 400, 300))
    surface = pygame.Surface((400, 300))

    attack_evt = ev.Event(id=1, kind=ev.ATTACK, team="Team A", message="Attack successful")
    damage_evt = ev.Event(id=2, kind=ev.DAMAGE, team="Team A", message="Team B HP -12", data={"amount": 12.0})

    renderer.draw(surface, _snapshot("Team A", "Team B", [attack_evt, damage_evt]))
    # a second frame with no new events must also not raise (steady-state
    # rendering after the event that used to crash it)
    renderer.draw(surface, _snapshot("Team A", "Team B", []))


def test_draw_still_works_with_default_team_names():
    """Regression guard: the fix must not break the original default-name
    case the renderer was originally built around."""
    renderer = ArenaRenderer(pygame.Rect(0, 0, 400, 300))
    surface = pygame.Surface((400, 300))

    attack_evt = ev.Event(id=1, kind=ev.ATTACK, team="Team Alpha", message="Attack successful")
    damage_evt = ev.Event(id=2, kind=ev.DAMAGE, team="Team Alpha", message="Team Beta HP -12", data={"amount": 12.0})

    renderer.draw(surface, _snapshot("Team Alpha", "Team Beta", [attack_evt, damage_evt]))


def test_draw_ignores_event_from_unrecognized_team_defensively():
    """Belt-and-suspenders: an event whose team matches neither ship (e.g.
    a stale event from a previous, differently-named battle reused against
    a fresh renderer) must be skipped, not raise."""
    renderer = ArenaRenderer(pygame.Rect(0, 0, 400, 300))
    surface = pygame.Surface((400, 300))

    stray_evt = ev.Event(id=1, kind=ev.ATTACK, team="Some Other Team", message="Attack successful")
    renderer.draw(surface, _snapshot("Team A", "Team B", [stray_evt]))


def test_draw_renders_hp_and_energy_bars_without_error():
    """Practice Console request: distinct HP and Energy bars must render
    above each ship whenever a font is supplied — this is the code path
    that was previously untested (existing tests never passed font_small,
    so the old/new per-ship label code never actually ran)."""
    pygame.font.init()
    font = pygame.font.SysFont("Segoe UI", 12)
    renderer = ArenaRenderer(pygame.Rect(0, 0, 400, 300))
    surface = pygame.Surface((400, 300))

    snap = _snapshot("Team A", "Team B", [])
    snap["ship_a"]["hp_pct"] = 0.8
    snap["ship_a"]["energy_pct"] = 0.4
    snap["ship_b"]["hp_pct"] = 0.15  # exercises the "critical" HP bar color branch
    snap["ship_b"]["energy_pct"] = 0.0  # exercises the empty-bar branch

    renderer.draw(surface, snap, font_small=font)


def test_advance_clock_freezes_while_not_running():
    """Battle Arena visualization request: pausing (engine reports
    running=False) must freeze in-flight animation progress, not let it
    keep advancing in real time — otherwise a projectile/hit-effect
    visible at the moment of a Pause would simply finish playing out
    during the pause, inconsistent with the frozen battle state.
    Deterministic — uses the injectable `now` rather than real sleeps."""
    renderer = ArenaRenderer(pygame.Rect(0, 0, 400, 300))

    t0 = renderer._advance_clock(running=True, now=100.0)
    assert t0 == 0.0  # first call just establishes the baseline, no delta yet

    t1 = renderer._advance_clock(running=True, now=100.5)
    assert abs(t1 - 0.5) < 1e-9  # running: advanced by the real delta

    # "pause" — real wall-clock keeps moving, but running=False
    t2 = renderer._advance_clock(running=False, now=101.5)
    assert t2 == t1, "animation clock must not advance while paused"

    t3 = renderer._advance_clock(running=False, now=105.0)
    assert t3 == t1, "animation clock must stay frozen for as long as paused"

    # resume — clock continues from where it left off, not from 0 and not
    # jumping by the real time that passed while paused
    t4 = renderer._advance_clock(running=True, now=105.2)
    assert abs(t4 - (t1 + 0.2)) < 1e-9


def test_ship_scale_matches_between_admin_and_practice_panel_sizes():
    """Requirement: the visual experience must be almost identical
    between the admin's Battle Arena panel (820x560px, ui/app.py's
    BattlePanel default) and the Practice Console's panel (440x320px,
    practice_console.py) — both represent the same 40x22.5 world-unit
    arena at different pixel sizes. Before this fix the hull was always
    drawn at a fixed 132px regardless of panel size, so a ship's size
    relative to the arena differed between the two. ship_scale() must
    convert each panel's own pixel size back to the same canonical
    world-unit ship length."""
    from sim import ship_renderer as sr
    from engine.config import SHIP_LENGTH_WORLD, ARENA_WIDTH, ARENA_HEIGHT

    admin_renderer = ArenaRenderer(pygame.Rect(0, 0, 820, 560))
    practice_renderer = ArenaRenderer(pygame.Rect(0, 0, 440, 320))

    admin_scale = admin_renderer.ship_scale()
    practice_scale = practice_renderer.ship_scale()

    def _effective_world_length(rect, scale):
        px_per_unit = min(rect.width / ARENA_WIDTH, rect.height / ARENA_HEIGHT)
        return (scale * sr.HULL_LEN) / px_per_unit

    admin_world_len = _effective_world_length(admin_renderer.rect, admin_scale)
    practice_world_len = _effective_world_length(practice_renderer.rect, practice_scale)

    assert abs(admin_world_len - SHIP_LENGTH_WORLD) < 1e-6
    assert abs(practice_world_len - SHIP_LENGTH_WORLD) < 1e-6
    assert abs(admin_world_len - practice_world_len) < 1e-6, (
        "a ship must occupy the same proportion of the arena in both panels"
    )
    # the two panels ARE different pixel sizes, so the raw scale factors
    # themselves should differ (proves this isn't trivially always 1.0)
    assert abs(admin_scale - practice_scale) > 1e-3


def test_projectiles_and_explosions_are_cleaned_up_over_time():
    """Requirement: effects must not accumulate forever — once an
    in-flight projectile/hit-effect's duration has elapsed (per the
    pause-aware animation clock), it must be dropped, not linger."""
    renderer = ArenaRenderer(pygame.Rect(0, 0, 400, 300))
    surface = pygame.Surface((400, 300))
    scale = renderer.ship_scale()

    events = [
        ev.Event(id=1, kind=ev.ATTACK, team="Team A", message="Attack successful"),
        ev.Event(id=2, kind=ev.DAMAGE, team="Team A", message="Team B HP -12", data={"amount": 12.0}),
    ]
    renderer._ingest_events(events, (10.0, 10.0), (20.0, 20.0), "Team A", "Team B", 0.0)
    assert len(renderer._projectiles) == 1
    assert len(renderer._explosions) == 1

    renderer._draw_projectiles(surface, 0.05, scale)
    renderer._draw_explosions(surface, 0.05, scale)
    assert len(renderer._projectiles) == 1, "still in flight, must not be dropped early"
    assert len(renderer._explosions) == 1, "still playing, must not be dropped early"

    longest = max(PROJECTILE_DURATION, EXPLOSION_DURATION) + 0.5
    renderer._draw_projectiles(surface, longest, scale)
    renderer._draw_explosions(surface, longest, scale)
    assert renderer._projectiles == [], "expired projectile must be cleaned up"
    assert renderer._explosions == [], "expired hit-effect must be cleaned up"


if __name__ == "__main__":
    pygame.init()
    tests = [
        test_draw_survives_custom_team_names_through_attack_and_damage,
        test_draw_still_works_with_default_team_names,
        test_draw_ignores_event_from_unrecognized_team_defensively,
        test_draw_renders_hp_and_energy_bars_without_error,
        test_advance_clock_freezes_while_not_running,
        test_ship_scale_matches_between_admin_and_practice_panel_sizes,
        test_projectiles_and_explosions_are_cleaned_up_over_time,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print(f"\nALL {len(tests)} RENDERER TESTS PASSED")
