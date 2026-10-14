# 0021. The manager is a person

Date: 2026-10-14
Status: Accepted

## Context

The manager was only a name and a reputation. Everything a club did off the stage came from its assistant coach and analyst, so the manager had no strengths or weaknesses of their own, and no hire could make up for them. The manager asked for a Football Manager style manager:
- created after picking a club, with a few attributes and no looks;
- attributes that grow over time;
- the depth of hiring an assistant who is strong where you are weak.

Their running career had to keep going without a restart. In follow-up answers they chose:

- a background plus points to spend;
- Football Manager's responsibilities: the manager decides who does what;
- attributes that grow by doing the work (a later change);
- a "Me" screen with attributes, statistics and trophies.

## Decision

The career gets a `profile`: a background, a nationality, nine attributes from 1 to 20, and duties.
- **Attributes.** The six staff attributes and three of the manager's own: man management, negotiation and tactics. The staff attributes are the assistant coach's development, drafting, motivation and teaching, and the analyst's scouting and meta.
- **Creation.** Every attribute starts at 4. Points take one to at most 15, and lowering one frees points. The pool is 36 points plus 0.6 per point of manager reputation above 60, between 24 and 60, so a manager a bigger club would hire starts better. A background adds a fixed bonus on top and some reputation:
  - a former pro: +3 drafting, +2 motivation, +2 teaching, +4 reputation;
  - a career coach: +3 development, +2 teaching, +2 man management, +2 reputation;
  - a former analyst: +3 scouting, +3 meta, +1 drafting, +1 reputation;
  - a newcomer: no bonus and five more points.
- **Duties.** For each staff attribute the manager picks who does the work: themselves, the staff member, or Auto. Auto, the default, means whoever of the two is better at it right now, so a new assistant takes over what they do better. An empty seat falls to the manager. At the manager's club `staff.attribute` answers through `manager.does`, so every rule that read the staff's attribute now reads whoever does the work. Champion select is read the same way: the board and suggestions use the drafting of whoever drafts (`staff.coach_lens`), and the live view's `reader` names them. AI clubs are unchanged.
- **The manager's own attributes.**
  - Negotiation moves the hidden floor of player and staff salary talks by 0.6 percent a point from 10: down for a better negotiator, up for a worse one, but never above what the player or staff member asked (`manager.floor`). A good negotiator also gets up to 6 percent off a selling club's asking fee. A poor one still pays only the asking fee, since that fee is shown.
  - Man management adds 2 percent a point above 10 to the "you are vital" answer in a talk, and takes 2 a point below. It also scales the weekly chance that an unsettled player settles, from x0.64 at 1 to x1.4 at 20.
  - Tactics scales how fast set plays are learned the same way, and adds 1 percent a point above 10 to the chance a play works, or takes 1 a point below (`plays.manager_edge`), in the game's own roll as in the play picker.
- **Gating.** At the manager's club, the board meeting, the draft, `advance`, `next_season`, bids, contract offers and budget moves answer "Create your manager first" until the manager exists. On a timer, the draft does nothing.
  - A new career creates the manager right after the club is picked.
  - A save from before this change opens without a manager, and those actions wait until it is created. The points come from the reputation earned so far, and everything else in the career stays as it was.
- **The manager's record.** The career keeps the manager's clubs and seasons, so the "Me" screen can show them:
  - **Spells.** A spell runs from the day a job starts (`board.start_job`) until the next one or a sacking. Each competition keeps the day of its first series, so a manager who returns to a club gets a row for each spell, with its own record.
  - **Seasons.** A season's competitions are cleared when the next season starts. So when a season ends, each competition the manager's club played under them is kept with its series and games won and lost and its final place. The season under way is counted from its matches.
  - **Reputation.** A point is noted each day the reputation changes: the world's, the region's, and which region. A move notes one on its day, so each region gets its own line.
  - **Older saves.** A save from before this starts a spell on the day the current job began. Its earlier seasons keep only the finishes their summaries had, each typed as a league, First Stand, MSI or Worlds by its name.
- **Before creation.** Until the profile exists the staff do everything and the manager's own attributes count as 10, though the gated actions wait.
- **API.** `GET /careers/{id}/manager` returns the profile, the duties, the record and what creation needs: the backgrounds, the points and the limits.

## Consequences

Who the manager is now matters, and hiring has a reason beyond overall ratings. An assistant who covers your weak spot is worth more to you than a better one who does not. Once growth comes in, doing the work yourself while weaker becomes a real choice. The rules that used staff attributes did not change, only who answers for them at the manager's club.
