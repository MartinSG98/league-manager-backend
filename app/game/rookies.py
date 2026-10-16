"""Rookies: a new class of players every off-season, the way Football Manager brings in regens.

The catalog only knows the players of 2026. From the first off-season on, every region gets a
class of rookies who turn pro for the next season. Most are ordinary and many will never make it;
a few are real prospects, and now and then one is a wonderkid. They come in two ways: through an
academy or ERL team of their region (their team of origin), or straight from solo queue with no
team at all. Either way they are free agents anyone can sign, like every ERL player.

How good a rookie can become is drawn first (CLASSES), then how far from it they start. What the
game shows as potential is the scouts' first estimate, and a hopeful one: the real ceiling is hidden
as for every player and is more often below it than above (training.ceiling), so some never get
near it and a scout report is the way to tell a wonderkid from a hyped bust.

Rookies live in the career (Career.rookies), not in the shared catalog. catalog_for gives a
career its own catalog: the shared players plus that career's rookies."""

import weakref
from dataclasses import replace

from app.game import ratings
from app.game.catalog import ROLES, Catalog, ChampionRecord, Player
from app.game.rng import Rng
from app.game.staff import Staff
from app.game.state import Career, CareerStaff, InboxMessage, PlayerState, Rookie

# (share of a class, lowest potential, highest potential, label) -- the labels never reach the client.
CLASSES = (
    (0.30, 40, 58, "bust"),
    (0.35, 55, 68, "journeyman"),
    (0.22, 65, 76, "decent"),
    (0.10, 75, 86, "prospect"),
    (0.03, 82, 88, "star"),
)
WONDERKID = (90, 98)  # every region rolls once for one of these
WONDERKID_CHANCE = 0.3  # otherwise the roll gives a star
PER_TEAM = 1.2  # rookies a season per tier-one team in the region
ACADEMY_SHARE = 0.6  # the rest come straight from solo queue
STRONG_REGIONS = {"KR": 2, "CN": 2}  # deeper talent pools add to every potential

COUNTRIES = {
    "KR": ("KR",),
    "CN": ("CN", "CN", "CN", "TW"),
    "EMEA": ("FR", "DE", "ES", "PL", "TR", "DK", "SE", "GR", "CZ", "PT", "GB", "IT", "BE", "NL"),
    "NA": ("US", "US", "CA", "MX"),
    "BR": ("BR", "BR", "BR", "AR", "CL"),
    "APAC": ("VN", "TW", "JP", "PH", "HK"),
}
_START = ("Ka", "Ze", "Ry", "Vi", "No", "Lu", "Mi", "Shi", "Xo", "Ta", "Ji", "Ha", "Do", "Re", "Fa", "Yu", "Ko",
          "Ra", "Se", "Wo", "Bel", "Cy", "Dra", "Eo", "Gal", "Ira", "Kai", "Lys", "Mor", "Nyx", "Or", "Pyr", "Qu",
          "Sol", "Tor", "Ul", "Vex", "Wyn", "Xen", "Zan")
_END = ("ro", "nix", "kai", "zu", "ve", "ra", "to", "mo", "shin", "lo", "x", "ka", "ru", "n", "ki", "ya", "on",
        "ix", "ze", "ris", "th", "rin", "dex", "lyn", "vo", "sa", "mi", "rek", "gen", "ji")
_WORDS = ("Ghost", "Lynx", "Echo", "Raven", "Sage", "Blitz", "Frost", "Nova", "Ember", "Drift", "Pulse", "Vortex",
          "Cipher", "Halo", "Mirage", "Rogue", "Talon", "Vesper", "Zenith", "Quill", "Onyx", "Kite", "Sable")


def is_rookie(pid: str) -> bool:
    return pid.startswith("r")


# The merged catalog of each career object, kept while the career lives. Rookies and new staff
# are only ever appended and never change, so their counts tell whether it is still current;
# reusing it also keeps champion select's caches per catalog (_duos, _by_role) warm.
_merged: dict[int, tuple[weakref.ref, tuple[int, int, int], Catalog]] = {}


def catalog_for(cat: Catalog, career: Career) -> Catalog:
    """The shared catalog with this career's rookies and new staff added. The shared one is never changed."""
    if not career.rookies and not career.new_staff:
        return cat
    key = (id(cat), len(career.rookies), len(career.new_staff))
    hit = _merged.get(id(career))
    if hit is not None and hit[0]() is career and hit[1] == key:
        return hit[2]
    players = {r.id: _player(r) for r in career.rookies if r.id not in cat.players}
    staff = {s.id: _staff(s) for s in career.new_staff if s.id not in cat.staff}
    if not players and not staff:
        return cat  # already merged
    merged = replace(cat, players={**cat.players, **players} if players else cat.players,
                     staff={**cat.staff, **staff} if staff else cat.staff)
    slot = id(career)

    def forget(ref: weakref.ref) -> None:
        if _merged.get(slot, (None,))[0] is ref:
            del _merged[slot]

    _merged[slot] = (weakref.ref(career, forget), key, merged)
    return merged


def _staff(s: CareerStaff) -> Staff:
    return Staff(id=s.id, name=s.name, kind=s.kind, position=s.position, region=s.region, team=None,
                 country=s.country, attributes=dict(s.attributes), overall=s.overall, salary=s.salary)


def _player(r: Rookie) -> Player:
    pool = tuple(ChampionRecord(champion, games, None) for champion, games in r.pool)
    return Player(
        id=r.id, name=r.name, role=r.role, country=r.country, league=r.league, team=r.team, games=0,  # type: ignore[arg-type]
        experience=r.experience, stats={}, attributes=dict(r.attributes), overall=r.overall, potential=r.potential,
        aggression=r.aggression, leadership=r.leadership, reputation=r.reputation, salary=r.salary, pool=pool,
        mastery={champion: ratings.mastery_from_games(games) for champion, games in r.pool},
        signatures=tuple(r.signatures),
    )


# ---------- the class of a new season ----------


def intake(cat: Catalog, career: Career, rng: Rng, season: int) -> list[Rookie]:
    """Draw every region's rookies for `season` and sign them in as free agents."""
    names = {p.name.lower() for p in cat.players.values()} | {r.name.lower() for r in career.rookies}
    new: list[Rookie] = []
    for region in cat.regions.values():
        teams = [t for t in cat.teams.values() if t.league == region.league]
        count = max(6, round(PER_TEAM * len(teams)))
        academies = [t for t in cat.teams.values()
                     if cat.leagues[t.league].region == region.id and cat.leagues[t.league].tier > 1]
        for n in range(count):
            # The first rookie of every region is its headline: a wonderkid more often than not.
            headline = n == 0
            rookie = _draw(cat, rng, region.id, academies, names, headline, f"r{season}{region.id.lower()}{n + 1:02d}",
                           season)
            names.add(rookie.name.lower())
            new.append(rookie)
    for rookie in new:
        career.rookies.append(rookie)
        career.players[rookie.id] = PlayerState(id=rookie.id)
    career.inbox.append(InboxMessage(
        id=career.next_message, day=career.day, kind="news", subject=f"The {season} rookie class turns pro",
        body=(f"{len(new)} rookies across every region are looking for a team: some through academies and ERL "
              "teams, some straight from solo queue. Most will not make it; a few will. Find them under Scouting "
              "with Rookies only, and send the analyst before you trust a potential."),
    ))
    career.next_message += 1
    return new


def _draw(cat: Catalog, rng: Rng, region: str, academies: list, names: set[str], headline: bool, rid: str,
          season: int) -> Rookie:
    if headline:
        low, high = WONDERKID if rng.chance(WONDERKID_CHANCE) else CLASSES[-1][1:3]
    else:
        roll, low, high = rng.next(), CLASSES[0][1], CLASSES[0][2]
        for share, lo, hi, _ in CLASSES:
            if roll < share:
                low, high = lo, hi
                break
            roll -= share
    potential = min(99, round(low + (high - low) * rng.next()) + STRONG_REGIONS.get(region, 0))
    # Nobody turns pro at their peak: a prospect starts 18 to 26 below the potential and needs about
    # three seasons to get near it, a bust is years away from nothing.
    gap = 18 + 8 * rng.next() if potential >= 85 else 14 + 14 * rng.next()
    overall = max(35, round(potential - gap))
    role = ROLES[rng.int(len(ROLES))]

    origin = rng.pick(academies) if academies and rng.chance(ACADEMY_SHARE) else None
    league = origin.league if origin else (rng.pick([t.league for t in academies]) if academies else cat.regions[region].league)

    base = (overall - 30) / 3.3
    weights = ratings.ROLE_WEIGHTS[role]
    attributes = {}
    for attr in ratings.ATTRIBUTES:
        if attr == "composure":
            value = base - 2 + 2 * (rng.next() - 0.5)
        elif attr == "champion_pool":
            value = 2 + 4 * rng.next()
        else:
            value = base + (weights[attr] - 0.125) * 8 + 3 * (rng.next() - 0.5)
        attributes[attr] = int(max(1, min(20, round(value))))

    in_role = [c.id for c in cat.champions.values() if role in c.roles]
    picks = rng.shuffle(in_role)[: 3 + rng.int(5)]
    pool = sorted(([c, 4 + rng.int(36)] for c in picks), key=lambda x: -x[1])
    reputation = int(max(1, min(40, round((overall - 40) * 0.5 + 6 * rng.next()))))
    return Rookie(
        id=rid, name=_name(rng, names), role=role, country=rng.pick(COUNTRIES.get(region, ("KR",))),
        league=league, team=origin.id if origin else "", season=season, experience=rng.int(40),
        attributes=attributes, overall=overall, potential=potential,
        aggression=1 + rng.int(20), leadership=3 + rng.int(10), reputation=reputation,
        salary=ratings.asking_salary(overall, reputation, region),
        pool=pool, signatures=[c for c, games in pool[:2] if games >= 15],
    )


def _name(rng: Rng, taken: set[str]) -> str:
    for _ in range(50):
        if rng.chance(0.25):
            name = rng.pick(_WORDS) + (str(rng.int(100)) if rng.chance(0.3) else "")
        else:
            name = rng.pick(_START) + rng.pick(_END)
            if rng.chance(0.15):
                name += rng.pick(_END)
        if name.lower() not in taken:
            return name
    return f"Rookie{rng.int(10000)}"
