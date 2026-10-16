"""Retirements: announced at one off-season, carried out at the next."""

import pytest

from app.game import contracts, engine, offseason, retirement, rookies, roster, shortlist, training, views
from app.game.catalog import get_catalog
from app.game.rng import Rng
from app.game.state import BoardMeetingAction

cat = get_catalog()


@pytest.fixture
def window(finished):
    career = finished.model_copy(deep=True)
    if career.board.meeting:
        engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
    return career


def test_ages_are_real_where_liquipedia_has_a_birth_date(finished):
    mine = rookies.catalog_for(cat, finished)
    faker = next(p.id for p in cat.players.values() if p.name == "Faker")
    assert cat.players[faker].born == "1996-05-07"
    assert retirement.career_age(mine, finished, faker) == pytest.approx(finished.season - 1996 + 0.65, abs=0.02)
    assert retirement.career_age(mine, finished, finished.rookies[0].id) < 21
    unknown = max((p for p in cat.players.values() if not p.born), key=lambda p: p.experience)
    assert retirement.career_age(mine, finished, unknown.id) <= 28 + finished.season - 2026, "games stand in, eight years at most"
    assert retirement.chance(mine, finished, faker) > 0.1, "a legend past 30 may well stop"


def test_age_takes_a_veteran_down_and_training_does_not_bring_them_back(finished):
    career = finished.model_copy(deep=True)
    mine = rookies.catalog_for(cat, career)
    faker = next(p.id for p in cat.players.values() if p.name == "Faker")
    career.season = 2030  # 34
    assert training.growth_target(mine, career, faker) < roster.overall(mine, career, faker) - 3
    before = roster.overall(mine, career, faker)
    offseason.develop(mine, career, Rng(career))
    assert roster.overall(mine, career, faker) < before


def test_a_top_flight_player_nobody_signs_for_two_or_three_seasons_retires(window):
    career = window
    mine = rookies.catalog_for(cat, career)
    free = [pid for pid, s in career.players.items()
            if s.team is None and not s.retired and s.retiring is None and retirement._top_flight(mine, career, pid)]
    tier_two = next(pid for pid, s in career.players.items()
                    if s.team is None and not s.retired and not retirement._top_flight(mine, career, pid))
    assert len(free) >= 10
    for state in career.players.values():
        state.unsigned = 0  # the first off-season has counted one already
    rng = Rng(career)
    assert not retirement.unsigned(mine, career, rng), "one season without a club is not enough"
    second = retirement.unsigned(mine, career, rng)
    assert second and len(second) < len(free), "after two, some give up"
    third = retirement.unsigned(mine, career, rng)
    assert set(second) | set(third) == set(free), "after three, everyone has"
    assert all(career.players[pid].retired for pid in free)
    assert not career.players[tier_two].retired, "tier-two players are free agents only for want of their clubs"
    assert career.players[tier_two].unsigned == 0


def test_players_still_among_the_best_do_not_stop_before_thirty(finished):
    mine = rookies.catalog_for(cat, finished)
    career = finished.model_copy(deep=True)
    stars = [pid for pid in career.players if roster.overall(mine, career, pid) >= retirement.STAR]
    assert stars
    for season in range(career.season, career.season + 6):
        career.season = season
        for pid in stars:
            if retirement.career_age(mine, career, pid) < retirement.STAR_AGE:
                assert retirement.chance(mine, career, pid) == 0, cat.players[pid].name
    veteran = max((pid for pid in career.players if 70 <= roster.overall(mine, career, pid) < retirement.GOOD),
                  key=lambda pid: retirement.career_age(mine, career, pid))
    assert retirement.chance(mine, career, veteran) > 0, "an older player past their best can still stop"


def test_some_players_announce_their_last_season_at_the_first_off_season(finished):
    announced = [pid for pid, s in finished.players.items() if s.retiring is not None]
    assert announced, "every off-season someone says the next season will be their last"
    assert all(finished.players[pid].retiring == finished.season + 1 for pid in announced)
    assert not any(s.retired for s in finished.players.values()), "nobody retires without a year's notice"


def test_a_retiring_franchise_player_lets_the_manager_choose_and_an_ai_club_names_its_best(window):
    career = window
    mine = rookies.catalog_for(cat, career)
    team = career.teams[career.team]
    star = team.franchise
    other = next(t for t in career.teams.values() if t.id != career.team and t.franchise)
    theirs = other.franchise
    career.players[star].retiring = career.season
    career.players[theirs].retiring = career.season
    retirement.retire(mine, career, career.season)
    assert team.franchise is None and career.franchise_choice is not None and star not in team.roster
    assert any(m.subject == "Name a new franchise player" for m in career.inbox)
    best = max(other.roster, key=lambda p: (roster.overall(mine, career, p), mine.players[p].reputation))
    assert other.franchise == best and theirs not in other.roster


def test_a_player_retires_when_their_last_season_ends(window):
    career = window
    mine = rookies.catalog_for(cat, career)
    team = career.teams[career.team]
    pid = next(p for p in team.roster if p != team.franchise)
    other = next(p.id for p in cat.players.values() if career.players[p.id].team is None and career.players[p.id].retiring is None)
    shortlist.add(mine, career, other)
    career.players[pid].retiring = career.season
    career.players[other].retiring = career.season
    gone = retirement.retire(mine, career, career.season)
    assert {pid, other} <= set(gone)
    assert career.players[pid].retired and career.players[pid].team is None and pid not in team.roster
    assert pid not in team.lineup.values()
    assert shortlist.entry(career, other) is None
    assert contracts.check_can_talk(mine, career, other) == f"{cat.players[other].name} has retired"
    found = views.players_search(mine, career, None, False, None, 5000)
    assert not {pid, other} & {row["id"] for row in found}
    assert any(m.subject == f"{cat.players[pid].name} retires" for m in career.inbox)


def test_a_save_whose_franchise_player_already_retired_gets_a_new_one(window):
    career = window
    team = career.teams[career.team]
    star = team.franchise
    career.players[star].retired = True
    team.roster.remove(star)
    assert engine.migrate(cat, career)
    assert team.franchise in team.roster and team.franchise != star
