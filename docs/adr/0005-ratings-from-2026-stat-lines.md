# 0005. Ratings from 2026 stat lines

Date: 2026-10-11
Status: Accepted, amended by [0014](0014-ratings-blend-three-seasons-career-and-internationals.md) and 2026-10-16

## Context

About 1,400 players across 27 leagues need ratings. Hand-rating them is impossible and would only be opinion. Raw stats cannot be compared across leagues either: a 4 KDA in an ERL is not a 4 KDA in the LCK.

## Decision

Ratings are computed from each player's 2026 gol.gg stat line when the catalog loads, the way Worlds Mayhem rates its players from many stats.

1. Every stat becomes a z-score among players of the same role in the same league.
2. Recipes of z-scores make eight attributes.
3. Each attribute is standardised again within its group.
4. League strength, hand-set in `leagues.json`, sets the baseline that every group is placed around.

Small samples shrink towards the average. Career games add composure and a little big-match experience.

Franchise players are hand-picked for well-known teams in `teams.json`. Every other team keeps its best-rated starter.

## Amendment, 2026-10-16

One line through every league's strength put the tier-one leagues far apart: the average starter was rated 81 in the LCK, 71 in the LEC and 67 in the LCS, so Hans Sama, the LEC's best bot laner, was 80 and Inspired, among the LCS's best, 75. The tier-one leagues now have their own line, anchored on the LCK: the baseline drops 0.15 an attribute point (0.5 overall) for every point of strength below 100, against 0.22 before. The LCK and the LPL barely move; the LEC's players gain about 3 overall, the LCS's and the LCP's about 5 and the CBLOL's about 6. Hans Sama is 82, Caps 89, Inspired 79. Tier-two leagues keep the old line, so the ERLs do not move. League strength itself is unchanged, and so is everything else it feeds (power rankings, reputation).

## Consequences

Every number can be traced back to a stat, and retuning is a code change with no rebuild. League strengths carry a lot of weight and are a judgement call. Players who moved leagues mid-season are rated against their last league, using stats from the whole year. Stars on a weak 2026 team rate lower than their name, which is what the data says. Age is not in the gol.gg data, so potential uses career games as a stand-in for youth.
