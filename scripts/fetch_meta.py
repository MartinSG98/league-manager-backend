"""Fetch how every champion was picked and banned across all 2026 pro play from gol.gg and write
app/data/meta_2026.json, the meta a career starts on.

    python -m scripts.fetch_meta

One page covers the whole season. Presence is picks plus bans over games played, the share of
drafts a champion showed up in. Patches in a career move champions away from this starting
point (see app/game/patches.py)."""

import html as htmllib
import json
import re
from datetime import date
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "meta_2026.json"
URL = "https://gol.gg/champion/list/season-S16/split-ALL/tournament-ALL/"
HEADERS = {"User-Agent": "Mozilla/5.0 (league-manager data fetch, personal fan project)"}

ROW = re.compile(r"""_img/champions_icon/(\w+)\.png'/>\s*([^<]+)</a></td>(.*?)</tr>""", re.S)
CELL = re.compile(r"<td class='text-center'>(.*?)</td>", re.S)
COLUMNS = ["picks", "bans", "prio", "wins", "losses", "winrate", "kda", "ban_turn", "pick_round", "blind",
           "game_time", "csm", "dpm", "gpm", "csd15", "gd15", "xpd15"]


def _num(text: str) -> float | None:
    text = re.sub(r"<[^>]+>", "", text).replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def main() -> None:
    page = httpx.get(URL, headers=HEADERS, timeout=90, follow_redirects=True).text
    champions: dict[str, dict] = {}
    for champ_id, name, rest in ROW.findall(page):
        values = dict(zip(COLUMNS, (_num(cell) for cell in CELL.findall(rest))))
        champions[champ_id] = {"name": htmllib.unescape(name.strip())} | {
            key: values.get(key) for key in ("picks", "bans", "prio", "winrate", "gd15")
        }
    games = round(sum(c["picks"] or 0 for c in champions.values()) / 10)
    for champ in champions.values():
        champ["presence"] = round(100 * ((champ["picks"] or 0) + (champ["bans"] or 0)) / max(games, 1), 1)
    payload = {"source": "gol.gg 2026 champion list", "fetched": str(date.today()), "games": games,
               "champions": champions}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(champions)} champions over {games} games")


if __name__ == "__main__":
    main()
