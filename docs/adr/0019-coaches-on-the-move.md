# 0019. Coaches on the move

Date: 2026-10-13
Status: Accepted

## Context

AI clubs kept their coach whatever happened. In a playtest G2 missed Worlds and nothing changed. Their coach only left when a contract ran out, and even then only a third of the time. The manager only heard from other clubs after being sacked. The manager asked for two things:

- AI clubs that fall short should part ways with their coach.
- Clubs should approach the manager, and the manager should be able to apply, as in Football Manager.

An AI club has no manager of its own. Its coach seat (`TeamState.coach`, a real coach from the staff data) is the nearest thing to a head coach. At the manager's club the manager is the head coach and the same seat holds the assistant.

## Decision

- **Expectations.** At the start of every season each club is ranked in its league by reputation (`TeamState.expected`). A club whose rank is within its region's Worlds slots is expected at Worlds.
- **After the season**, the day after the Worlds final, every AI club weighs its season:
  - each split forgives one place below expectation, then counts a point per place;
  - a missed Worlds counts three more.

  The chance to sack the coach is 4 percent a point, plus 35 for the missed Worlds, at most 85. A coach in the job less than four months (`TeamState.coach_since`) gets a third of that. A seat left empty by a contract that ran out also becomes a vacancy.
- **After a split**, a favourite (expected in the top three) that finishes four or more places lower sacks its coach 30 percent of the time, with the same discount.
- **Vacancies** stay open two weeks:
  - **Approaches.** A club approaches the manager when it is within reach (at most 1.5 stars above the manager's reputation, as for job offers after a sacking) and at least about as big as the manager's club (within 5 reputation). The chance is 40 percent plus 10 for every star of room, at most 80.
  - **Applications.** The manager can apply anywhere. A club out of reach says no. A club in reach offers the job 35 percent of the time plus 25 for every star of room, at most 95, and otherwise appoints someone else at once.
  - **Offers** stay open a week and stop Continue. Taking one moves the manager:
    - their bids and talks at the old club end;
    - a new board meets them;
    - the board hires an assistant coach for the empty seat.

    The old club keeps the manager's assistant as its coach.
  - **Unfilled vacancies.** When a vacancy closes, the club appoints the best free coach it can afford.
- **News.** Sackings and appointments are news in the manager's league and for clubs with a reputation of 70 or more.

## Consequences

About 15 coaching changes a season among 55 AI clubs in simulation: about 10 after Worlds and 5 after splits, mostly clubs that missed a Worlds they were expected at. A successful manager now gets offers without being sacked first, and can move up. Moving down is possible through applications. Coaches are never generated: when the free pool of a region runs dry, a club may stay without a coach until the window closes, as before.
