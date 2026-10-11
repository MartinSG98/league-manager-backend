from datetime import date

import pytest

from app.game import champ_select as cs
from app.game import competitions as comps
from app.game import contracts, draft, engine, match_engine, matchday, roster
from app.game.catalog import ROLES, get_catalog
from app.game.errors import IllegalAction
from app.game.rng import Rng
from app.game.state import (
    AcceptCounterAction, AdvanceAction, BanAction, ChampSelect, Competition, DraftNextAction, DraftPickAction,
    DraftSimAction, LiveSeries, Match, NextSeasonAction, OfferAction, OpponentTurnAction, ReleaseAction,
    SimSeriesAction, Stage, StartDraftAction,
)

cat = get_catalog()


@pytest.fixture(scope="module")
def drafted():
    career = engine.new_career(cat, "Tester", "G2", 42)
    engine.apply(cat, career, DraftSimAction(type="draft_sim"))
    return career


# ---------- data ----------


def test_every_tier_one_team_has_a_full_2026_lineup_and_a_franchise_player():
    for team in cat.teams.values():
        if team.tier != 1:
            continue
        assert set(team.starters) == set(ROLES), team.name
        assert team.franchise in team.roster, team.name


def test_ratings_stay_on_their_scales():
    for p in cat.players.values():
        assert 30 <= p.overall <= 99
        assert p.overall <= p.potential <= 99
        assert all(1 <= v <= 20 for v in p.attributes.values())
        assert p.salary >= 15


def test_stronger_leagues_rate_higher_on_average():
    def avg(league: str) -> float:
        ps = [p.overall for p in cat.players.values() if p.league == league]
        return sum(ps) / len(ps)

    assert avg("LCK") > avg("LEC") > avg("LFL")


def test_franchise_overrides_are_respected():
    assert cat.players[cat.teams["G2"].franchise].name == "Caps"
    assert cat.players[cat.teams["T1"].franchise].name == "Faker"


# ---------- draft ----------


def test_new_career_strips_rosters_and_the_ai_picks_one_at_a_time():
    career = engine.new_career(cat, "Tester", "G2", 7)
    d = career.drafts["LEC"]
    assert career.phase == "draft"
    assert d.number == 0
    g2 = career.teams["G2"]
    assert g2.roster == [cat.teams["G2"].franchise]
    # every other region drafted at once
    assert all(career.drafts[lg].done for lg in career.drafts if lg != "LEC")

    assert d.on_the_clock != "G2", "G2 finished high in 2026, so it does not pick first"
    engine.apply(cat, career, DraftNextAction(type="draft_next"))
    assert d.number == 1
    engine.apply(cat, career, DraftNextAction(type="draft_next", until_mine=True))
    assert d.on_the_clock == "G2"
    # Waiting on the manager's own pick never picks for them.
    before = d.number
    engine.apply(cat, career, DraftNextAction(type="draft_next"))
    assert d.number == before and d.on_the_clock == "G2"


def test_a_pick_must_fill_an_open_role_and_fit_the_budget():
    career = engine.new_career(cat, "Tester", "G2", 7)
    engine.apply(cat, career, DraftNextAction(type="draft_next", until_mine=True))
    caps_role = cat.players[cat.teams["G2"].franchise].role
    pool = draft.available(cat, career, "LEC")
    same_role = next(p for p in pool if p.role == caps_role)
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, DraftPickAction(type="draft_pick", player=same_role.id))
    career.teams["G2"].budget = draft.roster.payroll(career, career.teams["G2"]) + 10
    pricey = next(p for p in pool if p.role != caps_role and p.salary > 50)
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, DraftPickAction(type="draft_pick", player=pricey.id))


def test_after_the_draft_every_team_fields_five_and_nobody_plays_twice(drafted):
    seen: set[str] = set()
    for team in drafted.teams.values():
        assert set(team.lineup) == set(ROLES)
        for pid in team.roster:
            assert pid not in seen
            seen.add(pid)
            assert drafted.players[pid].team == team.id
    assert drafted.phase == "season"


def test_drafted_teams_stay_within_budget(drafted):
    over = [t.id for t in drafted.teams.values() if roster.payroll(drafted, t) > t.budget]
    assert not over


# ---------- competitions ----------


def _comp(teams: list[str]) -> Competition:
    return Competition(id="T", name="Test", short="Test", kind="league", start=date(2027, 1, 1), end=date(2027, 3, 1))


def test_double_round_robin_meets_everyone_twice(drafted):
    teams = [t.id for t in cat.league_teams("LEC")]
    comp = _comp(teams)
    stage = Stage(id="T-RS", name="RS", kind="round_robin", teams=teams, best_of=1, rounds=2)
    career = drafted.model_copy(deep=True)
    comps.build_round_robin(career, comp, stage, date(2027, 1, 1), date(2027, 3, 1))
    pairs: dict[frozenset, int] = {}
    for mid in stage.matches:
        m = career.matches[mid]
        pairs[frozenset((m.home, m.away))] = pairs.get(frozenset((m.home, m.away)), 0) + 1
    assert len(pairs) == len(teams) * (len(teams) - 1) // 2
    assert set(pairs.values()) == {2}


def test_six_team_bracket_gives_the_top_two_a_bye(drafted):
    teams = [t.id for t in cat.league_teams("LEC")][:6]
    comp = _comp(teams)
    stage = Stage(id="T-PO", name="PO", kind="single_elim", teams=teams, best_of=5)
    career = drafted.model_copy(deep=True)
    comps.build_single_elim(career, comp, stage, [[date(2027, 2, 1)], [date(2027, 2, 8)], [date(2027, 2, 15)]])
    first_round = [career.matches[m] for m in stage.matches
                   if career.matches[m].home_from.startswith("S:") and career.matches[m].away_from.startswith("S:")]
    playing = {t for m in first_round for t in (m.home, m.away)}
    assert len(stage.matches) == 5
    assert teams[0] not in playing and teams[1] not in playing


# ---------- champion select and games ----------


def test_ai_champion_select_fills_both_sides_without_repeats(drafted):
    rng = Rng(drafted.model_copy())
    select = ChampSelect(locked=["Orianna", "Azir"])
    sides = matchday.draft_sides(cat, drafted, "G2", "FNC")
    cs.run_ai(cat, drafted, select, sides, rng, human=None)
    picks = list(select.blue_picks.values()) + list(select.red_picks.values())
    assert set(select.blue_picks) == set(ROLES) == set(select.red_picks)
    assert len(set(picks + select.blue_bans + select.red_bans)) == 20
    assert "Orianna" not in picks and "Azir" not in picks


def test_a_game_is_deterministic_for_a_seed(drafted):
    def play(seed: int) -> tuple:
        career = drafted.model_copy(deep=True)
        career.rs = seed
        rng = Rng(career)
        match = Match(id="x", competition="x", stage="x", label="x", day=career.day, home="G2", away="FNC")
        result = matchday.play_ai_game(cat, career, match, rng)
        return result.record.winner, result.record.duration, tuple(result.record.kills)

    assert play(5) == play(5)


def test_the_opponent_moves_one_turn_at_a_time_and_never_for_the_manager(drafted):
    career = drafted.model_copy(deep=True)
    match = Match(id="x", competition="x", stage="x", label="x", day=career.day, home="FNC", away="G2")
    career.matches["x"] = match
    career.live = LiveSeries(match="x", our_side="red")
    engine.apply(cat, career, StartDraftAction(type="start_champ_select"))
    select = career.live.select
    assert select.step == 0, "blue (FNC) bans first, but only when asked"
    engine.apply(cat, career, OpponentTurnAction(type="opponent_turn"))
    assert select.step == 1 and len(select.blue_bans) == 1
    engine.apply(cat, career, OpponentTurnAction(type="opponent_turn"))
    assert select.step == 1, "red's turn: nothing happens"
    engine.apply(cat, career, BanAction(type="ban", champion=matchday_suggestion(career)))
    engine.apply(cat, career, OpponentTurnAction(type="opponent_turn", until_mine=True))
    assert cs.turn(select) == ("red", "ban")


def matchday_suggestion(career) -> str:
    live = career.live
    blue, red = matchday.sides(career.matches[live.match])
    teams = matchday.draft_sides(cat, career, blue, red)
    return cs.ban_options(cat, career, live.select, live.our_side, teams[live.our_side], teams["blue"])[0]["champion"]


def test_the_grid_explains_the_same_scores_the_ai_uses(drafted):
    career = drafted.model_copy(deep=True)
    select = ChampSelect()
    sides = matchday.draft_sides(cat, career, "G2", "FNC")
    rng = Rng(career)
    while cs.turn(select) != ("blue", "pick") or select.step < 10:
        cs.ai_step(cat, career, select, sides, rng)
    board = cs.board(cat, career, select, "blue", sides["blue"], sides["red"])
    assert board["kind"] == "pick"
    for row in cs.options(cat, career, select, "blue", sides["blue"], sides["red"], limit=40):
        entry = board["champions"][row["champion"]]
        scored = entry if entry["role"] == row["role"] else entry["others"][row["role"]]
        assert scored["score"] == pytest.approx(row["score"], abs=0.01)
        assert sum(n["value"] for n in scored["notes"]) == pytest.approx(row["score"], abs=0.05)
    best = cs.options(cat, career, select, "blue", sides["blue"], sides["red"], limit=1)[0]
    assert board["champions"][best["champion"]]["verdict"] >= 1
    taken = cs.unavailable(select)
    assert not taken & set(board["champions"])


def test_composition_penalises_one_damage_type():
    all_ad = {"TOP": "Jax", "JNG": "LeeSin", "MID": "Zed", "BOT": "Jinx", "SUP": "Pyke"}
    value, notes = cs.composition_modifier(cat, all_ad)
    assert value < 0 and notes


def test_fearless_locks_every_champion_already_played(drafted):
    career = drafted.model_copy(deep=True)
    rng = Rng(career)
    match = Match(id="x", competition="x", stage="x", label="x", day=career.day, home="G2", away="FNC",
                  best_of=3, fearless=True)
    matchday.play_ai_game(cat, career, match, rng)
    second = matchday.play_ai_game(cat, career, match, rng).record
    first = match.games[0]
    used = set(first.blue_picks.values()) | set(first.red_picks.values())
    assert not used & (set(second.blue_picks.values()) | set(second.red_picks.values()))


def test_stronger_side_wins_more_often(drafted):
    career = drafted.model_copy(deep=True)
    rng = Rng(career)
    strong, weak = "GEN", "DSG"
    wins = 0
    for i in range(60):
        match = Match(id=f"x{i}", competition="x", stage="x", label="x", day=career.day, home=strong, away=weak)
        wins += matchday.play_ai_game(cat, career, match, rng).record.winner == strong
    assert wins > 40


# ---------- contracts ----------


def _free_agent(career, role: str | None = None):
    pool = sorted(draft.available(cat, career, career.league), key=lambda p: -p.overall)
    return next(p for p in pool if role is None or p.role == role)


def test_a_lowball_offer_gets_a_counter_that_can_be_accepted(drafted):
    career = drafted.model_copy(deep=True)
    career.teams["G2"].budget += 2000
    player = _free_agent(career)
    want = contracts.ask(cat, career, player.id)
    engine.apply(cat, career, OfferAction(type="offer", player=player.id, salary=int(want.salary * 0.8), years=want.years))
    counter = career.negotiations[player.id].counter
    assert counter is not None and career.players[player.id].team is None
    engine.apply(cat, career, AcceptCounterAction(type="accept_counter", player=player.id))
    assert career.players[player.id].team == "G2"
    assert career.players[player.id].contract.salary == counter


def test_an_insulting_offer_ends_the_talks(drafted):
    career = drafted.model_copy(deep=True)
    player = _free_agent(career)
    want = contracts.ask(cat, career, player.id)
    engine.apply(cat, career, OfferAction(type="offer", player=player.id, salary=int(want.salary * 0.3), years=want.years))
    assert career.negotiations[player.id].blocked_until is not None
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, OfferAction(type="offer", player=player.id, salary=want.salary, years=want.years))


def test_a_fair_offer_is_accepted_and_counts_against_the_budget(drafted):
    career = drafted.model_copy(deep=True)
    team = career.teams["G2"]
    team.budget = roster.payroll(career, team) + 5000
    player = _free_agent(career)
    want = contracts.ask(cat, career, player.id)
    before = roster.payroll(career, team)
    engine.apply(cat, career, OfferAction(type="offer", player=player.id, salary=want.salary, years=want.years))
    assert career.players[player.id].team == "G2"
    assert roster.payroll(career, team) == before + want.salary


def test_free_agents_wait_until_the_draft_is_over():
    career = engine.new_career(cat, "Tester", "G2", 7)
    player = _free_agent(career)
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, OfferAction(type="offer", player=player.id, salary=500, years=2))


def test_releasing_your_only_player_in_a_role_is_refused(drafted):
    career = drafted.model_copy(deep=True)
    team = career.teams["G2"]
    role, pid = next((r, p) for r, p in team.lineup.items() if p != team.franchise
                     and sum(1 for x in team.roster if cat.players[x].role == r) == 1)
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, ReleaseAction(type="release", player=pid))
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, ReleaseAction(type="release", player=team.franchise))


# ---------- a whole season ----------


@pytest.fixture(scope="module")
def finished(drafted):
    career = drafted.model_copy(deep=True)
    for _ in range(500):
        if career.phase != "season":
            break
        if career.live:
            engine.apply(cat, career, SimSeriesAction(type="sim_series"))
        else:
            engine.apply(cat, career, AdvanceAction(type="advance"))
    return career


def test_a_season_plays_through_to_worlds(finished):
    career = finished
    assert career.phase == "offseason"
    assert all(c.status == "finished" and c.placements for c in career.competitions.values())
    short = {c.short for c in career.competitions.values() if c.kind == "international"}
    assert short == {"First Stand", "Mid-Season Invitational", "World Championship"}
    assert len(career.meta.history) >= 20  # a patch every two weeks
    worlds = career.competitions[f"{career.season}-WORLDS"]
    assert len(worlds.entrants) == 16


def test_match_engine_records_add_up(drafted):
    career = drafted.model_copy(deep=True)
    rng = Rng(career)
    match = Match(id="x", competition="x", stage="x", label="x", day=career.day, home="T1", away="HLE")
    record = matchday.play_ai_game(cat, career, match, rng).record
    blue_kills = sum(ln.kills for ln in record.players if ln.team == record.blue)
    assert blue_kills == record.kills[0]
    assert record.winner in (record.blue, record.red)
    assert match_engine.logistic(0) == 0.5


def test_the_next_season_drafts_only_the_open_roles(finished):
    career = finished.model_copy(deep=True)
    engine.apply(cat, career, NextSeasonAction(type="next_season"))
    assert career.season == finished.season + 1
    assert career.phase == "draft" and not career.matches
    assert career.history and career.history[-1].season == finished.season
    d = career.drafts[career.league]
    assert d.required_rounds <= 4
    engine.apply(cat, career, DraftSimAction(type="draft_sim"))
    assert career.phase == "season"
    for team in career.teams.values():
        assert set(team.lineup) == set(ROLES)


def test_the_next_season_cannot_start_early(drafted):
    career = drafted.model_copy(deep=True)
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, NextSeasonAction(type="next_season"))
