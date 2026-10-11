from fastapi import APIRouter, HTTPException

from app.game.catalog import ROLES, Player, get_catalog

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def _player(p: Player) -> dict:
    return {
        "id": p.id, "name": p.name, "role": p.role, "country": p.country, "league": p.league, "overall": p.overall,
        "potential": p.potential, "salary": p.salary, "signatures": list(p.signatures), "games": p.games,
        "photo": p.photo, "real_name": p.real_name,
    }


@router.get("")
def catalog() -> dict:
    cat = get_catalog()
    teams = []
    for t in cat.teams.values():
        if t.tier != 1:
            continue
        teams.append({
            "id": t.id, "name": t.name, "tag": t.tag, "league": t.league, "region": t.region, "color": t.color,
            "logo": t.logo, "prestige": t.prestige, "rank": t.rank, "wins": t.wins, "losses": t.losses,
            "franchise": _player(cat.players[t.franchise]) if t.franchise else None,
        })
    teams.sort(key=lambda t: (t["league"], t["rank"]))
    return {
        "patch": cat.patch,
        "regions": [{"id": r.id, "name": r.name, "league": r.league} for r in cat.regions.values()],
        "leagues": [
            {"id": lg.id, "name": lg.name, "full_name": lg.full_name, "region": lg.region, "tier": lg.tier,
             "logo": lg.logo, "players": sum(1 for p in cat.players.values() if p.league == lg.id)}
            for lg in cat.leagues.values()
        ],
        "teams": teams,
        "event_logos": cat.event_logos,
        "champions": [
            {"id": c.id, "name": c.name, "roles": list(c.roles), "focus": c.focus, "damage": c.damage, "cls": c.cls}
            for c in sorted(cat.champions.values(), key=lambda c: c.name)
        ],
    }


@router.get("/teams/{team_id}")
def team(team_id: str) -> dict:
    cat = get_catalog()
    t = cat.teams.get(team_id)
    if t is None:
        raise HTTPException(404, "No such team")
    region_pool = [p for p in cat.region_players(t.region) if p.id != t.franchise]
    return {
        "id": t.id, "name": t.name, "tag": t.tag, "league": t.league, "region": t.region, "color": t.color,
        "logo": t.logo, "prestige": t.prestige, "rank": t.rank, "wins": t.wins, "losses": t.losses,
        "franchise": _player(cat.players[t.franchise]) if t.franchise else None,
        "roster_2026": [_player(cat.players[pid]) | {"starter": pid in t.starters.values()} for pid in t.roster],
        "pool_size": len(region_pool),
        "pool_by_role": {r: sum(1 for p in region_pool if p.role == r) for r in ROLES},
    }
