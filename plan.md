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
