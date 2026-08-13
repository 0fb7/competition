# Code Battleship

A Python programming-competition platform: teams write Python strategies
that control autonomous battleships inside a sandboxed simulation. A
CustomTkinter dashboard monitors the battle, which renders through a
pygame-ce arena embedded directly in the dashboard window.

## Run it

```
pip install -r requirements.txt

# Full dashboard (CustomTkinter + embedded Pygame arena)
python -m ui.app

# Standalone Pygame arena only (also the dashboard's embedding fallback)
python -m sim.main

# Engine test suite (no display required)
python tests/test_engine.py
```

Requires Python 3.10+ (uses `X | Y` union type hints and `dict | None`
annotations). Verified on Python 3.14 with `pygame-ce` (chosen over
`pygame` because, at time of writing, `pygame` has no Python 3.14 wheel).

## Project layout

```
engine/       battle simulation — single source of truth for battle state
  ship.py         ship physics/rules (HP, energy, movement, attack)
  sandbox.py      AST-restricted execution of team strategy code
  api.py          the only actions team code can request
  battle.py       tick loop: runs team code, resolves movement/combat
  events.py       structured event bus (typed, in addition to the text log)
  runner.py       runs BattleEngine on a background thread for the UI
  competition.py  cross-battle win/loss/damage/score tracking

teams/        example team strategies (decide(friendly, enemies, api))

sim/          Pygame visualization
  ship_renderer.py   realistic top-down warship rendering + damage states
  renderer.py        arena grid, trajectories, event-driven projectile/explosion FX
  main.py            standalone launcher / dashboard fallback window

ui/           CustomTkinter dashboard
  app.py             owns the one BattleEngine/BattleRunner; wires all panels
  theme.py           color tokens + fonts (dark primary, light mode included)
  localization.py    EN/AR strings, Arabic shaping (arabic_reshaper + python-bidi)
  battle_panel.py    embeds the Pygame arena via SDL_WINDOWID (see docstring)
  ...                topbar, sidebar, team_panel, code_editor, battle_log,
                      scoreboard, difficulty_panel, status_bar

tests/
  test_engine.py  headless engine/sandbox/runner/competition tests
```

## Known limitations

- **Sandbox is a classroom/competition barrier, not hardened isolation.**
  AST validation + restricted builtins stop accidental misuse; it does
  not stop a determined attacker (no memory/CPU/timeout limits). Don't
  run untrusted code from strangers on this alone.
- **Difficulty levels are configuration only.** The engine doesn't have
  a built-in AI opponent whose behavior scales — ships are controlled by
  whatever code a team submits. Selecting a level stores it on the
  engine and displays it; it does not currently change anything.
- **Pygame embedding is a best-effort technique** (SDL_WINDOWID), mainly
  exercised on Windows. If it fails on a given platform/driver, the
  dashboard shows an "Open Arena Window" button that launches
  `sim/main.py` as its own process — note that process runs an
  independent battle, not a mirror of the dashboard's.
- **Only 2 ships / 1 concurrent battle.** Team roster (player names) is
  static configuration, not a team-management feature.
- **Sidebar tabs**: Dashboard/Battle Arena/Teams/Python Code/Leaderboard/
  Battle Logs all show the same combined dashboard view (matching the
  original single-screen UI concept). Challenges/Settings show an
  honest "not built yet" placeholder rather than fake content.
