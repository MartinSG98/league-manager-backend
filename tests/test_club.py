"""The board, reputation, training, set plays and the transfer window."""

from datetime import date, timedelta

import pytest

from app.game import board, engine, finances, match_engine, reputation, rookies, roster, shortlist, training, transfers
from app.game import plays as set_plays
from app.game.catalog import ROLES, get_catalog
from app.game.errors import IllegalAction
from app.game.rng import Rng
from app.game.state import (
    AcceptJobAction, AdjustBudgetAction, AdvanceAction, AutoSelectAction, BoardMeetingAction, Competition,
    DraftNextAction, DraftSimAction, OfferAction, PlayGameAction, RespondOfferAction, ScoutPlayerAction, SetPlayAction,
    SetPlayerTrainingAction, SetTrainingAction, ShortlistAction, TalkAction, TransferBidAction, TransferListAction,
)

from tests.conftest import create_manager

cat = get_catalog()


class Always:
    """An rng stand-in whose every chance comes true."""

    rs = 0

    def chance(self, p: float) -> bool:
        return True

    def next(self) -> float:
        return 0.0

    def pick(self, items):
        return items[0] if items else None


def _split(career, split: int, places: list[str]) -> Competition:
    comp = Competition(id=f"{career.board.season}-{career.league}-{split}", name="x", short="x", kind="league",
                       league=career.league, split=split, start=career.day, end=career.day, placements=places,
                       entrants=places, status="finished")
    career.competitions[comp.id] = comp
    return comp


def _last(career) -> list[str]:
    league = [t.id for t in cat.league_teams(career.league)]
    return [t for t in league if t != career.team] + [career.team]


# ---------- the board ----------


def test_a_new_career_starts_with_a_board_meeting_that_holds_the_draft():
    career = create_manager(engine.new_career(cat, "Tester", "T1", 3))
    assert career.board.meeting
    assert [o.kind for o in career.board.objectives] == ["split", "split", "split", "worlds"]
    # The favourite is asked for a lot.
    assert career.board.objectives[0].target <= 2 and career.board.objectives[-1].target >= 2
    d = career.drafts["LCK"]
    engine.apply(cat, career, DraftNextAction(type="draft_next", until_mine=True))
    assert d.number == 0, "the draft waits for the meeting"
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, DraftSimAction(type="draft_sim"))

    budget = career.teams["T1"].budget
    engine.apply(cat, career, BoardMeetingAction(type="board_meeting", stances={"split1": 1, "split2": 1}))
    assert not career.board.meeting
    first = career.board.objectives[0]
    assert first.target == first.proposed - 1
    assert career.teams["T1"].budget > budget


def test_a_small_club_is_only_asked_to_stay_off_the_bottom():
    career = engine.new_career(cat, "Tester", "DSG", 3)
    size = len(cat.league_teams("LCS"))
    assert career.board.objectives[0].target == size - 1
    assert career.board.objectives[-1].target == 0
    assert reputation.stars(career.teams["DSG"].reputation) < reputation.stars(career.teams["C9"].reputation)


def test_a_club_is_bigger_in_its_region_than_in_the_world(drafted):
    career = drafted
    gam = reputation.ratings(cat, career, "GAM")
    assert gam["region"] == "LCP" and gam["region_stars"] > gam["world_stars"]
    biggest = max(cat.league_teams("LCP"), key=lambda t: career.teams[t.id].reputation)
    assert reputation.ratings(cat, career, biggest.id)["region_stars"] == 5
    # The same club in the LCK's eyes and the world's: the strongest league loses nothing.
    t1 = career.teams["T1"].reputation
    assert reputation.world(cat, career, "T1") == t1
    # A player from the region sees GAM on its scale, one from elsewhere on the world's.
    plain = career.teams["GAM"].reputation
    home, _ = reputation.compared(cat, career, "GAM", None, "APAC")
    abroad, _ = reputation.compared(cat, career, "GAM", None, "KR")
    assert abroad < plain <= home
    # Two clubs of the player's region side by side keep their gap.
    a, b = reputation.compared(cat, career, "GAM", "CFO", "APAC")
    assert round(a - b, 6) == round(plain - career.teams["CFO"].reputation, 6)


def test_missing_objectives_warns_then_sacks_and_other_clubs_call(drafted):
    career = drafted.model_copy(deep=True)
    career.day += timedelta(days=120)  # past the grace period of a new job
    rng = Rng(career)
    career.board.confidence = 30
    board.after_competition(cat, career, _split(career, 1, _last(career)), rng)
    assert career.board.warned and not career.board.sacked
    assert career.board.objectives[0].status == "failed"
    board.after_competition(cat, career, _split(career, 2, _last(career)), rng)
    assert career.board.sacked
    assert len(career.job_offers) == 3 and career.team not in career.job_offers
    reach = reputation.stars(career.manager_reputation) + reputation.STAR_REACH
    assert all(reputation.stars(reputation.team_reputation(cat, career, t)) <= reach for t in career.job_offers)

    with pytest.raises(IllegalAction):
        engine.apply(cat, career, AdvanceAction(type="advance"))
    new = career.job_offers[0]
    engine.apply(cat, career, AcceptJobAction(type="accept_job", team=new))
    assert career.team == new and career.league == cat.teams[new].league
    assert career.board.meeting and not career.board.sacked
    assert career.board.confidence == board.START_CONFIDENCE


def test_a_new_job_is_safe_for_its_first_split(drafted):
    career = drafted.model_copy(deep=True)
    career.board.confidence = 5
    board.after_competition(cat, career, _split(career, 1, _last(career)), Rng(career))
    assert not career.board.warned and not career.board.sacked


def test_titles_raise_both_reputations(drafted):
    career = drafted.model_copy(deep=True)
    before, manager = career.teams[career.team].reputation, career.manager_reputation
    places = [career.team] + [t for t in _last(career) if t != career.team]
    reputation.after_competition(cat, career, _split(career, 1, places))
    assert career.teams[career.team].reputation > before
    assert career.manager_reputation > manager


def test_qualifying_for_msi_and_a_deep_run_are_bonuses(drafted):
    career = drafted.model_copy(deep=True)
    assert {b.id for b in career.board.bonuses} == {x[0] for x in board.BONUSES}
    others = [t for t in _last(career) if t != career.team]
    confidence, cash = career.board.confidence, career.teams[career.team].cash
    msi = Competition(id=f"{career.board.season}-MSI", name="MSI", short="Mid-Season Invitational",
                      kind="international", start=career.day, end=career.day, entrants=[career.team] + others[:7])
    career.competitions[msi.id] = msi
    board.event_created(cat, career, msi)
    qualify = next(b for b in career.board.bonuses if b.id == "MSI-in")
    assert qualify.status == "earned" and career.board.confidence == confidence + qualify.confidence
    assert career.teams[career.team].cash == cash + board.bonus_payment(career, qualify)
    msi.placements = [others[0], career.team] + others[1:7]
    msi.status = "finished"
    board.after_competition(cat, career, msi, Rng(career))
    status = {b.id: b.status for b in career.board.bonuses}
    assert status["MSI-top4"] == "earned" and status["MSI-final"] == "earned"

    # Missing First Stand costs nothing.
    before = career.board.confidence
    fst = Competition(id=f"{career.board.season}-FST", name="FST", short="First Stand", kind="international",
                      start=career.day, end=career.day, entrants=others[:8])
    career.competitions[fst.id] = fst
    board.event_created(cat, career, fst)
    assert all(b.status == "missed" for b in career.board.bonuses if b.event == "FST")
    assert career.board.confidence == before


# ---------- training ----------


def _week(career, team_id: str, load: str, focus: list[str], weeks: int = 1):
    team = career.teams[team_id]
    team.training.load = load
    team.training.focus = focus
    rng = Rng(career)
    for _ in range(weeks):
        training._team_week(cat, career, team)
        for pid in team.roster:
            training._player_week(cat, career, pid, career.players[pid], rng)


def test_the_load_trades_fatigue_for_sharpness(drafted):
    hard, easy = drafted.model_copy(deep=True), drafted.model_copy(deep=True)
    _week(hard, "G2", "intense", ["teamfighting"], 3)
    _week(easy, "G2", "light", ["teamfighting"], 3)
    pid = hard.teams["G2"].lineup["MID"]
    assert hard.players[pid].fatigue > easy.players[pid].fatigue
    assert hard.players[pid].sharpness > easy.players[pid].sharpness
    assert easy.players[pid].sharpness < drafted.players[pid].sharpness
    assert hard.teams["G2"].skills["teamfighting"] > easy.teams["G2"].skills["teamfighting"]


def test_a_focused_area_grows_faster_than_the_rest(drafted):
    career = drafted.model_copy(deep=True)
    team = career.teams["G2"]
    team.skills = {a: 8.0 for a in training.AREAS}
    _week(career, "G2", "normal", ["closing"], 10)
    assert team.skills["closing"] > 10
    assert all(team.skills["closing"] > team.skills[a] + 1.5 for a in training.AREAS if a != "closing")


def test_an_exhausted_player_can_burn_out(drafted):
    career = drafted.model_copy(deep=True)
    pid = career.teams["G2"].lineup["BOT"]
    state = career.players[pid]
    state.fatigue = 90
    training._player_week(cat, career, pid, state, Always())
    assert state.burnout == training.BURNOUT_WEEKS
    assert "Burned out" in training.condition_labels(state)
    assert training.quality(cat, career, pid, state, career.teams["G2"]) == 0


def test_a_set_play_is_learned_over_weeks(drafted):
    career = drafted.model_copy(deep=True)
    team = career.teams["G2"]
    unknown = next(p for p in set_plays.PLAYS if team.plays.get(p, 0) < 100)
    team.plays[unknown] = 0.0
    engine.apply(cat, career, SetTrainingAction(type="set_training", play=unknown))
    weeks = 0
    while team.plays[unknown] < 100 and weeks < 20:
        training._team_week(cat, career, team)
        weeks += 1
    assert 2 <= weeks <= 10
    assert team.training.play is None
    assert career.inbox[-1].subject.startswith("Set play learned")


def test_individual_training_learns_a_champion(drafted):
    career = drafted.model_copy(deep=True)
    pid = career.teams["G2"].lineup["MID"]
    champion = next(c.id for c in cat.champions.values() if roster.mastery(cat, career, pid, c.id) == 0)
    engine.apply(cat, career, SetPlayerTrainingAction(type="set_player_training", player=pid, champion=champion,
                                                      attribute="laning"))
    _week(career, "G2", "normal", ["macro"], 4)
    assert roster.mastery(cat, career, pid, champion) >= 12


def test_good_training_sets_a_higher_target_than_poor_training(drafted):
    career = drafted.model_copy(deep=True)
    pid = career.teams["G2"].lineup["TOP"]
    career.players[pid].development = [1.3] * 20
    good = training.growth_target(cat, career, pid)
    career.players[pid].development = [0.6] * 20
    poor = training.growth_target(cat, career, pid)
    assert good - poor > 2
    assert abs(training.ceiling(cat, career, pid) - cat.players[pid].potential) <= 6


def test_training_settings_are_checked(drafted):
    career = drafted.model_copy(deep=True)
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, SetTrainingAction(type="set_training", focus=["closing", "macro", "objectives"]))
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, SetTrainingAction(type="set_training", focus=["nonsense"]))
    known = next(p for p, v in career.teams["G2"].plays.items() if v >= 100)
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, SetTrainingAction(type="set_training", play=known))


def test_the_analyst_reviews_the_season(finished):
    reviews = [m for m in finished.inbox if m.report and m.report.get("kind") == "review"]
    assert len(reviews) >= 3
    report = reviews[-1].report
    assert {a["area"] for a in report["areas"]} == set(training.AREAS)
    assert all(a in training.AREAS for a in report["recommend"])


# ---------- the match ----------


def test_closing_out_games_makes_throws_rarer():
    assert match_engine.throw_odds(4) > 2 * match_engine.throw_odds(18) > 0


def test_set_plays_run_once_a_series_and_show_in_the_record(drafted):
    career = drafted.model_copy(deep=True)
    for _ in range(60):
        if career.live:
            break
        engine.apply(cat, career, AdvanceAction(type="advance"))
    engine.apply(cat, career, AutoSelectAction(type="auto_select"))
    assert career.live.phase == "ready"
    match = career.matches[career.live.match]
    known = set_plays.available(career, career.team, match)
    assert known
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, SetPlayAction(type="set_play", play="nonsense"))
    play = known[0]
    engine.apply(cat, career, SetPlayAction(type="set_play", play=play))
    engine.apply(cat, career, PlayGameAction(type="play_game"))
    record = match.games[-1]
    assert record.plays.get(career.team) == play
    assert play in match.plays_used[career.team]
    assert play not in set_plays.available(career, career.team, match)
    assert record.leads[0] >= 0 and record.leads[1] >= 0 and sum(record.fights) > 0


# ---------- the transfer window ----------


@pytest.fixture
def window(finished):
    career = finished.model_copy(deep=True)
    if career.board.meeting:
        engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
    return career


def test_the_off_season_opens_a_window_with_new_budgets_and_money(finished):
    assert finished.phase == "offseason" and transfers.window_open(finished)
    assert any(m.subject == "The transfer window is open" for m in finished.inbox)
    assert all(t.budget > 0 for t in finished.teams.values())


def _target(career, keen: bool = True):
    """A starter at another club the manager can bid for; keen: one who would not ask for more to come."""
    for p in sorted(cat.players.values(), key=lambda p: -roster.overall(cat, career, p.id)):
        state = career.players[p.id]
        if state.team in (None, career.team) or transfers.check_bid(cat, career, p.id) is not None:
            continue
        if keen and transfers.interest(cat, career, p.id, career.team)[0] not in ("keen", "open"):
            continue
        if career.teams[state.team].lineup.get(p.role) == p.id:
            return p.id
    raise AssertionError("nobody to bid for")


def test_buying_a_player_takes_an_agreed_fee_and_personal_terms(window):
    career = window
    team = career.teams[career.team]
    team.cash = 20000
    team.budget += 3000
    pid = _target(career)
    seller = career.players[pid].team
    ask = transfers.asking_fee(cat, career, pid)
    engine.apply(cat, career, TransferBidAction(type="transfer_bid", player=pid, fee=int(ask * 0.5)))
    assert career.offers[-1].status == "rejected"
    engine.apply(cat, career, TransferBidAction(type="transfer_bid", player=pid, fee=int(ask * 0.85)))
    offer = career.offers[-1]
    assert offer.status == "open" and offer.counter == ask
    engine.apply(cat, career, TransferBidAction(type="transfer_bid", player=pid, fee=ask))
    assert offer.status == "agreed" and career.players[pid].team == seller

    from app.game import contracts

    want = contracts.ask(cat, career, pid)
    cash = team.cash
    engine.apply(cat, career, OfferAction(type="offer", player=pid, salary=want.salary, years=want.years))
    assert career.players[pid].team == career.team and pid in team.roster
    assert pid not in career.teams[seller].roster
    assert offer.status == "completed" and team.cash == cash - ask
    assert career.teams[seller].cash >= ask


def test_a_franchise_player_is_not_for_sale_and_stars_snub_small_clubs(window):
    career = window
    other = next(t for t in career.teams.values() if t.id != career.team and t.franchise)
    assert transfers.asking_fee(cat, career, other.franchise) is None
    assert transfers.check_bid(cat, career, other.franchise) is not None
    star = max(cat.players.values(), key=lambda p: p.reputation)
    smallest = min(career.teams, key=lambda t: reputation.team_reputation(cat, career, t))
    assert transfers.interest(cat, career, star.id, smallest)[0] == "refuses"


def test_turning_down_a_bigger_club_upsets_the_player_who_asks_to_talk(window):
    career = window
    pid = next(p for p in career.teams[career.team].lineup.values() if p != career.teams[career.team].franchise)
    bigger = next(t for t in career.teams if t != career.team)
    career.teams[bigger].reputation = career.teams[career.team].reputation + 10
    offer = transfers._new_offer(career, pid, bigger, career.team, 500, 4)
    morale = career.players[pid].morale
    engine.apply(cat, career, RespondOfferAction(type="respond_offer", offer=offer.id, response="reject"))
    assert offer.status == "rejected"
    talk = career.conversations[-1]
    assert talk.player == pid and not talk.resolved and career.players[pid].morale < morale
    assert career.inbox[-1].conversation == talk.id
    engine.apply(cat, career, TalkAction(type="talk", conversation=talk.id, choice="promise"))
    assert talk.resolved and career.players[pid].promise == career.season + 1
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, TalkAction(type="talk", conversation=talk.id, choice="final"))

    # Next off-season the same kind of bid comes in and the manager says no again: the promise is broken.
    career.season += 1
    again = transfers._new_offer(career, pid, bigger, career.team, 500, 4)
    engine.apply(cat, career, RespondOfferAction(type="respond_offer", offer=again.id, response="reject"))
    assert career.players[pid].unsettled and career.conversations[-1].topic == "broken_promise"


def test_selling_a_player_banks_the_fee(window):
    career = window
    team = career.teams[career.team]
    pid = next(p for p in team.roster if p != team.franchise)
    buyer = next(t for t in career.teams if t != career.team)
    engine.apply(cat, career, TransferListAction(type="transfer_list", player=pid, listed=True))
    assert pid in team.listed
    offer = transfers._new_offer(career, pid, buyer, career.team, 400, 4)
    cash = team.cash
    engine.apply(cat, career, RespondOfferAction(type="respond_offer", offer=offer.id, response="accept"))
    assert career.players[pid].team == buyer and pid not in team.roster and pid not in team.listed
    assert team.cash == cash + 400


def test_the_window_closes_into_a_new_season_with_full_lineups(window):
    career = window
    closes = transfers.closing_day(career)
    assert closes == date(career.season + 1, 1, 16)
    for _ in range(120):
        if career.phase != "offseason":
            break
        for offer in [o for o in career.offers if o.seller == career.team and o.status == "open"]:
            engine.apply(cat, career, RespondOfferAction(type="respond_offer", offer=offer.id, response="reject"))
        for talk in [c for c in career.conversations if not c.resolved]:
            engine.apply(cat, career, TalkAction(type="talk", conversation=talk.id, choice="final"))
        before = career.day
        engine.apply(cat, career, AdvanceAction(type="advance"))
        assert (career.day - before).days == 1, "Continue moves through the window a day at a time"
    assert career.phase == "season" and career.matches
    assert career.day == closes
    assert any(s.played for s in career.players.values()), "last season's games count towards careers"
    mine = rookies.catalog_for(cat, career)  # rookies who signed are in lineups too
    for team in career.teams.values():
        assert set(team.lineup) == set(ROLES), team.id
        for role, pid in team.lineup.items():
            assert career.players[pid].team == team.id and mine.players[pid].role == role
    # Nobody plays for two clubs, and every rostered player has a contract.
    seen = set()
    for team in career.teams.values():
        for pid in team.roster:
            assert pid not in seen and career.players[pid].contract is not None
            seen.add(pid)


def test_contracts_that_end_run_out_on_free_agency_day(window):
    career = window
    expiring = [p for p in career.teams[career.team].roster
                if career.players[p].contract.until <= career.season and p != career.teams[career.team].franchise]
    transfers.open_free_agency(cat, career)
    for pid in expiring:
        assert career.players[pid].team is None


def test_an_old_save_gets_reputation_training_and_a_board(drafted):
    from app.game.state import BoardState, ReadMessageAction

    career = drafted.model_copy(deep=True)
    career.board = BoardState()
    career.manager_reputation = 0
    for team in career.teams.values():
        team.reputation = 0
        team.skills = {}
        team.plays = {}
    engine.apply(cat, career, ReadMessageAction(type="read_message"))
    assert career.board.meeting and career.board.objectives
    assert all(t.reputation and t.skills and t.plays for t in career.teams.values())
    assert career.manager_reputation > 0


# ---------- the shortlist ----------


def _days(career, until):
    while career.day < until:
        career.day += timedelta(days=1)
        shortlist.daily(cat, career)


def test_a_shortlisted_player_gets_reports_that_hold_their_real_potential(drafted):
    career = drafted.model_copy(deep=True)
    far = next(t for t in career.teams.values() if cat.teams[t.id].region != career.region)
    pid = far.lineup["MID"]
    engine.apply(cat, career, ShortlistAction(type="shortlist", player=pid))
    found = shortlist.entry(career, pid)
    assert found and found.due == career.day + timedelta(days=shortlist.scout_days(cat, career, pid))
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, ScoutPlayerAction(type="scout_player", player=pid))  # already watching

    _days(career, found.due)
    first = found.report
    assert first and first["kind"] == "player" and found.due is None
    assert career.inbox[-1].subject == f"Scout report: {cat.players[pid].name}" and career.inbox[-1].report == first
    real = training.ceiling(cat, career, pid)
    low, high = first["potential"]
    assert low - 0.5 <= real <= high + 0.5
    assert first["grade"] in ("A+", "A", "B", "C", "D") and first["fit"]

    engine.apply(cat, career, ScoutPlayerAction(type="scout_player", player=pid))
    _days(career, found.due)
    second = found.report
    assert second["number"] == 2
    assert second["potential"][1] - second["potential"][0] <= high - low, "a second look narrows the range"


def test_the_shortlist_follows_moves_and_drops_your_own_players(drafted):
    career = drafted.model_copy(deep=True)
    mine = career.teams[career.team]
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, ShortlistAction(type="shortlist", player=mine.lineup["TOP"]))
    other = next(t for t in career.teams.values() if t.id != career.team)
    a, b = other.lineup["TOP"], other.lineup["JNG"]
    for pid in (a, b):
        engine.apply(cat, career, ShortlistAction(type="shortlist", player=pid))
    career.players[a].team = None
    career.players[b].team = career.team
    shortlist.daily(cat, career)
    assert career.inbox[-1].subject == f"Shortlist: {cat.players[a].name} is a free agent"
    assert shortlist.entry(career, b) is None and shortlist.entry(career, a)
    engine.apply(cat, career, ShortlistAction(type="shortlist", player=a, on=False))
    assert career.shortlist == []


def test_moving_money_between_the_bank_and_the_salary_budget_is_worth_the_weeks_left(drafted):
    career = drafted.model_copy(deep=True)
    team = career.teams[career.team]
    budget, cash = team.budget, team.cash
    lim = finances.limits(career)
    assert lim.high >= budget + 100
    bonus = career.board.bonuses[0] if career.board.bonuses else None
    paid = board.bonus_payment(career, bonus) if bonus else None
    engine.apply(cat, career, AdjustBudgetAction(type="adjust_budget", budget=budget + 100))
    assert team.budget == budget + 100 and team.budget_moved == -100
    assert team.cash == cash - round(100 * lim.weeks / 52)
    if bonus:
        assert board.bonus_payment(career, bonus) == paid, "bonuses go by the budget the board set"
    engine.apply(cat, career, AdjustBudgetAction(type="adjust_budget", budget=budget))
    assert (team.budget, team.cash, team.budget_moved) == (budget, cash, 0), "moving it back gives the same"


def test_the_budget_stays_between_the_contracts_and_what_the_bank_can_pay(drafted):
    career = drafted.model_copy(deep=True)
    lim = finances.limits(career)
    assert lim.low <= career.teams[career.team].budget <= lim.high
    for budget in (lim.low - 10, lim.high + 10):
        with pytest.raises(IllegalAction):
            engine.apply(cat, career, AdjustBudgetAction(type="adjust_budget", budget=budget))
    engine.apply(cat, career, AdjustBudgetAction(type="adjust_budget", budget=lim.high))
    assert career.teams[career.team].cash >= 0


def test_the_budget_is_moved_after_the_draft_and_a_new_one_runs_a_full_year(window):
    career = create_manager(engine.new_career(cat, "Tester", "T1", 3))
    engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, AdjustBudgetAction(type="adjust_budget", budget=career.teams["T1"].budget - 10))
    assert finances.limits(window).weeks == 52
    assert all(t.budget_moved == 0 for t in window.teams.values())


def test_agreed_fees_are_set_aside_and_have_to_be_in_the_bank(window):
    from app.game import contracts

    career = window
    team = career.teams[career.team]
    team.budget += 3000
    pid = _target(career)
    ask = transfers.asking_fee(cat, career, pid)
    team.cash = ask + 50
    engine.apply(cat, career, TransferBidAction(type="transfer_bid", player=pid, fee=ask))
    assert transfers.reserved(career) == ask and transfers.free_cash(career) == 50
    assert "50k free in the bank" in transfers.check_bid(cat, career, _target(career), 100)
    lim = finances.limits(career)
    assert lim.high == team.budget + 50 * 52 // lim.weeks, "the slider only spends what is free"
    team.cash = ask - 1
    assert "cannot pay" in contracts.check_can_talk(rookies.catalog_for(cat, career), career, pid)


def test_debt_costs_confidence_and_deep_debt_cuts_wages(window):
    career = window
    team = career.teams[career.team]
    confidence = career.board.confidence
    target = _target(career)
    team.cash = -10
    finances.weekly(cat, career, Rng(career))
    assert career.board.in_debt and career.board.confidence == confidence - 1
    assert career.inbox[-1].subject == "The club is in debt"
    assert transfers.check_bid(cat, career, target, 10).startswith("The club is 10k in debt")
    salaries = {pid: career.players[pid].contract.salary for pid in team.roster if career.players[pid].contract}
    morale = {pid: career.players[pid].morale for pid in team.roster}
    team.cash = -finances.deep_debt(career) - 10
    finances.weekly(cat, career, Rng(career))
    assert career.board.confidence == confidence - 3, "deep debt costs two a week"
    assert career.inbox[-1].subject == "The board cuts wages"
    for pid, salary in salaries.items():
        assert career.players[pid].contract.salary <= salary * 0.9 + 5
        assert career.players[pid].morale == max(0, morale[pid] - finances.CUT_MORALE)
    cut = dict((pid, career.players[pid].contract.salary) for pid in salaries)
    finances.weekly(cat, career, Rng(career))
    assert all(career.players[pid].contract.salary == cut[pid] for pid in cut), "no second cut within eight weeks"
    team.cash = 5
    finances.weekly(cat, career, Rng(career))
    assert not career.board.in_debt and career.inbox[-1].subject == "The club is out of debt"


def test_winning_settles_an_unsettled_player_and_losing_does_not(drafted):
    career = drafted.model_copy(deep=True)
    team = career.teams[career.team]
    happy, sad = list(team.lineup.values())[:2]
    for pid in (happy, sad):
        career.players[pid].unsettled = True
    rng = Rng(career)
    for _ in range(40):
        career.players[happy].morale = 90  # a team that keeps winning
        career.players[sad].morale = 45
        for pid in (happy, sad):
            training._player_week(cat, career, pid, career.players[pid], rng)
    assert not career.players[happy].unsettled
    assert any(m.subject == f"{cat.players[happy].name} has settled" for m in career.inbox)
    assert career.players[sad].unsettled, "an unhappy player stays unsettled"


def _agree(career):
    """The manager agrees a fee for a starter elsewhere; returns the player, the seller and the offer."""
    team = career.teams[career.team]
    team.cash = 20000
    team.budget += 3000
    pid = _target(career)
    seller = career.players[pid].team
    engine.apply(cat, career, TransferBidAction(type="transfer_bid", player=pid, fee=transfers.asking_fee(cat, career, pid)))
    offer = career.offers[-1]
    assert offer.status == "agreed"
    return pid, seller, offer


def test_a_player_with_an_agreed_fee_is_off_the_market_and_a_sale_elsewhere_ends_the_deal(window):
    from app.game import contracts

    career = window
    pid, seller, offer = _agree(career)
    assert transfers.spoken_for(career, pid), "AI clubs leave him alone while personal terms are open"
    buyer = next(t for t in career.teams if t not in (career.team, seller))
    transfers._move(cat, career, pid, seller, buyer, 500)
    assert offer.status == "collapsed" and transfers.reserved(career) == 0
    assert "under contract with another team" in contracts.check_can_talk(rookies.catalog_for(cat, career), career, pid)
    assert pid in career.teams[buyer].roster and pid not in career.teams[career.team].roster
    assert career.inbox[-1].subject.startswith("Deal off")


def test_an_agreed_fee_lapses_when_the_contract_runs_out_and_the_player_comes_free(window):
    from app.game import contracts

    career = window
    pid, seller, offer = _agree(career)
    career.players[pid].contract.until = career.season
    transfers.open_free_agency(cat, career)
    assert career.players[pid].team is None and offer.status == "collapsed"
    team = career.teams[career.team]
    cash, seller_cash = team.cash, career.teams[seller].cash
    want = contracts.ask(cat, career, pid)
    engine.apply(cat, career, OfferAction(type="offer", player=pid, salary=want.salary, years=want.years))
    assert career.players[pid].team == career.team and pid not in career.teams[seller].roster
    assert team.cash == cash and career.teams[seller].cash == seller_cash, "a free agent costs no fee"


def test_a_release_in_the_off_season_pays_for_the_seasons_still_to_come(window):
    from app.game import contracts

    for until, cost in ((window.season, 0), (window.season + 1, 0.5)):
        career = window.model_copy(deep=True)
        team = career.teams[career.team]
        pid = next(p for p in team.roster if p not in team.lineup.values())
        career.players[pid].contract.until = until  # this season's contracts run out on December 1st
        salary = career.players[pid].contract.salary
        assert contracts.release(cat, career, pid) == int(salary * cost)


def test_rookies_from_solo_queue_have_not_played_together(window):
    career = window
    mine = rookies.catalog_for(cat, career)
    solo = {r.role: r.id for r in career.rookies if not r.team}
    assert "BOT" in solo and "SUP" in solo
    team = career.teams[career.team]
    pair = {"BOT": solo["BOT"], "SUP": solo["SUP"]}
    fresh, reasons = roster.chemistry(mine, career, team, pair)
    assert not any("were a bot lane" in r for r in reasons)
    assert "A new lineup that is still learning each other" in reasons
    team.together[roster._pair_key(solo["BOT"], solo["SUP"])] = 20
    assert roster.chemistry(mine, career, team, pair)[0] > fresh, "twenty games together make them a pair"


def _stale(career):
    """An older save: a fee was agreed, then the player moved to a third club and the deal stayed."""
    pid, seller, offer = _agree(career)
    other = next(t for t in career.teams if t not in (career.team, seller))
    old = career.teams[seller]
    old.roster.remove(pid)
    old.lineup = {r: p for r, p in old.lineup.items() if p != pid}
    career.teams[other].roster.append(pid)
    career.players[pid].team = other
    return pid, other, offer


def test_a_stale_agreed_fee_never_puts_a_player_on_two_rosters(window):
    from app.game import contracts

    career = window.model_copy(deep=True)
    pid, other, offer = _stale(career)
    assert "the deal is off" in contracts.check_can_talk(rookies.catalog_for(cat, career), career, pid)
    want = contracts.ask(cat, career, pid)
    with pytest.raises(IllegalAction):
        contracts._sign(cat, career, pid, want.salary, want.years)  # even past the check
    assert pid in career.teams[other].roster and pid not in career.teams[career.team].roster
    assert career.players[pid].team == other

    career = window.model_copy(deep=True)
    pid, other, offer = _stale(career)
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, OfferAction(type="offer", player=pid, salary=want.salary, years=want.years))
    assert offer.status == "collapsed", "loading the save calls the deal off"
    assert career.inbox[-1].subject.startswith("Deal off")
    assert pid not in career.teams[career.team].roster
