"""Career flow and the one entry point for actions.

A career starts on December 1st in the pre-season draft. Every other region drafts at once; in
the manager's league the AI teams pick one at a time as the client asks for them (draft_next), so
the manager watches the board fill up and can skip ahead to their own pick. Once that draft is done the
season is scheduled and `advance` moves the calendar a day at a time, playing every AI series
on the way, until the manager's team has a match (or something they should read happens)."""

from datetime import date, timedelta

from app.game import calendar, contracts, draft, matchday, offseason, patches, roster
from app.game.catalog import Catalog
from app.game.errors import IllegalAction
from app.game.matchday import Outcome
from app.game.rng import Rng
from app.game.state import (
    AcceptCounterAction, Action, AdvanceAction, AutoSelectAction, BanAction, Career, DraftAutoAction, DraftNextAction,
    DraftPassAction, DraftPickAction, DraftSimAction, InboxMessage, NextGameAction, NextSeasonAction, OfferAction,
    OpponentTurnAction, PickAction, PlayerState, PlayGameAction, ReadMessageAction, ReleaseAction, SetLineupAction,
    SetTacticsAction, SimSeriesAction, StartDraftAction,
)

FIRST_SEASON = 2027
STARTING_PATCH = "26.20"
MAX_DAYS_PER_ADVANCE = 120


def message(career: Career, kind: str, subject: str, body: str) -> None:
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind=kind, subject=subject, body=body))  # type: ignore[arg-type]
    career.next_message += 1


# ---------- a new career ----------


def new_career(cat: Catalog, manager: str, team_id: str, seed: int) -> Career:
    team = cat.teams.get(team_id)
    if team is None or team.tier != 1:
        raise IllegalAction("Pick a tier-one team")
    season = FIRST_SEASON
    career = Career(
        rs=seed & 0xFFFFFFFF,
        manager=manager.strip() or "Manager",
        team=team_id,
        region=team.region,
        league=team.league,
        season=season,
        day=calendar.season_start(season),
        players={pid: PlayerState(id=pid) for pid in cat.players},
        teams={},
        meta=patches.starting_meta(cat, STARTING_PATCH),
    )
    rng = Rng(career)
    draft.setup(cat, career)
    for league, d in career.drafts.items():
        if league != career.league:
            draft.run_until(cat, career, d, None, rng)
            draft.finish(cat, career, d)

    franchise = cat.players[career.teams[team_id].franchise or ""] if career.teams[team_id].franchise else None
    league = cat.leagues[team.league]
    d = career.drafts[team.league]
    position = d.sequence.index(team_id) + 1
    message(career, "board", f"Welcome to {team.name}",
            f"The board has handed you the keys for the {season} season.\n"
            + (f"{franchise.name} stays as the face of the franchise; everyone else is in the draft pool.\n"
               if franchise else "")
            + f"You pick {_ordinal(position)} in the first round of the {league.name} draft, "
              f"with a budget of {career.teams[team_id].budget}k for the season.")
    return career


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _maybe_finish_draft(cat: Catalog, career: Career, rng: Rng) -> None:
    d = career.drafts.get(career.league)
    if d is None or not d.done or career.phase != "draft":
        return
    draft.finish(cat, career, d)
    career.inbox.append(draft.summary(cat, career, d, career.team))
    start_season(cat, career)


def start_season(cat: Catalog, career: Career) -> None:
    career.phase = "season"
    calendar.create_season(cat, career)
    career.meta.next_patch = patches.first_patch_day(career.season)
    for team in career.teams.values():
        team.cash = max(team.cash, 0)
    first = min((m for m in career.matches.values() if career.team in (m.home, m.away)), key=lambda m: m.day)
    message(career, "news", f"The {career.season} season is scheduled",
            f"Your first match is on {first.day:%A %d %B} against {cat.teams[first.away if first.home == career.team else first.home].name}.")


# ---------- the calendar ----------


def _daily(cat: Catalog, career: Career, rng: Rng) -> None:
    meta = career.meta
    if meta.next_patch and career.day >= meta.next_patch:
        patches.release_patch(cat, career, rng)
    for state in career.players.values():
        if state.fatigue:
            state.fatigue = max(0, state.fatigue - 4)
    if career.day.weekday() == 0:
        _weekly(cat, career, rng)


def _weekly(cat: Catalog, career: Career, rng: Rng) -> None:
    for team in career.teams.values():
        wages = roster.payroll(career, team) / 52
        sponsors = cat.teams[team.id].prestige * 22 / 52
        team.cash = int(team.cash - wages + sponsors)
    for pid, state in career.players.items():
        if state.team is None:
            continue
        state.morale += (70 - state.morale) // 8
        player = cat.players[pid]
        gap = player.potential - roster.overall(cat, career, pid)
        if gap > 0 and rng.chance(min(0.6, 0.08 * gap)):
            attr = rng.pick(list(player.attributes)) or "mechanics"
            state.growth[attr] = round(state.growth.get(attr, 0.0) + 0.35, 2)


def _todays_matches(career: Career) -> list:
    return sorted((m for m in career.matches.values() if m.day == career.day and m.winner is None), key=lambda m: m.id)


def advance(cat: Catalog, career: Career, rng: Rng) -> None:
    if career.phase == "draft":
        raise IllegalAction("Finish the draft first")
    if career.live is not None:
        raise IllegalAction("Your match is waiting")
    if calendar.season_over(career):
        raise IllegalAction("The season is over")
    inbox_before = len(career.inbox)
    for _ in range(MAX_DAYS_PER_ADVANCE):
        career.day += timedelta(days=1)
        _daily(cat, career, rng)
        mine = None
        for match in _todays_matches(career):
            if match.home is None or match.away is None:
                continue
            if career.team in (match.home, match.away):
                mine = match
                continue
            matchday.play_ai_match(cat, career, match, rng)
        calendar.update(cat, career, rng)
        if mine is not None:
            matchday.start_live(career, mine)
            return
        if calendar.season_over(career):
            _end_season(cat, career)
            return
        if _worth_stopping(career, inbox_before):
            return


def _worth_stopping(career: Career, inbox_before: int) -> bool:
    """Stop when a competition the manager cares about finished or a new one was announced."""
    for msg in career.inbox[inbox_before:]:
        if msg.kind in ("news", "board") and (" is set" in msg.subject or " win the " in msg.subject):
            return True
    return False


def _season_review(cat: Catalog, career: Career) -> str:
    lines = []
    for comp in sorted(career.competitions.values(), key=lambda c: c.start):
        if career.team in comp.placements:
            lines.append(f"{comp.name}: {_ordinal(comp.placements.index(career.team) + 1)}")
    return "\n".join(lines) or "A season to forget."


def after_series(cat: Catalog, career: Career, rng: Rng) -> None:
    """The manager's series just ended: play the rest of the day and update the competitions."""
    for match in _todays_matches(career):
        if match.home and match.away and career.team not in (match.home, match.away):
            matchday.play_ai_match(cat, career, match, rng)
    calendar.update(cat, career, rng)
    if calendar.season_over(career):
        _end_season(cat, career)


def _end_season(cat: Catalog, career: Career) -> None:
    message(career, "board", f"The {career.season} season is over", _season_review(cat, career))
    offseason.contract_warning(cat, career)
    career.phase = "offseason"


# ---------- actions ----------


def apply(cat: Catalog, career: Career, action: Action) -> Outcome:
    rng = Rng(career)
    outcome = Outcome()
    if isinstance(action, (DraftPickAction, DraftPassAction, DraftAutoAction, DraftSimAction, DraftNextAction)):
        _draft_action(cat, career, action, rng)
    elif isinstance(action, AdvanceAction):
        advance(cat, career, rng)
    elif isinstance(action, SetLineupAction):
        matchday.set_lineup(cat, career, action.lineup)
    elif isinstance(action, SetTacticsAction):
        career.teams[career.team].tactics = action.tactics
    elif isinstance(action, StartDraftAction):
        matchday.start_champ_select(cat, career, rng)
    elif isinstance(action, BanAction):
        matchday.human_ban(cat, career, action.champion, rng)
    elif isinstance(action, PickAction):
        matchday.human_pick(cat, career, action.champion, action.role, rng)
    elif isinstance(action, AutoSelectAction):
        matchday.auto_select(cat, career, rng)
    elif isinstance(action, OpponentTurnAction):
        matchday.opponent_turn(cat, career, rng, action.until_mine)
    elif isinstance(action, PlayGameAction):
        outcome.details.append(matchday.play_live_game(cat, career, rng))
    elif isinstance(action, NextGameAction):
        if matchday.next_game(cat, career):
            after_series(cat, career, rng)
    elif isinstance(action, SimSeriesAction):
        if career.live is None:
            raise IllegalAction("There is no match in progress")
        outcome.details += matchday.sim_series(cat, career, rng)
        after_series(cat, career, rng)
    elif isinstance(action, OfferAction):
        contracts.offer(cat, career, action.player, action.salary, action.years)
    elif isinstance(action, AcceptCounterAction):
        contracts.accept_counter(cat, career, action.player)
    elif isinstance(action, ReleaseAction):
        contracts.release(cat, career, action.player)
    elif isinstance(action, NextSeasonAction):
        if career.phase != "offseason":
            raise IllegalAction("The season is not over yet")
        offseason.start_next_season(cat, career, rng)
        _maybe_finish_draft(cat, career, rng)
    elif isinstance(action, ReadMessageAction):
        for msg in career.inbox:
            if action.id is None or msg.id == action.id:
                msg.read = True
    else:  # pragma: no cover - the union is exhaustive
        raise IllegalAction("Unknown action")
    return outcome


def _draft_action(cat: Catalog, career: Career, action: Action, rng: Rng) -> None:
    if career.phase != "draft":
        raise IllegalAction("The draft is over")
    d = career.drafts[career.league]
    if isinstance(action, DraftSimAction):
        while not d.done:
            draft.auto_pick(cat, career, d, rng)
    elif isinstance(action, DraftNextAction):
        # Waiting on the manager's own turn does nothing, so a client on a timer never picks for them.
        if d.on_the_clock != career.team:
            if action.until_mine:
                draft.run_until(cat, career, d, career.team, rng)
            else:
                draft.auto_pick(cat, career, d, rng)
    else:
        if d.on_the_clock != career.team:
            raise IllegalAction("It is not your pick")
        if isinstance(action, DraftPickAction):
            draft.make_pick(cat, career, d, career.team, action.player)
        elif isinstance(action, DraftPassAction):
            draft.make_pick(cat, career, d, career.team, None)
        else:
            draft.auto_pick(cat, career, d, rng)
    _maybe_finish_draft(cat, career, rng)
