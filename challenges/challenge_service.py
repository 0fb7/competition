"""Validation + orchestration on top of ChallengeRepository. This is what
the UI talks to — never the repository directly.

Deliberately does not import engine/runner.py or hold a BattleRunner
reference — same layering rule as roster/team_service.py (spec section
30): UI -> ChallengeService -> ChallengeRepository -> Persistence, kept
separate from Challenge -> BattleConfig -> BattleEngine -> BattleRunner.
ui/app.py is the one place that bridges the two, exactly like it already
does for roster/ (App._sync_engine_identity, here extended to also push
BattleConfig).
"""

from __future__ import annotations

from typing import Optional

from .challenge import (
    Challenge, Rules, ValidationError, CHALLENGE_ID_RE, DIFFICULTY_LEVELS,
    STATUS_ACTIVE, STATUS_ARCHIVED, STATUS_DRAFT, STATUSES, UNSAFE_EDIT_FIELDS,
)
from .challenge_repository import ChallengeRepository
from engine.config import ALL_API_FUNCTIONS, WIN_CONDITIONS, WIN_DESTROY_ENEMY

DEFAULT_CHALLENGE_ID = "tactical-battleship"


class ChallengeService:
    def __init__(self, repository: ChallengeRepository):
        self.repo = repository

    # ---------------------------------------------------------- migration
    def ensure_default_challenge(self) -> None:
        """Idempotent: only seeds the default challenge the first time the
        JSON store is empty. Never overwrites an admin's edits."""
        if self.repo.get_all_challenges():
            return
        self.repo.create_challenge(Challenge(
            id=DEFAULT_CHALLENGE_ID,
            name="Tactical Battleship",
            description=(
                "The original Code Battleship scenario: two teams, each writing a Python "
                "strategy that pilots one autonomous ship. Ships close distance, manage "
                "energy, and fire when a target is in range."
            ),
            objective="Destroy the enemy ship before your own ship is destroyed.",
            difficulty="LEVEL_2",
            # engine defaults, except movement_energy_cost=0.5: the
            # Energy-as-a-resource extension applied to the flagship
            # challenge — every other Challenge (and Rules() itself)
            # still defaults to 0.0 (movement free), unaffected.
            rules=Rules(movement_energy_cost=0.5),
            win_condition=WIN_DESTROY_ENEMY,
            allowed_api=list(ALL_API_FUNCTIONS),
            status=STATUS_ACTIVE,
        ))

    # ------------------------------------------------------------ reads
    def get_challenge(self, challenge_id: str) -> Optional[Challenge]:
        return self.repo.get_challenge(challenge_id)

    def get_all_challenges(self) -> list[Challenge]:
        return self.repo.get_all_challenges()

    def get_active_challenge(self) -> Optional[Challenge]:
        for c in self.repo.get_all_challenges():
            if c.status == STATUS_ACTIVE:
                return c
        return None

    # ----------------------------------------------------------- create
    def create_challenge(
        self, challenge_id: str, name: str, description: str = "", objective: str = "",
        difficulty: str = "LEVEL_2", rules: Optional[Rules] = None,
        win_condition: str = WIN_DESTROY_ENEMY, allowed_api: Optional[list[str]] = None,
    ) -> Challenge:
        challenge_id = (challenge_id or "").strip()
        name = (name or "").strip()
        description = (description or "").strip()
        rules = rules or Rules()
        allowed_api = list(allowed_api) if allowed_api else list(ALL_API_FUNCTIONS)

        if not challenge_id:
            raise ValidationError("empty_id")
        if not CHALLENGE_ID_RE.match(challenge_id):
            raise ValidationError("invalid_id")
        if self.repo.get_challenge(challenge_id) is not None:
            raise ValidationError("duplicate_id")
        if not name:
            raise ValidationError("empty_name")
        if not description:
            raise ValidationError("empty_description")
        if difficulty not in DIFFICULTY_LEVELS:
            raise ValidationError("invalid_difficulty")
        if win_condition not in WIN_CONDITIONS:
            raise ValidationError("invalid_win_condition")

        rules.validate(win_condition, allowed_api)  # raises ValidationError

        challenge = Challenge(
            id=challenge_id, name=name, description=description, objective=objective,
            difficulty=difficulty, rules=rules, win_condition=win_condition,
            allowed_api=allowed_api, status=STATUS_DRAFT,
        )
        return self.repo.create_challenge(challenge)

    # ------------------------------------------------------------- edit
    def update_challenge(self, challenge_id: str, **fields) -> Challenge:
        challenge = self.repo.get_challenge(challenge_id)
        if challenge is None:
            raise KeyError(challenge_id)

        if challenge.status == STATUS_ACTIVE and (UNSAFE_EDIT_FIELDS & set(fields)):
            raise ValidationError("cannot_edit_active_rules")

        merged = Challenge.from_dict(challenge.to_dict())
        for key, value in fields.items():
            if not hasattr(merged, key):
                raise ValueError(f"unknown challenge field: {key}")
            setattr(merged, key, value)

        if not merged.name.strip():
            raise ValidationError("empty_name")
        if not merged.description.strip():
            raise ValidationError("empty_description")
        if merged.difficulty not in DIFFICULTY_LEVELS:
            raise ValidationError("invalid_difficulty")
        if merged.win_condition not in WIN_CONDITIONS:
            raise ValidationError("invalid_win_condition")
        merged.rules.validate(merged.win_condition, merged.allowed_api)

        return self.repo.update_challenge(challenge_id, **fields)

    # ----------------------------------------------------------- delete
    def delete_challenge(self, challenge_id: str) -> None:
        challenge = self.repo.get_challenge(challenge_id)
        if challenge is None:
            raise KeyError(challenge_id)
        if challenge.status == STATUS_ACTIVE:
            raise ValidationError("cannot_delete_active")
        self.repo.delete_challenge(challenge_id)

    # ----------------------------------------------------------- status
    def set_status(self, challenge_id: str, new_status: str) -> Challenge:
        if new_status not in STATUSES:
            raise ValidationError("invalid_status")
        challenge = self.repo.get_challenge(challenge_id)
        if challenge is None:
            raise KeyError(challenge_id)

        if new_status == STATUS_ACTIVE:
            if challenge.status == STATUS_ARCHIVED:
                raise ValidationError("cannot_activate_archived")
            # Only one active challenge at a time (section 21) — demote
            # whichever challenge currently holds it.
            for other in self.repo.get_all_challenges():
                if other.id != challenge_id and other.status == STATUS_ACTIVE:
                    self.repo.update_challenge(other.id, status="READY")

        return self.repo.update_challenge(challenge_id, status=new_status)

    def activate_challenge(self, challenge_id: str) -> Challenge:
        return self.set_status(challenge_id, STATUS_ACTIVE)
