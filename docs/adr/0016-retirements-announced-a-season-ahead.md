# 0016. Retirements, announced a season ahead

Date: 2026-10-13
Status: Accepted, amended 2026-10-13 and 2026-10-14

## Context

With a rookie class every off-season (ADR 0015) and nobody ever leaving, the player pool only grows and veterans play forever. The manager asked for retirements the way Football Manager does them: a player says a season ahead that the coming season will be their last. Faker was named as the kind of exception a rule has to allow: old, but still among the best and still playing.

The gol.gg data has no ages.

## Decision

- **Career age.** A stand-in for age: a debut at 18, plus a year for every 90 career games before 2026, plus a year for every season played in the game, give or take two years, never below 17. Rookies start at 18 in their first season. It is never shown.
- **Announcing.** At the start of every off-season each player may say the next season will be their last: 3% a season from age 25, 6% at 27, 10% at 28, 16% at 29, 25% at 30, 35% at 31 and 50% from 32. Under 25 only a player rated below 60 gives up, at 1%.
- **Who stays.** A player rated 85 or more is half as likely to stop. A legend still rated 80 or more after a thousand career games is five times less likely, which keeps Faker going about 19 years in 20 while he is still good. A player rated below 60 is twice as likely.
- **Retiring.** At the next off-season they retire: they leave their team, have no contract, and drop out of searches, free agency, shortlists and contract talks.
- **News.** The manager hears about their own players, as player messages, and about players with a reputation of 75 or more.

Career games now count the seasons played in the game (`PlayerState.played`), which development uses too: before, a player's career games never grew past their 2026 total plus the current season.

## Amendment, 2026-10-13

Two seasons into a career, LPL and LCK stars rated 88 to 93 (Knight, Elk, Gumayusi, Tian, RooKie) had retired at career ages of 26 to 30. Each had a chance of 1 to 5 percent, but there are some 70 players rated 85 or more, so a few went every year. Their career ages were also too high: the best teams play far more than 90 games a year, so a 24-year-old with 800 games came out at 27. Against the birth years of 37 well-known players, career games barely predict age at all past a few hundred games.

- Career games count towards the age up to eight years' worth (720 games) and no further.
- A player rated 85 or more does not announce before a career age of 30, and is a third as likely to after it (it was half).
- A player rated 80 or more is half as likely to announce (before, only 85 or more counted).

Expected announcements among players rated 85 or more fall from about 1 to 2.7 a season to almost none before 2030, and among those rated 78 to 84 by about a third. Retirements further down the ratings are unchanged.

## Consequences

The pool turns over: rookies come in, veterans and players going nowhere leave. Ages are invented, so a real player may retire earlier or later than they would have. Early seasons see few retirements, since most players start young by this measure.
