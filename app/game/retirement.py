"""Retirements, announced a season ahead the way Football Manager does it.

At the start of every off-season some players say the coming season will be their last. They play
it out and retire when it ends: they leave their team, become nobody's free agent and drop out of
searches, the market and shortlists.

The data has no ages, so a career age stands in: a debut at about 18 and some 90 games a year
before the game started, counting no more than eight years of games, then a year for every season
played in it, give or take two years. The cap matters for the stars of the LCK and LPL, who play
far more than 90 games a year: counted in full, a 24-year-old with 800 games came out at 27. A rookie
starts at 18. The chance of announcing grows with that age from 25 (CHANCE); younger players only
give up when they are going nowhere (rated below 60).
A player still among the best (rated 85 or more) does not stop before 30, and after that is a third
as likely to. A good player (80 or more) is half as likely, and a legend still that good after a
thousand career games (a Faker) five times less likely; a veteran going nowhere (rated below 60) is
twice as likely. The age is never shown: it is a stand-in, not a fact."""

from app.game import roster, transfers
from app.game.catalog import Catalog
from app.game.rng import Rng, fnv1a
from app.game.state import Career, InboxMessage

DATA_SEASON = 2026  # the season the catalog's career games run up to
GAMES_A_YEAR = 90
COUNTED_GAMES = 8 * GAMES_A_YEAR  # games past eight years' worth add no age: the busiest teams play far more
DEBUT_AGE = 18
# (career age from which, chance a season of announcing retirement)
CHANCE = ((32, 0.50), (31, 0.35), (30, 0.25), (29, 0.16), (28, 0.10), (27, 0.06), (25, 0.03))
YOUNG_QUIT = 0.01  # under 25 only a player going nowhere gives up
STAR = 85  # rated this or better: does not stop before STAR_AGE, and a third as likely after it
STAR_AGE = 30
GOOD = 80  # rated this or better: half as likely to stop
LEGEND_GAMES = 1000  # still GOOD after this many career games: five times less likely
FADING = 60  # rated below this: twice as likely
NOTABLE = 75  # reputation from which a retirement is news everywhere


def career_age(cat: Catalog, career: Career, pid: str) -> float:
    player = cat.players[pid]
    rookie = next((r for r in career.rookies if r.id == pid), None) if pid.startswith("r") else None
    debut = rookie.season if rookie else DATA_SEASON
    jitter = (fnv1a(f"{pid}|age") / 0xFFFFFFFF - 0.5) * 4
    games = min(player.experience, COUNTED_GAMES)
    return max(17.0, DEBUT_AGE + games / GAMES_A_YEAR + (career.season - debut) + jitter)


def chance(cat: Catalog, career: Career, pid: str) -> float:
    age = career_age(cat, career, pid)
    rating = roster.overall(cat, career, pid)
    if age < CHANCE[-1][0]:
        return YOUNG_QUIT if rating < FADING else 0.0
    if rating >= STAR and age < STAR_AGE:
        return 0.0  # still among the best: not yet
    base = next(p for start, p in CHANCE if age >= start)
    if rating >= GOOD and roster.career_games(cat, career, pid) >= LEGEND_GAMES:
        base /= 5
    elif rating >= STAR:
        base /= 3
    elif rating >= GOOD:
        base /= 2
    elif rating < FADING:
        base *= 2
    return min(0.9, base)


def _message(career: Career, kind: str, subject: str, body: str) -> None:
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind=kind, subject=subject, body=body))  # type: ignore[arg-type]
    career.next_message += 1


def _tell(cat: Catalog, career: Career, pid: str, subject: str, body: str) -> None:
    """The manager hears about their own players and about the big names."""
    state = career.players[pid]
    if state.team == career.team:
        _message(career, "player", subject, body)
    elif cat.players[pid].reputation >= NOTABLE:
        _message(career, "news", subject, body)


def retire(cat: Catalog, career: Career, season: int) -> list[str]:
    """Everyone who said `season` would be their last stops now."""
    gone = []
    for pid, state in career.players.items():
        if state.retired or state.retiring is None or state.retiring > season:
            continue
        name = cat.players[pid].name
        _tell(cat, career, pid, f"{name} retires", f"{name} has played their last game and retires from professional play.")
        team = career.teams.get(state.team or "")
        if team is not None:
            transfers._leave(cat, career, team, pid)
            if team.franchise == pid:
                new_franchise(cat, career, team, name)
        state.team = None
        state.contract = None
        state.retired = True
        state.retiring = None
        gone.append(pid)
    career.shortlist = [e for e in career.shortlist if e.player not in gone]
    return gone


def new_franchise(cat: Catalog, career: Career, team, retired: str) -> None:
    """The club's best player left takes over as its franchise player."""
    team.franchise = max(team.roster, key=lambda p: (roster.overall(cat, career, p), cat.players[p].reputation), default=None)
    if team.franchise and team.id == career.team:
        new = cat.players[team.franchise].name
        _message(career, "player", f"{new} is the new franchise player",
                 f"With {retired} gone, the board makes {new} the face of the club: not for sale, never released, "
                 "and kept on when the contract runs out.")


def announce(cat: Catalog, career: Career, rng: Rng, last_season: int) -> list[str]:
    """Some players say `last_season` will be their last."""
    told = []
    for pid, state in career.players.items():
        if state.retired or state.retiring is not None:
            continue
        if not rng.chance(chance(cat, career, pid)):
            continue
        state.retiring = last_season
        told.append(pid)
        name = cat.players[pid].name
        _tell(cat, career, pid, f"{name} will retire after the {last_season} season",
              f"{name} has decided that the {last_season} season will be their last. They will play it out and "
              "retire when it ends.")
    return told
