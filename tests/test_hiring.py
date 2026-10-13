"""The staff market: hiring, extending and releasing coaches and analysts, and new faces."""

import pytest

from app.game import engine, hiring, rookies, roster, views
from app.game.catalog import get_catalog
from app.game.errors import IllegalAction
from app.game.state import BoardMeetingAction, StaffAcceptCounterAction, StaffOfferAction, StaffReleaseAction

base = get_catalog()


@pytest.fixture
def window(finished):
    career = finished.model_copy(deep=True)
    if career.board.meeting:
        engine.apply(base, career, BoardMeetingAction(type="board_meeting"))
    team = career.teams[career.team]
    team.cash = 5000
    team.budget += 1000
    return career


def _cat(career):
    return rookies.catalog_for(base, career)


def _pick(career, kind: str, free: bool) -> str:
    """A staff member of the manager's region who would come."""
    cat = _cat(career)
    region = cat.teams[career.team].region
    for s in sorted(cat.staff.values(), key=lambda s: -s.overall):
        state = career.staff.get(s.id)
        employed = bool(state and state.team)
        if s.kind != kind or s.region != region or employed == free or (state and state.team == career.team):
            continue
        if hiring.stars_wanted(cat, s.id) <= 2:
            return s.id
    raise AssertionError("nobody to hire")


def _empty_seat(career, kind: str) -> None:
    sid = getattr(career.teams[career.team], kind)
    if sid:
        engine.apply(base, career, StaffReleaseAction(type="staff_release", staff=sid))


def test_releasing_your_coach_costs_half_the_contract_and_empties_the_seat(window):
    career = window
    team = career.teams[career.team]
    sid = team.coach
    cost = hiring.release_cost(career, sid)
    cash = team.cash
    engine.apply(base, career, StaffReleaseAction(type="staff_release", staff=sid))
    assert team.coach is None and career.staff[sid].team is None and team.cash == cash - cost


def test_hiring_a_free_coach_at_the_ask(window):
    career = window
    _empty_seat(career, "coach")
    sid = _pick(career, "coach", free=True)
    with pytest.raises(IllegalAction):
        engine.apply(base, career, StaffOfferAction(type="staff_offer", staff=sid, salary=100, years=5))
    ask = hiring.asking_salary(_cat(career), career, sid)
    engine.apply(base, career, StaffOfferAction(type="staff_offer", staff=sid, salary=ask, years=2))
    team = career.teams[career.team]
    assert team.coach == sid and career.staff[sid].contract.salary == ask
    assert career.staff[sid].contract.until == career.season + 2
    assert roster.payroll(career, team) >= ask


def test_another_clubs_analyst_costs_compensation_and_their_club_replaces_them(window):
    career = window
    _empty_seat(career, "analyst")
    cat = _cat(career)
    sid = _pick(career, "analyst", free=False)
    old = career.staff[sid].team
    fee = hiring.compensation(cat, career, sid)
    cash, their_cash = career.teams[career.team].cash, career.teams[old].cash
    ask = hiring.asking_salary(cat, career, sid)
    assert ask > cat.staff[sid].salary, "leaving a club costs a premium"
    engine.apply(base, career, StaffOfferAction(type="staff_offer", staff=sid, salary=ask, years=2))
    assert career.teams[career.team].analyst == sid
    assert career.teams[career.team].cash == cash - fee and career.teams[old].cash == their_cash + fee
    assert career.teams[old].analyst not in (None, sid), "their club appoints someone at once"


def test_a_low_offer_brings_a_counter_and_too_many_end_the_talks(window):
    career = window
    _empty_seat(career, "coach")
    sid = _pick(career, "coach", free=True)
    ask = hiring.asking_salary(_cat(career), career, sid)
    engine.apply(base, career, StaffOfferAction(type="staff_offer", staff=sid, salary=int(ask * 0.75), years=2))
    talks = career.staff_talks[sid]
    assert talks.counter and career.teams[career.team].coach is None
    engine.apply(base, career, StaffAcceptCounterAction(type="staff_accept_counter", staff=sid))
    assert career.teams[career.team].coach == sid

    other = _pick(career, "analyst", free=True)
    _empty_seat(career, "analyst")
    low = int(hiring.asking_salary(_cat(career), career, other) * 0.7)
    for _ in range(hiring.MAX_ROUNDS):
        engine.apply(base, career, StaffOfferAction(type="staff_offer", staff=other, salary=low, years=2))
    assert career.staff_talks[other].blocked_until is not None
    assert "does not want to talk" in hiring.check_can_talk(_cat(career), career, other)


def test_your_own_staff_are_extended_in_their_last_season_or_leave(window):
    career = window
    team = career.teams[career.team]
    sid = team.coach
    career.staff[sid].contract.until = career.season + 1
    assert "beyond this season" in hiring.check_can_talk(_cat(career), career, sid)
    career.staff[sid].contract.until = career.season
    assert hiring.check_can_talk(_cat(career), career, sid) is None
    assert sid in hiring.expiring(career)
    hiring.contracts_run_out(_cat(career), career)
    assert team.coach is None and career.staff[sid].team is None


def test_a_big_name_wants_a_bigger_club(window):
    career = window
    _empty_seat(career, "coach")
    cat = _cat(career)
    star = max((s for s in cat.staff.values() if s.kind == "coach"), key=lambda s: s.overall)
    career.teams[career.team].reputation = 30
    if hiring.stars_wanted(cat, star.id) > 1:
        assert "bigger club" in hiring.check_can_talk(cat, career, star.id)


def test_every_off_season_brings_new_faces_to_the_staff_market(finished):
    cat = _cat(finished)
    newcomers = [s for s in finished.new_staff if s.position == "Newcomer"]
    regions = {t.region for t in cat.teams.values() if t.id in finished.teams}
    assert len(newcomers) == 2 * len(regions)
    for s in finished.new_staff:
        assert s.id in cat.staff and s.id in finished.staff and finished.staff[s.id].team is None
    found = {row["id"] for row in views.staff_search(cat, finished, None, None, True, 2000)}
    assert {s.id for s in finished.new_staff} <= found
    detail = views.staff_detail(cat, finished, newcomers[0].id)
    assert detail["joined_market"] == finished.season + 1 and detail["ask"] > 0
