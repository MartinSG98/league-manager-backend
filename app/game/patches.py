"""The meta and the patches that move it.

Every champion has a power on the current patch, roughly -3 (unplayable) to +4 (first-pick or
ban). A career starts from real 2026 pro presence: the most picked and banned champions are the
strongest. A new patch lands every two weeks. Riot's balance team in here nerfs what the pros in
this career pick and ban the most and buffs what nobody touches, so the meta keeps turning
over, and every sixth patch is a bigger mid-season patch that shifts a whole class."""

from datetime import date, timedelta

from app.game.catalog import Catalog
from app.game.rng import Rng
from app.game.state import Career, InboxMessage, MetaState, Patch, PatchChange

PATCH_EVERY = timedelta(days=14)
BIG_PATCH_EVERY = 6
POWER_MIN, POWER_MAX = -3.5, 5.0

_ABILITIES = ("Q", "W", "E", "R", "passive", "base stats")
_BUFF_LINES = ("damage increased", "cooldown lowered", "mana cost lowered", "scaling increased", "duration increased")
_NERF_LINES = ("damage reduced", "cooldown raised", "mana cost raised", "scaling reduced", "range reduced")


def starting_meta(cat: Catalog, version: str) -> MetaState:
    ranked = sorted(cat.champions.values(), key=lambda c: c.presence)
    power: dict[str, float] = {}
    for i, champ in enumerate(ranked):
        percentile = i / max(1, len(ranked) - 1)
        value = -3 + 7 * percentile**1.3 + max(-0.5, min(0.5, (champ.winrate - 50) / 8))
        power[champ.id] = round(max(POWER_MIN, min(POWER_MAX, value)), 2)
    return MetaState(version=version, power=power)


def tier(power: float) -> str:
    if power >= 3:
        return "S"
    if power >= 1.5:
        return "A"
    if power >= 0:
        return "B"
    if power >= -1.5:
        return "C"
    return "D"


def first_patch_day(season: int) -> date:
    return date(season, 1, 6)


def next_version(version: str, season: int) -> str:
    major, _, minor = version.partition(".")
    if int(major) != season % 100:
        return f"{season % 100}.1"
    return f"{major}.{int(minor) + 1}"


def release_patch(cat: Catalog, career: Career, rng: Rng) -> Patch:
    meta = career.meta
    version = next_version(meta.version, career.season)
    number = int(version.split(".")[1])
    big = number % BIG_PATCH_EVERY == 0

    # Usage on the outgoing patch, picks count once and bans a little less.
    usage = {cid: meta.picks.get(cid, 0) + 0.7 * meta.bans.get(cid, 0) for cid in cat.champions}
    games = max(1, meta.games)
    changes: list[PatchChange] = []
    touched: set[str] = set()

    def change(cid: str, delta: float) -> None:
        if cid in touched:
            return
        touched.add(cid)
        name = cat.champions[cid].name
        line = rng.pick(_BUFF_LINES if delta > 0 else _NERF_LINES)
        note = f"{name} {rng.pick(_ABILITIES)} {line}"
        meta.power[cid] = round(max(POWER_MIN, min(POWER_MAX, meta.power[cid] + delta)), 2)
        changes.append(PatchChange(champion=cid, delta=round(delta, 2), note=note))

    # Nerfs: whatever showed up in more than a third of drafts is a target, the more the likelier.
    contested = sorted(cat.champions, key=lambda cid: -(usage[cid] / games + max(0.0, meta.power[cid]) / 10))
    nerfs = 3 + rng.int(3) + (2 if big else 0)
    for cid in contested[:12]:
        if len([c for c in changes if c.delta < 0]) >= nerfs:
            break
        presence = usage[cid] / games
        if rng.chance(min(0.9, 0.25 + presence + max(0.0, meta.power[cid]) / 10)):
            change(cid, -(0.8 + rng.next() * 1.4))

    # Buffs: mostly champions nobody plays, sometimes a mid-tier pick.
    forgotten = [cid for cid in cat.champions if meta.power[cid] < 0.5 and cid not in touched]
    buffs = 3 + rng.int(4) + (2 if big else 0)
    for cid in rng.shuffle(forgotten)[:buffs]:
        change(cid, 0.8 + rng.next() * 1.6)

    headline = f"Patch {version}"
    if big:
        cls = rng.pick(sorted({c.cls for c in cat.champions.values()}))
        shift = rng.pick((1.0, -1.0))
        for champ in cat.champions.values():
            if champ.cls == cls and champ.id not in touched:
                meta.power[champ.id] = round(max(POWER_MIN, min(POWER_MAX, meta.power[champ.id] + shift)), 2)
        verb = "rise" if shift > 0 else "fall"
        headline = f"Patch {version}: mid-season update, {cls}s {verb}"

    # Everyone drifts a little towards the middle so nothing stays on top forever.
    for cid in cat.champions:
        if cid not in touched:
            meta.power[cid] = round(meta.power[cid] * 0.97, 2)

    patch = Patch(version=version, day=career.day, headline=headline, changes=changes)
    meta.version = version
    meta.history.append(patch)
    meta.picks, meta.bans, meta.games = {}, {}, 0
    meta.next_patch = career.day + PATCH_EVERY

    buffs_txt = ", ".join(cat.champions[c.champion].name for c in changes if c.delta > 0)
    nerfs_txt = ", ".join(cat.champions[c.champion].name for c in changes if c.delta < 0)
    body = f"Buffed: {buffs_txt or 'nobody'}.\nNerfed: {nerfs_txt or 'nobody'}."
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind="patch", subject=headline, body=body))
    career.next_message += 1
    return patch


def record_draft(career: Career, picks: list[str], bans: list[str]) -> None:
    meta = career.meta
    meta.games += 1
    for cid in picks:
        meta.picks[cid] = meta.picks.get(cid, 0) + 1
    for cid in bans:
        meta.bans[cid] = meta.bans.get(cid, 0) + 1
