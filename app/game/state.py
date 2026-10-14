"""Career state: everything that changes while a save is played. Static facts (who a player is,
their 2026 stats, champion data) stay in the catalog and are looked up by id.

A career is one JSON document (see repository.py). Only tier-one teams are simulated; players
from tier-two leagues sit in the free-agent pool of their region until someone signs them."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.game.catalog import Role

Side = Literal["blue", "red"]
Phase = Literal["draft", "season", "offseason"]


class Contract(BaseModel):
    salary: int  # thousands of USD a season
    until: int  # last season the contract covers


class PlayerSeason(BaseModel):
    games: int = 0
    wins: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    cs: int = 0
    damage: int = 0
    minutes: float = 0
    mvps: int = 0
    rating_sum: float = 0
    champions: dict[str, int] = {}


class PlayerTraining(BaseModel):
    """What a player works on in their own time, on top of the team's scrims."""

    attribute: str | None = None  # one of ratings.ATTRIBUTES
    champion: str | None = None  # a champion to learn


class PlayerState(BaseModel):
    id: str
    team: str | None = None  # None is a free agent
    contract: Contract | None = None
    form: float = 0.0  # -3..3, recent performances
    morale: int = 70  # 0..100
    fatigue: int = 0  # 0..100
    sharpness: int = 70  # 0..100, kept up by scrims; low means complacent
    burnout: int = 0  # weeks left of a burnout
    growth: dict[str, float] = {}  # attribute change since the catalog, can go negative
    learned: dict[str, int] = {}  # mastery gained on champions since the catalog
    season: PlayerSeason = PlayerSeason()
    development: list[float] = []  # this season's weekly training quality, feeds the off-season growth
    training: PlayerTraining = PlayerTraining()
    unsettled: bool = False  # wants to leave
    promise: int | None = None  # season in which the manager promised to let them go for a big offer
    played: int = 0  # games in the seasons of this career before the current one
    retiring: int | None = None  # the season they have said will be their last
    retired: bool = False


class Tactics(BaseModel):
    style: Literal["early", "balanced", "scaling"] = "balanced"
    lane: Literal["top", "mid", "bot"] = "bot"  # where the jungler and resources go
    objectives: Literal["dragons", "balanced", "barons"] = "balanced"


class StaffState(BaseModel):
    id: str
    team: str | None = None
    contract: Contract | None = None


Load = Literal["light", "normal", "heavy", "intense"]


class Training(BaseModel):
    load: Load = "normal"  # how hard the team scrims
    focus: list[str] = []  # up to two team areas, see training.AREAS
    play: str | None = None  # the set play being drilled, see plays.PLAYS


class TeamState(BaseModel):
    id: str
    league: str
    roster: list[str] = []
    lineup: dict[str, str] = {}  # role -> player id
    franchise: str | None = None
    coach: str | None = None  # assistant coach, staff id
    analyst: str | None = None  # staff id
    budget: int = 0  # salary cap for the season, thousands of USD
    budget_moved: int = 0  # how much of the budget the board set the manager moved into the bank (negative: out of it)
    cash: int = 0  # bank balance, thousands of USD
    tactics: Tactics = Tactics()
    together: dict[str, float] = {}  # "a|b" -> games two players have started together, a good coach counts more
    reputation: float = 0  # 0..100, 0 until a career sets it from the catalog's prestige
    skills: dict[str, float] = {}  # team area -> 1..20, what scrims build
    plays: dict[str, float] = {}  # set play -> 0..100 learned
    training: Training = Training()
    listed: list[str] = []  # players the team would sell
    expected: int = 0  # where its reputation ranked it in its league when the season started, 0 before
    elo: float = 0.0  # the global power rankings' rating (power.py), 0 until seeded
    elo_start: float = 0.0  # its rating when the season began, for the trend
    coach_since: date | None = None  # when the coach in the seat was appointed, None from the first draft


class DraftPick(BaseModel):
    number: int
    round: int
    team: str
    player: str | None  # None is a pass in an optional round, or a staff pick
    salary: int = 0
    staff: str | None = None  # staff id in a staff round


class DraftState(BaseModel):
    league: str
    sequence: list[str]  # team id for every pick, snake order
    required_rounds: int  # rounds that fill the starting five
    optional_rounds: int = 0  # bench rounds, a team may pass
    staff_rounds: list[Literal["coach", "analyst"]] = []  # after the player rounds, one kind each
    picks: list[DraftPick] = []

    @property
    def done(self) -> bool:
        return len(self.picks) >= len(self.sequence)

    @property
    def number(self) -> int:
        return len(self.picks)

    @property
    def on_the_clock(self) -> str | None:
        return None if self.done else self.sequence[len(self.picks)]

    @property
    def rounds(self) -> int:
        return self.required_rounds + self.optional_rounds + len(self.staff_rounds)

    @property
    def round_kind(self) -> str:
        """"player", or the staff kind the current round is for."""
        extra = self.round - self.required_rounds - self.optional_rounds
        return self.staff_rounds[extra - 1] if 0 < extra <= len(self.staff_rounds) else "player"

    @property
    def teams_per_round(self) -> int:
        return len(self.sequence) // max(1, self.rounds)

    @property
    def round(self) -> int:
        return self.number // max(1, self.teams_per_round) + 1


class PlayerLine(BaseModel):
    player: str
    team: str
    role: Role
    champion: str
    kills: int
    deaths: int
    assists: int
    cs: int
    gold: int
    damage: int
    rating: float  # 1-10


class GameRecord(BaseModel):
    number: int
    blue: str
    red: str
    winner: str
    duration: int  # seconds
    kills: list[int]  # blue, red
    gold: list[int]
    towers: list[int]
    dragons: list[int]
    barons: list[int]
    blue_picks: dict[str, str]  # role -> champion
    red_picks: dict[str, str]
    blue_bans: list[str]
    red_bans: list[str]
    players: list[PlayerLine]
    mvp: str | None = None
    detailed: bool = False  # a full timeline is stored next to the career
    gold15: int = 0  # blue minus red gold at 15 minutes
    leads: list[int] = [0, 0]  # the biggest gold lead blue and red had
    fights: list[int] = [0, 0]  # teamfights won
    throws: list[int] = [0, 0]  # fights blue and red threw away while well ahead
    plays: dict[str, str] = {}  # team -> set play run
    play_results: dict[str, bool] = {}  # team -> whether it worked


class Match(BaseModel):
    id: str
    competition: str
    stage: str
    label: str
    day: date
    home: str | None = None  # None until a bracket feeds a team in
    away: str | None = None
    best_of: int = 1
    fearless: bool = False
    home_from: str | None = None  # "W:<match id>", "L:<match id>" or "S:<seed>"
    away_from: str | None = None
    games: list[GameRecord] = []
    winner: str | None = None
    plays_used: dict[str, list[str]] = {}  # team -> set plays already run in this series
    bracket: Literal["upper", "lower", "final"] | None = None  # double elimination only
    round: int = 0  # column in a double-elimination bracket
    eliminates: int = 0  # double elimination: the place the loser finishes, 0 when they drop to the lower bracket

    @property
    def score(self) -> tuple[int, int]:
        home = sum(1 for g in self.games if g.winner == self.home)
        return home, len(self.games) - home

    @property
    def loser(self) -> str | None:
        if self.winner is None:
            return None
        return self.away if self.winner == self.home else self.home


class Stage(BaseModel):
    id: str
    name: str
    kind: Literal["round_robin", "single_elim", "double_elim", "swiss"]
    teams: list[str]
    best_of: int
    final_best_of: int | None = None
    rounds: int = 1  # round robins: how many times everyone meets
    groups: list[list[str]] = []
    pots: list[list[str]] = []  # Swiss: the seeding pots the first round is drawn from, best first
    advance: int = 0  # teams that move on, 0 for a final stage
    days: list[date] = []
    matches: list[str] = []
    finished: bool = False
    ranking: list[str] = []  # final order once finished


class Competition(BaseModel):
    id: str
    name: str
    short: str
    kind: Literal["league", "international"]
    league: str | None = None
    split: int | None = None
    start: date
    end: date
    stages: list[Stage] = []
    entrants: list[str] = []
    status: Literal["upcoming", "running", "finished"] = "upcoming"
    placements: list[str] = []  # final order once finished
    prize_pool: int = 0  # thousands of USD


class PatchChange(BaseModel):
    champion: str
    delta: float
    note: str


class Patch(BaseModel):
    version: str
    day: date
    headline: str
    changes: list[PatchChange] = []


class MetaState(BaseModel):
    version: str
    power: dict[str, float]  # champion id -> strength on the current patch, about -3.5..+5
    history: list[Patch] = []
    next_patch: date | None = None
    # Pro play on the current patch, what the balance team looks at for the next one.
    picks: dict[str, int] = {}
    bans: dict[str, int] = {}
    games: int = 0


class InboxMessage(BaseModel):
    id: int
    day: date
    kind: Literal["news", "draft", "match", "patch", "board", "contract", "finance", "scouting", "staff", "transfer",
                  "player", "training", "draw"]
    subject: str
    body: str
    read: bool = False
    report: dict | None = None  # structured content for the client to draw: a scouting report, a review
    offer: int | None = None  # the transfer offer this message is about
    conversation: int | None = None  # the talk a player asked for
    competition: str | None = None  # a Swiss draw: the competition
    round: int | None = None  # and the round that was drawn


# ---------- the series being played by the manager's team ----------

DraftStepKind = Literal["ban", "pick"]


class ChampSelect(BaseModel):
    step: int = 0
    blue_bans: list[str] = []
    red_bans: list[str] = []
    blue_picks: dict[str, str] = {}  # role -> champion
    red_picks: dict[str, str] = {}
    locked: list[str] = []  # fearless: champions used earlier in the series


class LiveSeries(BaseModel):
    match: str
    game: int = 1
    our_side: Side = "blue"
    phase: Literal["lineup", "draft", "ready", "result"] = "lineup"
    select: ChampSelect = ChampSelect()
    play: str | None = None  # the set play chosen for this game


class SeasonSummary(BaseModel):
    season: int
    titles: list[str] = []
    finishes: dict[str, int] = {}  # competition name -> placement
    champions: dict[str, str] = {}  # competition name -> winning team id


class Negotiation(BaseModel):
    """Contract talks with one player, kept so a counter-offer can be accepted later."""

    player: str
    kind: Literal["sign", "extend"]
    rounds: int = 0
    counter: int | None = None  # salary the player came back with
    counter_years: int | None = None
    blocked_until: date | None = None  # walked away, will not talk again before this day
    message: str = ""


class Objective(BaseModel):
    """One thing the board expects this season: a finish in a split, or how far to go at Worlds."""

    id: str
    kind: Literal["split", "worlds"]
    split: int | None = None
    target: int  # split: this place or better; worlds: a step of board.WORLDS_STEPS
    proposed: int  # what the board asked for before the meeting
    status: Literal["pending", "met", "failed"] = "pending"
    result: str = ""


class Bonus(BaseModel):
    """Something the board rewards but does not demand: qualifying for First Stand or MSI, or a
    deep run there."""

    id: str
    event: Literal["FST", "MSI"]
    place: int  # 0: qualify; otherwise finish at this place or better
    confidence: int
    reputation: float  # the manager's
    sponsors: float  # share of the salary budget the sponsors pay
    status: Literal["pending", "earned", "missed"] = "pending"


class BoardState(BaseModel):
    season: int = 0  # the season the objectives are for
    confidence: int = 60  # 0..100
    objectives: list[Objective] = []
    bonuses: list[Bonus] = []
    meeting: bool = False  # a meeting about the objectives is waiting
    warned: bool = False  # one more bad review and the manager is sacked
    sacked: bool = False
    joined: date | None = None  # when the manager took this job
    history: list[str] = []  # the board's reviews, newest last
    in_debt: bool = False  # the bank is below zero and the board has said so
    wage_cut: date | None = None  # when the board last cut wages over the debt


class Vacancy(BaseModel):
    """An AI club looking for a head coach (see jobs.py)."""

    team: str
    opened: date
    closes: date  # the club appoints someone if nothing else happened by then
    offer_until: date | None = None  # an offer to the manager is open until then
    applied: bool = False
    declined: bool = False  # the manager turned it down or let it lapse


class TransferOffer(BaseModel):
    """A bid for a player under contract: an AI club bidding for the manager's player, or the
    manager bidding for someone else's."""

    id: int
    player: str
    buyer: str
    seller: str
    fee: int  # thousands of USD
    day: date
    expires: date
    status: Literal["open", "agreed", "completed", "rejected", "withdrawn", "expired", "collapsed"] = "open"
    counter: int | None = None  # the selling club's asking fee
    rounds: int = 0
    note: str = ""


class CareerStaff(BaseModel):
    """A coach or analyst the game made up after the first season: a retired player or a newcomer
    (see hiring.new_faces)."""
    id: str
    name: str
    kind: Literal["coach", "analyst"]
    position: str
    region: str
    country: str | None
    attributes: dict[str, int]
    overall: int
    salary: int
    season: int  # the off-season they joined the market in
    former_player: str | None = None  # the player id, for a retired player


class Rookie(BaseModel):
    """A player the game made up: one of a season's rookie class (see rookies.py)."""
    id: str
    name: str
    role: Role
    country: str | None
    league: str  # the league of the academy or ERL they came through, or of their region
    team: str  # their team of origin, "" when they came straight from solo queue
    season: int  # the season they turned pro for
    experience: int
    attributes: dict[str, int]
    overall: int
    potential: int  # the scouts' first estimate; the real ceiling is hidden like everyone's
    aggression: int
    leadership: int
    reputation: int
    salary: int
    pool: list[tuple[str, int]]  # champion, games
    signatures: list[str] = []


class Shortlisted(BaseModel):
    """A player on the manager's shortlist."""
    player: str
    added: date
    due: date | None = None  # when the analyst's next report lands
    reports: int = 0
    team: str | None = None  # the club the player was at when last seen
    report: dict | None = None  # the latest report


class Conversation(BaseModel):
    """A player asked to talk to the manager."""

    id: int
    player: str
    topic: Literal["rejected_bid", "broken_promise"]
    team: str | None = None  # the club that wanted them
    day: date
    expires: date
    resolved: bool = False
    outcome: str = ""


class Spell(BaseModel):
    """The manager's time at one club."""

    team: str
    start: date
    end: date | None = None  # None: still there
    left: Literal["", "moved", "sacked"] = ""


class CompetitionRecord(BaseModel):
    """How the manager's team did in one competition."""

    name: str
    kind: Literal["league", "FST", "MSI", "WORLDS"]
    team: str
    series: list[int] = [0, 0]  # won, lost
    games: list[int] = [0, 0]
    place: int | None = None  # the final place, once the competition is over
    first: date | None = None  # the day of its first series, which tells the spell it belongs to


class ManagerSeason(BaseModel):
    """The manager's season, kept when it ends: the competitions are cleared for the next one."""

    season: int
    competitions: list[CompetitionRecord] = []
    reputation: float = 0


class ManagerProfile(BaseModel):
    """The manager as a person (see manager.py): created once, after the club is picked."""

    background: Literal["pro", "coach", "analyst", "newcomer"]
    country: str | None = None  # ISO 3166 alpha-2
    attributes: dict[str, float]  # 1-20; what counts is the whole number, growth adds fractions
    duties: dict[str, Literal["manager", "staff"]] = {}  # a staff attribute -> who does that work; absent: the better one
    created: date


class Career(BaseModel):
    version: int = 1
    rs: int
    seed: int = 0  # fixed at creation, for hidden values that must never change
    schedules_drawn: bool = False  # round robins are drawn at random; older saves had one fixed order
    manager: str
    team: str
    region: str
    league: str
    season: int
    day: date
    phase: Phase = "draft"
    players: dict[str, PlayerState]
    teams: dict[str, TeamState]
    staff: dict[str, StaffState] = {}
    drafts: dict[str, DraftState] = {}
    competitions: dict[str, Competition] = {}
    matches: dict[str, Match] = {}
    meta: MetaState
    inbox: list[InboxMessage] = []
    live: LiveSeries | None = None
    history: list[SeasonSummary] = []
    negotiations: dict[str, Negotiation] = {}
    next_message: int = 1
    manager_reputation: float = 0  # 0..100, what the whole scene thinks of the manager
    manager_standing: dict[str, float] = {}  # region -> the manager's reputation there, where they have worked
    region_elo: dict[str, float] = {}  # region -> its rating in the global power rankings (power.py)
    region_elo_start: dict[str, float] = {}  # the same when the season began, for the trend
    franchise_choice: date | None = None  # the day by which the manager names a new franchise player, while one is due
    predicted: list[str] = []  # competitions the analyst has sent predictions for (predictions.py)
    board: BoardState = BoardState()
    job_offers: list[str] = []  # clubs that want the manager after a sacking
    vacancies: list[Vacancy] = []  # AI clubs looking for a head coach
    offers: list[TransferOffer] = []
    conversations: list[Conversation] = []
    transfers: list[dict] = []  # completed moves this window, newest last
    next_offer: int = 1
    reviewed_games: int = 0  # the manager's games the analyst had seen at the last review
    shortlist: list[Shortlisted] = []
    rookies: list[Rookie] = []  # every rookie class so far, oldest first
    new_staff: list[CareerStaff] = []  # coaches and analysts who joined the market in this career
    staff_talks: dict[str, Negotiation] = {}  # staff id -> contract talks
    profile: ManagerProfile | None = None  # None until the manager is created; older saves create theirs on load
    spells: list[Spell] = []  # the manager's clubs, oldest first
    manager_seasons: list[ManagerSeason] = []  # seasons that are over, oldest first
    # The manager's reputation each time it changed: day, world, region (older entries lack the region).
    reputation_log: list[tuple[date, float, float, str] | tuple[date, float, float] | tuple[date, float]] = []


# ---------- actions the client can post ----------


class DraftPickAction(BaseModel):
    type: Literal["draft_pick"]
    player: str


class DraftStaffAction(BaseModel):
    type: Literal["draft_staff"]
    staff: str


class DraftPassAction(BaseModel):
    type: Literal["draft_pass"]


class DraftAutoAction(BaseModel):
    type: Literal["draft_auto"]  # let the assistant make this pick


class DraftSimAction(BaseModel):
    type: Literal["draft_sim"]  # let the assistant finish the whole draft


class DraftNextAction(BaseModel):
    type: Literal["draft_next"]  # the team on the clock picks; nothing happens on the manager's turn
    until_mine: bool = False  # every pick up to the manager's turn at once


class AdvanceAction(BaseModel):
    type: Literal["advance"]


class SetLineupAction(BaseModel):
    type: Literal["set_lineup"]
    lineup: dict[str, str]


class SetTacticsAction(BaseModel):
    type: Literal["set_tactics"]
    tactics: Tactics


class StartDraftAction(BaseModel):
    type: Literal["start_champ_select"]


class BanAction(BaseModel):
    type: Literal["ban"]
    champion: str


class PickAction(BaseModel):
    type: Literal["pick"]
    champion: str
    role: Role


class AutoSelectAction(BaseModel):
    type: Literal["auto_select"]  # let the assistant finish champion select


class OpponentTurnAction(BaseModel):
    type: Literal["opponent_turn"]  # the opponent's next ban or pick; nothing happens on the manager's turn
    until_mine: bool = False  # every opponent turn up to the manager's at once


class PlayGameAction(BaseModel):
    type: Literal["play_game"]


class NextGameAction(BaseModel):
    type: Literal["next_game"]


class SimSeriesAction(BaseModel):
    type: Literal["sim_series"]  # auto-draft and simulate the rest of the series


class ReadMessageAction(BaseModel):
    type: Literal["read_message"]
    id: int | None = None  # None marks everything read


class OfferAction(BaseModel):
    type: Literal["offer"]
    player: str
    salary: int  # thousands of USD a season
    years: int


class AcceptCounterAction(BaseModel):
    type: Literal["accept_counter"]
    player: str


class ReleaseAction(BaseModel):
    type: Literal["release"]
    player: str


class NextSeasonAction(BaseModel):
    type: Literal["next_season"]  # move through the rest of the off-season to the new season


class BoardMeetingAction(BaseModel):
    type: Literal["board_meeting"]
    stances: dict[str, int] = {}  # objective id -> -1 (ask for less), 0 (accept) or 1 (promise more)


class AcceptJobAction(BaseModel):
    type: Literal["accept_job"]  # after a sacking, or an offer from a club looking for a head coach
    team: str


class StaffOfferAction(BaseModel):
    type: Literal["staff_offer"]  # hire a coach or analyst, or extend your own
    staff: str
    salary: int
    years: int


class StaffAcceptCounterAction(BaseModel):
    type: Literal["staff_accept_counter"]
    staff: str


class StaffReleaseAction(BaseModel):
    type: Literal["staff_release"]
    staff: str


class CreateManagerAction(BaseModel):
    type: Literal["create_manager"]
    background: Literal["pro", "coach", "analyst", "newcomer"]
    attributes: dict[str, int]  # before the background's bonus
    name: str | None = None
    country: str | None = None


class SetFranchiseAction(BaseModel):
    type: Literal["set_franchise"]  # while the seat is empty: one of the manager's players becomes the franchise player
    player: str


class SetDutyAction(BaseModel):
    type: Literal["set_duty"]
    attribute: str
    who: Literal["manager", "staff", "auto"]  # auto: whoever is better at it


class ApplyJobAction(BaseModel):
    type: Literal["apply_job"]
    team: str


class DeclineJobAction(BaseModel):
    type: Literal["decline_job"]
    team: str


class SetTrainingAction(BaseModel):
    type: Literal["set_training"]
    load: Load | None = None
    focus: list[str] | None = None
    play: str | None = None
    clear_play: bool = False


class SetPlayerTrainingAction(BaseModel):
    type: Literal["set_player_training"]
    player: str
    attribute: str | None = None
    champion: str | None = None


class SetPlayAction(BaseModel):
    type: Literal["set_play"]
    play: str | None = None


class TransferBidAction(BaseModel):
    type: Literal["transfer_bid"]
    player: str
    fee: int


class WithdrawBidAction(BaseModel):
    type: Literal["withdraw_bid"]
    offer: int


class RespondOfferAction(BaseModel):
    type: Literal["respond_offer"]
    offer: int
    response: Literal["accept", "reject", "negotiate"]


class TransferListAction(BaseModel):
    type: Literal["transfer_list"]
    player: str
    listed: bool


class TalkAction(BaseModel):
    type: Literal["talk"]
    conversation: int
    choice: Literal["vital", "promise", "final"]


class ShortlistAction(BaseModel):
    type: Literal["shortlist"]
    player: str
    on: bool = True  # False takes the player off


class ScoutPlayerAction(BaseModel):
    type: Literal["scout_player"]  # ask the analyst for a new report on a shortlisted player
    player: str


class AdjustBudgetAction(BaseModel):
    type: Literal["adjust_budget"]  # set the salary budget; the difference goes to or comes from the bank
    budget: int


Action = Annotated[
    DraftPickAction | DraftStaffAction | DraftPassAction | DraftAutoAction | DraftSimAction | DraftNextAction
    | AdvanceAction
    | SetLineupAction | SetTacticsAction | StartDraftAction | BanAction | PickAction | AutoSelectAction
    | OpponentTurnAction | PlayGameAction
    | NextGameAction | SimSeriesAction | ReadMessageAction | OfferAction | AcceptCounterAction | ReleaseAction
    | NextSeasonAction | BoardMeetingAction | AcceptJobAction | SetTrainingAction | SetPlayerTrainingAction
    | SetPlayAction | TransferBidAction | WithdrawBidAction | RespondOfferAction | TransferListAction | TalkAction
    | ShortlistAction | ScoutPlayerAction | AdjustBudgetAction | ApplyJobAction | DeclineJobAction
    | StaffOfferAction | StaffAcceptCounterAction | StaffReleaseAction | CreateManagerAction | SetDutyAction
    | SetFranchiseAction,
    Field(discriminator="type"),
]
