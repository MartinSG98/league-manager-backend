"""What the manager's analyst sends: a report on the next opponent on every match day, and a
preview of the next balance patch a few days before it lands.

How much a report says depends on the analyst's scouting (see staff.scouting_level):
1. the opponent's form, results and lineup with each player's signature champions
2. plus what each player has been playing this season and the team's game plan
3. plus the bans that hurt them most and their most dangerous player
4. plus their weak spots: the weakest starter, chemistry problems, low morale

The patch preview reads the same numbers the balance team does (see patches.release_patch):
the champions picked and banned most on this patch are the nerf targets. A sharp reader of the
meta names them in order with how likely each is, sends the preview four days ahead and spots a
mid-season update; a weak one sends it two days ahead and gets some names wrong."""

from datetime import timedelta

from app.game import champ_select as cs
from app.game import matchday, patches, roster
from app.game import staff as staffing
from app.game.catalog import ROLES, Catalog
from app.game.state import Career, ChampSelect, InboxMessage, Match


def _message(career: Career, kind: str, subject: str, body: str, report: dict | None = None) -> InboxMessage:
    msg = InboxMessage(id=career.next_message, day=career.day, kind=kind, subject=subject, body=body,  # type: ignore[arg-type]
                       report=report)
    career.inbox.append(msg)
    career.next_message += 1
    return msg


def _form(cat: Catalog, career: Career, team: str, last: int = 5) -> list[dict]:
    played = [m for m in career.matches.values() if m.winner and team in (m.home, m.away)]
    played.sort(key=lambda m: (m.day, m.id))
    out = []
    for m in played[-last:]:
        other = m.away if m.home == team else m.home
        mine, theirs = (m.score[0], m.score[1]) if m.home == team else (m.score[1], m.score[0])
        out.append({"won": m.winner == team, "against": cat.teams[other].tag if other else "?", "score": f"{mine}-{theirs}"})
    return out


def _season_champions(career: Career, pid: str, top: int = 3) -> list[list]:
    played = career.players[pid].season.champions
    return [[c, n] for c, n in sorted(played.items(), key=lambda kv: -kv[1])[:top]]


def scouting_report(cat: Catalog, career: Career, match: Match) -> InboxMessage:
    """The analyst's report on the manager's next opponent, sent to the inbox."""
    me = career.teams[career.team]
    opp_id = match.away if match.home == career.team else match.home
    assert opp_id is not None
    opp = career.teams[opp_id]
    analyst = cat.staff.get(me.analyst or "")
    level = staffing.scouting_level(staffing.attribute(cat, career, career.team, "scouting"))
    comp = career.competitions[match.competition]
    lineup = matchday.lineup_of(cat, career, opp_id)
    form = _form(cat, career, opp_id)

    players = []
    for role in ROLES:
        pid = lineup[role]
        p = cat.players[pid]
        row = {"id": pid, "name": p.name, "role": role, "photo": p.photo,
               "overall": roster.overall(cat, career, pid), "form": round(career.players[pid].form, 1),
               "signatures": list(p.signatures)}
        if level >= 2:
            row["recent"] = _season_champions(career, pid)
        players.append(row)

    report: dict = {
        "match": match.id, "opponent": opp_id, "level": level,
        "analyst": analyst.name if analyst else None,
        "competition": comp.name, "label": match.label, "best_of": match.best_of,
        "form": form, "players": players,
    }
    when = "Tomorrow" if match.day > career.day else "Today"
    lines = [f"{when}: {cat.teams[opp_id].name}, {comp.name} {match.label}, best of {match.best_of}."]
    if form:
        record = "".join("W" if f["won"] else "L" for f in form)
        lines.append(f"Recent form: {record} (oldest first).")
    else:
        lines.append("No results yet this season.")

    if level >= 2:
        report["plan"] = opp.tactics.model_dump()
        t = opp.tactics
        lines.append(f"They play a {t.style} game, jungle {t.lane}, objectives: {t.objectives}.")

    if level >= 3:
        mine = cs.DraftSide(career.team, matchday.lineup_of(cat, career, career.team), me.tactics)
        theirs = cs.DraftSide(opp_id, lineup, opp.tactics)
        select = ChampSelect(locked=matchday.fearless_locks(match))
        bans = cs.ban_options(cat, career, select, "blue", mine, theirs, limit=5)
        report["bans"] = [b["champion"] for b in bans]
        lines.append("Ban priorities: " + ", ".join(cat.champions[b["champion"]].name for b in bans) + ".")
        star = max(players, key=lambda r: r["overall"] + r["form"] * 2)
        why = f"in form ({star['form']:+.1f})" if star["form"] >= 1 else f"their best player (OVR {star['overall']})"
        report["threat"] = {"id": star["id"], "name": star["name"], "why": why}
        lines.append(f"Watch out for {star['name']}, {why}.")

    if level >= 4:
        weak: list[str] = []
        low = min(players, key=lambda r: r["overall"])
        weak.append(f"{low['name']} ({low['role']}) is their weakest starter (OVR {low['overall']})")
        chem, reasons = roster.chemistry(cat, career, opp, lineup)
        if chem < 0:
            weak += [r for r in reasons if "barrier" in r or "learning" in r or "Nobody" in r]
        unhappy = [cat.players[pid].name for pid in lineup.values() if career.players[pid].morale < 55]
        if unhappy:
            weak.append(f"Morale is low for {', '.join(unhappy)}")
        report["weaknesses"] = weak
        lines.append("Weak spots: " + "; ".join(weak) + ".")

    if level < 4:
        lines.append("A sharper analyst would find out more.")
    who = analyst.name if analyst else "Nobody on the staff"
    return _message(career, "scouting", f"Scouting report: {cat.teams[opp_id].name}", f"From {who}.\n" + "\n".join(lines),
                    report)


# ---------- the next patch ----------


def preview_lead(meta_skill: int) -> int:
    """Days before a patch the preview arrives."""
    return 4 if meta_skill >= 12 else 2


def _likelihood(chance: float) -> str:
    return "very likely" if chance >= 0.7 else "likely" if chance >= 0.5 else "possible"


def patch_preview(cat: Catalog, career: Career) -> InboxMessage | None:
    """The analyst's read on the coming patch, if it is due today."""
    meta = career.meta
    skill = staffing.attribute(cat, career, career.team, "meta")
    if meta.next_patch is None or career.day != meta.next_patch - timedelta(days=preview_lead(skill)):
        return None
    analyst = cat.staff.get(career.teams[career.team].analyst or "")
    games = max(1, meta.games)
    usage = {cid: meta.picks.get(cid, 0) + 0.7 * meta.bans.get(cid, 0) for cid in cat.champions}
    contested = sorted(cat.champions, key=lambda cid: -(usage[cid] / games + max(0.0, meta.power[cid]) / 10))

    def chance(cid: str) -> float:
        return min(0.9, 0.25 + usage[cid] / games + max(0.0, meta.power[cid]) / 10)

    name = cat.champions
    version = patches.next_version(meta.version, career.season)
    lines: list[str] = []
    if skill >= 15:
        lines += [f"{name[c].name}: nerf {_likelihood(chance(c))}" for c in contested[:6]]
    elif skill >= 10:
        lines.append("Likely nerfs: " + ", ".join(name[c].name for c in contested[:4]) + ".")
    else:
        # A shaky read: the right idea, with a name from further down the list mixed in.
        guess = contested[:2] + [contested[9]]
        lines.append("I think these get nerfed: " + ", ".join(name[c].name for c in guess) + ". Not sure, though.")
    if skill >= 10:
        forgotten = sorted((c for c in cat.champions if meta.power[c] < 0.5),
                           key=lambda c: (usage[c], meta.power[c]))[: 3 if skill >= 15 else 2]
        lines.append("Due a buff, maybe: " + ", ".join(name[c].name for c in forgotten) + ".")
    number = int(version.split(".")[1])
    if skill >= 12 and number % patches.BIG_PATCH_EVERY == 0:
        lines.append("This is a mid-season update: expect a whole class of champions to move.")
    who = analyst.name if analyst else "Nobody on the staff"
    return _message(career, "patch", f"Patch {version} preview", f"From {who}, the patch lands on "
                    f"{meta.next_patch:%A %d %B}.\n" + "\n".join(lines))
