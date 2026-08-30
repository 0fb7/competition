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
from sim.renderer import ArenaRenderer


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


if __name__ == "__main__":
    pygame.init()
    tests = [
        test_draw_survives_custom_team_names_through_attack_and_damage,
        test_draw_still_works_with_default_team_names,
        test_draw_ignores_event_from_unrecognized_team_defensively,
        test_draw_renders_hp_and_energy_bars_without_error,
    ]
    for fn in tests:
        print(f"{fn.__name__} ...")
        fn()
        print("  OK")
    print(f"\nALL {len(tests)} RENDERER TESTS PASSED")
