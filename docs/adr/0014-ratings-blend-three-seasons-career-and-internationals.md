# 0014. Ratings blend three seasons, the career and the international stage

Date: 2026-10-12
Status: Accepted

## Context

Rating players on their 2026 stat line alone (ADR 0005) put some well-known players far from where their name says. Faker rated 79, below Doran and Gumayusi. Hans Sama, the starting bot laner of the LEC's best team, rated 72, below the LEC average. Meanwhile newcomers with one good split on a weaker team rated in the low 80s. The manager asked for historical data to shape the ratings, and for the international stage to weigh more, since wins and games there are worth more.

## Decision

The overall rating blends four reads of each player:

| Weight | Read | From |
|---|---|---|
| 0.45 | Form | the 2026, 2025 and 2024 stat lines, weighted 1, 0.6 and 0.3 |
| 0.25 | Career | win rate over every career game (pulled towards 50% for short careers), KDA against the role, longevity |
| 0.15 | International | games and win rate at First Stand, MSI and Worlds since 2024, weighted 1, 0.8 and 0.6 by year |
| 0.15 | Team | how the player's 2026 team did |

- **Form.** Each earlier season is judged the same way as 2026: stat z-scores against the players who share the 2026 league and role. Seasons a player did not play do not count, so a rookie is judged on 2026 alone. Attributes use this three-year form too.
- **Career and international.** Both are z-scores among players of the same role in every league. Win rates are zero-sum inside a league, so the career does not favour one league over another. A player with no international record is not penalised in a league where nobody goes to internationals.
- **The league is kept.** The blend is rescaled to the mean and spread that 2026 form alone gave inside each (league, role) group. It reorders players within a league; league averages and spreads stay where ADR 0005 put them.

`scripts/fetch_golgg.py --history` adds the earlier seasons and the international events to `golgg_2026.json`, about ten pages.

## Consequences

Faker rates 86, Hans Sama 80, Gumayusi 88 and BrokenBlade 83. Players with one strong year and no international record come down, for example Naak Nako from 81 to 75. Earlier seasons are judged against the 2026 league, so a player who came up from an ERL carries an ERL season into an LEC comparison; at weight 0.3 to 0.6 that is accepted. MSI 2025 is not on gol.gg under any name we found, and Worlds 2026 had no stats when this was fetched. Ratings change for saves already in progress the next time the catalog loads.
