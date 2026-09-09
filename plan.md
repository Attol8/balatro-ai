# Merge the verified results into main

Outcome: keep a brief linked Black/Gold success statement at the top of README,
move the detailed wins table and screenshot below the existing results, and merge
the reviewed branch into main. Reuse the current evidence, CI and GitHub merge flow.
Smallest example: opening README mentions both wins; detailed evidence is lower down.

1. Adjust README hierarchy and retain the rule-by-rule audit and disclosures.
2. Review the complete branch diff, verify documentation links and required CI.
3. Commit, push and merge through GitHub; verify main includes the reviewed changes.

Acceptance: main has both win archives and accurate documentation, checks pass,
no game launches, and unrelated uv.lock remains untouched.

---

# Verify every Black Deck / Gold Stake rule in the published video

Outcome: establish whether the recorded PI4T2AH8 win uses all cumulative penalties.
Reuse native game sources, original trajectories and the Downloads video; no new game.
Smallest example: match the visible opening 3 hands / 2 discards / 6 Joker slots to
native BLACK/GOLD settings, then check every additional stake effect separately.

1. Independently inspect native rules and recorded state for all cumulative effects.
2. Inspect relevant frames from the actual 2× export, including sticker examples.
3. Record an evidence-backed verdict, distinguishing visible evidence from trace checks.

Acceptance: every rule accounted for, legitimate upgrades explained, and any unsupported
claims or presentation limitations explicitly identified.

Completed: native cumulative rules and scaling match the full trace; actual Downloads
2× frames confirm resource limits, cashout and sticker offers. Independent audit
verifies ten rental charges, Grabber, Paint Brush and Chicot. No Eternal/Perishable
Joker was owned, so expiry/unsellability was not exercised. Recorded the stale
playback-speed label and retained the disclosed modded/all-unlocked setup.

---

# Commit and push the completed Black/Gold work

Outcome: publish the bot improvements, private recording tools and both verified
win archives on the existing feature branch. Reuse the repository CI checks and
Git remote; preserve the unrelated pre-existing untracked `uv.lock`.

1. Review the pending implementation and evidence; run the full offline tests,
   Ruff and benchmark regeneration checks.
2. Commit the reviewed task files with the results and caveats included.
3. Push the existing branch without force and verify the remote commit matches.

Acceptance: tests and lint pass, archived evidence is included, no large local
video/save files are committed, and the remote branch matches the local commit.

Pre-push verification: 755 tests passed in 60.48 seconds; Ruff and diff checks
pass; benchmark JSON/Markdown regenerated unchanged; independent implementation
review found no blocking regression. Existing untracked uv.lock excluded.

---

# Publish both Black/Gold results and explain fair play

Outcome: put the finished video in Downloads and make both wins inspectable in
repository documentation, with accurate rules and explicit automation/profile caveats.
Reuse the existing native audits, manifests, trajectories and evidence layout.
Smallest example: each results row links to its final native score and original
compressed trace, with hashes proving the archive matches the local run.

1. Move the video without overwriting another file; verify destination and metadata.
2. Independently inspect fair-play boundaries and native rules; archive both wins
   under evidence with original manifests/results and deterministic compressed traces.
3. Update README and results documentation, retain earlier development loss disclosure,
   verify archives, firewall tests and unchanged legacy benchmark generation.

Acceptance: both native BLACK/GOLD wins independently backed by original trace
bytes; no claim of perfect play, clean-install progression, unmodified client or
win rate; no new game or Reddit upload. Existing unrelated work is preserved.

Completed: final MP4 moved to Downloads without overwrite (113,585,701 bytes).
Direct original-video frames at 00:45, 02:30 and 13:00 verify Black Deck resource
limits, gold chip, no Small Blind reward and Rental sticker. Both wins archived
under `evidence/astra-black-gold-*` with byte-identical compressed trajectories,
original manifests/results, fingerprints and score audits. README/results link
the separate Black/Gold report and disclosures. All archive hashes, native final
scores, counts and single unseeded starts verified. 37 adapter/coach tests pass;
legacy benchmark JSON/Markdown rebuilt byte-identically; diff check clean.
Changes remain local and uncommitted; no push or Reddit upload performed.

---

# Full Black/Gold recording for Reddit — 9 September 2026

Timing recovery: the first rendered winning hand took 69.7 seconds, exceeding the
60-second RPC default; an early recovered state rejected cash-out before the
animation settled. Add an optional positive finite `play --rpc-seconds` transport
timeout, verify argument validation/client wiring, then resume this same game
with 180 seconds. Default behavior and decision policy remain unchanged. Preserve
the original segment and disclose this transport-only change in provenance.

Outcome: record a fresh complete native BLACK/GOLD attempt privately, remove the central X cursor, and deliver a postable MP4 with the bot's concise recorded explanations alongside gameplay.

Design: reuse the verified Docker/Xvfb recorder, existing coach/runner, timestamped full trajectory and review viewer. Hide the X server cursor and disable pointer capture in FFmpeg. Freeze bot policy before the game; do not select a favorable seed or tune during the attempt. Export the raw complete recording and a separate side-by-side MP4; if shortening for Reddit limits, use disclosed uniform speed and preserve every action. No Reddit posting is authorized.

Smallest example: menu-only private clip visibly has no center cursor, then a saved four-action clip exports with matching explanations and actual score. Acceptance: these checks plus focused tests before native play; one fresh full game to a terminal outcome, preserved trace, native legal/score audit, playable cursor-free exports, all owned processes stopped and host saves unchanged. A win cannot be promised from the previous single success.

1. Remove cursor and verify short clip; prepare and test the independent side-panel video exporter.
2. Freeze policy, start a fresh unseeded BLACK/GOLD game inside the private recorder, monitor progress and recover only the same game if necessary.
3. Verify terminal state and native evidence, finalize video, export a Reddit-sized version with explicit playback speed, inspect output and save checkpoint.

Completed: fresh random `PI4T2AH8` won BLACK/GOLD, 420,305/400,000 with one hand
remaining; 270 legal actions, 227 coach requests, peak hand 227,383. One same-game
transport recovery; no seed screening or decision-policy tuning. Original capture
is 5,725.134 seconds. Final `black-deck-gold-reddit-final.mp4` is 845 seconds,
1920×720 H.264, 113,585,701 bytes: all action chronology at labelled 6.787× speed
plus a five-second final outcome card. Early/middle/end frames inspected, central
cursor absent, full decode passes. Browser review verifies 998 events, seeking,
rewind and explanation association. 98 focused tests, Ruff and diff checks pass.
Owned game containers stopped and six host-save hashes unchanged. Native score
audit preserves 44 matches and three one-chip Ramen floating-point discrepancies.
Evidence: `runs/black-gold-reddit-20260909/verification.json`. No Reddit upload.

---

# Invisible gameplay recording — 9 September 2026

Outcome: capture real Balatro gameplay without a game window or desktop recording on the user's work desktop.

Additional requested outcome: review footage beside the bot's recorded decisions and short public explanations. Reuse trajectory events, add wallclock/elapsed timestamps and a pre-capture clock anchor, and generate a local video/trace viewer with seekable events and an adjustable synchronization offset. Preserve the full numerical advice in expandable event details. Explanations describe the decisive public tradeoff, not internal reasoning; old traces lacking timestamps or explanations cannot supply them retroactively. Verify with small fixtures and the short native capture, without a full run.

Design: reuse the installed game, BalatroBot API and Docker daemon. Render inside a Linux container with Xvfb, record only that virtual display with FFmpeg, mount game/mod sources read-only and keep saves/output isolated. No full run; a short API-driven smoke test establishes capture and control.

Smallest example: start the container game, select BLACK/GOLD through the API, execute a legal opening action, capture a short MP4, verify changing rendered frames and correct game settings, then stop all owned processes.

1. Verify Linux loader/runtime compatibility and existing host prerequisites.
2. Add the smallest reproducible container recording workflow and documentation.
3. Run one bounded smoke capture; inspect video frames, API evidence and shutdown. Resolve concrete failures without opening any host game window.

Acceptance: no host display capture/window or host save mutation; native game API reachable only on localhost; nonblank playable video with visible state changes; short test only; owned container stopped. New container dependencies are justified by rendering privately while the user works.

Completed: pinned native ARM Lovely 0.9 / LÖVE 11.5 runtime; fresh isolated tutorial-complete settings; Docker/Xvfb/FFmpeg capture; timestamped trajectory events and short public explanations; seekable local video/trace review page. Final native BLACK/GOLD smoke completed four legal actions with four real coach explanations. Two Pair prediction108 matched native108. H.2641280×72015FPS,257.734s demo; browser verified playback, seeking, explanation association and rewind. Manual and12-second timer shutdown finalized playable MP4s; all owned containers stopped, ports12347/12348 closed, six host-save hashes unchanged. 103 focused regression tests, Ruff and diff checks pass. No full game run. Capture timing is approximate with an adjustable startup offset. Evidence `runs/virtual-recording-20260909/verification.json`; demo `capture-04/review.html` within that directory.

---

# Boss preparation and readiness gate — 9 September 2026

Outcome: improve Black Deck Gold Stake decisions across builds, then make one fresh headless attempt; Ante 8 takes priority over high scores. Global optimality and exhaustive closure of all possible improvements cannot be certified.

Design: reuse public observations, scoring, isolated probes and the native runner. Add explicit upcoming-boss preparation and guarded current-build capacity, with unknowns labelled. Independently audit other decision gaps and fix reproducible defects. No seed-specific policy, hidden information or future-offer oracle.

Smallest example: a build whose optimistic one-hand ceiling is below Needle's requirement must recognize that an extra-hand voucher cannot close that deficit. Reverse the check for sufficient capacity and unsupported builds; do not confuse a snapshot ceiling with future scaling potential.

1. Implement guarded boss readiness and audit independent action/scoring gaps.
2. Review diffs, run arithmetic and reversal checks across multiple builds/bosses, then use a small fixed set of isolated coach probes.
3. Freeze verified policy and run one fresh native random BLACK/GOLD game strictly headlessly, with rendering-on-API and audio disabled. Inspect opening correctness, continue same run, no restart for bad offers.
4. Audit terminal outcome, stop server, record evidence and remaining limitations.

Acceptance: supported calculations independently checked; unsupported estimates suppressed; meaningful tests/lint pass; varied local decisions verified; run legality and supported score parity audited. Only native Ante 8 completion establishes a win.

Gate passed: 717 tests, clean lint/diff, six distinct isolated decisions correct in eight attempts (two transport timeouts retried unchanged). Thirty policy files frozen. Fresh random BLACK/GOLD headless server93553 started; opening segment00 cap12calls30actions900s, calltimeout90s. No visible window, audio or API rendering. Continue same game after legality/score audit. Seed-search tooling reviewed as optional research and deferred: current evidence favors general decision improvements; user said skip if not useful.


Completed native attempt: **BLACK/GOLD won**, Cerulean Bell 435,408/400,000 with one hand unused; 264 legal actions, 220 coach requests, peak hand 247,230, 3,011.125 cumulative seconds. One random game across three budget segments, one start, no seed screening or mid-run policy edits. All 30 frozen hashes match. Four coach timeouts recovered; no RPC timeouts. Native all-unlocked profile, non-endless Ante 8 completion. Owned server 93553 stopped and port 12346 closed.

Frozen score audit: 32 exact matches, three unsupported hidden-state plays, two fractional discrepancies (10,454.4 vs 10,454 and 138,526.5 vs 138,526). Native source floors the final product; The post-run correction floors deterministic final products while preserving explicitly stochastic estimates; saved replay now matches all 34 supported hands. Original frozen audit retained. This single win establishes capability, not a win rate, global optimality or extremely high-score performance. Evidence: `runs/black-gold-readiness-20260909/final-audit.json` and `segment-02/result.json`.

Final post-run validation: **723 tests passed in 64.39s**, Ruff and diff checks clean; corrected replay 34 supported matches and three excluded. No further gameplay.

---

# Generalization gate and second headless attempt — 9 September 2026

Outcome: improve Black Deck Gold Stake survival across different builds, then test the frozen policy on one fresh native run. Ante 8 takes priority over high scores.

Design: reuse public observations, scorer, archived traces, isolated probe harness and bounded native runner. Diagnose build/economy decisions across multiple runs; make only supported general corrections. Separate development examples from held-out variations and reversal cases. Never tune to a game seed or inspect future offers/draws. Native gameplay must remain headless with rendering-on-API and audio disabled.

Smallest real example: distinguish a temporary scoring bridge from a lasting upgrade while preserving enough current score to survive, with tests reversing the decision when the bridge is still needed.

1. Audit cross-run evidence and define diverse local decision contracts before changing policy.
2. Implement the smallest justified correction, validate arithmetic/legality and held-out variations, then make a bounded set of isolated coach calls.
3. Once scoped evidence and reviewed strategy justify a credible attempt, freeze policy and launch one fresh unseeded BLACK/GOLD run headlessly. Inspect the opening for correctness and continue the same run to a terminal result within explicit budgets. Do not restart for unfavorable offers or tune mid-run.
4. Report native result separately from probe success, audit failures, and checkpoint evidence.

Acceptance: diverse fixed-state checks, reversal coverage, tests and lint pass; no seed-specific rules or future-state oracle; no visible game; one new native run with legal actions and score parity audited. A win is established only by native Ante 8 completion.

Completed attempt: 645 full-suite tests plus 11 new oracle checks; six distinct isolated decisions correct in seven attempts (one transport timeout, unchanged retry passed). Frozen policy used for one fresh random BLACK/GOLD game, strictly headless. Lost to Ante 5 Needle at 17,958/25,000 after 107 legal actions and 85 coach requests; 26 fully supported scores matched, one hidden-card score excluded. All 28 policy fingerprints unchanged. Server stopped and port closed.

Failure audit: exhaustive 9,841 public rank/suit classes grant perfect cards while retaining optimistic opening bonuses; unchanged build scores at most 19,950 against 25,000. Final hand was optimal, including all 720 Joker orders. This is a bound within the public scorer, not independent engine certification. Next development target: upcoming-boss build readiness before shop commitments and skips, validated across diverse builds/bosses. No further native game started; Black/Gold win remains unproven. Evidence: `runs/black-gold-generalization-20260909/`.

---

# Bounded public draw advice — 9 September 2026

Outcome: help the coach compare equal immediate scores and discard options by the next hand they leave, without paying for repeated full games.

Design: reuse the public scorer and unordered remaining deck. Deterministic common Monte Carlo samples, a small candidate cap, explicit one-draw horizons and uncertainty. Guard static normal-card non-boss states; no hidden order, future trace, unsupported runtime simulation or claim of full-round optimality. Existing legal validator retains authority.

Smallest real example: distinguish the recorded Six and Ten kickers, both scoring 11,000 now, by their probability of covering the remaining 4,424 next hand.

1. Implement conservative bounded advice and integrate it into the existing analysis packet.
2. Verify arithmetic, legality, guards and permutation invariance with focused tests; replay saved failure packets and measure preparation overhead.
3. Run a few isolated coach checks only if offline evidence supports the advice. Use no new full game unless this gate reveals a meaningful improvement.

Acceptance: no unsupported states receive forecasts; deterministic public-only results; independent small-deck oracle agreement; real recorded kicker ranking reproduced; bounded runtime; full tests pass. Black/Gold win remains unproven until native evidence establishes it.

Verified implementation: guarded 48-sample advice integrated; 623 tests pass, Ruff clean. Six saved-state replays took at most 2.43 seconds each. Two independent exhaustive toy oracles pass; four isolated coach calls solved both cases with/without advice, showing correctness but no demonstrated benefit. Two recorded-position calls changed the last-discard choice to play now and retain the discard.

Sequence gate: 128 paired public-deck simulations with the same downstream policy took 40.45 seconds. Original discard-first won 72/128; revised play-first won 73/128. Paired difference +0.78pp, approximate 95% interval −9.53 to +11.09pp: inconclusive. No new native game launched. Evidence: `runs/continuation-advice-check-20260909/`. Next: investigate earlier build/economy decisions and representative fixed-state probes before another full run; do not infer readiness from this small action change.

---

# Black/Gold feasibility and bounded opening — 9 September 2026

Outcome: establish whether attempting Black Deck Gold Stake is justified, fix demonstrable bottlenecks before a full run, then inspect a short headless opening using the existing coach.

Design: reuse installed native rules, existing human evidence, archived public traces, scorer and bounded runner. Separate human beatability from bot success and universal seed solvability. Keep the same live game across budget checkpoints; never reveal future draws or seed to the coach. No visible game window.

Smallest real example: verify a BLACK/GOLD start exposes three hands, two discards and six Joker slots, then compare predicted and actual opening scores and inspect the first shop decision.

1. Audit higher-stake mechanics, strategy coverage and cheap test gaps before gameplay.
2. Fix concrete misleading advice or contract failures and run targeted regression checks; avoid speculative rewrites.
3. Start headless only, cap the opening at 12 calls/24 actions, inspect public decisions and scoring parity.
4. Continue only when evidence supports it, retaining the same game; report exact limits and remaining uncertainty before any full-run claim.

Acceptance: source-backed feasibility assessment; passing regression checks; actual headless opening evidence with correct settings, score parity, legality and budget stop; no seed shopping or fabricated win-rate estimate.

Verified opening gate: full suite 535 passed (55.31s), Ruff clean. Headless BLACK/GOLD prefix reached Ante 2 in 12 requests / 16 legal actions/134.392s; all 3 actual hand scores matched predictions (316,716,700), no errors/timeouts. Evidence: `runs/black-gold-opening-check-20260909/opening-audit.json`. Continuing the same game, capped cumulatively at 80 requests/150 actions/1800s; temporary Ice Cream still needs durable support.

Continuation outcome: same game lost at Ante 5 Small Blind, 23,816 / 25,000; 84 total actions, 69 requests, 991.42s. All 17 hand scores match and all actions legal. Final-blind legal-play enumeration found no better immediate play. Saved public failure packets; stopped headless server; no second game. Next gate is offline build/discard planning analysis, not another full run. Black/Gold win and whole-run score gains remain unproven.

Offline follow-up: 200 paired public-deck draw samples completed in 2.459s with zero game/model calls. Chosen Six kicker estimated 31.5% next-hand survival; Nine 31.0%, no kicker 27.5%, Ten 18.0%. No superior action established; bounded continuation scoring is a promising next optimization, requiring broader fixed-state validation before production or a new game. Script and JSON saved with run.

---

# Black Deck Gold Stake and high-score decision checks — 9 September 2026

Outcome: enable Black Deck / Gold Stake play, prioritize its Ante 8 win, and test survival and scaling decisions with a handful of isolated coach calls before any full game.

Design: reuse the existing public observation firewall, scorer, coach transport, legal-action validator and run budgets. Add configurable deck/stake with safe resume and a small decision-probe harness. Any necessary live gameplay must be headless; never open a game window while the user is at work. Constructed cases are explicitly labelled; no simulator, hidden draws, new service or win-rate claim.

Smallest example: on Black/Gold with one hand left, the coach must take a visible scoring finish instead of farming; a separate high-score case must use a supported retrigger engine.

1. Merge latest origin/main, preserving all published evidence and current changes; resolve generated benchmark conflicts and verify.
2. Thread deck/stake through play, supervision, manifests and resumes. Add public survival context and focused regression coverage.
3. Add reusable public-state probes with explicit acceptance rules, offline by default and capped model calls when requested. Run offline checks, then a small Astra-low probe batch.
4. Inspect actual responses and report failures honestly. Full games remain gated on cheap checks; this task will not claim a Black/Gold win from probes.

Acceptance: merged main ancestry; passing tests; correct BLACK/GOLD start and resume; legal, scored probe results with bounded calls and no live game mutation. Report exact probe evidence and remaining gameplay uncertainty.

Verification: full offline suite499 passed; after adding two negative grader cases, focused probe suite8 passed. Ruff and diff checks pass.

Verified milestone: latest main merged as `575be69`; four Astra-low probes passed in four calls with no game launch. Offline acceptance includes configuration/resume, sticker arithmetic, fixture oracles, legal responses and single-attempt transport. Next gameplay gate is a resumable headless opening; Black/Gold win and whole-run score improvement remain unproven.

---

# Run stopping and high-score review

## Publication blocker audit — 8 September 2026

Outcome: identify major result-integrity issues or credential/private-data exposures before publishing the repository.

Design: reuse evidence validation and public-state tests; independently inspect headline provenance and source security while scanning tracked files, compressed artifacts, and reachable Git history without printing secrets. No publishing, game runs, or model gameplay calls.

Smallest example: trace the five-Astra-wins headline to actual Ante 8 clears and ensure no archived coach output contains an authentication token.

1. Audit major cheating/fabrication threats and source security in parallel.
2. Scan reachable Git blobs and candidate untracked additions for credentials/private data; inspect flagged locations safely.
3. Run appropriate integrity checks and report publication blockers separately from disclosed methodological limitations.

Acceptance: no unresolved major finding; clearly bound scan coverage and historical provenance uncertainty. Fix simple local exposure prevention if needed, without rewriting history or publishing.

Completed: no major cheating/fabrication or credential-exposure blocker found.
Five Astra peaks match actual chip deltas; all 60 listed artifact hashes validate,
1,835 coach requests contain no own seed, and all 38 forced actions are uniquely
legal. Fresh benchmark JSON/Markdown exactly match published files. Pattern scan
covered 2,142 reachable Git blobs across 316 commits, including 24 decompressed
gzip blobs (483 MB total decoded data), plus four untracked candidate files;
zero credential-pattern findings. Media screenshots and sampled GIF/video frames
showed no sensitive content; this was not an every-frame historical media audit.
Added log/credential exclusions and replaced tooltip HTML interpolation with DOM
text. Fifteen dashboard tests, hostile-tooltip check, JS syntax and diff checks
pass. No publication, history rewrite, new game or gameplay-model call. Current
local refs and pattern-based scanning bound the security conclusion; historical
mod provenance and disclosed development interventions remain qualifications.

## Benchmark rules audit — 8 September 2026

Outcome: determine whether published Red Deck / White Stake games use ordinary Balatro rules and disclose material automation or comparison differences.

Design: read archived starting states and results, the runner's action boundary, and installed mod patches; compare with documented game rules. Reuse existing evidence and tests. No games or model calls.

Smallest example: confirm a published Ante 1 start has the ordinary Red Deck resources and White Stake blind target, then trace whether any cheat endpoint is used.

1. Audit published settings and aggregation in parallel with installed mod changes.
2. Verify runner mutations and public-information tests; distinguish current installation from archived provenance.
3. Report standard rules, disclosed differences, and any remaining uncertainty with source links.

Acceptance: claims trace to actual configuration/code/observations; no blanket vanilla-equivalence claim without evidence.

Completed: all seven published coached games start RED/WHITE, $4, 52 cards,
zero Jokers, four hands/four discards and 300/450/600 opening targets. Reviewed
automation patches preserve native scoring and in-run unlock prerequisites;
collection unlocks and scoring advice are material comparison disclosures.
Installed mod code is locally modified and not historically fingerprinted by
coached manifests. D0000000 has a disclosed post-win autosave recovery with
changed state; early supervised/reset attempts preclude a clean win-rate claim.
86 adapter/client/benchmark tests passed; no new game or model call.

## Offline proof of higher-scoring decisions — 8 September 2026

Outcome: identify decisions that provably leave score or productive resources on the table before spending on another game, and separate local guarantees from unproven whole-run improvements.

Design: reuse archived public observations, the existing scorer, recorded actions and local game mechanics. Compare fixed-state scoring alternatives; inspect setup hands, discards and real shop offers; quantify draw reliability with exact public-count arithmetic. No new gameplay or coach calls and no gameplay-policy changes.

Smallest real example: replay the strongest run's first Tooth hand and compare a legal alternative under identical visible state, then explain whether its gain is enough for the blind.

1. Audit high-score and recent trajectories in parallel for play/production and build decisions.
2. Verify candidate mistakes against legal actions, scoring parity and explicit uncertainty; derive cheap acceptance checks for multi-step claims.
3. Report prioritized findings and a proof ladder for improvement, preserving the distinction between higher local score and higher completed-run score.

Acceptance: each concrete claim has a trace location or reproducible calculation; future draws and shops are never treated as known; no new expensive runs.

Completed: `docs/offline-score-proof.md` records a guaranteed Mail setup finish
with +$1.34375 expected net income, a legal Death-to-Glass alternative that still
clears by 2.94x, historical ignored score advice and a falsified immediate Mime
upgrade claim. `python -m scripts.audit_production_proof` and
`python -m scripts.audit_build_proof` pass their assertions; 45 supporting tests
passed, both scripts pass Ruff, and `git diff --check` passes. No gameplay-policy
change, new game, gameplay-model call or whole-run improvement claim.

## Implementation and fresh Astra run

Outcome: expose resource generation and phase-specific copier advice, correct misleading strategy guidance, and observe Astra on a fresh endless seed.

Design: reuse public observations, existing score estimates and legal adjacent reorders. Add bounded round-production context and event-specific copier targets; never label a future draw or approximate score as guaranteed survival. Preserve existing scoring candidates and runner limits. No hidden-state search or new service.

Smallest example: a safe current scoring finish with Purple seals must expose the generation opportunity, while the same hand facing an unmet requirement must warn against spending the last hand on setup. Copier advice must target Perkeo before shop exit and held effects before the terminal play.

1. Create feature branch and inspect current runner configuration.
2. Implement advice and focused regression tests; correct Glass, interest and boss-selection guidance.
3. Run relevant tests, review the diff, and launch Astra endless on a seed absent from existing evidence.
4. Monitor the run to termination and report score, ante, stop reason and use of new advice.

Acceptance: public-only advice, legal copier steps, explicit uncertainty and trigger timing; passing relevant tests; a persisted fresh-seed run result and trajectory. A single run is observational evidence, not a controlled improvement claim.

Outcome: explain whether recorded games stop prematurely and identify evidence-backed ways to score higher.

Smallest real example: compare the Ante 11 losses with TAF7DNTX's Ante 13 loss, including the final blind requirement, hands used, and runner termination reason.

Reuse: preserved result manifests, compressed trajectories, existing trajectory review, runner limits and strategy library. No new service, configuration, gameplay or model inference is needed.

1. Audit terminal conditions and recorded stop reasons, including current local edits.
2. Compare build development and missed decisions in stronger and weaker recorded games; inspect public high-score accounts as strategy evidence with deck/seed caveats.
3. Verify findings against code and recorded events, then give prioritized recommendations and distinguish existing guidance from untested changes.

Acceptance: every claimed premature stop or missed play has a code/trace reference; distinguish actual loss, budget exhaustion and interruption; avoid treating external high scores or hypothetical pivots as demonstrated performance improvements.

## Follow-up: expert video comparison

Outcome: identify specific expert decisions our player lacks, using several high-score videos with accessible transcripts or visual evidence.

Design: compare early economy/deck construction, engine transitions, and late-game setup/scoring. For each lesson link video timestamps, contrast recorded behavior and current implementation, and distinguish missing knowledge, missing numerical advice, and failures to apply existing knowledge. Reuse existing traces, strategy library and scoring code; do not change gameplay during this review.

1. Obtain video metadata and transcripts for a small, diverse sample; disclose any inaccessible sources.
2. Analyze decision sequences and independently inspect matching player capabilities.
3. Write a concise source-linked review with priorities and concrete offline acceptance examples.

Acceptance: at least three videos analyzed from actual content if accessible, with timestamped evidence; descriptions alone never count as viewed content. Correct inherited factual errors in the review rather than repeating them. No claims of validated gameplay improvement without evaluation.


## Completion — 8 September 2026

Implemented on `feat/round-production-advice` (policy `9395d7a`); 139 relevant
tests passed. Fresh seed XV2MP8L5 finished naturally at Ante 12, after an Ante 8
clear, with a 326,543,967 peak. Supervisor: `endless_game_over`, one segment,
zero restarts; all original budgets retained. Archived evidence and separately
labelled benchmark publication preserve the changed policy's provenance.
Round-production context was exercised; production-copier, Purple and Blue
opportunities did not occur. Matched-seed improvement remains unmeasured.
User requested README/docs updates and a final commit only after completion.

Publication verification: 59 benchmark tests passed; archived bytes/hashes and terminal transition agree;
benchmark regeneration is byte-stable; headline chart inspected after fixing
legend clipping caused by the longer policy label.
