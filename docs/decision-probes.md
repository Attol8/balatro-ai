# Cheap checks before a full game

The next gameplay priority is an Ante 8 win with **Black Deck / Gold Stake**.
High-score work is secondary. Any necessary gameplay should run headless.

Use three gates: offline mechanics and transport tests, a few isolated coach
decisions, then a bounded headless opening before committing to a full run.
A failed gate calls for inspecting the failure, not launching more games.

The probe harness uses the same public observation codec, numerical advice,
coach instructions and legal-action validator as gameplay. It has no game client
and never executes the returned action. Expected actions and explanations stay
outside the coach packet. Each case starts with an empty plan and history.

Prepare all cases without inference:

```sh
python -m balatro_ai.probe tests/fixtures/decision_probes.json \
  --output runs/probes-offline
pytest -q tests/test_probe.py tests/test_probe_cases.py tests/test_survival.py
```

Check four strategic decisions with Astra low, one attempt each:

```sh
python -m balatro_ai.probe tests/fixtures/decision_probes.json \
  --output runs/probes-astra --max-calls 4 --call-seconds 60
```

Default inference budget is zero. The hard maximum is eight calls; each timeout
or invalid response is a failed check, with no retry or speculative second
process. Output directories must be new. `cases.json`, `packets.json` and
`result.json` preserve the oracles, actual public packets, replies and outcomes.
The result includes prompt and case hashes. Only the first returned action is
graded; follow-ups are recorded and never executed.

The five initial fixtures test:

- A final-hand Photograph/Chad finish: King scores 280; Ace scores 38.
- An endless held-card finish: retain red-seal Steel King with Mime/Baron for
  12,074.0625 estimated chips rather than playing it for 1,150.
- Selling a rental Cloud 9 with no nines: no payout against $3 round rent.
- Keeping rental Cloud 9 with ten nines: $10 payout less $3 rent, conditional
  on clearing another round.
- Eternal rental legality in an empty shop. This last case is forced and can
  be checked offline without spending a model call.

These are constructed local states, not recorded games or certified reachable
histories. Independent arithmetic and legality tests establish their local
oracles. They do not measure drawing, shop adaptation, long-term planning,
real-client scoring parity, win probability or an improvement over the old
policy. Do not add probe passes to the published game results. Broaden the suite
with real failure snapshots as gameplay evidence becomes available.

For the next headless opening check, start the server only when needed:

```sh
BALATROBOT_ALL_UNLOCKED=1 SDL_MAC_BACKGROUND_APP=1 uvx balatrobot serve \
  --fast --headless --no-render-on-api --no-audio --logs-path runs/logs
balatro play --deck BLACK --stake GOLD --max-calls 12 --max-actions 24 \
  --seconds 600 --output runs/black-gold-opening
```

The bounded opening is a real game prefix, not a fresh full run. Preserve it:
`--resume runs/black-gold-opening` with a new output directory inherits its deck
and stake, and rejects conflicting overrides. Limits are cumulative on resume,
so increase them deliberately when continuing. `supervise` also accepts
`--deck BLACK --stake GOLD`. Fresh omissions retain RED/WHITE compatibility.

## First probe batch — 9 September 2026

Astra low passed all four non-forced cases in four calls (51.653 seconds summed
call time), with zero rejected responses or retries. The unproductive-rental
reply also proposed leaving the shop as a follow-up; it was recorded, not
executed. Local evidence: `runs/probes-black-gold-20260909/`.
No game was launched. This establishes only the local choices above; there is
no matched old-policy comparison and no Black/Gold gameplay result yet.

## Feasibility review before gameplay

Black/Gold has human winning runs: Balatro University's own
[All Decks Gold Streak](https://www.youtube.com/watch?v=XsM5_3GDLLM) description
reports completing the streak with Black Deck using five of its six Joker slots.
This demonstrates existence of wins, not universal seed solvability or our bot's
win probability. The published bot games here are Red/White, so their success
cannot answer the latter question.

The installed native game archive confirms Black's −1 hand/+1 Joker slot and
Gold's cumulative no-Small-base-reward, reduced discards, higher blind scaling
and sticker rules (`game.lua:632,2050–2059`). Gold base targets by ante are
300 / 1,000 / 3,200 / 9,000 / 25,000 / 60,000 / 110,000 / 200,000
(`functions/misc_functions.lua:942`), before blind multipliers. Thus the opening
has three hands, two discards and six Joker slots. Early scoring and the money
saved by finishing sooner matter before the extra slot provides much value.

Useful pre-run changes are numerical and mechanical:

- Exclude debuffed To the Moon from projected interest. An expired perishable
  should not imply income it can no longer produce.
- For ordinary non-boss hands, calculate exact one-discard flush-completion
  probability from unordered public deck counts. This is not a forecast of
  winning the blind; no unseen draw sequence is consulted.
- Correct The Mouth's lock from public first-hand history. Later failed attempts
  of another family must not make the original permitted family score zero.
- Condition expensive scaling-voucher advice on surviving and funding the build.

Headless startup explicitly disables render-on-API and audio; render-on-API
would otherwise override the mod's headless setting. The macOS launcher also
sets [SDL_MAC_BACKGROUND_APP](https://wiki.libsdl.org/SDL2/SDL_HINT_MAC_BACKGROUND_APP)
to avoid forcing foreground focus. Verify the actual `Headless mode enabled`
log before starting a run. The existing game save is backed up separately.

## First native headless opening — 9 September 2026

After 535 passing offline tests and a clean Ruff check, one unselected native seed
was started on BLACK/GOLD, headless with rendering and audio disabled. The capped
prefix cleared Ante 1 in 12 coach requests, 16 actions and 134.392 seconds. All 16
actions were legal and all 3 played-hand scores matched the public scorer:
316 / 716 / 700. There were no errors or timeouts. The bot reached the Ante 2 shop
with $15 and Ice Cream; durable scoring is still needed before its chips decay.

Evidence: `runs/black-gold-opening-check-20260909/opening-audit.json`,
`segment-00/result.json`, and the public trajectory. This is an opening gate,
not an Ante 8 win or a measured win rate. Owned sticker behavior was not exercised
in this prefix. Continuation retains the same native game and seed.

## Same-game continuation and failure

The opening gate justified continuing that same game. It lost at Ante 5 Small
Blind with **23,816 / 25,000** chips. Cumulative result: 84 actions, 69 coach
requests, 991.42 seconds, two coach timeouts and one recovered RPC timeout. No
second game was started. The owned headless server was stopped after the loss.

All 17 played-hand scores across both segments matched native chip deltas, and
all 84 actions were legal. Rental charges, perishable countdown/expiry and selling
expired Droll were observed. Exhaustive legal-play enumeration at the final
blind's three played states found no higher immediate score: 9,576, 11,000 and
3,240 were each maxima. The final 4,424-chip deficit had no visible scoring rescue.
This does not establish that earlier shopping or discard decisions were optimal.

The next inexpensive investigation is build sustainability and discard allocation:
can public unseen-card composition identify better continuation prospects before
spending discards or retaining a kicker? Compare alternatives without using the
recorded future draw order, and report distributions rather than declaring the
observed losing draw inevitable. Do not start another game merely to collect
more losses. Public failure packets are saved in `failure-packets.json` alongside
`continuation-audit.json` under the same local run directory.

Black/Gold remains **unbeaten by this bot in this evaluation**. High-score probes
validate local retrigger choices only; they do not establish whole-run score gains.

Shop review found no dominant missed upgrade. Cash peaked at $15, and two paid
rerolls cost $10 total. A useful future probe is Ante 4's Negative-tag skip:
redemption depends on a later shop Joker and can require reroll spending, while
skipping also preserves perishable lifespan. The recorded next shop had no Joker,
but that outcome must not be supplied to a prospective decision evaluator.
Choosing Drunkard over Chaos and declining To Do List are also tradeoffs, not
established errors. Repeating sticker warnings would not address this failure:
the coach recognized the approaching expiry and bought replacement Mult.

### Cheap public continuation experiment

At the penultimate play, four choices each score 11,000 immediately. The offline
`kicker-experiment.py` samples 200 common uniformly shuffled permutations of the
32 public unseen cards and enumerates every next-hand play. It never reads a
later trajectory state, game seed or actual future draw. Runtime was 2.459 seconds,
with zero game/model calls. Probability of scoring the required 4,424 next hand:

| Played kicker | Estimated survival | 95% Monte Carlo interval |
| --- | --- | --- |
| None (draw four) | 27.5% | 21.8–34.1% |
| Six (bot choice; draw five) | 31.5% | 25.5–38.2% |
| Nine (draw five) | 31.0% | 25.0–37.7% |
| Ten (draw five) | 18.0% | 13.3–23.9% |

Six and Nine are indistinguishable at this sample size. The paired Six-minus-Ten
difference is 13.5 percentage points (approximate 95% interval 8.4–18.6). This
supports building bounded public continuation advice: it can distinguish some
equal-immediate-score plays cheaply. It does not find a superior move to the one
the bot chose, prove general improvement, or account for earlier build decisions.
The low survival probability means the position was already fragile before the
losing draw. Evidence: `kicker-experiment.json` in the same run directory.

## Bounded draw advice implementation

`analysis.draw_continuation` now supplies at most eight candidate actions using
48 common public-deck samples. Each sample refills the hand and scores every
legal next-play subset. Play rows include current play plus next play; discard
rows include discard plus next play. Their costs and horizons differ, so the
coach must not rank them by probability alone. Neither models later discards,
reorders, consumables or a whole-round policy. Wilson intervals show sampling
uncertainty, not uncertainty in game mechanics.

Admission is conservative: Red/Black, a non-boss blind, at most eight ordinary
visible cards, matching public remaining counts, and a short fixed-effect Joker
list. Growing Jokers, unknown runtime, special playing cards, forced slots and
boss draw rules suppress the advice. An already available scoring finish also
suppresses it. Candidate generation is incomplete; it is advice, not an allowlist.

Two artificial reduced-hand/deck probes have exhaustive independent oracles:
retaining a Two makes a guaranteed winning follow-up; equally scoring alternatives
have only 50% or zero success. They test both a play kicker and a discard. They
are not natural Black Deck openings. Run their offline checks with:

```sh
pytest -q tests/test_continuation.py tests/test_continuation_probes.py
python -m balatro_ai.probe tests/fixtures/continuation_probes.json \
  --output runs/continuation-probes
```

The complete offline suite passes **623 tests**. Replaying six saved failure
packets took 0.64–2.43 seconds for supported advice, including a run concurrent
with tests; the terminal no-draw state returned no advice. Evidence and the
four-call isolated advice ablation live under
`runs/continuation-advice-check-20260909/`. No native game was started for this
implementation check. General strategic improvement and a Black/Gold win remain
unproven.

### Isolated coach and sequence checks

The two constructed continuation cases passed with and without advice: four
single-attempt coach calls, all correct. This verifies the small decisions but
does not demonstrate an advantage from the new advice. Two further calls used
saved public failure positions with their original plans/history. At request
`8a82041f` (9,576 chips, two hands, one discard), the coach changed from discarding
slots `[1,2,3]` to playing `[3,4,5,6,7]` for 11,000, preserving its last discard.
These were isolated responses; no game actions were executed.

An offline sequence comparison then used 128 common uniformly shuffled public
decks and the same downstream bounded policy for both first actions. Discard
first won 72/128 (56.25%); play first won 73/128 (57.03%). The paired difference
was +0.78 percentage points, with an approximate 95% interval of −9.53 to +11.09.
Runtime was 40.45 seconds. There is no demonstrated advantage for either first
action. These estimates concern this one simulated position and policy, not
native game outcomes or whole-run win rates.

The policy takes an available scoring finish, otherwise uses 16-sample public
continuation advice for the remaining play/discard choice. It never sees the
simulated deck order. It is incomplete and assumes the guarded static scoring
mechanics; independent native validation of simulated continuations remains
outstanding. Evidence: `recorded-coach/result.json` and
`sequence-experiment.py` / `sequence-experiment.json` under
`runs/continuation-advice-check-20260909/`. Six isolated coach calls and zero
new native games were used in this implementation check. The gate for another
full run remains unmet; the next investigation is earlier build/economy decisions
and more representative fixed-state choices.


## Cross-build generalization gate — 9 September 2026

Reviewed public evidence from several archived runs, rather than tuning to the
first Black/Gold seed. Two narrow coverage changes: ordinary-face Photograph +
Hanging Chad support and Shoot the Moon support alongside Baron; intrinsic decay
facts for Ice Cream, Popcorn and Turtle Bean even without stickers. These are
conditional facts, not a ranked purchase policy. Installed native source verifies
decay triggers and that debuff pauses both their effect and decay.

Seven support/reversal checks vary face ranks/suits, absent or debuffed Photograph,
Queen support and unknown deck composition. Four synthetic decision cases have
independent arithmetic: active perishable survival, expired perishable plus
Mercury, Pluto plus Constellation, and adapting Photograph/Chad to The Plant.
Development/held-out labels were fixed before coach calls; labels and oracles
never enter packets. Two existing profitable/unprofitable rental cases provide
controls. Constructed states establish local decisions, not natural reachability
or whole-run win probabilities.

Validation: full suite 645 passed (57.15s), then the 11 newly added generalization
tests passed separately; Ruff and diff checks clean. Policy files were hashed
before the isolated coach calls and remained fixed through the fresh
native attempt. Evidence root: `runs/black-gold-generalization-20260909/`.
A fresh game uses native random generation, with no seed selection or inspection
of future offers. Opening checks concern legality, settings and score parity;
unfavorable offers are not grounds for restarting.


### Frozen native attempt and failure diagnosis

Six distinct isolated decisions passed in seven attempts: one transport timeout
was retried unchanged and passed. Policy was not tuned from their responses.
One fresh randomly generated BLACK/GOLD game then ran strictly headless, without
rendering-on-API or audio. The same game continued after its opening checkpoint;
no restart, seed shopping or mid-run policy change occurred.

It lost to **Ante 5 The Needle, 17,958 / 25,000**, after 107 actions and 85 coach
requests (1,169.516 seconds cumulative). All actions were legal; all 26 fully
checkable played scores matched. One hidden-card case was excluded from parity
claims. Two coach timeouts and two RPC timeouts were recovered. All 28 frozen
policy fingerprints still matched. The owned server was stopped after the loss.
This run passed Ante 5 Small, where the previous attempt failed, but two games
cannot establish a win-rate improvement.

The failure was already present in the build on boss entry. An exhaustive offline
check of 9,841 rank/suit representatives grants any cards from the public standard
52-card deck and optimistically retains opening Blue Joker and Green Joker
bonuses despite discards. Its maximum is **19,950**, below the 25,000 requirement:
ideal two Tens and two Fours give 266 chips × 75 Mult. Actual discards reduce the
bonuses to 246 × 73 = 17,958. Exhaustive legal final plays and all 720 Joker orders
confirm the final action was optimal. This is a rigorous bound within the public
scorer and verified build assumptions, not independent engine verification of
every hypothetical hand. No hidden draw order or future offers were used.

The next improvement should expose upcoming-boss scoring requirements before
shop purchases and blind skips, distinguishing one-hand capacity from aggregate
round capacity. An extra hand cannot address Needle's fixed one-hand limit.
The audit does not establish a winning alternative purchase sequence. Validate
any readiness mechanism on different bosses, builds and reversal cases before
spending another full run. High-score gains and a Black/Gold win remain unproven.

Evidence: `final-audit.json`, `failure-scoring.py`, `failure-scoring.json`,
`policy-provenance.json` and `server-stopped.json` under
`runs/black-gold-generalization-20260909/`.


## Boss preparation and action coverage — 9 September 2026

Added public upcoming-boss preparation, with an exhaustive optimistic one-hand
ceiling only for Needle and a guarded plain-deck additive build. Unknown runtime,
modified cards, consumables and unsupported Jokers suppress numbers. Future
scaling remains outside this snapshot calculation. Independent arithmetic and
reversal checks cover empty/basic/Foil builds and the diagnosed additive build;
other boss hints are checked across shop, pack and blind selection phases.

An independent audit also reproduced two general advice gaps. Targeted Tarot
combinations previously consumed the whole strategic shortlist; examples now
rotate across action, item, mode and target cardinality. Adjacent reorder advice
previously missed neutral bridges. A bounded search can now supply the first
neutral step toward a better order, distinguishing immediate and eventual score.
Neutral steps must decrease a stable canonical ordering, and direct suggestions
must improve on the globally best current play. Repeated candidate reselection
terminates across all six permutations of a three-Joker example.

Limits remain explicit: the reorder search can miss canonical-increasing neutral
paths, score-sacrificing paths, larger Joker rows and hand-order neutral bridges.
The coach may still reason about raw legal actions. Neither the new advice nor
the existing bounded discard analysis establishes global optimality. Shop policy
also now recognizes sellable replacements when assessing Buffoon packs, and
explicitly distinguishes Needle scoring from extra-hand resources.

Validation: **717 tests passed in 82.66 seconds**, Ruff and diff checks clean.
The first overlapping suite collected an unfinished pack fixture and failed nine
fixture-validation cases; the completed fixture and clean full rerun passed.
Historical public replay reproduces Needle ceilings 19,950 and 17,958 in 1.064s
and 0.685s, respectively; earlier unsupported builds suppress numerical claims.
Thirty policy files were frozen before six isolated coach decisions. Evidence:
`runs/black-gold-readiness-20260909/`. Native outcome will be recorded separately.

All six isolated cases passed in eight attempts; two transport timeouts passed on
unchanged retry. No feedback-based policy tuning. Seed-search tooling was briefly
assessed and deferred in favor of general decision improvements and a fresh
unselected native game. No seed analyzer installed or seed screening performed.


### Native outcome

The one fresh, unselected BLACK/GOLD game **won**: Cerulean Bell finished at
435,408/400,000 with one hand remaining. Peak hand 247,230; 264/264 legal actions,
220 coach requests, 3,011.125 cumulative seconds. Budget checkpoints resumed the
same native game twice; the audit records exactly one start. Four 90-second
coach timeouts recovered; no RPC timeout. All 30 policy fingerprints stayed
unchanged through completion. Native all-unlocked profile, no endless mode;
headless server 93553 stopped and port 12346 confirmed closed.

Observed preparation included buying Director's Cut, reserving cash and rerolling
Needle to House, then Crimson Heart to Cerulean Bell. The bot replaced expiring
Duo with Sock and Buskin before the final boss. These are observed decisions,
not causal proof that the new advice produced the win. A single run establishes
that this bot can win Black/Gold; it does not estimate consistency or exhaust
improvement opportunities. Extremely high scores remain a separate objective.

The frozen scorer audit found 32 exact matches, three unsupported hidden-state
plays, and two sub-chip mismatches. Independent native-source inspection confirms
`math.floor(hand_chips*mult)` at `functions/state_events.lua:744`; the public
scorer returned the fractional product. Recorded examples are 10,454.4→10,454
and 138,526.5→138,526. This correction is made only after the frozen run, with
separate validation; the original audit remains preserved.

Evidence under `runs/black-gold-readiness-20260909/`: `final-audit.json`,
`segment-02/result.json`, `policy-provenance.json`, and `server-stopped.json`.

Post-run correction: deterministic awarded scores now floor the final product;
explicitly stochastic Misprint/Bloodstone estimates keep their existing
expected-value semantics. Six new checks cover final fractions, preservation of
intermediate fractions, and stochastic/resolved cases. The corrected saved replay
has **34 exact matches, three unsupported, zero mismatches**. Its provenance
correctly records one changed scorer file against the original frozen policy.
The first full rerun exposed 16 old fractional expectations (707 passed); updated
arithmetic keeps the decision thresholds unchanged. The archived first-win test
now verifies exact native parity on all 54 plays while retaining its historical
18 fractional discrepancies and unchanged source evidence. No game was run to
validate the correction.

Final post-run validation: **723 tests passed in 64.39s**, Ruff and diff checks clean; corrected replay 34 supported matches and three excluded. No further gameplay.
