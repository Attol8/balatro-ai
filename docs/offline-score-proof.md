# What we can prove before another run

Reviewed 8 September 2026 against the archived public trajectories and current
Python scoring. No games or gameplay model calls were made. Locations use
zero-based JSONL event indices; add one for a text editor's line number.

The best next improvement is to quantify **safe production and scoring-engine
reliability**, then require the coach to account for those comparisons. “Always
play rather than discard” and “buy Mime” do not survive the same scrutiny.
These findings prove local calculations, not a higher final score or ante.

Reproduce from the repository root:

```sh
python -m scripts.audit_production_proof
python -m scripts.audit_build_proof
```

Both scripts assert legality and key scoring calculations against the archived
observations. Supporting checks: 45 tests passed across trajectory audit,
production advice and strategy arithmetic exercises.

## 1. An extra hand can earn more while guaranteeing the blind

Source: `evidence/astra-round-production-XV2MP8L5/segments/00/trajectory.jsonl.gz`,
event **454**; the coach's plan is at 452.

Against Ante 4's Flint, the player has four hands, two discards, $40, and
`A K K J T 6 5`. The requirement is 10,000. Fibonacci, Holographic Stuntman,
Mail-In Rebate, Baron and Hack are active. Mail pays $5 for each discarded Three.
The public remaining deck contains 32 plain cards, including three Threes.

The player ends the blind with the Five for **12,689**. An alternative is:

1. Play `K K J T 6`, retaining the Ace and Five: **3,965**.
2. Draw five cards. Discard any newly drawn Threes for Mail income.
3. Play the retained Five: **at least 7,101**, even without any held Kings.

The guaranteed combined score is **11,066 > 10,000**. New cards cannot reduce
this finish: the retained Five and active scoring effects persist, the remaining
cards are plain, and additional held Kings only help. The setup itself cannot
accidentally end this blind. One discard is enough for all possible drawn Threes.

With uniformly shuffled unseen cards, expected Mail income is
`$5 × 5 × 3/32 = $2.34375`. The extra hand costs $1 in unused-hand payout,
giving **+$1.34375 expected cash**, ignoring any further profitable use of
the second discard. Interest remains capped with $40 held. There is about a
41.03% chance of finding at least one Three; finding none loses that $1.

This is a survival guarantee plus an expected-money improvement, **not guaranteed
extra money on every shuffle**, and not proof of a later scoring improvement.
The current advice lists generic production opportunities but does not supply
this sequence or arithmetic. The model's plan says “Farm Mail when safe” and
then ends the blind: knowing the slogan is insufficient.

The general principle is to reserve a verified finisher and price the remaining
hands and discards. Hands can cycle junk; discards can generate Mail/Purple-seal
resources. But a hand that supplies no growth, useful draw or production usually
just sacrifices its cashout dollar. Scoring alone does not permanently grow the
deck; that requires a specific mechanic. Burnt Joker and discard-scaling engines
are reasons to discard; play-scaling engines and Ramen can change the tradeoff in
the other direction. Boss restrictions and consumable capacity must be included.

## 2. Spend excess score on keeping the engine available

Source: `evidence/astra-low-TAF7DNTX/segments/04/trajectory.jsonl.gz`, events
**837** (Death) and **841** (next play).

The model uses Death to turn a Queen of Hearts into a blue-seal Steel Three.
It could legally use the same Death to copy the visible Glass Jack of Spades.
Both cards are already visible; no future offer or draw is assumed.

The recorded next singleton Glass-Jack play scores **2,853,107,712**, exactly
reproduced offline. After the alternative Death target, that same play scores
**1,766,209,536**, still **2.94×** the Ox's 600-million requirement. Glass-face
inventory increases from three to four, instead of retaining three. The duplicate
stays held and is not exposed to this hand's Glass break roll.

This proves the immediate blind remains won while obtaining another critical
engine card. It trades away the Steel/Blue copy's scoring and generation value;
it is not full-state dominance. The model should see and price that tradeoff.

Before the final Tooth, the actual deck has **one Glass face in 57 cards**
(event 924). After all five discards miss it, one target remains among 29 unseen
cards (948). Even cycling five cards on each of the next three hands offers only
`15/29 = 51.72%` access before the last hand, conditional on that state. Access
alone also does not guarantee the full scoring combination.

For a uniformly shuffled deck, access to at least one of K targets in d distinct
draws is `1 − C(N−K,d)/C(N,d)`. In an illustrative otherwise matched 57-card
deck, seeing 43 cards gives **75.44%** access with one target versus **94.30%**
with two. Those are controlled deck-composition calculations, not the replayed
outcome of the Death alternative. Actual choices change draws, breaks and shops.

For endless play, report reliable score alongside peak score: probability of
assembling the engine before hands run out, replacement supply, and the next
blind requirement. Optimize duplication, removal and hand size against that
specific bottleneck. Blindly thinning the deck can also remove bodies needed
for income or draw cycling.

## 3. The model sometimes ignores scoring advice it already has

Source: TAF segment 04, request **945**, transition **948**.

The historical packet already offers a legal play estimated at
**1,192,568,832**. The model instead chooses a different flush, retaining its
red-seal Glass Ten while searching for the Glass Jack. Its chosen play is
estimated at **764,127** and actually scores **770,347**. The roughly 1,561×
comparison is between scorer estimates; do not label both as game measurements.
Another historical candidate before the third hand estimates **5,275,984,896**
versus **951,035,904** for the chosen action (actual **951,042,624**).

This is evidence of failing to apply existing advice, not solely missing tools.
It also is not proof of losing a winnable blind: the requirement is 94 billion,
and the alternative branches have not been played. Adding maxima from several
recorded hands is not a valid upper bound on the counterfactual blind, because
the selected cards determine later hands.

Require an explicit resource or survival justification when rejecting a vastly
stronger candidate. Retaining an engine card can be correct during safe setup;
preservation without a credible route to the requirement is not a plan.

## 4. Reject improvements that fail the arithmetic

The earlier review called Mime the strongest missed engine offer in 2K9H9HN.
Replacing Holographic Cloud 9 with that offered Mime in the next four recorded
hands actually lowers their scores by about **10.4%, 20.0%, 5.7% and 17.2%**
(segment 05 events 132, 170, 174 and 228). The calculation hydrates Fortune
Teller's publicly visible runtime. The swap also loses Cloud 9's round income.

Mime remains a possible growth pivot after further deck/hand-level development.
The available evidence does not prove the purchase is an immediate upgrade.
This is why generic synergy advice should become a replacement comparison that
includes lost additive Mult, scoring timing, income and draw reliability.

Also preserve the mechanics correction: Glass normally has one 1-in-4 break
chance per scored card, irrespective of retriggers. The earlier trajectory review
incorrectly attributed breakage to individual retriggers; the later video review
and current prompt corrected it. [Official Balatro clarification](https://bsky.app/profile/playbalatro.com/post/3lp3e5m64l22n).

## The cheapest useful proof process

1. **Certify fixed-state alternatives.** Reproduce the recorded score where
   deterministic; validate legal targets, order and all relevant mechanics.
   Tag unsupported or random effects instead of treating estimates as exact.
2. **Certify short production sequences.** Preserve named scoring cards and
   prove the finish for every possible draw when feasible, as in the Mail case.
   Otherwise enumerate public card categories with their exact probabilities.
   Include hands, cashout, discard effects, bosses, breakage and capacity.
3. **Evaluate deck edits quantitatively.** Compare survival now, target-access
   probabilities and engine redundancy. Price lost income or score. Avoid
   treating all beneficial resources as interchangeable scalar points.
4. **Verify advice application separately.** Build a small recorded decision set
   containing these cases and reversal cases where farming or a pivot loses.
   Deterministic proof checks cost no model calls. After they pass, a bounded
   decision-only coach evaluation can test whether the model follows the advice;
   no full game is needed for that stage. It has not been run here.
5. **Reserve games for the remaining question.** Only a controlled subsequent
   policy comparison can measure whole-run improvement. Match seeds, budgets and
   objective; seeds alone do not preserve future draws after different actions.

Keep the first implementation small: extend the existing numerical advice with
a finish certificate and net production comparison, plus deck-edit alternatives
that preserve the current clear. Reuse the public-state contract and scorer;
there is no need for a new model, hidden-state search or service.

For this project, endless survival is the current objective. Peak hand score is
a separate metric: an action can lower today's unnecessary overkill while raising
the chance of surviving to much larger future scores. The two verified examples
make that distinction concrete.

## Follow-up: larger gaps beyond those witnesses

The extra-hand example demonstrates a method; its $1.34 expected gain should
not be mistaken for the main explanation of an orders-of-magnitude score gap.
Further read-only investigation on 8 September found the following.

**The search process can skip an engine opportunity before model review.**
In XV segment 00, response **1240** schedules four follow-up rerolls with an
explicit `shop_has_any` stop list. Its persistent plan calls for Glass duplication
and replenishment, but the stop list omits DNA. Transition **1248** reveals DNA
for $8 with $78 held; **1250**, sourced as `coach_followup`, rerolls it away for
$6. There is no intervening coach request. This proves an opportunity-review gap,
not that purchasing DNA would have been correct: all five Joker slots were full,
and a sale plus safe qualifying first hand would have been necessary. Batched
search should stop for relevant generation/transition opportunities as well as
the model's familiar scoring targets. The current numerical engine-opportunity
list also does not cover DNA.

**Hand-level investment can lag behind the deck's evolving scoring potential.**
XV's actual peak at **1780**, 326,543,967, is a **level-1 Full House**; Pair is
level 17. Holding every other field and selected card fixed, one additional
Full House level gives **458,385,156** (+40.4%), two give **612,344,745**
(+87.5%). This follows the scorer's Full House gain of +25 chips/+2 Mult per
level. An Earth was actually offered for $3 at request **1259**, with $57 held;
the model rerolled at **1262** while continuing to prioritize Pair planets.
The model could not know this exact future draw. One offer does not establish
two obtainable levels, and this fixed-hand calculation does not replay subsequent
blinds or The Arm. It does establish why planet priorities should be recomputed
jointly with deck shaping and likely hand families, rather than fixed by a plan.

**Engine growth needs a numerical target.** The same 326-million peak is only
about 54.4% of the later 600-million boss requirement. The historical next ante's
47-billion Small Blind is about 143.9 times that peak. Small additive upgrades or
extra dollars cannot be assumed to bridge that gap. Before spending, identify
which available investment changes the number of multiplier activations, their
strength, or the supply of scoring cards, and calculate its payoff. Distinguish
temporary survival Jokers, generation tools and the eventual scoring arrangement;
each should have a reason to remain and a condition for replacement.

**Ordering is a tool limitation, but not a demonstrated cause in these hands.**
The current adviser examines adjacent swaps for its top three plays, retaining
only immediate score increases. This can omit a useful sequence whose first swap
is neutral or worse. However, enumerating all 5! Joker orders for the recorded
selected cards at XV **1780**, **1865** and **1869** found no higher score.
Do not blame this loss on an unverified ordering mistake. A future bounded joint
search over play, card order and copier arrangement could certify stronger
comparisons without model calls where the scorer covers the mechanics.

Other open questions are investment timing (production now versus scoring now),
resource stock sufficient for several upcoming blinds, and scoring reliability
under boss effects. Current tools expose some relevant facts but do not solve
these multi-step decisions. The strategy retriever returns at most three examples
ranked by offer/keyword specificity, without scoring urgency or investment payoff.
These are verified capability gaps; their effect on final score remains unmeasured.

Priority judgment: first improve **engine growth/transition planning and reliable
access**, then opportunity-aware search and quantitative deck/planet allocation.
Safe extra-hand farming belongs inside that larger plan. New games should test
specific improvements only after local arithmetic and saved-decision checks pass.
