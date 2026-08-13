"""Challenge/Rules data model for Phase 2.

A Challenge configures WHAT a battle is: its rules (a structured
description of the mechanics that already exist in engine/ship.py — see
Rules below), which team API functions are usable, the win condition,
and metadata (name/description/objective/difficulty/status).

Rules deliberately expose exactly the 8 mechanics named in the brief
(movement, attack, range, damage, cooldown, energy, sensor_range,
battle_duration) — not every engine/config.py field. max_hp,
attack_energy_cost and energy_regen_rate stay at their engine defaults,
not exposed as Challenge rules, to avoid overbuilding the model with
knobs nobody asked for.

Rules.to_battle_config() is the ONLY place a Challenge turns into
something the engine understands (engine.config.BattleConfig), and it
reuses BattleConfig.validate() rather than re-implementing numeric
validation — one source of truth for "is this a legal battle config",
shared by the challenges layer and the engine itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import re

from engine.config import ALL_API_FUNCTIONS, BattleConfig, WIN_CONDITIONS, WIN_DESTROY_ENEMY

CHALLENGE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{2,48}$")

LEVEL_1, LEVEL_2, LEVEL_3 = "LEVEL_1", "LEVEL_2", "LEVEL_3"
DIFFICULTY_LEVELS = (LEVEL_1, LEVEL_2, LEVEL_3)

STATUS_DRAFT = "DRAFT"
STATUS_READY = "READY"
STATUS_ACTIVE = "ACTIVE"
STATUS_ARCHIVED = "ARCHIVED"
STATUSES = (STATUS_DRAFT, STATUS_READY, STATUS_ACTIVE, STATUS_ARCHIVED)

# Fields that change actual battle mechanics — editing these on an ACTIVE
# challenge is blocked (section 14: "do not allow live rules to silently
# change underneath a running battle"). Metadata (name/description/
# objective) stays editable at any status.
UNSAFE_EDIT_FIELDS = {"rules", "difficulty", "win_condition", "allowed_api"}


class ValidationError(ValueError):
    pass


@dataclass
class Rules:
    movement_speed: float = 6.0
    attack_enabled: bool = True
    attack_range: float = 10.0
    attack_damage: float = 12.0
    attack_cooldown: float = 1.2
    energy_pool: float = 100.0
    sensor_range: float = 100.0
    battle_duration: float | None = None  # seconds; None = no time limit

    def to_battle_config(self, win_condition: str, allowed_api: list[str] | None) -> BattleConfig:
        return BattleConfig(
            movement_speed=self.movement_speed,
            attack_enabled=self.attack_enabled,
            attack_range=self.attack_range,
            attack_damage=self.attack_damage,
            attack_cooldown=self.attack_cooldown,
            max_energy=self.energy_pool,
            sensor_range=self.sensor_range,
            battle_duration=self.battle_duration,
            win_condition=win_condition,
            allowed_api=list(allowed_api) if allowed_api is not None else None,
        )

    def validate(self, win_condition: str, allowed_api: list[str] | None) -> None:
        try:
            self.to_battle_config(win_condition, allowed_api).validate()
        except ValueError as e:
            raise ValidationError(str(e)) from e

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Rules":
        return Rules(
            movement_speed=d.get("movement_speed", 6.0),
            attack_enabled=d.get("attack_enabled", True),
            attack_range=d.get("attack_range", 10.0),
            attack_damage=d.get("attack_damage", 12.0),
            attack_cooldown=d.get("attack_cooldown", 1.2),
            energy_pool=d.get("energy_pool", 100.0),
            sensor_range=d.get("sensor_range", 100.0),
            battle_duration=d.get("battle_duration"),
        )


@dataclass
class Challenge:
    id: str
    name: str
    description: str = ""
    objective: str = ""
    difficulty: str = LEVEL_2
    rules: Rules = field(default_factory=Rules)
    win_condition: str = WIN_DESTROY_ENEMY
    allowed_api: list[str] = field(default_factory=lambda: list(ALL_API_FUNCTIONS))
    status: str = STATUS_DRAFT

    def to_battle_config(self) -> BattleConfig:
        return self.rules.to_battle_config(self.win_condition, self.allowed_api)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "objective": self.objective,
            "difficulty": self.difficulty,
            "rules": self.rules.to_dict(),
            "win_condition": self.win_condition,
            "allowed_api": list(self.allowed_api),
            "status": self.status,
        }

    @staticmethod
    def from_dict(d: dict) -> "Challenge":
        return Challenge(
            id=d["id"],
            name=d["name"],
            description=d.get("description", ""),
            objective=d.get("objective", ""),
            difficulty=d.get("difficulty", LEVEL_2),
            rules=Rules.from_dict(d.get("rules", {})),
            win_condition=d.get("win_condition", WIN_DESTROY_ENEMY),
            allowed_api=list(d.get("allowed_api", ALL_API_FUNCTIONS)),
            status=d.get("status", STATUS_DRAFT),
        )
