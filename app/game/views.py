"""What the client renders, worked out on the server so the UI never reimplements a rule.

Every function returns plain JSON-ready dicts with snake_case keys; the client keeps a
hand-written copy of these shapes in src/api/types.ts."""

from app.game import board as boardroom
from app.game import calendar, champ_select as cs
from app.game import competitions as comps
from app.game import draft as drafting
from app.game import finances, hiring, jobs, manager, matchday, patches, reputation, rookies, roster, shortlist, training
from app.game import transfers
from app.game import plays as set_plays
from app.game import staff as staffing
from app.game.catalog import ROLES, Catalog, Player
from app.game.ratings import ATTRIBUTES
from app.game.state import Career, Competition, Match, Stage

# ---------- small pieces ----------


def team_ref(cat: Catalog, team_id: str | None) -> dict | None:
    if team_id is None:
        return None
    t = cat.teams[team_id]
    return {"id": t.id, "name": t.name, "tag": t.tag, "color": t.color, "league": t.league, "region": t.region,
            "logo": t.logo}


def competition_logo(cat: Catalog, comp: Competition) -> str | None:
    if comp.league:
        return cat.leagues[comp.league].logo
    return cat.event_logos.get(comp.id.split("-", 1)[1])


def player_row(cat: Catalog, career: Career, pid: str) -> dict:
    p = cat.players[pid]
    state = career.players[pid]
    origin = cat.teams.get(p.team)
    return {
        "id": p.id,
        "name": p.name,
        "real_name": p.real_name,
        "photo": p.photo,
        "role": p.role,
        "country": p.country,
        "league": p.league,
        "origin": {"id": origin.id, "name": origin.name, "tag": origin.tag, "logo": origin.logo} if origin else None,
        "team": state.team,
        "franchise": bool(state.team and career.teams.get(state.team) and career.teams[state.team].franchise == pid),
        "overall": roster.overall(cat, career, pid),
        # The scouts' estimate, never below what the player already is.
        "potential": max(p.potential, roster.overall(cat, career, pid)),
        "salary": state.contract.salary if state.contract else p.salary,
        "contract_until": state.contract.until if state.contract else None,
        "reputation": p.reputation,
        "experience": p.experience,
        "signatures": list(p.signatures),
        "form": round(state.form, 1),
        "morale": state.morale,
        "fatigue": state.fatigue,
        "sharpness": state.sharpness,
        "status": training.condition_labels(state),
        "rookie": rookies.is_rookie(pid),
        "retiring": state.retiring,  # the season they said will be their last
        "retired": state.retired,
    }


def staff_row(cat: Catalog, career: Career, sid: str | None) -> dict | None:
    if not sid or sid not in cat.staff:
        return None
    s = cat.staff[sid]
    state = career.staff.get(sid)
    origin = cat.teams.get(s.team or "")
    contract = state.contract if state else None
    return {
        "id": s.id, "name": s.name, "real_name": s.real_name, "kind": s.kind, "position": s.position,
        "country": s.country, "photo": s.photo, "generated": s.generated, "region": s.region,
        "origin": {"id": origin.id, "name": origin.name, "tag": origin.tag, "logo": origin.logo} if origin else None,
        "team": state.team if state else None, "attributes": s.attributes, "overall": s.overall,
        "salary": contract.salary if contract else s.salary, "contract_until": contract.until if contract else None,
        "club": team_ref(cat, state.team) if state and state.team else None,
        "mine": bool(state and state.team == career.team),
    }


def staff_search(cat: Catalog, career: Career, kind: str | None, region: str | None, free_only: bool,
                 limit: int) -> list[dict]:
    """Coaches and analysts for the Scouting screen, best first."""
    rows = []
    for s in sorted(cat.staff.values(), key=lambda s: -s.overall):
        state = career.staff.get(s.id)
        if (kind and s.kind != kind) or (region and s.region != region) or (free_only and state and state.team):
            continue
        rows.append(staff_row(cat, career, s.id))
        if len(rows) >= limit:
            break
    return rows


def staff_detail(cat: Catalog, career: Career, sid: str) -> dict:
    """A staff member's page: who they are, their contract, and what talks with them would cost."""
    s = cat.staff[sid]
    state = career.staff.get(sid)
    team = career.teams[career.team]
    seat = getattr(team, s.kind)
    talks = career.staff_talks.get(sid)
    made = next((c for c in career.new_staff if c.id == sid), None)
    return staff_row(cat, career, sid) | {  # type: ignore[operator]
        "ask": hiring.asking_salary(cat, career, sid),
        "wanted_years": hiring.WANTED_YEARS, "max_years": hiring.MAX_YEARS,
        "compensation": hiring.compensation(cat, career, sid),
        "release_cost": hiring.release_cost(career, sid) if hiring.mine(career, sid) else None,
        "stars_wanted": round(hiring.stars_wanted(cat, sid), 1),
        "problem": hiring.check_can_talk(cat, career, sid),
        "talks": talks.model_dump(mode="json") if talks else None,
        "rounds_left": hiring.MAX_ROUNDS - (talks.rounds if talks else 0),
        "budget_room": hiring.budget_room(cat, career, sid),
        "seat": staff_row(cat, career, seat) if seat and seat != sid else None,
        "seat_name": hiring.SEAT_NAMES[s.kind],
        "joined_market": made.season if made else None,
        "former_player": player_row(cat, career, made.former_player) if made and made.former_player else None,
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
        "training": state.training.model_dump(),
        "development": training.development_trend(state),
        "market": transfers.player_market(cat, career, pid),
        "shortlist": _shortlist_entry(career, pid),
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


def _shortlist_entry(career: Career, pid: str) -> dict | None:
    found = shortlist.entry(career, pid)
    if found is None:
        return None
    return {"added": found.added.isoformat(), "due": found.due.isoformat() if found.due else None,
            "reports": found.reports, "report": found.report}


def shortlist_view(cat: Catalog, career: Career) -> list[dict]:
    rows = []
    for found in career.shortlist:
        pid = found.player
        level, _ = transfers.interest(cat, career, pid, career.team)
        rows.append(player_row(cat, career, pid) | {
            "shortlist": _shortlist_entry(career, pid),
            "value": transfers.market_value(cat, career, pid),
            "asking": transfers.asking_fee(cat, career, pid),
            "interest": level,
        })
    return rows


def match_summary(cat: Catalog, career: Career, match: Match) -> dict:
    comp = career.competitions[match.competition]
    return {
        "id": match.id,
        "competition": comp.id,
        "competition_name": comp.name,
        "competition_logo": competition_logo(cat, comp),
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
        "bracket": match.bracket,
        "round": match.round,
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
    b = career.board
    return {
        "id": save_id,
        "manager": career.manager,
        "profile": manager.summary(career),  # None: the manager is still to be created
        "season": career.season,
        "day": career.day.isoformat(),
        "phase": career.phase,
        "patch": career.meta.version,
        "team": team_ref(cat, career.team),
        "league": career.league,
        "league_logo": cat.leagues[career.league].logo,
        "region": career.region,
        "budget": team.budget,
        "payroll": roster.payroll(career, team),
        "cash": team.cash,
        "budget_adjust": finances.view(career),
        "next_match": match_summary(cat, career, nxt) if nxt else None,
        "live": live,
        "draft": draft_info,
        "staff": {"coach": staff_row(cat, career, team.coach), "analyst": staff_row(cat, career, team.analyst)},
        "unread": sum(1 for m in career.inbox if not m.read),
        "inbox": [m.model_dump(mode="json") for m in reversed(career.inbox[-40:])],
        "season_over": calendar.season_over(career),
        "draw": _pending_draw(career),
        "franchise_choice": career.franchise_choice.isoformat() if career.franchise_choice else None,
        "shortlist": [e.player for e in career.shortlist],
        "board": {
            "confidence": b.confidence, "security": boardroom.job_security(career), "warned": b.warned,
            "meeting": b.meeting, "sacked": b.sacked, "season": b.season,
            "objectives": [{"id": o.id, "text": boardroom.describe(cat, career, o), "status": o.status,
                            "result": o.result} for o in b.objectives],
            "bonuses": _bonuses(career),
        },
        "reputation": _reputation(cat, career),
        "job_offers": [_job_offer(cat, career, t) for t in career.job_offers],
        "window": {"open": transfers.window_open(career),
                   "closes": transfers.closing_day(career).isoformat(),
                   "free_agency": transfers.free_agency_day(career).isoformat()} if transfers.window_open(career) else None,
        "pending": {
            "offers": sum(1 for o in career.offers if o.seller == career.team and o.status == "open"),
            "talks": sum(1 for c in career.conversations if not c.resolved),
        },
    }


def _bonuses(career: Career) -> list[dict]:
    return [{"id": x.id, "text": boardroom.describe_bonus(x), "status": x.status, "confidence": x.confidence,
             "payment": boardroom.bonus_payment(career, x)} for x in career.board.bonuses]


def _reputation(cat: Catalog, career: Career) -> dict:
    team = reputation.team_reputation(cat, career, career.team)
    return {"team": round(team, 1), "team_stars": reputation.stars(team), **reputation.ratings(cat, career, career.team),
            "manager": career.manager_reputation, "manager_stars": reputation.stars(career.manager_reputation),
            "manager_ratings": reputation.manager_ratings(cat, career)}


def _job_offer(cat: Catalog, career: Career, team_id: str) -> dict:
    team = career.teams[team_id]
    rep = reputation.team_reputation(cat, career, team_id)
    return {"team": team_ref(cat, team_id), "stars": reputation.stars(rep), **reputation.ratings(cat, career, team_id),
            "budget": team.budget,
            "strength": round(roster.lineup_strength(cat, career, team), 1),
            "league_name": cat.leagues[cat.teams[team_id].league].name}


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
            "coach": staff_row(cat, career, t.coach), "analyst": staff_row(cat, career, t.analyst),
        })
    pool = []
    for p in drafting.available(cat, career, d.league):
        row = player_row(cat, career, p.id)
        problem = drafting.check_pick(cat, career, d, me, p) if not d.done else "The draft is over"
        row["problem"] = problem
        row["languages"] = sorted(roster.languages(cat, p))
        pool.append(row)
    pool.sort(key=lambda r: -r["overall"])
    staff_pool = []
    for s in drafting.available_staff(cat, career, d.league):
        row = staff_row(cat, career, s.id)
        row["problem"] = drafting.check_staff_pick(cat, career, d, me, s) if not d.done else "The draft is over"
        staff_pool.append(row)
    staff_pool.sort(key=lambda r: -r["overall"])
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
        "round_kind": d.round_kind if not d.done else "player",
        "staff_rounds": d.staff_rounds,
        "picks": [
            {"number": pk.number, "round": pk.round, "team": pk.team, "salary": pk.salary,
             "player": player_row(cat, career, pk.player) if pk.player else None,
             "staff": staff_row(cat, career, pk.staff)}
            for pk in d.picks
        ],
        "teams": teams,
        "pool": pool,
        "staff_pool": staff_pool,
        "me": {
            "budget": me.budget, "payroll": roster.payroll(career, me), "left": drafting.budget_left(career, me),
            "open_roles": open_roles, "reserve": drafting.reserve(cat, career, d.league, open_roles)
            + drafting.staff_reserve(cat, career, d, drafting.staff_needed(d, me)),
            "staff_needed": drafting.staff_needed(d, me),
            "can_pass": d.round_kind == "player" and (not drafting.is_required_round(d) or not open_roles),
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
        "stars": reputation.stars(reputation.team_reputation(cat, career, team_id)),
        **reputation.ratings(cat, career, team_id),
        "skills": {a: round(team.skills.get(a, 10.0), 1) for a in training.AREAS},
        "listed": team.listed if team_id == career.team else [],
        "franchise": team.franchise,
        "staff": {"coach": staff_row(cat, career, team.coach), "analyst": staff_row(cat, career, team.analyst)},
    }


def players_search(cat: Catalog, career: Career, region: str | None, free_agents: bool, role: str | None,
                   limit: int, rookies_only: bool = False) -> list[dict]:
    rows = []
    for p in cat.players.values():
        state = career.players[p.id]
        if region and cat.leagues[p.league].region != region:
            continue
        if state.retired or (free_agents and state.team is not None):
            continue
        if rookies_only and not rookies.is_rookie(p.id):
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
            "logo": competition_logo(cat, comp), "split": comp.split, "status": comp.status, "start": comp.start.isoformat(), "end": comp.end.isoformat(),
            "winner": team_ref(cat, comp.placements[0]) if comp.placements else None,
            "mine": career.team in comp.entrants,
        })
    return out


def _stage_view(cat: Catalog, career: Career, stage: Stage) -> dict:
    tables = []
    matches = [match_summary(cat, career, career.matches[m]) for m in stage.matches]
    if stage.kind == "swiss":
        pools = comps.swiss_pools(career, stage)
        for row in matches:
            row["pool"] = list(pools[row["id"]])
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
        "best_of": stage.best_of, "advance": stage.advance, "tables": tables, "matches": matches,
        "swiss_wins": comps.SWISS_WINS if stage.kind == "swiss" else None,
        "pots": [[team_ref(cat, t) for t in pot] for pot in stage.pots],
    }


def _pending_draw(career: Career) -> dict | None:
    """The newest Swiss draw, while the manager has not seen it and its round is still to play."""
    msg = next((m for m in reversed(career.inbox) if m.kind == "draw"), None)
    if msg is None or msg.read or msg.competition not in career.competitions:
        return None
    comp = career.competitions[msg.competition]
    stage = next((s for s in comp.stages if s.kind == "swiss"), None)
    if stage is None:
        return None
    pools = comps.swiss_pools(career, stage)
    drawn = [m for m in stage.matches if sum(pools[m]) + 1 == msg.round]
    if not drawn or any(career.matches[m].winner for m in drawn):
        return None
    return {"message": msg.id, "competition": comp.id, "name": comp.name, "round": msg.round}


def competition_view(cat: Catalog, career: Career, comp: Competition) -> dict:
    return {
        "id": comp.id, "name": comp.name, "short": comp.short, "kind": comp.kind, "status": comp.status,
        "league": comp.league, "logo": competition_logo(cat, comp), "start": comp.start.isoformat(),
        "end": comp.end.isoformat(),
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
        "players": [ln.model_dump(mode="json") | {"name": cat.players[ln.player].name, "photo": cat.players[ln.player].photo}
                    for ln in record.players],
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
    board = None
    coach = cat.staff.get(career.teams[career.team].coach or "")
    # Champion select is read by whoever drafts: the manager when they took it on or have no coach.
    drafting = staffing.attribute(cat, career, career.team, "drafting")
    yours = manager.does(cat, career, "drafting")
    reader = ({"name": career.manager, "drafting": drafting, "you": True} if yours
              else {"name": coach.name, "drafting": drafting, "you": False} if coach else None)
    if current and current[0] == live.our_side:
        me = teams[live.our_side]
        enemy = teams[cs.other_side(live.our_side)]
        who = f"manager:{career.manager}" if yours else coach.id if coach else "nobody"
        board = cs.board(cat, career, select, live.our_side, me, enemy, lens=staffing.coach_lens(drafting, who))
        suggestions = cs.suggestions(board)
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
        "board": board,
        "compositions": {
            side: _composition(cat, picks)
            for side, picks in (("blue", select.blue_picks), ("red", select.red_picks))
        },
        "coach": {"name": coach.name, "drafting": coach.attributes["drafting"]} if coach else None,
        "reader": reader,
        "scouting": next((m.report for m in reversed(career.inbox)
                          if m.kind == "scouting" and m.report and m.report.get("match") == match.id), None),
        "bench": [player_row(cat, career, p) for p in career.teams[career.team].roster
                  if p not in career.teams[career.team].lineup.values()],
        "mastery": _mastery_table(cat, career, teams),
        "plays": _plays_choice(cat, career, match) if live.phase == "ready" else None,
    }
    return view


def _plays_choice(cat: Catalog, career: Career, match: Match) -> dict:
    """The set plays the manager can call for the coming game, with how likely each is to work."""
    live = career.live
    picks = live.select.blue_picks if live.our_side == "blue" else live.select.red_picks
    early = cs.focus_bias(cat, picks)
    enemy = matchday.opponent(career, match)
    team = career.teams[career.team]
    options = []
    for pid in set_plays.PLAYS:
        play = set_plays.PLAYS[pid]
        learned = team.plays.get(pid, 0.0)
        if learned < set_plays.USABLE_FROM:
            continue
        used = pid in match.plays_used.get(career.team, [])
        options.append({
            "id": pid, "name": play.name, "phase": play.phase, "minute": play.minute, "effect": play.effect,
            "text": play.text, "learned": round(learned), "used": used,
            "chance": round(set_plays.team_chance(cat, career, career.team, enemy, pid, early), 2),
            "fit": round(set_plays.fit(play, early), 2),
        })
    options.sort(key=lambda o: (o["used"], -o["chance"]))
    return {"chosen": live.play, "options": options, "used": match.plays_used.get(career.team, []),
            "opponent_used": match.plays_used.get(enemy, [])}


# ---------- training ----------


def training_view(cat: Catalog, career: Career) -> dict:
    team = career.teams[career.team]
    latest = next((m for m in reversed(career.inbox) if m.report and m.report.get("kind") == "review"
                   and m.report.get("team") == career.team), None)
    players = []
    for pid in team.roster:
        state = career.players[pid]
        row = player_row(cat, career, pid)
        row |= {
            "starter": pid in team.lineup.values(),
            "training": state.training.model_dump(),
            "development": training.development_trend(state),
            "quality": round(training.season_quality(state), 2) if state.development else None,
            "burnout": state.burnout,
            "attributes": roster.attributes(cat, career, pid),
            "learning": ({"champion": state.training.champion,
                          "mastery": roster.mastery(cat, career, pid, state.training.champion)}
                         if state.training.champion else None),
        }
        players.append(row)
    players.sort(key=lambda r: (not r["starter"], ROLES.index(r["role"])))
    coach = cat.staff.get(team.coach or "")
    return {
        "load": team.training.load,
        "recommended": training.recommended_load(career, career.team),
        "advice": training.load_advice(career, career.team),
        "loads": [{"id": k, "name": v.name, "text": v.text, "fatigue": v.fatigue, "sharpness": v.sharpness,
                   "gain": v.gain} for k, v in training.LOADS.items()],
        "focus": team.training.focus,
        "areas": [{"id": a, "label": label, "effect": training.AREA_EFFECTS[a],
                   "level": round(team.skills.get(a, 10.0), 1)} for a, label in training.AREAS.items()],
        "drilling": team.training.play,
        "plays": [{"id": p.id, "name": p.name, "phase": p.phase, "minute": p.minute, "weeks": p.weeks,
                   "area": p.area, "area_label": training.AREAS[p.area], "style": p.style, "text": p.text,
                   "effect": p.effect, "learned": round(team.plays.get(p.id, 0.0))}
                  for p in set_plays.PLAYS.values()],
        "usable_from": set_plays.USABLE_FROM,
        "players": players,
        "attributes": list(ATTRIBUTES),
        "review": latest.report | {"day": latest.day.isoformat(), "subject": latest.subject} if latest else None,
        "coach": {"name": coach.name, "attributes": coach.attributes} if coach else None,
        "thresholds": {"burnout": training.BURNOUT_FROM, "complacent": training.COMPLACENT_BELOW,
                       "champion_cap": training.CHAMPION_CAP},
    }


# ---------- the board ----------


def board_view(cat: Catalog, career: Career) -> dict:
    b = career.board
    team = career.teams[career.team]
    objectives = []
    for o in b.objectives:
        row = {"id": o.id, "kind": o.kind, "split": o.split, "text": boardroom.describe(cat, career, o),
               "status": o.status, "result": o.result, "target": o.target, "proposed": o.proposed,
               "progress": _objective_progress(cat, career, o)}
        if b.meeting:
            row["options"] = []
            for stance in (-1, 0, 1):
                target = boardroom.stance_target(cat, career, o, stance)
                trial = o.model_copy(update={"target": target})
                moved = (target - o.proposed) if o.kind == "worlds" else (o.proposed - target)
                row["options"].append({"stance": stance, "text": boardroom.describe(cat, career, trial),
                                       "budget": round(boardroom.BUDGET_STEP * moved, 2), "possible": moved == stance})
        objectives.append(row)
    return {
        "season": b.season,
        "confidence": b.confidence,
        "security": boardroom.job_security(career),
        "warned": b.warned,
        "meeting": b.meeting,
        "sacked": b.sacked,
        "joined": b.joined.isoformat() if b.joined else None,
        "objectives": objectives,
        "bonuses": _bonuses(career),
        "history": list(reversed(b.history[-12:])),
        "reputation": _reputation(cat, career) | {"prestige": cat.teams[career.team].prestige},
        "finances": {
            "budget": team.budget, "payroll": roster.payroll(career, team), "cash": team.cash,
            "sponsors_per_week": round(reputation.sponsor_income(cat, career, career.team)),
            "budget_step": boardroom.BUDGET_STEP,
        },
        "league_reputation": sorted(
            ({"team": team_ref(cat, t.id), "reputation": round(reputation.team_reputation(cat, career, t.id), 1),
              "stars": reputation.stars(reputation.team_reputation(cat, career, t.id)),
              **reputation.ratings(cat, career, t.id)}
             for t in cat.league_teams(career.league)), key=lambda r: -r["reputation"]),
        "job_offers": [_job_offer(cat, career, t) for t in career.job_offers],
        "vacancies": jobs.view(cat, career),
        "reach": jobs.reach(cat, career),
        "star_reach": reputation.STAR_REACH,
        "thresholds": {"warning": boardroom.WARNING, "safe": boardroom.SAFE},
    }


def _objective_progress(cat: Catalog, career: Career, o) -> str | None:
    """Where the team stands now in the competition an open objective is about."""
    if o.status != "pending":
        return None
    if o.kind == "split":
        comp = career.competitions.get(f"{career.board.season}-{cat.teams[career.team].league}-{o.split}")
        if comp is None or comp.status == "upcoming":
            return None
        stage = comp.stages[0]
        rows = comps.standings(career, stage)
        place = next((i + 1 for i, r in enumerate(rows) if r["team"] == career.team), None)
        return f"Currently {boardroom._ordinal(place)} in the regular season" if place else None
    worlds = career.competitions.get(f"{career.board.season}-WORLDS")
    if worlds is not None:
        return "Qualified" if career.team in worlds.entrants else "Did not qualify"
    return None


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
