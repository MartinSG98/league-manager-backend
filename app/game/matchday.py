"""Playing series: AI against AI in one go, the manager's own series one step at a time.

The home team (the higher seed) is on blue side in game one; after that the loser of the last
game picks a side and takes blue. Best-of series use fearless draft: a champion played by either
team in an earlier game of the series cannot be picked again.

After champion select each side may call one set play it has not run yet in the series (see
plays.py). The manager's assistant suggests one; AI sides pick their own."""

from dataclasses import dataclass, field

from app.game import champ_select as cs
from app.game import competitions as comps
from app.game import match_engine, patches, power, roster, training
from app.game import plays as set_plays
from app.game import staff as staffing
from app.game.catalog import ROLES, Catalog
from app.game.errors import IllegalAction
from app.game.rng import Rng
from app.game.state import Career, ChampSelect, GameRecord, LiveSeries, Match, Side, Tactics


@dataclass
class Detail:
    """A played game's timeline, stored next to the career rather than inside it."""

    match: str
    game: int
    payload: dict


@dataclass
class Outcome:
    details: list[Detail] = field(default_factory=list)


# ---------- series bookkeeping ----------


def wins_needed(match: Match) -> int:
    return match.best_of // 2 + 1


def series_over(match: Match) -> bool:
    home, away = match.score
    return max(home, away) >= wins_needed(match)


def sides(match: Match) -> tuple[str, str]:
    """Blue and red team for the next game of the series."""
    assert match.home and match.away
    if not match.games:
        return match.home, match.away
    last = match.games[-1]
    loser = last.red if last.winner == last.blue else last.blue
    other = match.away if loser == match.home else match.home
    return loser, other


def fearless_locks(match: Match) -> list[str]:
    if not match.fearless:
        return []
    return [c for g in match.games for c in (*g.blue_picks.values(), *g.red_picks.values())]


def tactics_of(career: Career, team: str) -> Tactics:
    return career.teams[team].tactics


def lineup_of(cat: Catalog, career: Career, team: str) -> dict[str, str]:
    state = career.teams[team]
    lineup = dict(state.lineup)
    for role in ROLES:
        if role not in lineup:
            # Should not happen after a draft, but never send four players out.
            spare = next((p for p in state.roster if cat.players[p].role == role), None) or state.roster[0]
            lineup[role] = spare
    return lineup


def draft_sides(cat: Catalog, career: Career, blue: str, red: str) -> dict[str, cs.DraftSide]:
    def side(team: str) -> cs.DraftSide:
        noise = staffing.draft_noise(staffing.attribute(cat, career, team, "drafting"))
        return cs.DraftSide(team, lineup_of(cat, career, team), tactics_of(career, team), noise)

    return {"blue": side(blue), "red": side(red)}


# ---------- after each game ----------


def record_game(cat: Catalog, career: Career, match: Match, result: match_engine.GameResult,
                lineups: dict[str, dict[str, str]]) -> None:
    record = result.record
    match.games.append(record)
    patches.record_draft(career, [*record.blue_picks.values(), *record.red_picks.values()],
                         [*record.blue_bans, *record.red_bans])
    minutes = record.duration / 60
    for line in record.players:
        state = career.players[line.player]
        season = state.season
        season.games += 1
        season.wins += 1 if line.team == record.winner else 0
        season.kills += line.kills
        season.deaths += line.deaths
        season.assists += line.assists
        season.cs += line.cs
        season.damage += line.damage
        season.minutes += minutes
        season.rating_sum += line.rating
        season.mvps += 1 if record.mvp == line.player else 0
        season.champions[line.champion] = season.champions.get(line.champion, 0) + 1
        state.form = max(-3.0, min(3.0, state.form * 0.85 + (line.rating - 6.3) * 0.25))
        state.fatigue = min(100, state.fatigue + training.MATCH_FATIGUE)
        state.sharpness = min(100, state.sharpness + training.MATCH_SHARPNESS)
        # Playing a champion on stage teaches it, a little, more with a good coach.
        known = roster.mastery(cat, career, line.player, line.champion)
        if known < 80:
            teach = staffing.teaching_factor(staffing.attribute(cat, career, line.team, "teaching"))
            gain = max(1, round((3 if known < 40 else 1) * teach))
            state.learned[line.champion] = state.learned.get(line.champion, 0) + gain
    for team, lineup in lineups.items():
        if team in career.teams:
            weight = staffing.familiarity_per_game(staffing.attribute(cat, career, team, "motivation"))
            roster.record_games_together(career.teams[team], lineup, weight)
    for team, play in record.plays.items():
        used = match.plays_used.setdefault(team, [])
        if play not in used:
            used.append(play)


def finish_match(cat: Catalog, career: Career, match: Match) -> None:
    home, away = match.score
    match.winner = match.home if home > away else match.away
    for team in (match.home, match.away):
        state = career.teams.get(team or "")
        if not state:
            continue
        delta = 4 if team == match.winner else staffing.defeat_morale(staffing.attribute(cat, career, team, "motivation"))
        for pid in state.lineup.values():
            p = career.players[pid]
            p.morale = max(0, min(100, p.morale + delta))
    power.after_series(cat, career, match)
    comps.on_match_finished(career, match)


# ---------- AI series ----------


def play_ai_game(cat: Catalog, career: Career, match: Match, rng: Rng, detailed: bool = False) -> match_engine.GameResult:
    blue, red = sides(match)
    select = ChampSelect(locked=fearless_locks(match))
    teams = draft_sides(cat, career, blue, red)
    cs.run_ai(cat, career, select, teams, rng, human=None)
    calls = {blue: ai_play(cat, career, match, blue, red, select.blue_picks, rng),
             red: ai_play(cat, career, match, red, blue, select.red_picks, rng)}
    return _simulate(cat, career, match, select, teams, rng, calls)


def ai_play(cat: Catalog, career: Career, match: Match, team: str, enemy: str, picks: dict[str, str],
            rng: Rng | None) -> str | None:
    if team not in career.teams or enemy not in career.teams:
        return None
    return set_plays.choose(cat, career, team, enemy, match, cs.focus_bias(cat, picks), rng)


def _simulate(cat: Catalog, career: Career, match: Match, select: ChampSelect, teams: dict[str, cs.DraftSide],
              rng: Rng, calls: dict[str, str | None] | None = None) -> match_engine.GameResult:
    blue, red = teams["blue"], teams["red"]
    calls = calls or {}
    gb = match_engine.prepare(cat, career, "blue", blue.team, blue.lineup, dict(select.blue_picks), blue.tactics,
                              calls.get(blue.team))
    gr = match_engine.prepare(cat, career, "red", red.team, red.lineup, dict(select.red_picks), red.tactics,
                              calls.get(red.team))
    number = len(match.games) + 1
    result = match_engine.simulate(cat, career, gb, gr, rng, number, (select.blue_bans, select.red_bans))
    record_game(cat, career, match, result, {blue.team: blue.lineup, red.team: red.lineup})
    return result


def play_ai_match(cat: Catalog, career: Career, match: Match, rng: Rng) -> None:
    while not series_over(match):
        play_ai_game(cat, career, match, rng)
    finish_match(cat, career, match)


# ---------- the manager's series ----------


def our_side(career: Career, match: Match) -> Side:
    blue, _ = sides(match)
    return "blue" if blue == career.team else "red"


def start_live(career: Career, match: Match) -> LiveSeries:
    live = LiveSeries(match=match.id, game=len(match.games) + 1, our_side=our_side(career, match), phase="lineup")
    career.live = live
    return live


def live_match(career: Career) -> Match:
    if career.live is None:
        raise IllegalAction("There is no match in progress")
    return career.matches[career.live.match]


def start_champ_select(cat: Catalog, career: Career, rng: Rng) -> None:
    """Open champion select. Nobody moves yet: the opponent's turns are played by opponent_turn, so
    the client can let them take their time instead of locking in the moment the manager does."""
    live = career.live
    match = live_match(career)
    if live.phase != "lineup":
        raise IllegalAction("Champion select has already started")
    live.select = ChampSelect(locked=fearless_locks(match))
    live.phase = "draft"


def _check_ready(cat: Catalog, career: Career) -> None:
    live = career.live
    if live and live.phase == "draft" and cs.turn(live.select) is None:
        live.phase = "ready"
        # The assistant's suggestion is called unless the manager picks another play or none.
        match = live_match(career)
        enemy = opponent(career, match)
        picks = live.select.blue_picks if live.our_side == "blue" else live.select.red_picks
        live.play = ai_play(cat, career, match, career.team, enemy, picks, None)


def opponent(career: Career, match: Match) -> str:
    return (match.away if match.home == career.team else match.home) or ""


def set_play(cat: Catalog, career: Career, play: str | None) -> None:
    live = career.live
    if live is None or live.phase != "ready":
        raise IllegalAction("Set plays are called after champion select")
    if play is not None:
        match = live_match(career)
        if play not in set_plays.PLAYS:
            raise IllegalAction("Unknown set play")
        if play not in set_plays.available(career, career.team, match):
            raise IllegalAction("The team cannot run that play in this series")
    live.play = play


def _running_select(career: Career) -> ChampSelect:
    live = career.live
    if live is None or live.phase != "draft":
        raise IllegalAction("Champion select is not running")
    return live.select


def human_ban(cat: Catalog, career: Career, champion: str, rng: Rng) -> None:
    cs.ban(cat, _running_select(career), career.live.our_side, champion)
    _check_ready(cat, career)


def human_pick(cat: Catalog, career: Career, champion: str, role: str, rng: Rng) -> None:
    cs.pick(cat, _running_select(career), career.live.our_side, champion, role)
    _check_ready(cat, career)


def opponent_turn(cat: Catalog, career: Career, rng: Rng, until_mine: bool = False) -> None:
    """The opponent's next ban or pick, or all of them up to the manager's turn. On the manager's
    own turn this does nothing, so a client calling it on a timer can never move for the manager."""
    select = _running_select(career)
    current = cs.turn(select)
    if current is None or current[0] == career.live.our_side:
        return
    blue, red = sides(live_match(career))
    teams = draft_sides(cat, career, blue, red)
    if until_mine:
        cs.run_ai(cat, career, select, teams, rng, human=career.live.our_side)
    else:
        cs.ai_step(cat, career, select, teams, rng)
    _check_ready(cat, career)


def auto_select(cat: Catalog, career: Career, rng: Rng) -> None:
    live = career.live
    if live is None:
        raise IllegalAction("There is no match in progress")
    if live.phase == "lineup":
        start_champ_select(cat, career, rng)
    if live.phase != "draft":
        return
    match = live_match(career)
    blue, red = sides(match)
    cs.run_ai(cat, career, live.select, draft_sides(cat, career, blue, red), rng, human=None)
    _check_ready(cat, career)


def play_live_game(cat: Catalog, career: Career, rng: Rng) -> Detail:
    live = career.live
    if live is None or live.phase != "ready":
        raise IllegalAction("Finish champion select first")
    match = live_match(career)
    blue, red = sides(match)
    teams = draft_sides(cat, career, blue, red)
    enemy = opponent(career, match)
    enemy_picks = live.select.red_picks if live.our_side == "blue" else live.select.blue_picks
    calls = {career.team: live.play if live.play in set_plays.available(career, career.team, match) else None,
             enemy: ai_play(cat, career, match, enemy, career.team, enemy_picks, rng)}
    result = _simulate(cat, career, match, live.select, teams, rng, calls)
    match.games[-1].detailed = True
    live.phase = "result"
    return _detail(match, result)


def _detail(match: Match, result: match_engine.GameResult) -> Detail:
    return Detail(
        match=match.id,
        game=result.record.number,
        payload={
            "events": [e.__dict__ | {"score": list(e.score)} for e in result.events],
            "gold": result.gold_diff,
        },
    )


def next_game(cat: Catalog, career: Career) -> bool:
    """Move past a played game. Returns True when the series is over."""
    live = career.live
    if live is None or live.phase != "result":
        raise IllegalAction("Play the current game first")
    match = live_match(career)
    if series_over(match):
        finish_match(cat, career, match)
        career.live = None
        return True
    career.live = LiveSeries(match=match.id, game=len(match.games) + 1, our_side=our_side(career, match))
    return False


def sim_series(cat: Catalog, career: Career, rng: Rng) -> list[Detail]:
    """Auto-draft and play out every remaining game of the manager's series."""
    details: list[Detail] = []
    while career.live is not None:
        live = career.live
        if live.phase in ("lineup", "draft"):
            auto_select(cat, career, rng)
        if live.phase == "ready":
            details.append(play_live_game(cat, career, rng))
        if career.live and career.live.phase == "result":
            next_game(cat, career)
    return details


def set_lineup(cat: Catalog, career: Career, lineup: dict[str, str]) -> None:
    team = career.teams[career.team]
    if set(lineup) != set(ROLES):
        raise IllegalAction("A lineup needs one player in every role")
    if len(set(lineup.values())) != 5:
        raise IllegalAction("A player can only fill one role")
    for role, pid in lineup.items():
        if pid not in team.roster:
            raise IllegalAction(f"{cat.players.get(pid).name if pid in cat.players else pid} is not on your roster")
    if career.live and career.live.phase not in ("lineup",):
        raise IllegalAction("The lineup is locked once champion select starts")
    team.lineup = dict(lineup)


def game_record(match: Match, number: int) -> GameRecord | None:
    return next((g for g in match.games if g.number == number), None)
