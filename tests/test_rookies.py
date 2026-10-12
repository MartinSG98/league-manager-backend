"""Rookie classes: generated players from the first off-season on."""

from collections import Counter

import pytest

from app.game import contracts, engine, rookies, views
from app.game.catalog import get_catalog
from app.game.state import BoardMeetingAction, OfferAction

cat = get_catalog()


@pytest.fixture
def window(finished):
    career = finished.model_copy(deep=True)
    if career.board.meeting:
        engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
    return career


def test_no_rookies_before_the_first_off_season(drafted):
    assert drafted.rookies == []
    assert rookies.catalog_for(cat, drafted) is cat


def test_the_first_off_season_brings_a_rookie_class_to_every_region(finished):
    career = finished
    assert career.rookies, "a class turns pro when the first season ends"
    mine = rookies.catalog_for(cat, career)
    assert not {r.id for r in career.rookies} & set(cat.players), "the shared catalog is never changed"
    regions = Counter(mine.leagues[mine.players[r.id].league].region for r in career.rookies)
    assert set(regions) == set(cat.regions)
    assert all(career.players[r.id].team is None for r in career.rookies), "rookies start as free agents"
    assert all(r.season == career.season + 1 for r in career.rookies)
    assert len({r.name for r in career.rookies}) == len(career.rookies)
    assert not {r.name for r in career.rookies} & {p.name for p in cat.players.values()}
    potentials = [r.potential for r in career.rookies]
    assert min(potentials) < 58 and max(potentials) >= 86, "busts and real prospects in the same class"
    assert all(r.overall < r.potential for r in career.rookies)
    assert any(m.subject == f"The {career.season + 1} rookie class turns pro" for m in career.inbox)


def test_rookies_show_up_in_searches_and_can_be_signed(window):
    career = window
    mine = rookies.catalog_for(cat, career)
    found = views.players_search(mine, career, None, True, None, 2000, rookies_only=True)
    assert found and all(row["rookie"] for row in found)
    assert len(found) == len(career.rookies)
    target = min(career.rookies, key=lambda r: contracts.ask(mine, career, r.id).salary)  # one the budget fits
    ask = contracts.ask(mine, career, target.id)
    engine.apply(cat, career, OfferAction(type="offer", player=target.id, salary=ask.salary, years=ask.years))
    assert career.players[target.id].team == career.team
