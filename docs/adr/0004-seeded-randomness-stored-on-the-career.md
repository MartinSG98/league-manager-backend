# 0004. Seeded randomness stored on the career

Date: 2026-10-11
Status: Accepted

## Context

Drafts, patches, champion select and every game roll dice. With a global random module, reloading during champion select could change the AI's answer, and a lost game could be retried.

## Decision

The career carries a Mulberry32 state (`rs`), the same generator riftlike uses, and every draw advances it. A game is simulated in full when the manager presses play, and the result is stored. The client only plays the timeline back.

## Consequences

The same seed and the same choices replay the same career, which is what the determinism test checks and what the balance harness relies on. Any new random draw shifts every later draw for a given seed. After an engine change, replays of old seeds therefore diverge, while saved careers carry on normally.
