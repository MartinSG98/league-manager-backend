# League Manager backend

FastAPI backend for League Manager, Football Manager for League of Legends esports. You take over a tier-one team from any of the six major regions at the end of 2026. Your team keeps one franchise player, G2 keeps Caps and T1 keeps Faker. Everyone else in the region goes into a draft pool with the region's tier-two players. You draft a roster on a budget, then manage it season after season: three domestic splits, First Stand, MSI and Worlds, a new patch every two weeks, champion select in every game you play, a training plan every week, a board that judges you on the objectives you agreed, and a transfer window every off-season.

This repo holds the API and the whole game engine. The browser client lives in [league-manager-ui](https://github.com/MartinSG98/league-manager-ui) and only draws what this service returns.

| ![Champion select](https://raw.githubusercontent.com/MartinSG98/league-manager-ui/main/docs/screenshots/champion-select.png) | ![The game](https://raw.githubusercontent.com/MartinSG98/league-manager-ui/main/docs/screenshots/live-game.png) |
|---|---|
| Champion select, on a clock and fearless | The game, minute by minute |

More screens are in the [client's README](https://github.com/MartinSG98/league-manager-ui#screenshots).

Architecture decisions are recorded in [docs/adr](docs/adr/README.md), one numbered file per decision.

## How a season goes

1. **Pick a team, then create your manager.** Any of the 56 tier-one teams in the LCK, LPL, LEC, LCS, CBLOL and LCP. Then choose a background and spend points on nine attributes, as in Football Manager (see "You" under staff).
2. **Meet the board.** The board proposes a finish for each split and a target at Worlds, from where your club's reputation ranks it in the league. Accept each one, ask for less (4 percent less budget a step) or promise more (4 percent more).
3. **The draft.** Only when the career starts. On December 1st every tier-one team is stripped down to its franchise player. The rest of the region's 2026 tier-one players and every tier-two player form one pool, about 700 players for EMEA with the LEC and its 13 ERLs. Teams pick in snake order, the weakest 2026 team first. The first four rounds fill the starting five, so you can only draft a role you still need. Two optional bench rounds follow, then a round for an assistant coach and a round for an analyst. Salaries are fixed at each player's and staff member's asking price; starters sign for two seasons, bench picks for one and the franchise player for three. Every pick has to leave enough budget to fill your remaining roles and staff seats. Every other region drafts at the same time with the AI.
4. **Splits.** Three per region, under their real names: the LEC Versus, Spring and Summer, the LCK Cup, Rounds 1-2 and Rounds 3-4, and so on. Each is a round robin (Bo1 or Bo3 depending on the league and split), drawn anew every split and season: who meets whom in which week, and who is at home, changes every time. It is followed by best-of-five double-elimination playoffs, as in 2026: eight teams in the LPL and the LEC Versus, six elsewhere. The LEC Spring and Summer and the LCS Spring start their top four in the upper bracket and 5th and 6th in the lower one; the other six-team playoffs send the top two straight to the upper semifinals. A team is out after two defeats, or one in the lower bracket, and there is no bracket reset in the grand final.
5. **International events.** They follow Riot's 2026 rules, and the inbox announces each season's places when it starts ([ADR 0022](docs/adr/0022-global-power-rankings-and-the-2026-international-rules.md)). Teams qualify by their playoff finish.
   - **First Stand** (after split 1): 8 teams, two from the LCK and the LPL and one from every other region, in groups and then knockouts. The winning region sends both its MSI teams straight to the bracket.
   - **MSI** (after split 2): 11 teams, two a region and one from Brazil. Every first seed and the First Stand region's second go straight to an 8-team double-elimination bracket, seeded by how their regions did at First Stand. The other four second seeds play in (double elimination, Bo5) for the last place.
   - **Worlds** (after split 3): 19 teams, three a region and two from Brazil, plus a fourth for the two best regions at MSI. The MSI champion is invited if it reached its region's playoffs. The last team of each of the four other regions plays in for the 16th place in a Swiss stage, then best-of-five knockouts follow. The Swiss pots go by seed, then by the regions' place in the global power rankings. The first round draws pot 1 against pot 4 and pot 2 against pot 3, never two teams from one region. Later rounds draw teams with the same record, and nobody meets the same team twice.
6. **Match day.** Your analyst's report on the opponent is in the inbox. Set your lineup and tactics, then draft champions in tournament order (or let the assistant do it), call one of your set plays, then watch the game play out minute by minute. Best-of series use fearless draft, and each set play can be run once a series.
7. **Training.** Every week your team scrims at the load you set, works on up to two team areas and drills a set play, and each player can work on an attribute, learn a champion, or both. Every few games the analyst says what costs you the most.
8. **Continue.** `advance` moves the calendar one day, as in Football Manager, and plays every other match in the world that day. On your match day your match goes live. The transfer window goes by a day at a time too.
9. **Contracts.** Once the draft is over you can sign free agents and extend your own players whose contracts run out, by negotiating salary and length, or release players for half of what is left on their deal.
10. **The board's reviews.** After every split and after Worlds the board judges the objective it settles. A review that leaves confidence under 22 is a warning, and another under 22 before it is back above 35 is the sack; clubs within reach of your reputation then make you offers.
11. **The off-season.** After Worlds the transfer window opens until January 16th, the eve of the next season. Buy players under contract for a fee, sell yours, sign free agents. Contracts that end run out on December 1st. Players develop, the board sets new budgets and objectives, and the next season starts with no draft.

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
| POST | `/api/careers` | Start a career for `{"manager": "...", "team": "G2"}`, with an optional `seed` |
| GET | `/api/careers` | Saved careers, most recently played first |
| GET | `/api/careers/{id}` | The career summary: date, phase, budget, next match, inbox |
| DELETE | `/api/careers/{id}` | Delete a save |
| POST | `/api/careers/{id}/actions` | Play one action, get the updated summary back |
| GET | `/api/careers/{id}/draft` | Draft board: order, picks, every team, the pool with why each player can or cannot be picked |
| GET | `/api/careers/{id}/squad` | Your roster with attributes, form, contracts and chemistry, `?team=` for another team |
| GET | `/api/careers/{id}/players` | Player search, `?region=`, `?free_agents=true`, `?rookies_only=true`, `?role=` |
| GET | `/api/careers/{id}/players/{pid}` | One player: attributes, 2026 stats, champion pool and mastery, season stats |
| GET | `/api/careers/{id}/staff` | Coaches and analysts, filtered by `kind`, `region` and `free_only` |
| GET | `/api/careers/{id}/staff/{sid}` | One staff member: attributes, contract, the ask, compensation and talks |
| GET | `/api/careers/{id}/competitions` | Every competition of the season |
| GET | `/api/careers/{id}/power` | The global power rankings: every region and every tier-one team, with their trend this season |
| GET | `/api/careers/{id}/competitions/{cid}` | Standings, brackets and results |
| GET | `/api/careers/{id}/schedule` | Your team's matches, `?team=` for another team |
| GET | `/api/careers/{id}/matches/{mid}` | A series with every game's picks, bans and stat lines |
| GET | `/api/careers/{id}/matches/{mid}/games/{n}` | One game, with the full timeline if you played it |
| GET | `/api/careers/{id}/live` | Your series in progress: lineups, champion select, suggestions |
| GET | `/api/careers/{id}/meta` | Champion tiers on the current patch and recent patch notes |
| GET | `/api/careers/{id}/negotiate/{pid}` | Contract talks with a player: the agent's ask, budget room, any counter-offer |
| GET | `/api/careers/{id}/training` | Load, focus areas, set plays, each player's condition and own training, the analyst's latest review |
| GET | `/api/careers/{id}/manager` | You: background, attributes, who does what, your record (seasons, competitions, trophies, clubs, reputation over time), and the rules and backgrounds to create the manager |
| GET | `/api/careers/{id}/board` | Objectives (with the meeting's options), confidence, reputations, finances, job offers, clubs looking for a head coach and your reach |
| GET | `/api/careers/{id}/transfers` | The window: bids for your players, your bids, listed players, moves, players who want to talk |
| GET | `/api/careers/{id}/shortlist` | Your shortlist, with the analyst's latest report on each player |

Actions are JSON objects tagged by `type`:

| Action | Body | When |
|---|---|---|
| `draft_pick` | `player` | Your pick in the draft |
| `draft_staff` | `staff` | Your pick in a staff round |
| `draft_pass` | | Skip a bench-round pick |
| `draft_auto` | | Let the assistant make this pick |
| `draft_sim` | | Let the assistant finish the draft |
| `draft_next` | `until_mine` (optional) | The AI team on the clock picks, or every AI team up to your pick. Does nothing on your turn |
| `advance` | | Continue: the next day |
| `set_lineup` | `lineup` (role to player id) | Before champion select |
| `set_tactics` | `tactics` (`style`, `lane`, `objectives`) | Any time |
| `start_champ_select` | | Your match is waiting |
| `ban` | `champion` | Your ban turn |
| `pick` | `champion`, `role` | Your pick turn |
| `auto_select` | | Let the assistant finish champion select |
| `opponent_turn` | `until_mine` (optional) | The opponent's next ban or pick, or all of them up to your turn. Does nothing on your turn |
| `play_game` | | Champion select is done |
| `next_game` | | After a game, starts the next one or ends the series |
| `sim_series` | | Auto-draft and play out the rest of the series |
| `read_message` | `id` (optional) | Mark one inbox message, or all, read |
| `offer` | `player`, `salary`, `years` | Offer a free agent a contract, or extend one of your players in their last season |
| `accept_counter` | `player` | Sign at the salary the player countered with |
| `release` | `player` | Let a player go, paying half the rest of the contract |
| `next_season` | | In the off-season, skip to the new season; unanswered bids lapse |
| `board_meeting` | `stances` (objective id to -1, 0 or 1) | When the board is waiting to meet you |
| `accept_job` | `team` | After a sacking, take one of the offers; or take a club's offer while you have a club |
| `apply_job` | `team` | Apply to a club looking for a head coach |
| `decline_job` | `team` | Turn a club's offer down |
| `staff_offer` | `staff`, `salary`, `years` | Hire a coach or analyst, or extend one of yours in their last season |
| `staff_accept_counter` | `staff` | Accept a staff member's counter-offer |
| `staff_release` | `staff` | Release one of your staff |
| `set_training` | `load`, `focus`, `play`, `clear_play` (all optional) | Any time |
| `set_player_training` | `player`, `attribute`, `champion` | Any time, for one of your players |
| `set_play` | `play` (or none) | After champion select, before the game |
| `transfer_bid` | `player`, `fee` | Off-season, for a player under contract elsewhere |
| `withdraw_bid` | `offer` | One of your open bids |
| `respond_offer` | `offer`, `response` (`accept`, `reject`, `negotiate`) | A bid for one of your players |
| `transfer_list` | `player`, `listed` | Tell other clubs a player is for sale |
| `talk` | `conversation`, `choice` (`vital`, `promise`, `final`) | A player asked to talk |
| `adjust_budget` | `budget` | After the draft, to move money between the salary budget and the bank |
| `create_manager` | `background`, `attributes`, `name` and `country` (optional) | Once, before anything else: in a new career after picking the club, and in a save from before managers |
| `set_duty` | `attribute`, `who` (`manager`, `staff`, `auto`) | Who does one of the six staff jobs |
| `set_franchise` | `player` | While your club has no franchise player: name one of your players |
| `shortlist` | `player`, `on` (optional, `false` takes the player off) | Star a player: the analyst goes to watch them |
| `scout_player` | `player` | Ask the analyst for a new report on a shortlisted player |

An action that does not fit the career's current state returns 409 with the reason, for example drafting a second mid laner while you still have no jungler. Until your manager is created the board meeting, the draft, `advance`, `next_season`, bids, contract offers and budget moves wait, and `draft_next` does nothing. While the board is waiting to meet you, the draft, `advance` and new player signings wait too. While you have no club, only `accept_job`, `read_message` and `create_manager` work.

The AI never moves on its own after one of your actions. In the draft and in champion select the client asks for each AI move with `draft_next` or `opponent_turn`, so it can give the other teams a few seconds per turn and offer a skip button.

## The rules in numbers

**Ratings.** Every rated stat comes from the player's games on gol.gg. Each stat is turned into a z-score among the players of the same role in the same league. Recipes of those make eight attributes on a 1-20 scale:

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

The recipes differ a little by role: a jungler's laning counts first bloods, and a support's mechanics come from KDA and first bloods.

An average player sits at a baseline set by league strength. That is 15.5 for the LCK, 15.2 for the LPL, 13.7 for the LEC, 12.5 for the LCS and the LCP, 11.6 for the CBLOL and about 7 for a mid-sized ERL. The tier-one leagues sit closer together than one line through every league's strength would put them, so the best of the LEC and the LCS hold their own against LCK starters. Small samples are pulled towards the average. Form covers three seasons: 2026 counts fully, 2025 at 0.6 and 2024 at 0.3, each judged against the players who share the 2026 league and role. A player with no earlier season is judged on 2026 alone.

The overall rating (30-99) weighs the attributes by role, so a support's vision counts most and a bot laner's mechanics and teamfighting count most. It blends that form (0.45) with the career (0.25: career win rate held back for short careers, KDA, longevity), the international record (0.15: games and win rate at First Stand, MSI and Worlds since 2024) and how the 2026 team did (0.15). The blend keeps each league's average and spread, so it only reorders players inside a league ([ADR 0014](docs/adr/0014-ratings-blend-three-seasons-career-and-internationals.md)). A long career adds up to 3 points of big-match experience. Potential is higher for players with fewer career games.

**Salaries and money.** An asking salary doubles roughly every 7 overall points. It is scaled by region (Korea 1.0, China 1.15, EMEA 0.9, NA 1.1, Brazil 0.45, Pacific 0.55) and by reputation.
- **The salary budget.** In the first season it covers the franchise player, four players of the average quality a draft hands out, average staff and a bench player; the four players and the staff are scaled by prestige from 0.82 to 1.18. From then on the board sets it every off-season: five starters and a bench player (0.4 of a starter) at the region's going rate, scaled by reputation from 0.8 to 1.25, plus 80k for staff (92k in China), and never less than 3 percent above the contracts already signed. The objectives meeting then moves it 4 percent a step.
- **The bank.** The owners fund the salary budget, so every week what the payroll leaves of it goes to the bank, with sponsors (reputation x 6k a year) and prize money. Every off-season the owners add 15 percent of the budget for a one-star club, up to 35 percent for a five-star one, for transfers. Transfer fees come out of the bank. The bank starts at a quarter of the first season's budget.
- **Adjusting budgets.** As in Football Manager, the manager can move money between the salary budget and the bank at any time after the draft, and AI clubs do the same when a signing needs it (see the transfer window). The budget is a yearly figure, so a thousand of it is worth a thousand divided by 52 for every week left until the board sets the next one after Worlds: with 26 weeks to go, cutting the budget by 100k puts 50k in the bank, and raising it costs as much. The budget never drops below the contracts it pays, and the bank never below zero. Bonuses paid as a share of the budget go by the budget the board set ([ADR 0017](docs/adr/0017-moving-money-between-the-salary-budget-and-the-bank.md)). Fees agreed and waiting on personal terms are set aside: new bids and the slider only use what is left, and personal terms cannot be signed while the bank cannot pay the fee.
- **Debt.** The owners no longer clear the manager's debt when a season starts. While the bank is below zero the board pays for no transfers and loses a point of confidence every week, two once the debt passes a quarter of the salary budget. Past that quarter it cuts every player's wage by 10 percent for the rest of the contracts (staff keep theirs), at most every eight weeks: every player loses 20 morale, and some want to leave, the more the bigger the name (not the franchise player). The next transfer grant pays the debt off first ([ADR 0018](docs/adr/0018-debt-has-consequences.md)).

**Champions.** In a game a champion adds or subtracts from its player's rating:

- **Comfort** comes from mastery, which grows with career games: -2.6 on a champion never played, +1 to +3 on a comfort pick, +3 to +5 on a signature.
- **Meta power** on the current patch counts at 0.8x and runs from about -3 to +5.
- **Off role** costs 5.

Compositions with a single damage type lose 2, and those with nobody in front lose 1.5. A tactic that matches the composition's power curve adds 0.8, and one that goes against it costs 0.4. 53 hand-picked champion duos from riftlike add 0.6 per point, for example Xayah and Rakan +2 or Jarvan IV and Orianna +1, and a few known bad pairs subtract.

**Champion select.** A pick is scored as the player's comfort and meta power, plus what it does for the composition so far, plus half its lane edge against the enemy laner if that one is already picked.
- **The composition.** The missing damage type is worth +1, or +2 in the last two picks. Piling on the damage type the team already has, while the other one is still missing, costs 0.5, or 1 in the last two picks. A first frontliner is worth 0.6, or 1.8 late. Fitting the game plan adds 0.6, and going against it costs 0.3. Duos count as above.
- **Bans.** A ban is scored by the best enemy player still to pick on the champion. Combos with their picks and the lane it would win against ours are added. Four tenths of what the champion would be worth to us is taken off.
- **The grid.** The AI uses these scores. The manager's grid shows them, with every reason, as whoever drafts for the club reads them (see Drafting under Staff). The arrows on the grid follow simple thresholds:

| Arrow | Pick | Ban |
|---|---|---|
| Up | 2 or more | 2.5 or more |
| Double up | 4.5 or more | 4.5 or more |
| Down | -1.5 or less, with a lane, composition or meta reason | under 1, when we could play it ourselves |
| Double down | -5 or less, with such a reason | |

A champion is never marked down just because the player has not played it; its mastery badge already shows that.

**Chemistry.**
- Pairs that share a language count towards communication. Europe and North America play in English, Korea, China, Brazil and the Pacific in their own languages, and anyone playing abroad speaks English.
- Pairs that played together in 2026, or have started 20 games together since, count towards familiarity.
- The bot lane pair weighs most, then jungle and mid.
- A shotcaller with leadership 15 or more is worth +1, and a lineup whose best leader is under 9 loses 1.

Chemistry runs from about -5 to +4 on top of the team's average.

**Contracts.** The draft pays the asking price. After the draft, every deal is negotiated.
- **The ask.** It is the market rate for the player's current rating. A player asks 0.4 percent more for every point their reputation is above your club's, and up to 10 percent less from a bigger club, and a reluctant one (see the transfer window) 15 percent more on top. Your own players ask more when their morale is low, and a free agent without a team mid-season asks 10 percent less. Prospects want three seasons, players past 900 career games want one, everyone else two.
- **The floor.** Each player has a hidden floor between 86 and 97 percent of the ask, and every year away from the preferred length counts as 5 percent off the offer.
- **The answer.** At or above the floor, the player signs. Within reach, the player counters halfway between your offer and the ask. Under 60 percent, or after three failed rounds, the agent walks away for three weeks.
- **Rosters and releases.** A roster holds 8 players, and every offer has to fit the salary budget. Releasing a player costs half of the remaining contract. The franchise player cannot be released or listed, and neither can your only player in a role.

**Staff.** Every team has an assistant coach and an analyst, with attributes from 1 to 20. An empty seat counts as 4, except at your club, where you do that work.

| Attribute | What it changes | At 4 | At 10 | At 20 |
|---|---|---|---|---|
| Development | weekly chance that a player grows towards potential | x0.76 | x1 | x1.4 |
| Drafting | how whoever drafts for you (your coach, or you, see You) weighs the reasons in champion select | up to 56% off, misses lanes and combos | up to 35% off | exact |
| Drafting | how far an AI team wanders from its best pick | x1.4 | x1.1 | x0.6 |
| Motivation | morale lost with a defeat | -5 | -4 | -3 |
| Motivation | weekly morale recovery towards 70 | 1/9 of the gap | 1/7 | 1/4 |
| Motivation | one game together counts as | 0.85 | 1 | 1.25 |
| Motivation | the chance to burn out from 60 fatigue | x1.1 | x0.95 | x0.7 |
| Teaching | mastery from playing a champion on stage | x0.76 | x1 | x1.4 |
| Teaching | weekly chance a starter practises a top meta champion of their role (+2 mastery, up to 55) | 10% | 25% | 50% |
| Scouting | the report on the next opponent: 1 basic, 2 adds what they play and their game plan, 3 adds ban priorities and their key player, 4 adds weak spots | level 1 | level 2 | level 4 |
| Meta reading | the patch preview: 2 or 4 days ahead, names the nerf targets, with odds from 15, and spots mid-season updates from 12 | 2 days, some names wrong | 2 days, top 4 | 4 days, odds |

The misjudgements of whoever drafts are fixed for each person, so they always over- or underrate the same things. Teaching also speeds up team areas, set plays and champions a player learns on their own, and the analyst's scouting decides how often the game review reads the team right. Staff sign for two seasons. AI teams keep theirs about two times in three. When the transfer window closes the board fills any empty seat.

**The staff market.** Every coach and analyst has a page, and Scouting lists them next to the players ([ADR 0020](docs/adr/0020-the-staff-market.md)). Talks work like a player's: they ask their salary (15 percent more to leave a club they work for), settle for 85 to 95 percent of it over two seasons, and walk away for 30 days after three offers too low. Someone rated 55 joins any club; every 8 points more wants another star of club reputation, give or take one. Staff of another club cost compensation, half of what is left on their contract, and their club appoints someone else at once. Your own staff no longer renew themselves: extend them in their last season or they leave on free agency day. Releasing costs half of what is left on the contract. Their salaries count against the salary budget. Every off-season some of the players who retire join the market (the better and longer the career, the likelier; supports and junglers often as analysts), and every region gets a coach and an analyst nobody has heard of, mostly ordinary, a few very good.

**You.** The manager has the same six attributes as the staff and three of their own, all from 1 to 20 ([ADR 0021](docs/adr/0021-the-manager-is-a-person.md)).
- **Creation.** Every attribute starts at 4. Points take one to at most 15, and lowering one frees points. The pool is 36 points plus 0.6 a point of your reputation in your region above 60 (24 to 60).
- **Backgrounds.** A background adds a bonus on top:
  - a former pro: +3 drafting, +2 motivation, +2 teaching and 4 reputation;
  - a career coach: +3 development, +2 teaching, +2 man management and 2 reputation;
  - a former analyst: +3 scouting, +3 meta, +1 drafting and 1 reputation;
  - a newcomer: five more points.
- **Who does what.** For each staff attribute you choose who does the work, as Football Manager's responsibilities do: you, the staff member, or Auto (the default), whoever is better at it now. An empty seat is yours. When you draft, champion select is your read: the live view's `reader` says whose it is.
- **Negotiation.** The hidden floor of player and staff salary talks moves 0.6 percent a point from 10, down when better, but never above what they asked. A selling club takes up to 6 percent off its asking fee for a good negotiator; a poor one pays the asking fee.
- **Man management.** +2 percent a point above 10 when you tell a player they are vital, and 2 percent less a point below it. The weekly chance an unsettled player settles scales from x0.64 at 1 to x1.4 at 20.
- **Tactics.** Set plays are learned at x0.64 the speed at 1, up to x1.4 at 20, and work 1 percent more often a point above 10 and 1 percent less a point below it, in the game as in the play picker.
- **Older saves.** A save from before managers had attributes opens without a manager. The actions that need one wait until it is created, with points from the reputation earned so far.

**Training.** Every Monday each team plays out a week of scrims. AI teams train at the load their coach would recommend, on their weakest area.

| Load | Team areas | Fatigue a week | Sharpness a week |
|---|---|---|---|
| Light | x0.5 | +0 | -8 |
| Normal | x1 | +8 | +2 |
| Heavy | x1.4 | +16 | +5 |
| Intense | x1.8 | +26 | +7 |

Set plays are learned at x0.6, x1, x1.3 and x1.5 of the normal speed, and a week's growth is x0.7, x1, x1.2 and x1.4.

- **Condition.** Rest takes 28 fatigue off a week and every game on stage adds 4 fatigue and 1 sharpness. A player loses a point of power for every 30 fatigue and every 20 sharpness under 70, and gains one for every 20 over it. From 60 fatigue a player may burn out for three weeks: 4 points of power lost, 10 morale, no development. Under 40 sharpness a player is complacent.
- **Team areas.** Five areas on the 1-20 scale: early game, objective control, teamfighting, macro and closing out games. One focus trains an area at 0.18 x load x teaching a week, two at 60 percent each, slower as it gets higher. Out of focus an area gains a little, and one above about 10 slips back. Every new starter after a transfer window costs 6 percent of what each area holds above 5.
- **Players.** A player can work on one attribute (most of their weekly growth goes there, and a little keeps coming past their target), learn one champion (about 4 mastery a week, up to 75), or both.
- **Growth.** A week's quality is the load, the coach's development, morale, sharpness and whether the player starts; a normal week for a starter with an average coach is 1.0. The potential the scouts show is an estimate: the real ceiling is fixed per career, up to 3 points either side for an established player. A rookie's runs from 11 below to 3 above, 4 below on average, so more than one rookie in three ends 5 or more points short and one in ten a little past it. A player heads for that ceiling plus 4 points for every point of average quality above 1, at most 2 past it, or minus below it, so good training takes a player a little past their potential and poor training leaves them short. A week's chance to grow is 5 percent for every point between a player and their target, at most 45 percent, times the week's quality.
- **The analyst's review.** Every six games the analyst reads the last ten: gold at 15 minutes, leads of 3,500 or more thrown away, long wins, teamfights, dragons and Barons, towers. The two areas that cost most are recommended. A weak analyst gets it wrong more often.
- **Predictions.** The day before every split of your league and every international event, the analyst's predictions arrive in the inbox: every team in the order the analyst expects them to finish (with the playoff line, or how far each goes at an event), a dark horse, and where your team is picked against the board's goal. The analyst ranks teams by their power score plus 25 Elo for every point of their starting five's average overall, misreading each by up to 6 Elo for every point of scouting under 20 (predictions.py).

**Set plays.** Nine plays, from a level 1 invade or a Fnatic bush to a Baron bait or a 1-3-1 split push. A team knows two or three at the start and learns others by drilling one at a time: 3 to 6 weeks at a normal load. From 40 percent learned a play can be called, once a series, after champion select. It works 30 percent of the time, plus 45 for how well it is learned, plus 2.5 per point of the team's skill in the area behind it above 10, minus 1.5 per point of the opponent's above 10, plus or minus up to 10 for how the composition suits it, plus 1 per point of your tactics above 10 at your club (less below it), between 10 and 90 percent. When it works it gives what it is built for (first blood, a lane, both Voidgrubs, two dragons, a won fight at Baron, towers); when it fails it backfires. When both teams call the same play they clash: two sides about as well prepared cancel each other out a third of the time, and otherwise the better prepared side is likelier to win it and takes a big swing, such as a 4 for 0 when two tower dives meet.

**Commentary.** A game's timeline reads like a broadcast. Every fight with a triple, quadra or pentakill gets a caster's call for it ("QUADRA KILL for CAPS on Ahri!"), and six fights in ten get one for the play that won them, from the winning champion's class and ultimate ("ZEUS with a 4-man Unstoppable Force!", or for a fighter "dives the backline"), just before the fight's result. The calls are events of kind `highlight`; the ultimates' names come from Data Dragon (scripts/build_champions.py).

**The board.** Objectives come from where the club's reputation ranks it in its league: the two biggest clubs are asked to finish at most one place below where their reputation ranks them (the favourite in the top two), the others at most two places below it, and the easiest target is avoiding last place. Worlds ranges from a bonus to the semi-finals for the favourite of Korea or China. A board met once Worlds is set asks nothing of it from a team that is not in it.
- **Confidence.** It starts at 60. A split target met adds 6, more for a promise or a better finish; a miss costs 5 plus 3 a place, up to 14. Worlds is worth 8 either way, plus 3 a step above the target or 4 a step below it; when Worlds is only a bonus, qualifying is worth 4 and each step after it 2, and missing costs nothing. A target lowered at the meeting costs 2 more when it is missed. A title adds 5, an international one 8. Each new season starts two-fifths of the way back to 60.
- **Bonuses.** First Stand and MSI are not objectives but bonuses: qualifying for First Stand is worth 4 confidence and reaching its final 3 more; qualifying for MSI 4, its semi-finals 3 and its final 3 more. Each also adds a point of manager reputation and a sponsor payment of 3 to 5 percent of the salary budget. Missing them costs nothing.
- **Reviews.** Below 22 after a review, the board warns you; the next review still below 22 is the sack. Back above 35 lifts the warning. Nobody is warned in their first 75 days at a club.
- **Reputation.** A team's reputation starts at the organisation's prestige and moves with results: +3 for a domestic title, +1.5 for a final, -1.5 for the bottom two, up to +12 for winning Worlds. Every off-season it drifts a tenth of the way back to prestige. Stars are (reputation - 50) / 10, in half stars. Every club has two ratings: world stars weigh its reputation by its region's strength in the global power rankings (50 + (reputation - 50) x strength / 100, so the strongest region loses nothing and a top LCP club drops about a star), and region stars measure it against the biggest club of its region, who sits at 100. Budgets and sponsors stay on the plain reputation. The manager is rated twice too: in their region and in the world. They start in their region at 0.6 x the club's reputation + 28, and the world weighs that by the region's strength. Objectives and titles add to both: the region gets the full amount, the world as much as the region's strength (international results in full). A gain counts in full up to 70 and less and less above (57 percent at 85, 29 at 95, never under 15); a loss counts in full. A sacking costs 8 the same way. Where the manager never worked they are known by their world reputation. A club of the manager's region compares its region stars with theirs; any other club compares world stars. A sacked manager gets offers from three clubs at most one and a half stars above them on that scale.
- **Global power rankings.** Every tier-one team and every region has an Elo, as in Riot's Global Power Rankings. Every series moves the teams': the winner takes points from the loser, more for an upset, a longer series (a Bo3 counts 1.5 times, a Bo5 twice) and a bigger stage (K 16 for a regular season, 20 for playoffs, groups and Swiss, 12 for a play-in and 36 for international knockouts). Regions trade points at half that pace, and only when teams of two regions meet, so a region rises only by beating other regions. A team's power score is 80 percent its Elo and 20 percent its region's. A region's strength is 100 for the strongest and a point less for every 20 Elo below it, at least 50; it starts at the fixed league strengths (LCK 100, LPL 98, LEC 88, LCS and LCP 80, CBLOL 74), which player ratings keep.
- **Coaches on the move.** An AI club's coach stands in for its head coach. Each club is expected to finish where its reputation ranked it in its league when the season started, and to reach Worlds when that rank is within its region's slots. After the season it weighs each split (a place of grace, then a point for every place lower) and a missed Worlds (three points): the chance to sack the coach is 4 percent a point, plus 35 for a missed Worlds, at most 85, and a third of that for a coach in the job less than four months. After a split, a favourite (expected in the top three) four or more places lower sacks its coach 30 percent of the time. A vacancy stays open two weeks. A club within your reach (up to 1.5 stars above you, region stars in your region and world stars elsewhere) and about as big as yours approaches you 40 percent of the time plus 10 a star of room, though not in your first half season at a club (180 days); you can also apply anywhere: out of reach is a no, in reach an offer 35 percent of the time plus 25 a star of room, otherwise the club appoints someone else. An offer is open a week, but one made from the end of the last split until the Worlds final stands until two weeks after the final, so you can finish Worlds first; taking it ends every other offer and moves you to the new club with a new board ([ADR 0019](docs/adr/0019-coaches-on-the-move.md)).

**The transfer window.** It runs from the day after the Worlds final to January 16th, and Continue moves through it a day at a time.
- **Value.** A player's market value is the salary their rating and reputation command, times 0.5 plus 0.55 per season left on the contract, plus a share for room to grow. The selling club asks 1.3 times that for a starter, 0.85 for a bench player, 1.25 more for its only player in a role and 0.8 for a listed or unsettled one. A franchise player is not for sale, with one exception: yours cannot be listed, but now and then a rich club bids at least twice his market value (and goes up to three times it if you ask for more). Sell him, or see him retire, and you have 14 days to name the next one on a player's page; otherwise the board names your best player. AI clubs name theirs at once ([ADR 0023](docs/adr/0023-the-franchise-player-has-a-price.md)).
- **Bids.** A bid at the asking fee is agreed and the player's contract talks open. One within three quarters of it gets a counter. A lower one is turned down. Every failed bid in the window counts: after the third the club ends the talks and takes no bid for the player for two weeks. The fee is paid when the player signs. While a fee is agreed no other club bids for the player; if they leave the selling club before signing, because their contract runs out or they retire, the deal is off and the inbox says so.
- **Interest.** A player's standing is their reputation, or their current club's reputation minus 12 if that is higher. They see a club of their own region on the region's scale and any other on the world's, and compare their standing with the buying club's reputation on that scale minus 10: more than 20 above it and they refuse to talk, more than 8 and they are reluctant and ask 15 percent more. An unsettled player is 8 points easier to tempt.
- **AI clubs.** Each day every AI club has a 4.5 percent chance to act, and one with a hole in its five (an empty role, or a starter 15 below the other four) acts every day until it is filled. It signs a free agent for an empty role, or one more than 2 better than its weakest starter (from its own region, or from anywhere when nobody better is free at home), or bids for a player at least 4 better from a club no more than 5 reputation above its own (any club, for an unsettled player). It pays the way you can: a salary beyond its budget raises the budget, paid from the bank at what it is worth that week, and a fee beyond what the bank spares comes out of wage budget it will not use; it keeps 30 percent of its bank after a deal and moves nothing while in debt. Another AI club answers at once; you get four days. Their bids for your players are 0.9 to 1.2 times the market value; ask for more and they raise it 12 percent while it stays within 1.35 times the market value and their bank, or walk away. Players who moved are not sold on in the same window.
- **Players' feelings.** Turn down a club 3 reputation above yours, or one at least as big when the player's reputation is close to the club's, and the player loses 8 morale and asks to talk. You can tell them they are vital (works about half the time, more with a good reputation, for a starter), promise to let them go next off-season, or say the decision is final (18 morale, and they may ask to leave). Turning down the next big bid after a promise breaks it: 30 morale and a player who wants out. A "vital" that is not believed costs 12 morale and leaves the player unsettled. After a broken promise a second one is not believed, and "vital" works 25 percent less often. A talk ignored for a week counts as the decision being final. Unsettled players drift towards 45 morale and play a point worse. Winning lifts them anyway (a won series is +4 for the lineup): one still at 60 morale or more after the weekly drift settles with a 20 percent chance a week, so a starter on a team that wins most weeks settles within a month or two. A bench player who never plays stays unsettled until the next season (an even chance to settle) or a move.
- **Free agency and the close.** Contracts that end with the season run out on December 1st; until then you can extend them. When the window closes every club fills its empty roles from the free agents and its empty staff seats, an AI club replaces a starter who is a hole if anyone better is free, and open bids and agreed fees lapse. During the season an AI club with a hole signs a better free agent on a Monday, if one will come; players under contract wait for the window.

**The shortlist.** Star a player and the analyst goes to watch them. The report lands in the inbox two days later for a player in your league, four for one elsewhere in your region and seven for another region, plus up to two more with a weak analyst.
- **Potential.** The report puts the player's hidden real potential in a range: six points either side at scouting 1, a point and a half at scouting 20, and a third narrower with each new report on the same player.
- **The verdict.** A grade from A+ to D, from how much better the player is than your starter in the role now, or 0.6 times how much better they could become: 10 or more is A+, 6 A, 3 B, 0 C. With it come strengths and weaknesses, best champions, this season's form, whether they would come, their contract, value, asking fee and the salary they would want.
- **Watching.** A shortlisted player who moves or becomes a free agent is worth a message; one who joins your club comes off the list. The shortlist holds 40 players.

**Rookies.** From the first off-season on, every region gets a class of rookies for the next season, 1.2 per tier-one team: 30% busts (potential 40-58), 35% journeymen (55-68), 22% decent (65-76), 10% prospects (75-86) and 3% stars (82-88), and the first of each region's class is its headline rookie, a wonderkid (90-98) 30% of the time. Korea and China add 2 to every potential. They start 14 to 28 points below their potential, and those with 85 or more 18 to 26 below, so a prospect needs about three seasons to get near it. Most come through an academy or ERL team of their region, the rest straight from solo queue; all of them are free agents. The potential shown is the scouts' first guess, so send the analyst ([ADR 0015](docs/adr/0015-rookie-classes-in-the-career.md)).

**Retirements.** At the start of every off-season some players say the next season will be their last, and retire when it ends. There are no ages in the data, so a career age stands in: 18 at debut, a year per 90 career games up to eight years' worth, a year per season played in the game. From 25 the chance a season is 3%, rising to 25% at 30 and 50% from 32; under 25 only players rated below 60 give up. Players rated 85+ do not stop before 30 and are a third as likely after it, players rated 80+ half as likely, and legends still rated 80+ after a thousand career games five times less likely ([ADR 0016](docs/adr/0016-retirements-announced-a-season-ahead.md)).

**Off-season.** When Worlds ends AI teams decide on the contracts that end: they re-sign starters and anyone above their lineup's average more often than the rest. The franchise player renews automatically for three seasons. A player with fewer than 600 career games closes 12 to 30 percent of the gap to their growth target, about 21 on average. Past 1,100 career games a player can lose up to 2.2 overall a year. There is no draft after the first season.

**Patches.** A new patch every two weeks from January 6th. The balance team nerfs up to 3-5 of the champions that were picked or banned most on the outgoing patch and buffs 3-6 weak champions at random, mostly ones nobody plays; a mid-season update makes two more of each. Every sixth patch is a mid-season update that also moves a whole class up or down by one. Every other champion drifts 3 percent towards the middle each patch. The first patch's meta comes from real 2026 pro presence.

**Games.** A game is simulated minute by minute.

- **Laning (1-14).** Lanes trade gold by matchup, with solo kills and jungle ganks. Junglers contest voidgrubs at 6 and 10, the first dragons, and the herald at 14.
- **Drakes.** As on the Rift, the first two drakes are two different elements and the third a third one; the Rift then takes that element's form, and every drake after it, and the Soul, is the same. The Soul's power differs by element (Cloud +8, Mountain +3.5, Hextech +2.5, Ocean +2, Infernal and Chemtech +1.5), fitted so that the side with each Soul wins about as often as in ranked games (86.8 to 90.6 percent).
- **Fights.** From minute 15 fights break out most often around a live dragon, Baron or Elder; before that, a dragon turns into a fight 30 percent of the time. A fight is a logistic roll on the power difference plus gold lead and buffs (Baron +5, Elder +7, the Soul); from minute 35 the difference counts 1.25 times. The winner takes kills, the objective and towers.
- **The end.** The game ends when a side wins a fight with an inhibitor down and a buff or a big margin. From minute 55 every minute brings an Elder fight that can end it.
- **Team areas.** A team at 20 against one at 10 gets 1.5 power in the first 14 minutes and 1.2 in lane power for the early game, 0.5 of logistic edge in contested objectives, 2 power in fights for teamfighting and 1.5 in the gold drift after laning for macro. A team 3,000 gold or more ahead from minute 18 throws a fight it would have won 8.5 percent of the time, minus 0.45 per point of closing, and a good closer ends a game with a smaller margin.
- **Form on the day.** Each side also gets a random form of up to ±6.5. Blue side adds 0.4, and the loser of a game takes blue in the next. With the current tuning, a 4-point edge in team power wins about 65 percent of games, a 10-point edge about 85 percent and a 14-point edge about 93 percent.

## Data

- **Rosters and stats.** Rosters, roles, nationalities and 2026 stat lines for 27 leagues come from [gol.gg](https://gol.gg), and so do career champion pools, the 2024 and 2025 stat lines, the stat lines from the international events since 2024 that gol.gg has (no MSI 2025 or First Stand 2026) and 2026 champion presence. The scripts that fetch them are `scripts/fetch_golgg.py` and `scripts/fetch_meta.py`. Pages are cached in `.cache/`, so re-runs only fetch what is missing.
- **Logos and photos.** Team logos, league and event logos, player photos and real names come from the lolesports.com API through `scripts/fetch_lolesports.py`, which writes `app/data/lolesports.json`. Only URLs are stored, and the images stay on Riot's CDN. Every tier-one team, 195 teams in all, every league and about 1,320 of 1,368 players have one.
- **Staff.** Coaches and analysts of every tier-one team come from [Liquipedia](https://liquipedia.net/leagueoflegends) (CC BY-SA 3.0) through `scripts/fetch_staff.py`, which writes `app/data/staff.json`. The script makes one request every 31 seconds, as Liquipedia asks, and caches pages in `.cache/liquipedia`. Only names, positions and countries are kept. All 56 tier-one teams have staff there, 188 people in all. Ratings are this game's own, see [ADR 0010](docs/adr/0010-staff-from-liquipedia-with-own-ratings.md).
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
- the data, the draft rules and budgets, and round robin, single and double elimination shapes
- champion select with fearless, set plays, and determinism
- a full season through Worlds, the transfer window and into the next season
- the board's objectives, warnings, the sack and a new job
- training loads, team areas, burnout, set plays, growth and the analyst's review
- bids, counters, personal terms, players who ask to talk, and old saves
- the API from the board meeting to a played game, and the parsed save shared between requests
- rookie classes and retirements, the staff market, coaches on the move, the shortlist, money and debt
- the manager: creation, who does what, their own attributes, reputation in the region and the world, and the record
- the analyst's predictions before every split and event
- the global power rankings and the 2026 international places: MSI's play-in and byes, Worlds' fourth places and play-in, and the messages that announce them

The simulation prints the game win rate per gap in team power and who won each title over a few whole seasons. Its careers create a manager with the points spread evenly, as the tests do. The engine's constants at the top of `match_engine.py` were tuned against it.

## Structure

```
app/
├── main.py           app, CORS and routers
├── config.py         settings from LEAGUE_MANAGER_ environment variables
├── db.py, models.py  SQLite engine, the save table and played-game timelines
├── repository.py     load, store and list saves
├── routers/          catalog and careers endpoints
├── data/             leagues, teams, champions, gol.gg rosters, stats and meta, lolesports links, staff
└── game/
    ├── catalog.py    static world: regions, leagues, teams, players, champions
    ├── ratings.py    stat lines, careers and internationals to attributes, overall, potential, salary
    ├── rookies.py    a rookie class every off-season, kept in the career
    ├── retirement.py retirements, announced a season ahead
    ├── roster.py     current ratings, mastery, languages and chemistry
    ├── state.py      the saved career and the actions
    ├── rng.py        seeded randomness, stored on the career
    ├── errors.py     IllegalAction, answered with 409
    ├── draft.py      the first pre-season draft and budgets
    ├── contracts.py  negotiation, extensions and releases
    ├── transfers.py  the transfer window, fees, AI clubs' market, players who want to talk
    ├── offseason.py  the end of a season, development and the start of the next one
    ├── board.py      objectives, the meeting, confidence, the sack and new jobs
    ├── jobs.py       AI clubs sacking coaches, vacancies, offers and applications
    ├── staff.py      coaches and analysts: their ratings, and what each attribute changes
    ├── hiring.py     the staff market: talks, compensation, releases, new faces
    ├── scouting.py   the analyst's report on the next opponent and the patch preview
    ├── shortlist.py  the shortlist and the analyst's reports on players
    ├── finances.py   moving money between the salary budget and the bank
    ├── reputation.py team and manager reputation, stars, sponsors
    ├── power.py      the global power rankings: team and region Elo, region strength
    ├── predictions.py the analyst's predictions before every split and international event
    ├── manager.py    you: background, attributes, who does what, negotiation, man management, tactics
    ├── training.py   loads, team areas, players' own training, growth, the analyst's review
    ├── plays.py      set plays and how likely they are to work
    ├── calendar.py   the season: splits, First Stand, MSI, Worlds
    ├── competitions.py  round robins, single and double elimination brackets, Swiss, standings
    ├── patches.py    the meta and the patches that move it
    ├── champ_select.py  tournament draft order, AI picks and bans
    ├── match_engine.py  one game, minute by minute
    ├── matchday.py   series, fearless, the manager's live series
    ├── engine.py     career flow and the action entry point
    └── views.py      what the client renders
scripts/              data fetchers and the balance simulation
tests/                engine and API tests
```

League Manager was created under Riot Games' "Legal Jibber Jabber" policy using assets owned by Riot Games. Riot Games does not endorse or sponsor this project. League of Legends and all related names are trademarks of Riot Games. Statistics come from gol.gg, Games of Legends.
