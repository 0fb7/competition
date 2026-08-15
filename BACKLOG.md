# Code Battleship — Technical Backlog

Deferred issues, tracked visibly per each phase's spec instructions. Items
are not fixed just because a later phase happens to touch nearby code —
each one below is only marked done when it was actually fixed and tested.
Every item now carries one explicit status tag: **[CLOSED]**,
**[DEFERRED]**, **[OUT OF SCOPE]**, or **[ARCHITECTURAL]** — nothing
completed is left looking unresolved, and nothing architectural is
mislabeled as a bug.

## HIGH PRIORITY

1. **[CLOSED — Phase 7]** Sandbox CPU/timeout enforcement.
   `engine/worker.py`'s `DecideWorker` runs each side's `decide()` in a
   persistent, isolated OS process (spawned once per side, reused every
   tick); the parent enforces a real, OS-level timeout via
   `Connection.poll(config.code_execution_timeout)` and force-terminates
   (`Process.terminate()`/`.kill()`) a worker that doesn't answer in
   time — proven directly against a genuine `while True: pass` in
   `tests/test_phase7.py` and manually via a live hot-swapped hang
   during a real match. `code_execution_timeout` (default 2.0s) is the
   one source of truth (`engine/config.py`'s `BattleConfig`), never
   duplicated. Opt-in via `BattleEngine(..., isolate_execution=True)` —
   every direct-`BattleEngine` caller not opted in is unaffected. Phase 8
   closed the one remaining gap (item 16 below): `submissions/
   test_runner.py`'s "Test" button now uses this exact mechanism too.
   See README.md's "Security model" section for exactly what this does
   and does not guarantee.

2. **[CLOSED — Phase 7]** Cleanup orphaned submission stub files when
   deleting teams. `TeamService.delete_team()` calls
   `_cleanup_orphaned_submission_stub()`, which deletes
   `data/submissions/<team_id>.py` if and only if that file actually
   lives inside this service's own `submissions_dir` — the default
   Alpha/Beta teams' `teams/team_alpha.py`/`team_beta.py` files (a
   different directory) can never be touched, verified directly in
   `tests/test_phase7.py::test_orphan_submission_cleanup_only_deletes_own_stub`.
   Best-effort (a missing file or OS error never blocks the Team record
   deletion itself, which already succeeded first).

3. **[CLOSED — Phase 8]** Static Ahmed/Mohammed labels in the dashboard
   Team Panel. `ui/team_panel.py`'s standalone Battle Arena tab used to
   show hardcoded member labels (`ROSTER = {"alpha": {"player": "Ahmed"},
   "beta": {"player": "Mohammed"}}`) instead of real managed team data.
   Now `TeamCard.update_from(..., team=...)` receives the real Team
   object (`TeamService.team_for_slot(side)`, called once per tick from
   `ui/app.py`'s single drain point — no second team database) and shows
   the team's actual member names, falling back to an honest "no members
   yet" instead of a placeholder name. Score/wins/losses/damage were
   already real (CompetitionTracker); only the member/player row was
   stale. Verified in `tests/test_phase8.py` via `status_style`/team_panel
   import checks and manually in the running dashboard (manual item 4).

4. **[CLOSED — Phase 7, extended in Phase 8]** Warn about pending ship
   reassignment changes while a battle is active. `ui/teams_view.py`'s
   `_save_detail()` detects a ship-slot change on a team currently
   `IN_BATTLE` and shows a bilingual info dialog. Phase 8 made this
   state persistently VISIBLE, not just a one-shot popup: a
   **"Pending for next battle"** badge (bilingual) now stays on that
   team's card in both the Teams list and detail view until the battle
   it was pending against genuinely ends or resets (tracked via
   `TeamService.is_team_active()`, the same real live-engine-name check
   `compute_status()` uses internally — deliberately NOT
   `compute_status() == IN_BATTLE` alone, since unassigning a ship
   mid-battle would make that check misreport before the battle
   actually ends). The underlying deferral behavior
   (`App._sync_engine_state()` skipping re-sync mid-battle) was already
   correct and untouched.

5. **[CLOSED — Phase 7, polished in Phase 8]** Improve forbidden-API
   error messages. `engine/api.py::build_api()` keeps every
   `ALL_API_FUNCTIONS` name present in the dict handed to team code; a
   disallowed one maps to a stub that raises `ForbiddenAPIError` with a
   clear message ("API function 'attack' is not available in this
   challenge.") the moment it's *called* — never a bare `KeyError`.
   Phase 8 closed the remaining UX gap: the Live Monitoring Alerts panel
   used to show only a generic "Team code error" label with the team
   name, discarding the actual detail message; `_render_alerts()` now
   appends the real message (function name included, "error: " prefix
   stripped) so an admin sees "Team Alpha — Team code error: API
   function 'attack' is not available in this challenge." directly,
   bilingually, with no raw traceback. Still the same `CODE_ERROR`
   event/team-attributed log line as any other runtime error — no new
   failure path, no engine crash, never a fake winner (`tests/
   test_phase8.py::test_forbidden_api_*`).

6. **[CLOSED — Phase 5 + Phase 6]** Show DRAW as a distinct dashboard
   status/pill. Phase 5 covered Match/MatchResult/History/Match Details.
   Phase 6 closed the live-scoreboard gap: `ui/live_state.py::
   is_draw_outcome()` is the single shared check used by
   `ui/scoreboard.py`, `ui/team_panel.py`, and `ui/topbar.py` — all
   three live, real-time surfaces show a distinct DRAW state the moment
   a battle ends in one. Phase 8's status-vocabulary centralization
   (item 20 below) kept this exact behavior while removing the
   duplicated color dicts around it.

## MEDIUM / FUTURE

7. **[CLOSED — Phase 8]** Define proper cancelled-match behavior
   (retry / forfeit / advancement). Policy, now deterministic and
   documented in `tournament/tournament_service.py::
   _check_round_completion()`: a cancelled match always produces no
   winner and no MatchResult (unchanged since Phase 5). Round-robin: a
   cancelled match still counts toward "this round is done" — there is
   no bracket to protect, and leaving the round stuck over one cancelled
   match would only hide a genuinely finished round from the UI.
   Single-elimination: a round containing ANY cancelled match is
   explicitly **never** marked COMPLETED and **never** advances to the
   next round — no forfeit-to-opponent, no silently declaring the other
   bracket survivor a "champion" just because their opponent's match was
   cancelled. The round stays in its current status until an
   administrator manually intervenes (there is still no in-app
   "replace the match" action — see the note below); this is a genuinely
   blocked, visibly non-terminal state, never a silent auto-resolution.
   Verified in `tests/test_phase8.py::test_cancelled_match_blocks_
   single_elimination_advancement` (no champion, no next round created)
   and `test_cancelled_match_round_robin_still_completes` (round-robin
   unaffected). **Note:** there is still no UI action to actually
   *replace* a cancelled match and unblock the round — that would be new
   scope, not polish, and is intentionally not built here.

8. **[OUT OF SCOPE]** Improve single-elimination seeding. Still plain
   `team_ids` insertion order, not a balanced bracket. Explicitly listed
   under Phase 8's "DO NOT OVERBUILD" — a genuinely new scheduling
   feature, not a polish item.

9. **[OUT OF SCOPE]** Improve CUSTOM round scheduling. Still one match
   at a time via a simple Team A/Team B picker.

10. **[OUT OF SCOPE]** Add a visual tournament bracket. Phase 4/5 both
    deliberately kept this text-only; explicitly out of scope again per
    Phase 8's "no bracket viz" instruction.

11. **[OUT OF SCOPE]** Make difficulty levels affect actual behavior.
    `difficulty` is still configuration-only; explicitly listed under
    Phase 8's "no AI" instruction.

## NEW — surfaced during Phase 5

12. **[CLOSED — Phase 6 + Phase 7]** `error_match()` / `cancel_match()`
    had no UI entry point. `ui/competition_view.py` shows a **Cancel
    Match** button (bilingual confirmation dialog) on any non-bye match
    that's `PENDING`/`READY`; Stop (Phase 6) covers the `error_match()`
    path for a running match. A cancelled match produces no winner, no
    MatchResult, and is visually distinct from WIN/DRAW/ERROR via the
    centralized status table (item 20). Round-advancement policy is now
    also fully defined — see item 7.

13. **[CLOSED — Phase 8]** Global (cross-competition) leaderboard/
    team-performance UI. `ResultService.team_performance(team_id,
    competition_id=None)` already supported an all-time aggregation;
    `ui/results_view.py` now has a dedicated **Team Performance** tab
    (a team selector + identity card sourced live from `TeamService` +
    an all-time stats grid sourced from `team_performance()` + that
    team's recent match history). `team_performance()` itself gained two
    additive fields — `errors` (ERROR-outcome matches involving this
    team, shown for visibility WITHOUT folding into win_rate, preserving
    Phase 5's "ERROR is not a battle result" rule) and `competitions`
    (distinct competition count) and `score` (the exact `TeamRecord`
    formula leaderboard() already used, applied to historical
    aggregates instead of live session data — no second scoring
    system). A team rename updates the identity card but never mutates
    historical `MatchResult.team_x_name_at_match` snapshots — verified
    in `tests/test_phase8.py::test_team_performance_historical_
    survives_team_rename`.

## NEW — surfaced during Phase 6

14. **[ARCHITECTURAL]** The embedded pygame Battle Arena cannot be
    duplicated onto the Live Monitoring screen. The SDL_WINDOWID
    embedding technique (`ui/battle_panel.py`) attaches pygame's single
    global display surface to one specific native window handle; a
    second `BattlePanel` instance would either fail to embed or steal
    the display context from the Dashboard tab's existing one. The Live
    Monitoring screen instead shows the same real snapshot data (HP/
    energy/position/cooldown/target) as bars and numeric readouts. Not a
    bug — a documented architectural constraint that would need a
    genuinely different embedding strategy (e.g. render-to-offscreen-
    surface + blit into a `CTkImage`) to lift; not attempted in Phase 8
    per "do not replace working systems."

15. **[CLOSED — Phase 7]** Runtime error latch had no admin-facing
    "acknowledge/clear" action. The Live Monitoring screen's Engine
    Health panel has an **Acknowledge** button, enabled only when the
    runtime has demonstrably kept ticking *since* the fault. It never
    pretends a still-unhealthy engine recovered. A full Reset remains
    the other, always-available recovery path.

## NEW — surfaced during Phase 7

16. **[CLOSED — Phase 8]** `submissions/test_runner.py`'s "Test" button
    was not process-isolated. `run_test()` now constructs its throwaway
    `BattleEngine` with `isolate_execution=True` — the exact same
    `DecideWorker` mechanism item 1 already built, reused rather than
    duplicated, governed by the same single `code_execution_timeout`
    source of truth. `TestResult` gained a `status` field with four
    values — `PASSED` / `FAILED` / `TIMEOUT` / `ERROR` — so a timeout is
    never conflated with a genuine battle loss (`FAILED`) or a raised
    exception (`ERROR`); a timeout NEVER makes a submission eligible to
    submit (`SubmissionService.submit_submission()` already only checks
    `test_result.passed`, which is `True` only for `PASSED`). Workers are
    torn down (`engine.shutdown_workers()`) in a `finally` block so a
    throwaway Test engine never leaks a process, including across
    repeated timeouts. The submission workspace UI shows all four states
    with distinct bilingual labels/colors. Verified with real hangs,
    real runtime errors, real syntax errors, and a real pass, plus a
    direct child-process-count check proving no leak
    (`tests/test_phase8.py`, items 1-7).

17. **[CLOSED — Phase 8]** Isolated worker startup added a bounded,
    one-time UI pause when a match starts. The pause itself is not
    (and was never meant to be) engineered away — spawning a fresh OS
    process per side takes ~100-200ms, an infrequent, bounded cost, not
    the per-tick hang risk the timeout mechanism protects against.
    What Phase 8 fixed: `App._on_start_match()` now sets an explicit
    `_match_preparing` flag and forces a UI paint (topbar pill,
    Live Monitoring's runtime pill AND its context line, which now
    reads "Preparing battle workers...") **before** the blocking
    `set_team_code()` calls, so the pause is a real, visible PREPARING
    state instead of a silent freeze. `live_state.compute_runtime_state()`
    gained a `preparing` override that takes precedence even over a
    stale prior-battle snapshot. A worker that fails to even start is
    now detected immediately via the new `BattleRunner.worker_health()`
    and turned into a clear, immediate ERROR (`tournament_service.
    error_match(..., "worker_start_failed")`, a bilingual error dialog,
    the match never silently goes RUNNING with a dead side) instead of
    surfacing only once the engine starts ticking. Duplicate-start
    prevention: `active_match_id`/`_match_preparing` are set as the very
    first mutation after eligibility passes, before any blocking work,
    so a second Start invocation sees the guard immediately.

18. **[CLOSED — Phase 7]** `BattlePanel`'s render loop was independently
    draining `runner.snapshot()`, racing `_tick()`'s single authoritative
    consumer. `BattleRunner.snapshot_for_render()` is a second, explicitly
    non-draining method that `ui/battle_panel.py`'s ~60fps pygame loop
    calls instead — closing a real, pre-existing race dating back to
    Phase 0/6, discovered during Phase 7's own testing (a rare, one-shot
    `CODE_TIMEOUT` event intermittently failing to reach the UI, unlike
    high-frequency events like `DAMAGE` which "worked" often enough by
    accident to mask the same underlying race).

19. **[ARCHITECTURAL — by design, documented]** Security honesty: what
    Phase 7's isolation is and is not. `engine/worker.py`'s process
    isolation provides real OS-level CRASH/HANG containment appropriate
    for a classroom/internal competition where the threat model is
    "buggy code." It is explicitly **not** a hardened security boundary
    against a hostile actor: the worker process runs as the same OS user
    with the same filesystem/network access as the main app, on top of
    (not instead of) the AST-level sandbox (`engine/sandbox.py`) —
    neither layer attempts resource limits beyond the wall-clock
    timeout, filesystem restriction, or network isolation. Genuinely
    hostile, public-internet-facing code execution would need real
    containerization — out of scope, and never claimed otherwise. Now
    stated plainly in README.md's "Security model" section (Phase 8
    Step 13's explicit honesty requirement), not just in code comments.

## NEW — surfaced during Phase 8

20. **[CLOSED — Phase 8]** Status label/color logic was duplicated
    verbatim across multiple UI modules — competition status
    (`competition_view.py` vs `live_monitor_view.py`), team status
    (`teams_view.py`'s own list AND detail cards, plus a third copy
    added by this phase's new Team Performance card before being fixed),
    runtime-state color (`topbar.py` vs `live_monitor_view.py`), and the
    ACTIVE/DAMAGED/DESTROYED/DRAW ship-battle-status *derivation* itself
    (independently recomputed in `ui/app.py`'s scoreboard-row logic AND
    `ui/team_panel.py`). All now come from one shared `ui/status_style.py`
    — same colors, same labels, verified identical before/after so no
    screen's visible status pill changed. `scoreboard.py`'s status color
    mapping and `ui/app.py`'s/`ui/team_panel.py`'s status derivation were
    also consolidated onto the shared `status_style.ship_battle_status()`
    function. Covered by `tests/test_phase8.py::test_status_style_*`.

21. **[CLOSED — Phase 8]** A corrupted `data/*.json` file crashed the
    application at startup with a raw, unhandled `CorruptedDataError`
    traceback — every repository is constructed inside `App.__init__()`,
    so this was the one reachable "raw traceback window" the storage
    hardening in item 1's era hadn't actually closed at the UI layer.
    `ui/app.py::main()` now catches `CorruptedDataError` specifically
    and shows a clear, bilingual, actionable dialog naming the corrupted
    file before exiting — no data is touched or "repaired." Verified in
    `tests/test_phase8.py::test_app_main_shows_controlled_dialog_not_
    raw_traceback` (monkeypatched `App` construction to raise, confirmed
    a controlled `SystemExit` and exactly one dialog call, not a
    propagated exception).

22. **[CLOSED — Phase 8]** The submission workspace's background "Test"
    thread captured an unexpected internal exception into a dict that
    was never read anywhere — a genuine silent failure: if
    `test_submission()` ever raised something unexpected (a bug in the
    test runner, never a candidate-code error — those already become a
    structured `TestResult`, not an exception), the "Testing..." status
    would simply disappear with no result and no explanation.
    `_poll_test()` now shows a bilingual error dialog with the captured
    detail when this happens.

23. **[DEFERRED]** Team deletion is only blocked when the team is
    currently loaded into the LIVE engine (`is_team_active()`); it is
    NOT blocked when the team is only referenced by a PENDING/READY
    tournament Match in some other, not-yet-started competition. Such a
    match would keep a dangling `team_a_id`/`team_b_id`. Every UI call
    site that resolves a team by id already tolerates a missing team
    gracefully (`team.name if team else '-'`, established since Phase 4)
    — no crash results — but the reference itself is never cleaned up
    or blocked. Auditing this further would mean either a new
    cross-service referential-integrity check (new scope) or leaving it
    as-is (current behavior); left as-is per "do not overbuild," but
    disclosed here rather than silently accepted.

24. **[DEFERRED]** Malformed *individual* JSON records (an object
    missing a required field, e.g. a team dict with no `"id"` key) still
    raise a raw `KeyError` out of the relevant dataclass's `from_dict()`
    — `storage.py`'s hardening (item 1's era) deliberately scoped itself
    to "file missing" and "file corrupted as JSON," not per-record
    schema validation, matching that module's own explicit "do not
    overengineer" design note. *Unexpected extra fields* in a record
    ARE already tolerated everywhere (every `from_dict()` only reads the
    keys it needs). Audited in Phase 8 (Step 9) and left as a disclosed,
    accepted boundary rather than building a schema-validation layer
    across five dataclass families under this phase's time budget.
