# Code Battleship

A Python programming-competition desktop platform. Teams write Python
strategies that control autonomous battleships inside a simulated arena;
an administrator runs those strategies through structured competitions —
teams, challenges, code submissions, rounds, matches, results, and live
monitoring — from one CustomTkinter dashboard with an embedded pygame-ce
battle arena.

Built for classroom and internal programming competitions, in phases:
engine and dashboard first, then team/challenge/submission management,
then competitions and live control, then reliability hardening, then this
polish/completion pass.

## Run it

```
pip install -r requirements.txt

# Full dashboard (CustomTkinter + embedded pygame-ce arena) — the app
python -m ui.app

# Standalone pygame arena only (also the dashboard's embedding fallback)
python -m sim.main
```

Requires **Python 3.10+** (uses `X | Y` union type hints and `dict | None`
annotations). Verified on Python 3.14 with `pygame-ce` (chosen over
`pygame` because, at time of writing, `pygame` has no Python 3.14 wheel).

## Project layout

```
engine/         battle simulation — single source of truth for battle state
  ship.py           ship physics/rules (HP, energy, movement, attack, cooldown)
  sandbox.py        AST-restricted compile/validate of team strategy code
  api.py            the only actions team code can call; ForbiddenAPIError
                     for a Challenge-disallowed function
  config.py         BattleConfig — the one source of truth for battle rules,
                     including code_execution_timeout
  battle.py         tick loop: gathers/applies both sides' decide(), combat
  events.py         structured, typed event bus (CODE_ERROR, CODE_TIMEOUT,
                     ATTACK, DAMAGE, DESTROYED, BATTLE_WON, BATTLE_DRAW, ...)
  runner.py         runs BattleEngine on a background thread; the ONE
                     draining snapshot() consumer is ui/app.py's _tick()
  worker.py         DecideWorker — one persistent, isolated OS process per
                     side, real OS-enforced execution timeout (see below)
  competition.py    cross-battle win/loss/damage/score tracking (live)

teams/          example team strategies (decide(friendly, enemies, api))

roster/         Team + Member management (roster/team_service.py)
challenges/     Challenge + Rules management (battle configuration presets)
submissions/    per-(team, challenge) versioned code submissions,
                validate/test/submit workflow; submissions/test_runner.py
                runs an isolated "Test" battle against a built-in opponent
tournament/     Competition -> Round (round-robin / single-elimination /
                custom) -> Match lifecycle, cancel/error/advance logic
results/        immutable historical MatchResult records, leaderboards,
                cross-competition team performance aggregation

storage.py      shared JSON persistence: atomic writes, typed
                CorruptedDataError for malformed files, {} for missing ones

sim/            pygame-ce visualization
  ship_renderer.py   top-down warship rendering + damage states
  renderer.py        arena grid, trajectories, event-driven projectile/FX
  main.py            standalone launcher / dashboard embedding fallback

ui/             CustomTkinter dashboard
  app.py               owns the ONE BattleEngine/BattleRunner; wires every
                        panel; the single authoritative per-tick drain point
  theme.py             color tokens + fonts (dark + light)
  localization.py      EN/AR strings, Arabic shaping + RTL layout
  status_style.py       centralized status label/color tables (team,
                        competition, match, runtime, ship-battle status)
  live_state.py         pure runtime-state/alert/team-code-status logic
  teams_view.py, challenges_view.py, submission_workspace.py,
  competition_view.py, results_view.py, live_monitor_view.py
                        the Teams / Challenges / Python Code / Competition /
                        Results & Team Performance / Live Monitoring screens
  battle_panel.py       embeds the pygame arena via SDL_WINDOWID
  topbar.py, sidebar.py, team_panel.py, scoreboard.py, battle_log.py,
  status_bar.py, difficulty_panel.py, code_editor.py
                        supporting dashboard widgets

tests/
  test_engine.py, test_teams.py, test_challenges.py, test_submissions.py,
  test_tournament.py, test_results.py, test_live_control.py,
  test_phase7.py, test_phase8.py
                        each file is a standalone script (no pytest
                        dependency) — run with `python tests/test_X.py`;
                        each also re-runs representative checks from every
                        earlier phase as a regression guard

BACKLOG.md      tracked, honestly-labeled backlog: CLOSED / DEFERRED /
                OUT OF SCOPE / ARCHITECTURAL, never silently dropped
```

Run the full test suite:

```
for f in test_engine test_teams test_challenges test_submissions test_tournament test_results test_live_control test_phase7 test_phase8; do
  python tests/$f.py
done
```

229 automated tests, 0 external test-framework dependency.

## Workflows

- **Team**: create a team, add members, optionally assign it to the
  `alpha`/`beta` battle slot. `roster/team_service.py` is the only writer
  of team state; the dashboard's live Team Panel and the standalone
  Team Performance profile both read from it — no second team database.
- **Challenge**: define a named ruleset (movement speed, attack range/
  damage/cooldown, energy pool, sensor range, battle duration, win
  condition, allowed API functions). One Challenge is "active" at a time
  and supplies the `BattleConfig` every new battle/test uses.
- **Submission**: a team's versioned Python strategy for one Challenge.
  Draft → Validate (AST-level sandbox check) → Test (a real, isolated
  battle against a built-in opponent) → Submit (immutable from then on).
  A version can only ever be validated and tested against the exact code
  it will run with — Save/Validate/Test/Submit always re-check fresh code.
- **Competition**: add teams, create a Round (round-robin / single-
  elimination / custom), generate matches, start the competition, run
  matches from the Competition or Live Monitoring screen.
- **Match**: Prepare → (visibly) Preparing battle workers → Running →
  Completed / Draw / Error / Cancelled / Stopped. Pause/Resume/Reset/Stop
  are always available while a match runs; Cancel is available for a
  match that hasn't started. A cancelled match produces no winner, no
  result, and — for single-elimination — blocks that round from silently
  auto-advancing or declaring a champion (see BACKLOG.md #7).
- **Results**: every completed/errored match becomes an immutable
  `MatchResult` (never mutated after the fact, even if a team is later
  renamed or a challenge edited). Match History, Match Details with a
  full event timeline, per-competition leaderboards, and an all-time,
  cross-competition **Team Performance** profile are all derived reads
  over this same historical store — no second scoring formula.

## Security model — read this before treating it as more than it is

Team strategy code runs under two independent, additive layers:

1. **`engine/sandbox.py` — static AST validation.** Rejects `import`,
   `eval`/`exec`, dunder access, and anything outside a small whitelisted
   builtin set, before the code is ever compiled. This is what stops
   *accidental* misuse and obviously hostile syntax.
2. **`engine/worker.py` — OS process isolation with a real timeout.**
   Each side's `decide()` runs in its own persistent child process. The
   parent enforces a genuine OS-level wall-clock timeout
   (`Connection.poll(config.code_execution_timeout)`, default 2.0s,
   the one source of truth) and force-terminates
   (`Process.terminate()`/`.kill()`) a worker that doesn't answer in
   time — proven against a real `while True: pass`. This provides real
   CRASH and HANG containment: a stuck or crashed participant can never
   freeze the dashboard or the rest of the battle.
   `submissions/test_runner.py`'s "Test" button reuses this exact
   mechanism (not a second implementation) so a hanging Test also times
   out cleanly instead of hanging the background test thread forever.

**What this is not:** a hardened sandbox against a hostile actor. The
worker process runs as the same OS user, with the same filesystem and
network access, as the main application — there is no container, no
dropped privileges, no memory/CPU-share limiting beyond the wall-clock
timeout, and no network isolation. This is appropriate for a classroom
or internal competition where the threat model is "buggy code," not
"code deliberately written to escape isolation." Do not use this to run
code from untrusted strangers on the public internet without adding
real containerization (a locked-down container/VM per worker, dropped
privileges, no network) in front of it.

`CODE_ERROR` (a raised exception, including a `ForbiddenAPIError` for a
Challenge-disallowed API call), `CODE_TIMEOUT` (execution exceeded the
configured limit), and an engine-level fault are three deliberately
distinct signals — never conflated in events, alerts, or team-code
status — and none of them ever fabricates a winner or a result.

## Data persistence

Every store is a plain JSON file under `data/` (`teams.json`,
`challenges.json`, `submissions.json`, `tournament/`, `results/`),
written through `storage.py`'s shared helpers:

- **Atomic writes** — write to a `.tmp` file, then `os.replace()` (atomic
  on both Windows and POSIX), so an interrupted write never corrupts the
  real file.
- **Missing file** — returns an empty store, not an error (first run).
- **Corrupted file** — raises a single, clearly-typed
  `CorruptedDataError` instead of a raw `json.JSONDecodeError`; the
  application catches this at startup and shows a clear, bilingual
  dialog naming the problem file instead of crashing with a traceback.
  A corrupted file is never silently discarded or overwritten.

No database migration, no schema versioning, no automatic repair —
deliberately, for a single-admin desktop tool backed by small JSON files.
Malformed *individual records* (a JSON object missing a required field)
are not defended against beyond this — a known, accepted boundary, not
a claimed guarantee.

## Interface

- **English / Arabic**, switchable at runtime, including full RTL layout
  and Arabic text shaping (`arabic_reshaper` + `python-bidi`).
- **Dark / Light** theme, switchable at runtime; the brand accent color
  stays identical across both.
- A single, centralized status vocabulary (`ui/status_style.py`) drives
  every status pill across every screen (Team Panel, Scoreboard, Battle
  Arena, Teams, Competition, Live Monitoring, Results/History) — WIN,
  DRAW, ERROR, TIMEOUT, and CANCELLED are always visually and
  semantically distinct from each other, in both languages.

## Known limitations

- **Not a hardened security sandbox** — see "Security model" above.
- **Difficulty levels are configuration only.** No built-in AI opponent
  reads them; ships are controlled entirely by submitted team code.
- **Pygame embedding is a best-effort technique** (SDL_WINDOWID), mainly
  exercised on Windows. If it fails on a given platform/driver, the
  dashboard shows an "Open Arena Window" fallback that launches
  `sim/main.py` as its own process — that process runs an independent
  battle, not a mirror of the dashboard's.
- **Only 2 ships / 1 concurrent live battle.** The dashboard's Battle
  Arena, Team Panel, and Scoreboard always reflect one live engine.
- **No visual tournament bracket** — Competition/Round/Match state is
  shown as structured summaries and cards, not a bracket diagram
  (deliberately out of scope — see BACKLOG.md #10).
- **Single-elimination seeding** is insertion order, not a balanced
  bracket (BACKLOG.md #8); **custom round scheduling** is one match at a
  time via a Team A / Team B picker (BACKLOG.md #9).
- **A cancelled single-elimination match blocks that round** from
  auto-advancing rather than offering a retry/forfeit/replace flow —
  deterministic and safe against an accidental "last team standing"
  champion, but an administrator has no in-app way to replace the
  cancelled match yet (BACKLOG.md #7).
- Sidebar tabs Dashboard / Battle Arena / Battle Logs intentionally show
  the same combined live-battle view (they're different entry points
  into the one live engine, not different screens); Settings honestly
  shows a "not built yet" placeholder rather than fake content.

See `BACKLOG.md` for the complete, individually-tracked list of what's
closed, deferred, out of scope, or architectural, with the reasoning
behind each.
