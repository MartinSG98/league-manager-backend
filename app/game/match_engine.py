"""One game of League, simulated minute by minute.

Each side brings a power per role (player rating plus what their champion adds, see
champ_select), team chemistry, a composition modifier and a power curve: an early composition
is stronger before 14 minutes and weaker after 30, a scaling one the other way round.

Minutes 1-14 are laning. Every lane trades gold according to its matchup, with solo kills and
jungle ganks on top, and the junglers contest voidgrubs and the first dragons. From 15 minutes
fights break out, most often around a live objective; the winner of a fight takes kills, the
objective and towers. Gold, dragons, Soul, Baron and Elder all feed back into the next fight,
so a lead snowballs, but every fight is a dice roll and a weaker team can always throw one. The
game ends when a side wins a fight with an inhibitor already down and a buff or a big margin.

The result is a GameRecord with a stat line per player, and a timeline with the gold
difference every minute for the match-day playback."""

import math
from dataclasses import dataclass, field

from app.game import roster
from app.game.catalog import ROLES, Catalog
from app.game.champ_select import champion_power, composition_modifier, focus_bias, lane_edge
from app.game.rng import Rng
from app.game.state import Career, GameRecord, PlayerLine, Side, Tactics

DRAGONS = ("Infernal", "Mountain", "Ocean", "Cloud", "Hextech", "Chemtech")
# Calibration, tuned with scripts/simulate.py so that a 4 point edge in team power wins about
# 65 percent of games and a 10 point edge about 85 percent.
FIGHT_SCALE = 18.0  # power difference that makes a fight 73/27
GOLD_POWER = 0.2  # power per 1000 gold of lead
LANE_GOLD = 3.0  # gold per minute per point of lane difference
DAY_FORM = 6.5  # spread of a side's random form on the day
BLUE_EDGE = 0.4
FIGHT_CHANCE = (0.55, 0.2)  # chance of a fight in a minute with and without a live objective
DRIFT_GOLD = 6.0  # gold per minute per point of power after laning, farm and map control
BUFFS = {"baron": 5.0, "elder": 7.0, "soul": 3.0}
KILL_GOLD = 300
TOWER_GOLD = 550  # shared by the team, plates included

ROLE_GOLD = {"TOP": 0.21, "JNG": 0.19, "MID": 0.23, "BOT": 0.25, "SUP": 0.12}
ROLE_CS = {"TOP": 8.1, "JNG": 6.2, "MID": 8.6, "BOT": 9.2, "SUP": 1.3}
ROLE_DAMAGE = {"TOP": 0.22, "JNG": 0.15, "MID": 0.27, "BOT": 0.29, "SUP": 0.07}
ROLE_KILLS = {"TOP": 0.17, "JNG": 0.19, "MID": 0.26, "BOT": 0.32, "SUP": 0.06}
ROLE_DEATHS = {"TOP": 0.21, "JNG": 0.2, "MID": 0.18, "BOT": 0.18, "SUP": 0.23}
ROLE_ASSIST = {"TOP": 0.5, "JNG": 0.75, "MID": 0.62, "BOT": 0.6, "SUP": 0.85}
CLASS_DAMAGE = {"Mage": 1.15, "Marksman": 1.15, "Assassin": 1.1, "Fighter": 1.0, "Tank": 0.7, "Enchanter": 0.6}
CLASS_KILLS = {"Assassin": 1.3, "Marksman": 1.15, "Fighter": 1.05, "Mage": 1.0, "Tank": 0.6, "Enchanter": 0.5}


def logistic(x: float) -> float:
    return 1 / (1 + math.exp(-x))


@dataclass
class GameSide:
    side: Side
    team: str
    lineup: dict[str, str]
    picks: dict[str, str]
    tactics: Tactics
    power: dict[str, float] = field(default_factory=dict)
    aggression: dict[str, int] = field(default_factory=dict)
    base: float = 0.0
    early: float = 0.0
    gold: float = 0.0
    kills: int = 0
    towers: int = 0  # enemy towers destroyed
    inhibs: int = 0  # enemy inhibitors destroyed
    dragons: list[str] = field(default_factory=list)
    soul: bool = False
    grubs: int = 0
    barons: int = 0
    baron_until: int = -1
    elder_until: int = -1
    stats: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class Event:
    t: int
    kind: str
    side: Side | None
    text: str
    score: tuple[int, int] = (0, 0)
    gold: int = 0


@dataclass
class GameResult:
    record: GameRecord
    events: list[Event]
    gold_diff: list[int]  # blue minus red, every minute


def prepare(cat: Catalog, career: Career, side: Side, team: str, lineup: dict[str, str], picks: dict[str, str],
            tactics: Tactics) -> GameSide:
    gs = GameSide(side=side, team=team, lineup=lineup, picks=picks, tactics=tactics)
    for role in ROLES:
        pid = lineup[role]
        state = career.players[pid]
        rating = roster.overall(cat, career, pid)
        condition = state.form * 0.8 + (state.morale - 70) / 20 - state.fatigue / 30
        gs.power[role] = rating + champion_power(cat, career, pid, picks[role], role) + condition
        gs.aggression[role] = cat.players[pid].aggression
        gs.stats[role] = {"k": 0, "d": 0, "a": 0, "cs": 0.0, "dmg": 0.0}
    chem, _ = roster.chemistry(cat, career, career.teams[team], lineup) if team in career.teams else (0.0, [])
    comp, _ = composition_modifier(cat, picks)
    gs.early = focus_bias(cat, picks)
    style = tactics.style
    fit = 0.0
    if style == "early":
        fit = 0.8 if gs.early > 0 else -0.4
    elif style == "scaling":
        fit = 0.8 if gs.early < 0 else -0.4
    gs.base = sum(gs.power.values()) / 5 + chem + comp + fit
    return gs


class Game:
    def __init__(self, cat: Catalog, career: Career, blue: GameSide, red: GameSide, rng: Rng, number: int):
        self.cat, self.career, self.rng, self.number = cat, career, rng, number
        self.blue, self.red = blue, red
        self.blue.base += BLUE_EDGE + (rng.next() - 0.5) * 2 * DAY_FORM
        self.red.base += (rng.next() - 0.5) * 2 * DAY_FORM
        self.events: list[Event] = []
        self.gold_diff: list[int] = [0]
        self.minute = 0
        self.first_blood = False
        self.dragon_at, self.baron_at, self.elder_at = 5, 20, None
        self.herald_done = False
        self.winner: GameSide | None = None
        self.second = 0

    # ---------- helpers ----------

    def other(self, gs: GameSide) -> GameSide:
        return self.red if gs is self.blue else self.blue

    def strength(self, gs: GameSide) -> float:
        m = self.minute
        phase = 1.0 if m <= 14 else (-1.0 if m >= 32 else 1 - 2 * (m - 14) / 18)
        value = gs.base + gs.early * phase
        if m < 25:
            value += min(6, gs.grubs) * 0.12
        value += len(gs.dragons) * 0.35 + (BUFFS["soul"] if gs.soul else 0)
        if gs.baron_until >= m:
            value += BUFFS["baron"]
        if gs.elder_until >= m:
            value += BUFFS["elder"]
        value += (gs.gold - self.other(gs).gold) / 1000 * GOLD_POWER
        return value

    def name(self, gs: GameSide, role: str) -> str:
        pid = gs.lineup[role]
        return f"{self.cat.players[pid].name} ({self.cat.champions[gs.picks[role]].name})"

    def tag(self, gs: GameSide) -> str:
        return self.cat.teams[gs.team].tag

    def log(self, kind: str, side: GameSide | None, text: str) -> None:
        self.second = max(self.second + 1, self.minute * 60 + self.rng.int(55))
        self.events.append(Event(
            t=self.second, kind=kind, side=side.side if side else None, text=text,
            score=(self.blue.kills, self.red.kills), gold=int(self.blue.gold - self.red.gold),
        ))

    def weighted(self, weights: dict[str, float]) -> str:
        total = sum(weights.values())
        roll = self.rng.next() * total
        for role, w in weights.items():
            roll -= w
            if roll <= 0:
                return role
        return next(iter(weights))

    def kill(self, killer_side: GameSide, killer: str, victim: str, helpers: list[str], quiet: bool = False) -> None:
        loser = self.other(killer_side)
        killer_side.kills += 1
        killer_side.stats[killer]["k"] += 1
        loser.stats[victim]["d"] += 1
        for role in helpers:
            if role != killer:
                killer_side.stats[role]["a"] += 1
        bounty = KILL_GOLD + (100 if not self.first_blood else 0) + 60 * len(helpers)
        killer_side.gold += bounty
        if not self.first_blood:
            self.first_blood = True
            self.log("first_blood", killer_side,
                     f"First blood! {self.name(killer_side, killer)} kills {self.name(loser, victim)}")
        elif not quiet:
            self.log("kill", killer_side, f"{self.name(killer_side, killer)} kills {self.name(loser, victim)}")

    # ---------- laning ----------

    LANES = {"top": ("TOP",), "mid": ("MID",), "bot": ("BOT", "SUP")}

    def lane_power(self, gs: GameSide, lane: str) -> float:
        roles = self.LANES[lane]
        if lane == "bot":
            return (gs.power["BOT"] + 0.6 * gs.power["SUP"]) / 1.6
        return gs.power[roles[0]]

    def lane_diff(self, lane: str) -> float:
        main = self.LANES[lane][0]
        edge = lane_edge(self.cat, self.cat.champions[self.blue.picks[main]], self.cat.champions[self.red.picks[main]])
        return self.lane_power(self.blue, lane) - self.lane_power(self.red, lane) + edge

    def laning_minute(self) -> None:
        for lane in ("top", "mid", "bot"):
            d = self.lane_diff(lane)
            shift = LANE_GOLD * d + (self.rng.next() - 0.5) * 70
            self.blue.gold += shift / 2
            self.red.gold -= shift / 2
            roles = self.LANES[lane]
            aggr = sum(self.blue.aggression[r] + self.red.aggression[r] for r in roles) / (2 * len(roles))
            if self.rng.chance(0.022 + 0.003 * (aggr - 10) + 0.004 * abs(d)):
                winner = self.blue if self.rng.chance(logistic(d / 3)) else self.red
                loser = self.other(winner)
                killer = roles[0] if len(roles) == 1 else ("BOT" if self.rng.chance(0.7) else "SUP")
                victim = roles[0] if len(roles) == 1 else ("BOT" if self.rng.chance(0.55) else "SUP")
                helpers = [r for r in roles if r != killer]
                self.kill(winner, killer, victim, helpers)
        if self.minute >= 3:
            for gs in (self.blue, self.red):
                self.gank(gs)

    def gank(self, gs: GameSide) -> None:
        enemy = self.other(gs)
        if not self.rng.chance(0.055 + 0.004 * (gs.aggression["JNG"] - 10)):
            return
        weights = {"top": 0.25, "mid": 0.35, "bot": 0.4}
        weights[gs.tactics.lane] += 0.35
        lane = self.weighted(weights)
        roles = self.LANES[lane]
        mine = gs.power["JNG"] + self.lane_power(gs, lane)
        theirs = self.lane_power(enemy, lane) + 0.6 * enemy.power["JNG"]
        if self.rng.chance(logistic((mine - theirs) / 5 + 0.35)):
            killer = roles[0] if self.rng.chance(0.55) else "JNG"
            victim = roles[0] if len(roles) == 1 else ("BOT" if self.rng.chance(0.6) else "SUP")
            self.kill(gs, killer, victim, ["JNG", *roles])
        elif self.rng.chance(0.35):
            self.kill(enemy, roles[0], "JNG", list(roles))
            self.log("note", enemy, f"{self.tag(enemy)} punish the gank in {lane} lane")

    # ---------- objectives ----------

    def contest(self, roles: tuple[str, ...], bonus_blue: float = 0.0) -> GameSide:
        b = sum(self.blue.power[r] for r in roles) / len(roles)
        r = sum(self.red.power[x] for x in roles) / len(roles)
        edge = (b - r) / 3.5 + (self.blue.gold - self.red.gold) / 2500 + bonus_blue
        return self.blue if self.rng.chance(logistic(edge)) else self.red

    def tactic_bonus(self, kind: str) -> float:
        wants = {"dragons": "dragon", "barons": "baron"}
        b = 0.4 if wants.get(self.blue.tactics.objectives) == kind else 0.0
        r = 0.4 if wants.get(self.red.tactics.objectives) == kind else 0.0
        return b - r

    def take_dragon(self, gs: GameSide) -> None:
        if self.elder_at is not None:
            gs.elder_until = self.minute + 3
            self.elder_at = self.minute + 6
            self.log("elder", gs, f"{self.tag(gs)} slay the Elder Dragon")
            return
        kind = self.rng.pick(DRAGONS) or "Infernal"
        gs.dragons.append(kind)
        if len(gs.dragons) >= 4:
            gs.soul = True
            self.elder_at = self.minute + 6
            self.dragon_at = 999
            self.log("soul", gs, f"{self.tag(gs)} claim the {gs.dragons[2]} Soul")
        else:
            self.dragon_at = self.minute + 5
            self.log("dragon", gs, f"{self.tag(gs)} take the {kind} Drake ({len(gs.dragons)})")

    def early_objectives(self) -> None:
        m = self.minute
        if m in (6, 10):
            gs = self.contest(("JNG", "TOP"), self.tactic_bonus("baron"))
            gs.grubs += 3
            gs.gold += 150
            self.log("grubs", gs, f"{self.tag(gs)} take the Voidgrubs")
        if m >= self.dragon_at and self.elder_at is None:
            if self.rng.chance(0.3):
                self.fight(reason="dragon")
            else:
                self.take_dragon(self.contest(("JNG", "BOT", "SUP", "MID"), self.tactic_bonus("dragon")))
        if m == 14 and not self.herald_done:
            self.herald_done = True
            gs = self.contest(("JNG", "TOP", "MID"), self.tactic_bonus("baron"))
            self.log("herald", gs, f"{self.tag(gs)} secure the Rift Herald")
            if self.rng.chance(0.7):
                self.destroy_towers(gs, 1)

    # ---------- structures ----------

    def destroy_towers(self, gs: GameSide, count: int) -> None:
        for _ in range(count):
            if gs.towers < 9:
                gs.towers += 1
                gs.gold += TOWER_GOLD
                tier = ("outer", "inner", "inhibitor")[(gs.towers - 1) // 3]
                self.log("tower", gs, f"{self.tag(gs)} destroy an {tier} tower")
            elif gs.inhibs < 3:
                gs.inhibs += 1
                gs.gold += 50
                self.log("inhibitor", gs, f"{self.tag(gs)} break an inhibitor")
                return

    def can_end(self, gs: GameSide, margin: int) -> bool:
        if gs.inhibs < 1:
            return False
        buffed = gs.baron_until >= self.minute or gs.elder_until >= self.minute
        return buffed or margin >= 4 or (self.minute >= 38 and self.rng.chance(0.4))

    # ---------- fights ----------

    def fight(self, reason: str) -> GameSide:
        sb, sr = self.strength(self.blue), self.strength(self.red)
        late = 1.0 if self.minute < 35 else 1.25  # late fights are decided harder
        p_blue = logistic((sb - sr) * late / FIGHT_SCALE)
        winner = self.blue if self.rng.chance(p_blue) else self.red
        loser = self.other(winner)
        edge = abs(sb - sr) / FIGHT_SCALE
        won = min(5, 1 + self.rng.int(3) + (1 if edge > 0.6 else 0) + (1 if self.rng.chance(0.25) else 0))
        lost = min(won - 1, self.rng.int(3)) if won > 1 else 0
        self.teamfight_kills(winner, won)
        self.teamfight_kills(loser, lost)
        ace = won >= 5
        where = {"dragon": "at the dragon pit", "baron": "around Baron", "elder": "at the Elder Dragon"}.get(reason, "in the river")
        text = f"Teamfight {where}: {self.tag(winner)} win it {won} for {lost}" + (" and ACE" if ace else "")
        self.log("teamfight", winner, text)

        if reason == "baron" and self.rng.chance(0.8):
            winner.barons += 1
            winner.baron_until = self.minute + 3
            self.baron_at = self.minute + 6
            self.log("baron", winner, f"{self.tag(winner)} take Baron Nashor")
        elif reason in ("dragon", "elder") and self.rng.chance(0.85):
            self.take_dragon(winner)
        push = 1 + (2 if winner.baron_until >= self.minute else 0) + (2 if winner.elder_until >= self.minute else 0)
        push += 1 if won - lost >= 3 else 0
        if self.minute >= 15:
            self.destroy_towers(winner, push)
            if self.can_end(winner, won - lost):
                self.winner = winner
        return winner

    def teamfight_kills(self, gs: GameSide, count: int) -> None:
        enemy = self.other(gs)
        for _ in range(count):
            kw = {r: ROLE_KILLS[r] * CLASS_KILLS.get(self.cat.champions[gs.picks[r]].cls, 1.0) for r in ROLES}
            killer = self.weighted(kw)
            victim = self.weighted(dict(ROLE_DEATHS))
            helpers = [r for r in ROLES if r != killer and self.rng.chance(ROLE_ASSIST[r])]
            self.kill(gs, killer, victim, helpers, quiet=True)

    def midgame_minute(self) -> None:
        m = self.minute
        objective = None
        if m >= self.baron_at:
            objective = "baron"
        elif self.elder_at is not None and m >= self.elder_at:
            objective = "elder"
        elif m >= self.dragon_at:
            objective = "dragon"
        chance = FIGHT_CHANCE[0] if objective else FIGHT_CHANCE[1]
        if self.rng.chance(chance):
            self.fight(objective or "skirmish")
            return
        if objective in ("dragon", "elder") and self.rng.chance(0.35):
            self.take_dragon(self.contest(("JNG", "BOT", "SUP", "MID"), self.tactic_bonus("dragon")))
        elif objective == "baron" and self.rng.chance(0.15):
            gs = self.contest(("JNG", "MID", "TOP"), self.tactic_bonus("baron"))
            gs.barons += 1
            gs.baron_until = m + 3
            self.baron_at = m + 6
            self.log("baron", gs, f"{self.tag(gs)} sneak Baron Nashor")
        lead = self.blue.gold - self.red.gold
        ahead = self.blue if lead > 0 else self.red
        if self.rng.chance(0.06 + min(0.2, abs(lead) / 30000)):
            self.destroy_towers(ahead, 1)

    # ---------- the game ----------

    def income(self) -> None:
        base = 1700 + min(600, self.minute * 18)
        self.blue.gold += base
        self.red.gold += base
        if self.minute > 14:
            drift = (self.strength(self.blue) - self.strength(self.red)) * DRIFT_GOLD
            self.blue.gold += drift / 2
            self.red.gold -= drift / 2

    def play(self) -> GameSide:
        while self.winner is None:
            self.minute += 1
            self.income()
            if self.minute <= 14:
                self.laning_minute()
                self.early_objectives()
            else:
                self.midgame_minute()
            self.gold_diff.append(int(self.blue.gold - self.red.gold))
            if self.minute >= 55 and self.winner is None:
                self.blue.inhibs = max(self.blue.inhibs, 1)
                self.red.inhibs = max(self.red.inhibs, 1)
                self.blue.elder_until = self.red.elder_until = self.minute
                self.fight("elder")
        winner = self.winner
        self.second = max(self.second + 20, self.minute * 60 + 30)
        self.events.append(Event(t=self.second, kind="nexus", side=winner.side,
                                 text=f"{self.tag(winner)} destroy the Nexus!",
                                 score=(self.blue.kills, self.red.kills), gold=int(self.blue.gold - self.red.gold)))
        return winner

    # ---------- the record ----------

    def lines(self, gs: GameSide, won: bool) -> list[PlayerLine]:
        minutes = self.second / 60
        out = []
        team_damage = minutes * 2700 * (1 + (gs.gold - self.other(gs).gold) / 60000)
        dmg_w = {r: ROLE_DAMAGE[r] * CLASS_DAMAGE.get(self.cat.champions[gs.picks[r]].cls, 1.0) for r in ROLES}
        dmg_total = sum(dmg_w.values())
        lane_of = {"TOP": "top", "MID": "mid", "BOT": "bot", "SUP": "bot", "JNG": None}
        for role in ROLES:
            st = gs.stats[role]
            lane = lane_of[role]
            sign = 1 if gs.side == "blue" else -1
            edge = sign * self.lane_diff(lane) / 30 if lane else (gs.power["JNG"] - self.other(gs).power["JNG"]) / 30
            cs = ROLE_CS[role] * minutes * (1 + max(-0.15, min(0.15, edge))) * (0.95 + self.rng.next() * 0.1)
            gold = gs.gold * ROLE_GOLD[role] + st["k"] * 150
            damage = team_damage * dmg_w[role] / dmg_total * (0.85 + self.rng.next() * 0.3)
            perf = 6.0 + (0.38 * st["k"] + 0.2 * st["a"] - 0.42 * st["d"]) * min(1.3, 30 / max(minutes, 15))
            perf += 0.7 if won else -0.2
            # How the matchup looked on paper nudges the rating, the line itself decides it.
            perf += max(-0.8, min(0.8, (gs.power[role] - self.other(gs).power[role]) / 15))
            out.append(PlayerLine(
                player=gs.lineup[role], team=gs.team, role=role, champion=gs.picks[role], kills=int(st["k"]),
                deaths=int(st["d"]), assists=int(st["a"]), cs=int(cs), gold=int(gold), damage=int(damage),
                rating=round(max(1.0, min(10.0, perf)), 1),
            ))
        return out


def simulate(cat: Catalog, career: Career, blue: GameSide, red: GameSide, rng: Rng, number: int,
             bans: tuple[list[str], list[str]]) -> GameResult:
    game = Game(cat, career, blue, red, rng, number)
    winner = game.play()
    lines = game.lines(blue, winner is blue) + game.lines(red, winner is red)
    winners = [ln for ln in lines if ln.team == winner.team]
    mvp = max(winners, key=lambda ln: ln.rating).player
    record = GameRecord(
        number=number, blue=blue.team, red=red.team, winner=winner.team, duration=game.second,
        kills=[blue.kills, red.kills], gold=[int(blue.gold), int(red.gold)], towers=[blue.towers, red.towers],
        dragons=[len(blue.dragons), len(red.dragons)], barons=[blue.barons, red.barons],
        blue_picks=dict(blue.picks), red_picks=dict(red.picks), blue_bans=list(bans[0]), red_bans=list(bans[1]),
        players=lines, mvp=mvp,
    )
    return GameResult(record=record, events=game.events, gold_diff=game.gold_diff)
