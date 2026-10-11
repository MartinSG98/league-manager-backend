# 0010. Staff from Liquipedia, with this game's own ratings

Date: 2026-10-11
Status: Accepted

## Context

The manager asked for an assistant coach and an analyst on every team, picked in the draft, and for real 2026 staff where they can be found. Staff change things a manager feels every week: how players grow, how they take defeats, which champions they learn, how good the champion select advice is, and what the analyst finds out about the next opponent and the next patch.

None of this game's sources lists staff by job. gol.gg has players only. The lolesports.com API lists staff on team rosters under a single "none" role, so a head coach, an assistant and an analyst look the same. Leaguepedia's Cargo API still answers this machine with a rate-limit error. Liquipedia's team pages list every active coach and analyst with their position, country and real name. Its API allows one rendered page every 30 seconds.

## Decision

`scripts/fetch_staff.py` renders every tier-one team page through the Liquipedia API, one request every 31 seconds, and caches each page in `.cache/liquipedia`. It keeps everyone in the active roster and organisation tables whose position mentions coach or analyst. It writes `app/data/staff.json`, keyed by this game's team ids, with handle, real name, position and country. Photos come from the same team's lolesports.com roster when a handle matches. A team page with another title on Liquipedia gets a `liquipedia` entry in `teams.json`.

Liquipedia has no ratings, so the ratings are this game's own:
- the organisation's prestige sets the level
- the job title adds to it, so a head coach rates higher than a positional coach
- a fixed draw per person spreads the attributes around that level

Head coaches are in the pool as well, because the manager is the head coach in this game. Every region's pool is topped up with generated staff, so every team has a choice and cheap options always exist.

Staff are drafted in two extra snake rounds after the players, a coach round and then an analyst round, and paid from the same budget. The budget grows by the cost of an average pick for each seat.

## Consequences

Real names such as Perkz, Memento or Score show up in the draft, and staff matter in every part of the season. The ratings are invented and say nothing about the real people. The fetch takes about half an hour for 56 teams, but it is cached and only needs a rerun when rosters change. A team with no staff found on Liquipedia simply adds nothing real to the pool.

Liquipedia content is CC BY-SA 3.0. Only names, positions and countries are kept, and the README credits the source.
