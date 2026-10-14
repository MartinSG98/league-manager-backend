# 0011. Training: team areas, set plays and a weekly plan

Date: 2026-10-12
Status: Accepted, amended 2026-10-14

## Context

The manager asked for training that matters. The analyst should watch the games and say what to work on, such as closing games out or the early game. Training it should make a throw, or getting crushed early, less likely. Teams should rehearse set plays like a level 1 invade or the Fnatic bush and pull each one out once a series. Scrim load should matter: too much burns players out, too little makes them complacent, and the right amount depends on the time of the season. Players should develop over a year or two, sometimes short of their potential and sometimes past it.

The manager chose weekly settings over a day-by-day schedule, and set plays that are learned in training over plays every team knows from the start.

## Decision

Each team has five areas on the 1-20 scale: early game, objective control, teamfighting, macro and closing out games. They are properties of the team, not of the players, and they change the match engine in small, named places:
- early game: power in lanes and ganks
- objectives: the edge in contested objectives
- teamfighting: power in fights
- macro: the gold drift after laning
- closing: how often a team well ahead throws a fight, and the margin it needs to end

A team at 20 against one at 10 gains about what one or two rating points would give it. The balance harness still shows the win curve the engine was tuned to.

Every Monday a week of scrims is played out from three settings, which stay until the manager changes them:
- the load
- up to two focus areas
- one set play to drill

The load trades fatigue for sharpness and speed of progress. Fatigue and sharpness both change power on the day. Fatigue of 60 or more risks a three-week burnout, and low sharpness makes a player complacent. Match weeks add fatigue on their own, so the same load is right in the pre-season and wrong in the playoffs. AI teams follow the load their coach would recommend for the next seven days.

Set plays are drilled one at a time over 3-6 weeks and can be called from 40 percent learned. Each side calls at most one per game, after champion select, and each play once a series. A play's chance depends on how well it is learned, the team area behind it, the opponent's same area and how it suits the composition. It runs at its minute of the game and either gives its edge or backfires, and the playback shows which.

Players can also work on one attribute or learn one champion. Long-term growth heads for a ceiling that is hidden and fixed per career, up to six points either side of the potential shown. That ceiling is moved up or down by the average quality of the player's weeks: load, the coach's development, morale, sharpness and playing time.

Every six games the analyst reads the team's last ten from new fields on each game record: gold at 15, the biggest lead each side had, fights won, leads thrown away, dragons, Barons and towers. The analyst recommends the two areas that cost the most, and a weak analyst gets it wrong more often.

## Consequences

Every week has a decision with a cost, and the analyst points at the right one most of the time. A manager can leave everything at its default and still play. The AI keeps pace without a plan of its own. Old game records have no lead or fight data, so the analyst skips them. Team areas are a new axis of strength next to ratings, so the harness has to be rerun when their weights change.
