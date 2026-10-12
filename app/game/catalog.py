"""Static world data: regions, leagues, teams, players and champions as they stood at the end
of the 2026 season.

Everything here is read once from app/data and never changes during a career; what does change
(contracts, form, progression) lives on the career state. Player ratings are worked out from the
gol.gg stat lines when the catalog loads (see ratings.py), so retuning them needs no rebuild."""

import json
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.game.staff import Staff

DATA = Path(__file__).resolve().parent.parent / "data"

Role = Literal["TOP", "JNG", "MID", "BOT", "SUP"]
ROLES: tuple[Role, ...] = ("TOP", "JNG", "MID", "BOT", "SUP")


def champ_key(name: str) -> str:
    """Comparable key for a champion id or name, so gol.gg's `KhaZix` meets Data Dragon's `Khazix`."""
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return _CHAMP_ALIASES.get(key, key)


_CHAMP_ALIASES = {"wukong": "monkeyking", "renataglasc": "renata", "nunuwillump": "nunu"}


@dataclass(frozen=True)
class Champion:
    id: str  # Data Dragon id, also the image name
    name: str
    roles: tuple[Role, ...]  # first one is the main role
    focus: Literal["early", "mid", "late"]
    damage: Literal["AD", "AP", "MX"]
    cls: str
    presence: float  # share of 2026 pro drafts it was picked or banned in, 0-100
    winrate: float


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    league: str  # its tier-one league


@dataclass(frozen=True)
class League:
    id: str
    name: str
    full_name: str
    region: str
    tier: int
    strength: int  # 100 = LCK, drives the rating baseline of everyone who played there
    logo: str | None = None


@dataclass(frozen=True)
class ChampionRecord:
    champion: str  # champion id
    games: int
    winrate: float | None = None


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    role: Role
    country: str | None
    league: str
    team: str  # the 2026 team they ended the season on
    games: int  # 2026 games
    experience: int  # career games
    stats: dict[str, float | None]
    attributes: dict[str, int]  # 1-20, see ratings.ATTRIBUTES
    overall: int
    potential: int
    aggression: int  # 1-20, a style not a quality
    leadership: int  # 1-20, shotcalling
    reputation: int  # 0-100
    salary: int  # asking salary in thousands of USD a season
    pool: tuple[ChampionRecord, ...]  # most played first
    mastery: dict[str, int] = field(default_factory=dict)  # champion id -> 0-100
    signatures: tuple[str, ...] = ()
    photo: str | None = None  # URL on Riot's esports CDN
    real_name: str | None = None


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    tag: str
    league: str
    region: str
    tier: int
    color: str
    rank: int  # 2026 finish in the roster tournament, drives draft order
    wins: int
    losses: int
    roster: tuple[str, ...]  # player ids, starters first in role order
    starters: dict[str, str]  # role -> player id
    franchise: str | None  # player id the team keeps when the draft resets everyone else
    prestige: int  # 0-100, budget and sponsor pull
    logo: str | None = None


@dataclass(frozen=True, eq=False)  # hashed by identity so helpers can cache per catalog
class Catalog:
    patch: str
    regions: dict[str, Region]
    leagues: dict[str, League]
    teams: dict[str, Team]
    players: dict[str, Player]
    champions: dict[str, Champion]
    champion_by_key: dict[str, str]
    event_logos: dict[str, str] = field(default_factory=dict)  # FST, MSI, WORLDS
    staff: "dict[str, Staff]" = field(default_factory=dict)  # coaches and analysts, see staff.py

    def tier_one(self, region: str) -> League:
        return self.leagues[self.regions[region].league]

    def league_teams(self, league: str) -> list[Team]:
        return sorted((t for t in self.teams.values() if t.league == league), key=lambda t: t.rank)

    def region_players(self, region: str) -> list[Player]:
        return [p for p in self.players.values() if self.leagues[p.league].region == region]

    def champion_id(self, name: str) -> str | None:
        return self.champion_by_key.get(champ_key(name))


# ---------- loading ----------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _default_tag(name: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w]
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words)[:4].upper()


def _team_color(name: str) -> str:
    from app.game.rng import fnv1a

    hue = fnv1a(name) % 360
    return f"hsl({hue} 55% 50%)"


def _read(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@lru_cache
def get_catalog() -> Catalog:
    from app.game import ratings, staff

    config = _read("leagues.json")
    raw = _read("golgg_2026.json")
    meta = _read("meta_2026.json")["champions"]
    team_meta = _read("teams.json")["teams"] if (DATA / "teams.json").exists() else {}
    dragon = _read("champions.json")
    art = _read("lolesports.json") if (DATA / "lolesports.json").exists() else {"leagues": {}, "teams": {}, "players": {}}

    regions = {r["id"]: Region(r["id"], r["name"], r["league"]) for r in config["regions"]}
    leagues = {
        lg["id"]: League(lg["id"], lg["name"], lg["full_name"], lg["region"], lg["tier"], lg["strength"],
                         logo=art["leagues"].get(lg["id"]))
        for lg in config["leagues"]
    }

    meta_by_key = {champ_key(k): v for k, v in meta.items()}
    champions: dict[str, Champion] = {}
    for c in dragon["champions"]:
        m = meta_by_key.get(champ_key(c["id"]), {})
        champions[c["id"]] = Champion(
            id=c["id"], name=c["name"], roles=tuple(c["roles"]), focus=c["focus"], damage=c["damage"],
            cls=c["class"], presence=float(m.get("presence") or 0.0), winrate=float(m.get("winrate") or 50.0),
        )
    champion_by_key = {champ_key(c.id): c.id for c in champions.values()} | {
        champ_key(c.name): c.id for c in champions.values()
    }

    # A player can show up on two rosters (an academy call-up, a mid-season move); the highest
    # tier wins, then whoever played more games there.
    sightings: dict[str, tuple[int, int, str, dict, dict]] = {}
    for league_id, entry in raw["leagues"].items():
        if league_id not in leagues:
            continue
        tier = leagues[league_id].tier
        for team in entry["teams"]:
            for p in team["roster"]:
                rank = (-tier, p["games"])
                best = sightings.get(p["gol_id"])
                if best is None or rank > (best[0], best[1]):
                    sightings[p["gol_id"]] = (-tier, p["games"], league_id, team, p)

    team_ids: dict[tuple[str, str], str] = {}
    teams_raw: dict[str, dict] = {}
    for league_id, entry in raw["leagues"].items():
        if league_id not in leagues:
            continue
        for team in entry["teams"]:
            meta_t = team_meta.get(team["name"], {})
            team_id = meta_t.get("id") or f"{league_id.lower()}-{_slug(team['name'])}"
            team_ids[(league_id, team["gol_id"])] = team_id
            teams_raw[team_id] = {"league": league_id, "raw": team, "meta": meta_t}

    careers = raw.get("careers", {})
    history = raw.get("history", {})
    internationals = raw.get("international", {}).values()
    players: dict[str, Player] = {}
    rows = []
    for gol_id, (_, _, league_id, team, p) in sightings.items():
        rows.append({
            "id": f"p{gol_id}",
            "gol_id": gol_id,
            "name": p["name"],
            "role": p["role"],
            "country": p["country"] or (raw["players"].get(gol_id) or {}).get("country"),
            "league": league_id,
            "team": team_ids[(league_id, team["gol_id"])],
            "games": p["games"],
            "stats": raw["players"].get(gol_id) or {},
            "season_pool": p["champions"],
            "career": careers.get(gol_id, []),
            "history": {year: (history.get(year) or {}).get(gol_id) for year in ratings.HISTORY_YEARS},
            "international": [{"year": event["year"], **event["players"][gol_id]}
                              for event in internationals if gol_id in event["players"]],
        })
    for player in ratings.rate_players(rows, leagues, champion_by_key):
        extra = art["players"].get(player.id) or {}
        names = " ".join(n for n in (extra.get("first_name"), extra.get("last_name")) if n)
        players[player.id] = replace(player, photo=extra.get("photo"), real_name=names or None)

    teams: dict[str, Team] = {}
    for team_id, entry in teams_raw.items():
        team, meta_t, league_id = entry["raw"], entry["meta"], entry["league"]
        league = leagues[league_id]
        members = [players[f"p{p['gol_id']}"] for p in team["roster"] if players.get(f"p{p['gol_id']}")]
        members = [m for m in members if m.team == team_id]
        starters: dict[str, str] = {}
        for role in ROLES:
            in_role = sorted((m for m in members if m.role == role), key=lambda m: -m.games)
            if in_role:
                starters[role] = in_role[0].id
        bench = [m.id for m in sorted(members, key=lambda m: -m.games) if m.id not in starters.values()]
        roster = tuple([starters[r] for r in ROLES if r in starters] + bench)
        franchise = None
        wanted = meta_t.get("franchise")
        if wanted:
            franchise = next((m.id for m in members if m.name.lower() == wanted.lower()), None)
        if franchise is None and starters:
            franchise = max((players[pid] for pid in starters.values()), key=lambda p: (p.overall, p.reputation)).id
        games = team["wins"] + team["losses"]
        prestige = meta_t.get("prestige") or round(
            min(95, league.strength * 0.7 + (team["wins"] / games * 25 if games else 10))
        )
        teams[team_id] = Team(
            id=team_id,
            name=meta_t.get("name") or team["name"],
            tag=meta_t.get("tag") or _default_tag(team["name"]),
            league=league_id,
            region=league.region,
            tier=league.tier,
            color=meta_t.get("color") or _team_color(team["name"]),
            rank=team["rank"],
            wins=team["wins"],
            losses=team["losses"],
            roster=roster,
            starters=starters,
            franchise=franchise,
            prestige=int(prestige),
            logo=(art["teams"].get(team_id) or {}).get("logo"),
        )

    staff_raw = _read("staff.json") if (DATA / "staff.json").exists() else {"teams": {}}
    tier_one = {tid: t for tid, t in teams.items() if t.tier == 1}

    return Catalog(
        patch=dragon["patch"],
        regions=regions,
        leagues=leagues,
        teams=teams,
        players=players,
        champions=champions,
        champion_by_key=champion_by_key,
        event_logos={k: v for k, v in art["leagues"].items() if k in ("FST", "MSI", "WORLDS")},
        staff=staff.build(staff_raw, tier_one, leagues, regions),
    )
