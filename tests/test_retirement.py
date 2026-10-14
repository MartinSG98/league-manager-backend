"""Retirements: announced at one off-season, carried out at the next."""

import pytest

from app.game import contracts, engine, retirement, rookies, roster, shortlist, views
from app.game.catalog import get_catalog
from app.game.state import BoardMeetingAction

cat = get_catalog()


@pytest.fixture
def window(finished):
    career = finished.model_copy(deep=True)
    if career.board.meeting:
        engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
    return career


def test_career_age_puts_veterans_far_above_rookies(finished):
    mine = rookies.catalog_for(cat, finished)
    faker = next(p.id for p in cat.players.values() if p.name == "Faker")
    rookie = finished.rookies[0].id
    assert 24 <= retirement.career_age(mine, finished, faker) <= 29, "past eight years, games add no age"
    assert retirement.career_age(mine, finished, rookie) < 21
    assert retirement.chance(mine, finished, faker) < 0.1, "a legend still at the top keeps going"


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


def test_a_retiring_franchise_player_hands_the_role_to_the_best_player_left(window):
    career = window
    mine = rookies.catalog_for(cat, career)
    team = career.teams[career.team]
    star = team.franchise
    career.players[star].retiring = career.season
    retirement.retire(mine, career, career.season)
    best = max(team.roster, key=lambda p: (roster.overall(mine, career, p), mine.players[p].reputation))
    assert team.franchise == best and star not in team.roster
    assert career.inbox[-1].subject == f"{mine.players[best].name} is the new franchise player"


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
