"""The season: three domestic splits in every region and the three international events between
them, laid out on real dates.

    Dec 1        pre-season draft
    Jan 17       split 1 (LEC Versus, LCK Cup, LCS Lock-In, ...), playoffs from Feb 20
    Mar 13-22    First Stand, the split 1 winners (and LCK/LPL runners-up)
    Mar 28       split 2, playoffs from May 22
    Jun 26-Jul 12  MSI
    Jul 18       split 3, playoffs from Sep 4
    Oct 1-Nov 7  Worlds: a Swiss stage, then best-of-five knockouts

Domestic schedules are built when the season starts. Playoffs are built when the regular season
ends, and each international event when every region has finished the split before it."""

from dataclasses import dataclass
from datetime import date

from app.game import competitions as comps
from app.game.catalog import Catalog
from app.game.rng import Rng
from app.game.state import Career, Competition, InboxMessage, Stage

REGION_ORDER = ("KR", "CN", "EMEA", "NA", "APAC", "BR")


@dataclass(frozen=True)
class SplitDates:
    number: int
    regular: tuple[tuple[int, int], tuple[int, int]]
    playoffs: tuple[tuple[int, int], tuple[int, int]]


SPLITS = (
    SplitDates(1, ((1, 17), (2, 15)), ((2, 20), (3, 1))),
    SplitDates(2, ((3, 28), (5, 17)), ((5, 22), (6, 7))),
    SplitDates(3, ((7, 18), (8, 30)), ((9, 4), (9, 20))),
)

SPLIT_NAMES = {
    "LCK": ("Cup", "Rounds 1-2", "Rounds 3-4"),
    "LPL": ("Split 1", "Split 2", "Split 3"),
    "LEC": ("Versus", "Spring", "Summer"),
    "LCS": ("Lock-In", "Spring", "Summer"),
    "CBLOL": ("Cup", "Split 1", "Split 2"),
    "LCP": ("Split 1", "Split 2", "Split 3"),
}

# Per split: (round robin legs, regular season best-of, playoff teams)
FORMATS = {
    "LCK": ((1, 3, 6), (2, 3, 6), (2, 3, 6)),
    "LPL": ((1, 3, 8), (1, 3, 8), (1, 3, 8)),
    "LEC": ((1, 1, 8), (1, 3, 6), (1, 3, 6)),
    "LCS": ((2, 1, 6), (2, 1, 6), (2, 3, 6)),
    "CBLOL": ((2, 1, 6), (2, 1, 6), (2, 3, 6)),
    "LCP": ((1, 3, 6), (1, 3, 6), (1, 3, 6)),
}

# Prize pool of one split in thousands of USD; the last split pays half again as much.
DOMESTIC_PRIZE = {"LCK": 350, "LPL": 450, "LEC": 300, "LCS": 250, "CBLOL": 90, "LCP": 120}


@dataclass(frozen=True)
class International:
    id: str
    name: str
    after_split: int
    start: tuple[int, int]
    end: tuple[int, int]
    slots: dict[str, int]  # region -> teams
    prize: int


INTERNATIONALS = (
    International("FST", "First Stand", 1, (3, 13), (3, 22),
                  {"KR": 2, "CN": 2, "EMEA": 1, "NA": 1, "APAC": 1, "BR": 1}, 1000),
    International("MSI", "Mid-Season Invitational", 2, (6, 26), (7, 12),
                  {"KR": 2, "CN": 2, "EMEA": 2, "NA": 2, "APAC": 1, "BR": 1}, 2000),
    International("WORLDS", "World Championship", 3, (10, 1), (11, 7),
                  {"KR": 4, "CN": 4, "EMEA": 3, "NA": 2, "APAC": 2, "BR": 1}, 5000),
)

PRIZE_SHARE = (0.30, 0.17, 0.10, 0.10, 0.05, 0.05, 0.05, 0.05)


def _d(season: int, md: tuple[int, int]) -> date:
    return date(season, *md)


def season_start(season: int) -> date:
    return date(season - 1, 12, 1)


# ---------- domestic ----------


def create_season(cat: Catalog, career: Career) -> None:
    season = career.season
    for region_id in REGION_ORDER:
        league = cat.regions[region_id].league
        teams = [t.id for t in cat.league_teams(league)]
        for split in SPLITS:
            legs, best_of, playoff_teams = FORMATS[league][split.number - 1]
            name = SPLIT_NAMES[league][split.number - 1]
            comp = Competition(
                id=f"{season}-{league}-{split.number}",
                name=f"{cat.leagues[league].name} {name} {season}",
                short=f"{cat.leagues[league].name} {name}",
                kind="league",
                league=league,
                split=split.number,
                start=_d(season, split.regular[0]),
                end=_d(season, split.playoffs[1]),
                entrants=teams,
                prize_pool=int(DOMESTIC_PRIZE[league] * (1.5 if split.number == 3 else 1)),
            )
            regular = Stage(
                id=f"{comp.id}-RS", name="Regular season", kind="round_robin", teams=teams, best_of=best_of,
                rounds=legs, advance=min(playoff_teams, len(teams)),
            )
            comp.stages.append(regular)
            career.competitions[comp.id] = comp
            comps.build_round_robin(career, comp, regular, comp.start, _d(season, split.regular[1]))


def _playoff_days(start: date, end: date, rounds: int) -> list[list[date]]:
    """Weekends of the playoff window, the final alone on the last day."""
    days = comps.spread_days(start, end, max(rounds * 2, 2))
    out = []
    for r in range(rounds - 1):
        chunk = days[r * 2:(r + 1) * 2] or days[-2:-1]
        out.append(chunk)
    out.append([end])
    return out


def _build_playoffs(career: Career, comp: Competition, seeds: list[str]) -> None:
    split = SPLITS[comp.split - 1]  # type: ignore[operator]
    stage = Stage(id=f"{comp.id}-PO", name="Playoffs", kind="single_elim", teams=seeds, best_of=5, final_best_of=5)
    comp.stages.append(stage)
    rounds = 3 if len(seeds) > 4 else 2
    days = _playoff_days(_d(career.season, split.playoffs[0]), _d(career.season, split.playoffs[1]), rounds)
    comps.build_single_elim(career, comp, stage, days)


# ---------- international ----------


def _qualifiers(cat: Catalog, career: Career, event: International) -> list[tuple[str, int, str]]:
    """(region, rank in region, team), every region's first seed before anyone's second."""
    rows = []
    for region_id in REGION_ORDER:
        league = cat.regions[region_id].league
        comp = career.competitions[f"{career.season}-{league}-{event.after_split}"]
        for rank, team in enumerate(comp.placements[: event.slots[region_id]], start=1):
            rows.append((region_id, rank, team))
    rows.sort(key=lambda r: (r[1], REGION_ORDER.index(r[0])))
    return rows


def create_international(cat: Catalog, career: Career, event: International, rng: Rng) -> Competition:
    season = career.season
    qualified = _qualifiers(cat, career, event)
    comp = Competition(
        id=f"{season}-{event.id}", name=f"{event.name} {season}", short=event.name, kind="international",
        start=_d(season, event.start), end=_d(season, event.end), entrants=[t for _, _, t in qualified],
        prize_pool=event.prize,
    )
    career.competitions[comp.id] = comp
    teams = comp.entrants

    if event.id == "FST":
        groups = [[teams[0], teams[3], teams[4], teams[7]], [teams[1], teams[2], teams[5], teams[6]]]
        stage = Stage(id=f"{comp.id}-GR", name="Groups", kind="round_robin", teams=teams, best_of=3,
                      groups=groups, advance=4)
        comp.stages.append(stage)
        comps.build_round_robin(career, comp, stage, date(season, 3, 13), date(season, 3, 16))
    elif event.id == "MSI":
        direct = [t for r, n, t in qualified if r in ("KR", "CN") or (n == 1 and r in ("EMEA", "NA"))]
        play_in = [t for t in teams if t not in direct]
        stage = Stage(id=f"{comp.id}-PI", name="Play-In", kind="single_elim", teams=play_in, best_of=5, advance=2)
        comp.stages.append(stage)
        comps.build_single_elim(career, comp, stage, [[date(season, 6, 26), date(season, 6, 27)]])
    else:
        stage = Stage(id=f"{comp.id}-SW", name="Swiss stage", kind="swiss", teams=teams, best_of=1, advance=8,
                      days=[date(season, 10, d) for d in (1, 3, 5, 8, 10)])
        comp.stages.append(stage)
        region_of = {t: cat.teams[t].region for t in teams}
        comps.build_swiss_round(career, comp, stage, rng, region_of)

    names = ", ".join(cat.teams[t].tag for t in teams)
    _news(career, f"{comp.name} is set", f"Qualified: {names}.")
    return comp


def _build_international_knockout(career: Career, comp: Competition, seeds: list[str]) -> None:
    season = career.season
    stage = Stage(id=f"{comp.id}-KO", name="Knockouts", kind="single_elim", teams=seeds, best_of=5, final_best_of=5)
    comp.stages.append(stage)
    if comp.id.endswith("FST"):
        days = [[date(season, 3, 20), date(season, 3, 21)], [date(season, 3, 22)]]
    elif comp.id.endswith("MSI"):
        days = [[date(season, 7, d) for d in (2, 3, 4, 5)], [date(season, 7, 9), date(season, 7, 10)],
                [date(season, 7, 12)]]
    else:
        days = [[date(season, 10, d) for d in (22, 23, 24, 25)], [date(season, 10, 29), date(season, 11, 1)],
                [date(season, 11, 7)]]
    comps.build_single_elim(career, comp, stage, days)


# ---------- progression ----------


def update(cat: Catalog, career: Career, rng: Rng) -> list[str]:
    """Move every competition forward after matches were played. Returns ids that just finished."""
    finished: list[str] = []
    for comp in list(career.competitions.values()):
        if comp.status == "finished":
            continue
        if comp.status == "upcoming" and career.day >= comp.start:
            comp.status = "running"
        stage = next((s for s in comp.stages if not s.finished), None)
        if stage is None:
            continue
        if stage.kind == "swiss" and comps.stage_complete(career, stage):
            region_of = {t: cat.teams[t].region for t in stage.teams}
            if comps.build_swiss_round(career, comp, stage, rng, region_of):
                continue
        if not comps.stage_complete(career, stage):
            continue
        stage.finished = True
        stage.ranking = comps.rank_stage(career, stage)
        _advance_competition(cat, career, comp, stage)
        if comp.status == "finished":
            finished.append(comp.id)
    for comp_id in finished:
        _after_competition(cat, career, career.competitions[comp_id], rng)
    return finished


def _advance_competition(cat: Catalog, career: Career, comp: Competition, stage: Stage) -> None:
    if comp.kind == "league":
        if stage.id.endswith("-RS"):
            _build_playoffs(career, comp, stage.ranking[: stage.advance])
            return
        regular = comp.stages[0].ranking
        comp.placements = stage.ranking + [t for t in regular if t not in stage.ranking]
    else:
        if stage.id.endswith("-GR") or stage.id.endswith("-SW"):
            _build_international_knockout(career, comp, stage.ranking[: stage.advance])
            return
        if stage.id.endswith("-PI"):
            # Direct seeds arrive as LCK1, LPL1, LEC1, LCS1, LCK2, LPL2. Korea and China's second
            # seeds go to the middle of the bracket so the first seeds cannot meet before the final.
            direct = [t for t in comp.entrants if t not in stage.teams]
            order = (0, 1, 5, 4, 2, 3)
            seeds = [direct[i] for i in order if i < len(direct)] + stage.ranking[:2]
            _build_international_knockout(career, comp, seeds)
            return
        earlier = [s for s in comp.stages if s is not stage]
        rest: list[str] = []
        for s in reversed(earlier):
            rest += [t for t in s.ranking if t not in stage.ranking and t not in rest]
        comp.placements = stage.ranking + rest
    comp.status = "finished"
    _pay_prizes(career, comp)


def _pay_prizes(career: Career, comp: Competition) -> None:
    for place, team in enumerate(comp.placements):
        share = PRIZE_SHARE[place] if place < len(PRIZE_SHARE) else 0.02
        if team in career.teams:
            career.teams[team].cash += int(comp.prize_pool * share)


def _after_competition(cat: Catalog, career: Career, comp: Competition, rng: Rng) -> None:
    winner = cat.teams[comp.placements[0]]
    runner_up = cat.teams[comp.placements[1]] if len(comp.placements) > 1 else None
    body = f"{winner.name} win the {comp.name}" + (f", beating {runner_up.name} in the final." if runner_up else ".")
    mine = career.team in comp.placements
    if mine:
        place = comp.placements.index(career.team) + 1
        body += f"\nYour team finished {_ordinal(place)}."
    _news(career, f"{winner.tag} win the {comp.short}", body)
    if comp.kind == "league":
        split = comp.split or 0
        event = next((e for e in INTERNATIONALS if e.after_split == split), None)
        done = all(
            career.competitions[f"{career.season}-{cat.regions[r].league}-{split}"].status == "finished"
            for r in REGION_ORDER
        )
        if event and done and f"{career.season}-{event.id}" not in career.competitions:
            create_international(cat, career, event, rng)


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _news(career: Career, subject: str, body: str, kind: str = "news") -> None:
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind=kind, subject=subject, body=body))  # type: ignore[arg-type]
    career.next_message += 1


def season_over(career: Career) -> bool:
    worlds = career.competitions.get(f"{career.season}-WORLDS")
    return worlds is not None and worlds.status == "finished"
