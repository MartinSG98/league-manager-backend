# 0016. Retirements, announced a season ahead

Date: 2026-10-13
Status: Accepted

## Context

With a rookie class every off-season (ADR 0015) and nobody ever leaving, the player pool only grows and veterans play forever. The manager asked for retirements the way Football Manager does them: a player says a season ahead that the coming season will be their last. Faker was named as the kind of exception a rule has to allow: old, but still among the best and still playing.

The gol.gg data has no ages.

## Decision

- **Career age.** A stand-in for age: a debut at 18, plus a year for every 90 career games before 2026, plus a year for every season played in the game, give or take two years, never below 17. Rookies start at 18 in their first season. It is never shown.
- **Announcing.** At the start of every off-season each player may say the next season will be their last: 3% a season from age 25, 6% at 27, 10% at 28, 16% at 29, 25% at 30, 35% at 31 and 50% from 32. Under 25 only a player rated below 60 gives up, at 1%.
- **Who stays.** A player rated 85 or more is half as likely to stop. A legend still rated 80 or more after a thousand career games is five times less likely, which keeps Faker going about 19 years in 20 while he is still good. A player rated below 60 is twice as likely.
- **Retiring.** At the next off-season they retire: they leave their team, have no contract, and drop out of searches, free agency, shortlists and contract talks.
- **News.** The manager hears about their own players, as player messages that stop Continue, and about players with a reputation of 75 or more.

Career games now count the seasons played in the game (`PlayerState.played`), which development uses too: before, a player's career games never grew past their 2026 total plus the current season.

## Consequences

The pool turns over: rookies come in, veterans and players going nowhere leave. Ages are invented, so a real player may retire earlier or later than they would have. Early seasons see few retirements, since most players start young by this measure.
