# Minimal Balatro product: Astra low with numerical tools

## Outcome and scope

One installable CLI plays a single real Red Deck / White Stake, all-unlocked
Balatro game using gpt-6-astra at low reasoning effort through authenticated
Codex. A session-file mode also works with Codex/Claude without a model API
client. This replaces the old experiment collection. No model evaluation or
live-game run is permitted during this rewrite.

The confirmed Astra-high win remains evidence that the architecture can beat the
game. Low effort and the rewritten product have not been evaluated live; do not
relabel that win as a low-effort result or promise a win rate.

## Design

Real game -> typed public state -> numerical candidate analysis -> Astra low
with a compact persistent plan -> strict action validation -> one game action
-> settled observation and durable trace. Cashout is the only automatic action.
There is no fallback strategic policy, training, local game simulator, variant
registry, or ensemble. The model owns all meaningful decisions.

Retain the proven typed state, adapter, action legality, card/boss/consumable rules
and scorer. Extract tiny mechanics data instead of retaining strategy catalogs.
Replace the old coach, runner and CLI with a bounded single-game workflow.
The existing Codex CLI is authenticated via ChatGPT; model inference uses that
CLI, never a direct model API or API-key billing. Hard-code Astra/low as product
configuration. Keep requests and model working directories free of seeds and
private game state. Give failures explicit results; never retry uncertain game
mutations. Limit calls, output, and duration before any model/game action.

Smallest example: on a Ride the Bus hand, analysis includes a legal numbered-card
play and its score plus whether any scoring face resets Bus. The model can choose
a sufficient play that preserves growth. The prompt also explains Blue/Steel
held cards, deck edits supporting Blackboard, and rechecking Blueprint targets.
These are conditional mechanics, not a forced copy of the winning inventory.

## Product surface

- `balatro doctor`: read-only local CLI/auth/game readiness; no model inference.
- `balatro play --output RUN`: one game, Astra low via Codex, with explicit call
  and wall-clock limits; requires an idle game and matching profile.
- `balatro play --coach session --output RUN`: public request/response files for
  an existing Codex/Claude session; same validation, logs and limits.
- `balatro next RUN/public` and `balatro reply RUN/public`: session exchange.
- `balatro inspect RUN` / `balatro inspect evidence/first-win`: concise result
  and verified action/score evidence, entirely offline.

Package: `balatro_ai/game` contains preserved game rules; `analysis.py` prepares
scored plays and mechanism facts; `coach.py` handles bounded Codex/session
transport; `runner.py` executes and records one game; `cli.py` exposes commands.
Prompt and response schema ship as package data. Documentation covers installation,
startup, low-effort configuration, limits, failure behavior and the confirmed win.

## Cleanup and evidence

Pre-rewrite source and 2.6 GB of experiment outputs were preserved outside the
repository at `/Users/jacopo/Desktop/projects/balatro-ai-v2-history/seabass-before-product-20260907-002033`.
The owned paused runner and game server were stopped without playing another action.
Keep a compact first-win evidence bundle in `evidence/first-win` including the
compressed public trajectory, original prompt/model manifest and confirmed result.
Remove the old `balatro_ai_v2`, old tests/scripts/docs, candidate dependency/data,
and obsolete plans from the working product after migrating useful mechanics tests.
Git history and the external archive retain the old implementations.

## Acceptance

- No retained import requires an old simulator, baseline, candidate backend or
  deleted package. Package installs and console/module entrypoints work offline.
- All gameplay-model configuration is Astra/low; no direct model SDK or API-key
  path. Fake subprocess tests prove the emitted CLI flags and bounded execution.
- Tests verify public-only data, stale/illegal responses, model limits/timeouts,
  no mutation retries, premature victory flags, durable error results and the
  winning build's numerical/strategic affordances.
- Inspect the original winning trajectory offline under the preserved rules;
  report actual scoring discrepancies instead of claiming exact parity.
- Run local tests and packaging/CLI checks only. Never launch a model game or
  resume the previous pilot as part of acceptance.

## Completed verification — 2026-09-07

- Replaced the old experiment package with 17 runtime Python modules, one packaged
  coach prompt, focused tests, and compact tracked win evidence.
- `python3.11 -m pytest -q`: **208 passed**, all offline.
- Replayed scoring calculations for all 54 recorded winning plays: no prediction
  migration drift. Actual game differences remain separately recorded.
- Built `balatro_ai-1.0.0-py3-none-any.whl`, installed into an isolated environment
  and the local `.venv`, checked console/module help, offline result inspection,
  packaged prompt access, and fixed Astra/low configuration from outside the repo.
- Fixed active Psychic/Eye/Mouth score suppression uncovered during review.
  Approximate and uncertain numerical interactions are labeled explicitly.
- No model inference, live game, batch evaluation, or pilot resumption was run.
  Previous owned runner/server PIDs are absent. Low-effort win rate is unmeasured.

## Live correction — visible seed 2K9H9HN

Certificate exposed a stale BalatroBot `cards.limit` (52) after the public deck
composition grew to 53. Derive actual deck size from the validated public
composition. Keep capacity separate and retain codec consistency checks.

Recovery uses an explicitly reviewed continuation snapshot and public history,
compares the live state before any new mutation, preserves the coach plan and
cumulative budgets, and never replays the already-applied blind selection.
Acceptance: growing/shrinking deck regressions; continuation refuses changed
state and never sends start or repeats an old action. 212 offline tests pass.
The visible Astra-low game resumed from Ante2 Flint and played a 713-chip hand.

Ante3 shop correction: Astra proposed buying-and-using Hermit. Installed
BalatroBot buy.lua explicitly supports that mode only for usable vanilla Planets;
the validator was correct. Clarified the prompt. Invalid responses now receive
bounded validation feedback (two corrections, all charged to the existing call
budget); transport errors and uncertain mutations still stop without replay.
213 tests pass, including correction-before-mutation. Resumed unchanged shop
with preserved history/plan/cumulative budgets; Astra bought Hermit in store mode.

## Speed improvement during the visible game

Keep the active runner untouched while building and testing. Applying code to
that already-loaded process requires a brief pause and reviewed continuation;
user's earlier no-interruption preference remains pending clarification.

Smallest improvement: encode repeated public-state dictionaries as tables with
explicit columns/rows, preserving every value. Reuse the existing public packet,
Codex subprocess and validator. Shorten requested plan text without changing
strategy or model effort. Record coach call duration and packet byte counts for
future measured comparison. No new service, session protocol or delegated player.
Acceptance: exact reversible packet encoding across recorded winning requests,
measured byte reduction, existing fake-transport/runtime tests. No extra model
benchmark calls and no restart/mutation of the active game during development.

Speed change verification: 219 offline tests passed; packet tests were then
made independent of Git-ignored live runs using the tracked first-win evidence
and all 6 passed. Latest 62 live-recorded public requests round-tripped exactly;
wire bytes fell 11.5% including format instructions. Wheel built and installed.

User explicitly approved brief pause/resume to apply speed changes. Stopped only
at a coach-request boundary, verified unchanged public state, and resumed Ante4
with history, plan and cumulative budgets retained. Current output is
runs/astra-low-visible-fast-2K9H9HN-compact. First two calls14.037/10.509s,
plans357/287 characters; no claim of measured comparative speedup.

## Technical latency work

User authorizes technical optimizations only: preserve Astra low, every meaningful
decision, all public information, scoring and validation. Keep live game running
while profiling recorded states. Smallest change: move unique request ID after
stable instructions in the serialized packet so it no longer invalidates the
shared prefix. Reuse existing compact packet transport; no new service or model
conversation history. Add stage timing to distinguish numerical preparation,
encoding and Codex execution. Only cache identical immutable observations if
profiling justifies it; no reduced settling guarantees or strategic delegation.
Acceptance: identical expanded packet values, stable prefix across request IDs,
fake-only timing/transport tests and recorded-state benchmarks. No extra model
benchmark games. Live current run is at Ante6 and still running.

Technical latency result: 220 tests pass. Recorded-state profile (12 snapshots)
found hand analysis median~15ms and packet encoding~1ms; numerical caching would
save little. Local `codex --version` startup proxy median70ms excludes actual
inference initialization/network. Reordered packet keys only: stable instructions
first, unique request_id last. Added numerical/serialization/Codex stage timings.
No session-history changes, reduced information, altered scoring, skipped model
decisions or reduced settling validation. Applied via approved reviewed
continuation at Ante6. First calls7.861/7.923/9.806s; Codex accounted for virtually
all elapsed time. This is not a controlled comparative speed benchmark.

Further no-premium transport choice: retain the proven exec isolation rather than
introduce app-server configuration/context differences. Reuse one temporary
workspace and schema path across independent ephemeral Codex calls; erase each
response before/after use and clean up workspace at run end/error. This removes
another changing prompt-context path, without accumulating conversation history.
221 offline tests pass; wheel rebuilt/installed. Not yet live-benchmarked.

User requested unblocking the game after it hit200 coach calls. Raised only the
call cap to300 and resumed same public state/history/plan (session78797, output
runs/astra-low-visible-fast-2K9H9HN-extended). Reviewed Arcana delayed hand draw:
only hand/draw_count/remaining_deck had settled after the prior cap; adjusted
last buy_pack transition to observed settled public state, never replayed it.
The workspace change is for next launch; do not pause this resumed game again.

## Persistent Codex connection trial

User authorizes testing the warm Codex connection after rejecting higher-credit
Fast mode and strategy shortcuts. One local Codex app-server subprocess, standard
service, ChatGPT authentication, Astra low; fresh ephemeral thread for each
complete public packet preserves the existing decision-context contract. No
conversation-history accumulation. Validate returned configuration before any
turn, disable tools/instructions discovery, correlate replies and fail closed on
unexpected requests. Preserve independent exec transport until verified.

Acceptance: fake-server lifecycle/timeout/correlation/usage tests, actual local
initialize/thread-start handshake without inference, then at most two explicitly
bounded standard-credit public-packet model calls to verify integration and
measure latency/cache counters. These probes do not execute game actions. Keep
current visible game untouched while developing. Do not claim a speedup without
measurements or assume a persistent process guarantees an upstream cache hit.

Persistent-connection trial outcome: prototype lifecycle, correlation, failure and
configuration tests passed (4 fake-server cases,22 combined). Actual local
initialize/thread-start plus `codex debug prompt-input` audits (no inference)
show personal AGENTS.md still loaded despite available configuration overrides.
App-server rejects exec's --ignore-user-config/--ignore-rules flags. Therefore
fresh-thread app-server does not preserve the player's prompt contract here.
Archived prototype/tests outside repo at
/Users/jacopo/Desktop/projects/balatro-ai-v2-history/appserver-trial-20260907.
No model probes were made after that gate failed; no speedup is claimed.

Implemented remaining output-saving change: model may return plan="=" to retain
its full previous plan. Runner expands it before logging so recovery and future
packets preserve all strategy text.222 tests pass; wheel installed. Applies next
launch. Active visible run reachedAnte8 and was not interrupted for this work.

User explicitly requests continuing beyond Ante8. Verified Astra-low result:
Ante9 ROUND_EVAL,303 cumulative decisions,283 coachrequests,2972.87active seconds,
peak200854. Saved result/manifest and supervised-recovery provenance in
 evidence/astra-low-2K9H9HN. Added --endless and endless objective; Ante8 milestone
remains recorded while later game-over ends the endless segment.223 tests pass.
Resumed same state/history/plan to session29869, output
runs/astra-low-visible-fast-2K9H9HN-endless;600calls900actions7200active seconds
cumulative bounds. Verified cashout toAnte9SHOP and subsequent Astra actions.

## Save completed run, then improve — user request

Final visible run ended naturally atAnte11, peakhand1,239,454,384 cumulative
decisions357requests3611.146active seconds, with Ante8 cleared. Preserve complete
original trajectory segments (including interrupted slow attempt separately),
results/manifests and uncompressed SHA256 checksums in tracked evidence before
committing the working player.223 tests and all evidence hashes verified.

After that baseline commit, review the trajectory and research high-score
mechanisms. Compare missed opportunities with actually visible offers; never use
future knowledge to claim a move was obviously right. Improve only supported
mechanics/advice, retain Astra-low/standard credits/public-state isolation and
one minimal player. No live rerun or gameplay model calls are authorized.

## Post-run improvement design (baseline 99cf692)

User-visible outcome: Astra notices supported scaling offers before rerolling,
and receives accurate Fortune Teller estimates. Smallest examples: the Ante7
Mime offer remains visible to advice with five occupied Joker slots and five
Steel cards; the final Glass6 hand estimates 1,239,454 after integer flooring.
Reuse the public adapter, existing scorer, compact analysis packet and coach
prompt. Add conditional offer facts, not another player or a new service.

Acceptance: regress recorded public offers and final-hand arithmetic; audit all
49 recorded plays with hidden/stochastic exceptions; run full offline tests and
package checks. Document actual missed offers versus speculative pivots, and
retain source links for mechanics. No new game or gameplay inference. Commit
improvements separately from the preserved successful baseline.

Post-run implementation verified: Fortune Teller public tooltip runtime fixes
46/47 visible-hand parity (one Lucky RNG discrepancy; two hidden hands excluded).
Conditional engine offers now survive full slots, with Negative capacity handled;
coach guidance covers replacements, scoring phases and retrigger/deck development.
232 offline tests pass; wheel built and reinstalled locally. No gameplay/model
calls. Detailed findings and online sources: docs/trajectory-review.md.

## Offline strategy learning library

Outcome: Astra receives a few relevant reviewed decision examples without more
model calls or a live rerun. Smallest example: a visible Mime offer plus Steel
cards retrieves a replacement lesson explaining lost income/Mult and draw risk.
Reuse typed public observations, the existing scorer and analysis packet.

Design: 48 packaged JSON examples across at least16 strategy families, each with id, family, trigger_keys (any visible
owned/offered key), required_keys (all owned/offered keys), phases, situation,
options, lesson, reversal, provenance and sources. Sources distinguish recorded
observations from constructed mechanics exercises and external hypotheses.
Deterministic retrieval returns at most3 distinct-family examples, compact text,
no seed/future offers or online access in gameplay. Numerical exercise tests vary
held-card count and base Mult, and verify supported retrigger/copier arithmetic.
No new service, model training, seed finder installation, or game run.

Acceptance: 30–50 unique sourced examples, schema/source validation, recorded
shop retrieval, unrelated/hidden-state nonmatches, packet size bound, arithmetic
checks across alternative setups, full offline tests and installed package data.
Commit only after review. Online references are learning material, not authority
for unverified mechanics or evidence that a counterfactual wins.

User correction: cover many strategies beyond the last run. Expand to48 examples
including straights, flush/suit, face/retrigger, discard scaling, consumable and
economy engines, legendaries and deck construction. Recorded run is one input,
not the boundary. Explicitly distinguish partial scorer coverage from verified
mechanics so advice does not imply precise numerical support.

Completed:48 examples across31 topics (6 recorded,42 constructed), including
unseen straights/flushes, legendary/consumable, discard and conversion engines.
Retrieval requires public matches, favors offers, and returns at most3 distinct
families without sources/seed routes.15 arithmetic exercises plus integrity,
hidden-state and unseen-engine retrieval tests;253 tests pass. Offline retrieval
across383 saved decisions took0.0232s total, max1170bytes; no inference benchmark.
Wheel built/reinstalled and its48 packaged examples verified from /tmp.
No live game or gameplay model call. Scorer coverage limits documented and sent
to the coach. User correction about strategy breadth preserved in this design.
