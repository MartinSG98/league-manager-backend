# 0020. The staff market

Date: 2026-10-13
Status: Accepted, amended 2026-10-14

## Context

Coaches and analysts could only be picked in the first draft. After that the board hired them into empty seats and renewed the manager's own staff on its own. There was no page for a staff member, no way to negotiate with one, hire one from another club or let one go. The staff pool never changed either: nobody new ever joined it.

The manager asked for staff pages with salary talks and releases, for coaches and analysts in Scouting, and for new staff after the first season. In follow-up answers they chose:

- hiring free staff and, for compensation, staff of other clubs;
- new staff from retired players plus newcomers;
- negotiating renewals by hand, like players.

## Decision

- **Pages and Scouting.** Every coach and analyst has a page (`GET /careers/{id}/staff/{staff}`), and Scouting lists them by kind, region and free agents (`GET /careers/{id}/staff`).
- **Talks** follow the player model:
  - **The ask.** It is the staff member's salary, plus 15 percent to leave a club they work for. They settle for 85 to 95 percent, a fixed share per person and season, over two seasons. Each season more or less costs 5 percent of what the offer is worth to them.
  - **Walking away.** Three offers below that, or one under 60 percent of the ask, and they refuse to talk for 30 days. A counter-offer can be accepted.
- **Who comes.** A staff member rated 55 joins any club. Every 8 points more wants another star of club reputation, give or take one.
- **One seat per kind.** The manager has one assistant coach and one analyst, so the seat has to be empty to hire: release first.
- **Compensation.** A staff member of another club costs half of what is left on their contract, paid from the free bank (ADR 0018) when talks succeed. Their club appoints a replacement at once.
- **Own staff.** They no longer renew on their own. Their contracts run out on free agency day like the players', the contract warning names them, and they can be extended in their last season.
- **Releasing** costs half of what is left on the contract, as for a player. Staff salaries count against the salary budget, so talks check the room in it.
- **New faces** every off-season (`Career.new_staff`, overlaid on the catalog like rookies):
  - **Former players.** Each player who just retired after 300 or more career games joins with a chance of 20 to 70 percent, higher for a better rating. Supports and junglers become analysts half the time. Their skills come from their rating and career, leaned by their role.
  - **Newcomers.** Each region gets one coach and one analyst: 65 percent ordinary, 28 percent good, 7 percent very good.
  - **AI clubs** hire from the same pool.

## Consequences

Staff are now a market the manager works like the transfer market, and the pool renews itself as players retire. Generated staff carry no photo. A retired star often becomes a decent coach, so their old fans can follow them. The manager's own staff can now leave, so a manager who ignores the contract warning may start a season with an empty seat until the window closes.
