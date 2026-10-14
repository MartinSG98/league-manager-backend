# 0022. Global power rankings and the 2026 international rules

Date: 2026-10-15
Status: Accepted. Amends [0012](0012-the-board-and-reputation.md)

## Context

How much the world counted a region's results was a fixed number per league: LCK 100, LPL 98, LEC 88, LCS and LCP 80, CBLOL 74. A region that won every international event never grew, and a domestic title in the LCP added 80 percent of its worth to the manager's world reputation however the LCP did abroad. With three splits a year, a manager who won them all gained about a star and a half a season, and nothing slowed it down near the top.

The international events also followed the 2024 formats: fixed places per region, a 10-team MSI and a 16-team Worlds. The manager asked for Riot's rules, where places depend on how regions perform, and for global rankings like the ones LoL Esports publishes.

## Decision

- **Global power rankings** (`power.py`), after Riot's Global Power Rankings:
  - Every tier-one team and every region has an Elo.
  - Every series moves the team Elo. The winner takes points from the loser, more for an upset, a longer series and a bigger stage. K follows Riot's table: play-ins 12, groups and Swiss 20, domestic playoffs 20, international knockouts 36.
  - Domestic series move points only between a region's teams. When teams of two regions meet, their regions trade points at half that pace, so a region rises only by beating other regions.
  - A team's power score blends its Elo and its region's, 80 to 20.
  - Everything starts from the fixed league strengths and the clubs' reputations, so nothing changes until the regions meet.
- **Region strength.** It is now the region's place in the rankings: 100 for the strongest, a point less for every 20 Elo below it, at least 50. It replaces the fixed numbers in clubs' world stars and in the share of domestic results the world adds to the manager's reputation. Player ratings keep the fixed strengths, which describe the 2026 data.
- **Harder at the top.** A gain to the manager's reputation counts in full up to 70, then less and less: about 57 percent at 85 and 29 percent at 95, never under 15 percent. Losses count in full. A background's reputation is fixed and unaffected.
- **International places, by Riot's 2026 rules** (`calendar.py`):
  - **First Stand.** Two teams from the LCK and the LPL, one from every other region, as before. The winning region sends both its MSI teams straight to the bracket.
  - **MSI.** 11 teams: two a region, one from Brazil. Every first seed, plus the First Stand region's second, go straight to a bracket of eight, seeded by how their regions did at First Stand. The other four second seeds play in (double elimination, Bo5) for the last place.
  - **Worlds.** 19 teams: three a region and two from Brazil, plus a fourth for the two best regions at MSI. The MSI champion is invited if it reached its region's playoffs. The last team of each of the four other regions plays in (Sep 24-28) for the 16th place in the Swiss stage. The Swiss pots go by seed, then by the regions' place in the rankings.
  - **Boards and AI clubs** count on the fourth Worlds place for the two strongest regions when they set expectations.
- **Messages.** The inbox announces each season's places when the season starts. It also says which region earned the MSI byes after First Stand, and which two send four teams to Worlds after MSI.
- **The screen.** `GET /careers/{id}/power` returns the rankings, which the client shows under Global Rankings.

## Consequences

A strong showing abroad now pays off at home: a region that keeps beating others gains strength, its clubs gain world stars, and its domestic titles count for more in the world. A region that keeps losing slides. The manager's reputation still rises with every title but slows near the top, so five stars take years rather than seasons.

International places now move every season with MSI. A region that did well can send four teams to Worlds while a traditional power plays in.

Careers already in a season keep the events that were already set. The new places apply to every event set from now on, and the rankings start counting from the next series.
