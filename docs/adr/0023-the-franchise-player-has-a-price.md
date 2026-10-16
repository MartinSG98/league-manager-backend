# 0023. The franchise player has a price

Date: 2026-10-15
Status: Accepted, amended 2026-10-16. Amends [0013](0013-a-transfer-window-instead-of-a-yearly-draft.md) and [0016](0016-retirements-announced-a-season-ahead.md)

## Context

The franchise player could never leave: no club bid for him, he could not be listed or released, and when he retired the board made the best player the next one. The manager asked to be able to sell him, but only for a sum that makes it worth it, and to choose who comes next.

## Decision

- **Bids.** The manager's franchise player still cannot be listed or released. A club that could afford him and needs his role may bid for him, a quarter as often as for anyone else, and never for less than twice his market value (`transfers.FRANCHISE_PRICE`); asking for more raises the bid up to three times his value. AI clubs' franchise players stay off the market.
- **Naming the next.** When the manager's franchise player is sold or retires, the seat stays empty for 14 days, and the manager names any of their players (`set_franchise`). If they do not, the board names the best player. AI clubs name their best player at once, and so does a club the manager leaves with the choice open.

## Amendment, 2026-10-16

The manager can also ask the board to move the franchise from the player who has it to another of their players (`change_franchise`), as long as the new one has been at the club a year (`PlayerState.since`, kept from now on; a player who joined before counts as long enough).

- **A board that trusts the manager** (Secure, confidence 70 or more, `board.SECURE`) agrees at once.
- **Otherwise it asks why**, with four answers, each held against the facts (`transfers.reason_weight`, 0 to 1): he is the future of the club (younger, by up to six years, and with the potential to match), he has been our best player (his rating against the franchise player's), the fans love him (his reputation) and the franchise player is past his best (past 28 and no better than the new one).
- **The decision.** The chance is 15 percent, plus 60 times that weight, plus a point for every point of confidence above 45, between 5 and 95 percent. A no stands for the rest of the season, and an answer the facts do not bear out (a weight under 0.2) costs 3 confidence.

The old franchise player becomes an ordinary member of the squad and keeps his contract.

## Consequences

The face of the club becomes the manager's biggest decision rather than a fixed piece: a fortune for a star, or the star. The franchise player's protections (no listing, no release, a contract kept on) pass to whoever is named next.
