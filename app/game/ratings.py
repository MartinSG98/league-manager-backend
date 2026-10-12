"""Player ratings worked out from 2026 stat lines, the way Worlds Mayhem rates its players: many
stats per player, judged against the other players of the same role in the same league, then
placed on one scale by how strong that league is.

Every stat is turned into a z-score inside its (league, role) group, a handful of z-scores make
up each attribute, and each attribute is standardised again inside the group so that all of
them spread the same way. Small samples are pulled towards the league average. On the 1-20
scale an average player sits at a baseline set by league strength (LCK about 15.5, LEC 13,
an average ERL about 6); the overall rating uses the same baseline on a 30-99 scale.

Form covers three seasons, not one: the 2024 and 2025 stat lines are judged the same way against
the players who share the 2026 league and role, and weigh less the older they are (SEASON_WEIGHTS).
A player with no earlier season is judged on 2026 alone. Attributes and the overall rating both
use this three-year form.

The overall rating then blends that form with the player's career (win rate over every game they
have played, held back for short careers, KDA against their role and how long they have lasted),
their record on the international stage (First Stand, MSI and Worlds since 2024, where being
there counts and winning counts more) and how their team did this year.
The blend keeps each league's average and spread, so it reorders players inside a league rather
than moving leagues up or down: a decorated veteran with a quiet year stays near the top, a
newcomer with one hot split on a weak team does not jump past them."""

import math
from collections import defaultdict
from statistics import mean, pstdev

from app.game.catalog import ChampionRecord, League, Player
from app.game.rng import fnv1a

ATTRIBUTES = (
    "mechanics", "laning", "teamfighting", "vision", "macro", "consistency", "composure", "champion_pool",
)

# How much each attribute matters to the overall rating, per role.
ROLE_WEIGHTS: dict[str, dict[str, float]] = {
    "TOP": {"laning": .25, "mechanics": .2, "teamfighting": .2, "macro": .1, "vision": .05, "consistency": .1,
            "composure": .05, "champion_pool": .05},
    "JNG": {"laning": .1, "mechanics": .15, "teamfighting": .2, "macro": .25, "vision": .15, "consistency": .05,
            "composure": .05, "champion_pool": .05},
    "MID": {"laning": .2, "mechanics": .25, "teamfighting": .2, "macro": .1, "vision": .05, "consistency": .1,
            "composure": .05, "champion_pool": .05},
    "BOT": {"laning": .2, "mechanics": .25, "teamfighting": .25, "macro": .05, "vision": .05, "consistency": .1,
            "composure": .05, "champion_pool": .05},
    "SUP": {"laning": .1, "mechanics": .1, "teamfighting": .2, "macro": .2, "vision": .25, "consistency": .05,
            "composure": .05, "champion_pool": .05},
}

# Attribute recipes: stat -> weight. A negative weight means lower is better.
_CARRY = {
    "laning": {"gd15": .4, "csd15": .3, "xpd15": .3},
    "mechanics": {"kda": .35, "solo": .35, "dpm": .3},
    "teamfighting": {"kp": .35, "dmg_share": .35, "deaths": -.3},
}
_RECIPES: dict[str, dict[str, dict[str, float]]] = {
    "TOP": _CARRY,
    "MID": _CARRY,
    "BOT": _CARRY,
    "JNG": {
        "laning": {"gd15": .5, "xpd15": .3, "fb": .2},
        "mechanics": {"kda": .4, "dpm": .3, "solo": .3},
        "teamfighting": {"kp": .45, "dmg_share": .25, "deaths": -.3},
    },
    "SUP": {
        "laning": {"gd15": .5, "xpd15": .5},
        "mechanics": {"kda": .5, "fb": .3, "fb_victim": -.2},
        "teamfighting": {"kp": .5, "deaths": -.5},
    },
}
_SHARED = {
    "vision": {"vspm": .5, "wcpm": .3, "vs_share": .2},
    "macro": {"winrate": .7, "gd15": .3},
    "consistency": {"deaths": -.5, "kda": .3, "fb_victim": -.2},
}

ATTR_SPREAD = 2.2  # attribute points per standard deviation
OVERALL_SPREAD = 6.0  # overall points per standard deviation
Z_CLIP = 2.3
SHRINK_GAMES = 8  # a player with this many games keeps half of their distance from average
MIN_GAMES = 4  # fewer than this and a stat line does not shape the league averages

# The overall rating blends three reads of a player. One season of about twenty games is noisy, so
# this year's stat line is only part of it; the career behind it and how the team did fill the rest.
FORM_WEIGHT = 0.45  # the last three seasons' stat lines against the league and role
CAREER_WEIGHT = 0.25  # the career: win rate, KDA and how long they have lasted
INTERNATIONAL_WEIGHT = 0.15  # games and wins at First Stand, MSI and Worlds
TEAM_WEIGHT = 0.15  # how this year's team did: stars sit on winning teams
CAREER_SHRINK = 200  # career games at which a win rate keeps half of its distance from 50%
CAREER_MIN = 60  # career games before a career shapes the averages it is measured against
SEASON_WEIGHTS = {"2026": 1.0, "2025": 0.6, "2024": 0.3}  # how much each season's form counts
HISTORY_YEARS = ("2025", "2024")
INTERNATIONAL_YEARS = {"2026": 1.0, "2025": 0.8, "2024": 0.6}  # older events count a little less
INTERNATIONAL_SHRINK = 15  # international games at which a win rate keeps half its distance from 50%
INTERNATIONAL_FULL = 25  # international games that count as a full presence

# What a season of salary costs in each region relative to Korea.
REGION_ECONOMY = {"KR": 1.0, "CN": 1.15, "EMEA": 0.9, "NA": 1.1, "BR": 0.45, "APAC": 0.55}


def attribute_base(strength: int) -> float:
    return 10 + (strength - 75) * 0.22


def overall_base(strength: int) -> float:
    return 30 + 3.3 * attribute_base(strength)


def asking_salary(overall: int, reputation: int, region: str) -> int:
    """Thousands of USD a season. Doubles roughly every 7 overall points."""
    raw = 18 * math.exp((overall - 50) / 10) * REGION_ECONOMY.get(region, 1.0) * (1 + reputation / 200)
    return max(15, int(round(raw / 5) * 5))


def mastery_from_games(games: int) -> int:
    """0-100. Five games make a pocket pick, twenty a comfort pick, sixty or more a signature."""
    return min(100, round(17 * math.log1p(games)))


def _hash01(*parts: str) -> float:
    return fnv1a("|".join(parts)) / 0xFFFFFFFF


def _metrics(stats: dict) -> dict[str, float | None]:
    games = stats.get("games") or 0
    solo = stats.get("solo_kills")
    return {
        "gd15": stats.get("gd15"),
        "csd15": stats.get("csd15"),
        "xpd15": stats.get("xpd15"),
        "kda": stats.get("kda"),
        "kp": stats.get("kp"),
        "dmg_share": stats.get("dmg_share"),
        "dpm": stats.get("dpm"),
        "deaths": stats.get("deaths"),
        "vspm": stats.get("vspm"),
        "wcpm": stats.get("wcpm"),
        "vs_share": stats.get("vs_share"),
        "winrate": stats.get("winrate"),
        "fb": stats.get("fb"),
        "fb_victim": stats.get("fb_victim"),
        "kills": stats.get("kills"),
        "solo": (solo / games) if games and solo is not None else None,
    }


def _zscores(values: list[float | None], sample_games: list[int], minimum: int = MIN_GAMES) -> list[float]:
    """z-scores against the players with enough games; missing values sit slightly below average."""
    known = [v for v, g in zip(values, sample_games) if v is not None and g >= minimum]
    if len(known) < 3:
        return [0.0] * len(values)
    mu, sd = mean(known), pstdev(known) or 1.0
    return [((v - mu) / sd) if v is not None else -0.3 for v in values]


def _standardise(values: list[float], weights: list[int], minimum: int = MIN_GAMES) -> list[float]:
    known = [v for v, g in zip(values, weights) if g >= minimum]
    if len(known) < 3:
        return values
    mu, sd = mean(known), pstdev(known) or 1.0
    return [(v - mu) / sd for v in values]


def _combine(z: dict[str, float], recipe: dict[str, float]) -> float:
    return sum(z[stat] * weight for stat, weight in recipe.items())


def _pool(row: dict, champion_by_key: dict[str, str]) -> tuple[ChampionRecord, ...]:
    from app.game.catalog import champ_key

    games: dict[str, int] = {}
    winrates: dict[str, float] = {}
    for entry in row["career"]:
        cid = champion_by_key.get(champ_key(entry["champion"]))
        if cid:
            games[cid] = max(games.get(cid, 0), entry["games"])
            winrates[cid] = entry["winrate"]
    for name, count in row["season_pool"]:
        cid = champion_by_key.get(champ_key(name))
        if cid:
            games[cid] = max(games.get(cid, 0), count)
    ordered = sorted(games.items(), key=lambda kv: -kv[1])
    return tuple(ChampionRecord(cid, n, winrates.get(cid)) for cid, n in ordered)


def _career(row: dict) -> tuple[int, float | None, float | None]:
    """Career games, win rate and KDA, from every champion the player has played."""
    games = sum(e["games"] for e in row["career"])
    if not games:
        return 0, None, None
    winrate = sum(e["games"] * e["winrate"] for e in row["career"]) / games
    kda = sum(e["games"] * e["kda"] for e in row["career"]) / games
    return games, winrate, kda


def career_scores(rows: list[dict]) -> dict[str, float]:
    """How good each career has been, as a z-score among players of the same role in every league:
    a win rate that held up over many games (pulled towards 50% for short careers), a KDA above the
    role's, and a long career. Win rates are zero-sum inside each league, so this does not favour
    one league over another."""
    by_role: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_role[row["role"]].append(row)
    scores: dict[str, float] = {}
    for members in by_role.values():
        careers = [_career(m) for m in members]
        games = [g for g, _, _ in careers]
        winrate = [None if w is None else 50 + (w - 50) * g / (g + CAREER_SHRINK) for g, w, _ in careers]
        z_win = _zscores(winrate, games, CAREER_MIN)
        z_kda = _zscores([k for _, _, k in careers], games, CAREER_MIN)
        z_long = _zscores([math.log1p(g) for g in games], games, CAREER_MIN)
        raw = [0.6 * w + 0.2 * k + 0.2 * n for w, k, n in zip(z_win, z_kda, z_long)]
        for m, value in zip(members, _standardise(raw, games, CAREER_MIN)):
            scores[m["id"]] = value
    return scores


def international_scores(rows: list[dict]) -> dict[str, float]:
    """The international record since 2024, as a z-score among players of the same role: being at
    First Stand, MSI or Worlds counts (up to INTERNATIONAL_FULL games), and the win rate there counts
    more, held back towards 50% until a player has a good number of games. Players who never made
    it have no record; inside a league with no international teams that changes nothing."""
    by_role: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_role[row["role"]].append(row)
    scores: dict[str, float] = {}
    for members in by_role.values():
        raw = []
        for m in members:
            games = wins = 0.0
            for event in m["international"]:
                weight = INTERNATIONAL_YEARS.get(event["year"], 0.5)
                played = event.get("games") or 0
                games += weight * played
                wins += weight * played * (event.get("winrate") or 0) / 100
            if games == 0:
                raw.append(0.0)
                continue
            shrunk = 50 + (100 * wins / games - 50) * games / (games + INTERNATIONAL_SHRINK)
            raw.append(min(1.5, math.log1p(games) / math.log1p(INTERNATIONAL_FULL)) + (shrunk - 50) / 10)
        for m, value in zip(members, _standardise(raw, [1] * len(members), 0)):
            scores[m["id"]] = value
    return scores


def _blend(form: list[float], career: list[float], international: list[float], team: list[float],
           sample: list[int], reference: list[float]) -> list[float]:
    """Mix form, career, the international record and team into one z-score, then give it the mean
    and spread of `reference` (this year's form on its own) inside the group, so the blend reorders
    players but keeps the league's average and how far apart its players are."""
    mixed = [FORM_WEIGHT * f + CAREER_WEIGHT * c + INTERNATIONAL_WEIGHT * i + TEAM_WEIGHT * t
             for f, c, i, t in zip(form, career, international, team)]
    known = [i for i, g in enumerate(sample) if g >= MIN_GAMES]
    if len(known) < 3:
        return mixed
    ref_mu, ref_sd = mean(reference[i] for i in known), pstdev([reference[i] for i in known]) or 1.0
    mix_mu, mix_sd = mean(mixed[i] for i in known), pstdev([mixed[i] for i in known]) or 1.0
    return [ref_mu + (v - mix_mu) / mix_sd * ref_sd for v in mixed]


def _season(role: str, lines: list[dict]) -> tuple[list[int], dict[str, list[float]], dict[str, list[float]], list[float]]:
    """One season's read of a (league, role) group: games, stat z-scores, raw attributes and the
    overall performance, each standardised inside the group."""
    sample = [int(line.get("games") or 0) for line in lines]
    metrics = [_metrics(line) for line in lines]
    stat_names = metrics[0].keys()
    z_by_stat = {st: _zscores([mt[st] for mt in metrics], sample) for st in stat_names}
    raw_attr: dict[str, list[float]] = {}
    for attr, recipe in (_RECIPES[role] | _SHARED).items():
        combos = [_combine({st: z_by_stat[st][i] for st in stat_names}, recipe) for i in range(len(lines))]
        raw_attr[attr] = _standardise(combos, sample)
    weights = ROLE_WEIGHTS[role]
    perf = [sum(raw_attr[a][i] * w for a, w in weights.items() if a in raw_attr) for i in range(len(lines))]
    return sample, z_by_stat, raw_attr, _standardise(perf, sample)


def _across(values: list[list[float]], samples: list[list[int]], weights: list[float], i: int) -> float:
    """Player i's z-score over the seasons they played, each shrunk for a small sample and weighted
    by how recent it is. Seasons they did not play do not count."""
    total = weight_sum = 0.0
    for season_values, sample, weight in zip(values, samples, weights):
        games = sample[i]
        if games == 0:
            continue
        z = max(-Z_CLIP, min(Z_CLIP, season_values[i]))
        total += weight * z * games / (games + SHRINK_GAMES)
        weight_sum += weight
    return total / weight_sum if weight_sum else 0.0


def _experience(row: dict) -> int:
    """Career games, or an estimate from this year's games when the career page is missing, so
    a veteran without career data is not mistaken for a rookie."""
    career = sum(e["games"] for e in row["career"])
    if career:
        return career
    season = int(row["stats"].get("games") or row["games"] or 0)
    return min(900, int(season * 3.5))


def rate_players(rows: list[dict], leagues: dict[str, League], champion_by_key: dict[str, str]) -> list[Player]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["league"], row["role"])].append(row)

    experience = {r["id"]: _experience(r) for r in rows}
    careers = career_scores(rows)
    internationals = international_scores(rows)
    log_exp = {pid: math.log1p(n) for pid, n in experience.items()}
    exp_mu, exp_sd = mean(log_exp.values()), pstdev(log_exp.values()) or 1.0

    players: list[Player] = []
    for (league_id, role), members in groups.items():
        league = leagues[league_id]
        # 2026 first, then the earlier seasons of the same players.
        seasons = [_season(role, [m["stats"] for m in members])]
        seasons += [_season(role, [m["history"].get(year) or {} for m in members]) for year in HISTORY_YEARS]
        season_weights = [SEASON_WEIGHTS[year] for year in ("2026", *HISTORY_YEARS)]
        samples = [season[0] for season in seasons]
        sample, z_by_stat, raw_attr, _ = seasons[0]
        played = [any(sm[i] for sm in samples) for i in range(len(members))]
        composure = [(log_exp[m["id"]] - exp_mu) / exp_sd * 0.8 + 0.2 * z_by_stat["winrate"][i]
                     for i, m in enumerate(members)]

        # Form over three seasons; team is this year's; the career is shrunk on its own terms.
        form = []
        team = []
        this_year = []
        for i, games in enumerate(sample):
            shrink = games / (games + SHRINK_GAMES)
            if not played[i]:
                form.append(-0.5)  # on a roster but never played: a sub for a reason
            else:
                form.append(_across([season[3] for season in seasons], samples, season_weights, i))
            team.append(max(-Z_CLIP, min(Z_CLIP, z_by_stat["winrate"][i])) * shrink)
            this_year.append(-0.5 if games == 0 else max(-Z_CLIP, min(Z_CLIP, seasons[0][3][i])) * shrink)
        career = [max(-Z_CLIP, min(Z_CLIP, careers[m["id"]])) for m in members]
        international = [max(-Z_CLIP, min(Z_CLIP, internationals[m["id"]])) for m in members]
        blended = _blend(form, career, international, team, sample, this_year)

        base_attr = attribute_base(league.strength)
        base_ovr = overall_base(league.strength)
        for i, m in enumerate(members):
            games = sample[i]
            shrink = games / (games + SHRINK_GAMES)
            pool = _pool(m, champion_by_key)
            attributes: dict[str, int] = {}
            for attr in ATTRIBUTES:
                if attr == "champion_pool":
                    deep = sum(1 for rec in pool if rec.games >= 5)
                    value = 3 + deep * 0.9 + (league.strength - 75) * 0.08
                elif attr == "composure":
                    value = base_attr + ATTR_SPREAD * composure[i]
                else:
                    z = _across([season[2][attr] for season in seasons], samples, season_weights, i)
                    value = base_attr + ATTR_SPREAD * z
                attributes[attr] = int(max(1, min(20, round(value))))

            # Big-match experience: a long career is worth up to three points on top.
            pedigree = min(3.0, max(0.0, (experience[m["id"]] - 300) / 300))
            overall = int(max(30, min(99, round(base_ovr + OVERALL_SPREAD * blended[i] + pedigree))))

            seed = m["id"]
            exp_games = experience[m["id"]]
            if exp_games < 100:
                headroom = 8 + 8 * _hash01(seed, "pot")
            elif exp_games < 300:
                headroom = 4 + 5 * _hash01(seed, "pot")
            elif exp_games < 600:
                headroom = 1 + 4 * _hash01(seed, "pot")
            else:
                headroom = 2 * _hash01(seed, "pot")
            potential = int(min(99, round(overall + headroom)))

            aggr_raw = 0.4 * z_by_stat["fb"][i] + 0.4 * z_by_stat["solo"][i] + 0.2 * z_by_stat["kills"][i]
            aggression = int(max(1, min(20, round(10 + 3.5 * aggr_raw * max(shrink, 0.4)))))
            shotcaller = 2 if role in ("JNG", "MID", "SUP") else 0
            leadership = int(max(1, min(20, round(5 + 9 * _hash01(seed, "lead") + shotcaller
                                                  + min(4, exp_games / 250)))))
            reputation = int(max(1, min(99, round((overall - 40) * 1.1 + min(25, exp_games / 40)
                                                  + (10 if league.tier == 1 else 0)))))
            mastery = {rec.champion: mastery_from_games(rec.games) for rec in pool}
            # Career pools need six games for a signature, a lone 2026 split needs three.
            signatures = tuple(rec.champion for rec in pool[:3] if rec.games >= (6 if m["career"] else 3))

            players.append(Player(
                id=m["id"],
                name=m["name"],
                role=role,  # type: ignore[arg-type]
                country=m["country"],
                league=league_id,
                team=m["team"],
                games=m["games"],
                experience=exp_games,
                stats=m["stats"],
                attributes=attributes,
                overall=overall,
                potential=potential,
                aggression=aggression,
                leadership=leadership,
                reputation=reputation,
                salary=asking_salary(overall, reputation, league.region),
                pool=pool,
                mastery=mastery,
                signatures=signatures,
            ))
    return players
