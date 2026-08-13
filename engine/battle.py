"""Core battle loop: ticks both ships' team code, resolves movement and
attacks, and tracks the event log + win condition."""

import time

from .api import build_api
from .config import BattleConfig
from .sandbox import compile_team_module, run_decide
from .ship import Ship
from . import events as ev
from .events import EventBus


class BattleEngine:
    def __init__(
        self, team_a_code: str, team_b_code: str, difficulty: int = 2,
        team_a_name: str | None = None, team_b_name: str | None = None,
        config: BattleConfig | None = None,
    ):
        self._team_a_code = team_a_code
        self._team_b_code = team_b_code
        self.decide_a = compile_team_module(team_a_code)
        self.decide_b = compile_team_module(team_b_code)
        # Configuration only — see difficulty.py / ui/difficulty_panel.py.
        # No engine behavior currently changes based on this value; it exists
        # so the UI has something real to persist and display rather than a
        # value that silently does nothing with no acknowledgement anywhere.
        self.difficulty = difficulty
        # The active Challenge's rules (challenges/challenge.py), converted
        # to a BattleConfig. Defaulting to BattleConfig() reproduces the
        # exact numeric values this project shipped with before Phase 2 —
        # that's what makes "no Challenge selected" behave identically to
        # the old hardcoded engine.
        self.config = config or BattleConfig()
        self._reset_state(team_a_name, team_b_name)

    def _reset_state(
        self, team_a_name: str | None = None, team_b_name: str | None = None,
        config: BattleConfig | None = None,
    ):
        # roster/team_service.py (Phase 1 team management) can rename a
        # team; passing the new name through here is how that rename
        # reaches the live ship without a second, UI-side battle state.
        # With no override, keep whatever name the engine already had
        # (or the original defaults, on first construction).
        prev_a = getattr(self, "ship_a", None)
        prev_b = getattr(self, "ship_b", None)
        ta = team_a_name or (prev_a.team if prev_a else "Team Alpha")
        tb = team_b_name or (prev_b.team if prev_b else "Team Beta")

        if config is not None:
            self.config = config

        self.ship_a = Ship(id="alpha", team=ta, name="Falcon-01", x=6.0, y=16.0, config=self.config)
        self.ship_b = Ship(id="beta", team=tb, name="Titan-02", x=32.0, y=6.0, config=self.config)

        self.log: list[str] = []
        self.events = EventBus()
        self.tick_count = 0
        self.elapsed = 0.0
        self.running = False
        self.winner: str | None = None
        self.ended = False
        self.outcome: str | None = None

    @property
    def ships(self):
        return (self.ship_a, self.ship_b)

    def start(self):
        self.running = True

    def pause(self):
        self.running = False

    def reset(
        self, team_a_name: str | None = None, team_b_name: str | None = None,
        config: BattleConfig | None = None,
    ):
        self._reset_state(team_a_name, team_b_name, config)

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.append(f"{ts}  {msg}")
        if len(self.log) > 200:
            self.log = self.log[-200:]

    def _run_side(self, mover: Ship, opponent: Ship, decide_fn) -> dict:
        pending = {
            "move_target": None,
            "attack_target_id": None,
            "log": [],
            "_self": mover.snapshot(),
        }
        api = build_api(pending, self.config)
        status = run_decide(decide_fn, mover.snapshot(), [opponent.snapshot()], api)
        if status != "ok":
            self._log(f"{mover.team} code error - {status}")
            self.events.emit(ev.CODE_ERROR, mover.team, status)
        for line in pending["log"]:
            self._log(f"{mover.team}: {line}")
            self.events.emit(ev.CODE_EXECUTED, mover.team, line)
        if pending["attack_target_id"] == opponent.id:
            self.events.emit(
                ev.TARGET_ACQUIRED, mover.team, f"Target acquired: {opponent.name}",
                target_id=opponent.id,
            )
        return pending

    def step(self, dt: float) -> None:
        if not self.running or self.ended:
            return

        for ship in self.ships:
            ship.tick_cooldowns(dt)

        pending_a = self._run_side(self.ship_a, self.ship_b, self.decide_a)
        pending_b = self._run_side(self.ship_b, self.ship_a, self.decide_b)

        for ship, pending in ((self.ship_a, pending_a), (self.ship_b, pending_b)):
            if pending["move_target"] is not None and pending["attack_target_id"] is None:
                tx, ty = pending["move_target"]
                ship.move_toward(tx, ty, dt)
                ship.last_action = "move"

        for ship, opponent, pending in (
            (self.ship_a, self.ship_b, pending_a),
            (self.ship_b, self.ship_a, pending_b),
        ):
            if pending["attack_target_id"] == opponent.id and ship.can_attack(opponent):
                dmg = ship.fire_at(opponent)
                opponent.take_damage(dmg)
                ship.last_action = "attack"
                self._log(f"{ship.team} attacked {opponent.name} - {opponent.name} HP -{dmg:.0f}")
                self.events.emit(ev.ATTACK, ship.team, "Attack successful", target_id=opponent.id)
                self.events.emit(
                    ev.DAMAGE, ship.team, f"{opponent.name} HP -{dmg:.0f}",
                    target_id=opponent.id, target_team=opponent.team, amount=dmg, hp_after=opponent.hp,
                )
                if not opponent.alive:
                    self._log(f"{opponent.name} destroyed. {ship.team} wins.")
                    self.events.emit(ev.DESTROYED, opponent.team, f"{opponent.name} destroyed")
                    self.events.emit(ev.BATTLE_WON, ship.team, f"{ship.team} wins")
                    self.winner = ship.team
                    self.outcome = "DESTROY_ENEMY"
                    self.ended = True
                    self.running = False

        self.tick_count += 1
        self.elapsed += dt

        # Time-limit draw (challenges/ Rules.battle_duration). Only checked
        # once at the end of the tick that crosses the threshold — no
        # separate timer loop, the existing tick loop is unchanged.
        if not self.ended and self.config.battle_duration and self.elapsed >= self.config.battle_duration:
            self._log(f"Time limit reached ({self.config.battle_duration:.0f}s). Battle ends in a draw.")
            self.events.emit(ev.BATTLE_DRAW, "", "Time limit reached - draw")
            self.outcome = "TIME_LIMIT_DRAW"
            self.ended = True
            self.running = False
