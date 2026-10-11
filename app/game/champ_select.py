"""Champion select in tournament draft order, with fearless across a series.

A champion helps the player on it by three things: how well that player knows it (mastery from
career games), how strong it is on the current patch, and whether it is played in its own role.
The AI scores every legal option on those, adds what the composition still needs (both damage
types, someone to stand in front, a power curve that fits the tactic, champion combos) and the
lane it wins or loses, and bans what the enemy players are best on. The same scoring powers the
assistant's suggestions and the arrows on the manager's champion grid, which also list the reasons."""

from dataclasses import dataclass, field
from functools import lru_cache

from app.game import roster
from app.game.catalog import ROLES, Catalog, Champion
from app.game.errors import IllegalAction
from app.game.patches import tier
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
LANE_WEIGHT = 0.5  # how much a lane counter counts for in a pick, next to the player and the composition

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
class Note:
    """One reason a champion is a good or bad choice, in the same units as the score it adds to."""

    kind: str  # comfort, meta, role, comp, combo, lane, own
    value: float
    text: str


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


def _comfort_text(name: str, mastery: int) -> str:
    if mastery >= 75:
        return f"{name}: signature champion (mastery {mastery})"
    if mastery >= 50:
        return f"{name}: comfort pick (mastery {mastery})"
    if mastery >= 25:
        return f"{name}: pocket pick (mastery {mastery})"
    if mastery > 0:
        return f"{name} has barely played it (mastery {mastery})"
    return f"{name} has never played it on stage"


def champion_power(cat: Catalog, career: Career, pid: str, champion: str, role: str,
                   notes: list[Note] | None = None) -> float:
    """How much a champion adds to (or takes from) this player's rating in this game. Pass `notes`
    to also collect the reasons."""
    champ = cat.champions[champion]
    known = roster.mastery(cat, career, pid, champion)
    fit = comfort(known)
    meta = career.meta.power.get(champion, 0.0) * 0.8
    value = fit + meta
    if role not in champ.roles:
        value += OFF_ROLE
    if notes is not None:
        name = cat.players[pid].name
        notes.append(Note("comfort", fit, _comfort_text(name, known)))
        notes.append(Note("meta", meta, f"{tier(meta / 0.8)} tier on patch {career.meta.version}"))
        if role not in champ.roles:
            notes.append(Note("role", OFF_ROLE, f"Off-role for {name}"))
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


def other_side(side: Side) -> Side:
    return "red" if side == "blue" else "blue"


# ---------- composition ----------


def _comp_need(cat: Catalog, picked: list[Champion], champ: Champion, tactics: Tactics, slots_left: int,
               notes: list[Note] | None = None) -> float:
    """What a champion adds to the composition so far: the missing damage type, a frontline, the
    game plan and champion combos. Negative when it makes a lopsided composition worse."""
    ad = sum(1 for c in picked if c.damage == "AD") + sum(0.5 for c in picked if c.damage == "MX")
    ap = sum(1 for c in picked if c.damage == "AP") + sum(0.5 for c in picked if c.damage == "MX")
    late = slots_left <= 2
    parts: list[Note] = []
    if champ.damage == "AP" and ap < 1 and ad >= 2:
        parts.append(Note("comp", 2.0 if late else 1.0, "Adds the magic damage the team lacks"))
    elif champ.damage == "AD" and ad < 1 and ap >= 2:
        parts.append(Note("comp", 2.0 if late else 1.0, "Adds the physical damage the team lacks"))
    elif champ.damage == "AD" and ap < 1 and ad >= 2:
        parts.append(Note("comp", -1.0 if late else -0.5, "More physical damage, still no magic damage"))
    elif champ.damage == "AP" and ad < 1 and ap >= 2:
        parts.append(Note("comp", -1.0 if late else -0.5, "More magic damage, still no physical damage"))
    front = sum(1 for c in picked if c.cls == "Tank") + sum(0.5 for c in picked if c.cls == "Fighter")
    if front < 1:
        if champ.cls in ("Tank", "Fighter"):
            parts.append(Note("comp", 1.8 if late else 0.6, "Someone to stand in front"))
        elif late:
            parts.append(Note("comp", -0.6, "Still nobody to stand in front"))
    if tactics.style == "early":
        if champ.focus == "early":
            parts.append(Note("comp", 0.6, "Fits the early-game plan"))
        elif champ.focus == "late":
            parts.append(Note("comp", -0.3, "A scaling pick in an early-game plan"))
    elif tactics.style == "scaling":
        if champ.focus == "late":
            parts.append(Note("comp", 0.6, "Fits the scaling plan"))
        elif champ.focus == "early":
            parts.append(Note("comp", -0.3, "An early-game pick in a scaling plan"))
    duos = _duos(cat)
    for other in picked:
        duo = duos.get(frozenset((champ.id, other.id)), 0)
        if duo:
            verb = "Combo" if duo > 0 else "Clashes"
            parts.append(Note("combo", DUO_POWER * duo, f"{verb} with {other.name} ({duo:+d})"))
    if notes is not None:
        notes += parts
    return sum(n.value for n in parts)


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


def pick_score(cat: Catalog, career: Career, select: ChampSelect, side: Side, me: DraftSide, champ: Champion,
               role: str, notes: list[Note] | None = None) -> float:
    """What picking this champion for this role is worth: the player on it, the composition and the lane."""
    mine = picks_of(select, side)
    theirs = picks_of(select, other_side(side))
    picked = [cat.champions[c] for c in mine.values()]
    if notes is None:
        power = me.power(cat, career, champ.id, role)
    else:
        power = champion_power(cat, career, me.lineup[role], champ.id, role, notes)
    need = _comp_need(cat, picked, champ, me.tactics, 5 - len(mine), notes)
    counter = 0.0
    if role in theirs:
        enemy = cat.champions[theirs[role]]
        counter = lane_edge(cat, champ, enemy)
        if notes is not None and counter:
            text = f"Wins the lane against {enemy.name}" if counter > 0 else f"Loses the lane to {enemy.name}"
            notes.append(Note("lane", counter * LANE_WEIGHT, text))
    return power + need + counter * LANE_WEIGHT


def options(cat: Catalog, career: Career, select: ChampSelect, side: Side, me: DraftSide, enemy: DraftSide,
            limit: int = 12) -> list[dict]:
    """Best legal picks for this side: champion, role and the reasons, best first."""
    taken = unavailable(select)
    mine = picks_of(select, side)
    picked = [cat.champions[c] for c in mine.values()]
    slots_left = 5 - len(mine)
    theirs = picks_of(select, other_side(side))
    rows = []
    for role in ROLES:
        if role in mine:
            continue
        pid = me.lineup[role]
        for champ in _by_role(cat)[role]:
            if champ.id in taken:
                continue
            # The same sum as pick_score, without building the reasons for every option the AI looks at.
            power = me.power(cat, career, champ.id, role)
            need = _comp_need(cat, picked, champ, me.tactics, slots_left)
            counter = 0.0
            if role in theirs:
                counter = lane_edge(cat, champ, cat.champions[theirs[role]])
            rows.append({"champion": champ.id, "role": role, "player": pid, "power": round(power, 2),
                         "score": power + need + counter * LANE_WEIGHT, "need": round(need, 2),
                         "counter": round(counter, 2)})
    rows.sort(key=lambda r: -r["score"])
    return rows[:limit]


def ban_score(cat: Catalog, career: Career, select: ChampSelect, side: Side, me: DraftSide, enemy: DraftSide,
              champ: Champion, notes: list[Note] | None = None) -> float | None:
    """How much banning a champion takes away from the enemy, or None if nobody left on their side plays it.

    The threat is the best enemy player still to pick on it, plus combos with what they already have
    and the lane it would win against our pick. Banning a champion we would play ourselves costs a little."""
    theirs = picks_of(select, other_side(side))
    ours = picks_of(select, side)
    open_enemy = [r for r in ROLES if r not in theirs and r in champ.roles]
    if not open_enemy:
        return None
    role = max(open_enemy, key=lambda r: enemy.power(cat, career, champ.id, r))
    if notes is None:
        threat = enemy.power(cat, career, champ.id, role)
    else:
        threat = champion_power(cat, career, enemy.lineup[role], champ.id, role, notes)
    duo = duo_value(cat, champ.id, list(theirs.values()))
    if duo:
        threat += DUO_POWER * duo
        if notes is not None:
            partners = [cat.champions[c].name for c in theirs.values() if _duos(cat).get(frozenset((champ.id, c)))]
            verb = "Combos" if duo > 0 else "Clashes"
            notes.append(Note("combo", DUO_POWER * duo, f"{verb} with their {', '.join(partners)}"))
    if role in ours:
        edge = lane_edge(cat, champ, cat.champions[ours[role]])
        threat += edge * LANE_WEIGHT
        if notes is not None and edge:
            mine = cat.champions[ours[role]].name
            text = f"Would win the lane against your {mine}" if edge > 0 else f"Would lose the lane to your {mine}"
            notes.append(Note("lane", edge * LANE_WEIGHT, text))
    open_ours = [r for r in ROLES if r not in ours and r in champ.roles]
    best = max(open_ours, key=lambda r: me.power(cat, career, champ.id, r), default=None)
    cost = max(0.0, me.power(cat, career, champ.id, best)) * 0.4 if best else 0.0
    if notes is not None and cost and best:
        pid = me.lineup[best]
        known = roster.mastery(cat, career, pid, champ.id)
        notes.append(Note("own", -cost, f"Your {cat.players[pid].name} could play it too (mastery {known})"))
    return threat - cost


def ban_options(cat: Catalog, career: Career, select: ChampSelect, side: Side, me: DraftSide, enemy: DraftSide,
                limit: int = 12) -> list[dict]:
    taken = unavailable(select)
    rows = []
    for champ in cat.champions.values():
        if champ.id in taken:
            continue
        score = ban_score(cat, career, select, side, me, enemy, champ)
        if score is None:
            continue
        rows.append({"champion": champ.id, "score": score, "threat": round(score, 2)})
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


# ---------- the manager's champion grid ----------

_SITUATIONAL = {"lane", "comp", "combo"}


def verdict(kind: str, score: float, notes: list[Note]) -> int:
    """-2..2, the arrow on a champion in the manager's grid.

    Picks: up for a strong option. Down only when something about this game makes it worse: a lost
    lane, a lopsided composition, a clash, a champion weak on the patch. A champion the player does
    not know gets no arrow on that alone; the mastery badge already says so.
    Bans: up for a real threat, down when the champion matters more to us than to them."""
    if score >= 4.5:
        return 2
    if kind == "ban":
        if score >= 2.5:
            return 1
        own = sum(n.value for n in notes if n.kind == "own")
        return -1 if own <= -0.8 and score < 1 else 0
    if score >= 2:
        return 1
    bad = any((n.kind in _SITUATIONAL and n.value <= -0.25) or (n.kind == "meta" and n.value <= -1.2) for n in notes)
    if bad and score <= -5:
        return -2
    if bad and score <= -1.5:
        return -1
    return 0


def _entry(kind: str, score: float, notes: list[Note], role: str | None) -> dict:
    return {
        "role": role, "score": round(score, 2), "verdict": verdict(kind, score, notes),
        "notes": [{"text": n.text, "value": round(n.value, 2)} for n in notes],
    }


def board(cat: Catalog, career: Career, select: ChampSelect, side: Side, me: DraftSide, enemy: DraftSide) -> dict:
    """Every available champion scored for this side's current ban or pick, with the reasons.

    For a pick each champion is scored in every open role it plays (`others` holds the roles after
    the best one), and `fits` is false when it plays none of them. For a ban `fits` is false when
    nobody left on the enemy side plays it."""
    current = turn(select)
    if current is None:
        return {"kind": None, "champions": {}}
    kind = current[1]
    taken = unavailable(select)
    out: dict[str, dict] = {}
    if kind == "ban":
        for champ in cat.champions.values():
            if champ.id in taken:
                continue
            notes: list[Note] = []
            score = ban_score(cat, career, select, side, me, enemy, champ, notes)
            if score is None:
                out[champ.id] = {"role": None, "score": None, "verdict": 0, "fits": False, "others": {},
                                 "notes": [{"text": "Nobody left on their side plays it", "value": 0}]}
                continue
            theirs = picks_of(select, other_side(side))
            role = max((r for r in ROLES if r not in theirs and r in champ.roles),
                       key=lambda r: enemy.power(cat, career, champ.id, r))
            out[champ.id] = _entry("ban", score, notes, role) | {"fits": True, "others": {}}
        return {"kind": kind, "champions": out}

    open_roles = [r for r in ROLES if r not in picks_of(select, side)]
    for champ in cat.champions.values():
        if champ.id in taken:
            continue
        roles = [r for r in open_roles if r in champ.roles]
        entries = {}
        for role in roles or open_roles:
            notes = []
            entries[role] = _entry("pick", pick_score(cat, career, select, side, me, champ, role, notes), notes, role)
        best = max(entries, key=lambda r: entries[r]["score"])
        others = {r: e for r, e in entries.items() if r != best} if roles else {}
        out[champ.id] = entries[best] | {"fits": bool(roles), "others": others}
    return {"kind": kind, "champions": out}


# ---------- taking turns ----------


def ai_step(cat: Catalog, career: Career, select: ChampSelect, sides: dict[str, DraftSide], rng: Rng) -> None:
    current = turn(select)
    if current is None:
        return
    side, kind = current
    me, enemy = sides[side], sides[other_side(side)]
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
