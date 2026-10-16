"""Fetch players' birth dates from Liquipedia into app/data/ages.json.

    python -m scripts.fetch_ages            # every player in the catalog
    python -m scripts.fetch_ages Faker Caps # a few, to try it out (prints, writes nothing)

The data has no ages, and a career age guessed from games played makes the stars of the busiest
leagues years too young (see retirement.py). Liquipedia's player pages have a birth date in their
infobox. The script asks the API for the wikitext of 50 pages at a time (action=query, one request
every two seconds, as Liquipedia asks), follows redirects, and for a disambiguation page tries the
pages it links to. A page under the player's own name is theirs; among the pages a disambiguation
links to, the one whose romanized name shares a word with the player's real name from lolesports.com. Responses are
cached in .cache/liquipedia/ages, so a rerun only asks for what it does not have.

Liquipedia's content is CC BY-SA 3.0."""

import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import httpx

from app.game.catalog import get_catalog

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "liquipedia" / "ages"
OUT = ROOT / "app" / "data" / "ages.json"
API = "https://liquipedia.net/leagueoflegends/api.php"
HEADERS = {"User-Agent": "LeagueManagerFanGame/0.1 (personal non-commercial fan project)", "Accept-Encoding": "gzip"}
QUERY_PAUSE = 2.1  # seconds, Liquipedia's limit for action=query
BATCH = 50

FIELD = re.compile(r"^\|[ 	]*(\w+)[ 	]*=[ 	]*(.*?)[ 	]*$", re.M)
BIRTH = re.compile(r"(\d{4})-(\d{2})-(\d{2})|(\d{4})")
LINK = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]|link=([^|}]+)")
# Spellings of the same Korean family name, so "Jihun Jung" is "Jeong Ji-hoon".
VARIANTS = {"jung": "jeong", "chung": "jeong", "lee": "yi", "rhee": "yi", "choi": "choe", "kang": "gang",
            "gim": "kim", "bak": "park", "pak": "park", "ryu": "yu", "yoo": "yu", "shin": "sin", "jo": "cho"}


def _key(title: str) -> str:
    return CACHE / (re.sub(r"[^\w.-]+", "_", title) + ".json")  # type: ignore[return-value]


def fetch(client: httpx.Client, titles: list[str]) -> dict[str, str | None]:
    """Wikitext by the title asked for (None: no such page), from the cache where there is one."""
    out: dict[str, str | None] = {}
    missing = []
    for t in titles:
        path = _key(t)
        if path.exists():
            out[t] = json.loads(path.read_text(encoding="utf-8"))["text"]
        else:
            missing.append(t)
    for i in range(0, len(missing), BATCH):
        chunk = missing[i:i + BATCH]
        r = client.get(API, params={"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                                    "titles": "|".join(chunk), "redirects": "1", "format": "json",
                                    "formatversion": "2"}, headers=HEADERS, timeout=60)
        r.raise_for_status()
        q = r.json()["query"]
        alias = {n["from"]: n["to"] for n in q.get("normalized", [])}
        moved = {n["from"]: n["to"] for n in q.get("redirects", [])}
        pages = {p["title"]: (p["revisions"][0]["slots"]["main"]["content"] if "revisions" in p else None)
                 for p in q.get("pages", [])}
        for t in chunk:
            final = alias.get(t, t)
            final = moved.get(final, final)
            out[t] = pages.get(final)
            CACHE.mkdir(parents=True, exist_ok=True)
            _key(t).write_text(json.dumps({"title": final, "text": out[t]}), encoding="utf-8")
        time.sleep(QUERY_PAUSE)
    return out


def infobox(text: str | None) -> dict[str, str] | None:
    if not text or "{{Infobox player" not in text:
        return None
    body = text[text.index("{{Infobox player"):]
    return {k.lower(): v for k, v in FIELD.findall(body.split("\n}}", 1)[0])}


def disambiguation(text: str | None) -> list[str]:
    if not text or not re.search(r"\{\{\s*(Disambig|disambiguation)", text, re.I):
        return []
    found = {(a or b).strip().replace("_", " ") for a, b in LINK.findall(text)}
    return sorted(t for t in found if t and ":" not in t)


def birth(box: dict[str, str]) -> str | None:
    m = BIRTH.search(box.get("birth_date", ""))
    if not m:
        return None
    if m.group(1):
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return m.group(4)  # only the year is known


def _words(name: str) -> set[str]:
    """A name's words, lower case, a hyphenated given name as one word, family names spelled one way."""
    out = set()
    for w in re.split(r"\s+", name.lower()):
        w = re.sub(r"[^a-z]", "", w)
        if len(w) > 1:
            out.add(VARIANTS.get(w, w))
    return out


def same_person(box: dict[str, str], real_name: str | None) -> bool:
    if not real_name:
        return True
    theirs = _words(" ".join(box.get(k, "") for k in ("romanized_name", "name", "familyname", "givenname")))
    return not theirs or bool(_words(real_name) & theirs)


def main() -> None:
    cat = get_catalog()
    only = {a.lower() for a in sys.argv[1:]}
    players = [p for p in cat.players.values() if not only or p.name.lower() in only]
    found: dict[str, str] = {}
    with httpx.Client() as client:
        texts = fetch(client, sorted({p.name for p in players}))
        # A disambiguation page: try every page it links to and keep the one that is this player.
        candidates: dict[str, list[str]] = {}
        for p in players:
            links = disambiguation(texts.get(p.name))
            if links:
                candidates[p.id] = links
        more = fetch(client, sorted({t for links in candidates.values() for t in links}))
        for p in players:
            # A page under the player's own name is theirs: one name shared by two players gets a
            # disambiguation page. Among the pages a disambiguation links to, the real name decides.
            direct = p.id not in candidates
            options = [texts.get(p.name)] if direct else [more.get(t) for t in candidates[p.id]]
            for text in options:
                box = infobox(text)
                if box and (direct or same_person(box, p.real_name)) and birth(box):
                    found[p.id] = birth(box)  # type: ignore[assignment]
                    break
            if only:
                print(f"{p.name:14s} {p.real_name or '-':28s} {found.get(p.id, 'not found')}")
    if only:
        return
    OUT.write_text(json.dumps({"source": "Liquipedia, CC BY-SA 3.0", "fetched": date.today().isoformat(),
                               "players": dict(sorted(found.items()))}, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"{len(found)} of {len(players)} players have a birth date")


if __name__ == "__main__":
    main()
