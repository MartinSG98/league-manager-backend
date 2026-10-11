"""From Worlds to the next pre-season.

When Worlds ends the season's results go into the career history and contracts that run out
end. AI teams re-sign the players they value (most of the good ones, few of the weak ones) if
the budget allows; the manager has to extend their own players before the season ends or lose
them. Players develop: prospects grow towards their potential, long careers start to decline.
Staff sign for two seasons. When a contract ends the manager's staff renew automatically and
AI teams keep theirs about two times in three. Then every league holds a new draft, only for the
roles and staff seats teams still need, from the free agents of the region, in reverse order of
the last split's finish."""

from app.game import calendar, draft, patches, roster
from app.game import staff as staffing
from app.game.catalog import ROLES, Catalog
from app.game.ratings import ATTRIBUTES, asking_salary
from app.game.rng import Rng
from app.game.state import Career, Contract, DraftState, InboxMessage, PlayerSeason, SeasonSummary, StaffState

PROSPECT_GROWTH = 0.35  # share of the gap to potential a young player closes in an off-season
VETERAN_GAMES = 1100  # career games after which a player may start to decline


def _message(career: Career, kind: str, subject: str, body: str) -> None:
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind=kind, subject=subject, body=body))  # type: ignore[arg-type]
    career.next_message += 1


def summarise(cat: Catalog, career: Career) -> SeasonSummary:
    summary = SeasonSummary(season=career.season)
    for comp in sorted(career.competitions.values(), key=lambda c: c.start):
        if not comp.placements:
            continue
        summary.champions[comp.name] = comp.placements[0]
        if career.team in comp.placements:
            place = comp.placements.index(career.team) + 1
            summary.finishes[comp.name] = place
            if place == 1:
                summary.titles.append(comp.name)
    return summary


def expiring(career: Career, team_id: str) -> list[str]:
    team = career.teams[team_id]
    return [pid for pid in team.roster
            if career.players[pid].contract and career.players[pid].contract.until <= career.season]


def _last_split_order(cat: Catalog, career: Career, league: str) -> list[str]:
    """Teams worst first by their finish in the last split, for the draft order."""
    comp = career.competitions.get(f"{career.season}-{league}-3")
    teams = [t.id for t in cat.league_teams(league)]
    if comp and comp.placements:
        return list(reversed([t for t in comp.placements if t in teams]))
    return list(reversed(teams))


def start_next_season(cat: Catalog, career: Career, rng: Rng) -> None:
    summary = summarise(cat, career)
    career.history.append(summary)
    orders = {r.league: _last_split_order(cat, career, r.league) for r in cat.regions.values()}
    new_season = career.season + 1
    leaving: list[str] = []

    # Contracts
    for team in career.teams.values():
        for pid in list(team.roster):
            state = career.players[pid]
            if not state.contract or state.contract.until >= new_season:
                continue
            if pid == team.franchise:
                state.contract = Contract(salary=state.contract.salary, until=new_season + 2)
                continue
            if team.id != career.team and _ai_keeps(cat, career, team.id, pid, rng):
                salary = asking_salary(roster.overall(cat, career, pid), cat.players[pid].reputation, cat.teams[team.id].region)
                state.contract = Contract(salary=salary, until=new_season + 1)
                continue
            team.roster.remove(pid)
            state.team = None
            state.contract = None
            if team.id == career.team:
                leaving.append(cat.players[pid].name)
        team.lineup = _best_lineup(cat, career, team.roster)

    # Staff
    renewed, staff_left = [], []
    for sid in cat.staff:
        career.staff.setdefault(sid, StaffState(id=sid))
    for team in career.teams.values():
        for kind in ("coach", "analyst"):
            sid = getattr(team, kind)
            if not sid:
                continue
            state = career.staff[sid]
            if state.contract and state.contract.until >= new_season:
                continue
            name = cat.staff[sid].name
            if team.id == career.team or rng.chance(0.65):
                salary = state.contract.salary if state.contract else cat.staff[sid].salary
                state.contract = Contract(salary=salary, until=new_season + staffing.STAFF_YEARS - 1)
                if team.id == career.team:
                    renewed.append(name)
                continue
            setattr(team, kind, None)
            state.team = None
            state.contract = None
            if team.id == career.team:
                staff_left.append(name)

    # Development
    grew, declined = [], []
    for pid, state in career.players.items():
        player = cat.players[pid]
        games = player.experience + state.season.games
        now = roster.overall(cat, career, pid)
        change = 0.0
        if player.potential > now and games < 600:
            change = (player.potential - now) * PROSPECT_GROWTH * (0.5 + rng.next() * 0.7)
        elif games > VETERAN_GAMES:
            change = -rng.next() * 2.2
        if abs(change) >= 0.3:
            for attr in ATTRIBUTES:
                state.growth[attr] = round(state.growth.get(attr, 0.0) + change / 3.3, 2)
            if state.team == career.team and abs(change) >= 0.5:
                (grew if change > 0 else declined).append(f"{player.name} {round(change):+d}")
        state.season = PlayerSeason()
        state.form = 0.0
        state.fatigue = 0
        state.morale = 70

    # A clean slate for the calendar
    career.competitions = {}
    career.matches = {}
    career.live = None
    career.negotiations = {}
    career.season = new_season
    career.day = calendar.season_start(new_season)
    career.phase = "draft"
    career.meta.next_patch = patches.first_patch_day(new_season)

    body = []
    if summary.titles:
        body.append(f"Titles: {', '.join(summary.titles)}.")
    if leaving:
        body.append(f"Contracts ended: {', '.join(leaving)}.")
    if renewed:
        body.append(f"Staff renewed for {staffing.STAFF_YEARS} more seasons: {', '.join(renewed)}.")
    if staff_left:
        body.append(f"Staff who left: {', '.join(staff_left)}.")
    if grew:
        body.append(f"Improved: {', '.join(grew)}.")
    if declined:
        body.append(f"Declined: {', '.join(declined)}.")
    _message(career, "board", f"Welcome to the {new_season} pre-season", "\n".join(body) or "A quiet summer.")

    _setup_drafts(cat, career, orders, rng)


def _ai_keeps(cat: Catalog, career: Career, team_id: str, pid: str, rng: Rng) -> bool:
    team = career.teams[team_id]
    ratings = [roster.overall(cat, career, p) for p in team.lineup.values()] or [60]
    edge = roster.overall(cat, career, pid) - sum(ratings) / len(ratings)
    starter = pid in team.lineup.values()
    chance = 0.55 + edge * 0.04 + (0.15 if starter else -0.25)
    return rng.chance(max(0.05, min(0.9, chance)))


def _best_lineup(cat: Catalog, career: Career, members: list[str]) -> dict[str, str]:
    lineup = {}
    for role in ROLES:
        options = [p for p in members if cat.players[p].role == role]
        if options:
            lineup[role] = max(options, key=lambda p: roster.overall(cat, career, p))
    return lineup


def _setup_drafts(cat: Catalog, career: Career, orders: dict[str, list[str]], rng: Rng) -> None:
    career.drafts = {}
    for region in cat.regions.values():
        league = region.league
        teams = [career.teams[t.id] for t in cat.league_teams(league)]
        pool = sorted(draft.available(cat, career, league), key=lambda p: -p.overall)
        need = max((len(draft.open_roles(t)) for t in teams), default=0)
        top = pool[: max(1, need) * len(teams)]
        typical = sum(p.salary for p in top) / max(1, len(top))
        kinds = [k for k in ("coach", "analyst") if any(getattr(t, k) is None for t in teams)]
        for team in teams:
            prestige = cat.teams[team.id].prestige
            scale = max(0.82, min(1.18, 0.85 + 0.3 * (prestige - 60) / 40))
            open_count = len(draft.open_roles(team))
            staff_cost = draft.typical_staff_cost(cat, career, league, [k for k in kinds if getattr(team, k) is None])
            team.budget = int(round((roster.payroll(career, team) + (open_count * typical + staff_cost) * scale
                                     + typical * 0.3) / 10) * 10)
        order = orders[league]
        rounds = max(1, need) + 1 + len(kinds)
        d = DraftState(league=league, sequence=draft.snake(order, rounds), required_rounds=max(1, need),
                       optional_rounds=1, staff_rounds=kinds)
        career.drafts[league] = d
        if league != career.league:
            draft.run_until(cat, career, d, None, rng)
            draft.finish(cat, career, d)


def contract_warning(cat: Catalog, career: Career) -> None:
    """At the end of the season: tell the manager whose contracts run out."""
    names = [cat.players[p].name for p in expiring(career, career.team) if p != career.teams[career.team].franchise]
    if names:
        _message(career, "contract", "Contracts ending",
                 f"These contracts end with the season: {', '.join(names)}. Extend them from the player page "
                 "before you start the next season, or they leave as free agents.")

