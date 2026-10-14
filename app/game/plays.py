"""Set plays: moves a team rehearses in scrims and pulls out once in a series.

A team knows a set play once it has drilled it to 100 percent (see training.py); from 40 percent
it can try it, with less chance of it working. After every champion select each side may call
one play it has not used yet in the series. The play runs at its minute of the game and either
works, giving the edge it is built for, or backfires.

How likely a play is to work: 30 percent, plus up to 45 for how well it is learned, plus the
team's skill in the area behind it (+2.5 percent a point above 10), minus the opponent's in the
same area, plus at the manager's club 1 percent a point of the manager's tactics above 10, plus
how well it suits the composition: early plays want an early composition,
the split push wants a scaling one.

When both sides call the same play they run into each other (match_engine.Game.clash): one fight
instead of two plays. Two sides about as likely to make it work cancel each other out 35 percent of
the time; otherwise the side likelier to make it work is likelier to win it, by 1.5 percent per
point of difference, and the winner takes a big swing, such as a 4 for 0 when two tower dives meet."""

from dataclasses import dataclass
from typing import Literal

from app.game import manager
from app.game.catalog import Catalog
from app.game.rng import Rng
from app.game.state import Career, Match, TeamState

USABLE_FROM = 40.0  # learned percentage a play can be called from


@dataclass(frozen=True)
class SetPlay:
    id: str
    name: str
    phase: Literal["Level 1", "Early game", "Mid game", "Late game"]
    minute: int  # when it is run
    weeks: int  # weeks to learn at a normal load with an average coach
    area: str  # the team area that helps it work, see training.AREAS
    style: Literal["early", "scaling", "any"]  # the composition it suits
    text: str
    effect: str


PLAYS: dict[str, SetPlay] = {p.id: p for p in (
    SetPlay("invade", "Level 1 invade", "Level 1", 1, 3, "early_game", "early",
            "All five walk into the enemy jungle before the camps spawn to steal a buff or catch someone out.",
            "First blood and a stolen buff; backfires into the enemy's first blood"),
    SetPlay("fnatic_bush", "Fnatic bush", "Level 1", 1, 4, "early_game", "early",
            "The team hides in a lane brush at level 1 and jumps whoever walks past.",
            "First blood and a lane ahead; if spotted, the lanes start behind"),
    SetPlay("lane_swap", "Lane swap", "Early game", 2, 4, "macro", "any",
            "The duo goes top to dodge a losing matchup and take early plates.",
            "The worst lane is safe for ten minutes plus plate gold"),
    SetPlay("grubs", "Voidgrub setup", "Early game", 6, 3, "objectives", "any",
            "Lane priority and deep wards so the team owns both Voidgrub spawns.",
            "Both Voidgrub spawns, or both lost if the enemy reads it"),
    SetPlay("dive", "Tower dive", "Early game", 7, 5, "early_game", "early",
            "Jungle, mid and support dive the enemy bot lane under their tower.",
            "Two kills and the first tower; two deaths if it fails"),
    SetPlay("drakes", "Dragon setup", "Mid game", 12, 4, "objectives", "any",
            "Vision denial around the pit and lane priority before the next two dragons.",
            "The next two dragons"),
    SetPlay("pick", "Vision trap", "Mid game", 18, 4, "macro", "any",
            "Deep wards and a hidden flank to catch a carry before an objective.",
            "A pick on a carry and the upper hand in the next fight"),
    SetPlay("baron_bait", "Baron bait", "Mid game", 22, 5, "teamfighting", "any",
            "Start Baron with vision on the entrances to pull the enemy into a choke.",
            "A teamfight won at Baron and the Baron itself"),
    SetPlay("split_push", "1-3-1 split push", "Late game", 26, 6, "macro", "scaling",
            "Two side lanes pressure while three hold the middle of the map.",
            "Towers and an inhibitor in the late game; a side laner caught if it fails"),
)}


def known(team: TeamState) -> list[str]:
    return [p for p, v in team.plays.items() if p in PLAYS and v >= USABLE_FROM]


def available(career: Career, team_id: str, match: Match) -> list[str]:
    used = set(match.plays_used.get(team_id, []))
    return [p for p in known(career.teams[team_id]) if p not in used]


def fit(play: SetPlay, early: float) -> float:
    """How well a composition suits a play, -0.1..+0.1. `early` is champ_select.focus_bias."""
    lean = max(-2.0, min(2.0, early)) / 2
    if play.style == "early":
        return 0.1 * lean
    if play.style == "scaling":
        return -0.1 * lean
    return 0.0


def chance(play: SetPlay, learned: float, skill: float, enemy_skill: float, early: float, bonus: float = 0.0) -> float:
    value = 0.30 + 0.45 * min(100.0, learned) / 100 + 0.025 * (skill - 10) - 0.015 * (enemy_skill - 10) + bonus
    return max(0.1, min(0.9, value + fit(play, early)))


def team_chance(cat: Catalog, career: Career, team_id: str, enemy_id: str, play_id: str, early: float) -> float:
    play = PLAYS[play_id]
    team, enemy = career.teams[team_id], career.teams[enemy_id]
    # The manager's tactics, at their club: a percent a point above 10.
    bonus = 0.01 * (manager.own(career, "tactics") - manager.NEUTRAL) if team_id == career.team else 0.0
    return chance(play, team.plays.get(play_id, 0.0), team.skills.get(play.area, 10.0),
                  enemy.skills.get(play.area, 10.0), early, bonus)


def choose(cat: Catalog, career: Career, team_id: str, enemy_id: str, match: Match, early: float,
           rng: Rng | None = None) -> str | None:
    """The play an AI side (or the manager's assistant) calls: the likeliest to work, if any is
    worth the risk. An AI side keeps some plays back, so it does not run one every game."""
    options = available(career, team_id, match)
    if not options:
        return None
    scored = sorted(options, key=lambda p: -team_chance(cat, career, team_id, enemy_id, p, early))
    best = scored[0]
    if team_chance(cat, career, team_id, enemy_id, best, early) < 0.45:
        return None
    if rng is not None and not rng.chance(0.7):
        return None
    return best
