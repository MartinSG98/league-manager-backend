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


class PlayerState(BaseModel):
    id: str
    team: str | None = None  # None is a free agent
    contract: Contract | None = None
    form: float = 0.0  # -3..3, recent performances
    morale: int = 70  # 0..100
    fatigue: int = 0  # 0..100
    growth: dict[str, float] = {}  # attribute change since the catalog, can go negative
    learned: dict[str, int] = {}  # mastery gained on champions since the catalog
    season: PlayerSeason = PlayerSeason()


class Tactics(BaseModel):
    style: Literal["early", "balanced", "scaling"] = "balanced"
    lane: Literal["top", "mid", "bot"] = "bot"  # where the jungler and resources go
    objectives: Literal["dragons", "balanced", "barons"] = "balanced"


class TeamState(BaseModel):
    id: str
    league: str
    roster: list[str] = []
    lineup: dict[str, str] = {}  # role -> player id
    franchise: str | None = None
    budget: int = 0  # salary cap for the season, thousands of USD
    cash: int = 0  # bank balance, thousands of USD
    tactics: Tactics = Tactics()
    together: dict[str, int] = {}  # "a|b" -> games two players have started together


class DraftPick(BaseModel):
    number: int
    round: int
    team: str
    player: str | None  # None is a pass in an optional round
    salary: int = 0


class DraftState(BaseModel):
    league: str
    sequence: list[str]  # team id for every pick, snake order
    required_rounds: int  # rounds that fill the starting five
    optional_rounds: int = 0  # bench rounds, a team may pass
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
        return self.required_rounds + self.optional_rounds

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
    kind: Literal["round_robin", "single_elim", "swiss"]
    teams: list[str]
    best_of: int
    final_best_of: int | None = None
    rounds: int = 1  # round robins: how many times everyone meets
    groups: list[list[str]] = []
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
    kind: Literal["news", "draft", "match", "patch", "board", "contract", "finance"]
    subject: str
    body: str
    read: bool = False


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


class Career(BaseModel):
    version: int = 1
    rs: int
    manager: str
    team: str
    region: str
    league: str
    season: int
    day: date
    phase: Phase = "draft"
    players: dict[str, PlayerState]
    teams: dict[str, TeamState]
    drafts: dict[str, DraftState] = {}
    competitions: dict[str, Competition] = {}
    matches: dict[str, Match] = {}
    meta: MetaState
    inbox: list[InboxMessage] = []
    live: LiveSeries | None = None
    history: list[SeasonSummary] = []
    negotiations: dict[str, Negotiation] = {}
    next_message: int = 1


# ---------- actions the client can post ----------


class DraftPickAction(BaseModel):
    type: Literal["draft_pick"]
    player: str


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
    type: Literal["next_season"]


Action = Annotated[
    DraftPickAction | DraftPassAction | DraftAutoAction | DraftSimAction | DraftNextAction | AdvanceAction
    | SetLineupAction | SetTacticsAction | StartDraftAction | BanAction | PickAction | AutoSelectAction
    | OpponentTurnAction | PlayGameAction
    | NextGameAction | SimSeriesAction | ReadMessageAction | OfferAction | AcceptCounterAction | ReleaseAction
    | NextSeasonAction,
    Field(discriminator="type"),
]
