"""Coaches and analysts: who they are, what they are good at and what they change.

Every team drafts an assistant coach and an analyst after its players. The staff pool of a
region is the real 2026 staff of its tier-one teams, read from Liquipedia into
app/data/staff.json, topped up with generated staff so every team has a choice and cheap
options exist. Liquipedia gives names, positions and countries only, so every rating here is
this game's own estimate: the organisation's prestige and the job they held set the level,
and a fixed draw per person spreads the attributes.

An assistant coach has four attributes (1-20):
- development: how fast players grow towards their potential
- drafting: how well the coach reads champion select (the arrows, scores and suggestions
  the manager sees, and how sharp an AI team drafts)
- motivation: how hard defeats hit morale, how fast morale recovers and how fast a new lineup
  gels
- teaching: how fast players pick up champions, on stage and in weekly practice

An analyst has two:
- scouting: how much the report on the next opponent reveals
- meta: how early and how well the patch preview reads the next balance changes

A team without a coach or analyst works as if they had attributes of 4. At the manager's club the
manager does the work they took on and covers an empty seat (see manager.py)."""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from app.game.rng import fnv1a

StaffKind = Literal["coach", "analyst"]
COACH_ATTRIBUTES = ("development", "drafting", "motivation", "teaching")
ANALYST_ATTRIBUTES = ("scouting", "meta")
ATTRIBUTES: dict[str, tuple[str, ...]] = {"coach": COACH_ATTRIBUTES, "analyst": ANALYST_ATTRIBUTES}
NOBODY = 4  # what an empty staff seat is worth
STAFF_YEARS = 2

# What a job title says about someone, on top of the organisation's level.
_POSITION_BONUS = {
    "head coach": {"*": 2, "drafting": 1, "motivation": 1},
    "assistant coach": {"*": 1},
    "strategic coach": {"*": 1, "drafting": 2},
    "positional coach": {"teaching": 2, "development": 1},
    "performance coach": {"motivation": 3},
    "head analyst": {"*": 2},
    "analyst": {"*": 1},
    "data analyst": {"meta": 2},
}

_ECONOMY = {"KR": 1.0, "CN": 1.15, "EMEA": 0.9, "NA": 1.1, "BR": 0.45, "APAC": 0.55}
_GENERATED_COUNTRIES = {
    "KR": ("KR",), "CN": ("CN",), "BR": ("BR",), "NA": ("US", "US", "CA"),
    "EMEA": ("DE", "FR", "ES", "PL", "DK", "SE", "GB", "NL", "TR", "GR"),
    "APAC": ("TW", "VN", "JP", "PH", "HK"),
}
_SYLLABLES = ("ka", "ro", "vi", "zen", "mo", "ri", "tal", "en", "sa", "dor", "ly", "nex", "ar", "ki", "vo",
              "lu", "mar", "shi", "to", "ra", "fen", "is", "gal", "um", "ce", "bru", "ny", "ox", "pe", "dra")

COUNTRY_CODES = {
    "south korea": "KR", "korea": "KR", "china": "CN", "taiwan": "TW", "hong kong": "HK", "macau": "MO",
    "vietnam": "VN", "japan": "JP", "brazil": "BR", "united states": "US", "usa": "US", "canada": "CA",
    "united kingdom": "GB", "england": "GB", "scotland": "GB", "wales": "GB", "germany": "DE", "france": "FR",
    "spain": "ES", "portugal": "PT", "italy": "IT", "poland": "PL", "denmark": "DK", "sweden": "SE",
    "norway": "NO", "finland": "FI", "netherlands": "NL", "belgium": "BE", "croatia": "HR", "serbia": "RS",
    "slovenia": "SI", "czech republic": "CZ", "czechia": "CZ", "slovakia": "SK", "greece": "GR",
    "turkey": "TR", "türkiye": "TR", "romania": "RO", "bulgaria": "BG", "hungary": "HU", "austria": "AT",
    "switzerland": "CH", "ireland": "IE", "australia": "AU", "new zealand": "NZ", "argentina": "AR",
    "chile": "CL", "mexico": "MX", "peru": "PE", "colombia": "CO", "uruguay": "UY", "venezuela": "VE",
    "philippines": "PH", "thailand": "TH", "indonesia": "ID", "malaysia": "MY", "singapore": "SG",
    "russia": "RU", "ukraine": "UA", "belarus": "BY", "lithuania": "LT", "latvia": "LV", "estonia": "EE",
    "israel": "IL", "morocco": "MA", "egypt": "EG", "saudi arabia": "SA", "united arab emirates": "AE",
    "kazakhstan": "KZ", "bosnia and herzegovina": "BA", "north macedonia": "MK", "albania": "AL",
    "kosovo": "XK", "montenegro": "ME", "iceland": "IS", "luxembourg": "LU", "cyprus": "CY", "malta": "MT",
    "india": "IN", "south africa": "ZA", "algeria": "DZ", "tunisia": "TN", "jordan": "JO", "lebanon": "LB",
    "iran": "IR", "georgia": "GE", "armenia": "AM", "azerbaijan": "AZ", "moldova": "MD",
}


@dataclass(frozen=True)
class Staff:
    id: str
    name: str  # handle
    kind: StaffKind
    position: str  # the job they held in 2026, or "Free agent" for generated staff
    region: str
    team: str | None  # 2026 team id
    country: str | None  # ISO 3166 alpha-2
    attributes: dict[str, int] = field(default_factory=dict)  # 1-20
    overall: int = 50  # 30-99, on the same scale as players
    salary: int = 20  # thousands of USD a season
    real_name: str | None = None
    photo: str | None = None
    generated: bool = False


def kind_of(position: str) -> StaffKind:
    return "analyst" if "analyst" in position.lower() else "coach"


def _spread(key: str, size: int) -> int:
    """A fixed whole number in -size..size for this key."""
    return fnv1a(key) % (2 * size + 1) - size


def _finish(staff_id: str, name: str, kind: StaffKind, position: str, region: str, team: str | None,
            country: str | None, base: float, bonus: dict[str, int], spread: int, **extra) -> Staff:
    attrs = {}
    for attr in ATTRIBUTES[kind]:
        value = base + bonus.get("*", 0) + bonus.get(attr, 0) + _spread(f"{staff_id}:{attr}", spread)
        attrs[attr] = int(max(1, min(20, round(value))))
    avg = sum(attrs.values()) / len(attrs)
    overall = round(30 + (avg - 1) * 69 / 19)
    salary = 12 * 1.25 ** (avg - 5) * _ECONOMY.get(region, 1.0) * (1.15 if kind == "coach" else 1.0)
    salary = max(10, int(round(salary / 5) * 5))
    return Staff(id=staff_id, name=name, kind=kind, position=position, region=region, team=team, country=country,
                 attributes=attrs, overall=overall, salary=salary, **extra)


def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def _handle(seed: int) -> str:
    parts = [_SYLLABLES[(seed >> (5 * i)) % len(_SYLLABLES)] for i in range(2 + seed % 2)]
    return "".join(parts).capitalize()


def build(raw: dict, teams: dict, leagues: dict, regions: dict) -> dict[str, Staff]:
    """The staff pool of every region: real staff of its tier-one teams, then generated ones."""
    out: dict[str, Staff] = {}
    for team_id, rows in raw.get("teams", {}).items():
        team = teams.get(team_id)
        if team is None:
            continue
        level = 8 + (team.prestige - 50) / 50 * 5
        for row in rows:
            position = row["position"]
            kind = kind_of(position)
            sid = f"s-{_slug(row['handle'])}"
            if sid in out:
                sid = f"{sid}-{team_id.lower()}"
            bonus = next((b for title, b in _POSITION_BONUS.items() if title == position.lower()),
                         _POSITION_BONUS["analyst" if kind == "analyst" else "assistant coach"])
            country = COUNTRY_CODES.get((row.get("country") or "").lower())
            out[sid] = _finish(sid, row["handle"], kind, position, team.region, team_id, country, level, bonus, 3,
                               real_name=row.get("name"), photo=row.get("photo"))

    for region in regions.values():
        team_count = sum(1 for t in teams.values() if t.league == region.league)
        for kind in ("coach", "analyst"):
            real = sum(1 for s in out.values() if s.region == region.id and s.kind == kind)
            wanted = max(team_count, 2 * team_count - real)
            countries = _GENERATED_COUNTRIES.get(region.id, ("US",))
            for i in range(wanted):
                seed = fnv1a(f"{region.id}:{kind}:{i}")
                name = _handle(seed)
                sid = f"g-{region.id.lower()}-{kind}-{i}"
                base = 4 + (seed % 700) / 100  # 4..11
                out[sid] = _finish(sid, name, kind, "Free agent", region.id, None, countries[seed % len(countries)],
                                   base, {}, 2, generated=True)
    return out


def region_staff(cat, region: str, kind: StaffKind | None = None) -> list[Staff]:
    return [s for s in cat.staff.values() if s.region == region and (kind is None or s.kind == kind)]


# ---------- what staff change ----------


def attribute(cat, career, team_id: str | None, attr: str) -> int:
    """The attribute of whoever does that work for the team: the coach or analyst who covers
    `attr`, NOBODY for an empty seat. At the manager's club the manager does it instead when they
    took it on or the seat is empty (see manager.py)."""
    team = career.teams.get(team_id or "")
    if team is None:
        return NOBODY
    sid = team.analyst if attr in ANALYST_ATTRIBUTES else team.coach
    person = cat.staff.get(sid or "")
    if team_id == career.team and career.profile is not None:
        from app.game import manager  # here: manager needs the catalog, which needs this module

        if manager.does(cat, career, attr):
            return int(career.profile.attributes.get(attr, NOBODY))
    return person.attributes.get(attr, NOBODY) if person else NOBODY


def development_factor(value: int) -> float:
    """Multiplies the weekly chance that a player grows: 0.76 with nobody, 1.0 at 10, 1.4 at 20."""
    return 0.6 + value * 0.04


def teaching_factor(value: int) -> float:
    """Multiplies mastery gained by playing a champion on stage: 0.76 with nobody, 1.0 at 10, 1.4 at 20."""
    return 0.6 + value * 0.04


def practice_chance(value: int) -> float:
    """Weekly chance a starter practises one of the patch's best champions in their role."""
    return value / 40


def defeat_morale(value: int) -> int:
    """Morale lost with a defeated series: -5 with nobody, -4 at 10, -3 at 20."""
    return -round(5.4 - value * 0.12)


def morale_recovery_divisor(value: int) -> int:
    """Weekly morale moves 1/divisor of the way back to 70: 9 with nobody, 7 at 10, 4 at 20."""
    return max(4, 10 - value // 3)


def familiarity_per_game(value: int) -> float:
    """How much one game together counts towards the twenty that make a pair familiar."""
    return 0.75 + value * 0.025


def draft_noise(value: int) -> float:
    """How much an AI team's champion select wanders from its best option: 1.4x with nobody, 0.6x at 20."""
    return 1.6 - value * 0.05


def scouting_level(value: int) -> int:
    """1-4: how much the report on the next opponent reveals."""
    return 1 if value < 6 else 2 if value < 11 else 3 if value < 16 else 4


def coach_lens(drafting: int, who: str) -> tuple[dict[str, float], set[str]]:
    """How whoever drafts for the manager's club (the coach, or the manager, see manager.does)
    weighs the reasons behind a champion choice.

    A perfect read (drafting 20) weighs everything as it is. Below that every kind of reason is
    over- or underrated by a fixed amount that is part of who reads it (`who`), up to 70 percent at
    drafting 1, and weak readers miss lane matchups (under 8) and champion combos (under 5)."""
    error = (20 - drafting) / 20 * 0.7
    weights = {}
    for kind in ("comfort", "meta", "role", "comp", "combo", "lane", "own"):
        swing = (fnv1a(f"{who}:{kind}") % 201 - 100) / 100  # -1..1
        weights[kind] = 1 + error * swing
    weights["role"] = 1.0  # nobody misjudges an off-role pick
    hidden = set()
    if drafting < 8:
        hidden.add("lane")
    if drafting < 5:
        hidden.add("combo")
    return weights, hidden
