# 0017. Moving money between the salary budget and the bank

Date: 2026-10-13
Status: Accepted, amended 2026-10-14

## Context

The board sets a salary budget every off-season and puts money in the bank for transfers (ADR 0013). The manager could not change how the two are split. In Football Manager a manager can trade wage budget for transfer budget with a slider, for example to afford a fee by keeping wages down, or to pay a star more by spending less on fees. The manager asked for the same.

In this game the bank already holds the transfer money: fees come out of it, and the screens call it "Bank (transfer funds)". The salary budget is also money the owners pay out week by week: what the payroll leaves of it goes to the bank every Monday. A plain one-to-one exchange would therefore create money. Cutting the budget late in the season would put the full amount in the bank, while the club would lose only a few weeks of what it would have banked anyway, and the board sets a new budget after Worlds regardless.

## Decision

- **What moves.** The manager moves money between the salary budget and the bank. There is no separate transfer budget.
- **The rate.** A thousand of the budget is worth a thousand for every week left until the board sets the next budget (when Worlds ends), divided by 52. Cutting the budget by X puts X × weeks left / 52 in the bank now. Raising it costs as much. Over the rest of the season the club ends up with the same money either way: the manager only chooses when it is there and what it can buy.
- **Limits.** The budget never drops below the contracts it already pays (next season's contracts during the off-season), and the bank never goes below zero. The client moves the budget in steps of 10k, which the view publishes.
- **When.** Any time after the draft. Not while the board is waiting to meet the manager, because the meeting itself changes the budget.
- **The board.** The budget the board set is remembered (`TeamState.budget_moved`), and the sponsor payments that come as a share of the budget are paid on it, so moving money does not raise them. A new budget after Worlds clears the move.
- **AI clubs** do not adjust their budgets.

## Consequences

The slider is a timing tool, not a source of money: a manager who needs a fee now can take it from the salaries they are not paying, and one who wants to pay a player more can buy budget room with money from the bank. Early in the season the rate is close to one to one, and late in the season budget room is cheap and worth little in the bank. Exact figures come out of the API (`budget_adjust` in the career view) so the client never computes limits on its own.

## Amendment, 2026-10-14

AI clubs move money the same way, so a rich club is not stuck behind a tight budget while the manager is not. When a salary does not fit, the club raises its budget and the bank pays at the same rate; when a fee is more than the bank spares, the club cuts wage budget it will not use (`transfers._fund`, through `finances.move`). It keeps 30 percent of its bank after a deal, as it did before, and moves nothing while in debt. The manager's own budget still moves only by the manager's hand, even when the assistant fills an empty role.
