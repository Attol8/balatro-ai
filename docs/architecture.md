# Architecture

## Principle

Balatro is split into two different decision problems:

- tactical hand play: discard/play/card-order decisions inside a blind
- strategic run planning: shops, economy, jokers, vouchers, packs, tags

This project should use real Balatro code as the source of truth wherever it is
available. A hand-entered simulator is useful for cheap approximations, but it
must not become an unvalidated second game.

Local source/oracle inventory:

- Balatro Lua dump:
  `~/Library/Application Support/Balatro/Mods/lovely/dump`
- BalatroBot mod:
  `~/Library/Application Support/Balatro/Mods/BalatroBot`

The initial bet is a fast local simulator derived from the dumped Lua source.
BalatroBot is not the search environment. It is used to execute selected actions
in the real game and validate simulator predictions against real outcomes.

## Layers

1. `engine`
   - Readable reference implementation and source-derived model pieces.
   - Pure functions where possible.
   - Event logs explain why a score was produced.

2. `fast`
   - Integer-card hot-loop environment for search and training.
   - Fixed action ids and legal action masks for policy learning.
   - No BalatroBot, rendering, HTTP, or UI dependency in the training loop.

3. `balatrobot`
   - JSON-RPC client for live game control and validation snapshots.
   - Talks to the installed BalatroBot mod.
   - Converts BalatroBot card JSON into the fast simulator card ids.

4. `search`
   - Exhaustive or beam search over legal hand-play actions.
   - Runs against the local simulator, not the game process.

5. `actions`
   - Canonical policy action contract.
   - Converts tactical play/discard actions to fast action ids.
   - Converts every supported action to BalatroBot JSON-RPC method/params.

6. Future `agents`
   - Monte Carlo shop planner.
   - Learned value model once search baselines exist.
