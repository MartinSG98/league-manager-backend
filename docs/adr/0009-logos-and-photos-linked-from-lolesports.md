# 0009. Logos and photos linked from lolesports.com

Date: 2026-10-11
Status: Accepted

## Context

A manager game is mostly people and clubs, and the scene knows them by their logos and faces at least as well as by their names. The first build showed each team as its tag on a coloured badge and each player as a name only. gol.gg, the source of everything else, has no logos or photos that are easy to use. Leaguepedia has both, but its API was rate-limiting this machine.

## Decision

`scripts/fetch_lolesports.py` asks the lolesports.com API for every league and every team with its roster. It uses the public key the lolesports.com site itself sends, and it needs two requests in all. It matches the results against this game's teams and players and writes `app/data/lolesports.json`, which holds:
- logo URLs for teams, leagues and the three international events
- photo URLs for players
- players' real names

Only URLs are stored and served. The images stay on Riot's esports CDN, and the client loads them from there.

Teams are matched by name, then by tag. A few teams go by another name on lolesports.com, such as Team Liquid Alienware; these carry their code in `teams.json`. Players are matched by name inside their matched team first, then anywhere in the same region.

## Consequences

Every tier-one team and every league has a logo, and about 97 percent of players have a photo and a real name. Nothing heavy is committed or served by this API. The client needs internet access for the images and has to fall back to the tag or initials when one is missing or fails to load. Logos and photos follow whatever Riot puts on its CDN. A rerun of the script picks up new logos, while a URL that disappears simply falls back.
