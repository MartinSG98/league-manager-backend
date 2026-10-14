"""Moving money between the salary budget and the bank, the way Football Manager lets a manager
trade wage budget for transfer budget.

The owners pay the salary budget out week by week, and whatever the payroll leaves of it goes to the
bank (engine._weekly), until the board sets the next budget when the season ends. So every thousand
of the budget is worth a thousand for each week still to come: cutting the budget by X puts
X x weeks left / 52 in the bank now, and raising it by X costs as much. The club ends the season
with the same money either way; the manager only chooses when it is there and what it can buy.

The budget never drops below the contracts it already pays, and the bank never goes below what fees
already agreed will take out of it. Bonuses the board pays as a share of the budget go by the budget
it set, not the moved one.

Debt. The bank can still go below zero: a release pays half the contract left, and prize money or
sponsors do not always cover a payroll above the budget. The owners no longer clear it when the
season starts. While the club owes money:
- the board will not pay for transfers, so no bids, and no money moves into the salary budget;
- the board loses a point of confidence every week, two once the debt passes a quarter of the
  salary budget;
- past that quarter the board cuts every wage by 10 percent for the rest of the contracts, at most
  every eight weeks. Every player loses 20 morale, and some want to leave, the more the bigger the name;
- the next transfer grant pays off the debt before anything is left for transfers.
Cutting the salary budget is the quickest way out: it puts money in the bank at once."""

from dataclasses import dataclass
from datetime import date
from math import ceil, floor

from app.game import calendar, contracts, transfers
from app.game.catalog import Catalog
from app.game.errors import IllegalAction
from app.game.rng import Rng
from app.game.state import Career, InboxMessage, TeamState

WEEKS = 52
STEP = 10  # budgets move in steps of 10k, like the board sets them
DEEP_DEBT = 0.25  # debt as a share of the salary budget from which the board cuts wages
DEBT_CONFIDENCE = (1, 2)  # confidence lost a week in debt, and in deep debt
WAGE_CUT = 0.10  # off every wage when the board cuts them
CUT_MORALE = 20  # morale every player loses at a wage cut
CUT_EVERY = 8  # weeks before the board cuts wages again


@dataclass(frozen=True)
class Limits:
    low: int
    high: int
    weeks: int

    @property
    def rate(self) -> float:
        """What a thousand of the budget is worth in the bank today."""
        return self.weeks / WEEKS


def budget_ends(career: Career) -> date:
    """The day the board sets the next salary budget: when Worlds ends for the season this budget is for."""
    season = career.season + 1 if career.phase == "offseason" else career.season
    worlds = next(e for e in calendar.INTERNATIONALS if e.id == "WORLDS")
    return date(season, *worlds.end)


def weeks_left(career: Career) -> int:
    """Weeks until the board sets the next salary budget: what a thousand of it is worth, in 52nds."""
    return max(1, min(WEEKS, ceil((budget_ends(career) - career.day).days / 7)))


def limits(career: Career) -> Limits:
    team = career.teams[career.team]
    weeks = weeks_left(career)
    low = min(team.budget, contracts.committed(career, team))
    high = team.budget + max(0, int(transfers.free_cash(career) * WEEKS / weeks))
    return Limits(low=low, high=high, weeks=weeks)


def adjust(career: Career, budget: int) -> int:
    """Set the salary budget and settle the difference with the bank. Returns what the bank gained."""
    if career.phase == "draft":
        raise IllegalAction("The budget can be moved once the draft is over")
    team = career.teams[career.team]
    lim = limits(career)
    if budget < lim.low:
        raise IllegalAction(f"The budget cannot go below the {lim.low}k your contracts already cost")
    if budget > lim.high:
        if team.cash < 0:
            raise IllegalAction(f"The club is {-team.cash}k in debt: the budget can only go down")
        raise IllegalAction(f"The bank cannot pay for a budget above {lim.high}k")
    return move(career, team, budget)


def move(career: Career, team: TeamState, budget: int) -> int:
    """Set a club's salary budget and settle the difference with its bank, at what a thousand of the
    budget is worth today. Returns what the bank gained. The manager's slider comes through here, and
    so do AI clubs paying for a signing (transfers._fund)."""
    change = floor((team.budget - budget) * weeks_left(career) / WEEKS + 0.5)  # halves up, as the client rounds its preview
    team.cash += change
    team.budget_moved += team.budget - budget
    team.budget = budget
    return change


def view(career: Career) -> dict | None:
    if career.phase == "draft":
        return None
    team = career.teams[career.team]
    lim = limits(career)
    return {"low": lim.low, "high": lim.high, "weeks": lim.weeks, "rate": round(lim.rate, 4), "step": STEP,
            "set": team.budget + team.budget_moved, "moved": team.budget_moved,
            "reserved": transfers.reserved(career), "cut_at": deep_debt(career),
            "wage_cut": career.board.wage_cut.isoformat() if career.board.wage_cut else None}


# ---------- debt ----------


def deep_debt(career: Career) -> int:
    """The debt from which the board cuts wages."""
    return int(DEEP_DEBT * career.teams[career.team].budget)


def _board(career: Career, subject: str, body: str) -> None:
    career.inbox.append(InboxMessage(id=career.next_message, day=career.day, kind="board", subject=subject, body=body))
    career.next_message += 1


def weekly(cat: Catalog, career: Career, rng: Rng) -> None:
    """The board's view of the bank, every Monday after the week's money came in."""
    b = career.board
    if b.sacked:
        return
    team = career.teams[career.team]
    if team.cash >= 0:
        if b.in_debt:
            b.in_debt = False
            _board(career, "The club is out of debt", f"The bank is back at {team.cash}k. The board will fund "
                   "transfers again.")
        return
    debt, deep = -team.cash, deep_debt(career)
    if not b.in_debt:
        b.in_debt = True
        _board(career, "The club is in debt",
               f"The bank is {debt}k below zero. Until it is back above zero the board will not pay for transfers "
               f"and loses confidence every week. If the debt passes {deep}k, a quarter of the salary budget, the "
               "board will cut wages. Cutting the salary budget puts money in the bank at once.")
    b.confidence = max(0, b.confidence - DEBT_CONFIDENCE[debt > deep])
    if debt > deep and (b.wage_cut is None or (career.day - b.wage_cut).days >= CUT_EVERY * 7):
        cut_wages(cat, career, rng)


def cut_wages(cat: Catalog, career: Career, rng: Rng) -> None:
    """The board takes WAGE_CUT off every contract to pay the debt down, and the squad takes it badly."""
    team = career.teams[career.team]
    career.board.wage_cut = career.day
    saved = 0
    unhappy = []
    for pid in team.roster:
        state = career.players[pid]
        if state.contract is not None:
            cut = int(round(state.contract.salary * (1 - WAGE_CUT) / 5) * 5)
            saved += state.contract.salary - cut
            state.contract.salary = cut
        state.morale = max(0, state.morale - CUT_MORALE)
        # The bigger the name, the likelier they want out. The franchise player stays loyal.
        fame = max(0.0, min(1.0, (cat.players[pid].reputation - 40) / 50))
        if pid != team.franchise and not state.unsettled and rng.chance(0.1 + 0.4 * fame):
            state.unsettled = True
            unhappy.append(cat.players[pid].name)
    body = (f"The club owes {-team.cash}k. To pay it down the board cuts every wage by {int(WAGE_CUT * 100)} percent "
            f"for the rest of the contracts, which saves {saved}k a season. The whole squad loses morale.")
    if unhappy:
        body += f" {', '.join(unhappy)} {'want' if len(unhappy) > 1 else 'wants'} to leave."
    _board(career, "The board cuts wages", body)
