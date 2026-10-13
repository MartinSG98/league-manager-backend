"""Head coaches on the move: AI clubs sack their coach when a season goes badly, and clubs looking
for a coach approach the manager or answer their application.

An AI club's coach (TeamState.coach) stands in for its head coach; at the manager's own club the
manager is the head coach and the same seat holds their assistant.

Expectations. A club is expected to finish where its reputation ranked it in its league when the
season started (TeamState.expected), and, when that rank is within its region's Worlds slots, to
reach Worlds.

- After the season (the day after the Worlds final) every AI club weighs its season. Each split
  allows a place of grace and every place lower counts a point; missing Worlds when expected counts
  three more. The chance to sack the coach is 4 percent a point, plus 35 when Worlds was missed,
  at most 85. A coach in the job for less than four months gets a third of that.
- After each split, a club expected in its league's top three that finishes four or more places
  lower sacks its coach 30 percent of the time, with the same discount for a new coach.
- A coach whose contract ran out and was not renewed also leaves a vacancy.

Vacancies stay open two weeks. A club approaches the manager when it is within their reach (at
most STAR_REACH stars above their own reputation) and at least about as big as their club, 40
percent of the time plus 10 for every star of room. The manager can apply to any vacancy: out of
reach is a polite no, in reach the club offers the job 35 percent of the time plus 25 for every star
of room, and otherwise appoints someone else at once. An offer is open a week. Taking it moves the
manager to the new club, with a new board and the club's analyst; the board hires an assistant
coach for the empty seat. When a vacancy closes the club appoints the best free coach it can afford."""

from datetime import timedelta

from app.game import board, calendar, reputation, transfers
from app.game.catalog import Catalog
from app.game.errors import IllegalAction
from app.game.rng import Rng
from app.game.state import Career, Competition, InboxMessage, Vacancy

GRACE_PLACES = 1  # places below expectation a split forgives
SEASON_POINT = 0.04  # sack chance per point of a bad season
MISSED_WORLDS = 3  # points for missing Worlds when expected there
MISSED_WORLDS_CHANCE = 0.35
MAX_SACK = 0.85
NEW_COACH_DAYS = 120
NEW_COACH_FACTOR = 1 / 3
SPLIT_FAVOURITE = 3  # expected this high or better ...
SPLIT_DROP = 4  # ... and finishing this many places lower
SPLIT_SACK = 0.30
VACANCY_DAYS = 14
OFFER_DAYS = 7
SIZE_GAP = 5.0  # reputation a club approaching the manager can be below their own club
NOTABLE = 70  # reputation from which a club's coaching news reaches every league


# ---------- expectations ----------


def set_expectations(cat: Catalog, career: Career) -> None:
    """Rank every league by reputation at the start of a season."""
    for league in {t.league for t in career.teams.values()}:
        for rank, team_id in enumerate(_by_reputation(cat, career, league), start=1):
            career.teams[team_id].expected = rank


def _by_reputation(cat: Catalog, career: Career, league: str) -> list[str]:
    teams = [t for t, s in career.teams.items() if s.league == league]
    return sorted(teams, key=lambda t: -reputation.team_reputation(cat, career, t))


def expected(cat: Catalog, career: Career, team_id: str) -> int:
    team = career.teams[team_id]
    return team.expected or _by_reputation(cat, career, team.league).index(team_id) + 1


def _worlds_slots(cat: Catalog, team_id: str) -> int:
    worlds = next(e for e in calendar.INTERNATIONALS if e.id == "WORLDS")
    return worlds.slots.get(cat.teams[team_id].region, 0)


def season_points(cat: Catalog, career: Career, team_id: str, season: int) -> tuple[int, bool]:
    """How far a club's season fell short: points, and whether it missed a Worlds it was expected at."""
    team = career.teams[team_id]
    exp = expected(cat, career, team_id)
    points = 0
    for split in (1, 2, 3):
        comp = career.competitions.get(f"{season}-{team.league}-{split}")
        if comp and team_id in comp.placements:
            points += max(0, comp.placements.index(team_id) + 1 - exp - GRACE_PLACES)
    worlds = career.competitions.get(f"{season}-WORLDS")
    missed = exp <= _worlds_slots(cat, team_id) and (worlds is None or team_id not in worlds.entrants)
    return points + (MISSED_WORLDS if missed else 0), missed


def sack_chance(points: int, missed_worlds: bool, tenure_days: int | None) -> float:
    chance = min(MAX_SACK, SEASON_POINT * points + (MISSED_WORLDS_CHANCE if missed_worlds else 0.0))
    if tenure_days is not None and tenure_days < NEW_COACH_DAYS:
        chance *= NEW_COACH_FACTOR
    return chance


def _tenure(career: Career, team_id: str) -> int | None:
    since = career.teams[team_id].coach_since
    return (career.day - since).days if since else None


# ---------- sackings ----------


def season_review(cat: Catalog, career: Career, rng: Rng, season: int) -> None:
    """The day after the Worlds final: AI clubs weigh their season, and empty seats become vacancies."""
    for team_id, team in career.teams.items():
        if team_id == career.team or team.coach is None:
            continue
        points, missed = season_points(cat, career, team_id, season)
        if points and rng.chance(sack_chance(points, missed, _tenure(career, team_id))):
            exp = expected(cat, career, team_id)
            reason = (f"Expected to reach Worlds, {cat.teams[team_id].name} missed it" if missed
                      else f"Expected to finish {_ordinal(exp)} in the {cat.leagues[team.league].name}, "
                           f"{cat.teams[team_id].name} fell short all season")
            sack(cat, career, team_id, reason, rng)
    for team_id, team in career.teams.items():
        if team_id != career.team and team.coach is None and _vacancy(career, team_id) is None:
            open_vacancy(cat, career, team_id, rng)


def split_review(cat: Catalog, career: Career, comp: Competition, rng: Rng) -> None:
    """After a split: a favourite that collapsed may not wait for the end of the season."""
    for place, team_id in enumerate(comp.placements, start=1):
        team = career.teams.get(team_id)
        if team is None or team_id == career.team or team.coach is None:
            continue
        exp = expected(cat, career, team_id)
        if exp > SPLIT_FAVOURITE or place - exp < SPLIT_DROP:
            continue
        tenure = _tenure(career, team_id)
        chance = SPLIT_SACK * (NEW_COACH_FACTOR if tenure is not None and tenure < NEW_COACH_DAYS else 1.0)
        if rng.chance(chance):
            sack(cat, career, team_id, f"Expected to challenge for the title, {cat.teams[team_id].name} finished "
                 f"{_ordinal(place)} in the {comp.name}", rng)


def sack(cat: Catalog, career: Career, team_id: str, reason: str, rng: Rng) -> None:
    team = career.teams[team_id]
    sid = team.coach
    if sid is None:
        return
    career.staff[sid].team = None
    career.staff[sid].contract = None
    team.coach = None
    team.coach_since = None
    name = cat.teams[team_id].name
    if _notable(cat, career, team_id):
        _news(career, f"{name} part ways with {cat.staff[sid].name}",
              f"{reason}. {name} are looking for a new head coach.")
    open_vacancy(cat, career, team_id, rng)


# ---------- vacancies and offers ----------


def _vacancy(career: Career, team_id: str) -> Vacancy | None:
    return next((v for v in career.vacancies if v.team == team_id), None)


def reach(career: Career) -> float:
    return reputation.stars(career.manager_reputation) + reputation.STAR_REACH


def in_reach(cat: Catalog, career: Career, team_id: str) -> bool:
    return reputation.stars(reputation.team_reputation(cat, career, team_id)) <= reach(career)


def open_vacancy(cat: Catalog, career: Career, team_id: str, rng: Rng) -> Vacancy:
    vacancy = Vacancy(team=team_id, opened=career.day, closes=career.day + timedelta(days=VACANCY_DAYS))
    career.vacancies.append(vacancy)
    if career.board.sacked or career.phase == "draft":
        return vacancy
    level = reputation.team_reputation(cat, career, team_id)
    own = reputation.team_reputation(cat, career, career.team)
    room = reach(career) - reputation.stars(level)
    if room >= 0 and level >= own - SIZE_GAP and rng.chance(min(0.8, 0.4 + 0.1 * room)):
        _offer(cat, career, vacancy, approached=True)
    return vacancy


def _offer(cat: Catalog, career: Career, vacancy: Vacancy, approached: bool) -> None:
    vacancy.offer_until = career.day + timedelta(days=OFFER_DAYS)
    team = cat.teams[vacancy.team]
    stars = reputation.stars(reputation.team_reputation(cat, career, vacancy.team))
    opening = (f"{team.name} ({stars:g} stars, {cat.leagues[team.league].name}) are looking for a head coach and "
               "want you." if approached else f"{team.name} were impressed by your application and offer you the job.")
    _board(career, f"Job offer: {team.name}",
           f"{opening} The offer is open until {vacancy.offer_until:%d %B}. Take it or turn it down on the Club "
           "screen. Taking it means leaving your club: your bids and talks end there.")


def apply(cat: Catalog, career: Career, team_id: str, rng: Rng) -> None:
    vacancy = _vacancy(career, team_id)
    if vacancy is None:
        raise IllegalAction("That club is not looking for a head coach")
    if vacancy.offer_until is not None:
        raise IllegalAction("They have already offered you the job")
    if vacancy.applied or vacancy.declined:
        raise IllegalAction("You have already had your chance with that club")
    if career.phase == "draft":
        raise IllegalAction("Not before the draft is over")
    vacancy.applied = True
    name = cat.teams[team_id].name
    room = reach(career) - reputation.stars(reputation.team_reputation(cat, career, team_id))
    if room < 0:
        _board(career, f"{name} turn you down", f"{name} want a head coach with a bigger name.")
    elif rng.chance(min(0.95, 0.35 + 0.25 * room)):
        _offer(cat, career, vacancy, approached=False)
    else:
        _board(career, f"{name} turn you down", f"{name} thank you for your interest and appoint someone else.")
        fill(cat, career, vacancy)


def decline(cat: Catalog, career: Career, team_id: str) -> None:
    vacancy = _vacancy(career, team_id)
    if vacancy is None or vacancy.offer_until is None:
        raise IllegalAction("That club has not offered you a job")
    vacancy.offer_until = None
    vacancy.declined = True


def offered(career: Career, team_id: str) -> bool:
    vacancy = _vacancy(career, team_id)
    return vacancy is not None and vacancy.offer_until is not None and career.day <= vacancy.offer_until


def take(cat: Catalog, career: Career, team_id: str) -> None:
    """Leave the manager's club for one that offered them the job."""
    if not offered(career, team_id):
        raise IllegalAction("That club has not offered you a job")
    if career.live is not None:
        raise IllegalAction("Not during a match")
    old = career.team
    for offer in career.offers:
        if old in (offer.buyer, offer.seller) and offer.status in ("open", "agreed"):
            offer.status = "withdrawn"
            offer.note = "The manager left the club"
    for talk in career.conversations:
        talk.resolved = True
    career.negotiations = {}
    career.job_offers = []
    career.teams[old].listed = []
    career.vacancies = [v for v in career.vacancies if v.team != team_id]
    team = cat.teams[team_id]
    career.team, career.region, career.league = team_id, team.region, team.league
    new = career.teams[team_id]
    new.budget_moved = 0
    transfers._hire_staff(cat, career, new, "coach")  # the manager's assistant
    season = career.season + 1 if career.phase == "offseason" else career.season
    board.start_job(cat, career, season)
    stars = reputation.stars(reputation.team_reputation(cat, career, team_id))
    _board(career, f"Welcome to {team.name}",
           f"You leave {cat.teams[old].name} to become head coach of {team.name} ({stars:g} stars). The board wants "
           f"to meet you about its objectives for {season}.")
    _news(career, f"{team.tag} appoint {career.manager}",
          f"{team.name} hire {career.manager} from {cat.teams[old].name} as their new head coach.")


def fill(cat: Catalog, career: Career, vacancy: Vacancy) -> None:
    """The club appoints the best free coach it can afford."""
    career.vacancies = [v for v in career.vacancies if v is not vacancy]
    team = career.teams[vacancy.team]
    if team.coach is None:
        transfers._hire_staff(cat, career, team, "coach")
    if team.coach and _notable(cat, career, vacancy.team):
        _news(career, f"{cat.teams[vacancy.team].tag} appoint {cat.staff[team.coach].name}",
              f"{cat.teams[vacancy.team].name} name {cat.staff[team.coach].name} their new head coach.")


def daily(cat: Catalog, career: Career) -> None:
    for vacancy in list(career.vacancies):
        if vacancy.offer_until is not None and career.day > vacancy.offer_until:
            vacancy.offer_until = None
            vacancy.declined = True
            _board(career, f"The offer from {cat.teams[vacancy.team].name} has lapsed",
                   f"{cat.teams[vacancy.team].name} have stopped waiting for your answer.")
        if career.day >= vacancy.closes and vacancy.offer_until is None:
            fill(cat, career, vacancy)


# ---------- messages ----------


def _notable(cat: Catalog, career: Career, team_id: str) -> bool:
    return (career.teams[team_id].league == career.league
            or reputation.team_reputation(cat, career, team_id) >= NOTABLE)


def _news(career: Career, subject: str, body: str) -> None:
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind="news", subject=subject, body=body))
    career.next_message += 1


def _board(career: Career, subject: str, body: str) -> None:
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind="board", subject=subject, body=body))
    career.next_message += 1


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def view(cat: Catalog, career: Career) -> list[dict]:
    from app.game.views import team_ref

    rows = []
    for v in sorted(career.vacancies, key=lambda v: v.closes):
        if v.team == career.team:
            continue
        level = reputation.team_reputation(cat, career, v.team)
        rows.append({
            "team": team_ref(cat, v.team), "stars": reputation.stars(level),
            "league_name": cat.leagues[cat.teams[v.team].league].name, "opened": v.opened.isoformat(),
            "closes": v.closes.isoformat(), "offer_until": v.offer_until.isoformat() if v.offer_until else None,
            "applied": v.applied, "declined": v.declined, "in_reach": in_reach(cat, career, v.team),
        })
    return rows
