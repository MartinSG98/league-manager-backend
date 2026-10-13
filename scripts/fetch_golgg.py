"""Fetch every 2026 roster, stat line and champion pool the game is built on from gol.gg and
write them to app/data/golgg_2026.json.

    python -m scripts.fetch_golgg             # rosters and season stats, about 10 minutes
    python -m scripts.fetch_golgg --careers   # plus career champion pools, about an hour more
    python -m scripts.fetch_golgg --careers --cached-only   # rebuild the file from the cache, no requests
    python -m scripts.fetch_golgg --history   # only add earlier seasons and international events, ten pages

For every league in app/data/leagues.json the script reads the standings of its roster
tournament, then each team's page for who played which role, their nationality and the
champions they played. Season stats come from one page that covers every 2026 game. Career
pools need one page per player, so they are optional. The two seasons before 2026 come from one
page each too and go under "history"; the ratings use them to judge form over three years. Each
international event since 2024 is one more page, under "international": games and wins on the
biggest stages count extra in the ratings.

Pages are cached under .cache/golgg, so a second run only fetches what is missing and an
interrupted run picks up where it stopped. Uncached requests wait a few seconds each, gol.gg
is a fan site and this is a fan project."""

import argparse
import hashlib
import html as htmllib
import json
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parent.parent
LEAGUES = ROOT / "app" / "data" / "leagues.json"
OUT = ROOT / "app" / "data" / "golgg_2026.json"
CACHE = ROOT / ".cache" / "golgg"

BASE = "https://gol.gg"
SEASON = "S16"  # 2026
HISTORY = {"2025": "S15", "2024": "S14"}  # earlier seasons' stat lines, for the ratings
# International events as gol.gg names them, with their season and year. MSI 2025 is not on gol.gg
# under any name we found, and Worlds 2026 had no stats when this was fetched.
INTERNATIONAL = {
    "MSI 2024": ("S14", "2024"),
    "Worlds Play-In 2024": ("S14", "2024"),
    "Worlds Main Event 2024": ("S14", "2024"),
    "First Stand 2025": ("S15", "2025"),
    "Worlds 2025 Play-In": ("S15", "2025"),
    "Worlds 2025 Main Event": ("S15", "2025"),
    "MSI 2026": ("S16", "2026"),
}
HEADERS = {"User-Agent": "Mozilla/5.0 (league-manager data fetch, personal fan project)"}
PAUSE = 2.5  # seconds after every uncached request
CAREER_KEEP = 15

ROLES = {"TOP": "TOP", "JUNGLE": "JNG", "MID": "MID", "ADC": "BOT", "BOT": "BOT", "SUPPORT": "SUP"}

TEAM_ROW = re.compile(
    r"""<tr><td><a href='\.\./teams/team-stats/(\d+)/[^']*' title='[^']*'>([^<]+)</a></td>(.*?)(?=<tr><td><a href='\.\./teams/|</tbody>)""",
    re.S,
)
CELL = re.compile(r"<td class='text-center'>([^<]*)</td>")
ROSTER_ROW = re.compile(
    r"""<tr><td><img src='\.\./_img/role/(\w+)\.png'[^>]*>\s*\w+</td><td>(.*?)</td>(.*?)</tr>""", re.S
)
ROSTER_PLAYER = re.compile(r"""player-stats/(\d+)/[^']*'>([^<]+)</a>""")
COUNTRY = re.compile(r"""alt='([A-Z]{2,3})'""")
TEAM_CHAMP = re.compile(r"""_img/champions_icon/(\w+)\.png'/>.*?</a><br/>\s*(\d+)</span>""", re.S)
STAT_ROW = re.compile(r"""<tr><td><a href='\./player-stats/(\d+)/[^']*' title='[^']*'>([^<]+)</a></td>(.*?)</tr>""", re.S)
STAT_CELL = re.compile(r"<td class='text-center'>(.*?)</td>", re.S)
CAREER_ROW = re.compile(
    r"""_img/champions_icon/(\w+)\.png'/>[^<]*</a></td>\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>.*?>([\d.]+)%</div>.*?</td>\s*<td[^>]*>([\d.]+|Perfect)</td>""",
    re.S,
)

# Column order of gol.gg's player list, after the name.
STAT_COLUMNS = [
    "country", "games", "winrate", "kda", "kills", "deaths", "assists", "csm", "gpm", "kp", "dmg_share",
    "gold_share", "vs_share", "dpm", "vspm", "wpm", "wcpm", "vwpm", "gd15", "csd15", "xpd15", "fb",
    "fb_victim", "pentas", "solo_kills",
]


def _num(text: str) -> float | None:
    text = text.replace("%", "").replace("&nbsp;", "").strip()
    if text in ("", "-"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


class CacheMiss(Exception):
    pass


class Fetcher:
    def __init__(self, cached_only: bool = False, pause: float = PAUSE) -> None:
        CACHE.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(headers=HEADERS, timeout=90, follow_redirects=True)
        self.fetched = 0
        self.cached_only = cached_only
        self.pause = pause

    def get(self, path: str) -> str:
        url = BASE + path
        file = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")
        if file.exists():
            return file.read_text(encoding="utf-8")
        if self.cached_only:
            raise CacheMiss(url)
        for attempt in range(4):
            try:
                response = self.client.get(url)
                response.raise_for_status()
                break
            except httpx.HTTPError as exc:
                print(f"  retry {attempt + 1} for {url}: {exc}", flush=True)
                time.sleep(15 * (attempt + 1))
        else:
            raise RuntimeError(f"gave up on {url}")
        file.write_text(response.text, encoding="utf-8")
        self.fetched += 1
        time.sleep(self.pause)
        return response.text


def _tournament(name: str) -> str:
    return quote(name)


def standings(fetcher: Fetcher, tournament: str) -> list[dict]:
    page = fetcher.get(f"/tournament/tournament-ranking/{_tournament(tournament)}/")
    teams = []
    for team_id, name, rest in TEAM_ROW.findall(page):
        cells = CELL.findall(rest)
        wins = int(cells[0]) if cells and cells[0].strip().isdigit() else 0
        losses = int(cells[1]) if len(cells) > 1 and cells[1].strip().isdigit() else 0
        teams.append({"gol_id": team_id, "name": htmllib.unescape(name.strip()), "wins": wins, "losses": losses})
    # The ranking page lists every team once; keep the first sighting in standings order.
    seen: set[str] = set()
    ordered = []
    for team in teams:
        if team["gol_id"] not in seen:
            seen.add(team["gol_id"])
            ordered.append(team)
    for rank, team in enumerate(ordered, start=1):
        team["rank"] = rank
    return ordered


def roster(fetcher: Fetcher, team_id: str, tournament: str) -> list[dict]:
    page = fetcher.get(f"/teams/team-stats/{team_id}/split-ALL/tournament-{_tournament(tournament)}/")
    players = []
    for role, who, rest in ROSTER_ROW.findall(page):
        found = ROSTER_PLAYER.search(who)
        if not found:
            continue
        country = COUNTRY.search(who)
        champions = [(champ, int(games)) for champ, games in TEAM_CHAMP.findall(rest)]
        players.append({
            "gol_id": found.group(1),
            "name": htmllib.unescape(found.group(2).strip()),
            "role": ROLES.get(role.upper(), role.upper()),
            "country": country.group(1) if country else None,
            "games": sum(games for _, games in champions),
            "champions": champions,
        })
    return players


def season_stats(fetcher: Fetcher, season: str = SEASON, tournament: str = "ALL") -> dict[str, dict]:
    page = fetcher.get(f"/players/list/season-{season}/split-ALL/tournament-{_tournament(tournament) if tournament != 'ALL' else 'ALL'}/")
    stats: dict[str, dict] = {}
    for player_id, name, rest in STAT_ROW.findall(page):
        cells = STAT_CELL.findall(rest)
        row: dict = {"name": htmllib.unescape(name.strip())}
        for column, raw in zip(STAT_COLUMNS, cells):
            if column == "country":
                code = re.search(r"<span class='d-none'>([^<]*)</span>", raw)
                row["country"] = code.group(1).strip() or None if code else None
            else:
                row[column] = _num(re.sub(r"<[^>]+>", "", raw))
        stats[player_id] = row
    return stats


def career(fetcher: Fetcher, player_id: str) -> list[dict]:
    """Champions this player has played across their whole career, most played first."""
    page = fetcher.get(f"/players/player-stats/{player_id}/season-ALL/split-ALL/tournament-ALL/")
    picks = []
    for champ, games, winrate, kda in CAREER_ROW.findall(page):
        picks.append({
            "champion": champ,
            "games": int(games),
            "winrate": float(winrate),
            "kda": 99.0 if kda == "Perfect" else float(kda),
        })
    picks.sort(key=lambda p: -p["games"])
    return picks[:CAREER_KEEP]


def save(payload: dict) -> None:
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--careers", action="store_true", help="also fetch career champion pools")
    parser.add_argument("--only", nargs="*", help="league ids to fetch, all by default")
    parser.add_argument("--cached-only", action="store_true", help="only use pages already in .cache/golgg")
    parser.add_argument("--pause", type=float, default=PAUSE, help="seconds to wait after each request")
    parser.add_argument("--history", action="store_true", help="only fetch the earlier seasons' stat lines")
    args = parser.parse_args()

    config = json.loads(LEAGUES.read_text(encoding="utf-8"))
    existing = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    if args.history:
        fetcher = Fetcher(cached_only=args.cached_only, pause=args.pause)
        existing["history"] = {year: season_stats(fetcher, season) for year, season in HISTORY.items()}
        existing["international"] = {
            name: {"year": year, "players": season_stats(fetcher, season, name)}
            for name, (season, year) in INTERNATIONAL.items()
        }
        save(existing)
        print(", ".join(f"{year}: {len(rows)} players" for year, rows in existing["history"].items()), flush=True)
        print(", ".join(f"{name}: {len(e['players'])}" for name, e in existing["international"].items()), flush=True)
        return
    payload = {
        "source": "gol.gg",
        "fetched": str(date.today()),
        "season": SEASON,
        "leagues": existing.get("leagues", {}),
        "players": existing.get("players", {}),
        "careers": existing.get("careers", {}),
        "history": existing.get("history", {}),
        "international": existing.get("international", {}),
    }
    fetcher = Fetcher(cached_only=args.cached_only, pause=args.pause)

    for league in config["leagues"]:
        if args.only and league["id"] not in args.only:
            continue
        tournament = league["roster"]
        teams = standings(fetcher, tournament)
        for team in teams:
            team["roster"] = roster(fetcher, team["gol_id"], tournament)
        payload["leagues"][league["id"]] = {"tournament": tournament, "teams": teams}
        players = sum(len(t["roster"]) for t in teams)
        print(f"{league['id']}: {len(teams)} teams, {players} players ({fetcher.fetched} pages fetched)", flush=True)
        save(payload)

    payload["players"] = season_stats(fetcher)
    print(f"season stats for {len(payload['players'])} players", flush=True)
    save(payload)

    if args.careers:
        # Tier-one players first, then the strongest tier-two leagues, so a slow or interrupted run
        # still covers the players who matter most. Everyone else keeps their 2026 champion pool.
        priority = {lg["id"]: (lg["tier"], -lg["strength"]) for lg in config["leagues"]}
        rank: dict[str, tuple[int, int]] = {}
        for league_id, entry in payload["leagues"].items():
            for team in entry["teams"]:
                for p in team["roster"]:
                    key = priority.get(league_id, (9, 0))
                    rank[p["gol_id"]] = min(rank.get(p["gol_id"], key), key)
        wanted = sorted(rank, key=lambda pid: (rank[pid], pid))
        for i, player_id in enumerate(wanted, start=1):
            if player_id in payload["careers"]:
                continue
            try:
                payload["careers"][player_id] = career(fetcher, player_id)
            except CacheMiss:
                continue
            if i % 25 == 0:
                print(f"careers {i}/{len(wanted)}", flush=True)
                save(payload)
        save(payload)
        print(f"careers for {len(payload['careers'])} players", flush=True)

    print("done", flush=True)


if __name__ == "__main__":
    main()
