"""The manager: a person with a past and attributes, who shares the work with the staff.

After picking a club the manager is created, as in Football Manager. A background sets a few
attributes and adds to the manager's reputation, and a pool of points, bigger for a manager a
bigger club would hire, is spread over nine attributes on the 1-20 scale: every attribute starts
at 4, points take it to at most 15 (lower it to free points), and the background's bonus goes on
top. Careers from before this existed create their manager on their next action, with points
from the reputation earned so far.

Six attributes are the staff's: development, drafting, motivation and teaching (the assistant
coach's) and scouting and meta (the analyst's). For each one the manager decides who does the
work, as Football Manager's responsibilities do: themselves, the staff member, or whoever of the
two is better at it (the default, so a new assistant takes over what they do better). An empty
seat falls to the manager. Three are the manager's alone:
- man management: how well a talk with an unhappy player goes, and how fast an unsettled player
  settles
- negotiation: how far players and staff come down on their salary, and how far below its asking
  fee a selling club goes (a poor negotiator pays the asking fee)
- tactics: how fast set plays are learned and how often they work

What counts is the whole number: growth (to come) adds fractions. A career whose manager is not
created yet works as before: the staff do everything and the manager's own attributes are 10."""

from dataclasses import dataclass
from datetime import date

from app.game import reputation
from app.game.catalog import Catalog
from app.game.errors import IllegalAction
from app.game.state import Career, Competition, CompetitionRecord, ManagerProfile, ManagerSeason, Spell

ATTRIBUTES = ("development", "drafting", "motivation", "teaching", "scouting", "meta",
              "man_management", "negotiation", "tactics")
SEATS = {"development": "coach", "drafting": "coach", "motivation": "coach", "teaching": "coach",
         "scouting": "analyst", "meta": "analyst"}
OWN = ("man_management", "negotiation", "tactics")
NAMES = {"development": "Development", "drafting": "Drafting", "motivation": "Motivation", "teaching": "Teaching",
         "scouting": "Scouting", "meta": "Meta reading", "man_management": "Man management",
         "negotiation": "Negotiation", "tactics": "Tactics"}
TEXTS = {
    "development": "How fast players grow towards their potential",
    "drafting": "How well champion select is read: the arrows, scores and suggestions you see",
    "motivation": "How hard defeats hit morale, how fast it recovers, how fast a new lineup gels",
    "teaching": "How fast players pick up champions, on stage and in practice",
    "scouting": "How much the report on the next opponent and on shortlisted players reveals",
    "meta": "How early and how well the patch preview reads the next balance changes",
    "man_management": "How talks with unhappy players go and how fast an unsettled player settles",
    "negotiation": "How far players and staff come down on salary, and selling clubs below their asking fee",
    "tactics": "How fast set plays are learned and how often they work",
}
NEUTRAL = 10  # the manager's own attributes in a career whose manager is not created yet
BASE = 4  # every attribute before points
LOWEST, HIGHEST = 1, 15  # what points can make of an attribute
CAP = 20
NAME_LENGTH = 24


@dataclass(frozen=True)
class Background:
    name: str
    text: str
    reputation: float  # added to the manager's reputation
    bonus: dict[str, int]  # on top of the points
    points: int = 0  # extra points


BACKGROUNDS = {
    "pro": Background("Former pro", "Years on stage: players listen, and you read a draft the way they do.", 4.0,
                      {"drafting": 3, "motivation": 2, "teaching": 2}),
    "coach": Background("Career coach", "Academies and assistant jobs: you know how players grow and how to talk "
                        "to them.", 2.0, {"development": 3, "teaching": 2, "man_management": 2}),
    "analyst": Background("Former analyst", "VOD reviews and patch notes: you see what others miss.", 1.0,
                          {"scouting": 3, "meta": 3, "drafting": 1}),
    "newcomer": Background("Newcomer", "Nobody knows you yet: a clean slate and a few more points to spend.", 0.0,
                           {}, 5),
}


def points(reputation_value: float, background: str) -> int:
    """Points to spend above the base: 45 for the manager a 78-prestige club hires, more for a bigger name."""
    return max(24, min(60, round(36 + (reputation_value - 60) * 0.6))) + BACKGROUNDS[background].points


def budget(career: Career, background: str) -> int:
    """What the attributes may add up to before the bonus."""
    return BASE * len(ATTRIBUTES) + points(reputation.manager_in(career, career.region), background)


def even_spread(career: Career, background: str) -> dict[str, int]:
    """The points spread as evenly as they go, for tests and for a quick start."""
    total = budget(career, background)
    each, extra = divmod(total, len(ATTRIBUTES))
    return {a: min(HIGHEST, each + (1 if i < extra else 0)) for i, a in enumerate(ATTRIBUTES)}


def _staff_value(cat: Catalog, career: Career, attr: str) -> int | None:
    team = career.teams[career.team]
    person = cat.staff.get(getattr(team, SEATS[attr]) or "")
    return person.attributes.get(attr) if person else None


def create(cat: Catalog, career: Career, background: str, attributes: dict[str, int], name: str | None,
           country: str | None) -> None:
    if career.profile is not None:
        raise IllegalAction("Your manager is already created")
    if background not in BACKGROUNDS:
        raise IllegalAction("Pick a background")
    if set(attributes) != set(ATTRIBUTES):
        raise IllegalAction("Set every attribute")
    if any(not LOWEST <= v <= HIGHEST for v in attributes.values()):
        raise IllegalAction(f"Attributes go from {LOWEST} to {HIGHEST} before the background's bonus")
    total = budget(career, background)
    if sum(attributes.values()) > total:
        raise IllegalAction(f"That is {sum(attributes.values()) - total} points more than you have")
    if name is not None:
        name = " ".join(name.split())
        if not 1 <= len(name) <= NAME_LENGTH:
            raise IllegalAction(f"A name of 1 to {NAME_LENGTH} characters")
        career.manager = name
    if country is not None and not (len(country) == 2 and country.isalpha() and country.isupper()):
        raise IllegalAction("Unknown country")
    bg = BACKGROUNDS[background]
    values = {a: float(min(CAP, attributes[a] + bg.bonus.get(a, 0))) for a in ATTRIBUTES}
    career.profile = ManagerProfile(background=background, country=country, attributes=values, created=career.day)
    reputation.change_manager(cat, career, bg.reputation, everywhere=True)  # a past is known everywhere


def set_duty(career: Career, attr: str, who: str) -> None:
    if career.profile is None:
        raise IllegalAction("Create your manager first")
    if attr not in SEATS:
        raise IllegalAction("Only the staff's work can be shared")
    if who == "auto":
        career.profile.duties.pop(attr, None)
    else:
        career.profile.duties[attr] = who  # type: ignore[assignment]


def does(cat: Catalog, career: Career, attr: str) -> bool:
    """Whether the manager does this piece of the staff's work at their club: by choice, for an empty
    seat, or, left to the game, because they are better at it than the staff member."""
    p = career.profile
    if p is None or attr not in SEATS:
        return False
    staff = _staff_value(cat, career, attr)
    duty = p.duties.get(attr)
    return staff is None or duty == "manager" or (duty is None and int(p.attributes.get(attr, NEUTRAL)) > staff)


def own(career: Career, attr: str) -> int:
    """One of the manager's own attributes (man management, negotiation, tactics)."""
    return int(career.profile.attributes.get(attr, NEUTRAL)) if career.profile else NEUTRAL


def factor(value: int) -> float:
    """0.64 at 1, 1.0 at 10, 1.4 at 20, like the staff's development and teaching."""
    return 0.6 + value * 0.04


def haggle(career: Career) -> float:
    """What a price is multiplied by after the manager negotiates: 6 percent off at 20, 5 percent on at 1."""
    return 1 - 0.006 * (own(career, "negotiation") - 10)


def summary(career: Career) -> dict | None:
    p = career.profile
    if p is None:
        return None
    return {"background": p.background, "country": p.country}


def view(cat: Catalog, career: Career) -> dict:
    from app.game.views import staff_row, team_ref

    p = career.profile
    out: dict = {
        "name": career.manager,
        "club": None if career.board.sacked else team_ref(cat, career.team),
        "record": record_view(cat, career),
        "reputation": career.manager_reputation,
        "stars": reputation.stars(career.manager_reputation),
        "ratings": reputation.manager_ratings(cat, career),
        "profile": None,
        "attributes": [{"id": a, "name": NAMES[a], "text": TEXTS[a], "seat": SEATS.get(a)} for a in ATTRIBUTES],
        "backgrounds": [{"id": k, "name": b.name, "text": b.text, "reputation": b.reputation, "bonus": b.bonus,
                         "points": points(reputation.manager_in(career, career.region), k)}
                        for k, b in BACKGROUNDS.items()],
        "rules": {"base": BASE, "lowest": LOWEST, "highest": HIGHEST, "cap": CAP, "name_length": NAME_LENGTH},
        "duties": [],
    }
    if p is None:
        return out
    team = career.teams[career.team]
    out["profile"] = {
        "background": p.background, "background_name": BACKGROUNDS[p.background].name, "country": p.country,
        "attributes": {a: round(p.attributes.get(a, NEUTRAL), 2) for a in ATTRIBUTES}, "created": p.created.isoformat(),
    }
    for attr, seat in SEATS.items():
        sid = getattr(team, seat)
        out["duties"].append({
            "attribute": attr, "seat": seat, "staff": staff_row(cat, career, sid) if sid else None,
            "staff_value": _staff_value(cat, career, attr), "mine": int(p.attributes.get(attr, NEUTRAL)),
            "who": "manager" if does(cat, career, attr) else "staff", "choice": p.duties.get(attr, "auto"),
        })
    return out

# ---------- the manager's career: clubs, seasons, trophies ----------


def start_spell(career: Career) -> None:
    """A new job (board.start_job): the open spell ends and one at the new club begins."""
    last = career.spells[-1] if career.spells else None
    if last is not None and last.end is None:
        if last.team == career.team:
            return
        last.end, last.left = career.day, last.left or "moved"
    career.spells.append(Spell(team=career.team, start=career.day))


def end_spell(career: Career, how: str) -> None:
    last = career.spells[-1] if career.spells else None
    if last is not None and last.end is None:
        last.end, last.left = career.day, how  # type: ignore[assignment]


def _led(career: Career, day: date) -> str | None:
    """The club the manager led on that day."""
    for s in reversed(career.spells):
        if s.start <= day and (s.end is None or day <= s.end):
            return s.team
    return None


def _kind(comp: Competition) -> str:
    return "league" if comp.kind == "league" else comp.id.split("-", 1)[1]


def season_so_far(career: Career) -> list[CompetitionRecord]:
    """The manager's competitions this season, from the series their club played under them."""
    records: dict[tuple[str, str], CompetitionRecord] = {}
    for match in career.matches.values():
        team = _led(career, match.day) if match.winner else None
        comp = career.competitions.get(match.competition)
        if team is None or comp is None or team not in (match.home, match.away):
            continue
        rec = records.setdefault((comp.id, team), CompetitionRecord(name=comp.name, kind=_kind(comp), team=team))  # type: ignore[arg-type]
        rec.series[0 if match.winner == team else 1] += 1
        won = sum(1 for g in match.games if g.winner == team)
        rec.games[0] += won
        rec.games[1] += len(match.games) - won
    for (cid, team), rec in records.items():
        placements = career.competitions[cid].placements
        if team in placements:
            rec.place = placements.index(team) + 1
    return [records[k] for k in sorted(records, key=lambda k: career.competitions[k[0]].start)]


def record_season(career: Career) -> None:
    """Keep the season when it ends (offseason.start_offseason): its competitions are cleared later."""
    if any(s.season == career.season for s in career.manager_seasons):
        return
    career.manager_seasons.append(ManagerSeason(season=career.season, competitions=season_so_far(career),
                                                reputation=career.manager_reputation))


def _history_kind(name: str) -> str:
    return {"First Stand": "FST", "MSI": "MSI", "Worlds": "WORLDS"}.get(name, "league")


def ensure(career: Career) -> bool:
    """Give a career from before the Me screen its manager's past: the club they hold since they
    took the job, the seasons its summaries kept, and today's reputation. Returns True on a change."""
    changed = False
    if not career.spells:
        spell = Spell(team=career.team, start=career.board.joined or career.day)
        if career.board.sacked:
            spell.end, spell.left = career.day, "sacked"
        career.spells = [spell]
        changed = True
    if not career.reputation_log and career.manager_reputation:
        reputation.log_manager(career)
        changed = True
    known = {s.season for s in career.manager_seasons}
    for h in career.history:
        if h.season not in known:
            comps = [CompetitionRecord(name=n, kind=_history_kind(n), team="", place=p)  # type: ignore[arg-type]
                     for n, p in h.finishes.items()]
            career.manager_seasons.append(ManagerSeason(season=h.season, competitions=comps))
            changed = True
    career.manager_seasons.sort(key=lambda s: s.season)
    return changed


def _won_lost(records: list[CompetitionRecord], field: str) -> list[int]:
    return [sum(getattr(r, field)[0] for r in records), sum(getattr(r, field)[1] for r in records)]


def record_view(cat: Catalog, career: Career) -> dict:
    """The Me screen's record: every season, the trophies, the clubs and the reputation over time."""
    from app.game.views import team_ref

    seasons = list(career.manager_seasons)
    if all(s.season != career.season for s in seasons):
        seasons.append(ManagerSeason(season=career.season, competitions=season_so_far(career),
                                     reputation=career.manager_reputation))
    ref = (lambda t: team_ref(cat, t) if t in cat.teams else None)
    rows, trophies = [], []
    for s in seasons:
        rows.append({
            "season": s.season, "current": s.season == career.season,
            "teams": [ref(t) for t in dict.fromkeys(c.team for c in s.competitions if c.team)],
            "series": _won_lost(s.competitions, "series"), "games": _won_lost(s.competitions, "games"),
            "titles": [c.name for c in s.competitions if c.place == 1],
            "competitions": [c.model_dump() | {"team": ref(c.team)} for c in s.competitions],
        })
        trophies += [{"name": c.name, "kind": c.kind, "season": s.season, "team": ref(c.team)}
                     for c in s.competitions if c.place == 1]
    clubs = []
    for sp in career.spells:
        mine = [c for s in seasons for c in s.competitions if c.team == sp.team]
        clubs.append({"team": ref(sp.team), "start": sp.start.isoformat(), "end": sp.end.isoformat() if sp.end else None,
                      "left": sp.left, "series": _won_lost(mine, "series"), "games": _won_lost(mine, "games"),
                      "titles": sum(1 for c in mine if c.place == 1)})
    every = [c for s in seasons for c in s.competitions]
    open_spell = career.spells[-1] if career.spells and career.spells[-1].end is None else None
    return {
        "since": open_spell.start.isoformat() if open_spell else None,
        "totals": {"series": _won_lost(every, "series"), "games": _won_lost(every, "games"), "titles": len(trophies),
                   "seasons": len(seasons)},
        "seasons": list(reversed(rows)),
        "trophies": list(reversed(trophies)),
        "clubs": list(reversed(clubs)),
        "reputation_log": [[p[0].isoformat(), *p[1:]] for p in career.reputation_log],
    }
