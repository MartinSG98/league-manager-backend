"""Balance harness for the match engine: how often does the stronger side win a game?

    python -m scripts.simulate            # 2000 random tier-one pairings
    python -m scripts.simulate 5000 --season 3
    python -m scripts.simulate 20000 --souls

Teams come out of a normal career's drafts. For each game the script records the gap in team
power after champion select (what match_engine.prepare works out) and who won, then prints the
win rate per gap. --season N also plays N whole seasons and counts who wins each title, to see
that favourites win often but not always. --souls also prints how often the side with each
Soul wins, next to the real win rate (SOUL_TARGET)."""

import argparse
import random
import time
from collections import Counter, defaultdict

from app.game import champ_select as cs
from app.game import engine, manager, match_engine, matchday
from app.game.catalog import get_catalog
from app.game.rng import Rng
from app.game.state import (
    AdvanceAction, BoardMeetingAction, ChampSelect, CreateManagerAction, DraftSimAction, Match, SimSeriesAction,
)

TARGET = {2: 0.58, 4: 0.65, 6: 0.72, 8: 0.78, 10: 0.84, 14: 0.9}
# How often the side with each Soul wins: leagueofgraphs.com, all regions, patch 16.20 (October
# 2026, about 3.1 million ranked games). Pro play has no breakdown by element; the side with the
# Soul won all 52 games of the Worlds 2025 Swiss stage.
SOUL_TARGET = {"Infernal": 0.868, "Mountain": 0.880, "Ocean": 0.871, "Cloud": 0.906, "Hextech": 0.875, "Chemtech": 0.868}


def drafted_career(cat, seed: int):
    """G2 after the draft, its manager created with the points spread evenly, as the tests do."""
    career = engine.new_career(cat, "bot", "G2", seed)
    engine.apply(cat, career, CreateManagerAction(type="create_manager", background="coach",
                                                  attributes=manager.even_spread(career, "coach")))
    engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
    engine.apply(cat, career, DraftSimAction(type="draft_sim"))
    return career


def win_curve(games: int, seed: int, souls: bool = False) -> None:
    cat = get_catalog()
    career = drafted_career(cat, seed)
    rng = Rng(career)
    teams = list(career.teams)
    pick = random.Random(seed)
    buckets: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    blue_wins = 0
    soul_games: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # element -> [Soul side won, games]
    start = time.time()
    for i in range(games):
        a, b = pick.sample(teams, 2)
        match = Match(id=f"x{i}", competition="x", stage="x", label="x", day=career.day, home=a, away=b)
        select = ChampSelect()
        sides = matchday.draft_sides(cat, career, a, b)
        cs.run_ai(cat, career, select, sides, rng, human=None)
        gb = match_engine.prepare(cat, career, "blue", a, sides["blue"].lineup, dict(select.blue_picks), sides["blue"].tactics)
        gr = match_engine.prepare(cat, career, "red", b, sides["red"].lineup, dict(select.red_picks), sides["red"].tactics)
        gap = gb.base - gr.base
        result = match_engine.simulate(cat, career, gb, gr, rng, 1, (select.blue_bans, select.red_bans))
        blue_won = result.record.winner == a
        blue_wins += blue_won
        # Fold onto the stronger side so every bucket counts both directions.
        key = min(14, int(round(abs(gap) / 2)) * 2)
        stronger_won = blue_won if gap >= 0 else not blue_won
        buckets[key][0] += stronger_won
        buckets[key][1] += 1
        for event in result.events:
            if event.kind == "soul":
                element = event.text.split(" claim the ")[1].removesuffix(" Soul")
                soul_games[element][0] += (event.side == "blue") == blue_won
                soul_games[element][1] += 1
        _ = match
    print(f"{games} games in {time.time() - start:.1f}s, blue side won {blue_wins / games:.0%}")
    print("gap  games  stronger wins  target")
    for key in sorted(buckets):
        won, n = buckets[key]
        print(f"{key:>3}  {n:>5}  {won / n:>12.0%}  {TARGET.get(key, ''):>6}")
    if souls:
        print()
        print("soul       games  share  soul side wins  target")
        for element in match_engine.DRAGONS:
            won, n = soul_games[element]
            print(f"{element:<9} {n:>6}  {n / games:>5.1%}  {won / max(1, n):>14.1%}  {SOUL_TARGET[element]:>6.1%}")


def seasons(count: int, seed: int) -> None:
    cat = get_catalog()
    titles: dict[str, Counter] = defaultdict(Counter)
    for s in range(count):
        career = drafted_career(cat, seed + s)
        while career.phase == "season":
            if career.live:
                engine.apply(cat, career, SimSeriesAction(type="sim_series"))
            else:
                engine.apply(cat, career, AdvanceAction(type="advance"))
        for comp in career.competitions.values():
            key = comp.short if comp.kind == "international" else (comp.league or comp.short)
            titles[key][cat.teams[comp.placements[0]].tag] += 1
    for key, counter in titles.items():
        print(f"{key:<26} {', '.join(f'{t} {n}' for t, n in counter.most_common(6))}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("games", nargs="?", type=int, default=2000)
    parser.add_argument("--season", type=int, default=0, help="also play this many whole seasons")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--souls", action="store_true", help="also the win rate with each Soul")
    args = parser.parse_args()
    win_curve(args.games, args.seed, args.souls)
    if args.season:
        seasons(args.season, args.seed)


if __name__ == "__main__":
    main()
