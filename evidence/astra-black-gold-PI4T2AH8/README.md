# Recorded Black Deck / Gold Stake win — PI4T2AH8

Completed 9 September 2026. GPT-6 Astra, low effort, real Balatro through
BalatroBot, BLACK/GOLD, all-unlocked profile, non-endless Ante 8 objective.

Final score **420,305 / 400,000**, one hand left; 270 actions, 227 model requests, peak hand 227,383.

Two segments of one native game; one opening RPC timeout and a premature cash-out rejection, followed by an unchanged-state resume with a 180-second RPC timeout. The only changed frozen file was the CLI transport option; all 29 other frozen files matched. Container CPU allowance changed from two to three without restarting the game. Zero model timeouts. The score audit preserves 44 matches and three one-chip differences consistent with native Ramen floating-point decay. The cursor-free gameplay was recorded privately, with no host game window or desktop capture.

Exactly one logged start, with no seed supplied. Every continuation has
`resume_adjusted=false` and `resume_diff=[]`. The final native observation has
`won=true`, eight antes cleared and phase `ROUND_EVAL` (Ante 9 cash-out screen).
No endless run followed. This is not evidence of a win rate or an unmodified
fresh-account progression run. [Shared setup and fair-play disclosures](../../docs/black-gold-results.md).

## Evidence

Direct video checks (timestamps in the original capture):

- [00:45 opening frame](rules-first-hand.png): Black Deck back, six Joker slots,
  three hands, two discards and gold stake chip, before any purchases.
- [02:30 Small Blind cash-out](rules-shop.png): $2 solely for the two unused
  hands, with no blind reward money.
- [13:00 shop](rules-rental.png): Joker Stencil visibly has the gold Rental
  dollar sticker. These are extracted gameplay pixels, not trace overlays.

- [Final cumulative result](result.json) and [native audit](final-audit.json).
- [Policy fingerprints](policy-provenance.json).
- [Ordered segments and SHA-256 hashes](segments.json). Every segment preserves
  its original manifest/result bytes and full trajectory compressed with gzip
  `mtime=0`; hashes refer to uncompressed original bytes. Counts in resumed
  results are cumulative and must not be summed.

These artifacts were copied without modifying the native scores or traces.
The policy was under development, so file fingerprints rather than an uncommitted
Git revision identify the run. Large video files are retained locally, not in Git.
