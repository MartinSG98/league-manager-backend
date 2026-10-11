"""The pre-season draft: players first, then staff.

Every tier-one team keeps only its franchise player. Everyone else from that region's tier-one
league and its tier-two leagues goes into one pool, and the teams take turns picking from it in
snake order, the weakest 2026 team first. The first four rounds fill the starting five, so a
team can only pick a role it still needs; two optional bench rounds follow where a team may
pass. Then come two staff rounds in the same snake order: one for an assistant coach and one for
an analyst (see staff.py). Salaries are fixed at the asking price and every pick has to leave
enough budget to fill the remaining roles and staff seats with the cheapest options left."""

from app.game import roster
from app.game import staff as staffing
from app.game.catalog import ROLES, Catalog, Player
from app.game.errors import IllegalAction
from app.game.rng import Rng
from app.game.staff import Staff
from app.game.state import Career, Contract, DraftPick, DraftState, InboxMessage, TeamState

REQUIRED_ROUNDS = 4
OPTIONAL_ROUNDS = 2
STAFF_ROUNDS = ["coach", "analyst"]
STARTER_YEARS = 2  # seasons a drafted starter signs for
BENCH_YEARS = 1
FRANCHISE_YEARS = 3
STAFF_NAMES = {"coach": "assistant coach", "analyst": "analyst"}


# ---------- setup ----------


def setup(cat: Catalog, career: Career) -> None:
    """Strip every tier-one roster to its franchise player, set budgets and build each draft."""
    for region in cat.regions.values():
        league = region.league
        teams = cat.league_teams(league)
        for team in teams:
            state = TeamState(id=team.id, league=league)
            if team.franchise:
                player = cat.players[team.franchise]
                state.franchise = team.franchise
                state.roster = [team.franchise]
                state.lineup = {player.role: team.franchise}
                career.players[team.franchise].team = team.id
                career.players[team.franchise].contract = Contract(
                    salary=player.salary, until=career.season + FRANCHISE_YEARS - 1
                )
            career.teams[team.id] = state
        _set_budgets(cat, career, league)
        order = [t.id for t in sorted(teams, key=lambda t: -t.rank)]
        career.drafts[league] = DraftState(
            league=league, sequence=snake(order, REQUIRED_ROUNDS + OPTIONAL_ROUNDS + len(STAFF_ROUNDS)),
            required_rounds=REQUIRED_ROUNDS, optional_rounds=OPTIONAL_ROUNDS, staff_rounds=list(STAFF_ROUNDS),
        )


def snake(order: list[str], rounds: int) -> list[str]:
    sequence: list[str] = []
    for rnd in range(rounds):
        sequence += order if rnd % 2 == 0 else list(reversed(order))
    return sequence


def typical_staff_cost(cat: Catalog, career: Career, league: str, kinds: list[str]) -> float:
    """What a team pays for an average pick from the staff pool, for each kind it still needs."""
    region = cat.leagues[league].region
    teams = len(cat.league_teams(league))
    total = 0.0
    for kind in kinds:
        pool = sorted((s for s in available_staff(cat, career, league, kind)), key=lambda s: -s.overall)[:teams]
        total += sum(s.salary for s in pool) / max(1, len(pool))
    return total


def _set_budgets(cat: Catalog, career: Career, league: str) -> None:
    """Enough to buy an average draft class: the four picks a team would get if everyone took
    the best player left, a bench player and average staff, scaled by how big the organisation is."""
    teams = [career.teams[t.id] for t in cat.league_teams(league)]
    pool = sorted(available(cat, career, league), key=lambda p: -p.overall)
    top = pool[: REQUIRED_ROUNDS * len(teams)]
    typical = sum(p.salary for p in top) / max(1, len(top))
    bench = sorted(p.salary for p in pool[: len(pool) // 2])
    bench_cost = bench[len(bench) // 3] if bench else 30
    staff_cost = typical_staff_cost(cat, career, league, STAFF_ROUNDS)
    for state in teams:
        prestige = cat.teams[state.id].prestige
        scale = max(0.82, min(1.18, 0.85 + 0.3 * (prestige - 60) / 40))
        franchise = career.players[state.franchise].contract.salary if state.franchise else 0
        state.budget = int(round((franchise + (REQUIRED_ROUNDS * typical + staff_cost) * scale + bench_cost) / 10) * 10)
        state.cash = int(state.budget * 0.25)


# ---------- the pool ----------


def available(cat: Catalog, career: Career, league: str) -> list[Player]:
    region = cat.leagues[league].region
    return [p for p in cat.region_players(region) if career.players[p.id].team is None]


def available_staff(cat: Catalog, career: Career, league: str, kind: str | None = None) -> list[Staff]:
    region = cat.leagues[league].region
    return [s for s in staffing.region_staff(cat, region, kind)  # type: ignore[arg-type]
            if s.id in career.staff and career.staff[s.id].team is None]


def open_roles(team: TeamState) -> list[str]:
    return [r for r in ROLES if r not in team.lineup]


def budget_left(career: Career, team: TeamState) -> int:
    return team.budget - roster.payroll(career, team)


def reserve(cat: Catalog, career: Career, league: str, roles: list[str], skip: str | None = None) -> int:
    """What the cheapest players still available would cost to fill these roles."""
    cheapest: dict[str, int] = {}
    for p in available(cat, career, league):
        if p.id != skip and p.role in roles:
            cheapest[p.role] = min(cheapest.get(p.role, p.salary), p.salary)
    return sum(cheapest.get(r, 0) for r in roles)


def staff_needed(draft: DraftState, team: TeamState) -> list[str]:
    """Staff seats this team still has to fill in this draft's staff rounds still to come."""
    first = draft.required_rounds + draft.optional_rounds + 1
    upcoming = [kind for i, kind in enumerate(draft.staff_rounds) if first + i >= draft.round]
    return [kind for kind in upcoming if getattr(team, kind) is None]


def staff_reserve(cat: Catalog, career: Career, draft: DraftState, kinds: list[str], skip: str | None = None) -> int:
    """What the cheapest staff still available would cost for these seats."""
    total = 0
    for kind in kinds:
        prices = [s.salary for s in available_staff(cat, career, draft.league, kind) if s.id != skip]
        total += min(prices, default=0)
    return total


def is_required_round(draft: DraftState) -> bool:
    return draft.round <= draft.required_rounds


def check_pick(cat: Catalog, career: Career, draft: DraftState, team: TeamState, player: Player) -> str | None:
    """Why this pick is not allowed, or None if it is."""
    if draft.round_kind != "player":
        return f"This round is for an {STAFF_NAMES[draft.round_kind]}"
    if career.players[player.id].team is not None:
        return f"{player.name} has already been drafted"
    if cat.leagues[player.league].region != cat.leagues[draft.league].region:
        return f"{player.name} is not in this region's pool"
    needed = open_roles(team)
    if is_required_round(draft) and player.role not in needed:
        return f"You still need a {', '.join(needed)} before you can draft a second {player.role}"
    others = [r for r in needed if r != player.role]
    left = budget_left(career, team)
    later = staff_reserve(cat, career, draft, staff_needed(draft, team))
    if player.salary + reserve(cat, career, draft.league, others, skip=player.id) + later > left:
        if player.salary > left:
            return f"{player.name} asks {player.salary}k, you have {left}k left"
        still = ", ".join(others + [STAFF_NAMES[k] for k in staff_needed(draft, team)])
        return f"{player.name} fits the budget but would leave too little to fill {still}"
    return None


def check_staff_pick(cat: Catalog, career: Career, draft: DraftState, team: TeamState, person: Staff) -> str | None:
    kind = draft.round_kind
    if kind == "player":
        return "Staff are drafted after the players"
    if person.kind != kind:
        return f"This round is for an {STAFF_NAMES[kind]}"
    if person.id not in career.staff or career.staff[person.id].team is not None:
        return f"{person.name} has already been hired"
    if person.region != cat.leagues[draft.league].region:
        return f"{person.name} works in another region"
    if getattr(team, kind) is not None:
        return f"You already have an {STAFF_NAMES[kind]}"
    left = budget_left(career, team)
    others = [k for k in staff_needed(draft, team) if k != kind]
    if person.salary + staff_reserve(cat, career, draft, others, skip=person.id) > left:
        if person.salary > left:
            return f"{person.name} asks {person.salary}k, you have {left}k left"
        return f"{person.name} fits the budget but would leave too little for an {STAFF_NAMES[others[0]]}"
    return None


def idle_turn(draft: DraftState, team: TeamState) -> bool:
    """A staff round for a seat the team has already filled: nothing to decide, the turn passes."""
    kind = draft.round_kind
    return kind != "player" and getattr(team, kind) is not None


# ---------- picking ----------


def make_pick(cat: Catalog, career: Career, draft: DraftState, team_id: str, player_id: str | None) -> DraftPick:
    if draft.done:
        raise IllegalAction("The draft is over")
    if draft.on_the_clock != team_id:
        raise IllegalAction("It is not this team's pick")
    team = career.teams[team_id]
    pick = DraftPick(number=draft.number + 1, round=draft.round, team=team_id, player=None)
    if player_id is None:
        if is_required_round(draft) and open_roles(team):
            raise IllegalAction("You can only pass in the bench rounds")
        if draft.round_kind != "player" and not idle_turn(draft, team):
            raise IllegalAction(f"Every team needs an {STAFF_NAMES[draft.round_kind]}")
    else:
        player = cat.players.get(player_id)
        if player is None:
            raise IllegalAction("Unknown player")
        problem = check_pick(cat, career, draft, team, player)
        if problem:
            raise IllegalAction(problem)
        starter = player.role not in team.lineup
        state = career.players[player_id]
        state.team = team_id
        years = STARTER_YEARS if starter else BENCH_YEARS
        state.contract = Contract(salary=player.salary, until=career.season + years - 1)
        team.roster.append(player_id)
        if starter:
            team.lineup[player.role] = player_id
        pick.player = player_id
        pick.salary = player.salary
    draft.picks.append(pick)
    return pick


def hire(career: Career, team: TeamState, person: Staff) -> None:
    career.staff[person.id].team = team.id
    career.staff[person.id].contract = Contract(salary=person.salary, until=career.season + staffing.STAFF_YEARS - 1)
    setattr(team, person.kind, person.id)


def make_staff_pick(cat: Catalog, career: Career, draft: DraftState, team_id: str, staff_id: str,
                    force: bool = False) -> DraftPick:
    if draft.done:
        raise IllegalAction("The draft is over")
    if draft.on_the_clock != team_id:
        raise IllegalAction("It is not this team's pick")
    person = cat.staff.get(staff_id)
    if person is None:
        raise IllegalAction("Unknown staff member")
    team = career.teams[team_id]
    problem = check_staff_pick(cat, career, draft, team, person)
    if problem and not force:
        raise IllegalAction(problem)
    hire(career, team, person)
    if force:
        team.budget = max(team.budget, roster.payroll(career, team))
    pick = DraftPick(number=draft.number + 1, round=draft.round, team=team_id, player=None, staff=staff_id,
                     salary=person.salary)
    draft.picks.append(pick)
    return pick


def choose(cat: Catalog, career: Career, draft: DraftState, team_id: str, rng: Rng) -> str | None:
    """The assistant's pick for a team: the most value it can afford, with an eye on chemistry.
    In a staff round it is a staff id."""
    if draft.round_kind != "player":
        return choose_staff(cat, career, draft, team_id, rng)
    team = career.teams[team_id]
    needed = open_roles(team)
    required = is_required_round(draft) and bool(needed)
    left = budget_left(career, team)
    best: tuple[float, str] | None = None
    for player in available(cat, career, draft.league):
        if required and player.role not in needed:
            continue
        if not required and player.role in team.lineup and _has_backup(cat, team, player.role):
            continue
        if check_pick(cat, career, draft, team, player):
            continue
        value = _value(cat, career, team, player, left)
        if not required:
            starter = cat.players[team.lineup[player.role]] if player.role in team.lineup else None
            if starter and (player.overall < starter.overall - 14 or player.salary > 0.35 * left):
                continue
        value += (rng.next() - 0.5) * 3
        if best is None or value > best[0]:
            best = (value, player.id)
    if best is None:
        if required:
            return _emergency(cat, career, draft, team)
        return None
    return best[1]


def choose_staff(cat: Catalog, career: Career, draft: DraftState, team_id: str, rng: Rng) -> str | None:
    team = career.teams[team_id]
    if idle_turn(draft, team):
        return None
    kind = draft.round_kind
    best: tuple[float, str] | None = None
    for person in available_staff(cat, career, draft.league, kind):
        if check_staff_pick(cat, career, draft, team, person):
            continue
        value = person.overall - 60 * person.salary / max(1, team.budget) + (rng.next() - 0.5) * 6
        if best is None or value > best[0]:
            best = (value, person.id)
    if best:
        return best[1]
    pool = available_staff(cat, career, draft.league, kind)
    return min(pool, key=lambda s: s.salary).id if pool else None


def _has_backup(cat: Catalog, team: TeamState, role: str) -> bool:
    return sum(1 for pid in team.roster if cat.players[pid].role == role) >= 2


def _value(cat: Catalog, career: Career, team: TeamState, player: Player, left: int) -> float:
    value = float(player.overall) + max(0, player.potential - player.overall) * 0.12
    spoken = roster.languages(cat, player)
    mates = [cat.players[pid] for pid in team.lineup.values()]
    silent = sum(1 for mate in mates if not (roster.languages(cat, mate) & spoken))
    value -= 1.2 * silent
    value += sum(0.8 for mate in mates if mate.team == player.team)  # 2026 teammates come as a package
    value -= 5 * player.salary / max(1, team.budget)  # the same rating for less money is better
    return value


def _emergency(cat: Catalog, career: Career, draft: DraftState, team: TeamState) -> str | None:
    """No affordable player fits, so the cheapest one in a needed role it is."""
    needed = open_roles(team)
    pool = [p for p in available(cat, career, draft.league) if p.role in needed]
    if not pool:
        return None
    return min(pool, key=lambda p: p.salary).id


def force_pick(cat: Catalog, career: Career, draft: DraftState, team_id: str, player_id: str) -> DraftPick:
    """Sign a player outside the budget rules, only for emergencies when nothing else fits."""
    team = career.teams[team_id]
    player = cat.players[player_id]
    state = career.players[player_id]
    state.team = team_id
    state.contract = Contract(salary=player.salary, until=career.season + STARTER_YEARS - 1)
    team.roster.append(player_id)
    team.lineup.setdefault(player.role, player_id)
    team.budget = max(team.budget, roster.payroll(career, team))
    pick = DraftPick(number=draft.number + 1, round=draft.round, team=team_id, player=player_id, salary=player.salary)
    draft.picks.append(pick)
    return pick


def auto_pick(cat: Catalog, career: Career, draft: DraftState, rng: Rng) -> DraftPick:
    team_id = draft.on_the_clock
    assert team_id is not None
    team = career.teams[team_id]
    choice = choose(cat, career, draft, team_id, rng)
    if choice is None:
        # Nothing left that fits, or nothing to decide: an empty turn, finish() fills any gap.
        pick = DraftPick(number=draft.number + 1, round=draft.round, team=team_id, player=None)
        draft.picks.append(pick)
        return pick
    if draft.round_kind != "player":
        forced = bool(check_staff_pick(cat, career, draft, team, cat.staff[choice]))
        return make_staff_pick(cat, career, draft, team_id, choice, force=forced)
    if check_pick(cat, career, draft, team, cat.players[choice]):
        return force_pick(cat, career, draft, team_id, choice)
    return make_pick(cat, career, draft, team_id, choice)


def pass_idle(draft: DraftState, career: Career, team_id: str) -> None:
    """Skip the team's turns in staff rounds for seats it has already filled."""
    while not draft.done and draft.on_the_clock == team_id and idle_turn(draft, career.teams[team_id]):
        draft.picks.append(DraftPick(number=draft.number + 1, round=draft.round, team=team_id, player=None))


def run_until(cat: Catalog, career: Career, draft: DraftState, stop_at: str | None, rng: Rng) -> list[DraftPick]:
    """Let the AI pick until it is `stop_at`'s turn or the draft ends."""
    made = []
    while not draft.done:
        if stop_at is not None:
            pass_idle(draft, career, stop_at)
        if draft.done or draft.on_the_clock == stop_at:
            break
        made.append(auto_pick(cat, career, draft, rng))
    return made


# ---------- after the draft ----------


def finish(cat: Catalog, career: Career, draft: DraftState) -> None:
    for t in cat.league_teams(draft.league):
        team = career.teams[t.id]
        for role in open_roles(team):
            pool = [p for p in available(cat, career, draft.league) if p.role == role]
            if pool:
                force_pick(cat, career, draft, t.id, min(pool, key=lambda p: p.salary).id)
        for kind in draft.staff_rounds:
            if getattr(team, kind) is None:
                pool = available_staff(cat, career, draft.league, kind)
                if pool:
                    hire(career, team, min(pool, key=lambda s: s.salary))
                    team.budget = max(team.budget, roster.payroll(career, team))


def summary(cat: Catalog, career: Career, draft: DraftState, team_id: str) -> InboxMessage:
    team = career.teams[team_id]
    lines = []
    for role in ROLES:
        pid = team.lineup.get(role)
        if pid:
            p = cat.players[pid]
            lines.append(f"{role} {p.name} ({p.overall}, {career.players[pid].contract.salary}k)")
    bench = [cat.players[pid].name for pid in team.roster if pid not in team.lineup.values()]
    body = "\n".join(lines)
    if bench:
        body += f"\nBench: {', '.join(bench)}"
    for kind in ("coach", "analyst"):
        sid = getattr(team, kind)
        if sid:
            person = cat.staff[sid]
            body += f"\n{STAFF_NAMES[kind].capitalize()}: {person.name} ({person.overall}, {person.salary}k)"
    body += f"\nPayroll {roster.payroll(career, team)}k of a {team.budget}k budget."
    message = InboxMessage(id=career.next_message, day=career.day, kind="draft",
                           subject=f"{cat.leagues[draft.league].name} draft complete", body=body)
    career.next_message += 1
    return message
