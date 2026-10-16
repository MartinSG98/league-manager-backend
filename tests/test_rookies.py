"""Rookie classes: generated players from the first off-season on."""

from collections import Counter

import pytest

from app.game import contracts, engine, rookies, training, views
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


def test_a_careers_catalog_is_built_once_until_a_new_class_arrives(finished):
    career = finished.model_copy(deep=True)
    assert career.rookies
    first = rookies.catalog_for(cat, career)
    assert rookies.catalog_for(cat, career) is first, "built once per career"
    assert rookies.catalog_for(first, career) is first, "an already merged catalog comes back as it is"
    other = career.model_copy(deep=True)
    assert rookies.catalog_for(cat, other) is not first, "another career gets its own"
    career.rookies.append(career.rookies[0].model_copy(update={"id": "r-test", "name": "Testo"}))
    fresh = rookies.catalog_for(cat, career)
    assert fresh is not first and "r-test" in fresh.players and "r-test" not in first.players


def test_prospects_start_far_below_a_ceiling_the_scouts_overrate(finished):
    career = finished
    mine = rookies.catalog_for(cat, career)
    prospects = [r for r in career.rookies if r.potential >= 85]
    assert all(r.potential - r.overall >= 18 for r in prospects), "about three seasons from their potential"
    offsets = [training.ceiling(mine, career, r.id) - r.potential for r in career.rookies]
    low, high = training.ROOKIE_CEILING
    assert all(low <= o <= high for o in offsets)
    assert sum(offsets) / len(offsets) < -2, "the scouts' first read of a rookie is a hopeful one"
    assert sum(o <= -5 for o in offsets) >= len(offsets) / 5, "some never get near it"


def test_an_established_player_s_ceiling_is_close_to_the_potential_and_training_adds_at_most_two(finished):
    career = finished.model_copy(deep=True)
    pids = [p for p in cat.players if p in career.players][:200]
    assert all(abs(training.ceiling(cat, career, p) - cat.players[p].potential) <= training.CEILING_SPREAD for p in pids)
    pid = pids[0]
    career.players[pid].development = [1.6] * 26
    assert training.growth_target(cat, career, pid) == pytest.approx(training.ceiling(cat, career, pid) + training.TRAINING_BONUS)
    career.players[pid].development = [0.5] * 26
    assert training.growth_target(cat, career, pid) == pytest.approx(training.ceiling(cat, career, pid) - 2)
