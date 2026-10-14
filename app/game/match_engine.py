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

Team areas from training (see training.py) shift all of this a little: the early game adds power
in lanes and ganks, objective control wins contested objectives, teamfighting wins fights, macro
turns power into gold and towers after laning, and closing decides how often a team well ahead
gets greedy and throws a fight away. Each side may also run one set play (see plays.py) at its
minute of the game. When both call the same play they run into each other: one clash, which the
better prepared side wins big, or which cancels out when neither is.

The result is a GameRecord with a stat line per player, and a timeline with the gold
difference every minute for the match-day playback."""

import math
from collections import Counter
from dataclasses import dataclass, field

from app.game import roster, training
from app.game.catalog import ROLES, Catalog
from app.game.champ_select import champion_power, composition_modifier, focus_bias, lane_edge
from app.game.plays import PLAYS, SetPlay, manager_edge
from app.game.plays import chance as play_chance
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
BUFFS = {"baron": 5.0, "elder": 7.0}
# Power a Soul gives, per element: fitted with scripts/simulate.py --souls so that the side with
# each Soul wins about as often as in real games (SOUL_TARGET there).
SOUL_POWER = {"Infernal": 1.5, "Mountain": 3.5, "Ocean": 2.0, "Cloud": 8.0, "Hextech": 2.5, "Chemtech": 1.5}
KILL_GOLD = 300
TOWER_GOLD = 550  # shared by the team, plates included
# Team areas: power for a team at 20 against one at 10 (half that at 15, and minus below 10).
EARLY_POWER = 1.5  # strength in the first 14 minutes
LANE_POWER = 1.2  # lane power, so lane gold and ganks
OBJECTIVE_EDGE = 0.5  # logistic edge in a contested objective
FIGHT_POWER = 2.0
MACRO_POWER = 1.5  # in the gold drift after laning
THROW_LEAD = 3000  # gold lead from which a team may throw
THROW_BASE = 0.085  # chance a team that far ahead throws a fight it would have won, at closing 0
THROW_PER_POINT = 0.0045  # less per point of closing
HYPE_CHANCE = 0.6  # a fight without a multi-kill still gets a caster's call this often
MULTI_KILLS = {3: "TRIPLE KILL", 4: "QUADRA KILL", 5: "PENTAKILL"}
# What a caster shouts when a champion of each class wins a fight: {p} the player, {ult} their
# ultimate, {n} how many it caught, {victim} someone on the losing side.
HYPE = {
    "Tank": ("{p} with a {n}-man {ult}!", "{p} flashes in and catches {n} with {ult}!"),
    "Mage": ("{p} with a {n}-man {ult}!", "{p} lands {ult} on {n} of them!"),
    "Fighter": ("{p} flanks with {ult} and splits the fight in half!", "{p} dives the backline with {ult}!"),
    "Assassin": ("{p} jumps on {victim} and deletes them!", "{p} resets through the whole fight!"),
    "Marksman": ("{p} kites back and deals all the damage!", "{p} cleans it up with {ult}!"),
    "Enchanter": ("{p}'s {ult} turns the fight around!", "{p} saves the carry with {ult}!"),
}
CLASH_EVEN = 0.35  # chance two equally prepared sides calling the same play cancel each other out
CLASH_EDGE = 1.5  # how much a better chance to make the play work tilts a clash

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


def throw_odds(closing: float) -> float:
    """Chance a team well ahead throws a fight it would have won, by its closing (1-20)."""
    return max(0.005, THROW_BASE - THROW_PER_POINT * closing)


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
    soul: str | None = None  # the element of the Soul, once the side has it
    grubs: int = 0
    barons: int = 0
    baron_until: int = -1
    elder_until: int = -1
    stats: dict[str, dict[str, float]] = field(default_factory=dict)
    skills: dict[str, float] = field(default_factory=dict)  # team areas, 1..20
    play: str | None = None  # the set play called for this game
    play_chance: float = 0.0
    play_ok: bool | None = None  # None until it runs
    sure: dict[str, int] = field(default_factory=dict)  # objective -> contests a set play has decided
    next_fight: float = 0.0  # power for the next fight only
    swap_lane: str | None = None
    splitting: bool = False
    fights_won: int = 0
    throws: int = 0

    def skill(self, area: str) -> float:
        """-0.9..+1.0: how far the team area is from an average 10."""
        return (self.skills.get(area, 10.0) - 10) / 10


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
            tactics: Tactics, play: str | None = None) -> GameSide:
    gs = GameSide(side=side, team=team, lineup=lineup, picks=picks, tactics=tactics, play=play)
    if team in career.teams:
        gs.skills = dict(career.teams[team].skills)
    for role in ROLES:
        pid = lineup[role]
        state = career.players[pid]
        rating = roster.overall(cat, career, pid)
        gs.power[role] = rating + champion_power(cat, career, pid, picks[role], role) + training.condition(state)
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
        self.drakes: list[str] = []  # every elemental drake taken in the game, by either side
        self.herald_done = False
        self.winner: GameSide | None = None
        self.second = 0
        self.gold15 = 0
        for gs in (blue, red):
            if gs.play in PLAYS:
                enemy = self.other(gs)
                learned = career.teams[gs.team].plays.get(gs.play, 0.0) if gs.team in career.teams else 100.0
                area = PLAYS[gs.play].area
                gs.play_chance = play_chance(PLAYS[gs.play], learned, gs.skills.get(area, 10.0),
                                             enemy.skills.get(area, 10.0), gs.early, manager_edge(career, gs.team))
            else:
                gs.play = None

    # ---------- helpers ----------

    def other(self, gs: GameSide) -> GameSide:
        return self.red if gs is self.blue else self.blue

    def strength(self, gs: GameSide) -> float:
        m = self.minute
        phase = 1.0 if m <= 14 else (-1.0 if m >= 32 else 1 - 2 * (m - 14) / 18)
        value = gs.base + gs.early * phase
        if m <= 14:
            value += EARLY_POWER * gs.skill("early_game")
        if m < 25:
            value += min(6, gs.grubs) * 0.12
        value += len(gs.dragons) * 0.35 + (SOUL_POWER[gs.soul] if gs.soul else 0)
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
        early = LANE_POWER * gs.skill("early_game") if self.minute <= 14 else 0.0
        if lane == "bot":
            return (gs.power["BOT"] + 0.6 * gs.power["SUP"]) / 1.6 + early
        return gs.power[roles[0]] + early

    def lane_diff(self, lane: str) -> float:
        main = self.LANES[lane][0]
        edge = lane_edge(self.cat, self.cat.champions[self.blue.picks[main]], self.cat.champions[self.red.picks[main]])
        diff = self.lane_power(self.blue, lane) - self.lane_power(self.red, lane) + edge
        if self.minute <= 10:
            # A lane swap that worked takes the worst matchup out of the game for ten minutes.
            if self.blue.swap_lane == lane:
                diff = max(diff, 0.0)
            if self.red.swap_lane == lane:
                diff = min(diff, 0.0)
        return diff

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

    def contest(self, roles: tuple[str, ...], bonus_blue: float = 0.0, objective: str | None = None) -> GameSide:
        if objective is not None:
            for gs in (self.blue, self.red):
                if gs.sure.get(objective, 0) > 0:
                    gs.sure[objective] -= 1
                    return gs
        b = sum(self.blue.power[r] for r in roles) / len(roles)
        r = sum(self.red.power[x] for x in roles) / len(roles)
        edge = (b - r) / 3.5 + (self.blue.gold - self.red.gold) / 2500 + bonus_blue
        edge += OBJECTIVE_EDGE * (self.blue.skill("objectives") - self.red.skill("objectives"))
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
        kind = self.next_drake()
        self.drakes.append(kind)
        gs.dragons.append(kind)
        if len(gs.dragons) >= 4:
            gs.soul = kind
            self.elder_at = self.minute + 6
            self.dragon_at = 999
            self.log("soul", gs, f"{self.tag(gs)} claim the {kind} Soul")
        else:
            self.dragon_at = self.minute + 5
            self.log("dragon", gs, f"{self.tag(gs)} take the {kind} Drake ({len(gs.dragons)})")

    def next_drake(self) -> str:
        """As on the Rift: the first two drakes are two different elements and the third a third one.
        The Rift then takes that element's form, and every drake after it, and the Soul, is the same."""
        if len(self.drakes) >= 3:
            return self.drakes[2]
        return self.rng.pick([d for d in DRAGONS if d not in self.drakes]) or DRAGONS[0]

    def early_objectives(self) -> None:
        m = self.minute
        if m in (6, 10):
            gs = self.contest(("JNG", "TOP"), self.tactic_bonus("baron"), objective="grubs")
            gs.grubs += 3
            gs.gold += 150
            self.log("grubs", gs, f"{self.tag(gs)} take the Voidgrubs")
        if m >= self.dragon_at and self.elder_at is None:
            if self.rng.chance(0.3):
                self.fight(reason="dragon")
            else:
                self.take_dragon(self.contest(("JNG", "BOT", "SUP", "MID"), self.tactic_bonus("dragon"), "dragon"))
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
        # A team good at closing ends with a smaller margin; a poor one needs a bigger one.
        needed = 4 - round(gs.skill("closing") * 1.5)
        return buffed or margin >= needed or (self.minute >= 38 and self.rng.chance(0.4))

    def throw_chance(self, gs: GameSide) -> float:
        return throw_odds(gs.skills.get("closing", 10.0))

    # ---------- fights ----------

    def fight(self, reason: str) -> GameSide:
        sb = self.strength(self.blue) + FIGHT_POWER * self.blue.skill("teamfighting") + self.blue.next_fight
        sr = self.strength(self.red) + FIGHT_POWER * self.red.skill("teamfighting") + self.red.next_fight
        self.blue.next_fight = self.red.next_fight = 0.0
        late = 1.0 if self.minute < 35 else 1.25  # late fights are decided harder
        p_blue = logistic((sb - sr) * late / FIGHT_SCALE)
        winner = self.blue if self.rng.chance(p_blue) else self.red
        lead = self.blue.gold - self.red.gold
        if self.minute >= 18 and abs(lead) >= THROW_LEAD:
            leader = self.blue if lead > 0 else self.red
            if winner is leader and self.rng.chance(self.throw_chance(leader)):
                winner = self.other(leader)
                leader.throws += 1
                where = {"baron": "at Baron", "elder": "at the Elder Dragon", "dragon": "at the dragon"}.get(reason, "")
                self.log("throw", leader, f"{self.tag(leader)} get greedy {where or 'with a big lead'} and throw the fight away")
        loser = self.other(winner)
        winner.fights_won += 1
        edge = abs(sb - sr) / FIGHT_SCALE
        won = min(5, 1 + self.rng.int(3) + (1 if edge > 0.6 else 0) + (1 if self.rng.chance(0.25) else 0))
        lost = min(won - 1, self.rng.int(3)) if won > 1 else 0
        killers = self.teamfight_kills(winner, won)
        self.teamfight_kills(loser, lost)
        call = self.highlight(winner, loser, won, killers)
        if call:
            self.log("highlight", winner, call)
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

    def teamfight_kills(self, gs: GameSide, count: int) -> Counter:
        """The kills one side takes in a fight. Returns how many each role got."""
        killers: Counter = Counter()
        for _ in range(count):
            kw = {r: ROLE_KILLS[r] * CLASS_KILLS.get(self.cat.champions[gs.picks[r]].cls, 1.0) for r in ROLES}
            killer = self.weighted(kw)
            victim = self.weighted(dict(ROLE_DEATHS))
            helpers = [r for r in ROLES if r != killer and self.rng.chance(ROLE_ASSIST[r])]
            self.kill(gs, killer, victim, helpers, quiet=True)
            killers[killer] += 1
        return killers

    def highlight(self, win: GameSide, lose: GameSide, won: int, killers: Counter) -> str | None:
        """A caster's call for the fight that was just won: a multi-kill, or the play that won it."""
        if killers:
            role, count = killers.most_common(1)[0]
            if count >= 3:
                champ = self.cat.champions[win.picks[role]]
                return f"{MULTI_KILLS[min(count, 5)]} for {self.star(win, role)} on {champ.name}!"
        if won == 0 or not self.rng.chance(HYPE_CHANCE):
            return None
        engage = [r for r in ROLES if self.cat.champions[win.picks[r]].cls in ("Tank", "Mage")]
        if engage and self.rng.chance(0.6):
            role = self.rng.pick(engage) or engage[0]
        else:
            role = killers.most_common(1)[0][0] if killers else (self.rng.pick(ROLES) or "MID")
        champ = self.cat.champions[win.picks[role]]
        line = self.rng.pick(HYPE.get(champ.cls, HYPE["Fighter"])) or HYPE["Fighter"][0]
        victim = self.cat.players[lose.lineup[self.rng.pick(ROLES) or "MID"]].name
        return line.format(p=self.star(win, role), ult=champ.ult or "their ultimate",
                           n=min(5, max(2, won + self.rng.int(2))), victim=victim)

    def star(self, gs: GameSide, role: str) -> str:
        """A player's name the way a caster shouts it."""
        return self.cat.players[gs.lineup[role]].name.upper()

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
            self.take_dragon(self.contest(("JNG", "BOT", "SUP", "MID"), self.tactic_bonus("dragon"), "dragon"))
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
        for gs in (self.blue, self.red):
            if gs.splitting and self.rng.chance(0.12):
                self.log("note", gs, f"{self.tag(gs)}'s split push takes another tower")
                self.destroy_towers(gs, 1)

    # ---------- the game ----------

    def income(self) -> None:
        base = 1700 + min(600, self.minute * 18)
        self.blue.gold += base
        self.red.gold += base
        if self.minute > 14:
            macro = MACRO_POWER * (self.blue.skill("macro") - self.red.skill("macro"))
            drift = (self.strength(self.blue) - self.strength(self.red) + macro) * DRIFT_GOLD
            self.blue.gold += drift / 2
            self.red.gold -= drift / 2

    # ---------- set plays ----------

    def run_plays(self) -> None:
        due = [gs for gs in (self.blue, self.red)
               if gs.play and gs.play_ok is None and self.minute >= PLAYS[gs.play].minute and self.winner is None]
        if len(due) == 2 and self.blue.play == self.red.play:
            self.clash()
            return
        for gs in due:
            self.run_play(gs)

    def clash(self) -> None:
        """Both sides run the same play at the same moment: one fight instead of two plays a second
        apart. The side likelier to make the play work is likelier to win it, and the winner takes
        a big swing; two sides about as well prepared may cancel each other out."""
        play = PLAYS[self.blue.play or ""]
        margin = self.blue.play_chance - self.red.play_chance
        if self.rng.chance(CLASH_EVEN * max(0.0, 1 - abs(margin) / 0.3)):
            self.blue.play_ok = self.red.play_ok = False
            self.clash_even(play)
            return
        win = self.blue if self.rng.chance(max(0.1, min(0.9, 0.5 + CLASH_EDGE * margin))) else self.red
        lose = self.other(win)
        win.play_ok, lose.play_ok = True, False
        self.clash_won(play, win, lose)

    def rout(self, win: GameSide, killers: tuple[str, ...], victims: tuple[str, ...]) -> bool:
        """Several kills in one fight, for one line of the log. True when they include first blood."""
        fresh = not self.first_blood
        self.first_blood = True  # the clash line says so, rather than a line of its own
        for killer, victim in zip(killers, victims):
            self.kill(win, killer, victim, list(killers), quiet=True)
        return fresh

    def clash_won(self, play: SetPlay, win: GameSide, lose: GameSide) -> None:
        w, lo = self.tag(win), self.tag(lose)
        first, towers = False, 0
        if play.id == "invade":
            first = self.rout(win, ("JNG", "MID", "TOP"), tuple(self.rng.shuffle(("JNG", "SUP", "MID", "TOP"))[:3]))
            win.gold += 300
            text = f"the two teams meet in the jungle at level 1 and {w} win it 3 for 0"
        elif play.id == "fnatic_bush":
            first = self.rout(win, ("SUP", "JNG"), ("SUP", "BOT"))
            win.gold += 200
            text = f"{w} spot the other ambush first and collapse on {lo}'s bot lane"
        elif play.id == "lane_swap":
            win.gold += 600
            lose.gold -= 300
            text = f"{w} read the swap, swap back first and take {lo}'s plates"
        elif play.id == "grubs":
            win.sure["grubs"] = 2
            first = self.rout(win, ("JNG", "MID"), ("JNG", "SUP"))
            text = f"{w} win the fight at the pit and own both Voidgrub spawns"
        elif play.id == "dive":
            first = self.rout(win, ("BOT", "JNG", "MID", "SUP"), ("JNG", "MID", "SUP", "BOT"))
            towers = 1
            text = f"both dives crash into the bot lane at once and {w} turn it into a 4 for 0"
        elif play.id == "drakes":
            win.sure["dragon"] = 2
            first = self.rout(win, ("JNG",), ("SUP",))
            text = f"{w} catch {lo}'s warding party and own the next two dragons"
        elif play.id == "pick":
            first = self.rout(win, ("JNG", "SUP"), ("SUP", "MID"))
            win.next_fight += 5.0
            text = f"{w} sweep {lo}'s trap and catch two on the way out"
        elif play.id == "baron_bait":
            win.next_fight += 10.0
            text = f"both teams posture around Baron and {lo} walk into {w}'s choke"
        else:  # split_push
            win.splitting = True
            first = self.rout(win, ("JNG", "MID"), ("TOP", "BOT"))
            towers = 3
            text = f"{w} win the base race: {lo}'s side laners are caught and three towers fall"
        self.log("play", win, f"Set play clash, {play.name}: both teams call it, and {text}"
                              f"{', with first blood' if first else ''}")
        if towers:
            self.destroy_towers(win, towers)
        if play.id == "baron_bait":
            self.fight("baron" if self.minute >= self.baron_at else "skirmish")

    def clash_even(self, play: SetPlay) -> None:
        first = False
        if play.id == "invade":
            text = "they meet in the river at level 1 and back off"
        elif play.id == "fnatic_bush":
            self.blue.gold -= 250
            self.red.gold -= 250
            text = "both sit in a lane brush, nobody walks past, and both reach their lanes late"
        elif play.id == "lane_swap":
            text = "both duos swap and the lanes meet as they would have anyway"
        elif play.id == "grubs":
            text = "both set up the pit and the Voidgrubs are up for grabs"
        elif play.id == "dive":
            first = self.rout(self.blue, ("JNG", "MID"), ("BOT", "SUP"))
            self.rout(self.red, ("JNG", "MID"), ("BOT", "SUP"))
            text = "both dives hit the bot lane at once and it ends 2 for 2"
        elif play.id == "drakes":
            text = "both clear the vision around the pit and the next dragon is a straight fight"
        elif play.id == "pick":
            text = "the deep wards find each other and nobody is caught"
        elif play.id == "baron_bait":
            text = "both posture around Baron and it comes down to a straight fight"
        else:  # split_push
            text = "both split the map and trade a tower each"
        self.log("play", None, f"Set play clash, {play.name}: both teams call it and cancel each other out: "
                               f"{text}{', with first blood' if first else ''}")
        if play.id == "split_push":
            self.destroy_towers(self.blue, 1)
            self.destroy_towers(self.red, 1)
        if play.id == "baron_bait":
            self.fight("baron" if self.minute >= self.baron_at else "skirmish")

    def run_play(self, gs: GameSide) -> None:
        play = PLAYS[gs.play or ""]
        enemy = self.other(gs)
        ok = self.rng.chance(gs.play_chance)
        gs.play_ok = ok
        us, them = self.tag(gs), self.tag(enemy)
        head = f"Set play, {play.name}:"
        if play.id == "invade":
            if ok:
                victim = self.rng.pick(ROLES) or "JNG"
                self.log("play", gs, f"{head} {us} walk into the enemy jungle at level 1 and catch {self.name(enemy, victim)}")
                self.kill(gs, self.rng.pick(("JNG", "MID", "TOP")) or "JNG", victim, ["JNG", "SUP", "MID"])
                gs.gold += 300
            else:
                self.log("play", gs, f"{head} {them} were waiting for the invade and it backfires")
                self.kill(enemy, self.rng.pick(("JNG", "MID", "SUP")) or "JNG", self.rng.pick(("SUP", "JNG")) or "SUP", ["JNG", "SUP"])
        elif play.id == "fnatic_bush":
            if ok:
                victim = "SUP" if self.rng.chance(0.5) else "BOT"
                self.log("play", gs, f"{head} {us} hide in the lane brush and {self.name(enemy, victim)} walks right into it")
                self.kill(gs, self.rng.pick(("JNG", "MID", "SUP")) or "JNG", victim, ["JNG", "SUP", "MID", "BOT"])
                gs.gold += 200
            else:
                gs.gold -= 250
                self.log("play", gs, f"{head} {them} spot the ambush, and {us} reach their lanes late")
        elif play.id == "lane_swap":
            if ok:
                worst = min(("top", "mid", "bot"), key=lambda ln: self.lane_diff(ln) * (1 if gs is self.blue else -1))
                gs.swap_lane = worst
                gs.gold += 300
                self.log("play", gs, f"{head} {us} swap lanes to dodge the {worst} lane matchup and take early plates")
            else:
                gs.gold -= 300
                self.log("play", gs, f"{head} {them} mirror the lane swap and {us} lose their plates")
        elif play.id == "grubs":
            winner = gs if ok else enemy
            winner.sure["grubs"] = 2
            text = f"{us} own the jungle and set up both Voidgrub spawns" if ok else f"{them} read the setup and take the grubs pit"
            self.log("play", gs, f"{head} {text}")
        elif play.id == "dive":
            if ok:
                self.log("play", gs, f"{head} {us} dive the bot lane under tower")
                self.kill(gs, "JNG", "BOT", ["JNG", "MID", "SUP"])
                self.kill(gs, "MID", "SUP", ["JNG", "MID", "SUP"])
                self.destroy_towers(gs, 1)
            else:
                self.log("play", gs, f"{head} the tower dive goes wrong for {us}")
                self.kill(enemy, "BOT", "JNG", ["BOT", "SUP"])
                self.kill(enemy, "SUP", "SUP", ["BOT", "SUP"])
        elif play.id == "drakes":
            if ok:
                gs.sure["dragon"] = 2
                self.log("play", gs, f"{head} {us} clear the vision around the pit and set up the next two dragons")
            else:
                enemy.sure["dragon"] = 1
                self.log("play", gs, f"{head} {them} catch the warding party and take the next dragon")
        elif play.id == "pick":
            if ok:
                victim = "MID" if self.rng.chance(0.5) else "BOT"
                self.log("play", gs, f"{head} {us} catch {self.name(enemy, victim)} in a hidden flank")
                self.kill(gs, self.rng.pick(("JNG", "SUP", "MID")) or "JNG", victim, ["JNG", "SUP"])
                gs.next_fight += 5.0
            else:
                self.log("play", gs, f"{head} {them} sweep the trap and pick off {self.name(gs, 'SUP')}")
                self.kill(enemy, "JNG", "SUP", ["JNG", "MID"])
                enemy.next_fight += 3.0
        elif play.id == "baron_bait":
            if ok:
                gs.next_fight += 8.0
                self.log("play", gs, f"{head} {us} start Baron and {them} walk into the choke")
            else:
                enemy.next_fight += 4.0
                self.log("play", gs, f"{head} {them} do not take the bait and collapse on Baron")
            self.fight("baron" if self.minute >= self.baron_at else "skirmish")
        elif play.id == "split_push":
            if ok:
                gs.splitting = True
                self.log("play", gs, f"{head} {us} split the map 1-3-1 and towers start to fall")
                self.destroy_towers(gs, 2)
            else:
                self.log("play", gs, f"{head} {them} collapse on the side lane and catch {self.name(gs, 'TOP')}")
                self.kill(enemy, "JNG", "TOP", ["JNG", "MID"])
                self.destroy_towers(enemy, 1)

    def play(self) -> GameSide:
        while self.winner is None:
            self.minute += 1
            self.income()
            self.run_plays()
            if self.winner is not None:
                break
            if self.minute <= 14:
                self.laning_minute()
                self.early_objectives()
            else:
                self.midgame_minute()
            self.gold_diff.append(int(self.blue.gold - self.red.gold))
            if self.minute == 15:
                self.gold15 = self.gold_diff[-1]
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
            perf = 5.5 + (0.3 * st["k"] + 0.12 * st["a"] - 0.35 * st["d"]) * min(1.15, 28 / max(minutes, 15))
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
        players=lines, mvp=mvp, gold15=game.gold15 if game.minute >= 15 else game.gold_diff[-1],
        leads=[max(0, max(game.gold_diff)), max(0, -min(game.gold_diff))],
        fights=[blue.fights_won, red.fights_won], throws=[blue.throws, red.throws],
        plays={gs.team: gs.play for gs in (blue, red) if gs.play},
        play_results={gs.team: bool(gs.play_ok) for gs in (blue, red) if gs.play and gs.play_ok is not None},
    )
    return GameResult(record=record, events=game.events, gold_diff=game.gold_diff)
