"""Historical results/leaderboard/analytics logic for Phase 5.

Depends read-only on TournamentService/TeamService/ChallengeService/
SubmissionService (same one-directional dependency pattern
tournament_service.py used against team/challenge/submission in Phase 4).
Never imports BattleRunner/BattleEngine — this service only turns already-
completed Matches (plus the real battle telemetry the caller hands it)
into permanent history, and aggregates that history back out again. The
one and only place a MatchResult is created is `record_from_match()`,
called from:

  - tournament_service.py, for a BYE match (no battle ever ran — see
    match.is_bye; `battle_stats`/`events` are omitted, so hp/damage stay
    None rather than fabricated).
  - ui/app.py `_finish_active_match()`, right after a real match
    completes on the live BattleRunner (spec section 8's flow) — the only
    place that has actual post-battle ship HP + accumulated match events.

Score reuses engine.competition.TeamRecord.score verbatim (imported, not
reimplemented) — spec section 11 forbids a second scoring formula. Only
outcomes an engine actually produced (TEAM_A_WIN/TEAM_B_WIN/DRAW) feed
leaderboard/team-stats aggregation; BYE (no battle occurred) and ERROR
(no clean result) are visible in Match History but excluded from
win/loss/draw/damage aggregation so they can't silently invent a "win"
or skew a win rate with a battle that never happened.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from engine.competition import TeamRecord

from tournament.match import OUTCOME_DRAW, OUTCOME_ERROR, OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN
from tournament.round import STATUS_COMPLETED as R_COMPLETED, TYPE_ROUND_ROBIN, TYPE_SINGLE_ELIMINATION

from .match_result import DuplicateResultError, MatchEvent, MatchResult
from .result_repository import ResultRepository

REAL_OUTCOMES = (OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN, OUTCOME_DRAW)


class ResultService:
    def __init__(
        self, repository: ResultRepository, tournament_service, team_service,
        challenge_service, submission_service,
    ):
        self.repo = repository
        self.tournament_service = tournament_service
        self.team_service = team_service
        self.challenge_service = challenge_service
        self.submission_service = submission_service

    # ======================================================== result creation
    def record_from_match(self, match, battle_stats: Optional[dict] = None, events: Optional[list] = None) -> MatchResult:
        """Builds and persists the immutable MatchResult for an already-
        completed Match (spec section 8: never called before the battle
        actually ends — `match.status` must already be COMPLETED/ERROR
        by the time a caller reaches this). Idempotent: a second call for
        the same match_id returns the existing record instead of raising
        or overwriting it (spec section 19)."""
        existing = self.repo.get_match_result(match.id)
        if existing is not None:
            return existing

        team_a = self.team_service.get_team(match.team_a_id)
        team_b = self.team_service.get_team(match.team_b_id) if match.team_b_id else None
        sub_a = self.submission_service.get_submission(match.submission_a_id)
        sub_b = self.submission_service.get_submission(match.submission_b_id) if match.submission_b_id else None
        challenge = self.challenge_service.get_challenge(match.challenge_id)
        stats = battle_stats or {}

        result = MatchResult(
            id=match.id, match_id=match.id, competition_id=match.competition_id, round_id=match.round_id,
            team_a_id=match.team_a_id, team_b_id=match.team_b_id,
            submission_a_id=match.submission_a_id, submission_b_id=match.submission_b_id,
            challenge_id=match.challenge_id,
            outcome=match.outcome, winner_team_id=match.winner_team_id,
            duration=match.battle_duration,
            team_a_hp_remaining=stats.get("team_a_hp_remaining"),
            team_b_hp_remaining=stats.get("team_b_hp_remaining"),
            team_a_damage_dealt=stats.get("team_a_damage_dealt"),
            team_b_damage_dealt=stats.get("team_b_damage_dealt"),
            team_a_damage_received=stats.get("team_a_damage_received"),
            team_b_damage_received=stats.get("team_b_damage_received"),
            started_at=match.started_at, ended_at=match.ended_at,
            team_a_name_at_match=team_a.name if team_a else match.team_a_id,
            team_b_name_at_match=team_b.name if team_b else None,
            submission_a_version=sub_a.version if sub_a else None,
            submission_b_version=sub_b.version if sub_b else None,
            challenge_name_at_match=challenge.name if challenge else "",
            challenge_difficulty_at_match=challenge.difficulty if challenge else None,
            is_bye=match.is_bye,
        )
        try:
            self.repo.create_match_result(result)
        except DuplicateResultError:
            return self.repo.get_match_result(match.id)

        if events:
            match_events = [
                MatchEvent(kind=e.kind, team=e.team, message=e.message, timestamp=e.timestamp, data=dict(e.data))
                for e in events
            ]
            self.repo.save_match_events(match.id, match_events)
        return result

    # ============================================================== lookups
    def get_match_result(self, match_id: str) -> Optional[MatchResult]:
        return self.repo.get_match_result(match_id)

    def get_match_events(self, match_id: str) -> list[MatchEvent]:
        return self.repo.get_match_events(match_id)

    def match_history(
        self, competition_id: str = None, team_id: str = None, outcome: str = None,
        date_from: str = None, date_to: str = None,
    ) -> list[MatchResult]:
        results = (
            self.repo.get_competition_results(competition_id) if competition_id
            else self.repo.get_all_match_results()
        )
        if team_id:
            results = [r for r in results if team_id in (r.team_a_id, r.team_b_id)]
        if outcome:
            results = [r for r in results if r.outcome == outcome]
        if date_from:
            results = [r for r in results if r.ended_at and r.ended_at >= date_from]
        if date_to:
            results = [r for r in results if r.ended_at and r.ended_at <= date_to]
        results.sort(key=lambda r: r.ended_at or r.created_at, reverse=True)
        return results

    # =========================================================== aggregation
    def _aggregate_team_stats(self, results: list[MatchResult]) -> list[dict]:
        """Shared by leaderboard() and round_summary()'s round-robin
        standings — one aggregation routine, not two."""
        stats: dict[str, dict] = {}

        def bucket(team_id, name):
            if team_id not in stats:
                stats[team_id] = {
                    "team_id": team_id, "team_name": name, "played": 0, "wins": 0,
                    "losses": 0, "draws": 0, "damage_dealt": 0.0, "damage_received": 0.0,
                }
            return stats[team_id]

        for r in results:
            if r.outcome not in REAL_OUTCOMES:
                continue
            a = bucket(r.team_a_id, r.team_a_name_at_match)
            a["played"] += 1
            a["damage_dealt"] += r.team_a_damage_dealt or 0.0
            a["damage_received"] += r.team_a_damage_received or 0.0
            b = None
            if r.team_b_id:
                b = bucket(r.team_b_id, r.team_b_name_at_match)
                b["played"] += 1
                b["damage_dealt"] += r.team_b_damage_dealt or 0.0
                b["damage_received"] += r.team_b_damage_received or 0.0

            if r.outcome == OUTCOME_DRAW:
                a["draws"] += 1
                if b:
                    b["draws"] += 1
            elif r.winner_team_id == r.team_a_id:
                a["wins"] += 1
                if b:
                    b["losses"] += 1
            elif b and r.winner_team_id == r.team_b_id:
                b["wins"] += 1
                a["losses"] += 1

        rows = []
        for s in stats.values():
            record = TeamRecord(
                team=s["team_name"], wins=s["wins"], losses=s["losses"],
                damage_dealt=s["damage_dealt"], damage_received=s["damage_received"],
            )
            rows.append({
                **s,
                "win_rate": (s["wins"] / s["played"]) if s["played"] else 0.0,
                "score": record.score,
            })
        rows.sort(key=lambda r: r["score"], reverse=True)
        for i, row in enumerate(rows, start=1):
            row["rank"] = i
        return rows

    def leaderboard(self, competition_id: str) -> list[dict]:
        return self._aggregate_team_stats(self.repo.get_competition_results(competition_id))

    def team_performance(self, team_id: str, competition_id: str = None) -> dict:
        all_results = (
            self.repo.get_competition_results(competition_id) if competition_id
            else self.repo.get_all_match_results()
        )
        team_all_results = [r for r in all_results if team_id in (r.team_a_id, r.team_b_id)]
        results = [r for r in team_all_results if r.outcome in REAL_OUTCOMES]
        wins = losses = draws = 0
        damage_dealt = damage_received = 0.0
        durations = []
        name = team_id
        for r in results:
            is_a = r.team_a_id == team_id
            name = r.team_a_name_at_match if is_a else (r.team_b_name_at_match or name)
            damage_dealt += (r.team_a_damage_dealt if is_a else r.team_b_damage_dealt) or 0.0
            damage_received += (r.team_a_damage_received if is_a else r.team_b_damage_received) or 0.0
            if r.duration:
                durations.append(r.duration)
            if r.outcome == OUTCOME_DRAW:
                draws += 1
            elif r.winner_team_id == team_id:
                wins += 1
            else:
                losses += 1
        played = len(results)
        # Phase 8 (BACKLOG #13): additive fields only — win/loss/draw/
        # win_rate/played above are completely unchanged from Phase 5.
        # `errors` counts matches with a real OUTCOME_ERROR involving this
        # team WITHOUT folding them into win_rate (Phase 5's deliberate
        # "ERROR is not a battle result" rule, see this module's docstring)
        # — shown for visibility only. `score` reuses TeamRecord.score
        # verbatim (same formula leaderboard() already uses), never a
        # second scoring system. `name` also falls back to the most recent
        # ERROR-result name if the team never had a REAL_OUTCOMES result
        # (e.g. every match so far errored) so the profile still shows a
        # real display name instead of the raw team_id.
        errors = sum(1 for r in team_all_results if r.outcome == OUTCOME_ERROR)
        if team_all_results and name == team_id:
            last = team_all_results[-1]
            name = last.team_a_name_at_match if last.team_a_id == team_id else (last.team_b_name_at_match or name)
        competitions = len({r.competition_id for r in team_all_results})
        score = TeamRecord(team=name, wins=wins, losses=losses, damage_dealt=damage_dealt, damage_received=damage_received).score
        return {
            "team_id": team_id, "team_name": name, "played": played,
            "wins": wins, "losses": losses, "draws": draws, "errors": errors,
            "win_rate": (wins / played) if played else 0.0,
            "damage_dealt": damage_dealt, "damage_received": damage_received,
            "avg_duration": (sum(durations) / len(durations)) if durations else None,
            "competitions": competitions, "score": score,
        }

    def competition_summary(self, competition_id: str) -> Optional[dict]:
        comp = self.tournament_service.get_competition(competition_id)
        if comp is None:
            return None
        matches = self.tournament_service.get_competition_matches(competition_id)
        completed = [m for m in matches if m.status in ("COMPLETED", "ERROR")]
        draws = sum(1 for m in completed if m.outcome == OUTCOME_DRAW)

        champion = None
        rounds = self.tournament_service.get_competition_rounds(competition_id)
        elim_rounds = [r for r in rounds if r.round_type == TYPE_SINGLE_ELIMINATION and r.status == R_COMPLETED]
        if elim_rounds:
            final_round = max(elim_rounds, key=lambda r: r.order)
            final_matches = self.tournament_service.get_round_matches(final_round.id)
            if len(final_matches) == 1:
                fm = final_matches[0]
                champion_id = fm.winner_team_id if fm.winner_team_id else None
                if champion_id:
                    champion_team = self.team_service.get_team(champion_id)
                    champion = champion_team.name if champion_team else champion_id

        duration = None
        if comp.started_at and comp.ended_at:
            try:
                duration = (datetime.fromisoformat(comp.ended_at) - datetime.fromisoformat(comp.started_at)).total_seconds()
            except ValueError:
                duration = None

        return {
            "competition": comp, "champion": champion, "total_teams": len(comp.team_ids),
            "total_matches": len(matches), "completed_matches": len(completed), "draws": draws,
            "duration": duration, "leaderboard": self.leaderboard(competition_id),
        }

    def round_summary(self, round_id: str) -> Optional[dict]:
        round_obj = self.tournament_service.get_round(round_id)
        if round_obj is None:
            return None
        matches = self.tournament_service.get_round_matches(round_id)

        winners = []
        draws = 0
        for m in matches:
            if m.outcome == OUTCOME_DRAW:
                draws += 1
            elif m.winner_team_id:
                team = self.team_service.get_team(m.winner_team_id)
                winners.append(team.name if team else m.winner_team_id)

        standings = None
        if round_obj.round_type == TYPE_ROUND_ROBIN:
            results = [self.repo.get_match_result(m.id) for m in matches]
            results = [r for r in results if r is not None]
            standings = self._aggregate_team_stats(results)

        return {"round": round_obj, "matches": matches, "winners": winners, "draws": draws, "standings": standings}
