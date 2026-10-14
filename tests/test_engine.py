from collections import Counter
from datetime import date

import pytest

from app.game import champ_select as cs
from app.game import competitions as comps
from app.game import contracts, draft, engine, match_engine, matchday, roster, scouting
from app.game import staff as staffing
from app.game.catalog import ROLES, get_catalog
from app.game.errors import IllegalAction
from app.game.rng import Rng
from app.game.state import (
    AcceptCounterAction, AdvanceAction, BanAction, BoardMeetingAction, ChampSelect, Competition, DraftNextAction,
    DraftPassAction, DraftPickAction, DraftStaffAction, LiveSeries, Match, NextSeasonAction, OfferAction,
    OpponentTurnAction, ReleaseAction, Stage, StartDraftAction,
)

from tests.conftest import create_manager

cat = get_catalog()


def fresh(seed: int = 7, team: str = "G2"):
    """A new career with the board meeting done, so the draft can start."""
    career = create_manager(engine.new_career(cat, "Tester", team, seed))
    engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
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
    career = fresh()
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
    career = fresh()
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


def test_every_team_drafts_an_assistant_coach_and_an_analyst(drafted):
    hired = set()
    for team in drafted.teams.values():
        if team.league not in drafted.drafts:
            continue
        assert cat.staff[team.coach].kind == "coach"
        assert cat.staff[team.analyst].kind == "analyst"
        for sid in (team.coach, team.analyst):
            assert sid not in hired and drafted.staff[sid].team == team.id
            hired.add(sid)
    g2 = drafted.teams["G2"]
    assert roster.payroll(drafted, g2) >= drafted.staff[g2.coach].contract.salary + drafted.staff[g2.analyst].contract.salary


def test_staff_rounds_come_after_the_players_and_take_only_staff():
    career = fresh()
    d = career.drafts["LEC"]
    while d.round_kind == "player":
        if d.on_the_clock == "G2":
            engine.apply(cat, career, DraftNextAction(type="draft_next"))  # does nothing on our turn
            engine.apply(cat, career, engine_auto())
        else:
            engine.apply(cat, career, DraftNextAction(type="draft_next"))
    assert d.round_kind == "coach"
    engine.apply(cat, career, DraftNextAction(type="draft_next", until_mine=True))
    pool = draft.available_staff(cat, career, "LEC")
    analyst = next(s for s in pool if s.kind == "analyst")
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, DraftStaffAction(type="draft_staff", staff=analyst.id))
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, DraftPassAction(type="draft_pass"))
    coach = min((s for s in pool if s.kind == "coach"), key=lambda s: s.salary)
    engine.apply(cat, career, DraftStaffAction(type="draft_staff", staff=coach.id))
    assert career.teams["G2"].coach == coach.id
    with pytest.raises(IllegalAction):
        player = draft.available(cat, career, "LEC")[0]
        engine.apply(cat, career, DraftPickAction(type="draft_pick", player=player.id))


def engine_auto():
    from app.game.state import DraftAutoAction

    return DraftAutoAction(type="draft_auto")


def test_a_better_analyst_writes_a_fuller_scouting_report(drafted):
    def report(skill: int) -> dict:
        career = drafted.model_copy(deep=True)
        career.profile.duties["scouting"] = "staff"  # the analyst writes it, however good the manager is
        sid = career.teams["G2"].analyst
        person = cat.staff[sid]
        # Swap in a copy of the analyst with the scouting we want.
        from dataclasses import replace
        object.__setattr__(cat, "staff", cat.staff | {sid: replace(person, attributes={"scouting": skill, "meta": 10})})
        try:
            match = Match(id="x", competition=next(iter(career.competitions)), stage="x", label="x", day=career.day,
                          home="G2", away="FNC", best_of=3)
            career.matches["x"] = match
            return scouting.scouting_report(cat, career, match).report
        finally:
            object.__setattr__(cat, "staff", cat.staff | {sid: person})

    weak, strong = report(3), report(18)
    assert weak["level"] == 1 and strong["level"] == 4
    assert "bans" not in weak and "plan" not in weak
    assert len(strong["bans"]) == 5 and strong["threat"] and strong["weaknesses"]
    assert {p["role"] for p in strong["players"]} == set(ROLES)


def test_a_match_day_brings_a_scouting_report(drafted):
    career = drafted.model_copy(deep=True)
    for _ in range(60):
        engine.apply(cat, career, AdvanceAction(type="advance"))
        if career.live:
            break
    assert career.live
    last = career.inbox[-1]
    assert last.kind == "scouting" and last.report["match"] == career.live.match


def test_the_coach_sets_how_hard_a_defeat_hits_and_how_fast_players_grow():
    assert staffing.defeat_morale(20) > staffing.defeat_morale(10) > staffing.defeat_morale(staffing.NOBODY)
    assert staffing.development_factor(20) > 1 > staffing.development_factor(staffing.NOBODY)
    weights, hidden = staffing.coach_lens(staffing.NOBODY, "nobody")
    assert "lane" in hidden and "combo" in hidden
    weights, hidden = staffing.coach_lens(20, "anyone")
    assert not hidden and all(abs(w - 1) < 1e-9 for w in weights.values())


def test_a_career_saved_before_staff_existed_hires_them_on_the_next_action(drafted):
    from app.game.state import ReadMessageAction

    career = drafted.model_copy(deep=True)
    for team in career.teams.values():
        team.coach = team.analyst = None
    career.staff = {}
    engine.apply(cat, career, ReadMessageAction(type="read_message"))
    assert all(t.coach and t.analyst for t in career.teams.values())
    assert career.inbox[-1].kind == "staff"
    assert all(roster.payroll(career, t) <= t.budget + 1 for t in career.teams.values()
               if roster.payroll(drafted, drafted.teams[t.id]) <= drafted.teams[t.id].budget)


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


def test_knockout_losers_of_one_round_are_ranked_by_seed(drafted):
    teams = [t.id for t in cat.league_teams("LPL")][:8]
    comp = _comp(teams)
    stage = Stage(id="T-PO", name="PO", kind="single_elim", teams=teams, best_of=5)
    career = drafted.model_copy(deep=True)
    comps.build_single_elim(career, comp, stage, [[date(2027, 2, 1)], [date(2027, 2, 8)], [date(2027, 2, 15)]])
    for mid in stage.matches:  # the better seed wins every match
        match = career.matches[mid]
        comps._resolve(career, stage, match)
        match.winner = min((match.home, match.away), key=teams.index)
    ranking = comps.elim_ranking(career, stage)
    assert ranking[:2] == teams[:2]
    assert ranking[2:4] == teams[2:4], "semifinal losers by seed"
    assert ranking[4:] == teams[4:], "quarterfinal losers by seed, whichever match they were in"


# ---------- champion select and games ----------


@pytest.mark.parametrize("shape,size,lower_starts", [("eight", 8, 0), ("six_upper_four", 6, 2), ("six_byes", 6, 0)])
def test_a_double_elimination_bracket_gives_everyone_two_lives(drafted, shape, size, lower_starts):
    career = drafted.model_copy(deep=True)
    teams = [t.id for t in cat.league_teams("LPL")][:size]
    comp = Competition(id="T", name="T", short="T", kind="league", start=date(2027, 2, 20), end=date(2027, 3, 1))
    career.competitions["T"] = comp
    stage = Stage(id="T-PO", name="PO", kind="double_elim", teams=teams, best_of=5)
    comp.stages.append(stage)
    comps.build_double_elim(career, comp, stage, shape, date(2027, 2, 20), date(2027, 3, 1))
    matches = [career.matches[m] for m in stage.matches]
    assert all(a.day <= b.day for a, b in zip(matches, matches[1:]))
    losses = {t: 0 for t in teams}
    rng = Rng(career)
    for m in matches:
        assert m.home and m.away, f"{m.label} is waiting on a result that has not happened"
        m.winner = m.home if rng.chance(0.5) else m.away
        losses[m.loser] += 1
        comps.on_match_finished(career, m)
    ranking = comps.rank_stage(career, stage)
    assert sorted(ranking) == sorted(teams) and matches[-1].label == "Grand final"
    assert ranking[0] == matches[-1].winner and ranking[1] == matches[-1].loser
    # Everyone but the finalists is out after two defeats, or one if they started in the lower bracket.
    lower = set(teams[size - lower_starts:])
    for team in teams:
        if team == ranking[0]:
            assert losses[team] <= 1
        elif team == ranking[1]:
            assert losses[team] <= 2
        else:
            assert losses[team] == (1 if team in lower else 2), team


def test_playoffs_and_msi_are_double_elimination(finished):
    for comp in finished.competitions.values():
        if comp.kind == "league" or comp.short == "Mid-Season Invitational":
            assert comp.stages[-1].kind == "double_elim", comp.name
    worlds = finished.competitions[f"{finished.season}-WORLDS"]
    assert worlds.stages[-1].kind == "single_elim"


def test_the_swiss_stage_is_drawn_round_by_round_from_pools(finished):
    worlds = finished.competitions[f"{finished.season}-WORLDS"]
    stage = next(s for s in worlds.stages if s.kind == "swiss")
    pools = Counter(comps.swiss_pools(finished, stage).values())
    # 16 teams: every pool splits in two until three wins or three defeats.
    assert pools == {(0, 0): 8, (1, 0): 4, (0, 1): 4, (2, 0): 2, (1, 1): 4, (0, 2): 2,
                     (2, 1): 3, (1, 2): 3, (2, 2): 3}
    draws = [m for m in finished.inbox if m.kind == "draw" and m.competition == worlds.id]
    assert [m.round for m in draws] == [1, 2, 3, 4, 5]
    assert draws[1].body.count(" vs ") == 8
    assert draws[0].body.count("Pot 1 v Pot 4") == 4 and draws[0].body.count("Pot 2 v Pot 3") == 4
    met = [frozenset((finished.matches[m].home, finished.matches[m].away)) for m in stage.matches]
    assert len(set(met)) == len(met)  # nobody plays the same team twice


def test_the_first_swiss_round_draws_pot_1_against_pot_4_and_keeps_regions_apart(finished):
    worlds = finished.competitions[f"{finished.season}-WORLDS"]
    pots = next(s for s in worlds.stages if s.kind == "swiss").pots
    assert [len(p) for p in pots] == [4, 4, 4, 4]
    region_of = {t: cat.teams[t].region for pot in pots for t in pot}
    pot_of = {t: i for i, pot in enumerate(pots) for t in pot}
    for seed in range(40):
        career = finished.model_copy(deep=True)
        stage = Stage(id="X-SW", name="Swiss stage", kind="swiss", teams=[t for p in pots for t in p], pots=pots,
                      best_of=1, days=[date(career.season, 10, d) for d in (1, 3, 5, 8, 10)])
        career.rs = seed
        comps.build_swiss_round(career, worlds, stage, Rng(career), region_of)
        pairs = [(career.matches[m].home, career.matches[m].away) for m in stage.matches]
        assert len(pairs) == 8
        assert sorted((pot_of[a], pot_of[b]) for a, b in pairs) == [(0, 3)] * 4 + [(1, 2)] * 4
        assert all(region_of[a] != region_of[b] for a, b in pairs)


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
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, BanAction(type="ban", champion="NotAChampion"))
    assert select.step == 1 and not select.red_bans, "a made-up champion does not use up the ban"
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
    career.teams["G2"].budget += 2000
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
    career = fresh()
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


def test_a_season_plays_through_to_worlds(finished):
    career = finished
    assert career.phase == "offseason"
    assert all(c.status == "finished" and c.placements for c in career.competitions.values())
    short = {c.short for c in career.competitions.values() if c.kind == "international"}
    assert short == {"First Stand", "Mid-Season Invitational", "World Championship"}
    assert len(career.meta.history) >= 20  # a patch every two weeks
    worlds = career.competitions[f"{career.season}-WORLDS"]
    assert len(worlds.entrants) == 19


def test_match_engine_records_add_up(drafted):
    career = drafted.model_copy(deep=True)
    rng = Rng(career)
    match = Match(id="x", competition="x", stage="x", label="x", day=career.day, home="T1", away="HLE")
    record = matchday.play_ai_game(cat, career, match, rng).record
    blue_kills = sum(ln.kills for ln in record.players if ln.team == record.blue)
    assert blue_kills == record.kills[0]
    assert record.winner in (record.blue, record.red)
    assert match_engine.logistic(0) == 0.5


def test_the_next_season_has_no_draft_and_every_team_fields_five(finished):
    career = finished.model_copy(deep=True)
    assert career.board.meeting, "the board meets the manager about next season"
    engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
    drafts = {lg: len(d.picks) for lg, d in career.drafts.items()}
    engine.apply(cat, career, NextSeasonAction(type="next_season"))
    assert career.season == finished.season + 1
    assert career.phase == "season" and career.matches
    assert career.history and career.history[-1].season == finished.season
    assert {lg: len(d.picks) for lg, d in career.drafts.items()} == drafts
    for team in career.teams.values():
        assert set(team.lineup) == set(ROLES), team.id
        assert team.coach and team.analyst, team.id
        assert all(career.players[p].team == team.id for p in team.roster)


def test_the_next_season_cannot_start_early(drafted):
    career = drafted.model_copy(deep=True)
    with pytest.raises(IllegalAction):
        engine.apply(cat, career, NextSeasonAction(type="next_season"))


def test_two_teams_calling_the_same_play_clash_once(drafted):
    career = drafted.model_copy(deep=True)
    career.teams["G2"].plays["dive"] = 100.0
    career.teams["FNC"].plays["dive"] = 40.0
    select = ChampSelect()
    sides = matchday.draft_sides(cat, career, "G2", "FNC")
    cs.run_ai(cat, career, select, sides, Rng(career), human=None)
    blue_wins = even = 0
    for seed in range(60):
        career.rs = seed
        blue = match_engine.prepare(cat, career, "blue", "G2", sides["blue"].lineup, dict(select.blue_picks),
                                    sides["blue"].tactics, play="dive")
        red = match_engine.prepare(cat, career, "red", "FNC", sides["red"].lineup, dict(select.red_picks),
                                   sides["red"].tactics, play="dive")
        result = match_engine.simulate(cat, career, blue, red, Rng(career), 1, ([], []))
        plays = [e for e in result.events if e.kind == "play"]
        assert len(plays) == 1 and plays[0].text.startswith("Set play clash, Tower dive")
        outcome = result.record.play_results
        if outcome["G2"] == outcome["FNC"]:
            even += 1
            assert not outcome["G2"], "a clash that cancels out works for nobody"
        else:
            blue_wins += outcome["G2"]
    assert blue_wins > (60 - even) * 0.7, "the better prepared team wins most clashes"


def test_every_split_draws_its_own_schedule(drafted):
    def opening_week(comp):
        stage = comp.stages[0]
        return frozenset(frozenset((drafted.matches[m].home, drafted.matches[m].away))
                         for m in stage.matches if drafted.matches[m].day == stage.days[0])

    splits = [drafted.competitions[f"{drafted.season}-LEC-{s}"] for s in (1, 2, 3)]
    assert len({opening_week(c) for c in splits}) > 1, "the same opening week every split"
    for comp in splits:
        stage = comp.stages[0]
        meetings = Counter(frozenset((drafted.matches[m].home, drafted.matches[m].away)) for m in stage.matches)
        n = len(stage.teams)
        assert len(meetings) == n * (n - 1) // 2 and set(meetings.values()) == {stage.rounds}


def test_an_old_save_redraws_only_the_schedules_not_started(drafted):
    career = drafted.model_copy(deep=True)
    first = career.competitions[f"{career.season}-LEC-1"]
    second = career.competitions[f"{career.season}-LEC-2"]
    first.status = "running"
    played = dict((m, career.matches[m].model_copy()) for m in first.stages[0].matches)
    days, count = list(second.stages[0].days), len(second.stages[0].matches)
    career.schedules_drawn = False
    engine.migrate(cat, career)
    assert career.schedules_drawn
    assert all(career.matches[m] == played[m] for m in played), "a split under way keeps its schedule"
    assert second.stages[0].days == days and len(second.stages[0].matches) == count


def test_fights_come_with_a_casters_call(drafted):
    career = drafted.model_copy(deep=True)
    select = ChampSelect()
    sides = matchday.draft_sides(cat, career, "G2", "FNC")
    cs.run_ai(cat, career, select, sides, Rng(career), human=None)
    calls = []
    for seed in range(8):
        career.rs = seed
        blue = match_engine.prepare(cat, career, "blue", "G2", sides["blue"].lineup, dict(select.blue_picks),
                                    sides["blue"].tactics)
        red = match_engine.prepare(cat, career, "red", "FNC", sides["red"].lineup, dict(select.red_picks),
                                   sides["red"].tactics)
        events = match_engine.simulate(cat, career, blue, red, Rng(career), 1, ([], [])).events
        for i, e in enumerate(events):
            if e.kind == "highlight":
                calls.append(e.text)
                assert events[i + 1].kind == "teamfight", "the call comes just before the fight's result"
    assert len(calls) >= 8
    names = {cat.players[p].name.upper() for p in list(sides["blue"].lineup.values()) + list(sides["red"].lineup.values())}
    assert all(any(n in c for n in names) for c in calls), "every call names a player"
    assert all("!!" not in c and " / " not in c for c in calls)


def test_drakes_follow_the_rift_and_the_soul_is_the_rift_element(drafted):
    career = drafted.model_copy(deep=True)
    select = ChampSelect()
    sides = matchday.draft_sides(cat, career, "G2", "FNC")
    cs.run_ai(cat, career, select, sides, Rng(career), human=None)
    souls = Counter()
    for seed in range(40):
        career.rs = seed
        blue = match_engine.prepare(cat, career, "blue", "G2", sides["blue"].lineup, dict(select.blue_picks),
                                    sides["blue"].tactics)
        red = match_engine.prepare(cat, career, "red", "FNC", sides["red"].lineup, dict(select.red_picks),
                                   sides["red"].tactics)
        events = match_engine.simulate(cat, career, blue, red, Rng(career), 1, ([], [])).events
        drakes = [e.text.split(" the ")[1].split()[0] for e in events if e.kind in ("dragon", "soul")]
        assert len(set(drakes[:3])) == len(drakes[:3]), "the first three drakes are three different elements"
        assert all(d == drakes[2] for d in drakes[2:]), "the Rift keeps the third drake's element"
        soul = [e for e in events if e.kind == "soul"]
        if soul:
            assert soul[0].text.endswith(f"the {drakes[2]} Soul")
            souls[drakes[2]] += 1
    assert sum(souls.values()) >= 10 and len(souls) >= 3
