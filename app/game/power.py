"""Global power rankings, the way LoL Esports keeps them: an Elo for every tier-one team and one for
every region.

- A team's Elo moves with every series it plays. The winner takes points from the loser: more for
  an upset, for a longer series and for a bigger stage (K, after Riot's table).
- A region's Elo moves only on the international stage. When teams of two regions meet, the
  winner's region takes points from the loser's. Domestic series move points between the teams of
  one region and leave the region where it was, so a region rises only by beating other regions.
- A team's power score blends its own Elo and its region's, 80 to 20, as Riot's model does. The
  rankings are ordered by it.
- A region's strength is how much of what happens there the world notices (reputation.world, and
  the manager's world reputation): 100 for the strongest region, a point less for every 20 Elo
  below it.

Everything starts from the catalog's fixed league strengths (LCK 100 down to CBLOL 74) and the
clubs' reputations, so a new ranking changes nothing until the regions meet."""

from app.game.catalog import Catalog
from app.game.state import Career, Match

BASE = 1500.0  # the Elo of a region of strength 90
PER_STRENGTH = 20.0  # Elo per point of league strength, both ways
PER_REPUTATION = 5.0  # a team's Elo above its region's for every point of reputation above the region's average
TEAM_WEIGHT = 0.8  # of the power score; the rest is the region's Elo
SCALE = 400.0
REGION_PACE = 0.5  # a region moves at half the pace of its team
LOWEST = 50.0  # the least strength a region can fall to
# How much a series can move, by competition and stage, after Riot's table: play-ins least,
# international knockouts most.
K = {("league", "RS"): 16.0, ("league", "PO"): 20.0, ("international", "PI"): 12.0,
     ("international", "GR"): 20.0, ("international", "SW"): 20.0, ("international", "KO"): 36.0}


def _region_of(cat: Catalog, team_id: str) -> str:
    return cat.teams[team_id].region


def ensure(cat: Catalog, career: Career) -> bool:
    """Seed the rankings: every region at its league's strength, every team around its region by
    its reputation. Returns True when anything was seeded."""
    changed = False
    if not career.region_elo:
        for region in cat.regions.values():
            career.region_elo[region.id] = BASE + (cat.leagues[region.league].strength - 90) * PER_STRENGTH
        career.region_elo_start = dict(career.region_elo)
        changed = True
    unseeded = [t for t in career.teams.values() if not t.elo]
    if unseeded:
        for region_id, elo in career.region_elo.items():
            teams = [t for t in career.teams.values() if _region_of(cat, t.id) == region_id]
            if not teams:
                continue
            reps = {t.id: t.reputation or float(cat.teams[t.id].prestige) for t in teams}
            mean = sum(reps.values()) / len(reps)
            for t in teams:
                if not t.elo:
                    t.elo = round(elo + (reps[t.id] - mean) * PER_REPUTATION, 1)
                    t.elo_start = t.elo
        changed = True
    return changed


def new_season(career: Career) -> None:
    """Where every team and region stood when the season began, for the rankings' trend."""
    career.region_elo_start = dict(career.region_elo)
    for team in career.teams.values():
        team.elo_start = team.elo


def expected(a: float, b: float) -> float:
    """The chance the side rated `a` beats the side rated `b`."""
    return 1 / (1 + 10 ** ((b - a) / SCALE))


def k_factor(career: Career, match: Match) -> float:
    comp = career.competitions[match.competition]
    stage = match.stage.rsplit("-", 1)[-1]
    k = K.get((comp.kind, stage), 16.0)
    return k * (1 + (match.best_of - 1) / 4)  # a Bo3 counts half again, a Bo5 double


def after_series(cat: Catalog, career: Career, match: Match) -> None:
    """Move the ratings for a finished series (matchday.finish_match)."""
    if not match.winner or not match.home or not match.away:
        return
    winner = career.teams.get(match.winner)
    loser = career.teams.get(match.away if match.winner == match.home else match.home)
    if winner is None or loser is None or not winner.elo or not loser.elo:
        return
    k = k_factor(career, match)
    swing = k * (1 - expected(winner.elo, loser.elo))
    winner.elo = round(winner.elo + swing, 1)
    loser.elo = round(loser.elo - swing, 1)
    ra, rb = _region_of(cat, winner.id), _region_of(cat, loser.id)
    if ra != rb and ra in career.region_elo and rb in career.region_elo:
        moved = k * REGION_PACE * (1 - expected(career.region_elo[ra], career.region_elo[rb]))
        career.region_elo[ra] = round(career.region_elo[ra] + moved, 1)
        career.region_elo[rb] = round(career.region_elo[rb] - moved, 1)


def score(cat: Catalog, career: Career, team_id: str) -> float:
    """A team's power score: its Elo, blended with its region's."""
    team = career.teams[team_id]
    region = career.region_elo.get(_region_of(cat, team_id), team.elo)
    return TEAM_WEIGHT * team.elo + (1 - TEAM_WEIGHT) * region


def strength(career: Career, region: str, fallback: float) -> float:
    """How much of a region's results the world notices, 0-100: the strongest region is 100.
    `fallback` (the league's fixed strength) serves a career not yet ranked."""
    if region not in career.region_elo:
        return fallback
    top = max(career.region_elo.values())
    return max(LOWEST, min(100.0, 100 - (top - career.region_elo[region]) / PER_STRENGTH))


def region_order(career: Career) -> list[str]:
    """Regions from the strongest down."""
    return sorted(career.region_elo, key=lambda r: -career.region_elo[r])


def view(cat: Catalog, career: Career) -> dict:
    """The Global Rankings screen: every region and every tier-one team, strongest first."""
    from app.game.views import team_ref

    regions = []
    for rank, region_id in enumerate(region_order(career), start=1):
        league = cat.regions[region_id].league
        teams = sorted((t for t in career.teams if _region_of(cat, t) == region_id), key=lambda t: -score(cat, career, t))
        regions.append({
            "rank": rank, "region": region_id, "league": league, "name": cat.leagues[league].name,
            "logo": cat.leagues[league].logo,
            "elo": round(career.region_elo[region_id]),
            "change": round(career.region_elo[region_id] - career.region_elo_start.get(region_id, career.region_elo[region_id])),
            "strength": round(strength(career, region_id, cat.leagues[league].strength), 1),
            "best": team_ref(cat, teams[0]) if teams else None,
        })
    ranked = sorted(career.teams, key=lambda t: -score(cat, career, t))
    teams = []
    for rank, team_id in enumerate(ranked, start=1):
        team = career.teams[team_id]
        start = team.elo_start or team.elo
        region_id = _region_of(cat, team_id)
        teams.append({
            "rank": rank, "team": team_ref(cat, team_id), "region": region_id,
            "league": cat.regions[region_id].league, "score": round(score(cat, career, team_id)),
            "elo": round(team.elo), "change": round(team.elo - start), "mine": team_id == career.team,
        })
    return {"season": career.season, "regions": regions, "teams": teams}
