# 0006. A franchise player and a snake draft at fixed salaries

Date: 2026-10-11
Status: Accepted

## Context

The game is about building a roster, but real rosters are already built. Starting with the 2026 lineups would leave the manager little to do in the first pre-season.

## Decision

Every tier-one team keeps one franchise player: G2 keeps Caps, T1 keeps Faker. The rest of each region's 2026 players, tier one and tier two, become one pool.

- **Order.** Teams draft in snake order, with the weakest 2026 finisher first.
- **Rounds.** Four rounds must fill the starting five, then come two optional bench rounds.
- **Salaries and budget.**
  - Salaries are fixed at the asking price.
  - A pick must leave enough budget to fill the open roles with the cheapest players left.
  - Budgets are set so a team can afford roughly an average draft class, scaled by prestige.
- **Negotiation** belongs to later in the career, for extensions and free agents, not to the draft.

Every other region drafts with the AI when the career starts.

## Consequences

The first decision of a career is a real one: one star with cheap teammates, or a balanced five. The AI weighs rating, potential, shared language and 2026 teammates against cost, so drafts stay plausible. Lineups start with low familiarity, so chemistry grows over the first split. Undrafted players stay in the pool as free agents.
