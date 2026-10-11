"""What the client renders, worked out on the server so the UI never reimplements a rule.

Every function returns plain JSON-ready dicts with snake_case keys; the client keeps a
hand-written copy of these shapes in src/api/types.ts."""

from app.game import calendar, champ_select as cs
from app.game import competitions as comps
from app.game import draft as drafting
from app.game import matchday, patches, roster
from app.game.catalog import ROLES, Catalog, Player
from app.game.state import Career, Competition, Match, Stage

# ---------- small pieces ----------


def team_ref(cat: Catalog, team_id: str | None) -> dict | None:
    if team_id is None:
        return None
    t = cat.teams[team_id]
    return {"id": t.id, "name": t.name, "tag": t.tag, "color": t.color, "league": t.league, "region": t.region}


def player_row(cat: Catalog, career: Career, pid: str) -> dict:
    p = cat.players[pid]
    state = career.players[pid]
    origin = cat.teams.get(p.team)
    return {
        "id": p.id,
        "name": p.name,
        "role": p.role,
        "country": p.country,
        "league": p.league,
        "origin": {"id": origin.id, "name": origin.name, "tag": origin.tag} if origin else None,
        "team": state.team,
        "overall": roster.overall(cat, career, pid),
        "potential": p.potential,
        "salary": state.contract.salary if state.contract else p.salary,
        "contract_until": state.contract.until if state.contract else None,
        "reputation": p.reputation,
        "experience": p.experience,
        "signatures": list(p.signatures),
        "form": round(state.form, 1),
        "morale": state.morale,
        "fatigue": state.fatigue,
    }


def player_detail(cat: Catalog, career: Career, pid: str) -> dict:
    p = cat.players[pid]
    state = career.players[pid]
    season = state.season
    games = max(1, season.games)
    pool = []
    for rec in p.pool[:15]:
        pool.append({
            "champion": rec.champion, "games": rec.games, "winrate": rec.winrate,
            "mastery": roster.mastery(cat, career, pid, rec.champion),
            "meta": round(career.meta.power.get(rec.champion, 0.0), 1),
        })
    learned = [c for c in state.learned if c not in {r.champion for r in p.pool[:15]}]
    for cid in learned:
        pool.append({"champion": cid, "games": 0, "winrate": None, "mastery": roster.mastery(cat, career, pid, cid),
                     "meta": round(career.meta.power.get(cid, 0.0), 1)})
    return player_row(cat, career, pid) | {
        "attributes": roster.attributes(cat, career, pid),
        "aggression": p.aggression,
        "leadership": p.leadership,
        "languages": sorted(roster.languages(cat, p)),
        "stats_2026": {k: v for k, v in p.stats.items() if k != "name"},
        "games_2026": p.games,
        "pool": pool,
        "season": {
            "games": season.games, "wins": season.wins, "kills": season.kills, "deaths": season.deaths,
            "assists": season.assists, "kda": round((season.kills + season.assists) / max(1, season.deaths), 2),
            "cs_per_min": round(season.cs / max(1.0, season.minutes), 1),
            "rating": round(season.rating_sum / games, 2) if season.games else None, "mvps": season.mvps,
            "champions": sorted(season.champions.items(), key=lambda kv: -kv[1])[:8],
        },
    }


def match_summary(cat: Catalog, career: Career, match: Match) -> dict:
    comp = career.competitions[match.competition]
    return {
        "id": match.id,
        "competition": comp.id,
        "competition_name": comp.name,
        "stage": match.stage,
        "label": match.label,
        "day": match.day.isoformat(),
        "home": team_ref(cat, match.home),
        "away": team_ref(cat, match.away),
        "best_of": match.best_of,
        "fearless": match.fearless,
        "score": list(match.score),
        "winner": match.winner,
        "games": len(match.games),
    }


def _my_next_match(career: Career) -> Match | None:
    mine = [m for m in career.matches.values() if m.winner is None and career.team in (m.home, m.away)]
    return min(mine, key=lambda m: (m.day, m.id)) if mine else None


# ---------- the career ----------


def career_view(cat: Catalog, career: Career, save_id: str) -> dict:
    team = career.teams[career.team]
    nxt = _my_next_match(career)
    d = career.drafts.get(career.league)
    draft_info = None
    if career.phase == "draft" and d is not None:
        draft_info = {
            "on_the_clock": d.on_the_clock, "my_turn": d.on_the_clock == career.team, "round": d.round,
            "number": d.number + 1, "total": len(d.sequence),
        }
    live = None
    if career.live:
        live = {"match": career.live.match, "game": career.live.game, "phase": career.live.phase,
                "our_side": career.live.our_side}
    return {
        "id": save_id,
        "manager": career.manager,
        "season": career.season,
        "day": career.day.isoformat(),
        "phase": career.phase,
        "patch": career.meta.version,
        "team": team_ref(cat, career.team),
        "league": career.league,
        "region": career.region,
        "budget": team.budget,
        "payroll": roster.payroll(career, team),
        "cash": team.cash,
        "next_match": match_summary(cat, career, nxt) if nxt else None,
        "live": live,
        "draft": draft_info,
        "unread": sum(1 for m in career.inbox if not m.read),
        "inbox": [m.model_dump(mode="json") for m in reversed(career.inbox[-40:])],
        "season_over": calendar.season_over(career),
    }


def save_row(save, cat: Catalog) -> dict:
    return {
        "id": save.id, "manager": save.manager, "team": team_ref(cat, save.team), "season": save.season,
        "day": save.day.isoformat(), "phase": save.phase, "updated_at": save.updated_at.isoformat(),
    }


# ---------- draft ----------


def draft_view(cat: Catalog, career: Career) -> dict:
    d = career.drafts[career.league]
    me = career.teams[career.team]
    teams = []
    order = d.sequence[: d.teams_per_round]
    for tid in order:
        t = career.teams[tid]
        teams.append({
            "team": team_ref(cat, tid), "roster": [player_row(cat, career, p) for p in t.roster],
            "lineup": t.lineup, "budget": t.budget, "payroll": roster.payroll(career, t),
            "open_roles": drafting.open_roles(t), "franchise": t.franchise,
        })
    pool = []
    for p in drafting.available(cat, career, d.league):
        row = player_row(cat, career, p.id)
        problem = drafting.check_pick(cat, career, d, me, p) if not d.done else "The draft is over"
        row["problem"] = problem
        row["languages"] = sorted(roster.languages(cat, p))
        pool.append(row)
    pool.sort(key=lambda r: -r["overall"])
    open_roles = drafting.open_roles(me)
    return {
        "league": d.league,
        "round": d.round,
        "number": d.number + 1,
        "total": len(d.sequence),
        "required_rounds": d.required_rounds,
        "optional_rounds": d.optional_rounds,
        "done": d.done,
        "on_the_clock": d.on_the_clock,
        "my_turn": d.on_the_clock == career.team,
        "sequence": d.sequence,
        "picks": [
            {"number": pk.number, "round": pk.round, "team": pk.team, "salary": pk.salary,
             "player": player_row(cat, career, pk.player) if pk.player else None}
            for pk in d.picks
        ],
        "teams": teams,
        "pool": pool,
        "me": {
            "budget": me.budget, "payroll": roster.payroll(career, me), "left": drafting.budget_left(career, me),
            "open_roles": open_roles, "reserve": drafting.reserve(cat, career, d.league, open_roles),
            "can_pass": not drafting.is_required_round(d) or not open_roles,
        },
    }


# ---------- squad and teams ----------


def squad_view(cat: Catalog, career: Career, team_id: str | None = None) -> dict:
    team_id = team_id or career.team
    team = career.teams[team_id]
    chem, reasons = roster.chemistry(cat, career, team)
    return {
        "team": team_ref(cat, team_id),
        "is_mine": team_id == career.team,
        "lineup": team.lineup,
        "players": [player_detail(cat, career, pid) for pid in team.roster],
        "chemistry": {"score": chem, "reasons": reasons},
        "strength": round(roster.lineup_strength(cat, career, team), 1),
        "tactics": team.tactics.model_dump(),
        "budget": team.budget,
        "payroll": roster.payroll(career, team),
        "cash": team.cash,
        "prestige": cat.teams[team_id].prestige,
        "franchise": team.franchise,
    }


def players_search(cat: Catalog, career: Career, region: str | None, free_agents: bool, role: str | None,
                   limit: int) -> list[dict]:
    rows = []
    for p in cat.players.values():
        state = career.players[p.id]
        if region and cat.leagues[p.league].region != region:
            continue
        if free_agents and state.team is not None:
            continue
        if role and p.role != role:
            continue
        rows.append(player_row(cat, career, p.id))
    rows.sort(key=lambda r: -r["overall"])
    return rows[:limit]


# ---------- competitions ----------


def competitions_view(cat: Catalog, career: Career) -> list[dict]:
    out = []
    for comp in sorted(career.competitions.values(), key=lambda c: (c.start, c.id)):
        out.append({
            "id": comp.id, "name": comp.name, "short": comp.short, "kind": comp.kind, "league": comp.league,
            "split": comp.split, "status": comp.status, "start": comp.start.isoformat(), "end": comp.end.isoformat(),
            "winner": team_ref(cat, comp.placements[0]) if comp.placements else None,
            "mine": career.team in comp.entrants,
        })
    return out


def _stage_view(cat: Catalog, career: Career, stage: Stage) -> dict:
    tables = []
    if stage.kind == "round_robin":
        for i, group in enumerate(stage.groups or [stage.teams]):
            rows = comps.standings(career, stage, group)
            tables.append({"name": f"Group {'ABCD'[i]}" if stage.groups else None,
                           "rows": [r | {"team": team_ref(cat, r["team"])} for r in rows]})
    elif stage.kind == "swiss":
        record = comps.swiss_records(career, stage)
        ranked = comps.swiss_ranking(career, stage)
        tables.append({"name": None, "rows": [
            {"team": team_ref(cat, t), "wins": record[t][0], "losses": record[t][1], "game_wins": 0,
             "game_losses": 0, "played": sum(record[t])} for t in ranked]})
    return {
        "id": stage.id, "name": stage.name, "kind": stage.kind, "finished": stage.finished,
        "best_of": stage.best_of, "advance": stage.advance, "tables": tables,
        "matches": [match_summary(cat, career, career.matches[m]) for m in stage.matches],
    }


def competition_view(cat: Catalog, career: Career, comp: Competition) -> dict:
    return {
        "id": comp.id, "name": comp.name, "short": comp.short, "kind": comp.kind, "status": comp.status,
        "league": comp.league, "start": comp.start.isoformat(), "end": comp.end.isoformat(),
        "prize_pool": comp.prize_pool, "entrants": [team_ref(cat, t) for t in comp.entrants],
        "placements": [team_ref(cat, t) for t in comp.placements],
        "stages": [_stage_view(cat, career, s) for s in comp.stages],
    }


def schedule_view(cat: Catalog, career: Career, team_id: str | None = None) -> list[dict]:
    team_id = team_id or career.team
    mine = [m for m in career.matches.values() if team_id in (m.home, m.away)]
    mine.sort(key=lambda m: (m.day, m.id))
    return [match_summary(cat, career, m) for m in mine]


# ---------- matches ----------


def game_summary(cat: Catalog, record) -> dict:
    return record.model_dump(mode="json") | {
        "players": [ln.model_dump(mode="json") | {"name": cat.players[ln.player].name} for ln in record.players],
    }


def match_view(cat: Catalog, career: Career, match: Match) -> dict:
    return match_summary(cat, career, match) | {
        "game_list": [game_summary(cat, g) for g in match.games],
    }


def _side_view(cat: Catalog, career: Career, team_id: str, lineup: dict[str, str]) -> dict:
    team = career.teams[team_id]
    chem, reasons = roster.chemistry(cat, career, team, lineup)
    return {
        "team": team_ref(cat, team_id),
        "lineup": [player_row(cat, career, lineup[r]) | {"slot": r} for r in ROLES],
        "chemistry": {"score": chem, "reasons": reasons},
        "strength": round(roster.lineup_strength(cat, career, team), 1),
        "tactics": team.tactics.model_dump(),
    }


def live_view(cat: Catalog, career: Career) -> dict | None:
    live = career.live
    if live is None:
        return None
    match = career.matches[live.match]
    if live.phase == "result" and match.games:
        # Showing the game just played: its sides, not the ones the next game will use.
        blue, red = match.games[-1].blue, match.games[-1].red
    else:
        blue, red = matchday.sides(match)
    teams = matchday.draft_sides(cat, career, blue, red)
    select = live.select
    current = cs.turn(select) if live.phase == "draft" else None
    suggestions: list[dict] = []
    if current and current[0] == live.our_side:
        me = teams[live.our_side]
        enemy = teams["red" if live.our_side == "blue" else "blue"]
        if current[1] == "pick":
            suggestions = cs.options(cat, career, select, live.our_side, me, enemy, limit=15)
        else:
            suggestions = cs.ban_options(cat, career, select, live.our_side, me, enemy, limit=15)
        for s in suggestions:
            s["score"] = round(s["score"], 2)
    view = {
        "match": match_view(cat, career, match),
        "game": live.game,
        "phase": live.phase,
        "our_side": live.our_side,
        "blue": _side_view(cat, career, blue, teams["blue"].lineup),
        "red": _side_view(cat, career, red, teams["red"].lineup),
        "select": {
            "step": select.step,
            "turn": {"side": current[0], "kind": current[1]} if current else None,
            "order": [{"side": s, "kind": k} for s, k in cs.ORDER],
            "blue_bans": select.blue_bans, "red_bans": select.red_bans,
            "blue_picks": select.blue_picks, "red_picks": select.red_picks,
            "locked": select.locked if live.phase != "lineup" else matchday.fearless_locks(match),
        },
        "suggestions": suggestions,
        "compositions": {
            side: _composition(cat, picks)
            for side, picks in (("blue", select.blue_picks), ("red", select.red_picks))
        },
        "bench": [player_row(cat, career, p) for p in career.teams[career.team].roster
                  if p not in career.teams[career.team].lineup.values()],
        "mastery": _mastery_table(cat, career, teams),
    }
    return view


def _composition(cat: Catalog, picks: dict[str, str]) -> dict | None:
    if len(picks) < 5:
        return None
    value, notes = cs.composition_modifier(cat, picks)
    bias = cs.focus_bias(cat, picks)
    curve = "an early-game" if bias > 0.5 else "a scaling" if bias < -0.5 else "a mid-game"
    return {"value": round(value, 1), "notes": [f"Plays as {curve} composition", *notes]}


def _mastery_table(cat: Catalog, career: Career, teams: dict) -> dict:
    """Each player's twelve best champions with mastery, so the client can badge the champion grid."""
    out = {}
    for side, ds in teams.items():
        for role, pid in ds.lineup.items():
            p: Player = cat.players[pid]
            known = {rec.champion for rec in p.pool} | set(career.players[pid].learned)
            ranked = sorted(known, key=lambda c: -roster.mastery(cat, career, pid, c))[:12]
            out[pid] = {c: roster.mastery(cat, career, pid, c) for c in ranked}
    return out


# ---------- meta ----------


def meta_view(cat: Catalog, career: Career) -> dict:
    rows = []
    for cid, power in career.meta.power.items():
        champ = cat.champions[cid]
        rows.append({"champion": cid, "name": champ.name, "roles": list(champ.roles), "power": power,
                     "tier": patches.tier(power), "picks": career.meta.picks.get(cid, 0),
                     "bans": career.meta.bans.get(cid, 0)})
    rows.sort(key=lambda r: -r["power"])
    return {
        "version": career.meta.version,
        "next_patch": career.meta.next_patch.isoformat() if career.meta.next_patch else None,
        "games": career.meta.games,
        "champions": rows,
        "history": [p.model_dump(mode="json") for p in reversed(career.meta.history[-10:])],
    }
