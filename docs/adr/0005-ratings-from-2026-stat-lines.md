# 0005. Ratings from 2026 stat lines

Date: 2026-10-11
Status: Accepted

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

## Consequences

Every number can be traced back to a stat, and retuning is a code change with no rebuild. League strengths carry a lot of weight and are a judgement call. Players who moved leagues mid-season are rated against their last league, using stats from the whole year. Stars on a weak 2026 team rate lower than their name, which is what the data says. Age is not in the gol.gg data, so potential uses career games as a stand-in for youth.
