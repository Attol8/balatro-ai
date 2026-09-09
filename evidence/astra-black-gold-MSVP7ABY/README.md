# Headless Black Deck / Gold Stake win — MSVP7ABY

Completed 9 September 2026. GPT-6 Astra, low effort, real Balatro through
BalatroBot, BLACK/GOLD, all-unlocked profile, non-endless Ante 8 objective.

Final score **435,408 / 400,000**, one hand left; 264 actions, 220 model requests, peak hand 247,230.

Three segments of one native game; two budget continuations, four recovered model timeouts and no RPC timeout. All 30 frozen policy files matched at completion. No video was captured. The original scoring audit has two fractional differences; the separately archived post-run flooring correction matches all 34 supported plays, excluding three hidden-state plays.

Exactly one logged start, with no seed supplied. Every continuation has
`resume_adjusted=false` and `resume_diff=[]`. The final native observation has
`won=true`, eight antes cleared and phase `ROUND_EVAL` (Ante 9 cash-out screen).
No endless run followed. This is not evidence of a win rate or an unmodified
fresh-account progression run. [Shared setup and fair-play disclosures](../../docs/black-gold-results.md).

## Evidence

- [Final cumulative result](result.json) and [native audit](final-audit.json).
- [Policy fingerprints](policy-provenance.json).
- [Ordered segments and SHA-256 hashes](segments.json). Every segment preserves
  its original manifest/result bytes and full trajectory compressed with gzip
  `mtime=0`; hashes refer to uncompressed original bytes. Counts in resumed
  results are cumulative and must not be summed.

These artifacts were copied without modifying the native scores or traces.
The policy was under development, so file fingerprints rather than an uncommitted
Git revision identify the run. Large video files are retained locally, not in Git.
