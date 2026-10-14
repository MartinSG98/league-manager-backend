"""The global power rankings, and the international events they and the results seed (Riot's 2026 rules)."""

from collections import Counter

from app.game import calendar, power, reputation
from app.game.catalog import get_catalog
from app.game.state import Match

cat = get_catalog()


def _series(career, home, away, competition, stage, best_of=3, winner=None):
    match = Match(id=f"t-{home}-{away}", competition=competition, stage=stage, label="x", day=career.day,
                  home=home, away=away, best_of=best_of)
    match.winner = winner or home
    return match


def test_the_rankings_start_from_the_league_strengths(drafted):
    career = drafted
    assert power.region_order(career)[0] == "KR"
    for region in cat.regions.values():
        assert power.strength(career, region.id, 0) == cat.leagues[region.league].strength
    assert all(t.elo for t in career.teams.values())


def test_a_domestic_series_moves_teams_but_never_their_region(drafted):
    career = drafted.model_copy(deep=True)
    league = career.competitions[f"{career.season}-LEC-1"]
    home, away = "G2", "FNC"
    before = (career.teams[home].elo, career.teams[away].elo, dict(career.region_elo))
    power.after_series(cat, career, _series(career, home, away, league.id, f"{league.id}-RS", winner=away))
    gain = career.teams[away].elo - before[1]
    assert gain > 0 and career.teams[home].elo == round(before[0] - gain, 1)
    assert career.region_elo == before[2]


def test_beating_a_stronger_region_lifts_the_whole_region(drafted):
    career = drafted.model_copy(deep=True)
    fst = f"{career.season}-FST"
    from app.game.state import Competition

    career.competitions[fst] = Competition(id=fst, name="FST", short="First Stand", kind="international",
                                           start=career.day, end=career.day)
    lec, lck = career.region_elo["EMEA"], career.region_elo["KR"]
    big = power.k_factor(career, _series(career, "G2", "T1", fst, f"{fst}-KO", best_of=5))
    small = power.k_factor(career, _series(career, "G2", "T1", fst, f"{fst}-GR", best_of=1))
    assert big > small, "a knockout Bo5 counts for more than a group Bo1"
    power.after_series(cat, career, _series(career, "G2", "T1", fst, f"{fst}-KO", best_of=5))
    assert career.region_elo["EMEA"] > lec and career.region_elo["KR"] < lck
    assert power.strength(career, "EMEA", 0) > cat.leagues["LEC"].strength
    # A stronger region makes its clubs bigger in the world's eyes.
    assert reputation.world(cat, career, "G2") > 50 + (reputation.team_reputation(cat, career, "G2") - 50) * 0.88


def test_a_manager_near_the_top_gains_less(drafted):
    career = drafted.model_copy(deep=True)
    career.manager_standing[career.region] = 60.0
    reputation.change_manager(cat, career, 3.0)
    low = career.manager_standing[career.region] - 60.0
    career.manager_standing[career.region] = 95.0
    reputation.change_manager(cat, career, 3.0)
    high = career.manager_standing[career.region] - 95.0
    assert low == 3.0 and 0 < high < 1.0
    career.manager_standing[career.region] = 95.0
    reputation.change_manager(cat, career, -3.0)
    assert career.manager_standing[career.region] == 92.0, "a loss counts in full"


def test_msi_seeds_the_first_stand_region_and_plays_in_the_rest(finished):
    career = finished
    msi = career.competitions[f"{career.season}-MSI"]
    fst = career.competitions[f"{career.season}-FST"]
    assert len(msi.entrants) == 11
    play_in = msi.stages[0]
    assert play_in.kind == "double_elim" and len(play_in.teams) == 4
    region = cat.teams[fst.placements[0]].region
    assert all(cat.teams[t].region != region for t in play_in.teams), "the First Stand region skips the play-in"
    bracket = msi.stages[1]
    assert len(bracket.teams) == 8 and bracket.teams[-1] == play_in.ranking[0]
    assert sum(cat.teams[t].region == region for t in bracket.teams[:7]) == 2


def test_worlds_gives_the_two_best_msi_regions_a_fourth_team(finished):
    career = finished
    worlds = career.competitions[f"{career.season}-WORLDS"]
    best = calendar.event_regions(cat, career, "MSI")[:2]
    count = Counter(cat.teams[t].region for t in worlds.entrants)
    for region in cat.regions:
        base = next(e for e in calendar.INTERNATIONALS if e.id == "WORLDS").slots[region]
        assert count[region] == base + (1 if region in best else 0), region
    play_in, swiss = worlds.stages[0], worlds.stages[1]
    assert play_in.kind == "double_elim" and len(play_in.teams) == 4
    assert {cat.teams[t].region for t in play_in.teams} == set(cat.regions) - set(best)
    assert swiss.kind == "swiss" and len(swiss.teams) == 16 and swiss.pots[3][-1] == play_in.ranking[0]


def test_the_inbox_announces_the_places_and_what_first_stand_and_msi_decide(finished):
    subjects = [m.subject for m in finished.inbox]
    assert f"International places for {finished.season}" in subjects
    assert any(s.endswith("earn two MSI byes") for s in subjects)
    assert any(s.endswith("send four teams to Worlds") for s in subjects)


def test_a_season_moves_the_regions(finished):
    assert finished.region_elo != finished.region_elo_start or any(
        t.elo != t.elo_start for t in finished.teams.values())
    view = power.view(cat, finished)
    assert [r["rank"] for r in view["regions"]] == list(range(1, 7))
    assert len(view["teams"]) == len(finished.teams) and view["regions"][0]["strength"] == 100
