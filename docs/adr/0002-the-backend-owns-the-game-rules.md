# 0002. The backend owns the game rules

Date: 2026-10-11
Status: Accepted

## Context

A manager game is mostly rules: who can be drafted with the budget left, what a champion is worth to a player, which bracket match a winner moves to, how a game plays out. If the client knew any of them, its copy would drift from the server's.

## Decision

Every rule lives in `app/game`. The client posts one action at a time and reads views that already carry what it needs to draw:
- whether each pool player can be picked, and why not
- the assistant's pick and ban suggestions with their reasons
- standings and bracket slots
- the chemistry reasons

`app/game/views.py` is where those projections are built.

## Consequences

The UI stays a renderer and can be rebuilt freely. Views are larger than the raw state; a draft board carries the whole pool with a reason for each player. That is fine for a single-player game on a local server.
