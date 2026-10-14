"""The season: three domestic splits in every region and the three international events between
them, laid out on real dates.

    Dec 1        pre-season draft
    Jan 17       split 1 (LEC Versus, LCK Cup, LCS Lock-In, ...), playoffs from Feb 20
    Mar 13-22    First Stand, the split 1 winners (and LCK/LPL runners-up)
    Mar 28       split 2, playoffs from May 22
    Jun 26-Jul 12  MSI: a play-in, then a double-elimination bracket of eight
    Jul 18       split 3, playoffs from Sep 4
    Sep 24-Nov 7 Worlds: a play-in, a Swiss stage, then best-of-five knockouts

The international events follow Riot's 2026 rules:
- First Stand: two teams from the LCK and the LPL, one from every other region. The region that
  wins it sends both its MSI teams straight to the bracket.
- MSI: two teams a region, one from Brazil. Every region's first seed and the First Stand
  region's second go straight to the bracket of eight, seeded by how their regions did at First
  Stand; the other four second seeds play in for the last place (double elimination, Bo5).
- Worlds: three teams a region, two from Brazil, and a fourth for the two best regions at MSI;
  the MSI champion is invited if it reached its region's playoffs. The last team of each of the
  four other regions plays in for the sixteenth place in the Swiss stage. The Swiss pots go by
  seed, then by the regions' place in the global power rankings (power.py).

Every domestic playoff is a best-of-five double-elimination bracket, as in 2026: eight teams in
the LPL and the LEC Versus, six everywhere else. The LEC (Spring and Summer) and the LCS Spring
put their top four in the upper bracket and 5th and 6th in the lower one; the LCK, CBLOL, LCP and
the other LCS splits send their top two straight to the upper semifinals.

Domestic schedules are built when the season starts. Playoffs are built when the regular season
ends, and each international event when every region has finished the split before it."""

from dataclasses import dataclass
from datetime import date

from app.game import competitions as comps
from app.game import power
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

# Six-team playoffs with the top four in the upper bracket; every other six-team playoff gives the
# top two a bye (see competitions.DOUBLE_ELIM).
UPPER_FOUR = {("LEC", 2), ("LEC", 3), ("LCS", 2)}

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
                  {"KR": 2, "CN": 2, "EMEA": 2, "NA": 2, "APAC": 2, "BR": 1}, 2000),
    # Before the fourth team the two best regions at MSI send (EXTRA_WORLDS_SLOTS).
    International("WORLDS", "World Championship", 3, (9, 24), (11, 7),
                  {"KR": 3, "CN": 3, "EMEA": 3, "NA": 3, "APAC": 3, "BR": 2}, 5000),
)
EXTRA_WORLDS_SLOTS = 2  # the two best regions at MSI send a fourth team to Worlds

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


def playoff_shape(league: str, split: int, teams: int) -> str | None:
    if teams == 8:
        return "eight"
    if teams == 6:
        return "six_upper_four" if (league, split) in UPPER_FOUR else "six_byes"
    return None


def _build_playoffs(career: Career, comp: Competition, seeds: list[str]) -> None:
    split = SPLITS[comp.split - 1]  # type: ignore[operator]
    start, end = _d(career.season, split.playoffs[0]), _d(career.season, split.playoffs[1])
    shape = playoff_shape(comp.league or "", comp.split or 0, len(seeds))
    if shape:
        stage = Stage(id=f"{comp.id}-PO", name="Playoffs", kind="double_elim", teams=seeds, best_of=5)
        comp.stages.append(stage)
        comps.build_double_elim(career, comp, stage, shape, start, end)
        return
    stage = Stage(id=f"{comp.id}-PO", name="Playoffs", kind="single_elim", teams=seeds, best_of=5, final_best_of=5)
    comp.stages.append(stage)
    comps.build_single_elim(career, comp, stage, _playoff_days(start, end, 3 if len(seeds) > 4 else 2))


# ---------- international ----------


def _by_power(career: Career) -> list[str]:
    """Regions from the strongest down in the global power rankings, or the usual order before them."""
    return power.region_order(career) or list(REGION_ORDER)


def event_regions(cat: Catalog, career: Career, event_id: str) -> list[str]:
    """Regions by how they did at this season's event, best first (by their best team's place),
    then the rest by power."""
    comp = career.competitions.get(f"{career.season}-{event_id}")
    order: list[str] = []
    for team in (comp.placements if comp else []):
        if cat.teams[team].region not in order:
            order.append(cat.teams[team].region)
    return order + [r for r in _by_power(career) if r not in order]


def slots(cat: Catalog, career: Career, event: International) -> dict[str, int]:
    """Teams each region sends: the event's own, and at Worlds a fourth for the two best regions at MSI."""
    out = dict(event.slots)
    if event.id == "WORLDS":
        for region in event_regions(cat, career, "MSI")[:EXTRA_WORLDS_SLOTS]:
            out[region] += 1
    return out


def expected_worlds_slots(career: Career, region: str) -> int:
    """The Worlds teams a region can count on before MSI: the fourth for the two strongest regions."""
    worlds = next(e for e in INTERNATIONALS if e.id == "WORLDS")
    return worlds.slots[region] + (1 if region in _by_power(career)[:EXTRA_WORLDS_SLOTS] else 0)


def _playoff_teams(comp: Competition) -> list[str]:
    return comp.stages[1].teams if len(comp.stages) > 1 else comp.placements


def _qualifiers(cat: Catalog, career: Career, event: International) -> list[tuple[str, int, str]]:
    """(region, rank in region, team), every region's first seed before anyone's second, and the
    regions within a seed by power. At Worlds the MSI champion is invited if it reached its region's
    playoffs, in place of the last team that would have gone."""
    seats = slots(cat, career, event)
    msi = career.competitions.get(f"{career.season}-MSI")
    champion = msi.placements[0] if event.id == "WORLDS" and msi and msi.placements else None
    rows = []
    for region_id in REGION_ORDER:
        league = cat.regions[region_id].league
        comp = career.competitions[f"{career.season}-{league}-{event.after_split}"]
        teams = comp.placements[: seats[region_id]]
        if (champion and cat.teams[champion].region == region_id and champion not in teams
                and champion in _playoff_teams(comp)):
            teams = [*teams[:-1], champion]
        rows += [(region_id, rank, team) for rank, team in enumerate(teams, start=1)]
    order = _by_power(career)
    rows.sort(key=lambda r: (r[1], order.index(r[0])))
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
        # Every first seed, seeded by how its region did at First Stand, and the First Stand region's
        # second go straight to the bracket; the other second seeds play in for the eighth place.
        order = event_regions(cat, career, "FST")
        firsts = sorted((t for _, n, t in qualified if n == 1), key=lambda t: order.index(cat.teams[t].region))
        bye = [t for r, n, t in qualified if r == order[0] and n == 2]
        play_in = sorted((t for t in teams if t not in firsts + bye), key=lambda t: order.index(cat.teams[t].region))
        comp.entrants = firsts + bye + play_in  # the bracket's seeds in order, then the play-in
        stage = Stage(id=f"{comp.id}-PI", name="Play-In", kind="double_elim", teams=play_in, best_of=5, advance=1)
        comp.stages.append(stage)
        comps.build_double_elim(career, comp, stage, "four", date(season, 6, 26), date(season, 6, 30))
    else:
        # The last team of every region without a fourth plays in for the sixteenth Swiss place; the
        # rest keep their seed order, which makes the Swiss pots.
        extra = set(event_regions(cat, career, "MSI")[:EXTRA_WORLDS_SLOTS])
        last = {r: t for r, _, t in sorted(qualified, key=lambda q: q[1])}
        order = _by_power(career)
        play_in = sorted((t for r, t in last.items() if r not in extra), key=lambda t: order.index(cat.teams[t].region))
        comp.entrants = [t for _, _, t in qualified if t not in play_in] + play_in
        stage = Stage(id=f"{comp.id}-PI", name="Play-In", kind="double_elim", teams=play_in, best_of=5, advance=1)
        comp.stages.append(stage)
        comps.build_double_elim(career, comp, stage, "four", date(season, 9, 24), date(season, 9, 28))

    names = ", ".join(cat.teams[t].tag for t in teams)
    _news(career, f"{comp.name} is set", f"Qualified: {names}.")
    if stage.kind == "swiss":
        _swiss_draw(cat, career, comp, stage)
    return comp


def _swiss_draw(cat: Catalog, career: Career, comp: Competition, stage: Stage) -> None:
    """Tell the manager how the Swiss round just drawn pairs up, pool by pool."""
    pools = comps.swiss_pools(career, stage)
    rnd = max(sum(p) for p in pools.values()) + 1
    pot = {t: i + 1 for i, teams in enumerate(stage.pots) for t in teams}
    lines = []
    for mid in stage.matches:
        w, l = pools[mid]
        if w + l + 1 == rnd:
            m = career.matches[mid]
            label = f"Pot {pot[m.home]} v Pot {pot[m.away]}" if rnd == 1 and pot else f"{w}-{l}"  # type: ignore[index]
            lines.append(f"{label}: {cat.teams[m.home].tag} vs {cat.teams[m.away].tag}")  # type: ignore[index]
    career.inbox.append(InboxMessage(
        id=career.next_message, day=career.day, kind="draw", subject=f"{comp.name}: the Swiss round {rnd} draw",
        body="\n".join(lines), competition=comp.id, round=rnd,
    ))
    career.next_message += 1


def _build_worlds_swiss(cat: Catalog, career: Career, comp: Competition, teams: list[str], rng: Rng) -> None:
    """The Swiss stage of sixteen, in pots of four by seed and region power (the order of `teams`,
    the play-in winner last). The first round draws pot 1 against pot 4 and pot 2 against pot 3;
    within a record, a team from a higher pot ranks first."""
    season = career.season
    pots = [teams[i:i + 4] for i in range(0, len(teams), 4)]
    stage = Stage(id=f"{comp.id}-SW", name="Swiss stage", kind="swiss", teams=teams, pots=pots, best_of=1,
                  advance=8, days=[date(season, 10, d) for d in (1, 3, 5, 8, 10)])
    comp.stages.append(stage)
    comps.build_swiss_round(career, comp, stage, rng, {t: cat.teams[t].region for t in teams})
    _swiss_draw(cat, career, comp, stage)


def _build_international_knockout(career: Career, comp: Competition, seeds: list[str]) -> None:
    season = career.season
    if comp.id.endswith("MSI") and len(seeds) == 8:
        stage = Stage(id=f"{comp.id}-KO", name="Bracket stage", kind="double_elim", teams=seeds, best_of=5)
        comp.stages.append(stage)
        comps.build_double_elim(career, comp, stage, "eight", date(season, 7, 2), date(season, 7, 12))
        return
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
                _swiss_draw(cat, career, comp, stage)
                continue
        if not comps.stage_complete(career, stage):
            continue
        stage.finished = True
        stage.ranking = comps.rank_stage(career, stage)
        _advance_competition(cat, career, comp, stage, rng)
        if comp.status == "finished":
            finished.append(comp.id)
    for comp_id in finished:
        _after_competition(cat, career, career.competitions[comp_id], rng)
    return finished


def _advance_competition(cat: Catalog, career: Career, comp: Competition, stage: Stage, rng: Rng) -> None:
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
            # The direct places keep their seed order and the play-in winner comes last.
            direct = [t for t in comp.entrants if t not in stage.teams]
            if comp.id.endswith("MSI"):
                _build_international_knockout(career, comp, direct + stage.ranking[:1])
            else:
                _build_worlds_swiss(cat, career, comp, direct + stage.ranking[:1], rng)
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
    if comp.id == f"{career.season}-FST":
        region = cat.teams[comp.placements[0]].region
        _news(career, f"The {_league(cat, region)} earn two MSI byes",
              f"{winner.name} won First Stand, so both {_league(cat, region)} teams go straight to the MSI bracket stage. "
              "Every other region's second seed plays in for the last place, and the bracket is seeded by how the "
              "regions did at First Stand." + _yours(cat, career, [region], "Your region is one of them."))
    elif comp.id == f"{career.season}-MSI":
        best = event_regions(cat, career, "MSI")[:EXTRA_WORLDS_SLOTS]
        names = " and the ".join(_league(cat, r) for r in best)
        _news(career, f"The {names} send four teams to Worlds",
              f"The two best regions at MSI, the {names}, earn a fourth place at Worlds, and their teams skip the "
              f"play-in. {winner.name} are invited as MSI champions if they reach their region's playoffs. The last "
              "team of every other region plays in for the sixteenth place in the Swiss stage."
              + _yours(cat, career, best, "Your region sends four."))
    if comp.kind == "league":
        from app.game import jobs

        jobs.split_review(cat, career, comp, rng)
        split = comp.split or 0
        event = next((e for e in INTERNATIONALS if e.after_split == split), None)
        done = all(
            career.competitions[f"{career.season}-{cat.regions[r].league}-{split}"].status == "finished"
            for r in REGION_ORDER
        )
        if event and done and f"{career.season}-{event.id}" not in career.competitions:
            create_international(cat, career, event, rng)


def _league(cat: Catalog, region: str) -> str:
    return cat.leagues[cat.regions[region].league].name


def _yours(cat: Catalog, career: Career, regions: list[str], line: str) -> str:
    return f"\n{line}" if cat.teams[career.team].region in regions else ""


def announce_places(cat: Catalog, career: Career) -> None:
    """At the start of a season: how many teams each region sends to each international event."""
    order = _by_power(career)

    def places(event: International) -> str:
        return ", ".join(f"{_league(cat, r)} {event.slots[r]}" for r in order)

    fst, msi, worlds = INTERNATIONALS
    _news(career, f"International places for {career.season}",
          f"First Stand (March): {places(fst)}. The winning region sends both its MSI teams straight to the "
          "bracket stage.\n"
          f"MSI (June and July): {places(msi)}. Every region's first seed and the First Stand region's second go "
          "straight to the bracket; the other second seeds play in for the last place.\n"
          f"Worlds (September to November): {places(worlds)}, and a fourth for the two best regions at MSI. The "
          "last team of every other region plays in for the sixteenth place in the Swiss stage, whose pots follow "
          "the global power rankings.")


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _news(career: Career, subject: str, body: str, kind: str = "news") -> None:
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind=kind, subject=subject, body=body))  # type: ignore[arg-type]
    career.next_message += 1


def season_over(career: Career) -> bool:
    worlds = career.competitions.get(f"{career.season}-WORLDS")
    return worlds is not None and worlds.status == "finished"
