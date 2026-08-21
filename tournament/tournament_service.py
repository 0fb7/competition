"""Orchestration + business rules for Competitions/Rounds/Matches.

Depends on TeamService, ChallengeService, SubmissionService (read-only —
"team must exist", "challenge must exist", "submission must be
SUBMITTED") — the same one-directional dependency pattern
submissions/submission_service.py used against roster/challenges in
Phase 3. Deliberately does NOT import engine/runner.py or hold a
BattleRunner reference: this service only prepares a Match (resolves the
exact code + BattleConfig a battle needs) and records its result; it
never runs a battle itself. ui/app.py is the one bridge that takes a
prepared Match and actually drives BattleRunner — same architecture
Phases 1-3 already established.
"""

from __future__ import annotations

import itertools
import uuid
from typing import Optional

from challenges.challenge import STATUS_ARCHIVED as CHALLENGE_ARCHIVED
from engine.config import BattleConfig

from .competition import (
    Competition, LOCKED_STATUSES, STATUS_ACTIVE, STATUS_ARCHIVED, STATUS_COMPLETED,
    STATUS_DRAFT, STATUS_PAUSED, STATUS_READY, STATUSES, STRUCTURAL_FIELDS,
    ValidationError, utc_now_iso,
)
from .match import (
    Match, OUTCOME_CANCELLED, OUTCOME_DRAW, OUTCOME_ERROR, OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN,
    STATUS_CANCELLED as M_CANCELLED, STATUS_COMPLETED as M_COMPLETED, STATUS_ERROR as M_ERROR,
    STATUS_PENDING as M_PENDING, STATUS_READY as M_READY, STATUS_RUNNING as M_RUNNING,
)
from .round import (
    Round, ROUND_TYPES, STATUS_ACTIVE as R_ACTIVE, STATUS_CANCELLED as R_CANCELLED,
    STATUS_COMPLETED as R_COMPLETED, STATUS_PENDING as R_PENDING, STATUS_READY as R_READY,
    TYPE_CUSTOM, TYPE_ROUND_ROBIN, TYPE_SINGLE_ELIMINATION,
)
from .tournament_repository import TournamentRepository


class TournamentService:
    def __init__(
        self, repository: TournamentRepository, team_service, challenge_service, submission_service,
        result_service=None,
    ):
        self.repo = repository
        self.team_service = team_service
        self.challenge_service = challenge_service
        self.submission_service = submission_service
        # Optional (Phase 5): when provided, lets this service record the
        # MatchResult for a BYE the instant it's created — a BYE never
        # reaches ui/app.py's real-battle completion path (_finish_active_
        # match), so this is the only place a BYE's history gets written.
        # None keeps this service fully usable standalone, exactly as
        # Phase 4's tests already construct and exercise it.
        self.result_service = result_service

    # =========================================================== eligibility
    def is_team_eligible(self, team_id: str, challenge_id: str) -> bool:
        team = self.team_service.get_team(team_id)
        if team is None or team.disabled:
            return False
        return self.submission_service.get_active_submission(team_id, challenge_id) is not None

    # =========================================================== competitions
    def create_competition(self, competition_id: str, name: str, description: str = "", challenge_id: Optional[str] = None) -> Competition:
        from .competition import COMPETITION_ID_RE
        competition_id = (competition_id or "").strip()
        name = (name or "").strip()
        if not competition_id:
            raise ValidationError("empty_id")
        if not COMPETITION_ID_RE.match(competition_id):
            raise ValidationError("invalid_id")
        if self.repo.get_competition(competition_id) is not None:
            raise ValidationError("duplicate_id")
        if not name:
            raise ValidationError("empty_name")
        if challenge_id is not None and self.challenge_service.get_challenge(challenge_id) is None:
            raise ValidationError("challenge_not_found")

        comp = Competition(id=competition_id, name=name, description=description, challenge_id=challenge_id)
        return self.repo.create_competition(comp)

    def get_competition(self, competition_id: str) -> Optional[Competition]:
        return self.repo.get_competition(competition_id)

    def get_all_competitions(self) -> list[Competition]:
        return self.repo.get_all_competitions()

    def update_competition(self, competition_id: str, **fields) -> Competition:
        comp = self.repo.get_competition(competition_id)
        if comp is None:
            raise KeyError(competition_id)
        if comp.status in LOCKED_STATUSES and (STRUCTURAL_FIELDS & set(fields)):
            raise ValidationError("cannot_edit_locked_structure")
        if "name" in fields and not str(fields["name"]).strip():
            raise ValidationError("empty_name")
        if "challenge_id" in fields and fields["challenge_id"] is not None:
            if self.challenge_service.get_challenge(fields["challenge_id"]) is None:
                raise ValidationError("challenge_not_found")
        fields["updated_at"] = utc_now_iso()
        return self.repo.update_competition(competition_id, **fields)

    def delete_competition(self, competition_id: str) -> None:
        comp = self.repo.get_competition(competition_id)
        if comp is None:
            raise KeyError(competition_id)
        if comp.status in (STATUS_ACTIVE, STATUS_PAUSED):
            raise ValidationError("cannot_delete_active")
        matches = self.repo.get_competition_matches(competition_id)
        # Final Product Audit fix: ERROR matches already get a permanent
        # MatchResult recorded (the same results/ pipeline COMPLETED/BYE
        # matches use — see results/result_service.py's record_from_match(),
        # called from ui/app.py's _stop_active_match()/_finish_active_match()
        # for a live-engine fault/stop, and from error_match() callers).
        # A BYE match is already stored with status M_COMPLETED at creation
        # (see generate_round_robin/generate_single_elimination above), so
        # it was already covered by the M_COMPLETED check and needs no
        # separate case here. CANCELLED is deliberately NOT included: a
        # cancelled match never produces a MatchResult (spec section 8 /
        # tests/test_results.py::test_cancelled_result) — there is no
        # historical record to protect, so blocking on it would only
        # prevent cleaning up a competition that never actually ran.
        if any(m.status in (M_COMPLETED, M_ERROR) for m in matches):
            raise ValidationError("cannot_delete_historical")
        for r in self.repo.get_competition_rounds(competition_id):
            for m in self.repo.get_round_matches(r.id):
                pass  # matches are left in place intentionally — see module docstring; nothing to clean up beyond the competition record itself for a DRAFT/no-history competition
        self.repo.delete_competition(competition_id)

    # ------------------------------------------------------------- team roster
    def add_team(self, competition_id: str, team_id: str) -> Competition:
        comp = self.repo.get_competition(competition_id)
        if comp is None:
            raise KeyError(competition_id)
        if comp.status != STATUS_DRAFT:
            raise ValidationError("cannot_edit_locked_structure")
        team = self.team_service.get_team(team_id)
        if team is None:
            raise ValidationError("team_not_found")
        if team.disabled:
            raise ValidationError("team_disabled")
        if team_id in comp.team_ids:
            raise ValidationError("team_already_added")
        if comp.challenge_id and not self.is_team_eligible(team_id, comp.challenge_id):
            raise ValidationError("team_not_eligible")
        return self.repo.update_competition(competition_id, team_ids=comp.team_ids + [team_id], updated_at=utc_now_iso())

    def remove_team(self, competition_id: str, team_id: str) -> Competition:
        comp = self.repo.get_competition(competition_id)
        if comp is None:
            raise KeyError(competition_id)
        if comp.status != STATUS_DRAFT:
            raise ValidationError("cannot_edit_locked_structure")
        return self.repo.update_competition(
            competition_id, team_ids=[t for t in comp.team_ids if t != team_id], updated_at=utc_now_iso(),
        )

    # ------------------------------------------------------------- lifecycle
    def mark_ready(self, competition_id: str) -> Competition:
        comp = self.repo.get_competition(competition_id)
        if comp is None:
            raise KeyError(competition_id)
        if comp.status != STATUS_DRAFT:
            raise ValidationError("invalid_transition")
        if comp.challenge_id is None or self.challenge_service.get_challenge(comp.challenge_id) is None:
            raise ValidationError("challenge_not_found")
        if self.challenge_service.get_challenge(comp.challenge_id).status == CHALLENGE_ARCHIVED:
            raise ValidationError("challenge_not_usable")
        if len(comp.team_ids) < 2:
            raise ValidationError("not_enough_teams")
        for team_id in comp.team_ids:
            if not self.is_team_eligible(team_id, comp.challenge_id):
                raise ValidationError("team_not_eligible")
        return self.repo.update_competition(competition_id, status=STATUS_READY, updated_at=utc_now_iso())

    def start_competition(self, competition_id: str) -> Competition:
        comp = self.repo.get_competition(competition_id)
        if comp is None:
            raise KeyError(competition_id)
        if comp.status != STATUS_READY:
            raise ValidationError("invalid_transition")
        if not comp.round_ids:
            raise ValidationError("no_rounds")
        return self.repo.update_competition(competition_id, status=STATUS_ACTIVE, started_at=utc_now_iso(), updated_at=utc_now_iso())

    def pause_competition(self, competition_id: str) -> Competition:
        comp = self.repo.get_competition(competition_id)
        if comp is None or comp.status != STATUS_ACTIVE:
            raise ValidationError("invalid_transition")
        return self.repo.update_competition(competition_id, status=STATUS_PAUSED, updated_at=utc_now_iso())

    def resume_competition(self, competition_id: str) -> Competition:
        comp = self.repo.get_competition(competition_id)
        if comp is None or comp.status != STATUS_PAUSED:
            raise ValidationError("invalid_transition")
        return self.repo.update_competition(competition_id, status=STATUS_ACTIVE, updated_at=utc_now_iso())

    def complete_competition(self, competition_id: str) -> Competition:
        comp = self.repo.get_competition(competition_id)
        if comp is None or comp.status not in (STATUS_ACTIVE, STATUS_PAUSED):
            raise ValidationError("invalid_transition")
        return self.repo.update_competition(competition_id, status=STATUS_COMPLETED, ended_at=utc_now_iso(), updated_at=utc_now_iso())

    # =================================================================== rounds
    def create_round(self, competition_id: str, name: str, round_type: str) -> Round:
        comp = self.repo.get_competition(competition_id)
        if comp is None:
            raise KeyError(competition_id)
        if comp.status in (STATUS_COMPLETED, STATUS_ARCHIVED):
            raise ValidationError("competition_not_open")
        if round_type not in ROUND_TYPES:
            raise ValidationError("invalid_round_type")
        existing = self.repo.get_competition_rounds(competition_id)
        round_obj = Round(
            id=f"{competition_id}__round-{len(existing) + 1}", competition_id=competition_id,
            name=name or f"Round {len(existing) + 1}", order=len(existing) + 1, round_type=round_type,
        )
        self.repo.create_round(round_obj)
        self.repo.update_competition(competition_id, round_ids=comp.round_ids + [round_obj.id], updated_at=utc_now_iso())
        return round_obj

    def get_round(self, round_id: str) -> Optional[Round]:
        return self.repo.get_round(round_id)

    def get_competition_rounds(self, competition_id: str) -> list[Round]:
        return self.repo.get_competition_rounds(competition_id)

    def get_round_matches(self, round_id: str) -> list[Match]:
        return self.repo.get_round_matches(round_id)

    def get_competition_matches(self, competition_id: str) -> list[Match]:
        return self.repo.get_competition_matches(competition_id)

    # ---------------------------------------------------------- match creation
    def _next_match_number(self, competition_id: str) -> int:
        return len(self.repo.get_competition_matches(competition_id)) + 1

    def _create_match_for_pair(self, comp: Competition, round_obj: Round, team_a_id: str, team_b_id: Optional[str]) -> Match:
        """Pins the exact active submission ids at creation time (spec
        section 10) — a Match never re-resolves a newer submission later,
        even if the team submits a new version before the match runs."""
        sub_a = self.submission_service.get_active_submission(team_a_id, comp.challenge_id)
        if sub_a is None:
            raise ValidationError("team_not_eligible")

        is_bye = team_b_id is None
        sub_b = None
        if not is_bye:
            sub_b = self.submission_service.get_active_submission(team_b_id, comp.challenge_id)
            if sub_b is None:
                raise ValidationError("team_not_eligible")

        match = Match(
            id=f"{round_obj.id}__m{self._next_match_number(comp.id)}",
            competition_id=comp.id, round_id=round_obj.id, match_number=self._next_match_number(comp.id),
            team_a_id=team_a_id, team_b_id=team_b_id,
            submission_a_id=sub_a.id, submission_b_id=sub_b.id if sub_b else None,
            challenge_id=comp.challenge_id, is_bye=is_bye,
        )
        if is_bye:
            # A BYE never touches BattleEngine (spec section 19) — the
            # team simply advances, recorded plainly, not as a fake win.
            match.status = M_COMPLETED
            match.outcome = OUTCOME_TEAM_A_WIN
            match.winner_team_id = team_a_id
            match.started_at = utc_now_iso()
            match.ended_at = utc_now_iso()
        else:
            match.status = M_READY

        self.repo.create_match(match)
        round_obj.match_ids.append(match.id)
        self.repo.update_round(round_obj.id, match_ids=round_obj.match_ids)

        if is_bye and self.result_service is not None:
            # No battle ever ran, so hp/damage stay unset (None) — see
            # results/result_service.py's docstring; a BYE record exists
            # purely so Match History shows what actually happened.
            self.result_service.record_from_match(match)

        return match

    def generate_round_robin(self, round_id: str) -> list[Match]:
        round_obj = self._require_round(round_id, TYPE_ROUND_ROBIN)
        comp = self._require_competition(round_obj.competition_id)
        pairs = list(itertools.combinations(comp.team_ids, 2))  # every unique pair once, no self-pairs
        matches = [self._create_match_for_pair(comp, round_obj, a, b) for a, b in pairs]
        self.repo.update_round(round_id, status=R_READY)
        return matches

    def generate_single_elimination(self, round_id: str) -> list[Match]:
        """Seeding = the order teams were added to the competition
        (comp.team_ids, deterministic list order — documented, not
        random). If the team count isn't a power of two, the *top*
        `byes` seeds (first in team_ids) receive a BYE and advance
        without a battle; this is a simple, deterministic, documented
        strategy, not an attempt at an optimal balanced bracket."""
        round_obj = self._require_round(round_id, TYPE_SINGLE_ELIMINATION)
        comp = self._require_competition(round_obj.competition_id)
        teams = list(comp.team_ids)
        n = len(teams)
        next_pow2 = 1
        while next_pow2 < n:
            next_pow2 *= 2
        byes = next_pow2 - n

        matches = []
        bye_teams, remaining = teams[:byes], teams[byes:]
        for team_id in bye_teams:
            matches.append(self._create_match_for_pair(comp, round_obj, team_id, None))
        for i in range(0, len(remaining), 2):
            pair = remaining[i:i + 2]
            if len(pair) == 2:
                matches.append(self._create_match_for_pair(comp, round_obj, pair[0], pair[1]))
        self.repo.update_round(round_id, status=R_READY)
        return matches

    def create_custom_match(self, round_id: str, team_a_id: str, team_b_id: str) -> Match:
        round_obj = self._require_round(round_id, TYPE_CUSTOM)
        comp = self._require_competition(round_obj.competition_id)
        if team_a_id == team_b_id:
            raise ValidationError("self_match")
        if team_a_id not in comp.team_ids or team_b_id not in comp.team_ids:
            raise ValidationError("team_not_in_competition")
        existing = self.repo.get_round_matches(round_id)
        for m in existing:
            if {m.team_a_id, m.team_b_id} == {team_a_id, team_b_id}:
                raise ValidationError("duplicate_match")
        match = self._create_match_for_pair(comp, round_obj, team_a_id, team_b_id)
        self.repo.update_round(round_id, status=R_READY)
        return match

    def _require_round(self, round_id: str, expected_type: str) -> Round:
        round_obj = self.repo.get_round(round_id)
        if round_obj is None:
            raise KeyError(round_id)
        if round_obj.round_type != expected_type:
            raise ValidationError("wrong_round_type")
        return round_obj

    def _require_competition(self, competition_id: str) -> Competition:
        comp = self.repo.get_competition(competition_id)
        if comp is None:
            raise KeyError(competition_id)
        if not comp.challenge_id:
            raise ValidationError("challenge_not_found")
        return comp

    # =================================================================== matches
    def get_match(self, match_id: str) -> Optional[Match]:
        return self.repo.get_match(match_id)

    def can_start_match(self, match_id: str) -> tuple[bool, Optional[str]]:
        """Section 13's checklist, returned as (ok, reason_code) so the UI
        can show a clear reason instead of a silent failure."""
        match = self.repo.get_match(match_id)
        if match is None:
            return False, "match_not_found"
        if match.is_bye:
            return False, "match_is_bye"
        if match.status != M_READY:
            return False, "match_not_ready"
        comp = self.repo.get_competition(match.competition_id)
        if comp is None or comp.status != STATUS_ACTIVE:
            return False, "competition_not_active"
        round_obj = self.repo.get_round(match.round_id)
        if round_obj is None or round_obj.status not in (R_READY, R_ACTIVE):
            return False, "round_not_active"
        team_a = self.team_service.get_team(match.team_a_id)
        team_b = self.team_service.get_team(match.team_b_id)
        if team_a is None or team_b is None:
            return False, "team_missing"
        sub_a = self.submission_service.get_submission(match.submission_a_id)
        sub_b = self.submission_service.get_submission(match.submission_b_id)
        if sub_a is None or sub_b is None:
            return False, "submission_missing"
        from submissions.submission import STATUS_SUBMITTED
        if sub_a.status != STATUS_SUBMITTED or sub_b.status != STATUS_SUBMITTED:
            return False, "submission_not_submitted"
        if sub_a.team_id != match.team_a_id or sub_b.team_id != match.team_b_id:
            return False, "submission_team_mismatch"
        if sub_a.challenge_id != match.challenge_id or sub_b.challenge_id != match.challenge_id:
            return False, "submission_challenge_mismatch"
        challenge = self.challenge_service.get_challenge(match.challenge_id)
        if challenge is None:
            return False, "challenge_not_found"
        try:
            challenge.to_battle_config().validate()
        except ValueError:
            return False, "invalid_battle_config"
        return True, None

    def prepare_match_for_start(self, match_id: str) -> tuple[str, str, BattleConfig, str, str]:
        """Re-resolves and returns everything ui/app.py needs to actually
        run the match: (code_a, code_b, config, team_a_name, team_b_name).
        Reads submission.code fresh from the (immutable, SUBMITTED)
        submissions pinned on the match — never a newer version — and
        builds the BattleConfig fresh from the Challenge referenced on
        the match, exactly the snapshot spec sections 10/20/21 require.
        Transitions the match to RUNNING and its round to ACTIVE."""
        ok, reason = self.can_start_match(match_id)
        if not ok:
            raise ValidationError(reason)
        match = self.repo.get_match(match_id)
        sub_a = self.submission_service.get_submission(match.submission_a_id)
        sub_b = self.submission_service.get_submission(match.submission_b_id)
        challenge = self.challenge_service.get_challenge(match.challenge_id)
        team_a = self.team_service.get_team(match.team_a_id)
        team_b = self.team_service.get_team(match.team_b_id)

        self.repo.update_match(match_id, status=M_RUNNING, started_at=utc_now_iso())
        round_obj = self.repo.get_round(match.round_id)
        if round_obj.status != R_ACTIVE:
            self.repo.update_round(match.round_id, status=R_ACTIVE, started_at=round_obj.started_at or utc_now_iso())

        return sub_a.code, sub_b.code, challenge.to_battle_config(), team_a.name, team_b.name

    def complete_match(self, match_id: str, outcome: str, winner_team_id: Optional[str], duration: float) -> Match:
        match = self.repo.get_match(match_id)
        if match is None:
            raise KeyError(match_id)
        if match.status != M_RUNNING:
            raise ValidationError("match_not_running")
        if outcome not in (OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN, OUTCOME_DRAW, OUTCOME_ERROR):
            raise ValidationError("invalid_outcome")
        updated = self.repo.update_match(
            match_id, status=M_COMPLETED, outcome=outcome, winner_team_id=winner_team_id,
            ended_at=utc_now_iso(), battle_duration=duration,
        )
        self._check_round_completion(match.round_id)
        return updated

    def error_match(self, match_id: str, _message: str = "", duration: Optional[float] = None) -> Match:
        """Also the Phase 6 STOP path (ui/app.py._on_stop_match): an
        admin-initiated stop of a RUNNING match is recorded as ERROR, not
        a fake win — no `status != M_RUNNING` guard is enforced here
        because this method already had no status restriction in Phase 4
        (never wired to any UI trigger back then) and STOP must be able
        to reach a match from PREPARING/RUNNING alike. `duration`, when
        given, is the real elapsed simulation time at the moment of the
        stop (spec section 12) — never fabricated, never defaulted to a
        full/complete duration."""
        match = self.repo.get_match(match_id)
        if match is None:
            raise KeyError(match_id)
        updated = self.repo.update_match(
            match_id, status=M_ERROR, outcome=OUTCOME_ERROR, ended_at=utc_now_iso(), battle_duration=duration,
        )
        self._check_round_completion(match.round_id)
        return updated

    def cancel_match(self, match_id: str) -> Match:
        match = self.repo.get_match(match_id)
        if match is None:
            raise KeyError(match_id)
        if match.status not in (M_PENDING, M_READY):
            raise ValidationError("cannot_cancel_running_or_completed")
        return self.repo.update_match(match_id, status=M_CANCELLED, outcome=OUTCOME_CANCELLED, ended_at=utc_now_iso())

    # ---------------------------------------------------- round/bracket progress
    def _check_round_completion(self, round_id: str) -> None:
        """Phase 8 (BACKLOG #7) — the one deterministic cancelled-match
        policy, documented and applied identically to both round types:

          - A cancelled match produces no winner, no MatchResult, and no
            round-robin standings contribution (results/result_service.py
            already excludes it via REAL_OUTCOMES — unchanged).
          - Round-robin: a cancelled match still counts as "this round is
            done" (there is no bracket advancement to protect — a
            round-robin round is just a batch of independent matches, and
            leaving it perpetually ACTIVE over one cancelled match would
            only hide a genuinely finished round from the UI).
          - Single-elimination: a round containing ANY cancelled match is
            explicitly NEVER marked COMPLETED and NEVER advances to the
            next round — no forfeit-to-opponent, no silently declaring the
            other bracket survivor a "champion" just because their
            opponent's match was cancelled (exactly the accidental-
            champion risk this policy exists to prevent). The round stays
            in whatever status it already had until an administrator
            manually intervenes (e.g. by creating a replacement match) —
            a genuinely blocked, visibly non-terminal state, never a
            silent auto-resolution."""
        round_obj = self.repo.get_round(round_id)
        matches = self.repo.get_round_matches(round_id)
        if not matches:
            return
        has_cancelled = any(m.status == M_CANCELLED for m in matches)
        if round_obj.round_type == TYPE_SINGLE_ELIMINATION and has_cancelled:
            return  # blocked — see docstring; never auto-completes or advances
        if not all(m.status in (M_COMPLETED, M_ERROR, M_CANCELLED) for m in matches):
            return
        self.repo.update_round(round_id, status=R_COMPLETED, ended_at=utc_now_iso())

        if round_obj.round_type != TYPE_SINGLE_ELIMINATION:
            return
        winners = [m.winner_team_id for m in matches if m.winner_team_id]
        if len(winners) <= 1:
            return  # a single winner is the champion; nothing more to schedule
        comp = self.repo.get_competition(round_obj.competition_id)
        next_round = self.create_round(comp.id, f"Round {round_obj.order + 1}", TYPE_SINGLE_ELIMINATION)
        # Temporarily narrow the competition's team pool to this round's
        # winners (in bracket order) so _create_match_for_pair pairs them
        # correctly — this does not touch the ORIGINAL roster's team_ids
        # for the competition as a whole, only the local pairing input.
        comp_view = Competition.from_dict(comp.to_dict())
        comp_view.team_ids = winners
        for i in range(0, len(winners), 2):
            pair = winners[i:i + 2]
            team_b = pair[1] if len(pair) == 2 else None
            self._create_match_for_pair(comp_view, next_round, pair[0], team_b)
        self.repo.update_round(next_round.id, status=R_READY)
