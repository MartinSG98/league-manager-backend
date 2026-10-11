"""Champion select in tournament draft order, with fearless across a series.

A champion helps the player on it by three things: how well that player knows it (mastery from
career games), how strong it is on the current patch, and whether it is played in its own role.
The AI scores every legal option on those, adds what the composition still needs (both damage
types, someone to stand in front, a power curve that fits the tactic) and bans what the enemy
players are best on. The same scoring powers the assistant's suggestions for the manager."""

from dataclasses import dataclass, field
from functools import lru_cache

from app.game import roster
from app.game.catalog import ROLES, Catalog, Champion
from app.game.errors import IllegalAction
from app.game.rng import Rng
from app.game.state import Career, ChampSelect, Side, Tactics

ORDER: tuple[tuple[Side, str], ...] = (
    ("blue", "ban"), ("red", "ban"), ("blue", "ban"), ("red", "ban"), ("blue", "ban"), ("red", "ban"),
    ("blue", "pick"), ("red", "pick"), ("red", "pick"), ("blue", "pick"), ("blue", "pick"), ("red", "pick"),
    ("red", "ban"), ("blue", "ban"), ("red", "ban"), ("blue", "ban"),
    ("red", "pick"), ("blue", "pick"), ("blue", "pick"), ("red", "pick"),
)

OFF_ROLE = -5.0
DUO_POWER = 0.6  # team power per point of champion duo synergy

# Champion pairs that work well (or badly) together, carried over from riftlike's hand-picked list.
_DUOS = [
    ("Kalista", "Renata Glasc", 2),
    ("Kalista", "Rell", 1),
    ("Kalista", "Alistar", 1),
    ("Xayah", "Rakan", 2),
    ("Lucian", "Nami", 2),
    ("Lucian", "Braum", 1),
    ("Jinx", "Lulu", 1),
    ("Jinx", "Thresh", 1),
    ("Kai'Sa", "Nautilus", 1),
    ("Kai'Sa", "Rell", 1),
    ("Kai'Sa", "Alistar", 1),
    ("Ezreal", "Karma", 1),
    ("Zeri", "Yuumi", 1),
    ("Zeri", "Lulu", 1),
    ("Twitch", "Yuumi", 1),
    ("Aphelios", "Lulu", 1),
    ("Aphelios", "Thresh", 1),
    ("Varus", "Rell", 1),
    ("Caitlyn", "Lux", 1),
    ("Caitlyn", "Morgana", 1),
    ("Miss Fortune", "Leona", 1),
    ("Draven", "Leona", 1),
    ("Draven", "Nautilus", 1),
    ("Samira", "Nautilus", 2),
    ("Samira", "Rell", 1),
    ("Tristana", "Nautilus", 1),
    ("Kog'Maw", "Lulu", 2),
    ("Vayne", "Lulu", 1),
    ("Sivir", "Karma", 1),
    ("Smolder", "Milio", 1),
    ("Yunara", "Milio", 1),
    ("Senna", "Tahm Kench", 1),
    ("Ezreal", "Leona", -1),
    ("Kog'Maw", "Pyke", -1),
    ("Caitlyn", "Bard", -1),
    ("Jinx", "Pyke", -1),
    ("Jarvan IV", "Orianna", 1),
    ("Jarvan IV", "Galio", 1),
    ("Wukong", "Yasuo", 2),
    ("Diana", "Yasuo", 1),
    ("Nocturne", "Twisted Fate", 1),
    ("Vi", "Ahri", 1),
    ("Xin Zhao", "Galio", 1),
    ("Sejuani", "Galio", 1),
    ("Sejuani", "Orianna", 1),
    ("Maokai", "Orianna", 1),
    ("Nidalee", "Corki", 1),
    ("Lee Sin", "Syndra", 1),
    ("Ivern", "Kassadin", -1),
    ("Malphite", "Orianna", 1),
    ("Gragas", "Yasuo", 1),
    ("Alistar", "Yasuo", 1),
    ("Rakan", "Yone", 1),
]


@dataclass
class DraftSide:
    team: str
    lineup: dict[str, str]  # role -> player id
    tactics: Tactics
    cache: dict[tuple[str, str], float] = field(default_factory=dict)

    def power(self, cat: Catalog, career: Career, champion: str, role: str) -> float:
        """champion_power for whoever plays `role` on this side, remembered for the whole draft."""
        key = (champion, role)
        if key not in self.cache:
            self.cache[key] = champion_power(cat, career, self.lineup[role], champion, role)
        return self.cache[key]


@lru_cache(maxsize=8)
def _duos(cat: Catalog) -> dict[frozenset[str], int]:
    out = {}
    for a, b, value in _DUOS:
        ia, ib = cat.champion_id(a), cat.champion_id(b)
        if ia and ib:
            out[frozenset((ia, ib))] = value
    return out


def duo_value(cat: Catalog, champion: str, partners: list[str]) -> int:
    duos = _duos(cat)
    return sum(duos.get(frozenset((champion, other)), 0) for other in partners)


@lru_cache(maxsize=8)
def _by_role(cat: Catalog) -> dict[str, tuple[Champion, ...]]:
    return {role: tuple(c for c in cat.champions.values() if role in c.roles) for role in ROLES}


def comfort(mastery: int) -> float:
    """-2.6 on a champion never played, 0 at a pocket pick, +2.6 on a comfort pick, ~+5 on a signature."""
    return (mastery - 35) * 0.075


def champion_power(cat: Catalog, career: Career, pid: str, champion: str, role: str) -> float:
    """How much a champion adds to (or takes from) this player's rating in this game."""
    champ = cat.champions[champion]
    value = comfort(roster.mastery(cat, career, pid, champion)) + career.meta.power.get(champion, 0.0) * 0.8
    if role not in champ.roles:
        value += OFF_ROLE
    return value


def turn(select: ChampSelect) -> tuple[Side, str] | None:
    return ORDER[select.step] if select.step < len(ORDER) else None


def unavailable(select: ChampSelect) -> set[str]:
    return set(select.blue_bans) | set(select.red_bans) | set(select.blue_picks.values()) | set(
        select.red_picks.values()) | set(select.locked)


def picks_of(select: ChampSelect, side: Side) -> dict[str, str]:
    return select.blue_picks if side == "blue" else select.red_picks


def bans_of(select: ChampSelect, side: Side) -> list[str]:
    return select.blue_bans if side == "blue" else select.red_bans


# ---------- composition ----------


def _comp_need(cat: Catalog, picked: list[Champion], champ: Champion, tactics: Tactics, slots_left: int) -> float:
    ad = sum(1 for c in picked if c.damage == "AD") + sum(0.5 for c in picked if c.damage == "MX")
    ap = sum(1 for c in picked if c.damage == "AP") + sum(0.5 for c in picked if c.damage == "MX")
    value = 0.0
    if champ.damage == "AP" and ap < 1 and ad >= 2:
        value += 1.0 + (1.0 if slots_left <= 2 else 0)
    if champ.damage == "AD" and ad < 1 and ap >= 2:
        value += 1.0 + (1.0 if slots_left <= 2 else 0)
    front = sum(1 for c in picked if c.cls == "Tank") + sum(0.5 for c in picked if c.cls == "Fighter")
    if front < 1 and champ.cls in ("Tank", "Fighter"):
        value += 0.6 + (1.2 if slots_left <= 2 else 0)
    if tactics.style == "early" and champ.focus == "early":
        value += 0.6
    elif tactics.style == "scaling" and champ.focus == "late":
        value += 0.6
    value += DUO_POWER * duo_value(cat, champ.id, [c.id for c in picked])
    return value


def composition_modifier(cat: Catalog, picks: dict[str, str]) -> tuple[float, list[str]]:
    """Penalties for a finished five with one damage type or nobody in front."""
    champs = [cat.champions[c] for c in picks.values()]
    notes: list[str] = []
    value = 0.0
    ad = sum(1 for c in champs if c.damage == "AD") + sum(0.5 for c in champs if c.damage == "MX")
    ap = sum(1 for c in champs if c.damage == "AP") + sum(0.5 for c in champs if c.damage == "MX")
    if min(ad, ap) < 1:
        value -= 2.0
        notes.append("One damage type, easy to itemise against")
    elif min(ad, ap) < 1.5:
        value -= 0.7
        notes.append("Damage leans heavily one way")
    front = sum(1 for c in champs if c.cls == "Tank") + sum(0.5 for c in champs if c.cls == "Fighter")
    if front < 1:
        value -= 1.5
        notes.append("Nobody to stand in front")
    ids = [c.id for c in champs]
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            duo = _duos(cat).get(frozenset((a, b)), 0)
            if duo:
                value += DUO_POWER * duo
                verb = "combo" if duo > 0 else "clash"
                notes.append(f"{cat.champions[a].name} and {cat.champions[b].name} {verb} ({duo:+d})")
    return value, notes


def focus_bias(cat: Catalog, picks: dict[str, str]) -> float:
    """Positive for an early-game composition, negative for a scaling one."""
    champs = [cat.champions[c] for c in picks.values()]
    return 0.5 * (sum(1 for c in champs if c.focus == "early") - sum(1 for c in champs if c.focus == "late"))


# ---------- choices ----------


def options(cat: Catalog, career: Career, select: ChampSelect, side: Side, me: DraftSide, enemy: DraftSide,
            limit: int = 12) -> list[dict]:
    """Best legal picks for this side: champion, role and the reasons, best first."""
    taken = unavailable(select)
    mine = picks_of(select, side)
    picked = [cat.champions[c] for c in mine.values()]
    slots_left = 5 - len(mine)
    theirs = picks_of(select, "red" if side == "blue" else "blue")
    rows = []
    for role in ROLES:
        if role in mine:
            continue
        pid = me.lineup[role]
        for champ in _by_role(cat)[role]:
            if champ.id in taken:
                continue
            power = me.power(cat, career, champ.id, role)
            need = _comp_need(cat, picked, champ, me.tactics, slots_left)
            counter = 0.0
            if role in theirs:
                counter = lane_edge(cat, champ, cat.champions[theirs[role]])
            rows.append({"champion": champ.id, "role": role, "player": pid, "power": round(power, 2),
                         "score": power + need + counter * 0.5, "need": round(need, 2), "counter": round(counter, 2)})
    rows.sort(key=lambda r: -r["score"])
    return rows[:limit]


def ban_options(cat: Catalog, career: Career, select: ChampSelect, side: Side, me: DraftSide, enemy: DraftSide,
                limit: int = 12) -> list[dict]:
    taken = unavailable(select)
    enemy_side: Side = "red" if side == "blue" else "blue"
    open_enemy = [r for r in ROLES if r not in picks_of(select, enemy_side)]
    rows = []
    for champ in cat.champions.values():
        if champ.id in taken:
            continue
        threat = max((enemy.power(cat, career, champ.id, r) for r in open_enemy if r in champ.roles), default=-9.0)
        if threat <= -9:
            continue
        own = max((me.power(cat, career, champ.id, r) for r in ROLES if r in champ.roles), default=-9.0)
        score = threat - max(0.0, own) * 0.4
        rows.append({"champion": champ.id, "score": score, "threat": round(threat, 2)})
    rows.sort(key=lambda r: -r["score"])
    return rows[:limit]


def lane_edge(cat: Catalog, mine: Champion, theirs: Champion) -> float:
    """A small, antisymmetric lane-counter edge from class and power curve."""
    beats = {("Fighter", "Marksman"), ("Assassin", "Mage"), ("Assassin", "Marksman"), ("Tank", "Assassin"),
             ("Mage", "Tank"), ("Marksman", "Tank"), ("Fighter", "Mage"), ("Mage", "Fighter")}
    value = 0.0
    if (mine.cls, theirs.cls) in beats:
        value += 0.6
    if (theirs.cls, mine.cls) in beats:
        value -= 0.6
    order = {"early": 1, "mid": 0, "late": -1}
    value += 0.3 * (order[mine.focus] - order[theirs.focus])
    return value


def ai_step(cat: Catalog, career: Career, select: ChampSelect, sides: dict[str, DraftSide], rng: Rng) -> None:
    current = turn(select)
    if current is None:
        return
    side, kind = current
    me, enemy = sides[side], sides["red" if side == "blue" else "blue"]
    if kind == "ban":
        rows = ban_options(cat, career, select, side, me, enemy, limit=6)
        pool = rows[:4] if rows else []
        choice = max(pool, key=lambda r: r["score"] + rng.next() * 1.5)["champion"] if pool else None
        if choice is None:
            choice = next(c for c in cat.champions if c not in unavailable(select))
        ban(select, side, choice)
    else:
        rows = options(cat, career, select, side, me, enemy, limit=6)
        if rows:
            best = max(rows[:4], key=lambda r: r["score"] + rng.next() * 1.2)
            pick(cat, select, side, best["champion"], best["role"])
        else:
            # Everything in role is gone (fearless late in a series): take anything left.
            role = next(r for r in ROLES if r not in picks_of(select, side))
            choice = next(c for c in cat.champions if c not in unavailable(select))
            pick(cat, select, side, choice, role)


def ban(select: ChampSelect, side: Side, champion: str) -> None:
    current = turn(select)
    if current != (side, "ban"):
        raise IllegalAction("It is not your ban")
    if champion in unavailable(select):
        raise IllegalAction("That champion is not available")
    bans_of(select, side).append(champion)
    select.step += 1


def pick(cat: Catalog, select: ChampSelect, side: Side, champion: str, role: str) -> None:
    current = turn(select)
    if current != (side, "pick"):
        raise IllegalAction("It is not your pick")
    if champion not in cat.champions:
        raise IllegalAction("Unknown champion")
    if champion in unavailable(select):
        raise IllegalAction("That champion is not available")
    mine = picks_of(select, side)
    if role in mine:
        raise IllegalAction(f"You already have a {role}")
    mine[role] = champion
    select.step += 1


def run_ai(cat: Catalog, career: Career, select: ChampSelect, sides: dict[str, DraftSide], rng: Rng,
           human: Side | None) -> None:
    """Play AI turns until it is the human side's turn or champion select is over."""
    while True:
        current = turn(select)
        if current is None or current[0] == human:
            return
        ai_step(cat, career, select, sides, rng)
