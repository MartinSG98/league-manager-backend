"""Fetch team logos, league logos, player photos and real names from the lolesports.com API and
write app/data/lolesports.json, keyed by this game's own team, league and player ids.

    python -m scripts.fetch_lolesports

Two requests in total: every league and every team with its current roster. The key is the
public one the lolesports.com website itself sends. Only image URLs and names are stored, the
images stay on Riot's CDN.

Teams are matched by name, then by tag, preferring active teams of the same league; a few
teams go by another name there and are mapped in teams.json with a "lolesports" code. Players
are matched by name inside their matched team first, then anywhere in the same region."""

import json
import re
from datetime import date
from pathlib import Path

import httpx

from app.game.catalog import get_catalog

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "data" / "lolesports.json"
TEAMS_META = ROOT / "app" / "data" / "teams.json"
API = "https://esports-api.lolesports.com/persisted/gw"
KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"

# Our league id -> the league's name on lolesports.com, plus the international events.
LEAGUE_NAMES = {
    "LCK": "LCK", "LPL": "LPL", "LEC": "LEC", "LCS": "LCS", "CBLOL": "CBLOL", "LCP": "LCP",
    "LCKCL": "LCK Challengers", "LFL": "La Ligue Française", "PRM": "Prime League", "LES": "LES", "TCL": "TCL",
    "NLC": "NLC", "RL": "Rift Legends", "HM": "Hitpoint Masters", "LIT": "LoL Italian Tournament",
    "EBL": "Esports Balkan League", "ROL": "Road of Legends", "HLL": "Hellenic Legends League",
    "LPLOL": "Liga Portuguesa", "AL": "Arabian League", "NACL": "NACL", "LRN": "LRN", "LRS": "LRS",
    "CD": "Circuito Desafiante", "PCS": "PCS", "VCS": "VCS", "LJL": "LJL",
    "FST": "First Stand", "MSI": "MSI", "WORLDS": "Worlds",
}


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _https(url: str | None) -> str | None:
    if not url:
        return None
    return "https://" + url.split("://", 1)[1] if url.startswith("http://") else url


def get(client: httpx.Client, op: str) -> dict:
    response = client.get(f"{API}/{op}", params={"hl": "en-US"}, headers={"x-api-key": KEY})
    response.raise_for_status()
    return response.json()["data"]


def main() -> None:
    cat = get_catalog()
    overrides = {
        meta["id"]: meta["lolesports"]
        for meta in json.loads(TEAMS_META.read_text(encoding="utf-8"))["teams"].values()
        if "lolesports" in meta
    }
    with httpx.Client(timeout=60) as client:
        leagues = get(client, "getLeagues")["leagues"]
        teams = get(client, "getTeams")["teams"]

    league_logo = {lg["name"]: _https(lg["image"]) for lg in leagues}
    out_leagues = {ours: league_logo[name] for ours, name in LEAGUE_NAMES.items() if league_logo.get(name)}

    active = [t for t in teams if t["status"] == "active"]
    by_code: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for t in active:
        by_code.setdefault(t["code"].upper(), []).append(t)
        by_name.setdefault(_key(t["name"]), []).append(t)

    def pick(candidates: list[dict], league: str) -> dict | None:
        if not candidates:
            return None
        wanted = LEAGUE_NAMES.get(league)
        same = [c for c in candidates if (c.get("homeLeague") or {}).get("name") == wanted]
        return (same or candidates)[0]

    out_teams: dict[str, dict] = {}
    matched: dict[str, dict] = {}
    for team in cat.teams.values():
        found = None
        if team.id in overrides:
            found = pick(by_code.get(overrides[team.id].upper(), []), team.league)
        found = found or pick(by_name.get(_key(team.name), []), team.league)
        if found is None and team.tier == 1:
            found = pick(by_code.get(team.tag.upper(), []), team.league)
        if found is None:
            continue
        matched[team.id] = found
        out_teams[team.id] = {
            "logo": _https(found["image"]),
            "logo_alt": _https(found.get("alternativeImage")),
            "code": found["code"],
        }

    # Players: inside their own matched team first, then anywhere in the same region.
    league_region = {name: cat.leagues[ours].region for ours, name in LEAGUE_NAMES.items() if ours in cat.leagues}
    everywhere: dict[str, list[tuple[str | None, dict]]] = {}
    for t in active:
        region = league_region.get((t.get("homeLeague") or {}).get("name", ""))
        for p in t["players"]:
            everywhere.setdefault(_key(p["summonerName"]), []).append((region, p))

    out_players: dict[str, dict] = {}
    for player in cat.players.values():
        found = None
        team = matched.get(player.team)
        if team:
            found = next((p for p in team["players"] if _key(p["summonerName"]) == _key(player.name)), None)
        if found is None:
            options = everywhere.get(_key(player.name), [])
            local = [p for region, p in options if region == cat.leagues[player.league].region]
            if len(local) == 1 or (local and len({p["image"] for p in local}) == 1):
                found = local[0]
            elif len(options) == 1:
                found = options[0][1]
        if found is None or not found.get("image"):
            continue
        out_players[player.id] = {
            "photo": _https(found["image"]),
            "first_name": found.get("firstName") or None,
            "last_name": found.get("lastName") or None,
        }

    payload = {
        "source": "lolesports.com",
        "fetched": str(date.today()),
        "leagues": out_leagues,
        "teams": out_teams,
        "players": out_players,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tier_one = sum(1 for t in cat.teams.values() if t.tier == 1)
    tier_one_found = sum(1 for tid in out_teams if cat.teams[tid].tier == 1)
    print(f"leagues {len(out_leagues)}, teams {len(out_teams)} ({tier_one_found}/{tier_one} tier one), "
          f"players {len(out_players)}/{len(cat.players)}")


if __name__ == "__main__":
    main()
