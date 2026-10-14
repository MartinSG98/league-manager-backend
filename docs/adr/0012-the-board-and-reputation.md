# 0012. A board that sets objectives, and reputation in stars

Date: 2026-10-12
Status: Accepted, amended 2026-10-14

## Context

The manager asked for a Football Manager style board. There should be a meeting at the start to agree on the team's goals, the board should track how the manager does against them, and the manager can be sacked for being terrible, without the game being too punishing. After a sacking, offers should depend on the manager's reputation. A two-star manager should not be offered a five-star club, but can be offered one of up to three and a half stars, or a one-star club. Club reputation should grow through tournaments and decide which players are willing to join.

## Decision

Teams and the manager have a reputation from 0 to 100, shown as stars: (reputation - 50) / 10, in half stars.
- **Teams.** A team starts at its organisation's prestige and moves with results. Every off-season it drifts back towards prestige.
- **The manager.** The manager starts below the club that hired them, rises with objectives met and titles, and drops with a sacking.

The board meets the manager when a job starts and at the start of every off-season.
- **Objectives.** It proposes a finish for each split and a target at Worlds, from where the club's reputation ranks it in its league.
- **Stances.** The manager can accept each target, ask for one step less, or promise one step more. Each step moves the salary budget by 4 percent.
- **Waiting.** While the meeting waits, the draft, `advance` and new signings wait too.

Confidence starts at 60 and moves when an objective is decided: after each split and after Worlds.
- **Bonuses.** First Stand and MSI are bonuses, not objectives: qualifying and a deep run add confidence, manager reputation and a sponsor payment, and missing them costs nothing. The manager asked for qualifying and doing well there to be rewarded.
- **Warnings and the sack.** A review below 22 is a warning, and the next review still below 22 is the sack.
- **Grace.** Nobody is warned in their first 75 days at a club, and each new season pulls confidence part of the way back to 60. One terrible split never ends a career.

A sacked manager can only accept a job. Three clubs at most one and a half stars above the manager's reputation make offers, and the manager takes over one of them on the spot, mid-season or in the off-season, with a fresh board.

## Consequences

The objectives make the season's story explicit, and the meeting is a real trade between ambition and budget. A small club's manager is judged on staying off the bottom, not on titles. Getting sacked costs reputation and usually a step down, but the career goes on. Saves from before this change get reputations from prestige and a board meeting on their next action, covering only the splits not yet finished.

## Amendment, 2026-10-14

A club is now rated twice, because one number put a big name of a weaker league level with the giants: GAM Esports showed three and a half stars, like Dplus KIA. The manager wanted a world rating and a region rating.
- **World stars** weigh the reputation by the league's strength: 50 + (reputation - 50) x strength / 100, so the LCK loses nothing and a top LCP club drops about a star.
- **Region stars** measure a club against the biggest club of its region, who sits at 100: reputation + 100 - the region's top.

Players see a club of their own region on the region's scale and any other club on the world's, so Korean stars think twice about the LCP and its own players are keener on it. Two clubs of the player's region keep their plain gap. Who calls first after a sacking, and whether a club with a vacancy is about as big as the manager's, go by world reputation; who is in reach is under Jobs below. Staff look at a club the way players from their region do. Budgets, sponsors and the transfer grant stay on the plain reputation, so no club's money changes.

The manager asked for the same two ratings for themselves. `manager_reputation` is now the world's, and `manager_standing` keeps the manager's reputation in each region they have worked in.
- **The start.** A new manager starts in their region where the single number used to start. The world weighs that by the league's strength.
- **Changes.** Objectives, titles and a sacking move the region's in full and the world's by the league's strength. First Stand and MSI bonuses, the Worlds objective and international titles move both in full.
- **Elsewhere.** In a region the manager never worked in, they are known by their world reputation.
- **Jobs.** A club of the manager's region compares its region stars with the manager's region stars; any other club compares world stars. The one and a half star reach holds on either scale.
- **Older saves.** Their single number becomes the manager's standing in their region, and the world's is derived from it.
