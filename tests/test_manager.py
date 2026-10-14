"""The manager as a person: created once, sharing the staff's work, with three attributes of their own."""

import pytest

from app.game import contracts, engine, manager, plays, reputation, staff
from app.game.catalog import get_catalog
from app.game.errors import IllegalAction
from app.game.state import (
    BoardMeetingAction, CreateManagerAction, DraftNextAction, DraftSimAction, ReadMessageAction, SetDutyAction,
)

cat = get_catalog()


def _create(career, background="pro", attributes=None, **extra):
    attributes = attributes or manager.even_spread(career, background)
    engine.apply(cat, career, CreateManagerAction(type="create_manager", background=background, attributes=attributes,
                                                  **extra))


def test_a_new_career_waits_for_its_manager_who_brings_a_background():
    career = engine.new_career(cat, "Tester", "GAM", 5)
    with pytest.raises(IllegalAction, match="Create your manager"):
        engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
    engine.apply(cat, career, DraftNextAction(type="draft_next", until_mine=True))
    assert career.drafts["LCP"].number == 0, "the draft waits for the manager"
    engine.apply(cat, career, ReadMessageAction(type="read_message"))  # anything else still works

    before = career.manager_reputation
    spread = manager.even_spread(career, "pro")
    _create(career, "pro", spread, name="  Martin   SG ", country="BG")
    p = career.profile
    assert career.manager == "Martin SG" and p.country == "BG" and p.background == "pro"
    assert p.attributes["drafting"] == spread["drafting"] + 3 and p.attributes["tactics"] == spread["tactics"]
    assert career.manager_reputation == before + 4
    with pytest.raises(IllegalAction, match="already"):
        _create(career)
    engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
    engine.apply(cat, career, DraftSimAction(type="draft_sim"))
    assert career.phase == "season"


def test_points_have_limits_and_a_bigger_name_gets_more():
    small = engine.new_career(cat, "Tester", "DSG", 5)
    big = engine.new_career(cat, "Tester", "T1", 5)
    assert manager.points(big.manager_reputation, "coach") > manager.points(small.manager_reputation, "coach")
    assert manager.points(small.manager_reputation, "newcomer") == manager.points(small.manager_reputation, "coach") + 5

    spread = manager.even_spread(small, "coach")
    too_many = dict(spread, tactics=spread["tactics"] + 1)
    with pytest.raises(IllegalAction, match="more than you have"):
        _create(small, "coach", too_many)
    with pytest.raises(IllegalAction, match="from 1 to 15"):
        _create(small, "coach", dict(spread, tactics=16, meta=1))
    with pytest.raises(IllegalAction, match="every attribute"):
        _create(small, "coach", {k: v for k, v in spread.items() if k != "meta"})
    # Lowering one attribute pays for another.
    _create(small, "coach", dict(spread, meta=1, tactics=spread["tactics"] + spread["meta"] - 1))
    assert small.profile.attributes["meta"] == 1


def test_the_better_of_manager_and_staff_does_the_work_unless_the_manager_says_otherwise(drafted):
    career = drafted.model_copy(deep=True)
    team = career.teams[career.team]
    coach = cat.staff[team.coach].attributes["drafting"]
    career.profile.attributes["drafting"] = float(coach + 3)
    assert staff.attribute(cat, career, career.team, "drafting") == coach + 3, "left to the game, the better one"
    career.profile.attributes["drafting"] = float(coach - 3)
    assert staff.attribute(cat, career, career.team, "drafting") == coach

    engine.apply(cat, career, SetDutyAction(type="set_duty", attribute="drafting", who="manager"))
    assert staff.attribute(cat, career, career.team, "drafting") == coach - 3, "the manager took it on"
    view = next(d for d in manager.view(cat, career)["duties"] if d["attribute"] == "drafting")
    assert view["who"] == "manager" and view["choice"] == "manager" and view["staff_value"] == coach
    engine.apply(cat, career, SetDutyAction(type="set_duty", attribute="drafting", who="auto"))
    assert "drafting" not in career.profile.duties

    team.analyst = None
    career.profile.attributes["scouting"] = 7.6
    assert staff.attribute(cat, career, career.team, "scouting") == 7, "an empty seat falls to the manager"
    other = next(t for t in career.teams.values() if t.id != career.team and t.coach)
    assert staff.attribute(cat, career, other.id, "drafting") == cat.staff[other.coach].attributes["drafting"]
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, SetDutyAction(type="set_duty", attribute="negotiation", who="staff"))


def test_negotiation_man_management_and_tactics_are_the_managers_own(drafted):
    career = drafted.model_copy(deep=True)
    pid = next(p for p in cat.players if career.players[p].team is None and cat.players[p].overall >= 60)

    career.profile.attributes["negotiation"] = 20.0
    hard = contracts.ask(cat, career, pid).floor
    career.profile.attributes["negotiation"] = 1.0
    soft = contracts.ask(cat, career, pid).floor
    assert hard < soft and manager.haggle(career) > 1

    career.profile.attributes["tactics"] = 20.0
    enemy = next(t for t in career.teams if t != career.team)
    play = next(iter(plays.PLAYS))
    sharp = plays.team_chance(cat, career, career.team, enemy, play, 0.5)
    career.profile.attributes["tactics"] = 10.0
    assert sharp > plays.team_chance(cat, career, career.team, enemy, play, 0.5)
    assert plays.team_chance(cat, career, enemy, career.team, play, 0.5) == plays.chance(
        plays.PLAYS[play], career.teams[enemy].plays.get(play, 0.0),
        career.teams[enemy].skills.get(plays.PLAYS[play].area, 10.0),
        career.teams[career.team].skills.get(plays.PLAYS[play].area, 10.0), 0.5), "other clubs get no bonus"

    career.profile = None
    assert manager.own(career, "man_management") == manager.NEUTRAL and manager.haggle(career) == 1


def test_a_good_negotiator_buys_below_the_asking_fee_and_a_poor_one_pays_it(finished):
    from app.game import transfers
    from app.game.state import TransferBidAction

    def bid(negotiation: float, share: float) -> str:
        career = finished.model_copy(deep=True)
        if career.board.meeting:
            engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
        career.teams[career.team].cash = 50000
        career.profile.attributes["negotiation"] = negotiation
        pid = next(p for p in cat.players if career.players[p].team not in (None, career.team)
                   and transfers.check_bid(cat, career, p) is None)
        ask = transfers.asking_fee(cat, career, pid)
        engine.apply(cat, career, TransferBidAction(type="transfer_bid", player=pid, fee=int(ask * share)))
        return career.offers[-1].status

    assert bid(20.0, 0.95) == "agreed"
    assert bid(10.0, 0.95) == "open", "an average negotiator gets a counter at the asking fee"
    assert bid(1.0, 1.0) == "agreed", "a poor one still gets the player at the asking fee"


def test_the_season_is_kept_when_it_ends_and_counted_once(finished):
    career = finished
    assert career.phase == "offseason"
    kept = [s for s in career.manager_seasons if s.season == career.season]
    assert len(kept) == 1 and kept[0].competitions
    record = manager.record_view(cat, career)
    assert [s["season"] for s in record["seasons"]].count(career.season) == 1, "not counted again from the matches"
    season = record["seasons"][0]
    total = sum(c.series[0] + c.series[1] for c in kept[0].competitions)
    assert sum(season["series"]) == total > 0
    assert all(c.team for c in kept[0].competitions)
    assert record["totals"]["titles"] == len(record["trophies"])
    assert all(s.end is not None for s in career.spells[:-1])


def test_a_sacking_ends_a_spell_and_a_new_job_starts_one(drafted):
    from app.game import board
    from app.game.rng import Rng
    from app.game.state import AcceptJobAction

    career = drafted.model_copy(deep=True)
    assert [s.team for s in career.spells] == ["G2"] and career.spells[0].end is None
    before = career.manager_reputation
    board.sack(cat, career, Rng(career))
    assert career.spells[-1].end == career.day and career.spells[-1].left == "sacked"
    regional = reputation.manager_in(career, career.region)
    assert career.reputation_log[-1] == (career.day, career.manager_reputation, regional)
    assert career.manager_reputation < before
    engine.apply(cat, career, AcceptJobAction(type="accept_job", team=career.job_offers[0]))
    assert career.spells[-1].team == career.team != "G2" and career.spells[-1].end is None
    clubs = manager.record_view(cat, career)["clubs"]
    assert [c["team"]["id"] for c in clubs] == [career.team, "G2"]


def test_the_manager_has_a_world_and_a_region_reputation():
    from app.game import board

    career = engine.new_career(cat, "Tester", "GAM", 5)
    regional = reputation.manager_in(career, "APAC")
    assert career.manager_standing == {"APAC": regional}
    assert career.manager_reputation == round(50 + (regional - 50) * 0.8, 1), "the world weighs the LCP at 80 percent"
    # A league title: the region in full, the world by the league's strength.
    world = career.manager_reputation
    reputation.change_manager(cat, career, 3.0)
    assert reputation.manager_in(career, "APAC") == regional + 3 and career.manager_reputation == round(world + 2.4, 1)
    # An international title: both in full.
    reputation.change_manager(cat, career, 6.0, everywhere=True)
    assert reputation.manager_in(career, "APAC") == regional + 9 and career.manager_reputation == round(world + 8.4, 1)
    # Somewhere they never worked, they are their world name; clubs judge them on their own scale.
    assert reputation.manager_in(career, "KR") == career.manager_reputation
    mine, club = reputation.manager_vs_club(cat, career, "CFO")
    assert mine == reputation.stars(reputation.manager_in(career, "APAC"))
    mine, club = reputation.manager_vs_club(cat, career, "T1")
    assert mine == reputation.stars(career.manager_reputation) and club == 5
    assert not board.jobs_in_reach(cat, career, "T1") and board.jobs_in_reach(cat, career, "CFO")


def test_an_older_save_splits_its_managers_reputation():
    career = engine.new_career(cat, "Tester", "GAM", 5)
    career.manager_standing = {}
    career.manager_reputation = 81.8
    career.reputation_log = [(career.day, 81.8)]
    engine.migrate(cat, career)
    assert career.manager_standing == {"APAC": 81.8} and career.manager_reputation == round(50 + 31.8 * 0.8, 1)
    assert career.reputation_log == [(career.day, career.manager_reputation, 81.8)]
