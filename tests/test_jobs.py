"""Coaches on the move: AI clubs sack their coach after a bad season, and vacancies reach the manager."""

import pytest

from app.game import engine, jobs, training
from app.game.catalog import get_catalog
from app.game.errors import IllegalAction
from app.game.rng import Rng
from app.game.state import AcceptJobAction, ApplyJobAction, BoardMeetingAction, DeclineJobAction

cat = get_catalog()


@pytest.fixture
def window(finished):
    career = finished.model_copy(deep=True)
    if career.board.meeting:
        engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
    return career


def _club(career, reachable: bool = True) -> str:
    """An AI club without a vacancy, in or out of the manager's reach."""
    return next(t for t in sorted(career.teams) if t != career.team and jobs._vacancy(career, t) is None
                and jobs.in_reach(cat, career, t) == reachable)


def test_a_bad_season_makes_a_sacking_likelier():
    assert jobs.sack_chance(0, False, None) == 0
    assert jobs.sack_chance(3, False, None) < jobs.sack_chance(9, False, None) < jobs.sack_chance(9, True, None)
    assert jobs.sack_chance(40, True, None) == jobs.MAX_SACK
    assert jobs.sack_chance(9, True, 30) == pytest.approx(jobs.sack_chance(9, True, None) / 3), "a new coach gets time"


def test_the_end_of_a_season_sacks_coaches_and_opens_vacancies(finished):
    assert all(t.expected > 0 for t in finished.teams.values())
    assert finished.vacancies, "some club always has a season to forget"
    for vacancy in finished.vacancies:
        assert finished.teams[vacancy.team].coach is None
        points, missed = jobs.season_points(cat, finished, vacancy.team, finished.season)
        assert points > 0 or missed


def test_a_favourite_that_collapses_in_a_split_may_sack_its_coach(finished):
    comp = finished.competitions[f"{finished.season}-LCK-1"].model_copy(deep=True)
    favourite = comp.placements[0]
    comp.placements = comp.placements[1:] + [favourite]
    sacked = 0
    for seed in range(30):
        career = finished.model_copy(deep=True)
        career.team = next(t for t in career.teams if career.teams[t].league != "LCK")
        career.teams[favourite].expected = 1
        if career.teams[favourite].coach is None:
            career.teams[favourite].coach = next(s for s in cat.staff if career.staff[s].team is None)
        before = {t: career.teams[t].coach for t in comp.placements[:-1]}
        career.rs = seed
        jobs.split_review(cat, career, comp, Rng(career))
        sacked += career.teams[favourite].coach is None
        assert before == {t: career.teams[t].coach for t in before}, "nobody else fell four places"
    assert 0 < sacked < 30


def test_a_club_offers_the_job_and_the_manager_can_turn_it_down(window):
    career = window
    club = _club(career)
    vacancy = jobs.open_vacancy(cat, career, club, Rng(career))
    jobs._offer(cat, career, vacancy, approached=True)
    assert career.inbox[-1].subject.startswith("Job offer")
    engine.apply(cat, career, DeclineJobAction(type="decline_job", team=club))
    assert vacancy.declined and vacancy.offer_until is None
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, AcceptJobAction(type="accept_job", team=club))
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, ApplyJobAction(type="apply_job", team=club))


def test_taking_an_offer_moves_the_manager_to_the_new_club(window):
    career = window
    old = career.team
    roster = list(career.teams[old].roster)
    club = min((t for t in sorted(career.teams) if t != old and jobs._vacancy(career, t) is None
                and jobs.in_reach(cat, career, t)), key=lambda t: len(training.team_games(career, t)))
    career.reviewed_games = len(training.team_games(career, old))
    assert career.reviewed_games > len(training.team_games(career, club))
    vacancy = jobs.open_vacancy(cat, career, club, Rng(career))
    jobs._offer(cat, career, vacancy, approached=False)
    engine.apply(cat, career, AcceptJobAction(type="accept_job", team=club))
    assert career.reviewed_games == len(training.team_games(career, club)), "the analyst starts over"
    assert career.team == club and career.league == cat.teams[club].league
    assert career.board.meeting and not career.board.sacked
    assert career.teams[club].coach is not None, "the board hires the manager an assistant"
    assert jobs._vacancy(career, club) is None
    assert career.teams[old].roster == roster


def test_a_club_out_of_reach_turns_an_application_down(window):
    career = window
    career.manager_reputation = 30
    club = _club(career, reachable=False)
    vacancy = jobs.open_vacancy(cat, career, club, Rng(career))
    engine.apply(cat, career, ApplyJobAction(type="apply_job", team=club))
    assert vacancy.applied and vacancy.offer_until is None
    assert career.inbox[-1].subject.endswith("turn you down")
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, ApplyJobAction(type="apply_job", team=club))


def test_a_vacancy_left_open_is_filled_when_it_closes(window):
    career = window
    club = _club(career)
    vacancy = jobs.open_vacancy(cat, career, club, Rng(career))
    vacancy.offer_until = None
    coach = career.teams[club].coach
    career.staff[coach].team = None
    career.teams[club].coach = None
    career.day = vacancy.closes
    jobs.daily(cat, career)
    assert career.teams[club].coach is not None and jobs._vacancy(career, club) is None
    assert career.teams[club].coach_since == career.day
