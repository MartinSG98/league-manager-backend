# 0015. Rookie classes, kept in the career

Date: 2026-10-12
Status: Accepted, amended 2026-10-14 and 2026-10-16

## Context

The player pool was fixed: every player comes from 2026 gol.gg data, and the draft happens only when a career starts. Over several seasons the pool only ages. The manager asked for Football Manager style regens: from the first off-season on, a new generation of rookies of every kind, from hopeless busts to wonderkids, some through academies and ERL teams and some as free agents.

The catalog is loaded once and shared by every career, and the whole game looks players up in it.

## Decision

Every off-season, near the end of `start_offseason` (only the staff market's new faces come after it), each region gets a rookie class for the next season: 1.2 rookies per tier-one team, at least six.

- **Classes.** Potential is drawn first: 30% busts (40-58), 35% journeymen (55-68), 22% decent (65-76), 10% prospects (75-86) and 3% stars (84-90). Each region's first rookie is its headline: a wonderkid (90-98) 55% of the time, otherwise a star. Korea and China add 2 to every potential.
- **Start.** Rookies start 14 to 28 points below that potential, wonderkids 15 to 25, never below 35. Attributes follow the overall with the role's emphasis and some noise; composure and champion pools start low.
- **Origin.** 60% come through an academy or ERL team of their region, the rest straight from solo queue. In this game ERL players are free agents, so all rookies can be signed like any free agent; the origin is only shown.
- **Hidden ceiling.** The potential shown is the scouts' first estimate. The real ceiling is hidden as for every player, so shortlisting and a scout report is how to tell a wonderkid from a hyped bust.
- **Storage.** Rookies live in the career (`Career.rookies`), never in the shared catalog. `rookies.catalog_for` gives a career its own catalog, the shared players plus its rookies, without changing the shared one. `engine.apply` and every career endpoint use it.

## Consequences

The pool renews itself, and scouting has a purpose beyond the known names. About 70 players join each season, and since ADR 0016 retirements take players out of the pool. Generated names are made from syllables and a few words, and rookies have no photo. Any code that looks up players for a career has to use that career's catalog, not the shared one.

## Amendment, 2026-10-16

Rookies grew too fast and too many of them became stars: the best of each class started 73 to 79 and reached their ceiling, often 95 or more, within two seasons, and every class had three to six rookies with a potential of 90 or more.

- **Classes.** Stars are now 82-88, and a region's headline rookie is a wonderkid 30% of the time instead of 55%: one or two rookies with a potential of 90 or more a class.
- **Start.** A rookie with a potential of 85 or more starts 18 to 26 points below it, so a 93 starts around 71. With the slower growth of the amendment to [ADR 0011](0011-training-areas-and-set-plays.md) a prospect needs about three seasons to get near the ceiling.
- **Not all make it.** A rookie's hidden ceiling runs from 11 points below the potential shown to 3 above, 4 below on average: the scouts' first read of a teenager is hopeful. More than one rookie in three ends 5 or more points short and one in ten a little past it. A scout report still finds the real ceiling.
