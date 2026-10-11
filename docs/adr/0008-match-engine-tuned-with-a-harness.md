# 0008. Match engine tuned with a harness

Date: 2026-10-11
Status: Accepted

## Context

A minute-by-minute simulation with snowballing gold and many fights quickly becomes deterministic. In the first version a 4-point edge won 95 percent of games, and the best Korean team won all six of its events in a season. Real League has upsets.

## Decision

The engine's constants sit at the top of `match_engine.py`:
- fight scale
- gold to power
- lane gold
- objective buffs
- fight frequency
- a random form on the day for each side

They were tuned with `scripts/simulate.py`. It prints the stronger side's win rate for each gap in team power, and the title winners of whole simulated seasons. The target curve is about 58 percent at a 2-point gap, 65 at 4, 72 at 6, 84 at 10 and 90 at 14.

## Consequences

Favourites win most titles but not all of them, and international events produce surprises. Buffs still matter because they are won in fights and push structures. Any engine change should be followed by a harness run.
