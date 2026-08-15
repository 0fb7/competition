"""CustomTkinter dashboard entry point.

Architecture (matches the brief's diagram): this module owns exactly one
BattleEngine, wrapped in one BattleRunner (engine/runner.py) ticking on a
background thread. Every panel below — team cards, code editor, battle
log, scoreboard, the embedded pygame arena — reads from that same
runner.snapshot() each UI tick. There is no second, UI-only copy of
battle state.
"""

import os
import sys
import time
import tkinter.messagebox as messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk

from storage import CorruptedDataError

from engine.battle import BattleEngine
from engine.competition import CompetitionTracker
from engine.runner import BattleRunner
from engine.sandbox import SandboxError

from roster.team_repository import TeamRepository
from roster.team_service import TeamService

from challenges.challenge_repository import ChallengeRepository
from challenges.challenge_service import ChallengeService

from submissions.submission_repository import SubmissionRepository
from submissions.submission_service import SubmissionService

from tournament.tournament_repository import TournamentRepository
from tournament.tournament_service import TournamentService
from tournament.competition import ValidationError as TournamentValidationError
from tournament.match import OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN, OUTCOME_DRAW, OUTCOME_ERROR

from results.result_repository import ResultRepository
from results.result_service import ResultService
from engine import events as ev

from . import theme, localization
from .localization import t
from .topbar import TopBar
from .sidebar import Sidebar
from .status_bar import StatusBar
from .team_panel import TeamPanel
from .scoreboard import Scoreboard
from .difficulty_panel import DifficultyPanel
from .battle_log import BattleLog
from .battle_panel import BattlePanel
from .teams_view import TeamsView
from .challenges_view import ChallengesView
from .submission_workspace import SubmissionWorkspace
from .competition_view import CompetitionView
from .results_view import ResultsView
from . import live_state, status_style
from .live_monitor_view import LiveMonitorView

LIVE_EVENT_BUFFER = 200   # spec section 27: bounded live UI buffer; full history stays in results/
ALERT_BUFFER = 100
RUNTIME_LOG_BUFFER = 300

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_widget_scaling(1.0)

        self.tokens = theme.Tokens("dark")
        self.title("Code Battleship")
        self.geometry("1500x900")
        self.minsize(1180, 720)
        self.configure(fg_color=self.tokens.bg)

        self._last_snapshot = None
        self.competition = CompetitionTracker([])

        # ---- team management (roster/) ----
        team_repo = TeamRepository(os.path.join(ROOT, "data", "teams.json"))
        self.team_service = TeamService(
            team_repo,
            submissions_dir=os.path.join(ROOT, "data", "submissions"),
            is_team_active=self._is_team_active,
            competition_tracker=self.competition,
        )
        self.team_service.ensure_default_teams(
            os.path.join(ROOT, "teams", "team_alpha.py"),
            os.path.join(ROOT, "teams", "team_beta.py"),
        )

        # ---- challenges & rules (challenges/) ----
        challenge_repo = ChallengeRepository(os.path.join(ROOT, "data", "challenges.json"))
        self.challenge_service = ChallengeService(challenge_repo)
        self.challenge_service.ensure_default_challenge()

        # ---- submissions & versioning (submissions/) ----
        submission_repo = SubmissionRepository(os.path.join(ROOT, "data", "submissions.json"))
        self.submission_service = SubmissionService(submission_repo, self.team_service, self.challenge_service)

        # ---- historical results/leaderboard/analytics (results/) ----
        # Constructed before TournamentService so it can be injected —
        # TournamentService needs it to record a BYE's MatchResult the
        # instant the BYE is created (see tournament_service.py).
        result_repo = ResultRepository(os.path.join(ROOT, "data", "results"))

        # ---- competitions, rounds & matches (tournament/) ----
        tournament_repo = TournamentRepository(os.path.join(ROOT, "data", "tournament"))
        # TournamentService.result_service is set just below, once
        # self.result_service exists (they reference each other read-only).
        self.tournament_service = TournamentService(
            tournament_repo, self.team_service, self.challenge_service, self.submission_service,
        )
        self.result_service = ResultService(
            result_repo, self.tournament_service, self.team_service,
            self.challenge_service, self.submission_service,
        )
        self.tournament_service.result_service = self.result_service
        self.active_match_id = None  # set while a competition Match owns the live engine
        self.match_events: list = []  # engine.events.Event objects accumulated for the running competition match

        # ---- Phase 6: live runtime monitoring state, all derived (never
        # a second source of truth) from BattleRunner.snapshot() inside
        # the single authoritative drain point, _tick() ----
        self.admin_stopped = False      # admin pressed Stop this engine cycle (cleared on next prepare/reset)
        self.engine_fault = False       # engine.step() itself raised — see _on_engine_fault()
        self._engine_faults: list = []  # bounded (msg, timestamp) pairs, for the Runtime Log's technical detail
        self._fault_at_tick: int | None = None  # tick_count at the moment of the most recent fault — see _on_acknowledge_error()
        self.live_events: list = []     # bounded mirror of real events, for the Live Event Stream (spec section 27)
        self.alerts: list = []          # bounded Alert objects, for the administrator Alert area
        self.runtime_log: list = []     # bounded technical log entries (engine start/pause/.../match start/...)
        self.last_team_code_kind = {"alpha": None, "beta": None}   # most recent CODE_EXECUTED/CODE_ERROR per side
        self.last_target = {"alpha": None, "beta": None}           # most recent TARGET_ACQUIRED per side
        self.team_code_status = {"alpha": live_state.READY, "beta": live_state.READY}
        self.runtime_state = live_state.IDLE
        self._last_tick_perf = None
        self.ui_update_hz = 0.0
        self._match_preparing = False  # Phase 8 (BACKLOG #17): True only for the real span
        # _on_start_match() holds while spawning that match's isolated workers

        alpha_team = self.team_service.team_for_slot("alpha")
        beta_team = self.team_service.team_for_slot("beta")
        active_challenge = self.challenge_service.get_active_challenge()

        team_a_code, team_a_name = self._resolve_battle_code(alpha_team, active_challenge, "Team Alpha")
        team_b_code, team_b_name = self._resolve_battle_code(beta_team, active_challenge, "Team Beta")

        initial_config = active_challenge.to_battle_config() if active_challenge else None

        self.team_code_cache = {"alpha": team_a_code, "beta": team_b_code}
        self.code_valid = {"alpha": True, "beta": True}

        self.engine = BattleEngine(
            team_a_code, team_b_code, team_a_name=team_a_name, team_b_name=team_b_name,
            config=initial_config, isolate_execution=True,
        )
        self.runner = BattleRunner(self.engine, tick_hz=30)
        self.runner.on_error = self._on_engine_fault
        self.runner.start_thread()
        if active_challenge:
            self.runner.set_difficulty(self._difficulty_level_number(active_challenge.difficulty))

        self.competition.ensure_team(team_a_name)
        self.competition.ensure_team(team_b_name)

        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(66, self._tick)

    # ------------------------------------------------------- team/engine glue
    @staticmethod
    def _read_team_starter_code(team) -> str:
        """Phase 1's per-team file (teams/team_alpha.py, or a generated
        stub for a created team) — used as a fallback/starter, never as
        the thing a real battle uses once a submission exists. See
        _resolve_battle_code()."""
        with open(team.submission_id, encoding="utf-8") as f:
            return f.read()

    def _resolve_battle_code(self, team, challenge, default_name: str):
        """Phase 3's core integration point (spec section 19):
        Team -> Active Submission -> Submission.code -> Sandbox -> BattleEngine.
        Falls back to the team's Phase-1 starter file only when no
        SUBMITTED version exists yet for (team, challenge) — old files
        stay as migration examples/defaults, never silently overriding a
        real submitted version."""
        if not team:
            return _read(os.path.join(ROOT, "teams", "team_alpha.py" if default_name == "Team Alpha" else "team_beta.py")), default_name
        if challenge:
            active_submission = self.submission_service.get_active_submission(team.id, challenge.id)
            if active_submission:
                return active_submission.code, team.name
        return self._read_team_starter_code(team), team.name

    def _is_team_active(self, team_id: str) -> bool:
        """Passed into TeamService so it can block deleting a team that is
        actually loaded into the live engine right now — checked against
        the last snapshot from the single _tick() consumer, never by
        calling runner.snapshot() again here (that would steal events
        meant for _tick's own runner.snapshot() call)."""
        team = self.team_service.get_team(team_id)
        snap = self._last_snapshot
        if not team or not snap:
            return False
        battle_ongoing = snap["running"] or (snap["tick_count"] > 0 and snap["winner"] is None)
        if not battle_ongoing:
            return False
        return team.name in (snap["ship_a"]["team"], snap["ship_b"]["team"])

    @staticmethod
    def _difficulty_level_number(level: str) -> int:
        return {"LEVEL_1": 1, "LEVEL_2": 2, "LEVEL_3": 3}.get(level, 2)

    # ------------------------------------------------------ Phase 6: runtime monitoring
    def _on_engine_fault(self, msg: str):
        """BattleRunner.on_error — called directly FROM the background
        engine thread (engine/runner.py's _loop) when engine.step()
        itself raises. This is a bug in engine code, never a team's
        decide() (those are caught inside _run_side and turned into
        CODE_ERROR events; they never reach here) — spec section 7 calls
        this "serious runtime corruption" that must surface as an
        administrator-facing ERROR state, not be silently swallowed.
        Only touches a bool flag and appends to a bounded list — both
        atomic under CPython's GIL, so no new lock is introduced here;
        anything needing real cross-field consistency already goes
        through BattleRunner's own internal lock via snapshot()."""
        self.engine_fault = True
        self._fault_at_tick = self.engine.tick_count
        self._engine_faults.append((msg, time.time()))
        if len(self._engine_faults) > 50:
            self._engine_faults = self._engine_faults[-50:]
        print(f"[engine error] {msg}")

    def can_acknowledge_error(self) -> bool:
        """Phase 7 section 15: Acknowledge must NOT pretend the engine
        recovered — it may only clear the visible ERROR latch when the
        runtime has demonstrably kept working SINCE the fault (the
        background thread is still alive AND has produced at least one
        more successful tick than it had at the moment of the fault).
        If the thread died, or no further tick has happened yet, this
        returns False and _on_acknowledge_error() is a deliberate no-op —
        ERROR stays ERROR, exactly as Phase 6 intended, until a real
        Reset."""
        if not self.engine_fault or self._last_snapshot is None:
            return False
        return (
            self._last_snapshot["engine_alive"]
            and self._fault_at_tick is not None
            and self._last_snapshot["tick_count"] > self._fault_at_tick
        )

    def _on_acknowledge_error(self):
        if not self.can_acknowledge_error():
            return  # not actually healthy yet — refuse silently rather than fake a recovery
        self.engine_fault = False
        self._fault_at_tick = None
        self._log_runtime("engine_error_acknowledged")

    def _push_alert(self, alert: "live_state.Alert"):
        self.alerts.append(alert)
        if len(self.alerts) > ALERT_BUFFER:
            self.alerts = self.alerts[-ALERT_BUFFER:]
        if hasattr(self, "live_monitor_view"):
            self.live_monitor_view.notify_alert()

    def _log_runtime(self, key: str, **ctx):
        self.runtime_log.append({"key": key, "ctx": ctx, "ts": time.time()})
        if len(self.runtime_log) > RUNTIME_LOG_BUFFER:
            self.runtime_log = self.runtime_log[-RUNTIME_LOG_BUFFER:]

    def _reset_engine_cycle_flags(self):
        """Called whenever the live engine is (re)prepared — clears the
        per-cycle bookkeeping so a PREVIOUS match's error/stop state can't
        bleed into the NEXT one's runtime-state computation."""
        self.admin_stopped = False
        self.last_team_code_kind = {"alpha": None, "beta": None}
        self.last_target = {"alpha": None, "beta": None}

    # ---- administrative controls (spec section 12) — all thin wrappers
    # around the existing BattleRunner methods, never a duplicate ----
    def _on_pause(self):
        if self.runtime_state != live_state.RUNNING:
            return
        self.runner.pause_battle()
        self._log_runtime("engine_pause")

    def _on_resume(self):
        if self.runtime_state != live_state.PAUSED:
            return
        self.runner.start_battle()  # BattleEngine has one flag; resume == start, same as the existing Resume-by-Start convention
        self._log_runtime("engine_resume")

    def _confirm_reset(self):
        """Reset requires confirmation (spec section 13)."""
        if messagebox.askyesno(t("reset"), t("confirm_reset_match")):
            self._do_reset()

    def _do_reset(self):
        if self.active_match_id is not None:
            self._stop_active_match(reason="reset")
        self._reset()
        self.engine_fault = False
        self._engine_faults = []
        self._reset_engine_cycle_flags()
        self._log_runtime("engine_reset")
        if hasattr(self, "live_monitor_view"):
            self.live_monitor_view.refresh()

    def _confirm_stop(self):
        """Stop requires confirmation (spec section 13)."""
        if self.active_match_id is None:
            return
        if messagebox.askyesno(t("stop"), t("confirm_stop_match")):
            self._stop_active_match(reason="stop")

    def _stop_active_match(self, reason: str = "stop"):
        """STOP (spec section 12): freezes the engine immediately and, if
        a competition Match owns it, records the match as ERROR via the
        existing TournamentService.error_match() — never a fake winner,
        never a normal (WIN/DRAW) MatchResult. The real, partial
        telemetry captured up to the abort point (self.match_events /
        the last snapshot) IS recorded, honestly labeled ERROR, exactly
        like Phase 5's already-tested error-result path."""
        self.runner.pause_battle()
        if self.active_match_id is not None:
            match_id = self.active_match_id
            snap = self._last_snapshot
            try:
                match = self.tournament_service.error_match(
                    match_id, "stopped_by_administrator", duration=snap["elapsed"] if snap else None,
                )
                if snap is not None:
                    self._record_match_result(match, snap)
            except TournamentValidationError:
                pass
            self._teardown_active_match()
        self.admin_stopped = True
        self._log_runtime("match_stop_for_reset" if reason == "reset" else "match_stop")
        self._push_alert(live_state.Alert(live_state.SEVERITY_WARNING, "alert_engine_stopped", {}, time.time()))

    def _sync_engine_state(self, force: bool = False):
        """The one place Managed Team -> Submission -> Sandbox ->
        BattleEngine AND Challenge -> Rules -> BattleConfig -> BattleEngine
        both actually connect. Pushes whichever teams are assigned to the
        alpha/beta slots (their code + name) and the active Challenge's
        BattleConfig into the live engine, then resets. Skipped while a
        battle is genuinely in progress unless `force` (the Reset button)
        is given, so an unrelated team/challenge edit elsewhere can never
        corrupt a live battle."""
        alpha_team = self.team_service.team_for_slot("alpha")
        beta_team = self.team_service.team_for_slot("beta")
        if not alpha_team or not beta_team:
            return

        snap = self._last_snapshot
        battle_ongoing = snap and (snap["running"] or (snap["tick_count"] > 0 and snap["winner"] is None))
        if battle_ongoing and not force:
            return

        active_challenge = self.challenge_service.get_active_challenge()

        try:
            alpha_code, alpha_name = self._resolve_battle_code(alpha_team, active_challenge, "Team Alpha")
            beta_code, beta_name = self._resolve_battle_code(beta_team, active_challenge, "Team Beta")
            self.runner.set_team_code("alpha", alpha_code)
            self.runner.set_team_code("beta", beta_code)
            self.team_code_cache["alpha"] = alpha_code
            self.team_code_cache["beta"] = beta_code
            self.code_valid["alpha"] = True
            self.code_valid["beta"] = True
        except (SandboxError, OSError):
            self.code_valid["alpha"] = False
            self.code_valid["beta"] = False
            return  # keep whatever was already loaded rather than crash or reset with broken code

        config = active_challenge.to_battle_config() if active_challenge else None
        if active_challenge:
            self.runner.set_difficulty(self._difficulty_level_number(active_challenge.difficulty))

        self.runner.reset_battle(team_a_name=alpha_name, team_b_name=beta_name, config=config)
        self.competition.ensure_team(alpha_name)
        self.competition.ensure_team(beta_name)
        self._reset_engine_cycle_flags()

    def _on_start_match(self, match_id: str):
        """The one bridge between tournament/tournament_service.py (which
        never touches BattleRunner) and the live engine — mirrors
        _sync_engine_state()'s role for regular battles. Section 31: the
        SAME BattleRunner the standalone Battle Arena already shows is
        used here, so the arena genuinely reflects the running Match
        rather than a separate/fake view.

        Phase 8 (BACKLOG #17): set_team_code() below spawns a fresh OS
        process per side (~100-200ms each, measured in Phase 7) on THIS
        thread — not fixed here (that would risk the exact regression the
        Phase 7 lock-free/locked split was built to prevent), but now made
        an honest, visible PREPARING state instead of a silent freeze:
        `_match_preparing` flips True and a paint is forced BEFORE the
        blocking calls, and flips back False (success or failure) before
        this method returns."""
        if self.active_match_id is not None or self._match_preparing:
            return  # a match is already running or already being prepared; do not stomp it
        snap = self._last_snapshot
        battle_ongoing = snap and (snap["running"] or (snap["tick_count"] > 0 and not snap["ended"]))
        if battle_ongoing:
            messagebox.showwarning(t("start_match"), t("match_not_eligible"))
            self._push_alert(live_state.Alert(live_state.SEVERITY_WARNING, "alert_match_cannot_start", {}, time.time()))
            return
        try:
            code_a, code_b, config, name_a, name_b = self.tournament_service.prepare_match_for_start(match_id)
        except TournamentValidationError:
            messagebox.showwarning(t("start_match"), t("match_not_eligible"))
            self._push_alert(live_state.Alert(live_state.SEVERITY_WARNING, "alert_match_cannot_start", {}, time.time()))
            return

        # prepare_match_for_start() already flipped the Match to RUNNING —
        # set the preparing flag and active_match_id immediately so no
        # second Start click (or a second queued invocation) can slip in
        # while the workers below are spawning.
        self._match_preparing = True
        self.active_match_id = match_id
        self.runtime_state = live_state.PREPARING
        # _last_snapshot can still be None this early (the very first
        # _tick() call is scheduled 66ms after App.__init__, so a match
        # started before that single tick has ever run would otherwise
        # crash topbar.update_status()/live_monitor's update_from_tick()
        # on an unconditional snapshot["..."] lookup) — skip this
        # immediate paint in that narrow window; the real _tick() a
        # moment later still correctly computes PREPARING once a
        # snapshot exists (self.runtime_state is already set above).
        if self._last_snapshot is not None:
            self.topbar.update_status(self._last_snapshot, live_state.PREPARING)
            if hasattr(self, "live_monitor_view"):
                self.live_monitor_view.update_from_tick(
                    snap=self._last_snapshot, runtime_state=live_state.PREPARING, active_match_id=self.active_match_id,
                    match_context=None, team_code_status=self.team_code_status, last_target=self.last_target,
                    live_events=self.live_events, alerts=self.alerts, runtime_log=self.runtime_log,
                    ui_update_hz=self.ui_update_hz, embedded_fps=None, engine_faults=self._engine_faults,
                    can_acknowledge_error=False,
                )
        self.update_idletasks()  # force the PREPARING paint before the blocking work below

        self.runner.set_team_code("alpha", code_a)
        self.runner.set_team_code("beta", code_b)
        self.runner.reset_battle(team_a_name=name_a, team_b_name=name_b, config=config)

        health = self.runner.worker_health()
        if health.get("alpha") or health.get("beta"):
            # A worker failed to even start — a clear, immediate ERROR,
            # never a match that silently goes RUNNING with a dead side.
            self._match_preparing = False
            self.active_match_id = None
            try:
                self.tournament_service.error_match(match_id, "worker_start_failed")
            except TournamentValidationError:
                pass
            self._push_alert(live_state.Alert(live_state.SEVERITY_ERROR, "alert_worker_start_failed", {}, time.time()))
            self._log_runtime("match_worker_start_failed", match_id=match_id)
            messagebox.showerror(t("start_match"), t("worker_start_failed"))
            if hasattr(self, "competitions_view"):
                self.competitions_view.refresh()
            if hasattr(self, "live_monitor_view"):
                self.live_monitor_view.refresh()
            return

        self.match_events = []  # fresh per-match event buffer — see _tick()
        self._reset_engine_cycle_flags()
        match = self.tournament_service.get_match(match_id)
        self.match_context = {
            "competition": self.tournament_service.get_competition(match.competition_id),
            "round": self.tournament_service.get_round(match.round_id),
            "match": match,
        }
        self._log_runtime("match_start", match_id=match_id)
        self.runner.start_battle()
        self._match_preparing = False
        if hasattr(self, "competitions_view"):
            self.competitions_view.refresh()
        if hasattr(self, "live_monitor_view"):
            self.live_monitor_view.refresh()

    def _finish_active_match(self, snap: dict):
        """Called from _tick() once the engine reports the battle ended
        while a competition Match owns it. Reads the outcome straight off
        the real BattleEngine snapshot — never computes a winner
        independently (spec section 20)."""
        match_id = self.active_match_id
        outcome_raw = snap.get("outcome")
        winner_name = snap.get("winner")
        match = self.tournament_service.get_match(match_id)

        if outcome_raw == "TIME_LIMIT_DRAW" or (outcome_raw == "DESTROY_ENEMY" and winner_name is None):
            outcome, winner_team_id = OUTCOME_DRAW, None
        elif winner_name == snap["ship_a"]["team"]:
            outcome, winner_team_id = OUTCOME_TEAM_A_WIN, match.team_a_id
        elif winner_name == snap["ship_b"]["team"]:
            outcome, winner_team_id = OUTCOME_TEAM_B_WIN, match.team_b_id
        else:
            outcome, winner_team_id = OUTCOME_ERROR, None

        try:
            completed_match = self.tournament_service.complete_match(match_id, outcome, winner_team_id, snap["elapsed"])
        except TournamentValidationError:
            completed_match = None

        if completed_match is not None:
            self._record_match_result(completed_match, snap)
            self._log_runtime("match_completed", match_id=match_id, outcome=outcome)
            if outcome == OUTCOME_DRAW:
                self._push_alert(live_state.Alert(live_state.SEVERITY_WARNING, "alert_match_draw", {}, time.time()))
            else:
                self._push_alert(live_state.Alert(live_state.SEVERITY_SUCCESS, "alert_match_completed", {}, time.time()))

        self._teardown_active_match()

    def _teardown_active_match(self):
        """Clears active-match ownership and refreshes every view that
        reads it — the ONE place this happens, called from both a normal
        completion (_finish_active_match) and an admin Stop
        (_stop_active_match), so ownership can never be left dangling."""
        self.active_match_id = None
        self.match_context = None
        self.match_events = []
        if hasattr(self, "competitions_view"):
            self.competitions_view.refresh()
        if hasattr(self, "results_view"):
            self.results_view.refresh()
        if hasattr(self, "live_monitor_view"):
            self.live_monitor_view.refresh()

    def _record_match_result(self, match, snap: dict):
        """Builds the real-battle telemetry (spec section 3: only metrics
        the engine actually produced) and hands it + the match's captured
        event timeline to ResultService. Damage totals are summed from
        `self.match_events` — the events accumulated tick-by-tick in
        _tick() from this same match's own runner.snapshot() calls, never
        a second, independent read of the engine (avoids the exact
        snapshot()-draining race a Phase 4 manual-verification script hit
        by calling snapshot() a second time outside _tick())."""
        ship_a, ship_b = snap["ship_a"], snap["ship_b"]
        name_a, name_b = ship_a["team"], ship_b["team"]

        def _dealt(team_name):
            return sum(
                e.data.get("amount", 0.0) for e in self.match_events
                if e.kind == ev.DAMAGE and e.team == team_name
            )

        def _received(team_name):
            return sum(
                e.data.get("amount", 0.0) for e in self.match_events
                if e.kind == ev.DAMAGE and e.data.get("target_team") == team_name
            )

        battle_stats = {
            "team_a_hp_remaining": ship_a["hp"], "team_b_hp_remaining": ship_b["hp"],
            "team_a_damage_dealt": _dealt(name_a), "team_b_damage_dealt": _dealt(name_b),
            "team_a_damage_received": _received(name_a), "team_b_damage_received": _received(name_b),
        }
        self.result_service.record_from_match(match, battle_stats, self.match_events)

    def _team_stats(self, team_name: str):
        self.competition.ensure_team(team_name)
        return self.competition.records[team_name]

    def _on_teams_changed(self):
        self._sync_engine_state(force=False)
        if hasattr(self, "submissions_view"):
            self.submissions_view.refresh_selectors_and_defaults()

    def _on_challenges_changed(self):
        self._sync_engine_state(force=False)
        if hasattr(self, "submissions_view"):
            self.submissions_view.refresh_selectors_and_defaults()

    # ---------------------------------------------------------------- layout
    def _build_layout(self):
        # BattlePanel owns a live pygame display (embedded via SDL_WINDOWID)
        # and a scheduled after() render callback. Destroying its Tk frame
        # without shutting that down first leaves the render job pointing
        # at a dead window while the *next* BattlePanel tries to init a new
        # display at the same time — a real race that crashed pygame's SDL
        # layer during testing. Always shut it down before it's destroyed.
        if hasattr(self, "battle_panel"):
            try:
                self.battle_panel.shutdown()
            except Exception:
                pass

        for w in self.winfo_children():
            w.destroy()

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.topbar = TopBar(self, self.tokens, self._set_language, self._toggle_theme)
        self.topbar.grid(row=0, column=0, columnspan=2, sticky="ew")

        self.sidebar = Sidebar(self, self.tokens, self._on_nav_select)
        sidebar_col = 1 if localization.is_rtl() else 0
        main_col = 0 if localization.is_rtl() else 1
        self.sidebar.grid(row=1, column=sidebar_col, rowspan=2, sticky="ns")

        self.main_area = ctk.CTkFrame(self, fg_color=self.tokens.bg, corner_radius=0)
        self.main_area.grid(row=1, column=main_col, sticky="nsew", padx=12, pady=(10, 6))
        self.main_area.grid_columnconfigure(0, weight=16)
        self.main_area.grid_columnconfigure(1, weight=10)
        self.main_area.grid_rowconfigure(0, weight=1)

        self.bottom_area = ctk.CTkFrame(self, fg_color=self.tokens.bg, corner_radius=0)
        self.bottom_area.grid(row=2, column=main_col, sticky="ew", padx=12, pady=(0, 12))
        self.bottom_area.grid_columnconfigure(0, weight=1)
        self.bottom_area.grid_columnconfigure(1, weight=1)

        self.placeholder = ctk.CTkLabel(
            self.main_area, text="", font=theme.font(14), text_color=self.tokens.text_faint,
        )

        self._build_dashboard_content()
        self._build_teams_content()
        self._build_challenges_content()
        self._build_submissions_content()
        self._build_competition_content()
        self._build_results_content()
        self._build_live_monitor_content()
        self._build_bottom()

    def _build_dashboard_content(self):
        left = self.dashboard_left = ctk.CTkFrame(self.main_area, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_rowconfigure(1, weight=1)

        controls = ctk.CTkFrame(left, fg_color=self.tokens.panel, corner_radius=10)
        controls.pack(fill="x", pady=(0, 8))
        self.start_btn = ctk.CTkButton(controls, text=t("start"), fg_color=self.tokens.accent, command=self.runner.start_battle)
        self.start_btn.pack(side="left", padx=8, pady=8)
        self.pause_btn = ctk.CTkButton(controls, text=t("pause"), fg_color=self.tokens.panel_2, command=self.runner.pause_battle)
        self.pause_btn.pack(side="left", padx=4, pady=8)
        self.reset_btn = ctk.CTkButton(
            controls, text=t("reset"), fg_color="transparent", border_width=1,
            border_color=self.tokens.danger, text_color=self.tokens.danger, command=self._confirm_reset,
        )
        self.reset_btn.pack(side="left", padx=4, pady=8)

        self.match_context_lbl = ctk.CTkLabel(controls, text="", font=theme.font(10, "bold"), text_color=self.tokens.accent_glow)
        self.match_context_lbl.pack(side="right", padx=10)

        self.battle_panel = BattlePanel(left, self.tokens, self.runner)
        self.battle_panel.pack(fill="both", expand=True)

        self.battle_log = BattleLog(left, self.tokens)
        self.battle_log.configure(height=160)
        self.battle_log.pack(fill="x", pady=(8, 0))

        right = self.dashboard_right = ctk.CTkFrame(self.main_area, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")

        self.team_panel = TeamPanel(right, self.tokens)
        self.team_panel.pack(fill="x", pady=(0, 8))

        self.difficulty_panel = DifficultyPanel(right, self.tokens, self.runner.set_difficulty)
        self.difficulty_panel.pack(fill="x", pady=(0, 8))

        # Phase 3: the quick inline code editor that used to live here
        # called BattleRunner.set_team_code() directly on every "Run" —
        # a live hot-swap that completely bypassed the new submission /
        # versioning / immutability system (a team could edit and Run
        # over a SUBMITTED, supposedly-locked version). Editing now only
        # happens in the "Python Code" tab's SubmissionWorkspace, which
        # writes to a draft submission — never straight to the engine.
        note = ctk.CTkFrame(right, fg_color=self.tokens.panel, corner_radius=10)
        note.pack(fill="both", expand=True)
        ctk.CTkLabel(
            note, text=t("nav_code"), font=theme.font(12, "bold"), text_color=self.tokens.text,
        ).pack(anchor="w", padx=14, pady=(12, 4))
        ctk.CTkLabel(
            note, text=t("open_python_code_tab"), font=theme.font(11), text_color=self.tokens.text_faint,
            wraplength=260, justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 12))

    def _build_teams_content(self):
        self.teams_view = TeamsView(
            self.main_area, self.tokens, self.team_service,
            get_stats=self._team_stats, on_changed=self._on_teams_changed,
        )
        self.teams_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.teams_view.grid_remove()

    def _build_challenges_content(self):
        self.challenges_view = ChallengesView(
            self.main_area, self.tokens, self.challenge_service, on_changed=self._on_challenges_changed,
        )
        self.challenges_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.challenges_view.grid_remove()

    def _build_submissions_content(self):
        self.submissions_view = SubmissionWorkspace(
            self.main_area, self.tokens, self.team_service, self.challenge_service,
            self.submission_service, get_starter_code=self._read_team_starter_code,
            on_changed=self._on_submissions_changed,
        )
        self.submissions_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.submissions_view.grid_remove()

    def _build_competition_content(self):
        self.competitions_view = CompetitionView(
            self.main_area, self.tokens, self.tournament_service, self.team_service,
            self.challenge_service, self.submission_service,
            on_start_match=self._on_start_match, on_changed=self._on_competition_changed,
        )
        self.competitions_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.competitions_view.grid_remove()

    def _on_competition_changed(self):
        pass  # tournament data doesn't feed back into the live engine except via _on_start_match

    def _build_results_content(self):
        self.results_view = ResultsView(
            self.main_area, self.tokens, self.result_service, self.tournament_service,
            self.team_service, self.challenge_service,
        )
        self.results_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.results_view.grid_remove()

    def _build_live_monitor_content(self):
        self.live_monitor_view = LiveMonitorView(
            self.main_area, self.tokens,
            tournament_service=self.tournament_service, team_service=self.team_service,
            challenge_service=self.challenge_service, result_service=self.result_service,
            on_start_match=self._on_start_match, on_pause=self._on_pause, on_resume=self._on_resume,
            on_confirm_reset=self._confirm_reset, on_confirm_stop=self._confirm_stop,
            on_acknowledge_error=self._on_acknowledge_error,
        )
        self.live_monitor_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.live_monitor_view.grid_remove()

    def _build_bottom(self):
        self.status_bar = StatusBar(self.bottom_area, self.tokens)
        self.status_bar.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.scoreboard = Scoreboard(self.bottom_area, self.tokens)
        self.scoreboard.grid(row=0, column=1, sticky="ew", padx=(6, 0))

    # --------------------------------------------------------------- events
    def _reset(self):
        self._sync_engine_state(force=True)
        alpha_team = self.team_service.team_for_slot("alpha")
        beta_team = self.team_service.team_for_slot("beta")
        names = [team.name for team in (alpha_team, beta_team) if team]
        self.competition = CompetitionTracker(names)
        self.team_service.competition_tracker = self.competition

    def _on_submissions_changed(self):
        self._sync_engine_state(force=False)

    def _on_nav_select(self, key: str, implemented: bool):
        self.placeholder.grid_remove()
        self.teams_view.grid_remove()
        self.challenges_view.grid_remove()
        self.submissions_view.grid_remove()
        self.competitions_view.grid_remove()
        self.results_view.grid_remove()
        self.live_monitor_view.grid_remove()
        self.dashboard_left.grid_remove()
        self.dashboard_right.grid_remove()

        if key == "teams":
            self.teams_view.refresh()
            self.teams_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        elif key == "challenges":
            self.challenges_view.refresh()
            self.challenges_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        elif key == "code":
            self.submissions_view.refresh_selectors_and_defaults()
            self.submissions_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        elif key == "competition":
            self.competitions_view.refresh()
            self.competitions_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        elif key == "leaderboard":
            self.results_view.refresh()
            self.results_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        elif key == "live":
            self.live_monitor_view.refresh()
            self.live_monitor_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        elif implemented:
            self.dashboard_left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
            self.dashboard_right.grid(row=0, column=1, sticky="nsew")
        else:
            self.placeholder.configure(text=f"{t(f'nav_{key}')}\n\n{t('not_built_yet')}")
            self.placeholder.grid(row=0, column=0, columnspan=2, sticky="nsew")

    def _set_language(self, lang: str):
        localization.set_lang(lang)
        self._build_layout()

    def _toggle_theme(self):
        self.tokens.set_mode("light" if self.tokens.mode == "dark" else "dark")
        ctk.set_appearance_mode(self.tokens.mode)
        self.configure(fg_color=self.tokens.bg)
        self._build_layout()

    # ----------------------------------------------------------------- tick
    def _tick(self):
        """The ONE authoritative event-drain point (spec section 25).
        `runner.snapshot()` is called exactly once per tick, right here —
        every other component (BattlePanel excepted; it renders straight
        from the engine at its own 60fps pygame clock, same as before
        Phase 6) reads `snap`/`new_events` handed to it from this single
        call, never calling snapshot() itself. This is the same
        discipline _is_team_active()/_record_match_result()'s docstrings
        already establish; Phase 6 just widens the set of consumers fed
        from this one call (live event stream, alerts, team code status,
        runtime state) rather than introducing a second drain point."""
        now = time.perf_counter()
        if self._last_tick_perf is not None and now > self._last_tick_perf:
            self.ui_update_hz = 1.0 / (now - self._last_tick_perf)
        self._last_tick_perf = now

        snap = self.runner.snapshot()
        self._last_snapshot = snap
        new_events = snap["new_events"]

        # ---- single-drain distribution ----
        self.competition.ingest(new_events)
        self.live_events.extend(new_events)
        if len(self.live_events) > LIVE_EVENT_BUFFER:
            self.live_events = self.live_events[-LIVE_EVENT_BUFFER:]
        self._update_team_code_status(snap, new_events)
        for alert in live_state.alerts_from_events(new_events, snap["ship_a"]["team"], snap["ship_b"]["team"]):
            self._push_alert(alert)

        if self.active_match_id is not None:
            self.match_events.extend(new_events)
            if snap["ended"]:
                self._finish_active_match(snap)
            elif hasattr(self, "match_context") and self.match_context:
                ctx = self.match_context
                self.match_context_lbl.configure(
                    text=f"{t('competition_context')}: {ctx['competition'].name} · "
                         f"{ctx['round'].name} · #{ctx['match'].match_number}",
                )
        elif hasattr(self, "match_context_lbl"):
            self.match_context_lbl.configure(text="")
        self.competition.ensure_team(snap["ship_a"]["team"])
        self.competition.ensure_team(snap["ship_b"]["team"])

        self.runtime_state = live_state.compute_runtime_state(
            snap, self.active_match_id, self.admin_stopped, self.engine_fault,
            preparing=self._match_preparing,
        )
        is_draw = live_state.is_draw_outcome(snap)

        self.topbar.update_status(snap, self.runtime_state)

        ranked = self.competition.ranked()
        score_map = {r.team: r.score for r in ranked}
        self.team_panel.update_from_snapshot(
            snap, score_map.get(snap["ship_a"]["team"], 0), score_map.get(snap["ship_b"]["team"], 0), is_draw,
            team_a=self.team_service.team_for_slot("alpha"), team_b=self.team_service.team_for_slot("beta"),
        )

        ship_by_team = {snap["ship_a"]["team"]: snap["ship_a"], snap["ship_b"]["team"]: snap["ship_b"]}
        rows = []
        for i, rec in enumerate(ranked, start=1):
            ship = ship_by_team.get(rec.team)
            if ship is not None:
                status_key = status_style.ship_battle_status(ship, is_draw)
            else:
                status_key = "active"  # a managed team not currently loaded into either slot
            rows.append({
                "rank": i, "team": rec.team, "score": rec.score, "wins": rec.wins,
                "losses": rec.losses, "damage": rec.damage_dealt, "status_key": status_key,
            })
        self.scoreboard.update_rows(rows)
        self.battle_log.update_lines(snap["log_tail"])

        overall_valid = self.code_valid["alpha"] and self.code_valid["beta"]
        embedded_fps = self.battle_panel.last_fps if self.battle_panel.embedded else None
        self.status_bar.update_values(snap, overall_valid, embedded_fps)

        if hasattr(self, "live_monitor_view"):
            self.live_monitor_view.update_from_tick(
                snap=snap, runtime_state=self.runtime_state, active_match_id=self.active_match_id,
                match_context=getattr(self, "match_context", None), team_code_status=self.team_code_status,
                last_target=self.last_target, live_events=self.live_events, alerts=self.alerts,
                runtime_log=self.runtime_log, ui_update_hz=self.ui_update_hz, embedded_fps=embedded_fps,
                engine_faults=self._engine_faults, can_acknowledge_error=self.can_acknowledge_error(),
            )

        # Refresh the Teams list periodically (not every tick — rebuilding
        # it destroys/recreates widgets, which would wipe out anything the
        # admin is mid-typing in a create/edit form) and only in list mode,
        # so live stats stay current without fighting the admin's input.
        self._teams_refresh_counter = getattr(self, "_teams_refresh_counter", 0) + 1
        if (
            hasattr(self, "teams_view") and self.teams_view.winfo_ismapped()
            and self.teams_view.mode == "list" and self._teams_refresh_counter % 15 == 0
        ):
            self.teams_view.refresh()

        self.after(66, self._tick)

    def _update_team_code_status(self, snap: dict, new_events: list):
        """Updates last_team_code_kind/last_target from this tick's real
        events only (part of the single-drain distribution above), then
        recomputes team_code_status via the pure function in live_state.py."""
        name_a, name_b = snap["ship_a"]["team"], snap["ship_b"]["team"]
        for e in new_events:
            if e.kind in (ev.CODE_EXECUTED, ev.CODE_ERROR, ev.CODE_TIMEOUT):
                if e.team == name_a:
                    self.last_team_code_kind["alpha"] = e.kind
                elif e.team == name_b:
                    self.last_team_code_kind["beta"] = e.kind
            elif e.kind == ev.TARGET_ACQUIRED:
                target_id = e.data.get("target_id")
                target_name = name_b if target_id == "beta" else (name_a if target_id == "alpha" else None)
                if e.team == name_a:
                    self.last_target["alpha"] = target_name
                elif e.team == name_b:
                    self.last_target["beta"] = target_name
        self.team_code_status = {
            "alpha": live_state.compute_team_code_status(snap, name_a, self.last_team_code_kind["alpha"]),
            "beta": live_state.compute_team_code_status(snap, name_b, self.last_team_code_kind["beta"]),
        }

    def _on_close(self):
        try:
            self.battle_panel.shutdown()
        except Exception:
            pass
        # stop_thread() already calls engine.shutdown_workers() (see
        # engine/runner.py) — no isolated worker process may outlive the
        # app (spec section 6/35).
        self.runner.stop_thread()
        self.destroy()


def main():
    # Phase 8 (Step 10): a corrupted data/*.json file used to propagate
    # CorruptedDataError all the way out of App.__init__() as a raw,
    # unhandled traceback — the exact "no normal user action should
    # result in a raw traceback window" case the spec calls out. This is
    # the one place that can happen (every repository is constructed
    # inside App.__init__()), so it's the one place that needs to catch
    # it and show a clear, bilingual, actionable message instead. No data
    # is touched/repaired here — same "never silently overwrite" rule
    # storage.py itself documents.
    try:
        app = App()
    except CorruptedDataError as e:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            t("startup_corrupted_data_title"),
            t("startup_corrupted_data_body").format(detail=str(e)),
        )
        root.destroy()
        sys.exit(1)
    app.mainloop()


if __name__ == "__main__":
    main()
