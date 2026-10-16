"""Players and lineups as they stand right now in a career: catalog ratings plus growth,
champion mastery plus what was learned, and how well a starting five works together."""

from datetime import date
from itertools import combinations

from app.game.catalog import ROLES, Catalog, Player
from app.game.ratings import ATTRIBUTES, ROLE_WEIGHTS
from app.game.rng import fnv1a
from app.game.state import Career, TeamState

DATA_SEASON = 2026  # the season the catalog's career games run up to
GAMES_A_YEAR = 90
COUNTED_GAMES = 8 * GAMES_A_YEAR  # games past eight years' worth add no age: the busiest teams play far more
DEBUT_AGE = 18

# ---------- ratings ----------


def attributes(cat: Catalog, career: Career, pid: str) -> dict[str, int]:
    base = cat.players[pid].attributes
    growth = career.players[pid].growth
    return {a: int(max(1, min(20, round(base[a] + growth.get(a, 0.0))))) for a in ATTRIBUTES}


def career_games(cat: Catalog, career: Career, pid: str) -> int:
    """Career games: those before the game started, the seasons played in it and this one so far."""
    state = career.players[pid]
    return cat.players[pid].experience + state.played + state.season.games


def age(cat: Catalog, career: Career, pid: str) -> float:
    """How old a player is at the end of the current season. The real age where Liquipedia has a
    birth date. Otherwise a stand-in: a debut at about 18 and some 90 games a year before the game
    started, counting no more than eight years of games, then a year for every season played in it,
    give or take two years. A rookie starts at 18."""
    player = cat.players[pid]
    if player.born:
        year, month, day = (int(x) for x in (player.born.split("-") + ["7", "1"])[:3])
        return (date(career.season, 12, 31) - date(year, month, day)).days / 365.25
    debut = DATA_SEASON
    if pid.startswith("r"):  # a rookie
        debut = next((r.season for r in career.rookies if r.id == pid), DATA_SEASON)
    jitter = (fnv1a(f"{pid}|age") / 0xFFFFFFFF - 0.5) * 4
    games = min(player.experience, COUNTED_GAMES)
    return max(17.0, DEBUT_AGE + games / GAMES_A_YEAR + (career.season - debut) + jitter)


def overall(cat: Catalog, career: Career, pid: str) -> int:
    player = cat.players[pid]
    growth = career.players[pid].growth
    if not growth:
        return player.overall
    shift = sum(growth.get(a, 0.0) * w for a, w in ROLE_WEIGHTS[player.role].items())
    return int(max(30, min(99, round(player.overall + 3.3 * shift))))


def mastery(cat: Catalog, career: Career, pid: str, champion: str) -> int:
    known = cat.players[pid].mastery.get(champion, 0)
    return min(100, known + career.players[pid].learned.get(champion, 0))


def payroll(career: Career, team: TeamState, season: int | None = None) -> int:
    """Players and staff under contract, or only the contracts that still run in `season`."""

    def counts(contract) -> bool:
        return contract is not None and (season is None or contract.until >= season)

    players = sum(career.players[pid].contract.salary for pid in team.roster if counts(career.players[pid].contract))
    staff = sum(career.staff[sid].contract.salary for sid in (team.coach, team.analyst)
                if sid and sid in career.staff and counts(career.staff[sid].contract))
    return players + staff


# ---------- languages ----------

_NATIVE = {
    "KR": "ko", "CN": "zh", "TW": "zh", "HK": "zh", "MO": "zh", "VN": "vi", "JP": "ja", "TH": "th", "ID": "id",
    "MY": "ms", "PH": "tl", "BR": "pt", "PT": "pt", "ES": "es", "MX": "es", "AR": "es", "CL": "es", "PE": "es",
    "CO": "es", "UY": "es", "VE": "es", "EC": "es", "BO": "es", "PY": "es", "CR": "es", "GT": "es", "DO": "es",
    "PA": "es", "SV": "es", "HN": "es", "NI": "es", "PR": "es", "FR": "fr", "BE": "fr", "LU": "fr", "DE": "de",
    "AT": "de", "CH": "de", "DK": "da", "SE": "sv", "NO": "no", "FI": "fi", "IS": "is", "PL": "pl", "CZ": "cs",
    "SK": "sk", "TR": "tr", "GR": "el", "CY": "el", "IT": "it", "NL": "nl", "UA": "uk", "RU": "ru", "BY": "ru",
    "KZ": "ru", "LT": "lt", "LV": "lv", "EE": "et", "RO": "ro", "MD": "ro", "BG": "bg", "RS": "sr", "ME": "sr",
    "HR": "hr", "SI": "sl", "BA": "bs", "MK": "mk", "AL": "sq", "XK": "sq", "HU": "hu", "IL": "he", "SA": "ar",
    "AE": "ar", "EG": "ar", "MA": "ar", "DZ": "ar", "TN": "ar", "JO": "ar", "KW": "ar", "QA": "ar", "LB": "ar",
    "BH": "ar", "OM": "ar", "IQ": "ar", "IR": "fa", "AM": "hy", "GE": "ka", "AZ": "az",
}
_ENGLISH_HOME = {"US", "CA", "GB", "UK", "IE", "AU", "NZ", "SG", "IN", "ZA", "MT"}
# Players from these regions grow up with an esports scene that plays in its own language.
_LOCAL_SCENES = {"KR": {"KR"}, "CN": {"CN"}, "BR": {"BR"}, "APAC": {"TW", "HK", "MO", "VN", "JP", "TH", "PH"}}


def languages(cat: Catalog, player: Player) -> set[str]:
    country = (player.country or "").upper()
    spoken = {"en"} if country in _ENGLISH_HOME else set()
    native = _NATIVE.get(country)
    if native:
        spoken.add(native)
    region = cat.leagues[player.league].region
    local = _LOCAL_SCENES.get(region)
    # Europe and North America play in English, and so does anyone who moved abroad to play.
    if local is None or country not in local:
        spoken.add("en")
    return spoken or {"en"}


# ---------- chemistry ----------

PAIR_WEIGHT = {
    frozenset(("BOT", "SUP")): 2.0,
    frozenset(("JNG", "MID")): 1.5,
    frozenset(("JNG", "SUP")): 1.2,
    frozenset(("MID", "SUP")): 1.0,
    frozenset(("TOP", "JNG")): 1.0,
}


def _pair_weight(a: str, b: str) -> float:
    return PAIR_WEIGHT.get(frozenset((a, b)), 0.8)


def _were_teammates(a, b) -> bool:
    """Both came from the same 2026 team. Rookies straight from solo queue have no team ("")."""
    return bool(a.team) and a.team == b.team


def chemistry(cat: Catalog, career: Career, team: TeamState, lineup: dict[str, str] | None = None) -> tuple[float, list[str]]:
    """Team-wide modifier on top of individual ratings, about -5..+4, with the reasons behind it."""
    lineup = lineup or team.lineup
    starters = [(role, lineup[role]) for role in ROLES if role in lineup]
    if len(starters) < 2:
        return 0.0, []
    reasons: list[str] = []
    total_w = talk_w = known_w = 0.0
    silent: set[str] = set()
    for (ra, a), (rb, b) in combinations(starters, 2):
        w = _pair_weight(ra, rb)
        total_w += w
        pa, pb = cat.players[a], cat.players[b]
        if languages(cat, pa) & languages(cat, pb):
            talk_w += w
        else:
            silent.update((pa.name, pb.name))
        # Teammates from 2026 already know each other; new pairs get there over twenty games.
        shared = 20 if _were_teammates(pa, pb) else min(20, team.together.get(_pair_key(a, b), 0))
        known_w += w * shared / 20
    communication = talk_w / total_w
    familiarity = known_w / total_w
    score = (communication - 1) * 4 + familiarity * 3
    if communication < 0.999:
        reasons.append(f"Language barrier between {', '.join(sorted(silent))} ({communication:.0%} of pairs can talk)")
    else:
        reasons.append("Everyone shares a language")
    bot, sup = lineup.get("BOT"), lineup.get("SUP")
    if bot and sup and _were_teammates(cat.players[bot], cat.players[sup]):
        reasons.append(f"{cat.players[bot].name} and {cat.players[sup].name} were a bot lane in 2026")
    if familiarity >= 0.6:
        reasons.append(f"Most of the lineup has played together ({familiarity:.0%})")
    elif familiarity <= 0.2:
        reasons.append("A new lineup that is still learning each other")
    leader = max((cat.players[pid] for _, pid in starters), key=lambda p: p.leadership)
    if leader.leadership >= 15:
        score += 1
        reasons.append(f"{leader.name} leads the comms (leadership {leader.leadership})")
    elif leader.leadership < 9:
        score -= 1
        reasons.append("Nobody takes charge of the shotcalling")
    return round(score, 2), reasons


def _pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


def record_games_together(team: TeamState, lineup: dict[str, str], weight: float = 1.0) -> None:
    """Count a game started together for every pair; a motivating coach makes it count for more."""
    for a, b in combinations(sorted(lineup.values()), 2):
        key = _pair_key(a, b)
        team.together[key] = round(team.together.get(key, 0) + weight, 3)


# ---------- quick strength estimates for AI decisions and previews ----------


def lineup_strength(cat: Catalog, career: Career, team: TeamState) -> float:
    if not team.lineup:
        return 0.0
    ovr = [overall(cat, career, pid) for pid in team.lineup.values()]
    chem, _ = chemistry(cat, career, team)
    return sum(ovr) / len(ovr) + chem
