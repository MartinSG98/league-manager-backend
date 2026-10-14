"""Reputation: how big a club and its manager are in the eyes of players, sponsors and boards.

A team's reputation (0-100) starts at the organisation's prestige and moves with results: a
domestic title, a final or a deep run at an international event raises it, a bottom finish
lowers it, and every off-season it drifts a tenth of the way back to the organisation's
prestige. Players weigh it before they sign (see transfers.interest), sponsors pay by it and the
board sets the budget by it.

The manager has a reputation on the same scale. It starts a little below the club that hired
them, grows with objectives met and titles won, and drops with a sacking. After a sacking only
clubs up to one and a half stars above the manager call (see board.job_offers).

Both are shown as stars: (reputation - 50) / 10, in half stars from 0.5 to 5.

A club is rated twice. World stars weigh its reputation by its league's strength, so a big name
in the LCP or CBLOL counts for less than one in the LCK. Region stars measure it against the
biggest club of its own region, who is five stars. Players look at the region stars of a club
from their own region and at the world stars of the rest; job offers go by world stars. Money
(budgets, sponsors, the board's grant) stays on the plain reputation."""

from app.game.catalog import Catalog
from app.game.state import Career, Competition

STAR_REACH = 1.5  # how far above their own stars a sacked manager can still get offers

# Placement -> reputation change.
DOMESTIC = {1: 3.0, 2: 1.5, 3: 0.6, 4: 0.6}
DOMESTIC_BOTTOM = -1.5  # the last two of a league
INTERNATIONAL = {
    "FST": {1: 5.0, 2: 3.0, 3: 1.5, 4: 1.5},
    "MSI": {1: 7.0, 2: 4.0, 3: 2.0, 4: 2.0},
    "WORLDS": {1: 12.0, 2: 7.0, 3: 4.0, 4: 4.0, 5: 2.0, 6: 2.0, 7: 2.0, 8: 2.0},
}
TAKING_PART = 0.5  # an international event, whatever the result
DRIFT = 0.1

# Manager reputation for titles, on top of what the board's objectives give.
MANAGER_TITLE = {"league": 3.0, "FST": 4.0, "MSI": 6.0, "WORLDS": 10.0}
MANAGER_SACKED = -8.0


def stars(value: float) -> float:
    return max(0.5, min(5.0, round((value - 50) / 10 * 2) / 2))


def team_reputation(cat: Catalog, career: Career, team_id: str) -> float:
    team = career.teams.get(team_id)
    if team is None or not team.reputation:
        return float(cat.teams[team_id].prestige)
    return team.reputation


def world(cat: Catalog, career: Career, team_id: str) -> float:
    """How the whole scene sees a club: its reputation weighed by its league's strength (LCK 100)."""
    strength = cat.leagues[cat.teams[team_id].league].strength
    return 50 + (team_reputation(cat, career, team_id) - 50) * strength / 100


def regional(cat: Catalog, career: Career, team_id: str) -> float:
    """How a club's own region sees it: against the region's biggest club, who sits at 100."""
    region = cat.teams[team_id].region
    top = max((team_reputation(cat, career, t) for t in career.teams if cat.teams[t].region == region),
              default=100.0)
    return min(100.0, team_reputation(cat, career, team_id) + 100 - top)


def seen_from(cat: Catalog, career: Career, team_id: str, region: str | None) -> float:
    """A club through the eyes of someone from `region`: their region's view of its own clubs, the world's of the rest."""
    return regional(cat, career, team_id) if cat.teams[team_id].region == region else world(cat, career, team_id)


def compared(cat: Catalog, career: Career, team_id: str, other: str | None, region: str | None) -> tuple[float, float]:
    """A club and another (or nobody, 0) side by side through the eyes of someone from `region`:
    on the region's scale when both are its own clubs, on the world's otherwise."""
    local = cat.teams[team_id].region == region and (other is None or cat.teams[other].region == region)
    scale = regional if local else world
    return scale(cat, career, team_id), scale(cat, career, other) if other else 0.0


def ratings(cat: Catalog, career: Career, team_id: str) -> dict:
    """Both star ratings of a club, for the views."""
    return {"world_stars": stars(world(cat, career, team_id)), "region_stars": stars(regional(cat, career, team_id)),
            "region": cat.regions[cat.teams[team_id].region].league}


def label(cat: Catalog, career: Career, team_id: str) -> str:
    """Both ratings in words, for messages: "2.5 stars worldwide, 4.5 in the LCP"."""
    r = ratings(cat, career, team_id)
    return f"{r['world_stars']:g} stars worldwide, {r['region_stars']:g} in the {r['region']}"


def starting_manager_reputation(team_reputation_value: float) -> float:
    """The board hires someone a little below the club's own standing."""
    return round(0.6 * team_reputation_value + 28, 1)


def ensure(cat: Catalog, career: Career) -> None:
    """Give every team a reputation and the manager one, for new careers and old saves alike."""
    for team in career.teams.values():
        if not team.reputation:
            team.reputation = float(cat.teams[team.id].prestige)
    if not career.manager_reputation:
        career.manager_reputation = starting_manager_reputation(career.teams[career.team].reputation)


def _event(comp: Competition) -> str:
    return comp.id.split("-", 1)[1]


def change_for(comp: Competition, place: int) -> float:
    if comp.kind == "league":
        if place in DOMESTIC:
            return DOMESTIC[place]
        return DOMESTIC_BOTTOM if place > len(comp.placements) - 2 else 0.0
    table = INTERNATIONAL.get(_event(comp), {})
    return table.get(place, 0.0) + TAKING_PART


def after_competition(cat: Catalog, career: Career, comp: Competition) -> None:
    for i, team_id in enumerate(comp.placements):
        team = career.teams.get(team_id)
        if team is None:
            continue
        team.reputation = round(max(20.0, min(100.0, team_reputation(cat, career, team_id)
                                              + change_for(comp, i + 1))), 1)
    if comp.placements and comp.placements[0] == career.team:
        key = "league" if comp.kind == "league" else _event(comp)
        change_manager(career, MANAGER_TITLE.get(key, 0.0))


def change_manager(career: Career, delta: float) -> None:
    career.manager_reputation = round(max(30.0, min(100.0, career.manager_reputation + delta)), 1)


def drift(cat: Catalog, career: Career) -> None:
    """Off-season: a tenth of the way back to what the organisation is."""
    for team in career.teams.values():
        prestige = cat.teams[team.id].prestige
        current = team_reputation(cat, career, team.id)
        team.reputation = round(current + (prestige - current) * DRIFT, 1)


def sponsor_income(cat: Catalog, career: Career, team_id: str) -> float:
    """Thousands of USD a week, on top of the salary budget the owners fund."""
    return team_reputation(cat, career, team_id) * 6 / 52
