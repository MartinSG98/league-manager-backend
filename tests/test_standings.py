"""Round-robin tables and their tiebreaks."""

from datetime import date
from types import SimpleNamespace

from app.game import competitions as comps
from app.game.state import GameRecord, Match, Stage


def _table(results: list[tuple[str, str, int, int]]) -> list[str]:
    """The table of a made-up round robin, from (home, away, home games, away games)."""
    matches = {}
    for i, (home, away, h, a) in enumerate(results):
        games = [GameRecord.model_construct(winner=home) for _ in range(h)] + [GameRecord.model_construct(winner=away)
                                                                              for _ in range(a)]
        matches[f"m{i}"] = Match(id=f"m{i}", competition="C", stage="S", label="R", day=date(2027, 1, 1), home=home,
                                 away=away, best_of=3, winner=home if h > a else away, games=games)
    stage = Stage(id="S", name="S", kind="round_robin", best_of=3, teams=sorted({t for r in results for t in r[:2]}),
                  matches=list(matches))
    return [r["team"] for r in comps.standings(SimpleNamespace(matches=matches), stage)]  # type: ignore[arg-type]


def test_teams_level_on_wins_are_ranked_by_their_meeting_before_their_games():
    # A beat B and D and lost to C, with games 4-4. B beat C and D and lost to A, with games 5-2.
    table = _table([("A", "B", 2, 1), ("C", "A", 2, 0), ("B", "D", 2, 0), ("D", "C", 2, 0), ("A", "D", 2, 1),
                    ("B", "C", 2, 0)])
    assert table[:2] == ["A", "B"], "B has the better games, but A won the meeting"


def test_a_three_way_circle_goes_to_the_games_among_them():
    # The First Stand 2033 group: C9 beat GEN 2-1, GEN beat IG 2-1, IG beat C9 2-0, and all three beat FUR.
    table = _table([("IG", "FUR", 2, 0), ("GEN", "C9", 1, 2), ("GEN", "IG", 2, 1), ("C9", "FUR", 2, 0),
                    ("IG", "C9", 2, 0), ("GEN", "FUR", 2, 0)])
    assert table == ["IG", "GEN", "C9", "FUR"]
