"""Retirements: announced at one off-season, carried out at the next."""

import pytest

from app.game import contracts, engine, retirement, rookies, shortlist, views
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
    assert 28 <= retirement.career_age(mine, finished, faker) <= 33
    assert retirement.career_age(mine, finished, rookie) < 21
    assert retirement.chance(mine, finished, faker) > retirement.chance(mine, finished, rookie)
    assert retirement.chance(mine, finished, faker) < 0.1, "a legend still at the top keeps going"


def test_some_players_announce_their_last_season_at_the_first_off_season(finished):
    announced = [pid for pid, s in finished.players.items() if s.retiring is not None]
    assert announced, "every off-season someone says the next season will be their last"
    assert all(finished.players[pid].retiring == finished.season + 1 for pid in announced)
    assert not any(s.retired for s in finished.players.values()), "nobody retires without a year's notice"


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
