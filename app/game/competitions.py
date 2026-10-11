"""Competition stages: round robins (optionally in groups), seeded single-elimination brackets
with byes, double-elimination brackets with an upper and a lower bracket, and a Swiss stage.
Each stage owns its matches; when the last one is played the stage ranks its teams and the
competition moves on to the next stage or finishes."""

from collections import defaultdict
from datetime import date, timedelta

from app.game.rng import Rng
from app.game.state import Career, Competition, Match, Stage

# ---------- days ----------

_WEEKDAY_PREFERENCE = (5, 6, 4, 3, 2, 0, 1)  # Saturday first, Tuesday last


def spread_days(start: date, end: date, count: int) -> list[date]:
    """`count` match days between start and end, weekends first, spread evenly over the weeks."""
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if count >= len(days):
        return days[:count] if count <= len(days) else days + [days[-1]] * (count - len(days))
    weeks: dict[int, list[date]] = defaultdict(list)
    for d in days:
        weeks[(d - start).days // 7].append(d)
    per_week = -(-count // len(weeks))
    chosen: list[date] = []
    for week in sorted(weeks):
        ranked = sorted(weeks[week], key=lambda d: _WEEKDAY_PREFERENCE.index(d.weekday()))
        chosen += ranked[:per_week]
    chosen.sort()
    if len(chosen) > count:
        # Drop from the busiest stretch so the schedule stays even.
        step = len(chosen) / count
        chosen = [chosen[int(i * step)] for i in range(count)]
    return chosen


# ---------- matches ----------


def new_match(career: Career, comp: Competition, stage: Stage, label: str, day: date, best_of: int,
              home: str | None = None, away: str | None = None, home_from: str | None = None,
              away_from: str | None = None, **bracket) -> Match:
    mid = f"{stage.id}-{len(stage.matches) + 1}"
    match = Match(
        id=mid, competition=comp.id, stage=stage.id, label=label, day=day, home=home, away=away,
        best_of=best_of, fearless=best_of > 1, home_from=home_from, away_from=away_from, **bracket,
    )
    career.matches[mid] = match
    stage.matches.append(mid)
    return match


# ---------- round robin ----------


def _circle(teams: list[str]) -> list[list[tuple[str, str]]]:
    pool: list[str | None] = list(teams)
    if len(pool) % 2:
        pool.append(None)
    n = len(pool)
    rounds = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = pool[i], pool[n - 1 - i]
            if a is not None and b is not None:
                pairs.append((a, b) if r % 2 == 0 else (b, a))
        rounds.append(pairs)
        pool = [pool[0]] + [pool[-1]] + pool[1:-1]
    return rounds


def build_round_robin(career: Career, comp: Competition, stage: Stage, start: date, end: date) -> None:
    groups = stage.groups or [stage.teams]
    per_group = [_circle(g) for g in groups]
    base_rounds = max(len(r) for r in per_group)
    total = base_rounds * stage.rounds
    days = spread_days(start, end, total)
    stage.days = days
    for leg in range(stage.rounds):
        for r in range(base_rounds):
            day = days[leg * base_rounds + r]
            label = f"Week {(day - start).days // 7 + 1}" if comp.kind == "league" else f"Round {leg * base_rounds + r + 1}"
            for rounds in per_group:
                if r >= len(rounds):
                    continue
                for a, b in rounds[r]:
                    home, away = (a, b) if leg % 2 == 0 else (b, a)
                    new_match(career, comp, stage, label, day, stage.best_of, home=home, away=away)


def standings(career: Career, stage: Stage, group: list[str] | None = None) -> list[dict]:
    teams = group or stage.teams
    rows = {t: {"team": t, "wins": 0, "losses": 0, "game_wins": 0, "game_losses": 0, "played": 0} for t in teams}
    head: dict[tuple[str, str], int] = defaultdict(int)
    for mid in stage.matches:
        m = career.matches[mid]
        if m.winner is None or m.home not in rows or m.away not in rows:
            continue
        h, a = m.score
        rows[m.home]["game_wins"] += h
        rows[m.home]["game_losses"] += a
        rows[m.away]["game_wins"] += a
        rows[m.away]["game_losses"] += h
        rows[m.winner]["wins"] += 1
        rows[m.loser]["losses"] += 1  # type: ignore[index]
        rows[m.home]["played"] += 1
        rows[m.away]["played"] += 1
        head[(m.winner, m.loser)] += 1  # type: ignore[arg-type]

    def key(row: dict) -> tuple:
        return (-row["wins"], -(row["game_wins"] - row["game_losses"]), -row["game_wins"])

    ordered = sorted(rows.values(), key=key)
    # Two teams level on everything: whoever won the meeting goes first.
    for i in range(len(ordered) - 1):
        a, b = ordered[i], ordered[i + 1]
        if key(a) == key(b) and head[(b["team"], a["team"])] > head[(a["team"], b["team"])]:
            ordered[i], ordered[i + 1] = b, a
    return ordered


# ---------- single elimination ----------


def _bracket_order(size: int) -> list[int]:
    order = [1]
    while len(order) < size:
        n = len(order) * 2
        order = [x for s in order for x in (s, n + 1 - s)]
    return order


def _round_name(remaining: int, best_of: int) -> str:
    return {2: "Final", 4: "Semifinal", 8: "Quarterfinal"}.get(remaining, f"Round of {remaining}")


def build_single_elim(career: Career, comp: Competition, stage: Stage, days_by_round: list[list[date]]) -> None:
    """Seeds come from stage.teams in order. Missing seeds are byes. With `advance` set the
    bracket stops once that many teams are left (a play-in), otherwise it runs to a final."""
    seeds = stage.teams
    size = 1
    while size < len(seeds):
        size *= 2
    slots: list[str | None] = [f"S:{s}" if s <= len(seeds) else None for s in _bracket_order(size)]
    stop = max(1, stage.advance)
    rnd = 0
    while len(slots) > stop:
        remaining = len(slots)
        days = days_by_round[min(rnd, len(days_by_round) - 1)]
        nxt: list[str | None] = []
        playing = [(slots[i], slots[i + 1]) for i in range(0, len(slots), 2)]
        real = [p for p in playing if p[0] and p[1]]
        for i, (a, b) in enumerate(playing):
            if a is None or b is None:
                nxt.append(a or b)
                continue
            final = remaining == 2 and not stage.advance
            best_of = (stage.final_best_of or stage.best_of) if final else stage.best_of
            day = days[min(real.index((a, b)) * len(days) // max(1, len(real)), len(days) - 1)]
            label = _round_name(remaining, best_of) if not stage.advance else stage.name
            match = new_match(career, comp, stage, label, day, best_of, home_from=a, away_from=b)
            _resolve(career, stage, match)
            nxt.append(f"W:{match.id}")
        slots = nxt
        rnd += 1
    stage.days = sorted({career.matches[m].day for m in stage.matches})


def _resolve(career: Career, stage: Stage, match: Match) -> None:
    for side in ("home", "away"):
        source = getattr(match, f"{side}_from")
        if getattr(match, side) is not None or not source:
            continue
        kind, _, ref = source.partition(":")
        if kind == "S":
            setattr(match, side, stage.teams[int(ref) - 1])
        else:
            feeder = career.matches[ref]
            team = feeder.winner if kind == "W" else feeder.loser
            if team:
                setattr(match, side, team)


def elim_ranking(career: Career, stage: Stage) -> list[str]:
    """Champion first, then by the round each team went out in, better seed first within a round."""
    seed = {t: i for i, t in enumerate(stage.teams)}
    out_round: dict[str, int] = {}
    matches = [career.matches[m] for m in stage.matches]
    for i, m in enumerate(matches):
        if m.loser:
            out_round[m.loser] = i
    survivors = [t for t in stage.teams if t not in out_round]
    final = matches[-1] if matches else None
    if final and final.winner and not stage.advance:
        survivors = [final.winner]
    eliminated = sorted(out_round, key=lambda t: (-out_round[t], seed[t]))
    return sorted(survivors, key=lambda t: seed[t]) + eliminated


# ---------- double elimination ----------

# Every bracket as data: key, label, bracket, round, home, away, and the place the loser finishes
# (0 when they drop to the lower bracket). Sources are "S:<seed>", "W:<key>" or "L:<key>".
DoubleElimShape = list[tuple[str, str, str, int, str, str, int]]

DOUBLE_ELIM: dict[str, DoubleElimShape] = {
    # Eight teams, all in the upper bracket (LEC Versus, LPL, MSI's bracket stage).
    "eight": [
        ("U1", "Upper quarterfinal", "upper", 0, "S:1", "S:8", 0),
        ("U2", "Upper quarterfinal", "upper", 0, "S:4", "S:5", 0),
        ("U3", "Upper quarterfinal", "upper", 0, "S:2", "S:7", 0),
        ("U4", "Upper quarterfinal", "upper", 0, "S:3", "S:6", 0),
        ("U5", "Upper semifinal", "upper", 1, "W:U1", "W:U2", 0),
        ("U6", "Upper semifinal", "upper", 1, "W:U3", "W:U4", 0),
        ("L1", "Lower round 1", "lower", 1, "L:U1", "L:U2", 7),
        ("L2", "Lower round 1", "lower", 1, "L:U3", "L:U4", 7),
        ("L3", "Lower round 2", "lower", 2, "W:L1", "L:U6", 5),
        ("L4", "Lower round 2", "lower", 2, "W:L2", "L:U5", 5),
        ("UF", "Upper final", "upper", 3, "W:U5", "W:U6", 0),
        ("L5", "Lower round 3", "lower", 3, "W:L3", "W:L4", 4),
        ("LF", "Lower final", "lower", 4, "L:UF", "W:L5", 3),
        ("GF", "Grand final", "final", 5, "W:UF", "W:LF", 2),
    ],
    # Six teams, the top four in the upper bracket and 5th and 6th in the lower (LEC, LCS Spring).
    "six_upper_four": [
        ("U1", "Upper round 1", "upper", 0, "S:1", "S:4", 0),
        ("U2", "Upper round 1", "upper", 0, "S:2", "S:3", 0),
        ("L1", "Lower round 1", "lower", 1, "L:U1", "S:5", 5),
        ("L2", "Lower round 1", "lower", 1, "L:U2", "S:6", 5),
        ("UF", "Upper final", "upper", 1, "W:U1", "W:U2", 0),
        ("L3", "Lower round 2", "lower", 2, "W:L1", "W:L2", 4),
        ("LF", "Lower final", "lower", 3, "L:UF", "W:L3", 3),
        ("GF", "Grand final", "final", 4, "W:UF", "W:LF", 2),
    ],
    # Six teams, the top two straight into the upper semifinals (LCK, CBLOL, LCS Lock-In and Summer, LCP).
    "six_byes": [
        ("U1", "Upper round 1", "upper", 0, "S:3", "S:6", 0),
        ("U2", "Upper round 1", "upper", 0, "S:4", "S:5", 0),
        ("U3", "Upper semifinal", "upper", 1, "S:1", "W:U2", 0),
        ("U4", "Upper semifinal", "upper", 1, "S:2", "W:U1", 0),
        ("L1", "Lower round 1", "lower", 2, "L:U3", "L:U1", 5),
        ("L2", "Lower round 1", "lower", 2, "L:U4", "L:U2", 5),
        ("UF", "Upper final", "upper", 2, "W:U3", "W:U4", 0),
        ("L3", "Lower round 2", "lower", 3, "W:L1", "W:L2", 4),
        ("LF", "Lower final", "lower", 4, "L:UF", "W:L3", 3),
        ("GF", "Grand final", "final", 5, "W:UF", "W:LF", 2),
    ],
}


def bracket_days(start: date, end: date, per_round: list[int]) -> list[list[date]]:
    """A day for every match: each round starts after the one before, spread over the window,
    and its matches go two a day until the next round starts."""
    total = (end - start).days + 1
    count = len(per_round)
    starts = [round(r * (total - 1) / max(1, count - 1)) for r in range(count)]
    for r in range(1, count):
        starts[r] = max(starts[r], starts[r - 1] + 1)
    out = []
    for r, matches in enumerate(per_round):
        last = starts[r + 1] - 1 if r + 1 < count else starts[r]
        span = [start + timedelta(days=d) for d in range(starts[r], max(starts[r], last) + 1)]
        out.append([span[min(i // 2, len(span) - 1)] for i in range(matches)])
    return out


def build_double_elim(career: Career, comp: Competition, stage: Stage, shape: str, start: date, end: date) -> None:
    """Every match of the bracket up front, fed by the results before it (see _resolve). Seeds
    come from stage.teams in order."""
    rows = DOUBLE_ELIM[shape]
    rounds = max(r[3] for r in rows) + 1
    per_round = [sum(1 for r in rows if r[3] == n) for n in range(rounds)]
    days = bracket_days(start, end, per_round)
    taken = [0] * rounds
    ids: dict[str, str] = {}

    def source(ref: str) -> str:
        kind, _, key = ref.partition(":")
        return ref if kind == "S" else f"{kind}:{ids[key]}"

    for key, label, bracket, rnd, home, away, eliminates in sorted(rows, key=lambda r: r[3]):
        day = days[rnd][taken[rnd]]
        taken[rnd] += 1
        match = new_match(career, comp, stage, label, day, stage.best_of, home_from=source(home),
                          away_from=source(away), bracket=bracket, round=rnd, eliminates=eliminates)
        _resolve(career, stage, match)
        ids[key] = match.id
    stage.days = sorted({career.matches[m].day for m in stage.matches})


def double_elim_ranking(career: Career, stage: Stage) -> list[str]:
    """The grand final's winner, then everyone by the place the match they went out in gives,
    better seed first among teams that went out at the same point."""
    seed = {t: i for i, t in enumerate(stage.teams)}
    place: dict[str, int] = {}
    for mid in stage.matches:
        m = career.matches[mid]
        if m.loser and m.eliminates:
            place[m.loser] = m.eliminates
            if m.bracket == "final" and m.winner:
                place[m.winner] = 1
    return sorted(stage.teams, key=lambda t: (place.get(t, 99), seed[t]))


# ---------- swiss ----------


def swiss_records(career: Career, stage: Stage) -> dict[str, list[int]]:
    record = {t: [0, 0] for t in stage.teams}
    for mid in stage.matches:
        m = career.matches[mid]
        if m.winner:
            record[m.winner][0] += 1
            record[m.loser][1] += 1  # type: ignore[index]
    return record


def build_swiss_round(career: Career, comp: Competition, stage: Stage, rng: Rng, region_of: dict[str, str]) -> bool:
    """Pair the next Swiss round among teams still alive. Returns False when nobody is left."""
    record = swiss_records(career, stage)
    target = 3
    alive = [t for t in stage.teams if record[t][0] < target and record[t][1] < target]
    if not alive:
        return False
    rnd = sum(record[alive[0]])  # everyone alive has played the same number of rounds
    if rnd >= len(stage.days):
        return False
    met = {frozenset((career.matches[m].home, career.matches[m].away)) for m in stage.matches}
    buckets: dict[tuple[int, int], list[str]] = defaultdict(list)
    for t in alive:
        buckets[tuple(record[t])].append(t)  # type: ignore[index]
    day = stage.days[rnd]
    for rec, teams in sorted(buckets.items(), key=lambda kv: (-kv[0][0], kv[0][1])):
        pool = rng.shuffle(teams)
        decisive = rec[0] == target - 1 or rec[1] == target - 1
        best_of = 3 if decisive else stage.best_of
        while len(pool) >= 2:
            a = pool.pop(0)
            # First round avoids teams from the same region, later rounds avoid rematches.
            b = next(
                (x for x in pool if frozenset((a, x)) not in met and (rnd > 0 or region_of[x] != region_of[a])),
                pool[0],
            )
            pool.remove(b)
            new_match(career, comp, stage, f"Swiss round {rnd + 1} ({rec[0]}-{rec[1]})", day, best_of, home=a, away=b)
    return True


def swiss_ranking(career: Career, stage: Stage) -> list[str]:
    record = swiss_records(career, stage)
    seed = {t: i for i, t in enumerate(stage.teams)}
    return sorted(stage.teams, key=lambda t: (-record[t][0], record[t][1], seed[t]))


# ---------- progression ----------


def stage_complete(career: Career, stage: Stage) -> bool:
    return bool(stage.matches) and all(career.matches[m].winner for m in stage.matches)


def rank_stage(career: Career, stage: Stage) -> list[str]:
    if stage.kind == "round_robin":
        if stage.groups:
            # Group winners first, then runners-up and so on.
            tables = [[r["team"] for r in standings(career, stage, g)] for g in stage.groups]
            return [table[i] for i in range(max(len(t) for t in tables)) for table in tables if i < len(table)]
        return [r["team"] for r in standings(career, stage)]
    if stage.kind == "single_elim":
        return elim_ranking(career, stage)
    if stage.kind == "double_elim":
        return double_elim_ranking(career, stage)
    return swiss_ranking(career, stage)


def on_match_finished(career: Career, match: Match) -> None:
    """Feed the winner and loser into any bracket match waiting on them."""
    comp = career.competitions[match.competition]
    stage = next(s for s in comp.stages if s.id == match.stage)
    for mid in stage.matches:
        waiting = career.matches[mid]
        sources = ((waiting.home_from or "").partition(":")[2], (waiting.away_from or "").partition(":")[2])
        if waiting.winner is None and match.id in sources:
            _resolve(career, stage, waiting)
