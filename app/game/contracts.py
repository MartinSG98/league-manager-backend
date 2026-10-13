"""Contract talks: signing free agents, extending your own players and letting players go.

Draft salaries are fixed (see draft.py). Everything after the draft is negotiated. A player
has an asking salary and a contract length they prefer. The asking salary is the market rate
for their rating, more from a club smaller than their reputation and less after a long spell
without a team; an unhappy player wants more to stay. Each player also has a hidden floor
between 86 and 97 percent of the ask. An offer at or above the floor is accepted, one within
reach gets a counter halfway between offer and ask, and three failed rounds, or an offer
under 60 percent, end the talks for three weeks. Every year away from the preferred length
counts as 5 percent off the offer.

Players also look at the club (see transfers.interest): one far above the club's reputation will
not talk at all, a reluctant one asks 15 percent more. A player under contract elsewhere can only
be talked to once their club has accepted a transfer fee; signing them pays the fee."""

from dataclasses import dataclass
from datetime import timedelta

from app.game import reputation, roster
from app.game.catalog import ROLES, Catalog
from app.game.errors import IllegalAction
from app.game.ratings import asking_salary
from app.game.rng import fnv1a
from app.game.state import Career, Contract, InboxMessage, Negotiation

MAX_ROSTER = 8
MAX_YEARS = 3
MAX_ROUNDS = 3
WALK_AWAY = timedelta(days=21)


@dataclass(frozen=True)
class Ask:
    salary: int
    years: int
    floor: int  # hidden: the lowest salary at the preferred length that gets a yes


def _flexibility(pid: str, season: int) -> float:
    return 0.86 + 0.11 * (fnv1a(f"{pid}|{season}|flex") / 0xFFFFFFFF)


def ask(cat: Catalog, career: Career, pid: str) -> Ask:
    from app.game import transfers

    player = cat.players[pid]
    state = career.players[pid]
    team = cat.teams[career.team]
    rating = roster.overall(cat, career, pid)
    salary = asking_salary(rating, player.reputation, team.region)
    salary *= 1 + max(-0.1, (player.reputation - reputation.team_reputation(cat, career, career.team)) / 250)
    salary *= transfers.reluctance_premium(transfers.interest(cat, career, pid, career.team)[0])
    if state.team == career.team:
        salary *= 1 + (70 - state.morale) / 200
    elif state.team is None and career.phase == "season":
        salary *= 0.9  # out of a job mid-season, a little easier to sign
    if player.potential - rating >= 6:
        years = 3
    elif player.experience > 900:
        years = 1
    else:
        years = 2
    salary = int(round(salary / 5) * 5)
    return Ask(salary=salary, years=years, floor=int(salary * _flexibility(pid, career.season)))


def committed(career: Career, team) -> int:
    """Payroll the budget is measured against: next season's contracts during the off-season."""
    return roster.payroll(career, team, season=career.season + 1 if career.phase == "offseason" else None)


def _current(career: Career, pid: str, kind: str) -> int:
    """The salary an extension replaces, if it still counts against the budget."""
    contract = career.players[pid].contract
    if kind != "extend" or contract is None or career.phase == "offseason":
        return 0
    return contract.salary


def _talks(career: Career, pid: str, kind: str) -> Negotiation:
    talks = career.negotiations.get(pid)
    if talks is None or talks.kind != kind:
        talks = Negotiation(player=pid, kind=kind)  # type: ignore[arg-type]
        career.negotiations[pid] = talks
    return talks


def kind_of(career: Career, pid: str) -> str:
    return "extend" if career.players[pid].team == career.team else "sign"


def check_can_talk(cat: Catalog, career: Career, pid: str) -> str | None:
    from app.game import transfers

    if pid not in cat.players:
        return "Unknown player"
    state = career.players[pid]
    if state.retired:
        return f"{cat.players[pid].name} has retired"
    if career.live is not None:
        return "Not during a match"
    if career.board.sacked:
        return "You have no club right now"
    if state.team not in (None, career.team) and transfers.agreed(career, pid) is None:
        return f"{cat.players[pid].name} is under contract with another team"
    if state.team != career.team:
        level, why = transfers.interest(cat, career, pid, career.team)
        if level == "refuses":
            return why
    if state.team is None and career.phase == "draft":
        return "Free agents can be signed once the draft is over"
    talks = career.negotiations.get(pid)
    if talks and talks.blocked_until and career.day < talks.blocked_until:
        return f"{cat.players[pid].name} does not want to talk until {talks.blocked_until:%d %B}"
    if state.team != career.team:
        team = career.teams[career.team]
        if len(team.roster) >= MAX_ROSTER:
            return f"Your roster is full ({MAX_ROSTER} players), release someone first"
    if state.team == career.team and state.contract and state.contract.until > career.season:
        return f"{cat.players[pid].name} is signed beyond this season already"
    return None


def offer(cat: Catalog, career: Career, pid: str, salary: int, years: int) -> Negotiation:
    problem = check_can_talk(cat, career, pid)
    if problem:
        raise IllegalAction(problem)
    if not 1 <= years <= MAX_YEARS:
        raise IllegalAction(f"Contracts run one to {MAX_YEARS} seasons")
    if salary <= 0:
        raise IllegalAction("Offer a salary")
    kind = kind_of(career, pid)
    team = career.teams[career.team]
    current = _current(career, pid, kind)
    if committed(career, team) - current + salary > team.budget:
        raise IllegalAction("That salary does not fit your budget")
    talks = _talks(career, pid, kind)
    want = ask(cat, career, pid)
    effective = salary * (1 - 0.05 * abs(years - want.years))
    name = cat.players[pid].name
    talks.rounds += 1
    if effective >= want.floor:
        _sign(cat, career, pid, salary, years)
        talks.counter = None
        talks.message = f"{name} accepts: {salary}k a season for {years} season{'s' if years > 1 else ''}."
        return talks
    if effective < 0.6 * want.salary or talks.rounds >= MAX_ROUNDS:
        talks.blocked_until = career.day + WALK_AWAY
        talks.counter = None
        talks.rounds = 0
        talks.message = f"{name}'s agent ends the talks. Try again after {talks.blocked_until:%d %B}."
        return talks
    counter = max(want.floor, int(round((salary + want.salary) / 2 / 5) * 5))
    talks.counter = counter
    talks.counter_years = want.years
    talks.message = f"{name} wants {counter}k a season over {want.years} season{'s' if want.years > 1 else ''}."
    return talks


def accept_counter(cat: Catalog, career: Career, pid: str) -> Negotiation:
    talks = career.negotiations.get(pid)
    if talks is None or talks.counter is None:
        raise IllegalAction("There is no counter-offer on the table")
    problem = check_can_talk(cat, career, pid)
    if problem:
        raise IllegalAction(problem)
    team = career.teams[career.team]
    current = _current(career, pid, talks.kind)
    if committed(career, team) - current + talks.counter > team.budget:
        raise IllegalAction("That salary does not fit your budget")
    _sign(cat, career, pid, talks.counter, talks.counter_years or 2)
    talks.message = f"{cat.players[pid].name} signs for {talks.counter}k a season."
    talks.counter = None
    return talks


def _sign(cat: Catalog, career: Career, pid: str, salary: int, years: int) -> None:
    from app.game import transfers

    bought = transfers.complete_purchase(cat, career, pid)
    state = career.players[pid]
    team = career.teams[career.team]
    first = career.season if career.phase != "offseason" else career.season + 1
    state.contract = Contract(salary=salary, until=first + years - 1)
    if state.team != career.team:
        state.team = career.team
        team.roster.append(pid)
        role = cat.players[pid].role
        team.lineup.setdefault(role, pid)
        state.morale = max(state.morale, 75)
        subject = f"{cat.players[pid].name} joins {cat.teams[career.team].name}"
        if bought:
            subject += f" from {cat.teams[bought.seller].name} for {bought.fee}k"
    else:
        state.morale = min(100, state.morale + 8)
        subject = f"{cat.players[pid].name} signs a new contract"
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind="contract", subject=subject,
                                     body=f"{salary}k a season until the end of {state.contract.until}."))
    career.next_message += 1


def release(cat: Catalog, career: Career, pid: str) -> int:
    """Let a player go. The club pays half of what is left on the contract. Returns the cost."""
    team = career.teams[career.team]
    if pid not in team.roster:
        raise IllegalAction("That player is not on your roster")
    if career.live is not None:
        raise IllegalAction("Not during a match")
    if pid == team.franchise:
        raise IllegalAction("The board will not let the franchise player go")
    role = cat.players[pid].role
    if team.lineup.get(role) == pid:
        backup = next((p for p in team.roster if p != pid and cat.players[p].role == role), None)
        if backup is None:
            raise IllegalAction(f"Sign another {role} before releasing your only one")
        team.lineup[role] = backup
    state = career.players[pid]
    seasons_left = (state.contract.until - career.season + 1) if state.contract else 0
    cost = int((state.contract.salary if state.contract else 0) * max(0, seasons_left) * 0.5)
    team.cash -= cost
    team.roster.remove(pid)
    state.team = None
    state.contract = None
    state.morale = 60
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind="contract",
                                     subject=f"{cat.players[pid].name} released",
                                     body=f"Severance paid: {cost}k."))
    career.next_message += 1
    return cost


def negotiation_view(cat: Catalog, career: Career, pid: str) -> dict:
    from app.game import transfers

    want = ask(cat, career, pid)
    talks = career.negotiations.get(pid)
    team = career.teams[career.team]
    kind = kind_of(career, pid)
    current = _current(career, pid, kind)
    level, why = transfers.interest(cat, career, pid, career.team)
    # The agent's opening line gives a range, never the floor itself.
    return {
        "player": pid,
        "kind": kind,
        "asking": want.salary,
        "years": want.years,
        "hint": f"The agent is looking for around {want.salary}k a season over {want.years} "
                f"season{'s' if want.years > 1 else ''}.",
        "problem": check_can_talk(cat, career, pid),
        "budget_room": team.budget - committed(career, team) + current,
        "interest": level,
        "interest_text": why,
        "rounds_left": MAX_ROUNDS - (talks.rounds if talks else 0),
        "counter": talks.counter if talks else None,
        "counter_years": talks.counter_years if talks else None,
        "message": talks.message if talks else "",
        "roles_needed": [r for r in ROLES if r not in team.lineup],
    }
