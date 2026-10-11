# 0012. A board that sets objectives, and reputation in stars

Date: 2026-10-12
Status: Accepted

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
- **Warnings and the sack.** A review below 22 is a warning, and the next review still below 22 is the sack.
- **Grace.** Nobody is warned in their first 75 days at a club, and each new season pulls confidence part of the way back to 60. One terrible split never ends a career.

A sacked manager can only accept a job. Three clubs at most one and a half stars above the manager's reputation make offers, and the manager takes over one of them on the spot, mid-season or in the off-season, with a fresh board.

## Consequences

The objectives make the season's story explicit, and the meeting is a real trade between ambition and budget. A small club's manager is judged on staying off the bottom, not on titles. Getting sacked costs reputation and usually a step down, but the career goes on. Saves from before this change get reputations from prestige and a board meeting on their next action, covering only the splits not yet finished.
