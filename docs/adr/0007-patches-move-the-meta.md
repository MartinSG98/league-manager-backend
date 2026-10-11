# 0007. Patches move the meta

Date: 2026-10-11
Status: Accepted

## Context

A League season is shaped by patches. What is strong in January has been nerfed by spring. A static table of champion strength would make the best draft the same all year.

## Decision

Each champion has a meta power on the current patch, seeded from real 2026 pick and ban presence. Every two weeks a patch:
- nerfs what this career's pro scene picked and banned most on the outgoing patch
- buffs champions nobody played
- drifts everything slightly towards the middle

Every sixth patch also moves a whole class. Patch notes go to the inbox and the meta screen.

A player's mastery of a champion is separate from its patch power. A nerfed signature is still a comfort pick, just a weaker one.

## Consequences

The meta reacts to how the career is played, including the manager's own drafts. The AI drafts from the current patch, so it adapts too. Patch notes are generated flavour text on top of the numeric changes.
