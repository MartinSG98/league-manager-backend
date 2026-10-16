"""From the Worlds final to the next season.

There is only one draft, when a career starts. After that the off-season is a transfer window
(see transfers.py) that runs from the day after the Worlds final to January 16th.

When Worlds ends the season goes into the career history and the clubs plan the next one:
- AI clubs decide on the players whose contracts end with the season: they keep most of the
  good ones and few of the weak ones; the rest leave on free agency day. The manager has until
  free agency day to extend their own.
- Staff sign for two seasons. When a contract ends the manager's staff renew automatically and
  AI clubs keep theirs about two times in three.
- Players develop. Each player heads for a target: their hidden ceiling, moved up or down by how
  well they trained over the season (see training.growth_target). Players with fewer than 600
  career games close about a fifth of the gap to it each off-season, on top of what the weeks of
  training add. Past 27 a player declines every off-season, by about half a point for every year
  over 27: one point at 29, three at 33.
- Reputations drift back towards what each organisation is, the board sets next season's budgets
  and meets the manager about next season's objectives.
- Players who said the season just ended would be their last retire, and some others say the next
  one will be theirs (see retirement.py).
- A new class of rookies turns pro in every region (see rookies.py): free agents from academies,
  ERL teams and solo queue, most of them ordinary and a few of them very good.

When the window closes every club fills its empty roles and staff seats, team areas lose some of
what they had built for every new face in the lineup, and the new season is scheduled."""

from collections import Counter

from app.game import board, hiring, jobs, manager, patches, reputation, retirement, rookies, roster, training, transfers
from app.game import staff as staffing
from app.game.catalog import ROLES, Catalog
from app.game.ratings import ATTRIBUTES, asking_salary
from app.game.rng import Rng
from app.game.state import Career, Contract, InboxMessage, PlayerSeason, SeasonSummary, StaffState

PROSPECT_GROWTH = 0.25  # share of the gap to the growth target a young player closes in an off-season
DECLINE_FROM = 27  # the age after which a player loses some level every off-season ...
DECLINE = 0.5  # ... about this much for every year over it, between half and one and a half times as much
NEW_FACE_COST = 0.06  # share of a team area above 5 lost for every new starter


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


# ---------- the end of a season ----------


def start_offseason(cat: Catalog, career: Career, rng: Rng) -> None:
    career.history.append(summarise(cat, career))
    manager.record_season(career)
    career.phase = "offseason"
    new_season = career.season + 1
    retired = retirement.retire(cat, career, career.season) + retirement.unsigned(cat, career, rng)

    for team in career.teams.values():
        for pid in expiring(career, team.id):
            state = career.players[pid]
            if pid == team.franchise:
                state.contract = Contract(salary=state.contract.salary, until=new_season + 2)  # type: ignore[union-attr]
            elif team.id != career.team and _ai_keeps(cat, career, team.id, pid, rng):
                salary = asking_salary(roster.overall(cat, career, pid), cat.players[pid].reputation,
                                       cat.teams[team.id].region)
                state.contract = Contract(salary=salary, until=new_season + 1)

    renewed, staff_left = _staff_contracts(cat, career, rng, new_season)
    jobs.season_review(cat, career, rng, career.season)
    grew, declined = develop(cat, career, rng)
    reputation.drift(cat, career)
    grant = paid = 0
    for team in career.teams.values():
        team.budget = board.season_budget(cat, career, team.id)
        team.budget_moved = 0
        amount = board.transfer_grant(cat, career, team.id)
        if team.id == career.team:
            grant, paid = amount, min(amount, max(0, -team.cash))
        team.cash += amount
    if not career.board.sacked:
        board.new_season(cat, career, new_season)

    body = []
    if renewed:
        body.append(f"Staff renewed for {staffing.STAFF_YEARS} more seasons: {', '.join(renewed)}.")
    if staff_left:
        body.append(f"Staff who left: {', '.join(staff_left)}.")
    if grew:
        body.append(f"Improved: {', '.join(grew)}.")
    if declined:
        body.append(f"Declined: {', '.join(declined)}.")
    body.append(f"The board sets your salary budget for {new_season} at {career.teams[career.team].budget}k "
                f"and puts {grant}k in the bank for transfers"
                + (f", {paid}k of which pays off the club's debt." if paid else "."))
    _message(career, "board", f"Off-season {career.season}", "\n".join(body))
    contract_warning(cat, career)
    transfers.open_window(cat, career)
    retirement.announce(cat, career, rng, new_season)
    # Last, so nothing else in this call looks the new players up in a catalog that predates them.
    rookies.intake(cat, career, rng, new_season)
    _new_staff_news(cat, career, hiring.new_faces(cat, career, rng, retired, new_season))


def _staff_contracts(cat: Catalog, career: Career, rng: Rng, new_season: int) -> tuple[list[str], list[str]]:
    renewed, left = [], []
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
            if team.id == career.team:
                continue  # the manager's own staff are the manager's to extend (hiring.py)
            if rng.chance(0.65):
                salary = state.contract.salary if state.contract else cat.staff[sid].salary
                state.contract = Contract(salary=salary, until=new_season + staffing.STAFF_YEARS - 1)
                if team.id == career.team:
                    renewed.append(name)
                continue
            setattr(team, kind, None)
            state.team = None
            state.contract = None
            if team.id == career.team:
                left.append(name)
    return renewed, left


def develop(cat: Catalog, career: Career, rng: Rng) -> tuple[list[str], list[str]]:
    grew, declined = [], []
    for pid, state in career.players.items():
        if state.retired:
            continue
        player = cat.players[pid]
        games = roster.career_games(cat, career, pid)
        now = roster.overall(cat, career, pid)
        target = training.growth_target(cat, career, pid)
        change = 0.0
        over = roster.age(cat, career, pid) - DECLINE_FROM
        if over > 0:
            change = -DECLINE * over * (0.5 + rng.next())
        elif target > now and games < 600:
            change = (target - now) * PROSPECT_GROWTH * (0.5 + rng.next() * 0.7)
        if abs(change) >= 0.3:
            for attr in ATTRIBUTES:
                state.growth[attr] = round(state.growth.get(attr, 0.0) + change / 3.3, 2)
            if state.team == career.team and abs(change) >= 0.5:
                (grew if change > 0 else declined).append(f"{player.name} {round(change):+d}")
    return grew, declined


def _ai_keeps(cat: Catalog, career: Career, team_id: str, pid: str, rng: Rng) -> bool:
    team = career.teams[team_id]
    ratings = [roster.overall(cat, career, p) for p in team.lineup.values()] or [60]
    edge = roster.overall(cat, career, pid) - sum(ratings) / len(ratings)
    starter = pid in team.lineup.values()
    chance = 0.55 + edge * 0.04 + (0.15 if starter else -0.25)
    return rng.chance(max(0.05, min(0.9, chance)))


def _new_staff_news(cat: Catalog, career: Career, made: list) -> None:
    former = [f"{s.name} ({'coach' if s.kind == 'coach' else 'analyst'})" for s in made if s.former_player]
    if former:
        _message(career, "news", "Retired players turn to coaching",
                 f"New on the staff market: {', '.join(former)}. Find them under Scouting.")


def contract_warning(cat: Catalog, career: Career) -> None:
    """Tell the manager whose contracts run out on free agency day."""
    names = [cat.players[p].name for p in expiring(career, career.team) if p != career.teams[career.team].franchise]
    names += [f"{cat.staff[s].name} ({hiring.SEAT_NAMES[cat.staff[s].kind]})" for s in hiring.expiring(career)]
    if names:
        _message(career, "contract", "Contracts ending",
                 f"These contracts end on {transfers.free_agency_day(career):%d %B}: {', '.join(names)}. Extend "
                 "them from the player page before then, or they leave as free agents.")


# ---------- the start of the next one ----------


def start_new_season(cat: Catalog, career: Career, rng: Rng) -> None:
    """The window closes: fill every lineup, reset the season and move the calendar on. The
    caller schedules the season (engine.start_season)."""
    transfers.close_window(cat, career)
    arrivals = Counter(m["to"] for m in career.transfers
                       if m["to"] in career.teams and m["player"] in career.teams[m["to"]].lineup.values())
    for team in career.teams.values():
        keep = max(0.0, 1 - NEW_FACE_COST * arrivals[team.id])
        team.skills = {a: round(5 + (v - 5) * keep, 2) if v > 5 else v for a, v in team.skills.items()}
        for role in ROLES:
            if role not in team.lineup:
                options = [p for p in team.roster if cat.players[p].role == role]
                if options:
                    team.lineup[role] = max(options, key=lambda p: roster.overall(cat, career, p))
    for state in career.players.values():
        state.played += state.season.games
        state.season = PlayerSeason()
        state.form = 0.0
        state.development = []
        if state.unsettled and rng.chance(0.5):
            state.unsettled = False
        state.morale = 55 if state.unsettled else 70
        if state.promise is not None and state.promise <= career.season:
            state.promise = None
    career.competitions = {}
    career.matches = {}
    career.live = None
    career.negotiations = {}
    career.transfers = []
    career.reviewed_games = 0
    career.season += 1
    career.meta.next_patch = patches.first_patch_day(career.season)
