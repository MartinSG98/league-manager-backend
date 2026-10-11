"""Fetch the coaching and analyst staff of every tier-one team from Liquipedia and write
app/data/staff.json, keyed by this game's team ids.

    python -m scripts.fetch_staff [--cached-only] [--only G2,T1]

Each team page is rendered through the Liquipedia API (action=parse). Liquipedia allows one such
request every 30 seconds, so a full run takes about half an hour; every page is cached in
.cache/liquipedia and a rerun only fetches what is missing. The staff are read from the active
"Player Roster" and "Organization" tables: anyone whose position mentions coach or analyst.
Photos come from the lolesports.com roster of the same team when a handle matches there.

Liquipedia content is CC BY-SA 3.0; only names, positions and countries are kept."""

import argparse
import html as htmllib
import json
import re
import time
from pathlib import Path

import httpx

from app.game.catalog import get_catalog

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "data" / "staff.json"
TEAMS_META = ROOT / "app" / "data" / "teams.json"
CACHE = ROOT / ".cache" / "liquipedia"
API = "https://liquipedia.net/leagueoflegends/api.php"
HEADERS = {"User-Agent": "LeagueManagerFanGame/0.1 (personal non-commercial fan project)", "Accept-Encoding": "gzip"}
PARSE_PAUSE = 31  # seconds, Liquipedia's limit for action=parse
LOLESPORTS = "https://esports-api.lolesports.com/persisted/gw"
LOLESPORTS_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"

STAFF = re.compile(r"coach|analyst", re.I)
SKIP = re.compile(r"manager|content|streamer|creator|ceo|founder|owner|director", re.I)


class CacheMiss(Exception):
    pass


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def page(client: httpx.Client, title: str, cached_only: bool) -> str | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (re.sub(r"[^A-Za-z0-9_.-]", "_", title) + ".html")
    if path.exists():
        return path.read_text(encoding="utf-8")
    if cached_only:
        raise CacheMiss(title)
    response = client.get(API, params={"action": "parse", "page": title, "format": "json", "prop": "text",
                                       "redirects": "1"}, headers=HEADERS)
    response.raise_for_status()
    data = response.json()
    time.sleep(PARSE_PAUSE)
    if "error" in data:
        print(f"  {title}: {data['error'].get('info')}")
        path.write_text("", encoding="utf-8")
        return None
    text = data["parse"]["text"]["*"]
    path.write_text(text, encoding="utf-8")
    return text


def _active_part(html: str, anchor: str) -> str:
    start = html.find(f'id="{anchor}"')
    if start < 0:
        return ""
    end = html.find("<h2", start + 10)
    part = html[start:end if end > 0 else len(html)]
    former = part.find('id="Former')
    return part[:former] if former > 0 else part


def staff_rows(html: str) -> list[dict]:
    """Active coaches and analysts from the roster and organization tables."""
    rows = []
    seen = set()
    for anchor in ("Player_Roster", "Organization"):
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", _active_part(html, anchor), re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            texts = [_text(c) for c in cells]
            at = next((i for i, t in enumerate(texts) if STAFF.search(t) and not SKIP.search(t)), None)
            if at is None or at < 2:
                continue
            handle = texts[at - 2] or texts[at - 1]
            name = texts[at - 1] if texts[at - 2] else None
            flag = re.search(r'<img[^>]+alt="([^"]+)"', cells[0]) or re.search(r'<img[^>]+alt="([^"]+)"', cells[at - 2])
            key = handle.lower()
            if not handle or key in seen:
                continue
            seen.add(key)
            rows.append({"handle": handle, "name": name or None, "position": texts[at],
                         "country": flag.group(1) if flag else None})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cached-only", action="store_true")
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    cat = get_catalog()
    meta = json.loads(TEAMS_META.read_text(encoding="utf-8"))["teams"]
    titles = {m["id"]: m.get("liquipedia") for m in meta.values()}
    only = {t for t in args.only.split(",") if t}
    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"teams": {}}

    with httpx.Client(timeout=60) as client:
        roster_photos = _lolesports_photos(client)
        teams = [t for t in cat.teams.values() if t.tier == 1 and (not only or t.id in only)]
        teams.sort(key=lambda t: (t.league, t.rank))
        for team in teams:
            title = titles.get(team.id) or team.name.replace(" ", "_")
            try:
                html = page(client, title, args.cached_only)
            except CacheMiss:
                continue
            except httpx.HTTPError as exc:
                print(f"  {team.id}: {exc}")
                continue
            rows = staff_rows(html or "")
            photos = roster_photos.get(team.name.lower(), {}) | roster_photos.get(team.tag.lower(), {})
            for row in rows:
                row["photo"] = photos.get(row["handle"].lower())
            out["teams"][team.id] = rows
            found = ", ".join(f"{r['handle']} ({r['position']})" for r in rows) or "none found"
            print(f"{team.league} {team.id}: {found}")
            OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


def _lolesports_photos(client: httpx.Client) -> dict[str, dict[str, str]]:
    """Team name or code -> staff handle -> photo, from the non-player entries of lolesports rosters."""
    try:
        response = client.get(f"{LOLESPORTS}/getTeams", params={"hl": "en-US"}, headers={"x-api-key": LOLESPORTS_KEY})
        response.raise_for_status()
    except httpx.HTTPError:
        return {}
    out: dict[str, dict[str, str]] = {}
    for team in response.json()["data"]["teams"]:
        if team.get("status") != "active":
            continue
        staff = {p["summonerName"].strip().lower(): p["image"].replace("http://", "https://")
                 for p in team.get("players", []) if p.get("role") == "none" and p.get("image")}
        for key in (team["name"].lower(), team["code"].lower()):
            out.setdefault(key, {}).update(staff)
    return out


if __name__ == "__main__":
    main()
