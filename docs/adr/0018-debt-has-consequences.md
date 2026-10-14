# 0018. Debt has consequences

Date: 2026-10-13
Status: Accepted, amended 2026-10-14

## Context

The manager's bank went to −442k in a playtest:

1. Two fees were agreed on the same day, 620k and 1,330k. Each was checked against the bank on its own, not against what the other had already promised.
2. Then the budget slider (ADR 0017) moved money into the salary budget without knowing that 1,330k was promised to the seller.
3. Finally the fee was paid when personal terms were signed, with no check that the bank could pay it.

Being in debt cost nothing. Bids were refused while the bank was below zero, but the weekly money paid it down, and the owners cleared whatever was left when the next season started. The manager asked for consequences like Football Manager's, including wage cuts that leave the players unhappy when the club is deep in the red.

## Decision

- **Agreed fees are set aside.** A fee agreed and waiting on personal terms counts against the bank: new bids and the budget slider only see what is left. Personal terms cannot be signed while the bank cannot pay the fee.
- **The owners stop clearing the manager's debt** at the start of a season. They still clear an AI club's debt.
- **While the bank is below zero:**
  - The board pays for no transfers, so no bids, and the salary budget can only go down.
  - The board loses a point of confidence every week, or two once the debt passes a quarter of the salary budget. Confidence feeds the reviews, so a long debt can cost the job.
  - The first week in debt brings a message, and so does getting out of it.
- **Deep debt cuts wages.** Past a quarter of the salary budget the board cuts every player's wage by 10 percent (staff keep theirs) for the rest of the contracts, at most every eight weeks. Every player loses 20 morale. Each player except the franchise player may become unsettled and want to leave: 10 percent for an unknown, up to 50 for a star (by reputation). Lower wages leave more of the budget for the bank, which pays the debt down.
- **The next transfer grant pays the debt first**, and the board's message says how much of it went there.
- **The way out the manager controls** is cutting the salary budget, which puts money in the bank at once (ADR 0017).

## Consequences

Overspending is now a real decision: a manager can still release players or carry a payroll above the budget into the red, but the board and the squad react. AI clubs are untouched; their finances stay as simple as before. A 10 percent cut is permanent for the contracts it hits, so a squad that went through one is cheaper to keep but less happy for weeks, and the stars may push for a move.
