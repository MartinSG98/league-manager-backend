# 0003. A career is one JSON document

Date: 2026-10-11
Status: Accepted, amended 2026-10-14

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

## Amendment, 2026-10-14: parsing once

Mid-season the document had grown to 4.7 MB (1,121 matches with their game records) and took about 80 ms to parse. Every request parsed it again, and the UI follows each click with five to seven reads, which made about half a second of parsing per click, growing through the season.

- **Reads** share one parsed career per save (`repository._parsed`), kept while the save's `updated_at` is unchanged. Only the two saves used last stay parsed (`CACHED_SAVES`): one parsed save takes about 40 MB, and one career is played at a time. Views never change the career, and a test checks that they leave it as it was.
- **Actions** parse their own copy, so one that fails half way leaves nothing behind. The copy they store becomes the one reads get.
- **The catalog with a career's rookies and new staff** (`rookies.catalog_for`) is built once per parsed career, and again only when a new class arrives. Both lists only ever grow.

Moving finished seasons out of the document remains the next step if it keeps growing.
