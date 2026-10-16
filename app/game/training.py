"""Training: what a team works on between matches, and what it does to the players.

Every Monday each team plays out a week of scrims. The manager sets three things on the training
screen; AI teams set them by themselves (see ai_plan).

- The scrim load: light, normal, heavy or intense. More load builds team areas, set plays and
  players faster and keeps players sharp, but it tires them. Fatigue costs power in games, and a
  player at 60 fatigue or more may burn out for three weeks. Too little load and players lose
  sharpness and get complacent. Match weeks already tire a team, so a load that suits the
  pre-season burns players out during the playoffs.
- Up to two team areas to focus on (see AREAS). One focus trains it at full speed, two at 60
  percent each. Areas out of focus creep up slowly, and one well above 10 slips back when it is
  never worked on.
- One set play to drill (see plays.py).

Each player can also work on one attribute or learn one champion on top of the team's scrims.

How well a player develops depends on the week's quality: the load, the coach's development,
morale and sharpness, and whether they start. Every player has a ceiling the scouts only see
roughly: the potential shown is an estimate. An established player's real one sits up to three
points either side of it; a rookie's is a hopeful read and more often below it (see ceiling). Good
weeks over a few seasons take a player to that ceiling or two points past it, poor ones leave
them short (see growth_target).

Every other week of the season the analyst watches the team's recent games and says which area
costs the most: games behind at 15 minutes point at the early game, leads thrown away at
closing games out, lost fights at teamfighting. A weak analyst sometimes reads it wrong."""

from dataclasses import dataclass

from app.game import manager
from app.game import plays as set_plays
from app.game import roster
from app.game import staff as staffing
from app.game.catalog import Catalog
from app.game.rng import Rng, fnv1a
from app.game.state import Career, GameRecord, InboxMessage, PlayerState, TeamState

AREAS: dict[str, str] = {
    "early_game": "Early game",
    "objectives": "Objective control",
    "teamfighting": "Teamfighting",
    "macro": "Macro",
    "closing": "Closing out games",
}
AREA_EFFECTS: dict[str, str] = {
    "early_game": "Lanes, ganks and early skirmishes in the first 14 minutes",
    "objectives": "Who takes Voidgrubs, dragons, Herald and Baron when both teams want them",
    "teamfighting": "Every teamfight from the mid game on",
    "macro": "Gold and towers from map control once laning is over",
    "closing": "How rarely a lead is thrown away and how quickly a won game ends",
}


@dataclass(frozen=True)
class LoadLevel:
    name: str
    gain: float  # speed of team areas, set plays and player growth
    fatigue: int  # fatigue a week of scrims adds; rest takes 28 a week off
    sharpness: int  # sharpness change over a week
    text: str


LOADS: dict[str, LoadLevel] = {
    "light": LoadLevel("Light", 0.5, 0, -8, "Rest and review. Players recover but lose their edge."),
    "normal": LoadLevel("Normal", 1.0, 8, 2, "A regular block of scrims."),
    "heavy": LoadLevel("Heavy", 1.4, 16, 5, "Long scrim days. Fast progress, tiring in a match week."),
    "intense": LoadLevel("Intense", 1.8, 26, 7, "Bootcamp hours. The fastest progress and a real risk of burnout."),
}

MATCH_FATIGUE = 4  # fatigue a game on stage adds
MATCH_SHARPNESS = 1
BURNOUT_FROM = 60
BURNOUT_WEEKS = 3
SETTLE_MORALE = 60  # an unsettled player still this happy after the weekly drift ...
SETTLE_CHANCE = 0.2  # ... settles with this chance a week; only winning keeps them that happy
COMPLACENT_BELOW = 40
CHAMPION_CAP = 75  # mastery individual practice can take a champion to
PRACTICE_GAIN = 2  # the coach's own pick of meta champions, see practice
PRACTICE_CAP = 55
QUALITY_NORM = 1.13  # a normal week with an average coach for a starter is quality 1.0
GROWTH_CHANCE = 0.05  # a week's chance to grow, per point between a player and their target ...
GROWTH_CHANCE_MAX = 0.45  # ... up to this, times the week's quality
CEILING_SPREAD = 3  # an established player's real ceiling sits up to this far either side of the potential
ROOKIE_CEILING = (-11, 3)  # a rookie's, from this far below the potential to this far above, a few under most often
TRAINING_BONUS = 2  # the most that good training takes a player past their ceiling
REVIEW_GAMES = 6  # new games before the analyst writes another review


def _spread(key: str, size: float) -> float:
    return (fnv1a(key) % 1001 / 1000 * 2 - 1) * size


# ---------- setting a team up ----------


def init_team(cat: Catalog, career: Career, team: TeamState) -> None:
    """Team areas from the organisation's standing, two or three set plays it already knows."""
    prestige = cat.teams[team.id].prestige
    if not team.skills:
        base = 7.5 + (prestige - 75) / 25 * 1.5
        team.skills = {a: round(max(3.0, min(14.0, base + _spread(f"{team.id}:{a}", 1.5))), 1) for a in AREAS}
    if not team.plays:
        order = sorted(set_plays.PLAYS, key=lambda p: fnv1a(f"{team.id}:{p}"))
        team.plays = {p: 100.0 for p in order[: 2 + fnv1a(team.id) % 2]}
    if not team.training.focus:
        team.training.focus = [min(AREAS, key=lambda a: team.skills.get(a, 10.0))]


def ensure(cat: Catalog, career: Career) -> None:
    for team in career.teams.values():
        init_team(cat, career, team)


# ---------- the week ----------


def series_ahead(career: Career, team_id: str, days: int = 7) -> list:
    from datetime import timedelta

    end = career.day + timedelta(days=days)
    return [m for m in career.matches.values()
            if m.winner is None and career.day <= m.day < end and team_id in (m.home, m.away)]


def expected_games(best_of: int) -> float:
    return {1: 1.0, 3: 2.5, 5: 4.0}.get(best_of, best_of / 2 + 0.5)


def recommended_load(career: Career, team_id: str) -> str:
    team = career.teams[team_id]
    starters = [career.players[p] for p in team.lineup.values()]
    tired = sum(s.fatigue for s in starters) / max(1, len(starters))
    upcoming = series_ahead(career, team_id)
    games = sum(expected_games(m.best_of) for m in upcoming)
    if tired >= 45 or games >= 6 or any(m.best_of == 5 for m in upcoming):
        return "light"
    if not upcoming:
        return "heavy"
    return "normal"


def load_advice(career: Career, team_id: str) -> str:
    upcoming = series_ahead(career, team_id)
    games = sum(expected_games(m.best_of) for m in upcoming)
    load = LOADS[recommended_load(career, team_id)].name.lower()
    if not upcoming:
        return f"No matches in the next seven days: a good week to train hard. A {load} load suits it."
    return (f"{len(upcoming)} series (about {games:g} games) in the next seven days. "
            f"A {load} load keeps the players fresh enough.")


def ai_plan(cat: Catalog, career: Career, team: TeamState) -> None:
    """How an AI team trains: the load its coach would recommend, its weakest area, and the next
    set play it does not know yet."""
    team.training.load = recommended_load(career, team.id)  # type: ignore[assignment]
    team.training.focus = [min(AREAS, key=lambda a: team.skills.get(a, 10.0))]
    current = team.training.play
    if current is None or team.plays.get(current, 0.0) >= 100:
        order = sorted(set_plays.PLAYS, key=lambda p: fnv1a(f"{team.id}:{p}"))
        team.training.play = next((p for p in order if team.plays.get(p, 0.0) < 100), None)


def weekly(cat: Catalog, career: Career, rng: Rng) -> None:
    for team in career.teams.values():
        if team.id != career.team or career.board.sacked:
            ai_plan(cat, career, team)
        _team_week(cat, career, team)
    for pid, state in career.players.items():
        if state.team is not None and state.team in career.teams:
            _player_week(cat, career, pid, state, rng)
    practice(cat, career, rng)


def _team_week(cat: Catalog, career: Career, team: TeamState) -> None:
    load = LOADS[team.training.load]
    teach = staffing.teaching_factor(staffing.attribute(cat, career, team.id, "teaching"))
    focus = [a for a in team.training.focus if a in AREAS][:2]
    share = 1.0 if len(focus) == 1 else 0.6
    for area in AREAS:
        level = team.skills.get(area, 8.0)
        room = max(0.0, (20 - level) / 10)
        change = 0.04 * load.gain * room
        if area in focus:
            change += 0.18 * load.gain * teach * share * room
        else:
            change -= 0.025 * max(0.0, level - 9)
        team.skills[area] = round(max(1.0, min(20.0, level + change)), 2)

    play = team.training.play
    if play in set_plays.PLAYS and team.plays.get(play, 0.0) < 100:
        step = 100 / set_plays.PLAYS[play].weeks * load.gain ** 0.7 * teach
        if team.id == career.team:
            step *= manager.factor(manager.own(career, "tactics"))
        team.plays[play] = round(min(100.0, team.plays.get(play, 0.0) + step), 1)
        if team.plays[play] >= 100:
            team.training.play = None
            if team.id == career.team:
                _message(career, "training", f"Set play learned: {set_plays.PLAYS[play].name}",
                         "The team runs it without thinking now. Pick it after champion select to use it once a "
                         "series. Choose the next play to drill on the training screen.")


def quality(cat: Catalog, career: Career, pid: str, state: PlayerState, team: TeamState) -> float:
    """How much a player got out of the week, about 0.5-1.5; 1.0 is a normal week for a starter."""
    if state.burnout:
        return 0.0
    load = LOADS[team.training.load]
    dev = staffing.development_factor(staffing.attribute(cat, career, team.id, "development"))
    starter = 1.0 if pid in team.lineup.values() else 0.7
    value = load.gain ** 0.6 * dev * (0.8 + state.morale / 250) * (0.7 + state.sharpness / 200) * starter
    return value / QUALITY_NORM


def _player_week(cat: Catalog, career: Career, pid: str, state: PlayerState, rng: Rng) -> None:
    team = career.teams[state.team or ""]
    load = LOADS[team.training.load]
    mine = team.id == career.team
    name = cat.players[pid].name
    state.fatigue = max(0, min(100, state.fatigue + load.fatigue))
    state.sharpness = max(0, min(100, state.sharpness + load.sharpness))

    motivation = staffing.attribute(cat, career, team.id, "motivation")
    if state.burnout:
        state.burnout -= 1
        if state.burnout == 0 and mine:
            _message(career, "training", f"{name} is over the burnout", "Ready to train and play at full strength again.")
    elif state.fatigue >= BURNOUT_FROM and rng.chance((state.fatigue - 55) / 60 * (1.2 - motivation / 40)):
        state.burnout = BURNOUT_WEEKS
        state.morale = max(0, state.morale - 10)
        if mine:
            _message(career, "training", f"{name} has burned out",
                     f"Fatigue {state.fatigue}. {name} plays well below their level and learns nothing for "
                     f"{BURNOUT_WEEKS} weeks. A lighter load helps the rest of the team avoid the same.")

    calm = 45 if state.unsettled else 70
    state.morale = max(0, min(100, state.morale + (calm - state.morale) // staffing.morale_recovery_divisor(motivation)))
    settle = SETTLE_CHANCE * (manager.factor(manager.own(career, "man_management")) if mine else 1.0)
    if state.unsettled and state.morale >= SETTLE_MORALE and rng.chance(settle):
        state.unsettled = False
        if mine:
            _message(career, "player", f"{name} has settled",
                     f"Winning has changed {name}'s mind: they are happy here again and no longer want to leave.")

    q = quality(cat, career, pid, state, team)
    state.development = (state.development + [round(q, 2)])[-52:]
    player = cat.players[pid]
    gap = growth_target(cat, career, pid) - roster.overall(cat, career, pid)
    focus = state.training.attribute
    if gap > 0 and rng.chance(min(GROWTH_CHANCE_MAX, GROWTH_CHANCE * gap) * q):
        attr = focus if focus and rng.chance(0.6) else (rng.pick(list(player.attributes)) or "mechanics")
        state.growth[attr] = round(state.growth.get(attr, 0.0) + 0.35, 2)
    elif focus and rng.chance(0.1 * q):
        # Extra work still adds a little once a player is at their level.
        state.growth[focus] = round(state.growth.get(focus, 0.0) + 0.25, 2)

    champion = state.training.champion
    if champion and q > 0:
        teach = staffing.teaching_factor(staffing.attribute(cat, career, team.id, "teaching"))
        if roster.mastery(cat, career, pid, champion) < CHAMPION_CAP:
            state.learned[champion] = state.learned.get(champion, 0) + max(1, round(4 * teach * load.gain ** 0.5))
        if roster.mastery(cat, career, pid, champion) >= CHAMPION_CAP:
            state.training.champion = None
            if mine:
                _message(career, "training", f"{name} has learned {cat.champions[champion].name}",
                         f"Mastery {roster.mastery(cat, career, pid, champion)}: ready for stage. Pick another "
                         "champion or attribute on the training screen.")


def practice(cat: Catalog, career: Career, rng: Rng) -> None:
    """The coach's own pick: a starter without a champion of their own to learn may work on one
    of the patch's best champions for their role. How often depends on the coach's teaching."""
    from app.game.catalog import ROLES

    best: dict[str, list[str]] = {}
    for role in ROLES:
        fits = [c.id for c in cat.champions.values() if role in c.roles]
        best[role] = sorted(fits, key=lambda cid: -career.meta.power.get(cid, 0.0))[:5]
    for team in career.teams.values():
        chance = staffing.practice_chance(staffing.attribute(cat, career, team.id, "teaching"))
        for role, pid in team.lineup.items():
            if career.players[pid].training.champion or not rng.chance(chance):
                continue
            target = next((c for c in best[role] if roster.mastery(cat, career, pid, c) < PRACTICE_CAP), None)
            if target:
                learned = career.players[pid].learned
                learned[target] = learned.get(target, 0) + PRACTICE_GAIN


# ---------- long-term growth ----------


def ceiling(cat: Catalog, career: Career, pid: str) -> float:
    """The real potential, hidden. An established player's is up to CEILING_SPREAD either side of
    the scouts' estimate. A rookie's runs from 11 below it to 3 above, 4 below on average: more than
    one rookie in three ends five or more short, one in ten a little past it."""
    a = fnv1a(f"{career.seed}|{pid}|ceiling-a") / 0xFFFFFFFF
    b = fnv1a(f"{career.seed}|{pid}|ceiling-b") / 0xFFFFFFFF
    middle = (a + b) / 2  # 0 to 1, a half most often
    if pid.startswith("r"):  # rookies.is_rookie, without the import
        low, high = ROOKIE_CEILING
        return cat.players[pid].potential + low + (high - low) * middle
    return cat.players[pid].potential + (2 * middle - 1) * CEILING_SPREAD


def season_quality(state: PlayerState) -> float:
    recent = state.development[-26:]
    return sum(recent) / len(recent) if recent else 1.0


def growth_target(cat: Catalog, career: Career, pid: str) -> float:
    """Where a player is heading: the hidden ceiling, moved by how well they have trained, at most
    TRAINING_BONUS past it."""
    return ceiling(cat, career, pid) + min(TRAINING_BONUS, (season_quality(career.players[pid]) - 1) * 4)


def development_trend(state: PlayerState) -> str:
    if not state.development:
        return "Not assessed"
    q = season_quality(state)
    if state.burnout:
        return "Burned out"
    if q >= 1.15:
        return "Thriving"
    if q >= 0.9:
        return "Developing"
    if q >= 0.7:
        return "Slow"
    return "Stagnating"


def condition_labels(state: PlayerState) -> list[str]:
    labels = []
    if state.burnout:
        labels.append("Burned out")
    elif state.fatigue >= BURNOUT_FROM:
        labels.append("Exhausted")
    elif state.fatigue >= 40:
        labels.append("Tired")
    if state.sharpness < COMPLACENT_BELOW:
        labels.append("Complacent")
    elif state.sharpness >= 85:
        labels.append("Sharp")
    if state.unsettled:
        labels.append("Unsettled")
    return labels


def condition(state: PlayerState) -> float:
    """Power a player gains or loses on the day from their state, on top of their rating."""
    value = state.form * 0.8 + (state.morale - 70) / 20 - state.fatigue / 30 + (state.sharpness - 70) / 20
    if state.burnout:
        value -= 4
    if state.unsettled:
        value -= 1
    return value


# ---------- the analyst's review ----------


def _ours(record: GameRecord, team: str) -> tuple[int, int]:
    """Index of `team` and of its opponent in the record's [blue, red] lists."""
    return (0, 1) if record.blue == team else (1, 0)


def team_games(career: Career, team: str) -> list[GameRecord]:
    matches = sorted((m for m in career.matches.values() if team in (m.home, m.away) and m.games),
                     key=lambda m: (m.day, m.id))
    return [g for m in matches for g in m.games if g.leads != [0, 0] or g.fights != [0, 0]]


def read_games(games: list[GameRecord], team: str) -> dict[str, dict]:
    """What the numbers say about each area: a problem score (0 is fine, 1 is a big problem) and a line."""
    n = len(games)
    gold15 = sum((g.gold15 if g.blue == team else -g.gold15) for g in games) / n
    led = [g for g in games if g.leads[_ours(g, team)[0]] >= 3500]
    thrown = [g for g in led if g.winner != team]
    fights = [sum(g.fights[_ours(g, team)[i]] for g in games) for i in (0, 1)]
    fight_share = fights[0] / max(1, sum(fights))
    dragons = [sum(g.dragons[_ours(g, team)[i]] for g in games) for i in (0, 1)]
    barons = [sum(g.barons[_ours(g, team)[i]] for g in games) for i in (0, 1)]
    obj_share = (dragons[0] + 2 * barons[0]) / max(1, sum(dragons) + 2 * sum(barons))
    towers = [sum(g.towers[_ours(g, team)[i]] for g in games) for i in (0, 1)]
    tower_share = towers[0] / max(1, sum(towers))
    won = [g for g in games if g.winner == team]
    long_wins = sum(1 for g in won if g.duration > 34 * 60)
    return {
        "early_game": {"score": max(0.0, -gold15 / 1800),
                       "line": f"{'Behind' if gold15 < 0 else 'Ahead'} by {abs(gold15):,.0f} gold at 15 minutes on average"},
        "closing": {"score": (len(thrown) / len(led) if led else 0.0) * 1.3 + long_wins / max(1, len(won)) * 0.3 - 0.1,
                    "line": f"Lost {len(thrown)} of {len(led)} games after leading by 3,500 gold or more"
                    + (f", {long_wins} of {len(won)} wins went past 34 minutes" if won else "")},
        "teamfighting": {"score": (0.5 - fight_share) * 3,
                         "line": f"Won {fight_share:.0%} of teamfights ({fights[0]} of {sum(fights)})"},
        "objectives": {"score": (0.5 - obj_share) * 2.5,
                       "line": f"Took {dragons[0]} of {sum(dragons)} dragons and {barons[0]} of {sum(barons)} Barons"},
        "macro": {"score": (0.5 - tower_share) * 2.0,
                  "line": f"Took {tower_share:.0%} of the towers destroyed"},
    }


def review(cat: Catalog, career: Career) -> InboxMessage | None:
    """Every few games: the analyst's read on what to work on."""
    games = team_games(career, career.team)
    if len(games) - career.reviewed_games < REVIEW_GAMES:
        return None
    career.reviewed_games = len(games)
    recent = games[-10:]
    reading = read_games(recent, career.team)
    analyst = cat.staff.get(career.teams[career.team].analyst or "")
    skill = staffing.attribute(cat, career, career.team, "scouting")
    blur = (20 - skill) / 20 * 0.45
    for area, row in reading.items():
        row["score"] += blur * _spread(f"{career.seed}|{len(games)}|{area}", 1.0)
    ranked = sorted(reading, key=lambda a: -reading[a]["score"])
    recommend = [a for a in ranked[:2] if reading[a]["score"] >= 0.15]
    if len(recommend) == 2 and reading[recommend[1]]["score"] < reading[recommend[0]]["score"] * 0.6:
        recommend = recommend[:1]
    who = analyst.name if analyst else "Your coaching staff"
    sure = "I am confident about this" if skill >= 15 else "I am fairly sure" if skill >= 10 else "I think"
    if recommend:
        names = " and ".join(AREAS[a].lower() for a in recommend)
        subject = f"Analyst review: work on {names}"
        lead = f"{sure}: {names} is where we lose the most."
    else:
        subject = "Analyst review: no glaring weakness"
        lead = "Nothing stands out. Keep the current plan, or use the time to drill a new set play."
    lines = [f"{who} watched our last {len(recent)} games.", lead, ""]
    lines += [f"- {AREAS[a]}: {reading[a]['line']}" for a in ranked]
    report = {
        "kind": "review", "team": career.team, "games": len(recent), "analyst": analyst.name if analyst else None,
        "skill": skill,
        "recommend": recommend,
        "areas": [{"area": a, "label": AREAS[a], "line": reading[a]["line"], "score": round(reading[a]["score"], 2),
                   "level": round(career.teams[career.team].skills.get(a, 10.0), 1)} for a in ranked],
    }
    return _message(career, "training", subject, "\n".join(lines), report)


def _message(career: Career, kind: str, subject: str, body: str, report: dict | None = None) -> InboxMessage:
    msg = InboxMessage(id=career.next_message, day=career.day, kind=kind, subject=subject, body=body,  # type: ignore[arg-type]
                       report=report)
    career.inbox.append(msg)
    career.next_message += 1
    return msg


# ---------- the manager's settings ----------


def set_team(career: Career, load: str | None, focus: list[str] | None, play: str | None, clear_play: bool) -> None:
    from app.game.errors import IllegalAction

    team = career.teams[career.team]
    if load is not None:
        if load not in LOADS:
            raise IllegalAction("Unknown load")
        team.training.load = load  # type: ignore[assignment]
    if focus is not None:
        if len(focus) > 2 or any(a not in AREAS for a in focus) or len(set(focus)) != len(focus):
            raise IllegalAction("Pick up to two different team areas")
        team.training.focus = list(focus)
    if clear_play:
        team.training.play = None
    elif play is not None:
        if play not in set_plays.PLAYS:
            raise IllegalAction("Unknown set play")
        if team.plays.get(play, 0.0) >= 100:
            raise IllegalAction("The team already knows that play")
        team.training.play = play


def set_player(cat: Catalog, career: Career, pid: str, attribute: str | None, champion: str | None) -> None:
    from app.game.errors import IllegalAction
    from app.game.ratings import ATTRIBUTES

    team = career.teams[career.team]
    if pid not in team.roster:
        raise IllegalAction("That player is not on your roster")
    if attribute is not None and attribute not in ATTRIBUTES:
        raise IllegalAction("Unknown attribute")
    if champion is not None:
        if champion not in cat.champions:
            raise IllegalAction("Unknown champion")
        if roster.mastery(cat, career, pid, champion) >= CHAMPION_CAP:
            raise IllegalAction(f"{cat.players[pid].name} already knows {cat.champions[champion].name} well")
    state = career.players[pid]
    state.training.attribute = attribute
    state.training.champion = champion
