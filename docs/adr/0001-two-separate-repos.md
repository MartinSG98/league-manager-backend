# 0001. Two separate repos

Date: 2026-10-11
Status: Accepted

## Context

League Manager is a browser game with a server behind it, built the same way as riftlike. The game rules, the saved careers and the API are one concern, and the screens are another.

## Decision

Two repos. `league-manager-backend` holds the FastAPI service with the game engine, and `league-manager-ui` holds the React client. Both sit next to each other locally under one parent folder.

## Consequences

Each repo reads on its own and has its own history. A change to the API shape needs a matching change in the client, and there is no shared commit to tie the two together, so the client keeps a hand-written copy of the response types. The two run on their own ports, 8020 and 5190, which stay clear of riftlike's 8010 and 5180. The backend allows the client's origin through CORS.
