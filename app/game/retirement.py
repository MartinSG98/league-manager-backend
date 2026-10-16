"""Retirements, announced a season ahead the way Football Manager does it.

At the start of every off-season some players say the coming season will be their last. They play
it out and retire when it ends: they leave their team, become nobody's free agent and drop out of
searches, the market and shortlists.

A player's age is real where Liquipedia has a birth date, which it has for nearly every tier-one
player; for the rest a career age stands in (roster.age). The chance of announcing grows with age
from 25 (CHANCE) and is high from 33; younger players only give up when they are going nowhere
(rated below 60). A player still among the best (rated 85 or more) does not stop before 30, and
after that is a third as likely to. A good player (80 or more) is half as likely, and so is a legend
still that good after a thousand career games (a Faker); a veteran going nowhere (rated below 60)
is twice as likely. Age also takes a veteran's level down every off-season (offseason.develop), so
a legend is rarely still that good at 33.

A player who has been in the top flight (in 2026, or with a club in this career) and has no club
when an off-season starts is going nowhere: after two such off-seasons in a row they retire half of
the time, after three they always do (unsigned). Tier-two players are free agents only because the
game has no tier-two clubs, so they are left alone."""

from app.game import roster, transfers
from app.game.catalog import Catalog
from app.game.rng import Rng
from app.game.state import Career, InboxMessage

# (age from which, chance a season of announcing retirement)
CHANCE = ((34, 0.80), (33, 0.65), (32, 0.50), (31, 0.35), (30, 0.25), (29, 0.16), (28, 0.10), (27, 0.06),
          (25, 0.03))
YOUNG_QUIT = 0.01  # under 25 only a player going nowhere gives up
STAR = 85  # rated this or better: does not stop before STAR_AGE, and a third as likely after it
STAR_AGE = 30
GOOD = 80  # rated this or better: half as likely to stop
LEGEND_GAMES = 1000  # still GOOD after this many career games: half as likely
FADING = 60  # rated below this: twice as likely
NOTABLE = 75  # reputation from which a retirement is news everywhere
UNSIGNED_MAYBE = 2  # off-seasons in a row without a club after which a top-flight player may give up ...
UNSIGNED_GIVE_UP = 0.5  # ... with this chance ...
UNSIGNED_ALWAYS = 3  # ... and after which they always do


def career_age(cat: Catalog, career: Career, pid: str) -> float:
    return roster.age(cat, career, pid)


def chance(cat: Catalog, career: Career, pid: str) -> float:
    age = career_age(cat, career, pid)
    rating = roster.overall(cat, career, pid)
    if age < CHANCE[-1][0]:
        return YOUNG_QUIT if rating < FADING else 0.0
    if rating >= STAR and age < STAR_AGE:
        return 0.0  # still among the best: not yet
    base = next(p for start, p in CHANCE if age >= start)
    if rating >= GOOD and roster.career_games(cat, career, pid) >= LEGEND_GAMES:
        base /= 2
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
                transfers.vacate_franchise(cat, career, team, f"{name} has retired")
        state.team = None
        state.contract = None
        state.retired = True
        state.retiring = None
        gone.append(pid)
    career.shortlist = [e for e in career.shortlist if e.player not in gone]
    return gone


def _top_flight(cat: Catalog, career: Career, pid: str) -> bool:
    """Has been in the top flight: a tier-one player in 2026, a rookie, or anyone who has played for a club here."""
    if pid.startswith("r") or career.players[pid].played:
        return True
    team = cat.teams.get(cat.players[pid].team)
    return team is not None and cat.leagues[team.league].tier == 1


def unsigned(cat: Catalog, career: Career, rng: Rng) -> list[str]:
    """At the start of an off-season: count another one without a club for every top-flight player
    who has none, and retire those who have waited long enough."""
    gone = []
    for pid, state in career.players.items():
        if state.retired:
            continue
        if state.team is not None or not _top_flight(cat, career, pid):
            state.unsigned = 0
            continue
        state.unsigned += 1
        if state.unsigned >= UNSIGNED_ALWAYS or (state.unsigned >= UNSIGNED_MAYBE and rng.chance(UNSIGNED_GIVE_UP)):
            name = cat.players[pid].name
            _tell(cat, career, pid, f"{name} retires",
                  f"No club has signed {name} for {state.unsigned} seasons, and {name} has decided to retire.")
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
