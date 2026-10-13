"""The board: what it expects each season, how it judges the manager and when it lets them go.

When a manager takes a job, and again at the start of every off-season for the season after,
the board meets them with its objectives: a finish in each of the three splits and how far to
go at Worlds. The targets come from where the club's reputation ranks it in its league: the
favourite is asked for a top-two finish, the second club for a top three, everyone else for a
finish at most two places below their rank, and the easiest target is staying off the bottom.
The manager can accept each target, ask for one step less (the board trims the budget by 4
percent a step) or promise one step more (4 percent more).

Confidence (0-100, 60 for a new manager) moves when an objective is decided: up for a target
met, more for one the manager promised, down for a miss, more the bigger the miss. Titles add
on top. A new season starts confidence two-fifths of the way back to 60.

First Stand and MSI are not objectives but bonuses (see BONUSES): qualifying, and a deep run,
add confidence and manager reputation and bring a sponsor payment to the bank. Missing them
costs nothing.

The board reviews the manager after each split and after Worlds. Below 22 confidence the first
review is a warning and the next one still below it is the sack; back above 35 lifts the
warning. Nobody is warned or sacked in their first 75 days, which covers the first split of a
job. A sacked manager gets offers from clubs up to one and a half stars above their own
reputation (see reputation.py) and picks where to go next."""

from app.game import calendar, reputation
from app.game.catalog import Catalog
from app.game.errors import IllegalAction
from app.game.rng import Rng
from app.game.state import BoardState, Bonus, Career, Competition, InboxMessage, Objective

START_CONFIDENCE = 60
WARNING = 22  # below this a review is a warning, and after a warning the sack
SAFE = 35  # back above this and the warning is lifted
GRACE_DAYS = 75
BUDGET_STEP = 0.04
# id, event, place (0: qualify), confidence, manager reputation, sponsor payment as a share of the budget
BONUSES = (
    ("FST-in", "FST", 0, 4, 1.0, 0.04),
    ("FST-final", "FST", 2, 3, 1.0, 0.03),
    ("MSI-in", "MSI", 0, 4, 1.0, 0.05),
    ("MSI-top4", "MSI", 4, 3, 1.0, 0.03),
    ("MSI-final", "MSI", 2, 3, 1.0, 0.03),
)
EVENT_NAMES = {"FST": "First Stand", "MSI": "MSI"}
WORLDS_STEPS = {
    0: "Worlds would be a bonus",
    1: "Qualify for Worlds",
    2: "Reach the Worlds knockouts",
    3: "Reach the Worlds semi-finals",
    4: "Reach the Worlds final",
    5: "Win Worlds",
}


def _message(career: Career, subject: str, body: str) -> None:
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind="board", subject=subject, body=body))
    career.next_message += 1


# ---------- objectives ----------


def _league_rank(cat: Catalog, career: Career, team_id: str) -> tuple[int, int]:
    """Where the club's reputation puts it in its league (0 is the biggest), and the league size."""
    league = cat.teams[team_id].league
    teams = sorted((t.id for t in cat.league_teams(league)),
                   key=lambda t: -reputation.team_reputation(cat, career, t))
    return teams.index(team_id), len(teams)


def split_name(cat: Catalog, league: str, split: int) -> str:
    return f"{cat.leagues[league].name} {calendar.SPLIT_NAMES[league][split - 1]}"


def propose(cat: Catalog, career: Career, team_id: str, season: int) -> list[Objective]:
    rank, size = _league_rank(cat, career, team_id)
    leeway = 1 if rank < 2 else 2
    target = max(1, min(size - 1, rank + 1 + leeway))
    league = cat.teams[team_id].league
    out = []
    for split in (1, 2, 3):
        comp = career.competitions.get(f"{season}-{league}-{split}")
        if comp is not None and comp.status == "finished":
            continue  # already decided before the manager arrived
        out.append(Objective(id=f"split{split}", kind="split", split=split, target=target, proposed=target))
    region = cat.teams[team_id].region
    slots = next(e for e in calendar.INTERNATIONALS if e.id == "WORLDS").slots[region]
    if rank == 0 and region in ("KR", "CN"):
        worlds = 3
    elif rank < slots // 2 or (rank == 0 and slots >= 2):
        worlds = 2
    elif rank < slots:
        worlds = 1
    else:
        worlds = 0
    worlds_comp = career.competitions.get(f"{season}-WORLDS")
    if worlds_comp is None or worlds_comp.status != "finished":
        out.append(Objective(id="worlds", kind="worlds", target=worlds, proposed=worlds))
    return out


def describe(cat: Catalog, career: Career, obj: Objective) -> str:
    if obj.kind == "worlds":
        return WORLDS_STEPS[obj.target]
    league = cat.teams[career.team].league
    name = split_name(cat, league, obj.split or 1)
    size = len(cat.league_teams(league))
    if obj.target == 1:
        return f"Win the {name}"
    if obj.target >= size - 1:
        return f"Avoid finishing last in the {name}"
    return f"Finish in the top {obj.target} of the {name}"


def _step_bounds(cat: Catalog, career: Career, obj: Objective) -> tuple[int, int]:
    if obj.kind == "worlds":
        return 0, 5
    return 1, len(cat.league_teams(cat.teams[career.team].league)) - 1


def stance_target(cat: Catalog, career: Career, obj: Objective, stance: int) -> int:
    """The target after the manager asks for less (-1) or promises more (+1)."""
    low, high = _step_bounds(cat, career, obj)
    if obj.kind == "worlds":
        return max(low, min(high, obj.proposed + stance))
    return max(low, min(high, obj.proposed - stance))


# ---------- meetings ----------


def start_job(cat: Catalog, career: Career, season: int) -> None:
    """A new board relationship: fresh confidence and a meeting about this season's objectives."""
    career.board = BoardState(season=season, confidence=START_CONFIDENCE, joined=career.day,
                              objectives=propose(cat, career, career.team, season), meeting=True,
                              bonuses=bonuses_for(career, season))


def new_season(cat: Catalog, career: Career, season: int) -> None:
    """Off-season: the objectives for the next season, with the confidence carried over."""
    b = career.board
    b.confidence = round(b.confidence + (START_CONFIDENCE - b.confidence) * 0.4)
    b.season = season
    b.objectives = propose(cat, career, career.team, season)
    b.bonuses = bonuses_for(career, season)
    b.meeting = True


# ---------- bonuses ----------


def bonuses_for(career: Career, season: int) -> list[Bonus]:
    """The bonuses still to play for: none for an event that is already over or under way."""
    out = []
    for bid, event, place, confidence, rep, sponsors in BONUSES:
        if f"{season}-{event}" in career.competitions:
            continue
        out.append(Bonus(id=bid, event=event, place=place, confidence=confidence,  # type: ignore[arg-type]
                         reputation=rep, sponsors=sponsors))
    return out


def describe_bonus(bonus: Bonus) -> str:
    name = EVENT_NAMES[bonus.event]
    if bonus.place == 0:
        return f"Qualify for {name}"
    if bonus.place == 2:
        return f"Reach the {name} final"
    return f"Reach the {name} semi-finals"


def bonus_payment(career: Career, bonus: Bonus) -> int:
    team = career.teams[career.team]
    # A share of the budget the board set, whatever the manager moved to or from the bank.
    return int(round((team.budget + team.budget_moved) * bonus.sponsors / 10) * 10)


def _settle(career: Career, bonus: Bonus, earned: bool) -> None:
    b = career.board
    bonus.status = "earned" if earned else "missed"
    if not earned:
        return
    b.confidence = min(100, b.confidence + bonus.confidence)
    reputation.change_manager(career, bonus.reputation)
    payment = bonus_payment(career, bonus)
    career.teams[career.team].cash += payment
    b.history.append(f"{career.day.isoformat()} Bonus: {describe_bonus(bonus)}. Confidence {b.confidence}/100.")
    _message(career, f"Board bonus: {describe_bonus(bonus)}",
             f"The board is pleased: +{bonus.confidence} confidence. The sponsors pay a bonus of {payment}k into the bank.")


def event_created(cat: Catalog, career: Career, comp: Competition) -> None:
    """An international event is set: the qualification bonus is decided."""
    event = comp.id.split("-", 1)[1]
    if career.board.sacked or not comp.id.startswith(f"{career.board.season}-"):
        return
    qualified = career.team in comp.entrants
    for bonus in career.board.bonuses:
        if bonus.event != event or bonus.status != "pending":
            continue
        if bonus.place == 0:
            _settle(career, bonus, qualified)
        elif not qualified:
            bonus.status = "missed"


def _event_finished(career: Career, comp: Competition) -> None:
    event = comp.id.split("-", 1)[1]
    if not comp.id.startswith(f"{career.board.season}-"):
        return
    place = comp.placements.index(career.team) + 1 if career.team in comp.placements else 99
    for bonus in career.board.bonuses:
        if bonus.event == event and bonus.status == "pending" and bonus.place:
            _settle(career, bonus, place <= bonus.place)


def hold_meeting(cat: Catalog, career: Career, stances: dict[str, int]) -> None:
    b = career.board
    if not b.meeting:
        raise IllegalAction("There is no board meeting waiting")
    steps = 0
    lines = []
    for obj in b.objectives:
        stance = max(-1, min(1, int(stances.get(obj.id, 0))))
        obj.target = stance_target(cat, career, obj, stance)
        moved = (obj.target - obj.proposed) if obj.kind == "worlds" else (obj.proposed - obj.target)
        steps += moved
        lines.append(f"- {describe(cat, career, obj)}" + (" (you promised more)" if moved > 0 else
                                                           " (you asked for less)" if moved < 0 else ""))
    team = career.teams[career.team]
    if steps:
        team.budget = int(round(team.budget * (1 + BUDGET_STEP * steps) / 10) * 10)
    b.meeting = False
    budget_line = (f"The board {'raises' if steps > 0 else 'cuts'} the budget to {team.budget}k."
                   if steps else f"The budget stays at {team.budget}k.")
    _message(career, f"Objectives for {b.season}", "\n".join(["The board's expectations:", *lines, budget_line]))


# ---------- judging results ----------


def _decide(cat: Catalog, career: Career, obj: Objective, met: bool, delta: int, result: str) -> None:
    b = career.board
    obj.status = "met" if met else "failed"
    obj.result = result
    b.confidence = max(0, min(100, b.confidence + delta))
    promised = (obj.target - obj.proposed) if obj.kind == "worlds" else (obj.proposed - obj.target)
    reputation.change_manager(career, (1.5 + max(0, promised)) if met else -1.0)


def _worlds_reached(career: Career, comp: Competition | None) -> int:
    if comp is None or career.team not in comp.entrants:
        return 0
    if career.team not in comp.placements:
        return 1
    place = comp.placements.index(career.team) + 1
    return 5 if place == 1 else 4 if place == 2 else 3 if place <= 4 else 2 if place <= 8 else 1


def after_competition(cat: Catalog, career: Career, comp: Competition, rng: Rng) -> None:
    """Decide the objective this competition settles, then review the manager."""
    b = career.board
    if b.sacked or b.meeting or not comp.placements:
        return
    if comp.kind == "international":
        _event_finished(career, comp)
    team = career.team
    title = comp.placements[0] == team
    if title:
        b.confidence = min(100, b.confidence + (5 if comp.kind == "league" else 8))
    obj = None
    if comp.kind == "league" and comp.league == cat.teams[team].league:
        obj = next((o for o in b.objectives if o.kind == "split" and o.split == comp.split
                    and o.status == "pending" and comp.id.startswith(f"{b.season}-")), None)
        if obj is not None:
            place = comp.placements.index(team) + 1
            if place <= obj.target:
                delta = 6 + 2 * max(0, obj.proposed - obj.target) + (3 if place < obj.target else 0)
                _decide(cat, career, obj, True, delta, f"Finished {_ordinal(place)}")
            else:
                delta = -(5 + 3 * min(3, place - obj.target)) - (2 if obj.target > obj.proposed else 0)
                _decide(cat, career, obj, False, delta, f"Finished {_ordinal(place)}")
    elif comp.id == f"{b.season}-WORLDS":
        obj = next((o for o in b.objectives if o.kind == "worlds" and o.status == "pending"), None)
        if obj is not None:
            reached = _worlds_reached(career, comp)
            text = WORLDS_STEPS[reached] if reached else "Did not qualify"
            if obj.target == 0:
                _decide(cat, career, obj, True, 4 + 2 * (reached - 1) if reached else 0, text)
            elif reached >= obj.target:
                delta = 8 + 3 * (reached - obj.target) + 2 * max(0, obj.target - obj.proposed)
                _decide(cat, career, obj, True, delta, text)
            else:
                delta = -(8 + 4 * min(2, obj.target - reached)) - (2 if obj.target < obj.proposed else 0)
                _decide(cat, career, obj, False, delta, text)
    if obj is not None:
        review(cat, career, rng, obj)
    elif title:
        _message(career, "The board congratulates you", f"Winning the {comp.name} pleases the board.")


def job_security(career: Career) -> str:
    b = career.board
    if b.sacked:
        return "Sacked"
    if b.warned:
        return "Final warning"
    if b.confidence >= 70:
        return "Secure"
    if b.confidence >= 45:
        return "Stable"
    if b.confidence >= WARNING:
        return "Under pressure"
    return "At risk"


def review(cat: Catalog, career: Career, rng: Rng, obj: Objective) -> None:
    b = career.board
    verdict = "met" if obj.status == "met" else "missed"
    line = f"{describe(cat, career, obj)}: {verdict} ({obj.result}). Confidence {b.confidence}/100."
    b.history.append(f"{career.day.isoformat()} {line}")
    grace = b.joined is not None and (career.day - b.joined).days < GRACE_DAYS
    if b.confidence >= SAFE:
        b.warned = False
    if b.confidence < WARNING and not grace:
        if b.warned:
            sack(cat, career, rng)
            return
        b.warned = True
        _message(career, "The board is losing patience",
                 f"{line}\nResults have to improve. Another review like this one and the board will look "
                 "for a new manager.")
        return
    mood = ("The board is delighted." if obj.status == "met" and b.confidence >= 70 else
            "The board is satisfied." if obj.status == "met" else
            "The board is disappointed." if b.confidence >= 45 else
            "The board is worried about the direction of the team.")
    _message(career, f"Board review: {describe(cat, career, obj)}", f"{line}\n{mood}")


# ---------- the sack and a new job ----------


def sack(cat: Catalog, career: Career, rng: Rng) -> None:
    b = career.board
    b.sacked = True
    b.warned = False
    reputation.change_manager(career, reputation.MANAGER_SACKED)
    career.job_offers = job_offers(cat, career, rng)
    career.negotiations = {}
    for offer in career.offers:
        if offer.status in ("open", "agreed"):
            offer.status = "withdrawn"
            offer.note = "The manager who made it was sacked"
    for talk in career.conversations:
        talk.resolved = True
    names = ", ".join(f"{cat.teams[t].name} ({reputation.stars(reputation.team_reputation(cat, career, t)):g} stars)"
                      for t in career.job_offers)
    _message(career, f"{cat.teams[career.team].name} have sacked you",
             f"The board has lost faith in you and ends your contract.\nClubs that called your agent: {names}.\n"
             "Choose your next club to carry on.")


def job_offers(cat: Catalog, career: Career, rng: Rng, count: int = 3) -> list[str]:
    reach = reputation.stars(career.manager_reputation) + reputation.STAR_REACH
    teams = [t for t in career.teams if t != career.team]
    level = {t: reputation.team_reputation(cat, career, t) for t in teams}
    eligible = [t for t in teams if reputation.stars(level[t]) <= reach]
    if len(eligible) < count:
        eligible += sorted((t for t in teams if t not in eligible), key=lambda t: level[t])[: count - len(eligible)]
    # The bigger clubs in reach call first, with some luck in who is looking right now.
    ranked = sorted(eligible, key=lambda t: -(level[t] + rng.next() * 15))
    return ranked[:count]


def accept_job(cat: Catalog, career: Career, team_id: str) -> None:
    if team_id not in career.job_offers:
        raise IllegalAction("That club has not offered you a job")
    old = career.team
    career.teams[old].listed = []
    team = cat.teams[team_id]
    career.team = team_id
    career.region = team.region
    career.league = team.league
    career.job_offers = []
    career.negotiations = {}
    season = career.season + 1 if career.phase == "offseason" else career.season
    start_job(cat, career, season)
    stars = reputation.stars(reputation.team_reputation(cat, career, team_id))
    _message(career, f"Welcome to {team.name}",
             f"You are the new manager of {team.name} ({stars:g} stars). The board wants to meet you about "
             f"its objectives for {season}.")


# ---------- budgets ----------


def season_budget(cat: Catalog, career: Career, team_id: str) -> int:
    """What the board gives a club for next season's salaries: enough for a starting five at the
    region's going rate, a bench player and staff, scaled by the club's reputation, and never
    less than the contracts it already has."""
    from app.game import roster

    region = cat.teams[team_id].region
    clubs = len(cat.league_teams(cat.teams[team_id].league))
    ratings = sorted((roster.overall(cat, career, p.id) for p in cat.region_players(region)), reverse=True)
    top = ratings[: clubs * 5]
    from app.game.ratings import asking_salary

    typical = sum(asking_salary(r, 50, region) for r in top) / max(1, len(top))
    scale = max(0.8, min(1.25, 0.85 + 0.3 * (reputation.team_reputation(cat, career, team_id) - 60) / 40))
    staff = 2 * 40 * (1.15 if region == "CN" else 1.0)
    team = career.teams[team_id]
    committed = roster.payroll(career, team, season=career.season + 1)
    budget = (typical * 5 + typical * 0.4) * scale + staff
    return int(round(max(budget, committed * 1.03) / 10) * 10)


def transfer_grant(cat: Catalog, career: Career, team_id: str) -> int:
    """What the owners put in the bank for the transfer window: 15 percent of the salary budget
    for a one-star club, up to 35 for a five-star one."""
    stars = reputation.stars(reputation.team_reputation(cat, career, team_id))
    return int(round(career.teams[team_id].budget * (0.1 + 0.05 * stars) / 10) * 10)


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
