# League Manager backend

FastAPI backend for League Manager, Football Manager for League of Legends esports. You take over a tier-one team from any of the six major regions at the end of 2026. Your team keeps one franchise player, G2 keeps Caps and T1 keeps Faker. Everyone else in the region goes into a draft pool with the region's tier-two players. You draft a roster on a budget, then manage it through a whole season: three domestic splits, First Stand, MSI and Worlds, a new patch every two weeks, and champion select in every game you play.

This repo holds the API and the whole game engine. The browser client lives in [league-manager-ui](https://github.com/MartinSG98/league-manager-ui) and only draws what this service returns.

Architecture decisions are recorded in [docs/adr](docs/adr/README.md), one numbered file per decision.

## How a season goes

1. **Pick a team.** Any of the 56 tier-one teams in the LCK, LPL, LEC, LCS, CBLOL and LCP.
2. **The draft.** On December 1st every tier-one team is stripped down to its franchise player. The rest of the region's 2026 tier-one players and every tier-two player form one pool, about 700 players for EMEA with the LEC and its 13 ERLs. Teams pick in snake order, the weakest 2026 team first. The first four rounds fill the starting five, so you can only draft a role you still need. Two optional bench rounds follow. Salaries are fixed at each player's asking price, and every pick has to leave enough budget to fill your remaining roles. Every other region drafts at the same time with the AI.
3. **Splits.** Three per region, under their real names: the LEC Versus, Spring and Summer, the LCK Cup, Rounds 1-2 and Rounds 3-4, and so on. Each is a round robin (Bo1 or Bo3 depending on the league and split) followed by best-of-five playoffs with byes for the top seeds.
4. **International events.** First Stand after split 1 has 8 teams in groups and then knockouts. MSI after split 2 has 10 teams, with a play-in and then an 8-team bracket. Worlds after split 3 has 16 teams in a Swiss stage and then best-of-five knockouts. Teams qualify by their playoff finish.
5. **Match day.** Set your lineup and tactics, then draft champions in tournament order (or let the assistant do it), then watch the game play out minute by minute. Best-of series use fearless draft.
6. **Continue.** `advance` moves the calendar a day at a time and plays every other match in the world on the way, until your team plays next.
7. **Contracts.** Once the draft is over you can sign free agents and extend your own players whose contracts run out, by negotiating salary and length, or release players for half of what is left on their deal.
8. **The off-season.** After Worlds, contracts that end are gone (AI teams re-sign the players they value), prospects grow, veterans may decline, and every league drafts again, only for the roles its teams still need.

## Running locally

Requires Python 3.11 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8020
```

The API starts on http://127.0.0.1:8020. Check it is alive at http://127.0.0.1:8020/api/health and browse the interactive API reference at http://127.0.0.1:8020/docs. The SQLite file `league_manager.db` is created on first start. There are no external services and no API keys. All game data ships in `app/data`.

## Configuration

Copy `.env.example` to `.env` if you need to change anything.

| Variable | Default | Purpose |
|---|---|---|
| `LEAGUE_MANAGER_CORS_ORIGIN` | `http://localhost:5190` | Origin the frontend dev server runs on |
| `LEAGUE_MANAGER_DATABASE_URL` | `sqlite:///league_manager.db` | SQLAlchemy database URL |

## API

| Method | Path | What it does |
|---|---|---|
| GET | `/api/health` | Liveness check |
| GET | `/api/catalog` | Regions, leagues, tier-one teams with their franchise player, every champion |
| GET | `/api/catalog/teams/{id}` | One team's 2026 roster and the size of its region's draft pool |
| POST | `/api/careers` | Start a career for `{"manager": "...", "team": "G2"}` |
| GET | `/api/careers` | Saved careers, most recently played first |
| GET | `/api/careers/{id}` | The career summary: date, phase, budget, next match, inbox |
| DELETE | `/api/careers/{id}` | Delete a save |
| POST | `/api/careers/{id}/actions` | Play one action, get the updated summary back |
| GET | `/api/careers/{id}/draft` | Draft board: order, picks, every team, the pool with why each player can or cannot be picked |
| GET | `/api/careers/{id}/squad` | Your roster with attributes, form, contracts and chemistry, `?team=` for another team |
| GET | `/api/careers/{id}/players` | Player search, `?region=`, `?free_agents=true`, `?role=` |
| GET | `/api/careers/{id}/players/{pid}` | One player: attributes, 2026 stats, champion pool and mastery, season stats |
| GET | `/api/careers/{id}/competitions` | Every competition of the season |
| GET | `/api/careers/{id}/competitions/{cid}` | Standings, brackets and results |
| GET | `/api/careers/{id}/schedule` | Your team's matches, `?team=` for another team |
| GET | `/api/careers/{id}/matches/{mid}` | A series with every game's picks, bans and stat lines |
| GET | `/api/careers/{id}/matches/{mid}/games/{n}` | One game, with the full timeline if you played it |
| GET | `/api/careers/{id}/live` | Your series in progress: lineups, champion select, suggestions |
| GET | `/api/careers/{id}/meta` | Champion tiers on the current patch and recent patch notes |
| GET | `/api/careers/{id}/negotiate/{pid}` | Contract talks with a player: the agent's ask, budget room, any counter-offer |

Actions are JSON objects tagged by `type`:

| Action | Body | When |
|---|---|---|
| `draft_pick` | `player` | Your pick in the draft |
| `draft_pass` | | Skip a bench-round pick |
| `draft_auto` | | Let the assistant make this pick |
| `draft_sim` | | Let the assistant finish the draft |
| `advance` | | Continue to your next match |
| `set_lineup` | `lineup` (role to player id) | Before champion select |
| `set_tactics` | `tactics` (`style`, `lane`, `objectives`) | Any time |
| `start_champ_select` | | Your match is waiting |
| `ban` | `champion` | Your ban turn |
| `pick` | `champion`, `role` | Your pick turn |
| `auto_select` | | Let the assistant finish champion select |
| `play_game` | | Champion select is done |
| `next_game` | | After a game, starts the next one or ends the series |
| `sim_series` | | Auto-draft and play out the rest of the series |
| `read_message` | `id` (optional) | Mark one inbox message, or all, read |
| `offer` | `player`, `salary`, `years` | Offer a free agent a contract, or extend one of your players in their last season |
| `accept_counter` | `player` | Sign at the salary the player countered with |
| `release` | `player` | Let a player go, paying half the rest of the contract |
| `next_season` | | After Worlds, start the next pre-season |

An action that does not fit the career's current state returns 409 with the reason, for example drafting a second mid laner while you still have no jungler.

## The rules in numbers

**Ratings.** Every rated stat comes from the player's 2026 games on gol.gg. Each stat is turned into a z-score among the players of the same role in the same league. Recipes of those make eight attributes on a 1-20 scale:

| Attribute | Made from |
|---|---|
| Laning | gold, CS and XP difference at 15 |
| Mechanics | KDA, solo kills per game, damage per minute |
| Teamfighting | kill participation, damage share, deaths |
| Vision | vision score per minute, wards cleared, vision share |
| Macro | win rate, gold difference at 15 |
| Consistency | deaths, KDA, first-blood victim rate |
| Composure | career games and win rate |
| Champion pool | champions with five or more career games |

An average player sits at a baseline set by league strength. That is 15.5 for the LCK, 13 for the LEC and about 6 for a mid-sized ERL. Small samples are pulled towards the average. The overall rating (30-99) weighs the attributes by role, so a support's vision counts most and a bot laner's mechanics and teamfighting count most. A long career adds up to 3 points of big-match experience. Potential is higher for players with fewer career games.

**Salaries.** An asking salary doubles roughly every 7 overall points. It is scaled by region (Korea 1.0, China 1.15, EMEA 0.9, NA 1.1, Brazil 0.45, Pacific 0.55) and by reputation. A team's budget covers its franchise player, four players of the average quality a draft hands out, and a bench player. It is scaled by the organisation's prestige, from 0.82 to 1.18.

**Champions.** In a game a champion adds or subtracts from its player's rating:

- **Comfort** comes from mastery, which grows with career games: -2.6 on a champion never played, +2.6 on a comfort pick, about +5 on a signature.
- **Meta power** on the current patch counts at 0.8x and runs from about -3 to +5.
- **Off role** costs 5.

Compositions with a single damage type lose 2, and those with nobody in front lose 1.5. A tactic that matches the composition's power curve adds 0.8. 53 hand-picked champion duos from riftlike add 0.6 per point, for example Xayah and Rakan +2 or Jarvan IV and Orianna +1, and a few known bad pairs subtract.

**Chemistry.**
- Pairs that share a language count towards communication. Europe and North America play in English, Korea, China and Brazil in their own languages, and anyone playing abroad speaks English.
- Pairs that played together in 2026, or have started 20 games together since, count towards familiarity.
- The bot lane pair weighs most, then jungle and mid.
- A shotcaller with leadership 15 or more is worth +1.

Chemistry runs from about -5 to +4 on top of the team's average.

**Contracts.** The draft pays the asking price. After the draft, every deal is negotiated.
- **The ask.** It is the market rate for the player's current rating. A player whose reputation is above your club's prestige asks up to 40 percent more. Your own players ask more when their morale is low, and a free agent without a team mid-season asks 10 percent less. Prospects want three seasons, players past 900 career games want one, everyone else two.
- **The floor.** Each player has a hidden floor between 86 and 97 percent of the ask, and every year away from the preferred length counts as 5 percent off the offer.
- **The answer.** At or above the floor, the player signs. Within reach, the player counters halfway between your offer and the ask. Under 60 percent, or after three failed rounds, the agent walks away for three weeks.
- **Rosters and releases.** A roster holds 8 players. Releasing a player costs half of the remaining contract.

**Off-season.** Contracts that end leave the team. The franchise player renews automatically for three seasons. AI teams re-sign starters and anyone above their lineup's average more often than the rest. A player with fewer than 600 career games and room to grow closes 35 percent of the gap to potential, give or take. Past 1,100 career games a player can lose up to 2 overall a year. The next draft runs in reverse order of the last split's finish, with as many required rounds as the neediest team has open roles, plus one bench round.

**Patches.** A new patch every two weeks from January 6th. The balance team nerfs 3-5 of the champions that were picked or banned most on the outgoing patch and buffs 3-6 that nobody played. Every sixth patch is a mid-season update that also moves a whole class up or down by one. Every other champion drifts 3 percent towards the middle each patch. The first patch's meta comes from real 2026 pro presence.

**Games.** A game is simulated minute by minute.

- **Laning (1-14).** Lanes trade gold by matchup, with solo kills and jungle ganks. Junglers contest voidgrubs at 6 and 10, the first dragons, and the herald at 14.
- **Fights (from 15).** Fights break out most often around a live dragon, Baron or Elder. A fight is a logistic roll on the power difference plus gold lead and buffs (Baron +5, Elder +7, Soul +3). The winner takes kills, the objective and towers.
- **The end.** The game ends when a side wins a fight with an inhibitor down and a buff or a big margin.
- **Form on the day.** Each side also gets a random form of up to ±6.5. With the current tuning, a 4-point edge in team power wins about 65 percent of games, a 10-point edge about 85 percent and a 14-point edge about 93 percent.

## Data

- **Rosters and stats.** Rosters, roles, nationalities and 2026 stat lines for 27 leagues come from [gol.gg](https://gol.gg), and so do career champion pools and 2026 champion presence. The scripts that fetch them are `scripts/fetch_golgg.py` and `scripts/fetch_meta.py`. Pages are cached in `.cache/`, so re-runs only fetch what is missing.
- **Logos and photos.** Team logos, league and event logos, player photos and real names come from the lolesports.com API through `scripts/fetch_lolesports.py`, which writes `app/data/lolesports.json`. Only URLs are stored, and the images stay on Riot's CDN. Every tier-one team, 195 teams in all, every league and about 1,320 of 1,368 players have one.
- **Champions.** The champion list is Data Dragon 16.20.1, with roles, power curve, damage type and class tagged by hand in `scripts/build_champions.py`.
- **Leagues.** `app/data/leagues.json` lists every league with its region, tier, strength and the gol.gg tournament its rosters come from.
- **Teams.** `app/data/teams.json` holds tags, colours, prestige and franchise players for tier-one teams. Teams not listed there keep the best-rated starter as their franchise player.

## Tests and balance

```bash
pip install -r requirements-dev.txt
pytest
python -m scripts.simulate 2000 --season 3
```

The tests cover:
- the data, the draft rules and budgets, and round robin and bracket shapes
- champion select with fearless, and determinism
- a full season through Worlds
- the API from draft to a played game

The simulation prints the game win rate per gap in team power and who won each title over a few whole seasons. The engine's constants at the top of `match_engine.py` were tuned against it.

## Structure

```
app/
├── main.py           app, CORS and routers
├── config.py         settings from LEAGUE_MANAGER_ environment variables
├── db.py, models.py  SQLite engine, the save table and played-game timelines
├── repository.py     load, store and list saves
├── routers/          catalog and careers endpoints
├── data/             leagues, teams, champions, gol.gg rosters, stats and meta
└── game/
    ├── catalog.py    static world: regions, leagues, teams, players, champions
    ├── ratings.py    2026 stat lines to attributes, overall, potential, salary
    ├── roster.py     current ratings, mastery, languages and chemistry
    ├── state.py      the saved career and the actions
    ├── draft.py      the pre-season draft and budgets
    ├── contracts.py  negotiation, extensions and releases
    ├── offseason.py  contracts ending, development, the next draft
    ├── calendar.py   the season: splits, First Stand, MSI, Worlds
    ├── competitions.py  round robins, brackets, Swiss, standings
    ├── patches.py    the meta and the patches that move it
    ├── champ_select.py  tournament draft order, AI picks and bans
    ├── match_engine.py  one game, minute by minute
    ├── matchday.py   series, fearless, the manager's live series
    ├── engine.py     career flow and the action entry point
    └── views.py      what the client renders
scripts/              data fetchers and the balance simulation
tests/                engine and API tests
```

League Manager is a fan project. It is not affiliated with or endorsed by Riot Games. League of Legends and all related names are trademarks of Riot Games. Statistics come from gol.gg, Games of Legends.
