# 0003. A career is one JSON document

Date: 2026-10-11
Status: Accepted

## Context

A career holds:
- the contracts and form of about 1,400 players
- 54 teams
- a season of roughly a thousand series, with every game's picks and stat lines
- the meta
- an inbox

It could be normalised into tables or kept as one document.

## Decision

As with riftlike's runs, a career is one Pydantic tree stored as JSON in the `save` table. Day, phase and team are copied into columns for the save list.

Static facts stay out of the document. A player's 2026 stats, attributes and champion pool come from the catalog by id. The career only stores what has changed: growth, learned champions, contract and form.

The minute-by-minute timeline of a game the manager played is the one exception. It lives in its own `gamedetail` table, because nothing in the engine reads it again.

## Consequences

The engine has no database code and works on plain models. Loading and saving a career right after the draft takes a few milliseconds. By Worlds the document is a few megabytes and still loads in well under a second. If multiple seasons make it too large, finished seasons can move out to their own rows without changing the engine.
