"""Validation + orchestration on top of TeamRepository. This is what the
UI talks to — never the repository directly.

Deliberately does NOT import engine/runner.py or hold a BattleRunner
reference (see spec section 25's layering rule: UI -> Team Service ->
Team Repository -> Persistence, kept separate from BattleRunner ->
BattleEngine). Two narrow, explicit collaborators are injected instead
so the coupling is visible and minimal rather than implicit:

  - `is_team_active(team_id)` — a predicate the app supplies, backed by
    BattleRunner.snapshot(), used only to block deletion of a team
    currently fighting. TeamService never reads battle state itself.
  - `competition_tracker` — used for exactly one thing: renaming a
    CompetitionTracker record when a team is renamed, so accumulated
    wins/losses/damage survive the rename (see
    CompetitionTracker.rename_team). No scoring logic lives here.
"""

from __future__ import annotations

import os
import uuid
from typing import Callable, Optional

from .team import Member, Team, ValidationError, TEAM_ID_RE, SHIP_SLOTS, STATUS_DISABLED, STATUS_IN_BATTLE, STATUS_NOT_READY, STATUS_READY
from .team_repository import TeamRepository

IDLE_SUBMISSION_TEMPLATE = '''# {team_name} — starter strategy
def decide(friendly, enemies, api):
    api["hold_position"]()
'''


class TeamService:
    def __init__(
        self,
        repository: TeamRepository,
        submissions_dir: str,
        is_team_active: Optional[Callable[[str], bool]] = None,
        competition_tracker=None,
    ):
        self.repo = repository
        self.submissions_dir = submissions_dir
        self.is_team_active = is_team_active or (lambda team_id: False)
        self.competition_tracker = competition_tracker
        os.makedirs(submissions_dir, exist_ok=True)

    # ---------------------------------------------------------- migration
    def ensure_default_teams(self, alpha_code_path: str, beta_code_path: str) -> None:
        """Idempotent: only seeds Alpha/Beta the first time the JSON store
        is empty. Never overwrites teams the admin has since edited."""
        if self.repo.get_all_teams():
            return
        self.repo.create_team(Team(
            id="team-alpha", name="Team Alpha", ship_id="alpha",
            submission_id=alpha_code_path,
            members=[Member(member_id="m-ahmed", name="Ahmed")],
        ))
        self.repo.create_team(Team(
            id="team-beta", name="Team Beta", ship_id="beta",
            submission_id=beta_code_path,
            members=[Member(member_id="m-mohammed", name="Mohammed")],
        ))

    # ------------------------------------------------------------ reads
    def get_team(self, team_id: str) -> Optional[Team]:
        return self.repo.get_team(team_id)

    def get_all_teams(self) -> list[Team]:
        return self.repo.get_all_teams()

    def team_for_slot(self, ship_id: str) -> Optional[Team]:
        for team in self.repo.get_all_teams():
            if team.ship_id == ship_id:
                return team
        return None

    def compute_status(self, team: Team) -> str:
        if team.disabled:
            return STATUS_DISABLED
        if team.ship_id and self.is_team_active(team.id):
            return STATUS_IN_BATTLE
        if team.ship_id and team.submission_id:
            return STATUS_READY
        return STATUS_NOT_READY

    # ----------------------------------------------------------- create
    def create_team(self, name: str, team_id: str | None = None, ship_id: str | None = None) -> Team:
        name = (name or "").strip()
        if not name:
            raise ValidationError("empty_name")

        team_id = (team_id or self._slugify(name)).strip()
        if not team_id:
            raise ValidationError("empty_id")
        if not TEAM_ID_RE.match(team_id):
            raise ValidationError("invalid_id")
        if self.repo.get_team(team_id) is not None:
            raise ValidationError("duplicate_id")

        if ship_id:
            self._validate_ship_slot(ship_id, exclude_team_id=None)

        submission_path = os.path.join(self.submissions_dir, f"{team_id}.py")
        with open(submission_path, "w", encoding="utf-8") as f:
            f.write(IDLE_SUBMISSION_TEMPLATE.format(team_name=name))

        team = Team(id=team_id, name=name, ship_id=ship_id, submission_id=submission_path)
        return self.repo.create_team(team)

    # ------------------------------------------------------------- edit
    def update_team(self, team_id: str, name: str | None = None, ship_id: str | None = "__unset__") -> Team:
        team = self.repo.get_team(team_id)
        if team is None:
            raise KeyError(team_id)

        fields = {}
        old_name = team.name

        if name is not None:
            name = name.strip()
            if not name:
                raise ValidationError("empty_name")
            fields["name"] = name

        if ship_id != "__unset__":
            if ship_id:
                self._validate_ship_slot(ship_id, exclude_team_id=team_id)
            fields["ship_id"] = ship_id

        updated = self.repo.update_team(team_id, **fields) if fields else team

        if "name" in fields and self.competition_tracker is not None and old_name != fields["name"]:
            self.competition_tracker.rename_team(old_name, fields["name"])

        return updated

    def set_disabled(self, team_id: str, disabled: bool) -> Team:
        return self.repo.update_team(team_id, disabled=disabled)

    # ----------------------------------------------------------- delete
    def delete_team(self, team_id: str) -> None:
        team = self.repo.get_team(team_id)
        if team is None:
            raise KeyError(team_id)
        if self.is_team_active(team_id):
            raise ValidationError("cannot_delete_active")
        self.repo.delete_team(team_id)
        self._cleanup_orphaned_submission_stub(team)

    def _cleanup_orphaned_submission_stub(self, team: Team) -> None:
        """Phase 7 backlog item: create_team() writes a starter stub to
        self.submissions_dir/<team_id>.py (see create_team() below); once
        the Team record is gone, that file is orphaned. Deletes it IF AND
        ONLY IF it actually lives inside this service's own submissions_dir
        — the default Alpha/Beta teams point at teams/team_alpha.py and
        teams/team_beta.py (checked-in project files, a different
        directory entirely), so this can never delete those or any other
        team's file, even by path-name coincidence. Best-effort: a
        missing file or a permissions error here must never prevent the
        Team record itself from having been deleted (already done above),
        and never touches submissions/submissions.json's historical
        Submission records or anything results/ has persisted — those
        stay fully intact and readable (spec section 12)."""
        path = team.submission_id
        if not path:
            return
        try:
            stub_dir = os.path.realpath(self.submissions_dir)
            file_dir = os.path.realpath(os.path.dirname(path))
            if file_dir != stub_dir:
                return  # not one of our generated stubs — never touch it
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass  # cleanup is best-effort; the Team record deletion already succeeded

    # ----------------------------------------------------------- members
    def add_member(self, team_id: str, name: str) -> Team:
        name = (name or "").strip()
        if not name:
            raise ValidationError("empty_member_name")
        member = Member(member_id=f"m-{uuid.uuid4().hex[:8]}", name=name)
        return self.repo.add_member(team_id, member)

    def remove_member(self, team_id: str, member_id: str) -> Team:
        return self.repo.remove_member(team_id, member_id)

    # ------------------------------------------------------------ ships
    def assign_ship(self, team_id: str, ship_id: str | None) -> Team:
        return self.update_team(team_id, ship_id=ship_id)

    def _validate_ship_slot(self, ship_id: str, exclude_team_id: str | None) -> None:
        if ship_id not in SHIP_SLOTS:
            raise ValidationError("invalid_ship")
        holder = self.team_for_slot(ship_id)
        if holder is not None and holder.id != exclude_team_id:
            raise ValidationError("ship_already_assigned")

    @staticmethod
    def _slugify(name: str) -> str:
        slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
        while "--" in slug:
            slug = slug.replace("--", "-")
        return slug or f"team-{uuid.uuid4().hex[:6]}"
