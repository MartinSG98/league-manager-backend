"""The shortlist: players the manager is watching, and the analyst's reports on them.

Putting a player on the shortlist sends the analyst to watch them. The report lands in the inbox
a few days later: two days for a player in the manager's league, four for one elsewhere in the
region and seven for another region, plus up to two more with a weak analyst or none.

Everything the player screens show stays visible; the report adds the analyst's judgement:
- **Potential.** Every player's real ceiling is hidden (training.ceiling). The report gives a
  range that holds it: six points either side with nobody watching, a point and a half at
  scouting 20, and a third narrower with every new report on the same player.
- **Fit.** How the player compares with the manager's starter in the role, now and at their peak.
- **The deal.** Whether they would come (transfers.interest), their contract, value, the fee their
  club asks and the salary they would want.
- **A grade.** A+ to D, from how much better than the starter they are or could become.

The analyst keeps an eye on the shortlist too: a move or free agency is worth a message, and a
player who joins the manager's club comes off it."""

from datetime import timedelta

from app.game import contracts, roster, training, transfers
from app.game import staff as staffing
from app.game.catalog import Catalog
from app.game.errors import IllegalAction
from app.game.ratings import ROLE_WEIGHTS
from app.game.rng import fnv1a
from app.game.state import Career, InboxMessage, Shortlisted

MAX_SHORTLIST = 40
WIDEST = 6.0  # half the potential range with nobody watching
NARROWEST = 1.5  # at scouting 20
GRADES = (
    (10, "A+", "A rare talent for this team. Worth almost any price."),
    (6, "A", "Would walk into the starting five. Strongly recommended."),
    (3, "B", "A clear upgrade. Recommended at the right price."),
    (0, "C", "Not better than what you have. A useful backup."),
    (-999, "D", "Not good enough for this team."),
)


def _message(career: Career, subject: str, body: str, report: dict | None = None) -> None:
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind="scouting", subject=subject,
                                     body=body, report=report))
    career.next_message += 1


def entry(career: Career, pid: str) -> Shortlisted | None:
    return next((e for e in career.shortlist if e.player == pid), None)


def scout_days(cat: Catalog, career: Career, pid: str) -> int:
    state = career.players[pid]
    league = cat.teams[state.team].league if state.team in cat.teams else cat.players[pid].league
    days = 2 if league == career.league else 4 if cat.leagues[league].region == career.region else 7
    return days + round((20 - staffing.attribute(cat, career, career.team, "scouting")) / 8)


def spread(scouting: int, reports: int) -> float:
    """Half the width of the potential range in a player's report number `reports`."""
    base = NARROWEST + (20 - scouting) / 19 * (WIDEST - NARROWEST)
    return max(0.5, base * (2 / 3) ** max(0, reports - 1))


# ---------- the manager's actions ----------


def add(cat: Catalog, career: Career, pid: str) -> Shortlisted:
    if pid not in cat.players:
        raise IllegalAction("There is no such player")
    name = cat.players[pid].name
    if career.players[pid].team == career.team:
        raise IllegalAction(f"{name} already plays for you")
    if career.players[pid].retired:
        raise IllegalAction(f"{name} has retired")
    found = entry(career, pid)
    if found:
        return found
    if len(career.shortlist) >= MAX_SHORTLIST:
        raise IllegalAction(f"The shortlist holds {MAX_SHORTLIST} players; take someone off first")
    found = Shortlisted(player=pid, added=career.day, team=career.players[pid].team)
    career.shortlist.append(found)
    request(cat, career, pid)
    return found


def remove(career: Career, pid: str) -> None:
    career.shortlist = [e for e in career.shortlist if e.player != pid]


def request(cat: Catalog, career: Career, pid: str) -> None:
    found = entry(career, pid)
    if found is None:
        raise IllegalAction("Put the player on your shortlist first")
    if found.due is not None:
        raise IllegalAction(f"The analyst is already watching {cat.players[pid].name}")
    found.due = career.day + timedelta(days=scout_days(cat, career, pid))


# ---------- every day ----------


def daily(cat: Catalog, career: Career) -> None:
    for found in list(career.shortlist):
        pid = found.player
        state = career.players[pid]
        name = cat.players[pid].name
        if state.team == career.team:
            remove(career, pid)
            continue
        if state.team != found.team:
            if state.team is None:
                _message(career, f"Shortlist: {name} is a free agent",
                         f"{name} has no club now and can be signed without a transfer fee.")
            else:
                _message(career, f"Shortlist: {name} joins {cat.teams[state.team].name}",
                         f"{name} ({cat.players[pid].role}) has moved to {cat.teams[state.team].name}.")
            found.team = state.team
        if found.due is not None and career.day >= found.due:
            found.reports += 1
            found.due = None
            found.report = report(cat, career, pid, found.reports)
            _message(career, f"Scout report: {name}", f"The analyst's report on {name}.", found.report)


# ---------- the report ----------


def report(cat: Catalog, career: Career, pid: str, number: int) -> dict:
    p = cat.players[pid]
    state = career.players[pid]
    mine = career.teams[career.team]
    overall = roster.overall(cat, career, pid)
    scouting = staffing.attribute(cat, career, career.team, "scouting")

    # A range that always holds the real ceiling, centred a little off it.
    real = training.ceiling(cat, career, pid)
    half = spread(scouting, number)
    lean = (fnv1a(f"{career.seed}|{pid}|scout|{number}") / 0xFFFFFFFF - 0.5) * 1.6 * half
    low = max(30, round(real + lean - half))
    high = min(99, round(real + lean + half))

    attributes = roster.attributes(cat, career, pid)
    weights = ROLE_WEIGHTS[p.role]
    ranked = sorted(attributes, key=lambda a: -attributes[a] - weights[a])
    weak = sorted((a for a in attributes if weights[a] >= 0.1), key=lambda a: attributes[a])

    pool = [r.champion for r in p.pool[:15]] + [c for c in state.learned if c not in {r.champion for r in p.pool[:15]}]
    champions = sorted(((c, roster.mastery(cat, career, pid, c)) for c in pool), key=lambda x: -x[1])[:3]

    season = state.season
    form = None
    if season.games:
        form = {"games": season.games, "wins": season.wins,
                "kda": round((season.kills + season.assists) / max(1, season.deaths), 2),
                "rating": round(season.rating_sum / season.games, 2)}

    starter = mine.lineup.get(p.role)
    if starter is None or starter == pid:
        score = 10.0
        fit = f"You have nobody at {p.role}: {p.name} would start."
        starter_row = None
    else:
        now = roster.overall(cat, career, starter)
        peak = max(now, cat.players[starter].potential)
        score = max(overall - now, 0.6 * ((low + high) / 2 - peak))
        starter_name = cat.players[starter].name
        starter_row = {"id": starter, "name": starter_name, "overall": now}
        if overall - now >= 3:
            fit = f"Better than {starter_name} ({now}) already: a starter."
        elif overall - now >= -1:
            fit = f"About level with {starter_name} ({now}): competition for the place."
        elif (low + high) / 2 - peak >= 3:
            fit = f"Behind {starter_name} ({now}) for now, but could pass them."
        else:
            fit = f"A backup behind {starter_name} ({now})."
    grade, verdict = next((g, v) for floor, g, v in GRADES if score >= floor)

    level, why = transfers.interest(cat, career, pid, career.team)
    asking = transfers.asking_fee(cat, career, pid)
    wage = contracts.ask(cat, career, pid).salary
    notes = []
    if level == "refuses":
        notes.append(f"{p.name} would not join you now.")
    if asking is not None and asking > mine.cash:
        notes.append(f"Their club wants about {asking}k, more than the {mine.cash}k in your bank.")
    if not transfers.window_open(career) and state.team in career.teams:
        notes.append("Players under contract can only be bought in the off-season window.")

    return {
        "kind": "player", "number": number, "day": career.day.isoformat(),
        "player": pid, "name": p.name, "photo": p.photo, "role": p.role, "team": state.team,
        "analyst": cat.staff[mine.analyst].name if mine.analyst in cat.staff else None,
        "confidence": "high" if half <= 2 else "fair" if half <= 4 else "rough",
        "overall": overall, "potential": [low, high], "peaked": high <= overall,
        "strengths": ranked[:3], "weaknesses": weak[:2],
        "champions": [[c, m] for c, m in champions],
        "form": form,
        "fit": fit, "starter": starter_row,
        "interest": level, "interest_text": why,
        "contract": {"until": state.contract.until, "salary": state.contract.salary} if state.contract else None,
        "value": transfers.market_value(cat, career, pid), "asking": asking, "wage": wage,
        "grade": grade, "verdict": verdict, "notes": notes,
    }
