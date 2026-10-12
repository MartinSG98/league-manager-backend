"""Career flow and the one entry point for actions.

A career starts on December 1st with a board meeting about the season's objectives, then the
pre-season draft. Every other region drafts at once; in the manager's league the AI teams pick
one at a time as the client asks for them (draft_next), so the manager watches the board fill up
and can skip ahead to their own pick. Once that draft is done the season is scheduled and
`advance` moves the calendar a day at a time, playing every AI series on the way, until the
manager's team has a match (or something they should read happens).

After Worlds comes the off-season: a transfer window that `advance` also moves through, stopping
when a club bids for one of the manager's players or a player wants to talk. When it closes the
next season is scheduled. There is no draft after the first one."""

from datetime import timedelta

from app.game import board, calendar, contracts, draft, matchday, offseason, patches, reputation, roster, scouting
from app.game import training, transfers
from app.game.catalog import Catalog
from app.game.errors import IllegalAction
from app.game.matchday import Outcome
from app.game.rng import Rng
from app.game.state import (
    AcceptCounterAction, AcceptJobAction, Action, AdvanceAction, AutoSelectAction, BanAction, BoardMeetingAction,
    Career, DraftAutoAction, DraftNextAction, DraftPassAction, DraftPickAction, DraftSimAction, DraftStaffAction,
    InboxMessage, NextGameAction, NextSeasonAction, OfferAction, OpponentTurnAction, PickAction, PlayerState,
    PlayGameAction, ReadMessageAction, ReleaseAction, RespondOfferAction, SetLineupAction, SetPlayAction,
    SetPlayerTrainingAction, SetTacticsAction, SetTrainingAction, SimSeriesAction, StaffState, StartDraftAction,
    TalkAction, TransferBidAction, TransferListAction, WithdrawBidAction,
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
        seed=(seed & 0xFFFFFFFF) or 1,
        manager=manager.strip() or "Manager",
        team=team_id,
        region=team.region,
        league=team.league,
        season=season,
        day=calendar.season_start(season),
        players={pid: PlayerState(id=pid) for pid in cat.players},
        teams={},
        staff={sid: StaffState(id=sid) for sid in cat.staff},
        meta=patches.starting_meta(cat, STARTING_PATCH),
    )
    rng = Rng(career)
    draft.setup(cat, career)
    reputation.ensure(cat, career)
    training.ensure(cat, career)
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
              f"with a budget of {career.teams[team_id].budget}k for the season.\n"
              "Before the draft starts the board wants to agree this season's objectives with you.")
    board.start_job(cat, career, season)
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
    scouting.patch_preview(cat, career)
    for state in career.players.values():
        if state.fatigue:
            state.fatigue = max(0, state.fatigue - 4)
    if career.phase == "offseason":
        transfers.daily(cat, career, rng)
    if career.day.weekday() == 0:
        _weekly(cat, career, rng)


def _weekly(cat: Catalog, career: Career, rng: Rng) -> None:
    for team in career.teams.values():
        # The owners fund the salary budget; what the payroll leaves of it, and the sponsors, go to the bank.
        team.cash = int(team.cash + (team.budget - roster.payroll(career, team)) / 52
                        + reputation.sponsor_income(cat, career, team.id))
    training.weekly(cat, career, rng)
    if career.phase == "season" and not career.board.sacked:
        training.review(cat, career)


def _todays_matches(career: Career) -> list:
    return sorted((m for m in career.matches.values() if m.day == career.day and m.winner is None), key=lambda m: m.id)


def _update_competitions(cat: Catalog, career: Career, rng: Rng) -> None:
    """Move the competitions on, then let reputations and the board react to what finished and
    to the international events that were just set."""
    before = set(career.competitions)
    for comp_id in calendar.update(cat, career, rng):
        comp = career.competitions[comp_id]
        reputation.after_competition(cat, career, comp)
        board.after_competition(cat, career, comp, rng)
    for comp_id in set(career.competitions) - before:
        if career.competitions[comp_id].kind == "international":
            board.event_created(cat, career, career.competitions[comp_id])


def _check_free(career: Career) -> None:
    if career.board.sacked:
        raise IllegalAction("You have no club: choose one of the job offers first")
    if career.board.meeting:
        raise IllegalAction("The board is waiting to meet you about the objectives")


def advance(cat: Catalog, career: Career, rng: Rng) -> None:
    if career.phase == "draft":
        raise IllegalAction("Finish the draft first")
    if career.live is not None:
        raise IllegalAction("Your match is waiting")
    _check_free(career)
    if career.phase == "offseason":
        _advance_offseason(cat, career, rng)
        return
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
        _update_competitions(cat, career, rng)
        if career.board.sacked:
            # The board acted before the match: the old team plays it without the manager.
            if mine is not None:
                matchday.play_ai_match(cat, career, mine, rng)
                _update_competitions(cat, career, rng)
            if calendar.season_over(career):
                _end_season(cat, career, rng)
            return
        if mine is not None:
            matchday.start_live(career, mine)
            scouting.scouting_report(cat, career, mine)
            return
        if calendar.season_over(career):
            _end_season(cat, career, rng)
            return
        if _worth_stopping(career, inbox_before):
            return


def _advance_offseason(cat: Catalog, career: Career, rng: Rng, stop: bool = True) -> None:
    inbox_before = len(career.inbox)
    for _ in range(MAX_DAYS_PER_ADVANCE):
        career.day += timedelta(days=1)
        _daily(cat, career, rng)
        if career.day >= transfers.closing_day(career):
            offseason.start_new_season(cat, career, rng)
            start_season(cat, career)
            return
        if career.board.sacked or career.board.meeting:
            return
        if stop and any(m.kind in ("transfer", "player", "board", "contract", "staff")
                        for m in career.inbox[inbox_before:]):
            return


def _worth_stopping(career: Career, inbox_before: int) -> bool:
    """Stop when a competition the manager cares about finished or a new one was announced, or
    the board has something to say."""
    for msg in career.inbox[inbox_before:]:
        if msg.kind in ("news", "board") and (" is set" in msg.subject or " win the " in msg.subject):
            return True
        if msg.kind == "board" and ("losing patience" in msg.subject or "sacked" in msg.subject):
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
    _update_competitions(cat, career, rng)
    if calendar.season_over(career):
        _end_season(cat, career, rng)


def _end_season(cat: Catalog, career: Career, rng: Rng) -> None:
    message(career, "board", f"The {career.season} season is over", _season_review(cat, career))
    offseason.start_offseason(cat, career, rng)


def skip_offseason(cat: Catalog, career: Career, rng: Rng) -> None:
    """Straight to the next season: unanswered bids lapse and players who wanted a word get none."""
    if career.phase != "offseason":
        raise IllegalAction("The season is not over yet")
    _check_free(career)
    while career.phase == "offseason":
        _advance_offseason(cat, career, rng, stop=False)
        if career.board.sacked or career.board.meeting:
            return


# ---------- actions ----------


def migrate(cat: Catalog, career: Career) -> bool:
    """Bring a career saved by an older version up to date. Returns True when anything changed.

    Staff: every team gets the staff pool, and once the draft is over every team hires an
    assistant coach and an analyst straight away (see _hire_staff). Training, reputation and the
    board: every team gets its team areas and set plays, reputations start at prestige and the
    board meets the manager about the season's objectives."""
    changed = False
    if len(career.staff) < len(cat.staff):
        for sid in cat.staff:
            career.staff.setdefault(sid, StaffState(id=sid))
        changed = True
    if career.phase != "draft" and not any(t.coach or t.analyst for t in career.teams.values()):
        _hire_staff(cat, career)
        changed = True
    if not career.seed:
        career.seed = career.rs or 1
        changed = True
    if not career.manager_reputation or any(not t.reputation for t in career.teams.values()):
        reputation.ensure(cat, career)
        changed = True
    if any(not t.skills or not t.plays for t in career.teams.values()):
        training.ensure(cat, career)
        changed = True
    if not career.board.season:
        board.start_job(cat, career, career.season + 1 if career.phase == "offseason" else career.season)
        changed = True
    elif not career.board.bonuses:
        bonuses = board.bonuses_for(career, career.board.season)
        if bonuses:
            career.board.bonuses = bonuses
            changed = True
    if career.phase == "offseason" and not any(h.season == career.season for h in career.history):
        # Saved at the end of a season under the old rules, before the transfer window existed.
        offseason.start_offseason(cat, career, Rng(career))
        changed = True
    return changed


def _hire_staff(cat: Catalog, career: Career) -> None:
    """The boards hire staff without a draft: the biggest organisations choose first, each takes
    the best value it sees, and the board raises the budget by the salary."""
    for team in sorted(career.teams.values(), key=lambda t: -cat.teams[t.id].prestige):
        for kind in ("coach", "analyst"):
            pool = draft.available_staff(cat, career, team.league, kind)
            if not pool:
                continue
            person = max(pool, key=lambda s: s.overall - 60 * s.salary / max(1, team.budget))
            draft.hire(career, team, person)
            team.budget += person.salary
    mine = career.teams[career.team]
    names = [f"{cat.staff[sid].name} as {draft.STAFF_NAMES[kind]}"
             for kind, sid in (("coach", mine.coach), ("analyst", mine.analyst)) if sid]
    if names:
        message(career, "staff", "The board has hired your staff",
                f"New this season: {' and '.join(names)}. Their salaries come on top of your budget. "
                "When their contracts end, the board renews them.")


_ALWAYS = (AcceptJobAction, ReadMessageAction)
_NEED_THE_BOARD = (DraftPickAction, DraftStaffAction, DraftPassAction, DraftAutoAction, DraftSimAction, AdvanceAction,
                   NextSeasonAction, TransferBidAction, OfferAction)


def apply(cat: Catalog, career: Career, action: Action) -> Outcome:
    rng = Rng(career)
    outcome = Outcome()
    migrate(cat, career)
    if career.board.sacked and not isinstance(action, _ALWAYS):
        raise IllegalAction("You have no club: choose one of the job offers first")
    if career.board.meeting and isinstance(action, DraftNextAction):
        return outcome  # the draft waits for the meeting; a client on a timer just gets nothing
    if career.board.meeting and isinstance(action, _NEED_THE_BOARD):
        raise IllegalAction("The board is waiting to meet you about the objectives")
    if isinstance(action, (DraftPickAction, DraftStaffAction, DraftPassAction, DraftAutoAction, DraftSimAction,
                           DraftNextAction)):
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
    elif isinstance(action, SetPlayAction):
        matchday.set_play(cat, career, action.play)
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
        skip_offseason(cat, career, rng)
    elif isinstance(action, BoardMeetingAction):
        board.hold_meeting(cat, career, action.stances)
    elif isinstance(action, AcceptJobAction):
        board.accept_job(cat, career, action.team)
    elif isinstance(action, SetTrainingAction):
        training.set_team(career, action.load, action.focus, action.play, action.clear_play)
    elif isinstance(action, SetPlayerTrainingAction):
        training.set_player(cat, career, action.player, action.attribute, action.champion)
    elif isinstance(action, TransferBidAction):
        transfers.bid(cat, career, action.player, action.fee)
    elif isinstance(action, WithdrawBidAction):
        transfers.withdraw(career, action.offer)
    elif isinstance(action, RespondOfferAction):
        transfers.respond(cat, career, action.offer, action.response, rng)
    elif isinstance(action, TransferListAction):
        transfers.set_listed(cat, career, action.player, action.listed)
    elif isinstance(action, TalkAction):
        transfers.talk(cat, career, action.conversation, action.choice, rng)
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
        elif isinstance(action, DraftStaffAction):
            draft.make_staff_pick(cat, career, d, career.team, action.staff)
        elif isinstance(action, DraftPassAction):
            draft.make_pick(cat, career, d, career.team, None)
        else:
            draft.auto_pick(cat, career, d, rng)
    draft.pass_idle(d, career, career.team)
    _maybe_finish_draft(cat, career, rng)

