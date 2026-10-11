"""Player ratings worked out from 2026 stat lines, the way Worlds Mayhem rates its players: many
stats per player, judged against the other players of the same role in the same league, then
placed on one scale by how strong that league is.

Every stat is turned into a z-score inside its (league, role) group, a handful of z-scores make
up each attribute, and each attribute is standardised again inside the group so that all of
them spread the same way. Small samples are pulled towards the league average. On the 1-20
scale an average player sits at a baseline set by league strength (LCK about 15.5, LEC 13,
an average ERL about 6); the overall rating uses the same baseline on a 30-99 scale."""

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


def _zscores(values: list[float | None], sample_games: list[int]) -> list[float]:
    """z-scores against the players with enough games; missing values sit slightly below average."""
    known = [v for v, g in zip(values, sample_games) if v is not None and g >= MIN_GAMES]
    if len(known) < 3:
        return [0.0] * len(values)
    mu, sd = mean(known), pstdev(known) or 1.0
    return [((v - mu) / sd) if v is not None else -0.3 for v in values]


def _standardise(values: list[float], weights: list[int]) -> list[float]:
    known = [v for v, g in zip(values, weights) if g >= MIN_GAMES]
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
    log_exp = {pid: math.log1p(n) for pid, n in experience.items()}
    exp_mu, exp_sd = mean(log_exp.values()), pstdev(log_exp.values()) or 1.0

    players: list[Player] = []
    for (league_id, role), members in groups.items():
        league = leagues[league_id]
        sample = [int(m["stats"].get("games") or 0) for m in members]
        metrics = [_metrics(m["stats"]) for m in members]
        stat_names = metrics[0].keys()
        z_by_stat = {s: _zscores([mt[s] for mt in metrics], sample) for s in stat_names}

        recipes = _RECIPES[role] | _SHARED
        raw_attr: dict[str, list[float]] = {}
        for attr, recipe in recipes.items():
            combos = [_combine({s: z_by_stat[s][i] for s in stat_names}, recipe) for i in range(len(members))]
            raw_attr[attr] = _standardise(combos, sample)
        raw_attr["composure"] = [(log_exp[m["id"]] - exp_mu) / exp_sd * 0.8 + 0.2 * z_by_stat["winrate"][i]
                                 for i, m in enumerate(members)]

        weights = ROLE_WEIGHTS[role]
        perf = [sum(raw_attr[a][i] * w for a, w in weights.items() if a in raw_attr) for i in range(len(members))]
        perf = _standardise(perf, sample)

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
                    value = base_attr + ATTR_SPREAD * raw_attr["composure"][i]
                else:
                    z = max(-Z_CLIP, min(Z_CLIP, raw_attr[attr][i])) * shrink
                    value = base_attr + ATTR_SPREAD * z
                attributes[attr] = int(max(1, min(20, round(value))))

            z_perf = max(-Z_CLIP, min(Z_CLIP, perf[i])) * shrink
            if games == 0:
                z_perf = -0.5  # on a roster but never played: a sub for a reason
            # Big-match experience: a long career is worth up to three points on top of this year's form.
            pedigree = min(3.0, max(0.0, (experience[m["id"]] - 300) / 300))
            overall = int(max(30, min(99, round(base_ovr + OVERALL_SPREAD * z_perf + pedigree))))

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
