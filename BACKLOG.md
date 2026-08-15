# Code Battleship — Technical Backlog

Deferred issues, tracked visibly per each phase's spec instructions. Items
are not fixed just because a later phase happens to touch nearby code —
each one below is only marked done when it was actually fixed and tested.

## HIGH PRIORITY

1. **Sandbox CPU/timeout enforcement.** ✅ **FIXED in Phase 7.**
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
   only `ui/app.py`'s one live engine turns it on, so every pre-existing
   direct-`BattleEngine` caller (all 168 pre-Phase-7 tests,
   `submissions/test_runner.py`'s "Test" battles) is completely
   unaffected. See item 16 below for the one deliberately-deferred piece
   (the "Test" button itself isn't isolated yet) and the Phase 7 report's
   "Security Limitations" section for exactly what this does and does
   not guarantee.

2. **Cleanup orphaned submission stub files when deleting teams.**
   ✅ **FIXED in Phase 7.** `TeamService.delete_team()` now calls
   `_cleanup_orphaned_submission_stub()`, which deletes
   `data/submissions/<team_id>.py` if and only if that file actually
   lives inside this service's own `submissions_dir` — the default
   Alpha/Beta teams' `teams/team_alpha.py`/`team_beta.py` files (a
   different directory) can never be touched, verified directly in
   `tests/test_phase7.py::test_orphan_submission_cleanup_only_deletes_own_stub`.
   Best-effort (a missing file or OS error never blocks the Team record
   deletion itself, which already succeeded first).

3. **Static Ahmed/Mohammed labels in the dashboard Team Panel.**
   `ui/team_panel.py`'s standalone Battle Arena tab still shows the
   original hardcoded member labels instead of real managed team/member
   data from `roster/`. *(Open — the Teams tab itself has shown real data
   since Phase 1; only the standalone dashboard panel is stale. Not
   touched in Phase 7 — out of this phase's security/reliability scope.)*

4. **Warn about pending ship reassignment changes while a battle is
   active.** ✅ **FIXED in Phase 7.** `ui/teams_view.py::_save_detail()`
   now detects a ship-slot change on a team currently `IN_BATTLE`
   (`TeamService.compute_status()`) and shows a bilingual info dialog
   ("This change will take effect after the current battle is reset." /
   "سيصبح هذا التغيير سارياً بعد إعادة تعيين المعركة الحالية.") — the
   underlying deferral behavior (`App._sync_engine_state()` already
   skips re-syncing mid-battle) was correct and untouched; this only
   makes it visible instead of silent.

5. **Improve forbidden-API error messages.** ✅ **FIXED in Phase 7.**
   `engine/api.py::build_api()` now keeps every `ALL_API_FUNCTIONS` name
   present in the dict handed to team code; a disallowed one maps to a
   stub that raises a new `ForbiddenAPIError` with a clear message
   ("API function 'attack' is not available in this challenge.") the
   moment it's *called* — never a bare `KeyError` at the subscript.
   Still caught by the same `sandbox.run_decide()` try/except as any
   other team-code runtime error (turned into the existing `CODE_ERROR`
   event/team-attributed log line) — no new failure path, no engine
   crash, no change to the AST-level static `allowed_api` validator in
   `submissions/`.

6. **Show DRAW as a distinct dashboard status/pill.** ✅ **FIXED —
   Phase 5 + Phase 6.** Phase 5 covered Match/MatchResult/History/Match
   Details (`results/result_service.py`'s `_outcome_label()`/
   `_outcome_color()`). Phase 6 closes the remaining live-scoreboard gap
   explicitly called out above: `ui/live_state.py::is_draw_outcome()` is
   the single shared check now used by `ui/scoreboard.py` (its
   `status_key == "draw"` branch, its own warning color, never
   success/danger), `ui/team_panel.py` (`TeamCard.update_from(...,
   is_draw=...)`), and `ui/topbar.py` (`update_status()`) — all three
   live, real-time surfaces now show a distinct DRAW state the moment a
   battle ends in one, verified against a real forced draw in both the
   automated suite (`tests/test_live_control.py::test_draw_live_status`)
   and manual verification items 25-28. **Fully closed, both historical
   and live.**

## MEDIUM / FUTURE

7. **Define proper cancelled-match behavior (retry / forfeit /
   advancement).** `TournamentService.cancel_match()` now has a full UI
   path (item 12, Phase 7), but there is still no round-advancement
   policy for a cancelled match beyond "excluded from winners" in
   `_check_round_completion()` — no retry flow, no forfeit-to-opponent
   rule. Phase 5 deliberately does **not** create a MatchResult for a
   cancelled match (spec section 8: never record a result before a battle
   actually happened) — see `tests/test_results.py::test_cancelled_result`
   and `tests/test_phase7.py::test_cancel_match_lifecycle`. *(Open.)*

8. **Improve single-elimination seeding.** Still plain `team_ids`
   insertion order, not a balanced bracket. *(Open.)*

9. **Improve CUSTOM round scheduling.** Still one match at a time via a
   simple Team A/Team B picker. *(Open.)*

10. **Add a visual tournament bracket.** Phase 4 and Phase 5 both
    deliberately kept this text-only (a Phase 5 Match/Round/Competition
    summary exists, but no bracket diagram) — explicitly out of scope per
    both phases' specs ("do not overbuild"). *(Open, and intentionally
    so — a future phase's job.)*

11. **Make difficulty levels affect actual behavior.** `difficulty` is
    still configuration-only; no built-in AI opponents read it yet.
    *(Open.)*

## NEW — surfaced during Phase 5

12. **`error_match()` / `cancel_match()` have no UI entry point.**
    ✅ **FULLY CLOSED in Phase 7** (Phase 6 already closed the
    `error_match()`/Stop half). `ui/competition_view.py` now shows a
    **Cancel Match** button (with a bilingual confirmation dialog) on
    any non-bye match that's `PENDING`/`READY` — exactly
    `TournamentService.cancel_match()`'s existing, unmodified guard;
    already-`RUNNING`/`COMPLETED` matches never show the button and the
    service itself still refuses them. A cancelled match produces no
    winner, no MatchResult (verified in
    `tests/test_phase7.py::test_cancel_match_lifecycle` — nothing ran,
    so there's nothing to record, same principle Phase 5 already
    established for BYE/never-started matches), and is visually distinct
    from WIN/DRAW/ERROR via the existing `MATCH_STATUS_KEY`/
    `_match_status_color` mapping. Round-advancement policy for a
    cancelled match beyond "excluded from winners" remains open — see
    item 7.

13. **Global (cross-competition) leaderboard/team-performance UI.**
    `ResultService.team_performance(team_id, competition_id=None)`
    already supports an all-time, cross-competition view (and is
    covered by `tests/test_results.py`), but `ui/results_view.py` only
    surfaces the per-competition leaderboard in the UI. Match History
    *does* support an "All Competitions" filter. A dedicated per-team
    all-time profile screen would be a natural, low-risk follow-up.
    *(Open.)*

## NEW — surfaced during Phase 6

14. **The embedded pygame Battle Arena cannot be duplicated onto the Live
    Monitoring screen.** The SDL_WINDOWID embedding technique
    (`ui/battle_panel.py`) attaches pygame's single global display
    surface to one specific native window handle; a second `BattlePanel`
    instance on the Live Monitoring screen would either fail to embed or
    steal the display context from the Dashboard tab's existing one — and
    section 2 explicitly forbids anything that could look like a second
    battle/engine view. The Live Monitoring screen instead shows the same
    real snapshot data (HP/energy/position/cooldown/target) as bars and
    numeric readouts, and existing dashboard tab remains the one place
    with the actual pygame visualization. Not a bug — a documented
    architectural constraint. *(Open — would need a genuinely different
    embedding strategy, e.g. rendering to an offscreen surface and
    blitting into a `CTkImage`, to lift.)*

15. **Runtime error latch has no admin-facing "acknowledge/clear"
    action.** ✅ **FIXED in Phase 7.** The Live Monitoring screen's
    Engine Health panel now has an **Acknowledge** button
    (`App.can_acknowledge_error()` / `_on_acknowledge_error()`) — but it
    stays disabled, and clicking it is a deliberate no-op, unless the
    runtime has demonstrably kept ticking *since* the fault (background
    thread still alive AND at least one more successful tick than the
    engine had at the moment of the fault). It never pretends a still-
    unhealthy engine recovered; ERROR stays ERROR until that's actually
    true, exactly as spec section 15 required. A full Reset remains
    available and unchanged as the other recovery path.

## NEW — surfaced during Phase 7

16. **`submissions/test_runner.py`'s "Test" button is not
    process-isolated.** Phase 7's `DecideWorker` timeout/isolation
    mechanism (item 1) was deliberately applied ONLY to `ui/app.py`'s one
    live `BattleRunner` engine, not to the throwaway `BattleEngine` Phase
    3's "Test" button constructs in `run_test()`. A team's code that
    genuinely infinite-loops can still hang the "Test" button's
    background thread indefinitely (it doesn't freeze the Tk UI thread —
    that's already backgrounded per Phase 3's own docstring — but it
    never completes either). Deliberately deferred rather than risked:
    wiring `isolate_execution=True` into that path touches
    `submissions/submission_service.py`'s real call site, which all 30
    of Phase 3's already-verified tests exercise — not worth the
    regression risk under this phase's time budget for a secondary,
    already-backgrounded path. *(Open — a real, disclosed limitation,
    not a claimed fix.)*

17. **Isolated worker startup adds a bounded, one-time UI pause when a
    match starts or code changes.** `BattleRunner.set_team_code()` now
    also restarts that side's `DecideWorker` (`engine.set_worker_code()`)
    — spawning a fresh OS process takes roughly 100–200ms on this
    machine (measured directly during the Phase 7 audit), and that call
    happens on the Tk main thread (inside the same lock `set_team_code`
    already held pre-Phase-7), not the background engine thread. This is
    a bounded, infrequent (not per-tick) cost, unlike the per-tick hang
    risk the timeout mechanism actually protects against, and was judged
    an acceptable tradeoff rather than engineering an async worker-
    startup path. *(Open — not urgent; documented so it isn't mistaken
    for the per-tick responsiveness guarantee regressing.)*

18. **`BattlePanel`'s render loop was independently draining
    `runner.snapshot()`, racing `_tick()`'s single authoritative
    consumer.** ✅ **FIXED in Phase 7** (found during this phase's own
    testing, not present in any prior phase's report — a real,
    pre-existing bug dating back to Phase 0/6, not introduced by Phase
    7). `BattleRunner.snapshot_for_render()` is now a second, explicitly
    non-draining method (bounded recent-events window, `_last_event_id`
    never touched) that `ui/battle_panel.py`'s ~60fps pygame loop calls
    instead of `snapshot()` — closing exactly the "two independent
    `runner.snapshot()` consumers" race every phase since Phase 4 has
    warned against, which this one had actually been committing the
    whole time. See the Phase 7 report's "Bugs Found" section for how
    this was discovered (a rare, one-shot `CODE_TIMEOUT` event
    intermittently failing to reach `ui/app.py`'s team-code-status
    tracking, unlike high-frequency events like `DAMAGE` which "worked"
    often enough by accident to mask the same underlying race).

19. **Security honesty: what Phase 7's isolation is and is not.**
    `engine/worker.py`'s process isolation provides real OS-level
    CRASH/HANG containment appropriate for a classroom/internal
    competition where the threat model is "buggy code." It is
    explicitly **not** a hardened security boundary against a hostile
    actor: the worker process runs as the same OS user with the same
    filesystem/network access as the main app, on top of (not instead
    of) the pre-existing AST-level sandbox (`engine/sandbox.py`)
    restricting imports/builtins/dunder access — neither layer attempts
    resource limits (memory, CPU shares beyond the wall-clock timeout),
    filesystem restriction, or network isolation. Genuinely hostile,
    public-internet-facing code execution would need real containerization
    (a locked-down container/VM per worker, dropped privileges, no
    network) — out of scope, and never claimed otherwise. *(Open by
    design — a documented boundary, not a gap to close casually.)*
