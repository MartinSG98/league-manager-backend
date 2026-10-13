"""The staff market: hiring, extending and releasing coaches and analysts, and the new faces that
join it every off-season.

Talks work like a player's (contracts.py), on a staff member's own page:
- **The ask.** Their salary (staff.py), a sixth more to leave a club they already work for. They
  settle for 85 to 95 percent of it, a fixed share per person and season. Two seasons is what they
  want; every season more or less costs 5 percent of what the offer is worth to them. Three offers
  below that and they walk away for 30 days.
- **Who comes.** A coach rated 55 is happy anywhere; every 8 points more wants another star of
  club reputation, give or take one: a 95 wants a five-star club.
- **Staff of another club** cost compensation, half of what is left on their contract. The club
  appoints a replacement at once. Agreed talks pay it from the bank.
- **The manager's own staff** no longer renew on their own: their contracts run out on free agency
  day like the players', and they can be extended in their last season.
- **Releasing** costs half of what is left on the contract, as for a player.
- **New faces.** Every off-season some of the players who retire join the market, the better and
  longer their career the likelier (a support or jungler more often as an analyst), with skills
  drawn from their career. Every region also gets a coach and an analyst nobody has heard of, most
  of them ordinary, a few very good."""

from datetime import timedelta

from app.game import roster, transfers
from app.game import staff as staffing
from app.game.catalog import Catalog
from app.game.errors import IllegalAction
from app.game.rng import Rng, fnv1a
from app.game.staff import ATTRIBUTES
from app.game.state import Career, CareerStaff, Contract, InboxMessage, Negotiation

MOVE_PREMIUM = 1.15  # on the ask, to leave a club they work for
MAX_YEARS = 3
WANTED_YEARS = 2
MAX_ROUNDS = 3
WALK_AWAY = timedelta(days=30)
HAPPY_ANYWHERE = 55  # overall a staff member joins any club with
POINTS_A_STAR = 8
COMPENSATION = 0.5  # of what is left on their contract
FORMER_GAMES = 300  # career games from which a retiring player may move into staff
SEAT_NAMES = {"coach": "assistant coach", "analyst": "analyst"}


# ---------- what they want ----------


def _flexibility(sid: str, season: int) -> float:
    return 0.85 + 0.10 * (fnv1a(f"{sid}|{season}|staff") / 0xFFFFFFFF)


def asking_salary(cat: Catalog, career: Career, sid: str) -> int:
    state = career.staff.get(sid)
    moving = state is not None and state.team not in (None, career.team)
    return int(round(cat.staff[sid].salary * (MOVE_PREMIUM if moving else 1.0) / 5) * 5)


def stars_wanted(cat: Catalog, sid: str) -> float:
    return max(0.0, (cat.staff[sid].overall - HAPPY_ANYWHERE) / POINTS_A_STAR)


def compensation(cat: Catalog, career: Career, sid: str) -> int | None:
    """What another club wants for letting their staff member go, None when they are free or yours."""
    state = career.staff.get(sid)
    if state is None or state.team in (None, career.team) or state.contract is None:
        return None
    first = career.season + 1 if career.phase == "offseason" else career.season
    seasons = max(1, state.contract.until - first + 1)
    return max(10, int(round(state.contract.salary * seasons * COMPENSATION / 5) * 5))


def release_cost(career: Career, sid: str) -> int:
    contract = career.staff[sid].contract
    if contract is None:
        return 0
    first = career.season + 1 if career.phase == "offseason" else career.season
    return int(contract.salary * max(0, contract.until - first + 1) * 0.5)


def mine(career: Career, sid: str) -> bool:
    state = career.staff.get(sid)
    return state is not None and state.team == career.team


def check_can_talk(cat: Catalog, career: Career, sid: str) -> str | None:
    """Why the manager cannot talk to this staff member now, or None."""
    from app.game import reputation

    if sid not in cat.staff:
        return "Unknown staff member"
    person = cat.staff[sid]
    state = career.staff.get(sid)
    if career.board.sacked:
        return "You have no club right now"
    if career.live is not None:
        return "Not during a match"
    if career.phase == "draft":
        return "Staff are hired in the draft until it is over"
    talks = career.staff_talks.get(sid)
    if talks and talks.blocked_until and career.day < talks.blocked_until:
        return f"{person.name} does not want to talk until {talks.blocked_until:%d %B}"
    team = career.teams[career.team]
    if mine(career, sid):
        if state and state.contract and state.contract.until > career.season:
            return f"{person.name} is signed beyond this season already"
        return None
    seat = getattr(team, person.kind)
    if seat:
        return f"Release your {SEAT_NAMES[person.kind]}, {cat.staff[seat].name}, first"
    club = reputation.stars(reputation.team_reputation(cat, career, career.team))
    if club + 1 < stars_wanted(cat, sid):
        return f"{person.name} wants to work for a bigger club"
    fee = compensation(cat, career, sid)
    if fee is not None and fee > transfers.free_cash(career):
        return f"{cat.teams[state.team].name} want {fee}k compensation, more than you have free in the bank"  # type: ignore[union-attr]
    return None


# ---------- talks ----------


def _talks(career: Career, sid: str) -> Negotiation:
    kind = "extend" if mine(career, sid) else "sign"
    talks = career.staff_talks.get(sid)
    if talks is None or talks.kind != kind:
        talks = Negotiation(player=sid, kind=kind)
        career.staff_talks[sid] = talks
    return talks


def offer(cat: Catalog, career: Career, sid: str, salary: int, years: int) -> Negotiation:
    problem = check_can_talk(cat, career, sid)
    if problem:
        raise IllegalAction(problem)
    if not 1 <= years <= MAX_YEARS:
        raise IllegalAction(f"Staff contracts run one to {MAX_YEARS} seasons")
    if salary <= 0:
        raise IllegalAction("Offer a salary")
    _fits(cat, career, sid, salary)
    talks = _talks(career, sid)
    want = asking_salary(cat, career, sid)
    floor = want * _flexibility(sid, career.season)
    effective = salary * (1 - 0.05 * abs(years - WANTED_YEARS))
    name = cat.staff[sid].name
    talks.rounds += 1
    if effective >= floor:
        _sign(cat, career, sid, salary, years)
        talks.counter = None
        talks.message = f"{name} accepts: {salary}k a season for {years} season{'s' if years > 1 else ''}."
        return talks
    if effective < 0.6 * want or talks.rounds >= MAX_ROUNDS:
        talks.blocked_until = career.day + WALK_AWAY
        talks.counter = None
        talks.rounds = 0
        talks.message = f"{name} ends the talks. Try again after {talks.blocked_until:%d %B}."
        return talks
    talks.counter = max(int(round(floor / 5) * 5), int(round((salary + want) / 2 / 5) * 5))
    talks.counter_years = WANTED_YEARS
    talks.message = f"{name} wants {talks.counter}k a season over {WANTED_YEARS} seasons."
    return talks


def accept_counter(cat: Catalog, career: Career, sid: str) -> Negotiation:
    talks = career.staff_talks.get(sid)
    if talks is None or talks.counter is None:
        raise IllegalAction("There is no counter-offer on the table")
    problem = check_can_talk(cat, career, sid)
    if problem:
        raise IllegalAction(problem)
    _fits(cat, career, sid, talks.counter)
    _sign(cat, career, sid, talks.counter, talks.counter_years or WANTED_YEARS)
    talks.message = f"{cat.staff[sid].name} signs for {talks.counter}k a season."
    talks.counter = None
    return talks


def budget_room(cat: Catalog, career: Career, sid: str) -> int:
    """The most this staff member could be paid within the salary budget."""
    from app.game import contracts

    team = career.teams[career.team]
    state = career.staff.get(sid)
    current = state.contract.salary if mine(career, sid) and state and state.contract and career.phase != "offseason" else 0
    return team.budget - contracts.committed(career, team) + current


def _fits(cat: Catalog, career: Career, sid: str, salary: int) -> None:
    if salary > budget_room(cat, career, sid):
        raise IllegalAction("That salary does not fit your budget")


def _sign(cat: Catalog, career: Career, sid: str, salary: int, years: int) -> None:
    person = cat.staff[sid]
    state = career.staff.setdefault(sid, _state(sid))
    team = career.teams[career.team]
    first = career.season + 1 if career.phase == "offseason" else career.season
    joined = not mine(career, sid)
    paid = None
    if joined and state.team:
        paid = compensation(cat, career, sid)
        old = career.teams[state.team]
        team.cash -= paid or 0
        old.cash += paid or 0
        setattr(old, person.kind, None)
        transfers._hire_staff(cat, career, old, person.kind)  # the other club appoints someone at once
    state.team = career.team
    state.contract = Contract(salary=salary, until=first + years - 1)
    setattr(team, person.kind, sid)
    subject = (f"{person.name} joins as {SEAT_NAMES[person.kind]}" + (f" for {paid}k compensation" if paid else "")
               if joined else f"{person.name} signs a new contract")
    _message(career, "staff", subject, f"{salary}k a season until the end of {state.contract.until}.")


def _state(sid: str):
    from app.game.state import StaffState

    return StaffState(id=sid)


def release(cat: Catalog, career: Career, sid: str) -> int:
    if not mine(career, sid):
        raise IllegalAction("That staff member does not work for you")
    if career.live is not None:
        raise IllegalAction("Not during a match")
    person = cat.staff[sid]
    cost = release_cost(career, sid)
    team = career.teams[career.team]
    team.cash -= cost
    setattr(team, person.kind, None)
    state = career.staff[sid]
    state.team = None
    state.contract = None
    career.staff_talks.pop(sid, None)
    _message(career, "staff", f"{person.name} leaves the club",
             f"You release your {SEAT_NAMES[person.kind]}. The club pays {cost}k, half of what was left on the contract.")
    return cost


def contracts_run_out(cat: Catalog, career: Career) -> None:
    """Free agency day: the manager's staff whose contract ended and were not extended leave."""
    team = career.teams[career.team]
    for kind in ("coach", "analyst"):
        sid = getattr(team, kind)
        state = career.staff.get(sid or "")
        if sid and state and state.contract and state.contract.until <= career.season:
            setattr(team, kind, None)
            state.team = None
            state.contract = None
            _message(career, "staff", f"{cat.staff[sid].name} leaves the club",
                     f"The contract of your {SEAT_NAMES[kind]} ran out. Hire a new one from Scouting, or the board "
                     "fills the seat when the window closes.")


def expiring(career: Career) -> list[str]:
    team = career.teams[career.team]
    return [sid for sid in (team.coach, team.analyst)
            if sid and sid in career.staff and career.staff[sid].contract
            and career.staff[sid].contract.until <= career.season]  # type: ignore[union-attr]


# ---------- new faces ----------

# A retired player's role leans their staff skills: (chance to become an analyst, coach bonuses)
_ROLE_LEAN = {
    "TOP": (0.3, {"teaching": 1}),
    "JNG": (0.5, {"drafting": 2}),
    "MID": (0.35, {"drafting": 1, "teaching": 1}),
    "BOT": (0.3, {"development": 1}),
    "SUP": (0.5, {"motivation": 2}),
}
# How good a new face is: (share, lowest base, highest base) on the 1-20 scale
_NEW_FACES = ((0.65, 4, 9), (0.28, 8, 13), (0.07, 12, 16))


def new_faces(cat: Catalog, career: Career, rng: Rng, retired: list[str], season: int) -> list[CareerStaff]:
    """The off-season's newcomers to the staff market: some of the players who just retired, and a
    coach and an analyst per region nobody has heard of."""
    made: list[CareerStaff] = []
    for pid in retired:
        player = cat.players[pid]
        games = roster.career_games(cat, career, pid)
        rating = roster.overall(cat, career, pid)
        if games < FORMER_GAMES or not rng.chance(max(0.2, min(0.7, 0.35 + 0.3 * (rating - 60) / 30))):
            continue
        analyst_share, lean = _ROLE_LEAN.get(player.role, (0.35, {}))
        kind = "analyst" if rng.chance(analyst_share) else "coach"
        base = 5 + (rating - 60) / 6 + min(3.0, games / 500)
        region = cat.leagues[player.league].region
        made.append(_person(f"x-{pid}", player.name, kind, f"Former {player.role} player", region, player.country,
                            base, lean if kind == "coach" else {}, rng, season, former=pid))
    for region in sorted({t.region for t in cat.teams.values() if t.id in career.teams}):
        for kind in ("coach", "analyst"):
            roll, base = rng.next(), 6.0
            for share, low, high in _NEW_FACES:
                if roll < share:
                    base = low + rng.next() * (high - low)
                    break
                roll -= share
            seed = fnv1a(f"{season}:{region}:{kind}:new")
            sid = f"n-{season}-{region.lower()}-{kind}"
            made.append(_person(sid, staffing._handle(seed), kind, "Newcomer", region, None, base, {}, rng, season))
    career.new_staff += made
    for person in made:
        career.staff[person.id] = _state(person.id)
    return made


def _person(sid: str, name: str, kind: str, position: str, region: str, country: str | None, base: float,
            bonus: dict[str, int], rng: Rng, season: int, former: str | None = None) -> CareerStaff:
    attrs = {a: int(max(1, min(20, round(base + bonus.get(a, 0) + (rng.next() - 0.5) * 4)))) for a in ATTRIBUTES[kind]}
    avg = sum(attrs.values()) / len(attrs)
    overall = round(30 + (avg - 1) * 69 / 19)
    salary = max(10, int(round(12 * 1.25 ** (avg - 5) * staffing._ECONOMY.get(region, 1.0)
                               * (1.15 if kind == "coach" else 1.0) / 5) * 5))
    return CareerStaff(id=sid, name=name, kind=kind, position=position, region=region, country=country,
                       attributes=attrs, overall=overall, salary=salary, season=season, former_player=former)


def _message(career: Career, kind: str, subject: str, body: str) -> None:
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind=kind, subject=subject, body=body))  # type: ignore[arg-type]
    career.next_message += 1
