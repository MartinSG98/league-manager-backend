# 0013. A transfer window instead of a yearly draft

Date: 2026-10-12
Status: Accepted

## Context

Until now every off-season ended in a new draft for the roles teams still needed. The manager asked for the draft to happen only at the start of a career and for transfers after that: buying and selling players, with players who would rather not join a small club, and players who are unhappy when a bid from a bigger club is turned down and want to talk about it. Transfers should happen only in the off-season.

Club money also had no use. Weekly wages were paid out of a bank that sponsors could not refill, so every club ended the season close to zero and could not have paid a transfer fee.

## Decision

The off-season is a transfer window from the day after the Worlds final to January 16th, the eve of the next season, and the calendar moves through it day by day. Continue stops at least every Monday. The manager asked for the window to be about twice as long as the first version's, which closed on December 15th.
- **Free agency.** Contracts that end with the season run out on December 1st, which leaves time to extend players first.
- **Fees.** A player under contract costs a fee: the market value, raised for a starter or a club's only player in a role, lowered for a bench or listed player. A franchise player is never for sale.
- **Bids.** The manager's bid is agreed, countered or turned down at once. An agreed fee opens contract talks, and the fee is paid when the player signs.
- **Interest.** Players compare their own reputation with the club's. A big gap means a refusal, a smaller one means a reluctant player who wants more money.
- **AI clubs.** They sign free agents and bid for upgrades. Bids between AI clubs settle at once. A bid for one of the manager's players waits four days for an answer.
- **Unhappy players.** Turning down a bigger club upsets the player, who asks to talk. The manager answers with one of three lines, and a promise to let the player go is remembered for the next window.
- **The close.** When the window closes every club fills its empty roles and staff seats, and the new season is scheduled with no draft.

Money now works like this:
- **Salaries.** The owners fund the salary budget, so what the payroll leaves of it goes to the bank every week, along with sponsors and prize money.
- **Transfers.** Every off-season the board puts a share of the budget in the bank for transfers, more for a bigger club. Fees come out of the bank.

## Consequences

Rosters change between seasons through moves that make sense: bigger clubs take the best players from smaller ones, and a strong player at a weak club is hard to keep. The manager's off-season has decisions with a cost: sell to buy, keep an upset player or cash in. ADR 0006's draft now only happens once per career. Budgets are set by the board from the region's going rate and the club's reputation instead of from a draft pool. Saves made at the end of a season under the old rules open the window on their next action.
