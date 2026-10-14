"""The analyst's predictions: the day before every split of the manager's league and every
international event starts, a piece in the inbox on how it will finish.

The analyst ranks the teams by their power score (power.py) and their starting five, a point of
average overall worth PER_OVERALL Elo. They read it through their scouting: every team's value
moves by up to (20 - scouting) x NOISE either way, so a weak analyst gets more of it wrong. When
the manager does the scouting, it is their read."""

from datetime import timedelta

from app.game import calendar, power, roster
from app.game import staff as staffing
from app.game.catalog import Catalog
from app.game.rng import Rng
from app.game.state import Career, Competition, InboxMessage

PER_OVERALL = 25.0  # Elo a point of the starting five's average overall is worth
NOISE = 6.0  # Elo of misreading a team, both ways, for every point of scouting under 20
# How far a team is picked to go at each event, by its predicted place.
STAGES = {
    "FST": ((1, "champions"), (2, "the final"), (4, "the semi-finals"), (99, "out in the groups")),
    "MSI": ((1, "champions"), (2, "the final"), (4, "the last four"), (8, "the bracket stage"), (99, "out in the play-in")),
    "WORLDS": ((1, "champions"), (2, "the final"), (4, "the semi-finals"), (8, "the quarter-finals"),
               (16, "out in the Swiss stage"), (99, "out in the play-in")),
}


def strength(cat: Catalog, career: Career, team_id: str) -> float:
    team = career.teams[team_id]
    five = [roster.overall(cat, career, p) for p in team.lineup.values()]
    lineup = sum(five) / len(five) if five else 60.0
    return power.score(cat, career, team_id) + (lineup - 75) * PER_OVERALL


def predict(cat: Catalog, career: Career, teams: list[str], rng: Rng) -> list[str]:
    """The teams from the predicted winner down, as the manager's analyst reads them."""
    scouting = staffing.attribute(cat, career, career.team, "scouting")
    spread = max(0, 20 - scouting) * NOISE
    read = {t: strength(cat, career, t) + (rng.next() - 0.5) * 2 * spread for t in teams}
    return sorted(teams, key=lambda t: -read[t])


def _author(cat: Catalog, career: Career) -> str:
    from app.game import manager

    if manager.does(cat, career, "scouting"):
        return "Your own read"
    analyst = career.teams[career.team].analyst
    return f"{cat.staff[analyst].name}, your analyst," if analyst in cat.staff else "The club's analysts"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _stage(event: str, place: int) -> str:
    return next((label for top, label in STAGES.get(event, STAGES["WORLDS"]) if place <= top), "out early")


def _league_piece(cat: Catalog, career: Career, comp: Competition, order: list[str]) -> str:
    playoffs = calendar.FORMATS[comp.league or ""][(comp.split or 1) - 1][2]
    lines = []
    for place, team_id in enumerate(order, start=1):
        note = " - the favourites" if place == 1 else ""
        mark = "  (us)" if team_id == career.team else ""
        lines.append(f"{place}. {cat.teams[team_id].name}{note}{mark}")
        if place == playoffs and place < len(order):
            lines.append("--- the playoff line ---")
    # The dark horse: picked furthest above where its reputation ranks it.
    jumps = {t: career.teams[t].expected - (i + 1) for i, t in enumerate(order) if career.teams[t].expected}
    horse = max(jumps, key=lambda t: jumps[t], default=None)
    tail = []
    if horse and jumps[horse] >= 2:
        tail.append(f"Dark horse: {cat.teams[horse].name}, picked {_ordinal(order.index(horse) + 1)} "
                    f"though their name ranks them {_ordinal(career.teams[horse].expected)}.")
    if career.team in order:
        ours = order.index(career.team) + 1
        goal = next((o for o in career.board.objectives if o.kind == "split" and o.split == comp.split), None)
        board = f" The board asks for a top {goal.target} finish." if goal and goal.target > 1 else (
            " The board wants the title." if goal else "")
        tail.append(f"{cat.teams[career.team].name}: picked to finish {_ordinal(ours)}.{board}")
    return "\n".join(lines + ([""] + tail if tail else []))


def _event_piece(cat: Catalog, career: Career, comp: Competition, order: list[str]) -> str:
    event = comp.id.rsplit("-", 1)[-1]
    lines = []
    for place, team_id in enumerate(order, start=1):
        team = cat.teams[team_id]
        league = cat.leagues[team.league].name
        mark = "  (us)" if team_id == career.team else ""
        lines.append(f"{place}. {team.name} ({league}) - {_stage(event, place)}{mark}")
    tail = []
    if career.team in order:
        stage = _stage(event, order.index(career.team) + 1)
        verb = "win it" if stage == "champions" else f"go {stage}" if stage.startswith("out") else f"reach {stage}"
        tail.append(f"{cat.teams[career.team].name}: picked to {verb}.")
    return "\n".join(lines + ([""] + tail if tail else []))


def daily(cat: Catalog, career: Career, rng: Rng) -> None:
    """The day before a competition the manager would follow starts: the analyst's predictions."""
    for comp in sorted(career.competitions.values(), key=lambda c: c.start):
        if comp.id in career.predicted or comp.status == "finished":
            continue
        if comp.kind == "league" and comp.league != cat.teams[career.team].league:
            continue
        if not (comp.start - timedelta(days=1) <= career.day <= comp.start):
            continue
        teams = comp.entrants or (comp.stages[0].teams if comp.stages else [])
        teams = [t for t in teams if t in career.teams]
        if not teams:
            continue
        order = predict(cat, career, teams, rng)
        piece = _league_piece(cat, career, comp, order) if comp.kind == "league" else _event_piece(cat, career, comp, order)
        career.inbox.append(InboxMessage(
            id=career.next_message, day=career.day, kind="scouting", subject=f"Analyst predictions: {comp.name}",
            body=f"{_author(cat, career)} on how the {comp.name} will finish:\n\n{piece}"))
        career.next_message += 1
        career.predicted.append(comp.id)
