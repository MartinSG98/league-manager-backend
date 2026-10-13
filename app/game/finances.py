"""Moving money between the salary budget and the bank, the way Football Manager lets a manager
trade wage budget for transfer budget.

The owners pay the salary budget out week by week, and whatever the payroll leaves of it goes to the
bank (engine._weekly), until the board sets the next budget when the season ends. So every thousand
of the budget is worth a thousand for each week still to come: cutting the budget by X puts
X x weeks left / 52 in the bank now, and raising it by X costs as much. The club ends the season
with the same money either way; the manager only chooses when it is there and what it can buy.

The budget never drops below the contracts it already pays, and the bank never goes below zero.
Bonuses the board pays as a share of the budget go by the budget it set, not the moved one."""

from dataclasses import dataclass
from datetime import date
from math import ceil, floor

from app.game import calendar, contracts
from app.game.errors import IllegalAction
from app.game.state import Career

WEEKS = 52
STEP = 10  # budgets move in steps of 10k, like the board sets them


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


def limits(career: Career) -> Limits:
    team = career.teams[career.team]
    weeks = max(1, min(WEEKS, ceil((budget_ends(career) - career.day).days / 7)))
    low = min(team.budget, contracts.committed(career, team))
    high = team.budget + max(0, int(team.cash * WEEKS / weeks))
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
        raise IllegalAction(f"The bank cannot pay for a budget above {lim.high}k")
    change = floor((team.budget - budget) * lim.rate + 0.5)  # halves up, as the client rounds its preview
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
            "set": team.budget + team.budget_moved, "moved": team.budget_moved}
