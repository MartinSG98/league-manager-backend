# 0008. Match engine tuned with a harness

Date: 2026-10-11
Status: Accepted, amended 2026-10-14

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

## Amendment, 2026-10-14: drakes and Souls

Every drake used to be a random element, so a Soul could be of an element the map never had, and every Soul was worth the same 3 points.

- **Elements.** Drakes now follow the Rift: the first two are two different elements, the third a third one, and every drake after it is that element, as is the Soul.
- **Soul power.** Each Soul has its own power. No breakdown by element was found for pro play, and Oracle's Elixir's yearly files could not be downloaded at the time, so the targets are leagueofgraphs.com's win rates for the side with each Soul in about 3.1 million ranked games on patch 16.20: Cloud 90.6, Mountain 88.0, Hextech 87.5, Ocean 87.1, Chemtech and Infernal 86.8 percent. In pro play the side with the Soul won all 52 games of the Worlds 2025 Swiss stage.
- **Fit.** `scripts/simulate.py --souls` prints the engine's win rate for each Soul next to its target. The side that takes a Soul is usually ahead already, so a point of Soul power is worth only about half a point of win rate: 85.5 percent at no Soul power, 87.7 at 3 and 91.4 at 10. The fitted powers are Cloud 8, Mountain 3.5, Hextech 2.5, Ocean 2 and Infernal and Chemtech 1.5. Over 20,000 games every Soul lands within 1.5 points of its target, which is the sampling noise, and all of them together win 87.7 percent against 87.8 in ranked.
- **Elder.** It stays at +7 for three minutes: the side that takes an Elder wins 86.7 percent of the time in the engine, which the manager found right.

Pro players tend to rate Cloud as the weakest Soul, so ranked numbers may overrate it for pro play. Oracle's Elixir data would settle that.
