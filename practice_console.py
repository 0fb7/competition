"""Participant Practice Console — a separate, stripped-down distributable
for competitors to practice writing and testing their ship's decide()
function before the real event.

This is intentionally a standalone script, not a mode of the main
dashboard (ui/app.py): it has no navigation, no Teams/Challenges/
Competition/Live Monitoring/Results screens, and no access to the
organizer's data/ directory at all. There is nothing to hide because
nothing else exists in this window. It reuses ui/code_editor.py,
ui/theme.py, and the engine's own sandbox/isolation exactly as the main
app's "Test" workflow does, but talks directly to BattleEngine instead of
going through submissions/submission_service.py — a participant using
this tool has no Team/Challenge/Submission records at all, just code.

Run from the project root:
    python practice_console.py

The exported .py file (via the "Export Code" button) is what a
participant later pastes into the real Submission Workspace (Python Code
tab) in the main application before the actual competition.
"""

from __future__ import annotations

import os
import sys
import time
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox

import customtkinter as ctk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.battle import BattleEngine
from engine.config import BattleConfig
from engine.runner import BattleRunner
from engine.sandbox import SandboxError
from engine import events as ev
from submissions.submission import TestResult, TEST_ERROR, TEST_FAILED, TEST_PASSED, TEST_TIMEOUT
from ui import theme, branding
from ui.battle_panel import BattlePanel
from ui.code_editor import CodeEditor

# ---------------------------------------------------------------- opponents
# Three fixed, built-in practice opponents of increasing sophistication.
# None of these is a real team's code and none is ever used by the real
# Test workflow in the main app (submissions/test_runner.py has its own,
# separate built-in opponent) — practicing here never touches, and is
# never touched by, the organizer's competition data.

EASY_OPPONENT_CODE = '''# Practice opponent - EASY
# Never chases. Only attacks if a target already happens to be in range.
def decide(friendly, enemies, api):
    target = api["find_nearest"](enemies)
    if target is None:
        api["hold_position"]()
        return
    if friendly["attack_ready"] and api["distance_to"](target) <= 10.0:
        api["attack"](target)
    else:
        api["hold_position"]()
'''

MEDIUM_OPPONENT_CODE = '''# Practice opponent - MEDIUM
# Chases the nearest enemy and attacks whenever in range.
def decide(friendly, enemies, api):
    target = api["find_nearest"](enemies)
    if target is None:
        api["hold_position"]()
        return
    if friendly["attack_ready"] and api["distance_to"](target) <= 10.0:
        api["attack"](target)
        api["log"]("engaging", target["name"])
    else:
        api["move_toward"](target["x"], target["y"])
'''

HARD_OPPONENT_CODE = '''# Practice opponent - HARD
# Chases and attacks, but also manages energy and disengages when hurt.
def decide(friendly, enemies, api):
    target = api["find_nearest"](enemies)
    if target is None:
        api["hold_position"]()
        return

    dist = api["distance_to"](target)

    if friendly["hp_pct"] < 0.3 or friendly["energy_pct"] < 0.25:
        away_x = friendly["x"] - (target["x"] - friendly["x"])
        away_y = friendly["y"] - (target["y"] - friendly["y"])
        api["move_toward"](away_x, away_y)
        api["log"]("disengaging")
        return

    if friendly["attack_ready"] and dist <= 10.0:
        api["attack"](target)
        api["log"]("firing", target["name"])
    elif dist > 10.0:
        api["move_toward"](target["x"], target["y"])
    else:
        api["hold_position"]()
'''

DIFFICULTIES = {
    "Easy": EASY_OPPONENT_CODE,
    "Medium": MEDIUM_OPPONENT_CODE,
    "Hard": HARD_OPPONENT_CODE,
}

CANDIDATE_NAME = "You"
OPPONENT_NAME = "AI Opponent"
# Real-time wall-clock cap on a live practice battle (there is no
# Challenge-configured battle_duration here — BattleConfig() defaults to
# None, i.e. no automatic time-limit draw), mirroring the same 30-second
# ceiling submissions/test_runner.py's offline run_test() uses.
MAX_BATTLE_WALL_SECONDS = 30.0

STARTER_CODE = '''def decide(friendly, enemies, api):
    # Write your ship's strategy here.
    #
    # Available on `api`:
    #   api["move_toward"](x, y)      - move toward a point
    #   api["hold_position"]()        - stop moving
    #   api["attack"](target)         - attack a target (must be in range and ready)
    #   api["find_nearest"](enemies)  - nearest visible enemy, or None
    #   api["distance_to"](target)    - distance to a target
    #   api["log"](*parts)            - write a line to the battle log
    #
    # `friendly` is your own ship's state: x, y, hp, hp_pct, energy,
    # energy_pct, alive, attack_ready, attack_cooldown.

    api["hold_position"]()
'''


def classify_result(engine: BattleEngine, config: BattleConfig, start_wall: float) -> TestResult:
    """Same PASSED/FAILED/TIMEOUT/ERROR classification submissions/
    test_runner.py::run_test() uses, applied to a battle that was watched
    live via BattleRunner instead of stepped through headlessly. Reaching
    MAX_BATTLE_WALL_SECONDS without engine.ended (a stalemate, nobody's
    decide() ever misbehaving) is NOT a TEST_TIMEOUT — that status is
    reserved for a real ev.CODE_TIMEOUT event (a specific decide() call
    itself running too long). A stalemate that simply ran out of practice
    time falls through to the same alive/dead check run_test()'s original
    900-tick cap always used: still alive when time runs out = PASSED."""
    events = engine.events.all()
    candidate_timed_out = any(
        e.kind == ev.CODE_TIMEOUT and e.team == CANDIDATE_NAME for e in events
    )
    candidate_errors = [e.message for e in events if e.kind == ev.CODE_ERROR and e.team == CANDIDATE_NAME]
    damage_dealt = sum(
        e.data.get("amount", 0.0) for e in events if e.kind == ev.DAMAGE and e.team == CANDIDATE_NAME
    )

    result_errors = candidate_errors[:5]
    if candidate_timed_out:
        status = TEST_TIMEOUT
        result_errors = [f"decide() exceeded {config.code_execution_timeout:.1f}s and was terminated"]
    elif candidate_errors:
        status = TEST_ERROR
    elif engine.ship_a.alive:
        status = TEST_PASSED
        result_errors = []
    else:
        status = TEST_FAILED
        result_errors = []

    return TestResult(
        passed=(status == TEST_PASSED),
        status=status,
        winner=engine.winner,
        duration=time.perf_counter() - start_wall,
        errors=result_errors,
        final_hp=engine.ship_a.hp,
        damage_dealt=damage_dealt,
        events_count=len(events),
    )


STATUS_COLORS = {
    TEST_PASSED: theme.SUCCESS,
    TEST_FAILED: theme.WARNING,
    TEST_TIMEOUT: theme.DANGER,
    TEST_ERROR: theme.DANGER,
}
STATUS_LABELS = {
    TEST_PASSED: "PASSED",
    TEST_FAILED: "FAILED",
    TEST_TIMEOUT: "TIMEOUT",
    TEST_ERROR: "ERROR",
}


class PracticeConsole(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.tokens = theme.Tokens("dark")
        self.title("code Battleship - Programming Club")
        branding.set_window_icon(self, "assets/logo.png")
        self.geometry("1300x820")
        self.minsize(1020, 680)
        self.configure(fg_color=self.tokens.bg)

        self._testing = False
        self.arena_panel = None      # BattlePanel — only exists while/after a battle has run
        self._active_runner = None   # BattleRunner for the in-progress (or just-finished) live battle
        self._active_engine = None
        self._battle_start_wall = None
        self._battle_config = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 6))
        logo_image = branding.load_logo_ctkimage(height=28)
        if logo_image is not None:
            ctk.CTkLabel(header, image=logo_image, text="").pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            header, text="PRACTICE CONSOLE", font=theme.font(16, "bold"), text_color=self.tokens.text,
        ).pack(side="left")
        ctk.CTkLabel(
            header, text="Practice only — this is not a real competition submission",
            font=theme.font(10), text_color=self.tokens.text_faint,
        ).pack(side="left", padx=(12, 0))

        diff_row = ctk.CTkFrame(self, fg_color="transparent")
        diff_row.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkLabel(diff_row, text="Opponent Difficulty", font=theme.font(11, "bold"), text_color=self.tokens.text_dim).pack(side="left", padx=(0, 8))
        self.difficulty_var = ctk.StringVar(value="Medium")
        self.difficulty_menu = ctk.CTkSegmentedButton(
            diff_row, values=list(DIFFICULTIES.keys()), variable=self.difficulty_var,
            fg_color=self.tokens.panel_2, selected_color=self.tokens.accent,
        )
        self.difficulty_menu.pack(side="left")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=3)
        body.grid_rowconfigure(1, weight=2)

        self.editor = CodeEditor(body, self.tokens, on_change=self._on_code_changed)
        self.editor.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 8))
        self.editor.load_code(STARTER_CODE, "practice_ship.py", read_only=False)
        self.editor.set_toolbar_buttons([
            {"text": "Test", "kind": "primary", "command": self._start_test},
            {"text": "Export Code", "kind": "neutral", "command": self._export_code},
        ])

        self.arena_container = ctk.CTkFrame(body, fg_color=self.tokens.panel, corner_radius=10)
        self.arena_container.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        self._render_empty_arena()

        self.result_panel = ctk.CTkFrame(body, fg_color=self.tokens.panel, corner_radius=10)
        self.result_panel.grid(row=1, column=1, sticky="nsew")
        self._render_empty_result()

    # -------------------------------------------------------------- arena panel
    def _render_empty_arena(self):
        for w in self.arena_container.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.arena_container, text="Battle Arena", font=theme.font(12, "bold"), text_color=self.tokens.text,
        ).pack(anchor="w", padx=14, pady=(12, 4))
        ctk.CTkLabel(
            self.arena_container, text="Click Test to watch your ship fight live.",
            font=theme.font(10), text_color=self.tokens.text_faint,
        ).pack(anchor="w", padx=14)

    def _show_live_arena(self, runner: BattleRunner):
        for w in self.arena_container.winfo_children():
            w.destroy()
        # A fresh BattlePanel per battle — it binds to one runner for its
        # whole life (same as ui/app.py's single long-lived one), so a new
        # instance is built for every Test rather than trying to rebind an
        # existing one.
        self.arena_panel = BattlePanel(self.arena_container, self.tokens, runner, width=440, height=320)
        self.arena_panel.pack(fill="both", expand=True, padx=8, pady=8)

    # -------------------------------------------------------------- result panel
    def _clear_result_panel(self):
        for w in self.result_panel.winfo_children():
            w.destroy()

    def _render_empty_result(self):
        self._clear_result_panel()
        ctk.CTkLabel(
            self.result_panel, text="Test Result", font=theme.font(12, "bold"), text_color=self.tokens.text,
        ).pack(anchor="w", padx=14, pady=(14, 6))
        ctk.CTkLabel(
            self.result_panel, text="Click Test to run your code against the selected AI opponent.",
            font=theme.font(10), text_color=self.tokens.text_faint, wraplength=260, justify="left",
        ).pack(anchor="w", padx=14)

    def _render_result(self, result: TestResult):
        self._clear_result_panel()
        color = STATUS_COLORS.get(result.status, self.tokens.text_faint)
        label = STATUS_LABELS.get(result.status, result.status)

        ctk.CTkLabel(
            self.result_panel, text="Test Result", font=theme.font(12, "bold"), text_color=self.tokens.text,
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ctk.CTkLabel(
            self.result_panel, text=label, font=theme.font(15, "bold"), text_color=color,
        ).pack(anchor="w", padx=14, pady=(0, 10))

        rows = [
            ("Winner", result.winner or "-"),
            ("Final HP", f"{result.final_hp:.0f}" if result.final_hp is not None else "-"),
            ("Duration", f"{result.duration:.2f}s"),
            ("Events", str(result.events_count)),
        ]
        for label_text, value in rows:
            row = ctk.CTkFrame(self.result_panel, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=2)
            ctk.CTkLabel(row, text=label_text, font=theme.font(10), text_color=self.tokens.text_faint, width=80, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=value, font=theme.font(10, mono=True), text_color=self.tokens.text).pack(side="left")

        if result.errors:
            ctk.CTkLabel(
                self.result_panel, text="Details", font=theme.font(11, "bold"), text_color=self.tokens.danger,
            ).pack(anchor="w", padx=14, pady=(12, 4))
            for err in result.errors[:5]:
                ctk.CTkLabel(
                    self.result_panel, text=f"• {err}", font=theme.font(9, mono=True),
                    text_color=self.tokens.text_dim, wraplength=260, justify="left", anchor="w",
                ).pack(anchor="w", padx=14, pady=1)

    # -------------------------------------------------------------- actions
    def _on_code_changed(self):
        pass

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.difficulty_menu.configure(state=state)
        self.editor.set_toolbar_buttons([
            {"text": "Test", "kind": "primary", "command": self._start_test if enabled else (lambda: None)},
            {"text": "Export Code", "kind": "neutral", "command": self._export_code if enabled else (lambda: None)},
        ])

    def _teardown_previous_battle(self):
        """Stops and cleans up whatever the last Test started, if
        anything — every worker process and background thread must be
        gone before a new one starts (mirrors ui/app.py's one-runner-at-a-
        time discipline, just re-created per test instead of reused)."""
        if self.arena_panel is not None:
            self.arena_panel.shutdown()
        if self._active_runner is not None:
            self._active_runner.stop_thread()  # also calls engine.shutdown_workers()
        self._active_runner = None
        self._active_engine = None

    def _start_test(self):
        if self._testing:
            return
        self._teardown_previous_battle()

        code = self.editor.get_code()
        difficulty = self.difficulty_var.get()
        opponent_code = DIFFICULTIES.get(difficulty, MEDIUM_OPPONENT_CODE)
        config = BattleConfig()

        try:
            engine = BattleEngine(
                code, opponent_code, config=config,
                team_a_name=CANDIDATE_NAME, team_b_name=OPPONENT_NAME,
                isolate_execution=True,
            )
        except SandboxError as e:
            self._render_result(TestResult(passed=False, status=TEST_ERROR, errors=[str(e)], duration=0.0))
            return

        self._testing = True
        self._set_controls_enabled(False)
        self.editor.set_status_text("Testing...", self.tokens.accent_glow)
        self._clear_result_panel()
        ctk.CTkLabel(
            self.result_panel, text="Battle in progress — watch the arena.",
            font=theme.font(10), text_color=self.tokens.text_faint,
        ).pack(anchor="w", padx=14, pady=14)

        self._active_engine = engine
        self._active_runner = BattleRunner(engine, tick_hz=30)
        self._battle_config = config
        self._battle_start_wall = time.perf_counter()
        self._show_live_arena(self._active_runner)

        self._active_runner.start_thread()
        self._active_runner.start_battle()
        self.after(66, self._poll_live_battle)

    def _poll_live_battle(self):
        runner = self._active_runner
        if runner is None:
            return  # a new test already tore this one down
        snap = runner.snapshot()
        elapsed_wall = time.perf_counter() - self._battle_start_wall
        timed_out_wall = elapsed_wall > MAX_BATTLE_WALL_SECONDS
        if not snap["ended"] and not timed_out_wall:
            self.after(66, self._poll_live_battle)
            return

        result = classify_result(self._active_engine, self._battle_config, self._battle_start_wall)
        self._active_runner.stop_thread()
        self._active_runner = None
        self._active_engine = None
        self._testing = False
        self._set_controls_enabled(True)
        self.editor.set_status_text("", self.tokens.text_faint)
        self._render_result(result)

    def _on_close(self):
        self._teardown_previous_battle()
        self.destroy()

    def _export_code(self):
        code = self.editor.get_code()
        path = filedialog.asksaveasfilename(
            title="Export Code",
            defaultextension=".py",
            filetypes=[("Python file", "*.py")],
            initialfile="my_ship.py",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
        except OSError as e:
            messagebox.showerror("Export Code", f"Could not save the file: {e}")
            return
        messagebox.showinfo("Export Code", f"Code exported to:\n{path}")


def main():
    app = PracticeConsole()
    app.mainloop()


if __name__ == "__main__":
    main()
