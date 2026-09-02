# Superhuman Balatro AI Rebuild Plan

## Objective

Build an agent that exceeds a declared strong-human benchmark on clean Balatro runs while using only information available through the normal game interface. The active promotion target is Red Deck at Gold Stake on the declared single-machine compute budget. All-deck Gold remains the later generalization target, not a prerequisite for the first superhuman result. Fast-environment results, source-rule inventories, and isolated parity checks are supporting diagnostics, never success criteria.

## Active Objective (2026-09-02): Red/White Heuristic, Fair Jackdaw Rollouts, Then Gold

The exact two-decision tactical solver and certified Joker envelope have not
created a winning policy. Freeze them as differential and regression evidence;
do not widen them as strength levers. The active path is to build a competent
public-information Red Deck/White Stake policy, use an isolated synthesized
Jackdaw state as an approximate fair rollout model, and distill search only
after it beats the heuristic. Gold-stake work resumes only after that sequence
produces authoritative White-stake wins.

### Fixed constraints

- Real Balatro remains authoritative. Candidate results screen changes but
  never count as wins.
- Policy and rollout inputs contain only `PublicObservation`, sufficient typed
  public history, typed public actions, and a policy-owned search nonce. The
  live seed, private candidate state, hidden deck order, actual RNG, raw object
  IDs, and authority clones never cross the boundary.
- Unknown observation fields, runtime counters, actions, mechanics, phases, or
  synthesis requirements fail closed.
- Development, gate, and authority seed panels are distinct. Incomplete,
  rejected, timed-out, and illegal runs count as losses.
- Average round, ante, margin, and search activity are diagnostics. Promotion
  is based on paired authoritative win rate with a preregistered confidence
  criterion.

### Architecture

1. **Measurable evaluator.** Persist a versioned public terminal projection,
   loss-blind and visible-boss attribution, score margin, action/resource
   summaries, and policy diagnostics. Compare frozen artifacts on identical
   paired seeds and report both win discordances.
2. **Build-aware heuristic.** Replace prefix-truncated tactical choices with a
   hand-family-aware proposal that works at every supported hand size. Maintain
   a public build plan; compare plays and discards by survival value; score
   typed visible Joker runtime state; handle bosses; and make coherent shop,
   economy, consumable, voucher, tag, replacement, and ordering decisions.
3. **Isolated belief-rollout worker.** Accept only a strict serialized public
   belief state, search nonce, and rollout index. Synthesize a complete Jackdaw
   rollout envelope, including repository compatibility state; sample every
   unresolved latent from policy-owned tapes; project roots and successors
   through the public adapter; and deep-copy the synthesized envelope for
   sibling options.
4. **Search then compression.** Search coherent shop, pack, skip, and in-blind
   options to the next boss under a fixed Phase 1 continuation policy. Only
   after frozen search beats that policy, distill public sibling values into a
   compact model for pruning and continuation.
5. **Gold curriculum.** Add cumulative stake mechanics deliberately, including
   faster scaling, reduced discards, Eternal, Perishable, and Rental stickers.
   Preserve the same fairness and authority gates.

### Phase 0: Make Progress Measurable

- [x] Reproduce Red/White seed 63 at `b821b5b` and `HEAD` with one identical
  candidate command, then test every descendant revision. Locate the first
  action divergence and classify it as policy regression, engine correction,
  or infrastructure behavior; never restore an invalid win merely to recover
  the seed.
- [x] Extend candidate reports with the final public observation or a versioned
  lossless terminal projection, rejected decisions, terminal blind and visible
  boss, target/chips/margin, and per-run public action/resource summaries.
- [x] Add a versioned diagnostics field to the isolated policy response. Report
  exact-blind and pre-boss search attempts, completions, incompletions by
  reason, and changes without exposing engine or authority state.
- [x] Add paired report generation for two frozen candidate reports. Require
  identical seed/config panels, count incomplete runs as losses, and report
  baseline-only wins, candidate-only wins, ties, and paired deltas.
- [x] Add focused protocol, evaluator, telemetry, and paired-report tests. Run
  the relevant suite, inspect the diff, and produce a fresh seed-63 report.

#### Phase 0 gate

Seed 63 has a recorded first-divergence diagnosis; evaluator reports retain the
declared terminal and policy diagnostics; paired comparisons fail closed on
panel/config mismatch; and all focused tests pass.

#### Phase 0 result

The identical candidate bisect stays winning through `06d61c6` and first loses
at `c0b1bb5`. Decisions 0–49 are identical after accounting for the new public
schema fields. At decision 50 the old policy skips an Arcana pack; the expanded
public action contract exposes Temperance as a legal choice and the unchanged
pack ranker selects it at value zero without comparing against skip. This is a
policy regression revealed by a correct action-contract expansion, not an
engine-parity or infrastructure regression. Unknown zero-value Tarot/Spectral
choices now preserve the explicit skip baseline until a public value rule is
implemented. The instrumented seed-63 candidate run again wins at ante 9,
round 24 after 212 decisions, with the terminal Verdant Leaf target recorded as
100,000, final chips 115,307, and margin +15,307.

Candidate reports now retain the complete final public observation, a versioned
terminal projection, terminal-blind and visible-boss context, accepted action
and selected-card counts, rejected decisions, and strict per-search diagnostic
counters including incomplete-reason totals. Policy wire protocol v3 rejects
unknown diagnostic fields. The paired comparator rejects mismatched panels or
runtime/config evidence and preserves distinct policy inference budgets. The
focused Phase 0 and adjacent public-policy suite passes 118 tests.

### Phase 1: Blind-Aware, Build-Aware Public Heuristic

#### Phase 1 progress

- Full legal play/discard reachability no longer depends on the former 512-action
  or 2,048-candidate prefixes; focused 9-, 10-, and 13-card regressions cover
  the previously unreachable small hands.
- The strategic policy now plays immediately when its projected score clears
  the current blind, removes the artificial two-discard cap, and may cycle
  non-scoring kickers before the last hand. On the paired development seeds
  1--20 this raised average round from 6.2 to 8.0 and average ante from 2.35
  to 2.8: ten seeds improved, eight tied, and two regressed, with zero wins in
  both artifacts. Keep the change as a survival-floor improvement; it does not
  satisfy the strength gate.
- Source-audited, fail-closed static catalogs now cover exactly all 150 pinned
  vanilla Joker keys and all 28 vanilla bosses. The catalogs are knowledge
  layers only until their typed fields and rules are consumed by policy and
  scoring decisions.
- The public scorer now follows the pinned event order for played-card,
  retrigger, held-card, and left-to-right Joker-main effects. It also projects
  The Arm's public level reduction and normalizes tooltip x-mult float noise.
  On organic Red/White seeds 1--20 it exactly matched 395/395 deterministic
  play scores; 78 explicitly uncertain plays involved stochastic Jokers, The
  Hook, or face-down cards. The paired 20-seed screen gained 12 total rounds
  with no regression. On the full 200-seed panel, average ante/round improved
  from 3.640/10.740 to 3.725/11.000 and ante-5 reach from 50 to 59 runs, but
  both artifacts still won 0/200. The Phase 1 strength gate remains closed.
- One adjacent Joker reorder is now allowed only when the corrected scorer
  proves it raises the current best legal play and that play does not already
  clear. It fired twice and was terminal-progress neutral on seeds 1--20. A
  primary committed Planet may use the same $3 reserve as a high-value Joker;
  this was also neutral on that panel but closes a contradictory economy rule.
- Two plausible heuristics failed paired screens and were deleted. A repeated-
  score survival trigger for made-hand discards lost 11 total rounds versus
  the corrected scorer. Requiring three public plays before accepting a
  secondary Planet lost three total rounds. Do not tune either cutoff on the
  development panel.
- A 50-seed visible-offer audit found 377/1,073 shop Joker exposures and 15/58
  Buffoon choices were rejected by the public-complete support gate. Known-
  initial Green Joker, Ride the Bus, and Red Card are now admitted before their
  typed counters exist; deterministic Golden Joker, Chaos, and Rough Gem are
  valued only as economy effects. On 200 seeds this expansion completed every
  run, gained 17 total rounds and three total antes (32 improved, 25 regressed),
  and raised ante-6+ reach from 11 to 16, but still won 0/200. Average round is
  11.085. The strength gate remains closed.
- Two further strategy experiments failed and were deleted. Restricting pair-
  family Joker fit to guaranteed primary/secondary patterns lost three rounds
  and one ante on seeds 1--20. Early Investment/Coupon/Negative/edition-tag
  skips behind a 2x projected boss margin lost 26 total rounds and collapsed
  average ante from 4.00 to 3.75. Do not revive either global rule.
- The evaluator now persists semantic public action counters such as purchased,
  chosen, used, and sold item keys in addition to aggregate action counts. The
  counter is derived from the pre-action public observation and records no raw
  IDs or hidden state. This closes the remaining Phase 0 attribution gap.
- A fail-closed shop survival tiebreaker now requires an exact public
  `PlayCards -> CashOut -> SHOP` chain, deterministic agreement with the
  observed Big-Blind score, and a visible Wall or Violet Vessel. It may only
  prefer an already-supported affordable offer that flips the projected boss
  from loss to clear. It was terminal-neutral on 50 seeds; it is retained as a
  correctness floor, not a strength claim.
- Celestial packs may preserve a $12 reserve instead of the full $25 interest
  cap. On 50 development seeds this gained eight rounds and three antes (eight
  improved, four regressed). The Fish last-hand path now discards anonymous
  public slots as well as visible low cards: seed 20's terminal score improved
  from 3,314 to 18,110 and seed 30 from 5,694 to 7,906 without changing their
  terminal rounds. Both remain losses.
- A valued but reserve-blocked Joker no longer suppresses a building reroll.
  On 50 seeds this gained ten rounds and four antes (two improved, one
  regressed); seed 43 alone gained eight rounds and three antes from two valid
  additional rerolls. The retained candidate reached average ante/round
  4.02/12.04 on that panel with zero wins. A new 200-seed gate is pending.
- Additional rejected experiments are frozen as negative evidence. Hiker
  purchase support produced zero improvements and one two-round regression on
  50 seeds. Buying typed To Do List lost three rounds and one ante; its public
  target is used only when an organically owned copy can collect income on an
  already-clearing hand. Disabling Hieroglyph/Petroglyph lost 14 rounds on 20
  seeds; lowering guarded replacement to ante three lost seven; buying Arcana
  packs lost six. Allowing Green Joker discards lost five rounds with no
  improvements. Reserving open Joker slots for growth after two scorers was
  catastrophic, dropping average round from 11.90 to 9.25. Do not revive these
  global rules without a new causal model and a new development panel.
- The retained Celestial/Fish/reroll candidate completed all 200 Red/White
  seeds with zero wins, average ante 3.795, and average round 11.255. A
  public build-pacing rule then played the committed hand when its modeled
  score met the remaining per-hand blind pace. On the same panel it gained
  100 rounds and 35 antes (54 improved, 36 regressed), reached ante five on
  74 seeds instead of 60, and produced the first new candidate win at seed
  44. The resulting 1/200 win rate and average ante/round 3.970/11.755 are
  meaningful progression but fail the 20/200 strength floor, so Phase 2
  remains locked. Of the 199 losses, 198 exhausted both hands and discards;
  the broad failure is insufficient build score, not unused tactical actions.
- The next prespecified Phase 1 experiment will retain build pacing and replace
  category-only ties between direct Joker offers with an exact public scoring
  probe. It may use only the most recent fully visible deterministic play,
  must exactly reproduce the observed score, and must preserve current
  affordability, reserve, slot, and destructive-replacement gates. Screen it
  first on the paired development panel; retain it only if progression and
  terminal target ratio improve without losing the seed-44 candidate win.
- That exact-score shop probe passed its 50-seed screen: it gained seven rounds
  and two antes, improved ante-five terminal score/target from 0.71 to 0.77,
  and retained the seed-44 win. Keep it for the next gate. A subsequent strict
  build-confidence experiment failed and was deleted: requiring the primary
  lane to hold a majority before build pacing lost 58 rounds and 20 antes on
  the same panel and removed the only win. The useful Pair lane must accumulate
  public play evidence before it can dominate all build votes; do not revive a
  majority gate without changing the commitment model.
- The next isolated shop experiment removes the unrelated three-action reroll
  cutoff. A build with fewer than two modeled scorers, or a full lineup that
  still needs an upgrade, may reroll only when the configured six-action shop
  budget leaves a subsequent buy/leave action and the reroll preserves the
  existing economy reserve. Affordability, replacement, and support gates do
  not change. Screen this separately before merging it into a 200-seed gate.
- The wider reroll window failed and was deleted. It changed only seed 15 on
  the 50-seed panel, where it lost seven rounds and three antes, with no gains
  elsewhere and no additional win. Keep the bounded three-action reroll window
  until option values or a continuation model can justify extra rerolls.
- The next tactical experiment addresses typed face-down bosses. After first
  accepting any public modeled play that already clears, The House, Fish,
  Wheel, or Mark may discard only slots represented as `HiddenHandCard`, up to
  the legal five-card limit. This spends no hidden identity and prevents an
  all-hidden House opening from consuming a hand for a zero-information play.
  Non-face-down bosses and fully visible hands retain existing behavior.
- A shared face-down rule gained 12 rounds and six antes but regressed three
  seeds because Fish, Wheel, and Mark do not share The House's reveal
  lifecycle. The narrowed House-only rule is strictly better on the 50-seed
  screen: four improvements, zero regressions, +11 rounds, +5 antes, and the
  seed-44 win retained. Keep only `FaceDownMode.FIRST_HAND`; other face-down
  modes need separate public continuation models.
- The frozen exact-score-shop plus House candidate completed all 200 gate runs
  with 2 wins (seeds 44 and 189), average ante 4.065, and average round 12.005.
  Against build-pace-v1 it gained 50 rounds and 19 antes (25 improved, 13
  regressed), added seed 189, and lost no prior win. This is the strongest
  candidate so far but only a 1% win rate, so it fails the 20/200 Phase 1
  strength floor and Phase 2 remains locked.
- Both current wins bought at least six Celestial opportunities and converted
  them into a level-five Pair or level-eleven Two Pair build. Celestial floor
  screens were path-dependent: $3 added seed 41 but bought 55 additional packs
  and lost 27 rounds/seven antes; $9 kept the win but lost 32 rounds/12 antes.
  The $6 midpoint added seed 41 and kept seed 44 on seeds 1--50, but its full
  200-seed check merely swapped seed 189 for seed 41: one candidate-only win,
  one baseline-only win, and the same 2/200 total. Under the paired-win rule it
  is rejected. Restore the retained $12 reserve; Joker, voucher, reroll, and
  replacement reserves remain unchanged.
- The next isolated shop experiment applies the retained exact public scoring
  probe to destructive replacements. On a reproducible deterministic hand,
  evaluate the actual post-sale lineup and money after removing each sellable
  Joker and appending each affordable offer; require a strict score gain before
  selling. If the probe is unavailable, retain the existing typed category
  fallback. This addresses 71/200 category-only sales without expanding Joker
  support or weakening reserve/additive-mult/eternal/Negative gates.
- The replacement probe failed its 50-seed screen and was deleted: it
  suppressed three sales, produced two regressions totaling four rounds and
  one ante, and added no improvement or win. A single observed hand is useful
  for non-destructive offer ranking but is not sufficient replacement
  authority.
- The next tactical experiment makes discard keep-sets use the public remaining
  deck multiset. Pair/rank lanes retain made groups first and then prefer ranks
  with more public copies remaining; Flush lanes break equal held-suit counts
  by remaining suit supply; Straight windows prefer publicly completable
  missing ranks. This changes no hidden order, stochastic sampling, scorer, or
  search authority and fixes cases that currently keep an exhausted high rank.
- Deck-aware keep-set tie-breaking failed and was deleted. On 50 seeds it lost
  25 rounds and nine antes (four regressions, one improvement) while preserving
  the same single win. Composition-only completion supply sacrificed too much
  immediate card value and is not sufficient to change these discard ties.
- The next shop experiment removes a hardcoded option-order contradiction:
  direct Joker purchases currently return before any visible committed Planet,
  even when typed values are 45--85 versus 100 for the primary Planet. Rank
  already legal and reserve-affordable direct Jokers and Planets together;
  preserve the existing scores so a stronger build-compatible Joker may still
  win. Pack, voucher, capacity, reserve, and replacement rules do not change.
- Joint direct-Joker/Planet ranking failed its 50-seed screen and was deleted.
  It preserved the seed-44 win but lost four total rounds and three antes,
  including three large regressions, without adding a win. Retain Joker-first
  option ordering until a continuation value can price the open slot and the
  compounded value of future Planet levels.
- The next scorer increment models Blueprint and Brainstorm composition without
  trusting Jackdaw's inconsistent compatibility dispatch. Resolve copy chains
  from ordered public Joker slots, preserve duplicate occurrences and the
  copier's edition, and use the terminal target's typed public runtime. Admit
  only deterministic scoring-return targets already modeled by Phase 1;
  mutation, creation, RNG, joker-on-joker, and passive/global-rule targets fail
  closed. Refactor played- and held-card retriggers so duplicate and copied
  retrigger Jokers contribute separately. Copy offers remain worth zero without
  a publicly resolvable compatible target and are valued contextually otherwise.
  Require exact unit oracles for chains, cycles, debuffs, runtime, editions,
  played/held effects, retriggers, incompatible targets, and no-target offers
  before a paired seed screen.
- The conservative scorer and occurrence-aware retrigger implementation pass
  their exact tests. Contextual copy-card purchasing was terminal-neutral on
  seeds 1--50: it changed seed 31 from Seed Money to Brainstorm but changed no
  seed's terminal round, ante, or win. Remove that purchase authority and keep
  Blueprint/Brainstorm offers at zero until a continuation value exists; retain
  the scorer as differential correctness for organically owned copies.
- The next economy experiment removes value from vouchers whose benefit the
  deployed policy cannot consume. Tarot Merchant/Tycoon have no value while
  direct Tarot purchases and Arcana packs remain unsupported; Omen Globe has no
  value without Arcana packs; Retcon has no value without boss-reroll actions.
  Keep Planet, hand-resource, interest, discount, shop-capacity, edition, and
  consumable-capacity vouchers unchanged. This is an affordance correction,
  not a global voucher cutoff: the retained 200-seed policy bought Tarot
  Merchant 31 times for no reachable downstream action and none of those runs
  won. Screen the exact change on the paired 50-seed panel before promotion.
- The voucher-affordance correction passes the paired 50-seed screen: four
  seeds improve, none regress, total progression rises by eight rounds and two
  antes, and seed 44 remains a win. Promote this exact policy to the full
  200-seed panel; do not add further voucher changes during that run.
- The full 200-seed voucher panel retains both wins and improves average
  ante/round from 4.065/12.005 to 4.090/12.070. Six seeds improve, three
  regress, and net progression is +13 rounds/+5 antes; there are no paired win
  discordances. Retain the correction as the new heuristic floor, but the
  policy remains 2/200 and Phase 2 stays locked.
- The next Phase 1 design ports the public part of the June evaluator rather
  than its private fast-simulator planner. At a reproducible shop context,
  sample a small fixed set of hands without replacement from the public deck
  multiset using a digest-derived policy tape, score every legal play with the
  Phase 1 scorer, and estimate per-blind capability with the visible hand
  budget. Use one shared sample set for the current lineup and each affordable
  direct Joker offer. This projection may rank offers, permit a purchase that
  publicly flips the next visible blind from loss to survival, and justify a
  reserve-preserving reroll when the current build is projected dead. It may
  not step Jackdaw, inspect live order/RNG, synthesize shops, alter packs or
  replacements, or override an unavailable/inexact public context. Add
  determinism, hidden-twin, common-sample, survival-flip, and fail-closed tests
  before the paired panel.
- The combined projection authority fails decisively on seeds 1--50: it loses
  the seed-44 win, 122 rounds, and 40 antes. Public capability below the next
  target is too common early to justify a blind reroll; those rerolls displace
  vouchers, packs, and later purchases. Delete projection-triggered rerolls.
  Re-screen only common-sample offer ranking and direct purchases that flip a
  visible survival deficit. If that isolated authority regresses, delete the
  projection rather than tune its sample count or thresholds on this panel.
- The isolated projection still loses the seed-44 win, 16 rounds, and six
  antes, with four regressions and only two improvements. Delete the complete
  representative-hand projection and its tests. A small sampled point estimate
  is not reliable purchase authority; the next use of this evaluator belongs
  inside Phase 2 shared-particle continuation search after the Phase 1 gate,
  not in the heuristic.
- The next bounded June-derived slice is typed temporary-Joker lifecycle value.
  Price Ice Cream from visible remaining chips, Popcorn from visible remaining
  Mult, Ramen from visible xMult, and Seltzer from visible remaining hands.
  After the existing one general replacement, permit another sale only when
  one of those public counters is exhausted and a visible affordable offer
  clears the unchanged material-upgrade margin. Do not reopen general repeated
  churn, lower the ante-four gate, or use a one-hand destructive score probe.
  Add valuation and second-sale tests, then screen on the paired 50 seeds.
- The temporary-Joker lifecycle slice fails its paired screen and is deleted.
  It preserves the one win but loses four rounds and two antes versus the
  voucher-affordance floor, with regressions on seeds 39 and 42 and no paired
  improvements. Retain the one-replacement cap and the prior catalog values.
- Before treating candidate seeds 44 or 189 as wins, extend the existing real
  authority smoke runner with an explicit public-baseline selector. Non-smoke
  policies run through the same isolated `PolicyProcess` contract as candidate
  evaluation, the trace manifest records the resolved implementation and
  inference budget, and the child is closed on every exit. Preserve the
  current no-buy smoke default. Replay each frozen candidate win in non-fast
  Balatro with exclusive provenance-rich traces; incomplete or rejected runs
  are losses.
- The first seed-44 authority attempt is incomplete after four accepted
  actions and does not count. After choosing from a single-choice Buffoon
  pack, BalatroBot correctly returned to `SHOP` but retained the internal
  `G.GAME.pack_choices == 1`; the adapter passed that stale non-pack counter
  into `PublicObservation`, which correctly rejected it. Preserve the public
  invariant. Normalize a well-typed choice counter to zero outside an actual
  pack phase while continuing to require and type-check the raw field, add a
  focused post-pack regression, and retry with a fresh exclusive trace.
- The second authority attempt is a valid real Balatro win at ante 9, round 24
  after 182 accepted and zero rejected decisions. Its 185-row trace passes the
  exclusive hash-chain verifier. Candidate replay stops at transition 5 only
  because privileged canonicalization still retained the same closed-pack
  counter (authority 1, Jackdaw 0). Apply the same phase-derived zero to the
  canonical observed state, preserve the distinct raw digest and strict type
  check, then regenerate the authority trace; differential evidence has no
  retroactive normalization or mismatch waiver.
- The regenerated third authority attempt is again a complete real Balatro
  win at ante 9, round 24 after 182 accepted and zero rejected decisions. Its
  hash chain verifies and candidate replay agrees for 181/182 transitions.
  The sole remaining mismatch is the final Crimson Heart victory: authority
  clears the boss's transient Joker debuff before settled `ROUND_EVAL`, while
  Jackdaw clears playing-card debuffs and Joker facing but leaves the last
  selected Joker debuffed. Add a candidate-wrapper round-win compatibility
  step that clears only Crimson Heart's transient Joker debuffs, preserving an
  expired Perishable debuff, then replay the unchanged authority trace with no
  mismatch waiver. This is a parity repair, not a strength change.
- The Crimson Heart compatibility repair passes its focused tests and the
  unchanged third authority trace now replays in exact observed lockstep for
  all 182/182 accepted transitions. All 185 exclusive trace rows pass the
  hash-chain verifier against the clean pinned Jackdaw revision. Seed 44 is
  therefore a complete non-fast Red/White authority win with exact candidate
  replay evidence; the broad Phase 1 strength gate remains closed at 2/200
  candidate wins.
- A read-only affordance audit found 161 affordable, capacity-legal direct
  Tarot/Spectral offers across 149 of 572 shop roots on candidate seeds 1--20;
  the strategic policy bought none. Test the smallest deterministic slice:
  direct `c_empress` only, tied for the most exposures at 16. The public action
  contract and targeted-use scorer already support it. After committed Planet
  purchases and before packs, buy Empress only with an open consumable slot
  and while preserving the existing economy reserve; the existing
  `SELECTING_HAND` controller owns its visible 1--2-card target. Do not buy any
  other Tarot/Spectral card or reopen Arcana packs. The 50-seed screen requires
  complete runs, at least five observed buy-to-legal-use cycles, the seed-44
  win retained, and strictly positive paired round and ante totals; otherwise
  delete the slice.
- Direct Empress fails promotion and is deleted. It produced six direct buys
  and six legal visible-target uses with all 50 runs complete and no rejected
  actions, satisfying the contract/exposure checks. Seed 10 gained three
  rounds and one ante while seed 39 lost exactly three rounds and one ante;
  the aggregate round, ante, and win deltas are all zero. Permanent card
  improvement alone does not justify the displaced shop option.
- The next isolated Joker slice is Fortune Teller, the highest-frequency
  eligible deterministic scorer gap (eight shop appearances and zero buys on
  a read-only seeds 1--20 shadow). Do not parse its localized effect text or
  change the authority mod. Derive the displayed current Mult from the exact
  public history already owned by the isolated policy: count accepted Tarot
  `UseConsumable` and pack-pick actions, then enrich only Fortune Teller items
  in the policy's internal observation copy. If a future structured runtime
  counter exists and disagrees, fail closed. Reuse the generic typed current-
  Mult scorer and scaling valuation; absent history/runtime outside policy
  enrichment remains unsupported. Add public-history, score, inconsistent-
  runtime, and no-history tests. Screen on the paired 50 seeds and retain only
  if seed 44 remains a win and there is a strictly positive paired round and
  ante total with no new incomplete/rejected runs.
- Fortune Teller fails the paired screen and is deleted from the policy. Four
  copies were bought, seed 44 remained a win, and all 50 runs completed with
  zero rejected decisions, but the candidate lost four total rounds and one
  ante versus the voucher-affordance floor. Seed 34 gained one round and seed
  50 gained three rounds/one ante, while seeds 42 and 45 lost eight rounds/two
  antes between them. Keep the report as negative evidence; a public tally is
  not sufficient purchase authority without continuation value.
- The next isolated shop experiment addresses a distinct x-mult acquisition
  deadlock from the June heuristic. A read-only seeds 1--50 shadow found 11
  shops where the retained policy leaves despite ante three or later, an open
  Joker slot, at least two modeled scorers, no build-usable x-mult, and a
  reserve-preserving legal reroll. The prior wider-window failure changed only
  the action cap for rerolls that were already authorized; it did not authorize
  this open-slot structural hunt. After considering all visible purchases,
  vouchers, Planets, and packs, permit this exact state to use the existing
  three-action reroll window. Do not breach the economy reserve or alter full-
  lineup replacements. Keep only if all 50 paired runs complete with zero
  rejected actions, seed 44 remains a win, and aggregate round and ante deltas
  are both strictly positive; otherwise delete it.
- The open-slot x-mult reroll fails and is deleted. It preserves the seed-44
  win and all 50 runs complete without rejection, but only seeds 35 and 39
  change; they lose 13/4 and 3/1 rounds/antes respectively, for aggregate
  deltas of -16 rounds and -5 antes with no improvement. A structural need is
  not enough to price a blind reroll without option values.
- The next tactical experiment fixes a build-commitment contradiction rather
  than tuning a discard threshold. In an organic seed-1 opening, the public
  build is Pair and the hand already contains two 2s, but `_coverage_discard`
  replaces that committed keep-set with a larger four-card straight fragment
  and discards one of the pair. Across the retained 200 seeds, 3,089 discards
  cycle only 3.46 cards on average despite a five-card limit. When the visible
  hand already makes the primary target family, preserve that exact target
  keep-set and do not overwrite it with generic pair/suit/straight fragments;
  when the target is not made, retain the opportunistic fallback unchanged.
  Do not change build inference, boss rules, scoring, remaining-deck logic, or
  discard availability. The paired-50 gate requires complete rejection-free
  runs, seed 44 retained, no baseline-only win, strictly positive round and
  ante totals, and more improved than regressed seeds; otherwise delete it.
- The made-build discard invariant passes the paired 50-seed screen. All runs
  complete without rejection, seed 44 remains a win, and seed 6 becomes a new
  win. Aggregate progression is +8 rounds and +3 antes, with 15 improved and
  six regressed seeds. Promote this exact frozen change to the 200-seed gate;
  do not combine it with another policy experiment during that run.
- The full 200-seed gate confirms the discard invariant. All runs complete
  without rejection; wins rise from 2 to 4 (new seeds 6 and 59, retained seeds
  44 and 189) with no baseline-only win. Aggregate progression is +49 rounds
  and +13 antes, with 54 improved, 30 regressed, and 116 tied seeds. Retain it
  as the new Phase 1 floor. A 2% win rate still fails the required 20/200 floor,
  so Phase 2 remains locked.
- The next shop experiment targets the audited late reserve/upgrade deadlock.
  On the new floor's seeds 1--50, a read-only shadow found 18 late first-shop
  states with an exact reproduced public score below visible next-blind pace;
  six had a modeled score-improving option that the policy did not take, and
  five belonged to losing runs. At ante four or later, only at the first
  settled shop action with an exact score reproduction, allow one coherent
  sell-then-buy Joker replacement when the current lineup cannot meet the
  visible next target, the post-sale lineup plus offer strictly improves that
  exact score, the transaction leaves at least $12, and the offer remains a
  supported scorer. Preserve Eternal/Negative, additive-mult, legality, and
  action-budget gates; infer the follow-up purchase solely from the immediately
  preceding public sale/history. Do not authorize rerolls, packs, or unrelated
  repeated churn. The paired-50 gate requires complete rejection-free runs,
  both current wins retained, at least one candidate-only win, no baseline-only
  win, and strictly positive total round and ante deltas; otherwise delete it.
- The emergency score-replacement experiment fails its paired gate and is
  deleted. All 50 runs complete without rejection, but wins fall from two to
  zero because seeds 6 and 44 both regress from completed runs to ante-seven
  losses. Aggregate progression is -16 rounds and -8 antes, with three
  improved, eight regressed, and 39 tied seeds. The exact one-hand score delta
  is too myopic to price the downstream value of the sold Joker; retain the
  candidate report as negative evidence and keep the made-build discard policy
  as the Phase 1 floor.
- The next isolated blind-selection experiment consumes two immediate strong
  Small-Blind tags that the current policy always ignores. Skip for `Meteor
  Tag` when the visible boss is known and not a high-target Wall/Violet
  Vessel; its guaranteed Mega Celestial pack is already handled by the
  committed-Planet pack policy. Skip for `Top-up Tag` under the same boss gate
  only when at least one Joker slot is open, so the immediate free Common
  Joker reward is not wholly wasted. Do not add Coupon/Voucher/edition/random-
  rarity tags, inspect future pack/Joker contents, or change shop/pack policy.
  The paired-50 gate requires complete rejection-free runs, both current wins
  retained, at least one candidate-only win, no baseline-only win, and
  strictly positive total round and ante deltas; otherwise delete it.
- The immediate Meteor/Top-up tag slice fails its paired gate and is deleted.
  All 50 runs complete without rejection and both wins remain, but it adds no
  win, total rounds are exactly unchanged, and only three seeds improve while
  five regress. Total ante progression is +3; seed 38 reaches ante eight, but
  that isolated near-solve is not sufficient authority to tune a tag rule on
  the development panel. Retain the report as negative evidence.
- A proposed Ice Cream scorer gap is not real in organic candidate state and
  is not implemented: a direct seed-12 shop observation exposes the fresh
  card's typed `current_chips=100`, and the existing generic runtime scorer
  projects the exact offer delta from 3,744 to 5,544. Keep the runtime path;
  do not add a duplicate static +100 branch.
- The next isolated shop experiment ports the narrow structural Buffoon rule
  from the preserved June heuristic. At ante four or later, after direct
  cards/vouchers have had their existing priority, permit a Buffoon pack when
  a Joker slot remains open, the build already has at least two modeled
  scorers, no build-usable x-mult, and the purchase preserves the full existing
  economy reserve. The existing pack policy chooses or skips visible contents;
  do not change pack scoring, full-slot behavior, earlier-ante acquisition,
  rerolls, or replacements. A read-only seeds 1--50 audit found 58 ignored
  open-slot Buffoon exposures with at least two scorers, nearly all without
  usable x-mult. The paired-50 gate requires complete rejection-free runs,
  both current wins retained, at least one candidate-only win, no baseline-
  only win, and strictly positive total round and ante deltas; otherwise
  delete it.
- The late structural Buffoon slice is behaviorally inert and is deleted. All
  50 paired runs complete without rejection, both retained wins remain, and
  every seed has exactly the same terminal win, round, and ante as the Phase 1
  floor. The policy never reaches this fallback after the higher-priority shop
  rules on the audited paths, so visible offer frequency alone overstated its
  decision reachability. Retain the candidate report as negative evidence.
- A read-only replay of the preserved June evaluator's generic 1.5x per-hand
  pace override is also negative. It changes 13 decisions on seeds 1--10 but
  reduces aggregate progression from 123 rounds/44 antes to 109 rounds/39
  antes while leaving the same single win. Do not port that global pace rule;
  build-specific action shaping needs its own causal gate.
- The next bounded correction repairs the Observatory path end to end. The
  retained 200-seed floor buys Observatory on seeds 92 and 123; both lose at
  ante seven, and seed 123 dies at 54,920/70,000 while visibly holding Uranus.
  The policy already retains Planets after buying Observatory, but its scorer
  omits the public held-Planet x1.5 effect and its shop policy blocks every
  Celestial pack. Worse, pinned Jackdaw documents the passive but does not
  apply it in `score_hand`, so affected candidate outcomes are understated.
  Add the exact source-ordered effect to the candidate compatibility layer:
  each non-debuffed held Planet matching the detected hand multiplies Mult by
  3/2 after Joker scoring and before the deck-back final-scoring step. Add the
  same typed effect to the public scorer and permit a Celestial pack under
  Observatory only when a consumable slot is open; direct Planet prices,
  reserves, pack choice, and the existing hold behavior do not change. Tests
  must cover one/multiple matching Planets, a nonmatching Planet, debuff, and
  Plasma ordering. The paired-50 strength screen requires complete
  rejection-free runs, both retained wins, no baseline-only win, and strictly
  positive total rounds and antes. Candidate parity remains provisional until
  an organic Observatory authority transition replays exactly.
- The paired seeds 1--50 Observatory screen is exactly neutral because the
  voucher is absent from every run: all 50 terminal win/round/ante tuples are
  identical to the floor. This is an empty treatment group, not strength
  evidence, so it neither promotes nor rejects the source-backed correction.
  Re-plan the behavioral check around seeds 92 and 123, the only Observatory
  owners identified before implementation in the retained 200-seed report.
  Both targeted runs must complete without rejection and improve their exact
  paired terminal progression before spending a full-panel gate. The
  compatibility correction remains provisional until organic authority
  lockstep; do not count it as a Phase 1 win-rate gain on the neutral panel.
- The targeted check partially validates the correction but rejects the shop
  expansion. Seed 123 advances from ante 7/round 21 at 54,920/70,000 to ante
  8/round 23 after the held Uranus scores; seed 92 raises its terminal chips
  from 13,022 to 16,534 but remains at ante 7/round 21. Enabling Celestial
  packs under Observatory bought three extra packs on seed 92 without clearing
  its Needle, so remove that unproven purchase authority. Retain only the
  exact public scorer and candidate-kernel effect as provisional correctness;
  the 4/200 made-build report remains the strength floor and no full-panel
  promotion run is warranted by this sparse result.
- A scorer-only replay after removing the Celestial expansion reproduces the
  same targeted result: seed 92 remains ante 7/round 21 and seed 123 reaches
  ante 8/round 23. Thus the exact held-Planet correction, not the extra pack
  spending, causes the advance. It remains correctness evidence rather than a
  win-rate promotion.
- A separate scaling-action audit rejects another tempting tactical lever.
  On seeds 1--10, Square is owned in 93 selecting-hand states and already
  triggers on 57 best plays; Trousers triggers whenever its qualifying hand is
  available. Forcing an exact four-card Square play whenever it meets remaining
  per-hand pace changes ten states but drops progression from 123 rounds/44
  antes/one win to 111/39/zero. Do not spend survival margin merely to grow a
  visible scaling counter.
- The next shop experiment addresses a different, quantified lockout. The
  retained policy allows at most one general Joker replacement in the entire
  run because `already_replaced` scans all public history. Of 63 losing runs
  that end at ante four or later with a full lineup and at least $25, 40 had
  already used that single sale and can never upgrade again. Scope the cap to
  one coherent sell-then-buy transaction per shop visit while preserving the
  ante-four, full-lineup, known-card, Eternal/Negative, additive-Mult,
  affordability, reserve, material-margin, and remaining-action gates. Do not
  allow a second sale in the same shop or change any value. The paired-50 gate
  requires complete rejection-free runs, both retained wins, no baseline-only
  win, at least one candidate-only win, positive total rounds and antes, and
  more improved than regressed seeds; otherwise delete it.
- Per-shop replacement fails and is deleted. All 50 runs complete without
  rejection and both wins remain, but no seed improves; seeds 15 and 19
  regress for aggregate deltas of -5 rounds and -2 antes after additional
  Golden Joker/Raised Fist and Onyx Agate/Stencil churn. Restore the lifetime
  one-replacement cap. Full-lineup stagnation is real, but category margins do
  not supply the continuation value needed to solve it.
- The next isolated Joker slice makes Burnt Joker a coherent build tool rather
  than merely admitting an unsupported shop offer. Local vanilla source and
  pinned Jackdaw agree that a non-debuffed Burnt Joker levels the poker hand
  represented by the first explicit discard of each round. Give the offer a
  contextual utility value, but do not treat it as a direct scorer. During a
  blind, alter only the existing fallback-discard path: after an already-
  clearing play, boss recovery, and a committed hand that meets per-hand pace
  have all been rejected, prefer the cheapest fully visible legal discard that
  exactly makes the committed primary hand. Require an unused first discard,
  an active Burnt Joker, and no Green Joker or Ramen; hidden cards and malformed
  states fail closed. Multiple Burnt copies and Blueprint/Brainstorm copying
  remain unsupported because the pinned candidate and vanilla copy semantics
  are not yet differentially locked. This must not force an extra discard where
  the retained policy would already play. The paired-50 gate requires complete rejection-
  free runs, both retained wins, no baseline-only win, at least one candidate-
  only win, positive total rounds and antes, and more improved than regressed
  seeds; otherwise delete the policy slice and retain only any independently
  proven correctness tests.
- Burnt Joker fails the paired screen and the policy slice is deleted. All 50
  runs complete without rejection and both retained wins remain, but every
  seed has the same terminal win/round/ante tuple as the Phase 1 floor. Seed 11
  is a real treatment: it buys Burnt, raises Pair from level four to level ten,
  and cycles fewer cards, but it also displaces Seeing Double and one Planet
  purchase and still dies at the same ante-six blind. Aggregate round and ante
  deltas are exactly zero with no candidate-only win. A correct mechanic is
  not purchase authority; retain the report as negative evidence.
- A proposed pre-boss Luchador purchase exposed a candidate correctness gap
  before policy work began. Pinned Jackdaw implements Luchador's
  `selling_self` result and `Blind.disable`, but its sell handler removes the
  sold card without firing or applying that result. Therefore the existing
  public policy can already sell an organically owned Luchador while the
  candidate silently leaves the boss active. Repair this in the candidate
  compatibility boundary first: capture a Luchador sale before removal, apply
  `Blind.disable` only to a live non-disabled boss, restore Water discards,
  Needle hands, and Manacle hand size, preserve the changed Wall/Violet target,
  clear Cerulean forced selection, reveal face-down cards/Jokers, and clear
  debuffs. Non-boss sales remain unchanged and malformed private engine state
  fails closed. Add focused ordinary-boss and special-boss regressions. The
  correction is provisional until an organic authority Luchador sale replays
  exactly; no purchase authority or strength claim may depend on it before the
  local contract passes.
- The local Luchador contract now passes. The compatibility boundary captures
  the sold card before removal, applies the existing pinned `Blind.disable`
  transition afterward, and explicitly consumes its public side-effect
  descriptor. Focused tests cover capture, ordinary/non-boss behavior, Water,
  Needle, Manacle, Wall, Violet Vessel, Cerulean Bell, face-down reveal, and
  Crimson Heart cleanup. Keep parity provisional pending an organic authority
  sale; the correction itself is retained as a source-backed candidate fix.
- With that local contract repaired, test one dedicated Luchador purchase rule
  without assigning it a generic Joker value. Only after both visible normal
  blinds are defeated and a typed survival-relevant boss is `UPCOMING`, buy a
  base, non-Eternal Luchador into an open slot if the full purchase price
  preserves the current economy reserve and no owned Luchador or Chicot already
  supplies the effect. Existing modeled direct Joker purchases keep priority;
  the rule does not affect Buffoon choices, replacements, rerolls, or shops
  before Small/Big blinds. The existing first-action boss sale owns execution.
  Exclude money-only bosses because this slice prices survival, not cashback.
  The paired-50 gate requires complete rejection-free runs, both retained wins,
  no baseline-only win, at least one candidate-only win, positive total rounds
  and antes, and more improved than regressed seeds; otherwise delete only the
  purchase rule while retaining the independent candidate correction.
- The reserve-safe pre-boss Luchador purchase rule is behaviorally inert and
  is deleted. No seed in the paired 50 treatment panel buys or sells a
  Luchador under the full contract, and every terminal win/round/ante tuple is
  identical to the Phase 1 floor. Keep the compatibility correction and its
  tests; do not weaken the reserve or boss-position gates on this panel merely
  to manufacture treatment.
- The next isolated economy slice tests Riff-Raff without pretending its
  generated Jokers have deterministic value. Pinned integration tests cover
  its `setting_blind` creation, sequential Common-pool draws, edition rolls,
  and capacity handling, but the pre-blind search capability correctly remains
  closed. Add a dedicated direct-shop fallback only: at ante three or earlier,
  after modeled Jokers, vouchers, and committed Planets have all declined,
  buy a base Riff-Raff only when at least one Joker slot will remain after the
  purchase and the full cost preserves the economy reserve. Do not assign a
  generic `_joker_value`, choose it from Buffoon packs, predict its children,
  or admit it to replacement/search. Resulting Jokers become usable only after
  their ordinary public descriptors appear. The paired-50 gate requires
  complete rejection-free runs, both retained wins, no baseline-only win, at
  least one candidate-only win, positive total rounds and antes, and more
  improved than regressed seeds; otherwise delete the policy slice.
- The early direct Riff-Raff slice fails and is deleted. It produces one real
  treatment on seed 14, where the generated public Jokers eventually replace
  Riff-Raff, but the run dies six rounds and one ante earlier. No seed improves,
  both wins remain, and all 50 runs complete without rejection; aggregate
  deltas are -6 rounds and -1 ante. Keep Riff-Raff outside generic valuation,
  packs, replacement, and search until option values can price its stochastic
  children.
- Re-open the late exact-score replacement question only after repairing the
  transaction contract that invalidated its first test. In the retained 200
  seeds, 29 of 35 ante-four-plus losses within 15% of their target have five
  Jokers, and 21 of those also retain at least $25. The prior emergency report
  sold Hack on winning seed 44 without a corresponding post-sale purchase;
  its sell and buy priorities were not atomic, so the large regression does
  not isolate replacement value. At the first action of a shop only, require
  an exactly reproduced fully visible deterministic hand whose current
  per-blind capacity misses the next visible target. Enumerate one public
  sellable non-Eternal/non-Negative Joker and one visible deterministic
  supported scoring offer; the post-sale lineup and money must strictly raise
  exact score, leave at least $12, preserve the sole additive-Mult role, and
  fit the remaining shop-action budget. Return the sale only after freezing
  that unique best pair by deterministic public fields. On the immediately
  following SHOP observation, recompute the same pair from the preceding
  public state/history and force its still-visible legal `BuyShopCard` before
  consumables, Planets, or other shop priorities. Any mismatch fails closed.
  Exclude sale-reactive Campfire/Swashbuckler and stochastic score contexts.
  Preserve the lifetime one-replacement cap. The paired-50 gate requires
  complete rejection-free runs, both retained wins, no orphan sale, no
  baseline-only win, at least one candidate-only win, positive total rounds
  and antes, and more improved than regressed seeds; otherwise delete the
  repaired experiment.
- The repaired atomic replacement executes complete sell-then-buy transactions
  but still fails the paired gate and is deleted. All 50 runs complete without
  rejection and retained wins 6 and 44 remain, but there is no candidate-only
  win. Only seeds 7, 30, and 42 change terminal progression: seed 7 improves,
  seeds 30 and 42 regress, for aggregate deltas of -5 rounds and -2 antes.
  Correct transaction sequencing therefore does not rescue exact single-hand
  score replacement; downstream build and option value remain the missing
  variables. Preserve the candidate report as negative evidence.
- The next isolated discard experiment fixes redundant Pair keep-sets. When a
  committed Pair is already visible but below the existing per-hand pace, the
  current keep-set retains every paired rank; with two or three pairs this can
  leave only one or two discard slots and repeatedly redraw the same hand
  strength. Retain exactly one two-card pair, chosen by the existing public
  scorer over every visible same-rank pair combination, and cycle the remaining
  cards through the unchanged five-card discard limit. Do not alter made-hand
  detection, build inference, Green/Ramen gates, play priority, remaining-deck
  logic, or any non-Pair lane. Add exact selection and hidden-twin tests. The
  paired-50 gate requires complete rejection-free runs, retained wins 6 and
  44, no baseline-only win, at least one candidate-only win, positive total
  rounds and antes, and more improved than regressed seeds; otherwise delete
  the policy slice and preserve its report as negative evidence.
- Single-pair retention fails decisively and is deleted. It increases discarded
  cards by 151 on seeds 1--50 and creates a new win on seed 29, proving real
  treatment, but loses retained seed 44 and drops 64 rounds and 18 antes. Ten
  seeds improve while 16 regress. Aggressive cycling changes downstream draw
  and shop trajectories too broadly; do not tune which pair survives against
  this development panel without a continuation value.
- A read-only paired-panel shadow exposes a separate build-pacing bug. Across
  seeds 1--50, 129 chosen discards reject a public best play that already meets
  the remaining per-hand survival pace and belongs to the committed hand
  family. Pair builds discard a pace-clearing Two Pair 117 times and a Three
  of a Kind 12 times because `_build_pace_play` requires exact hand-name
  equality. Accept a play only when the existing public scorer proves it meets
  pace and `_hand_matches` proves it is the primary hand or a strict in-family
  upgrade. Preserve boss eligibility, exact scorer ordering, and all
  off-family behavior; in particular, Two Pair builds must not treat a lone
  Pair as an upgrade. Add Pair/Two-Pair, Full-House, off-family, and hidden-twin
  regressions. The paired-50 gate requires complete rejection-free runs,
  retained wins 6 and 44, no baseline-only win, at least one candidate-only
  win, positive round and ante totals, and more improved than regressed seeds;
  otherwise delete the slice and preserve its report.
- Family-upgrade pacing fails and is deleted. It is a high-treatment change,
  saving 310 discarded cards across seeds 1--50, but wins remain two while
  aggregate progression falls 35 rounds and eight antes. Ten seeds improve
  and 15 regress. Playing a currently pace-clearing related hand sacrifices
  too much later draw quality and scaling; exact current score is again not a
  sufficient continuation value. Preserve the candidate report.
- The next shop experiment addresses the build prior's self-lock. Joker
  archetype mismatch currently returns value zero, so the default Pair plan
  refuses supported build-defining x-mult such as Trio, Family, Order, Tribe,
  and Ancient Joker before an owned card can pivot the public build votes.
  Only in ante one or two and with fewer than two modeled scoring Jokers,
  assign a discounted buy value to a supported x-mult offer whose explicit
  hand archetype does not match the current plan. Keep ordinary exact-score
  ranking ahead of the fallback, preserve the existing building reserve and
  legality/capacity rules, and do not change `_joker_value`, replacements,
  later antes, non-x-mult cards, or x-mult without a hand-family archetype.
  Add early/late, scorer-count, unsupported, and hidden-twin tests. The paired-
  50 gate requires complete rejection-free runs, retained wins 6 and 44, no
  baseline-only win, at least one candidate-only win, positive round and ante
  totals, and more improved than regressed seeds; otherwise delete the slice
  and preserve its report.
- The bounded early x-mult pivot is an empty treatment and is deleted. It
  changes no semantic action and every terminal win/round/ante tuple is
  identical on seeds 1--50. Do not widen the ante or scorer-count bounds on
  this development panel merely to expose the rule; preserve the report as
  reachability evidence.
- The next consumable slice restores deterministic direct-shop economy from
  the June policy without reopening Arcana packs. The strategic controller
  already uses held Hermit and Temperance but never buys either from a visible
  shop. With an open consumable slot and two remaining shop actions, buy
  Hermit only when `min(2 * (money - cost), 20)` strictly exceeds current
  money, or Temperance only when the capped sum of visible Joker sell values
  minus cost is a strict cash gain. The next SHOP action already uses the held
  card before all other priorities, completing the public buy/use cycle.
  Preserve legality, consumable capacity, action budget, and every other
  direct-card/pack priority; malformed or missing costs fail closed. Add
  profitable/unprofitable, capacity, budget, immediate-use, and hidden-twin
  tests. The paired-50 gate requires complete rejection-free runs, retained
  wins 6 and 44, no baseline-only win, at least one candidate-only win,
  positive round and ante totals, and more improved than regressed seeds;
  otherwise delete the slice and preserve its report.
- Direct Hermit/Temperance purchase fails and is deleted. The policy completes
  three Hermit and 13 Temperance buy/use cycles without rejection and retains
  both wins, but adds no win and loses seven rounds and three antes overall;
  two seeds improve and four regress. Hermit advances seed 38 to ante eight,
  but that sparse near-solve does not satisfy the gate or justify threshold
  tuning on the development panel. Preserve the report as negative evidence.
- The next coherent build experiment repairs owned hand-specific x-mult
  commitment. Fifteen losses in the retained 200-seed floor finish with Duo,
  Trio, Family, Order, or Tribe, yet almost all keep a different Pair/Two-Pair
  lane because every Joker archetype currently contributes the same two votes.
  Weight an owned deterministic hand-specific x-mult as a build-defining
  signal for attainable Pair, Straight, and Flush lanes. Three/Four-of-a-Kind
  may receive the stronger vote only after public play or level evidence shows
  the lane has been made; otherwise keep the existing weak vote. Do not change
  shop valuation, Planet valuation, play pacing, discard mechanics, or
  unconditional/held-card x-mult. This makes the existing exact Planet and
  discard commitments follow a scorer the policy already bought without
  reopening the rejected early-offer pivot. The paired-50 gate requires
  complete rejection-free runs, retained wins 6 and 44, no baseline-only win,
  at least one candidate-only win, positive round and ante totals, and more
  improved than regressed seeds; otherwise delete the policy change and keep
  its report as negative evidence.
- Owned hand-specific x-mult commitment fails and is deleted. All 50 runs
  complete without rejection and wins 6 and 44 remain, but only seed 41
  changes: committing its Trio build loses six rounds and two antes. There is
  no candidate-only win or improvement. A visible conditional multiplier is
  not sufficient evidence that the deck can repeatedly make its hand; retain
  the weak generic Joker vote and the candidate report as negative evidence.
- The next tactical experiment delays build pacing until a build can exist.
  In ante one the current rule can choose an 88-chip Pair over an already
  visible 200-chip Straight merely because both meet average per-hand pace,
  spending extra hands and losing the dollars that seed the first shops.
  Disable only `_build_pace_play` in ante one; the exact best-play scorer,
  clear-now priority, existing discard fallback, boss legality, and every
  ante-two-plus commitment remain unchanged. Add a regression showing the
  stronger visible hand wins this opening while the existing ante-two build
  pacing remains active. The paired-50 gate requires complete rejection-free
  runs, retained wins 6 and 44, no baseline-only win, at least one
  candidate-only win, positive round and ante totals, and more improved than
  regressed seeds; otherwise delete the slice and retain its report.
- Delaying ante-one build pacing fails and is deleted. It is a broad treatment:
  15 seeds change, with large gains on seeds 22, 32, and 47, but it loses the
  seed-44 win and regresses eight seeds versus seven improvements. Aggregate
  movement is only +3 rounds and zero antes. The committed low-hand opening is
  path-dependent but cannot be replaced by immediate-score maximization alone;
  preserve the report and the retained pacing rule.
- The first-divergence audit narrows the same mechanism without seed-specific
  state. The lost seed-44 path first changes on the ante-one boss, while the
  largest rescues begin on ordinary Small/Big Blinds where unused-hand dollars
  are still the relevant payoff. Disable build pacing only before the first
  boss (`ante == 1` and no current boss rule); retain exact build pacing for
  that boss and every later blind. This is a new prespecified slice, not a
  threshold fitted to a digest. Its paired-50 screen requires both wins
  retained, positive total rounds and antes, more improvements than
  regressions, and no incomplete/rejected runs before a 200-seed gate.
- The narrowed pre-boss economy rule also fails and is deleted. It preserves
  both wins and changes 11 seeds, but only four improve while seven regress;
  aggregate movement is +1 round and -1 ante. Immediate-score/discard policy
  is not a reliable substitute for the retained build commitment even on
  ordinary opening blinds. Preserve the candidate report and restore the
  original pacing rule everywhere.
- Re-plan Phase 1 around a coherent candidate policy instead of further local
  overrides. Add a separately named `phase1_june` policy that keeps the
  retained public play/discard/scorer/boss controller but replaces the shop
  sequence with the public-only June evaluator: use held consumables first;
  keep one coherent replacement intent; compare visible supported Jokers,
  committed Planets, useful vouchers, and supported pack classes in one
  benefit-minus-cost scale; then apply the June reroll gate or leave. Joker
  values use public ante, money, hand-play counts, owned typed runtime, slot
  pressure, and missing x-mult, never private deck order, seed, candidate
  state, future RNG, or a simulator step. Keep the retained policy unchanged
  during the experiment so the rewrite has a trustworthy paired control.
  Arcana is included only through visible pack purchase and the existing typed
  pack-target policy; Standard/Spectral remain zero until their portfolio
  values are modeled. Add selection, capacity, affordability, determinism,
  and hidden-twin tests. The first paired-50 gate requires complete
  rejection-free runs, both retained wins, at least one candidate-only win,
  positive total rounds and antes, and more improvements than regressions.
  Only then replace the retained shop controller and run the 200-seed strength
  gate.
- The first coherent June screen fails. It creates a new win on seed 27 and
  improves 21 seeds, but loses retained wins 6 and 44, regresses 21 seeds, and
  drops 39 rounds/seven antes. The candidate buys 204 Arcana packs across 50
  runs; this is the same unsupported portfolio failure already seen in the
  isolated Arcana experiment, now magnified by benefit-minus-cost ranking.
  Preserve the broad report. Set Arcana back to zero alongside Standard and
  Spectral, leaving every other June option score unchanged, and re-screen
  that narrowed coherent shop policy once. It must satisfy the original
  paired gate; otherwise delete the alternative policy in full.
- The no-Arcana June policy also fails and is deleted in full. It retains only
  one win, averages 12.88 rounds/4.36 antes versus the floor's 13.78/4.60, and
  still over-spends through its unified value scale. The June evaluator's
  local option scores were effective only with its historical continuation
  rollouts; porting them as direct authority does not provide a competent
  heuristic. Preserve both candidate reports and the public/private audit,
  but remove the alternative policy, constants, and tests. Phase 1 remains at
  4/200 and the Phase 2 lock remains in force.
- A disjoint seeds 201--250 baseline completed 50/50 runs and won seed 243,
  but both runs that reached Verdant Leaf sold every owned Joker and then
  scored almost nothing. This exposes a candidate correctness gap rather than
  a shop-policy hypothesis. Pinned Jackdaw applies Verdant Leaf's debuff and
  implements `Blind.disable`, but its generic sell handler never disables
  Verdant Leaf after a Joker sale. Generalize the existing Luchador
  compatibility boundary: before removal, recognize either a Luchador sold
  into any live boss or any Joker sold into a live, non-disabled Verdant Leaf;
  after the sale, apply the same typed `Blind.disable` result and fail closed
  on malformed private engine state. Consumable sales, already-disabled
  bosses, and ordinary Joker sales remain inert. Add focused Verdant,
  Luchador, ordinary-boss, and non-boss regressions, then rerun only the two
  affected seeds before deciding whether a new frozen panel is warranted.
  Treat the correction as provisional until an organic authority Verdant sale
  replays exactly, and do not count candidate-only recovered wins as authority
  evidence.
- The local Verdant correction passes 36 focused candidate tests plus lint and
  diff checks. On the two affected disjoint-panel seeds, it changes exactly
  the broken boss response: seed 201 sells one weak Joker instead of all six
  and wins with 105,516 chips; seed 242 likewise keeps four Jokers and wins
  with 177,216. Both runs complete without rejection. This is strong causal
  candidate evidence for the compatibility repair, not authority evidence.
  Because clearing an earlier Verdant Leaf can change all later public shops,
  rerun the complete seeds 1--200 panel under the corrected candidate instead
  of assuming only terminal-Verdant runs can change.
- The corrected full panel completes 200/200 runs without rejection at
  74.83 decisions/s and still wins seeds 6, 44, 59, and 189. Average
  ante/round is 4.160/12.325. The only terminal progression change versus the
  older made-build artifact is seed 123 advancing from ante 7/round 21 to
  ante 8/round 23, which is the already-retained Observatory scorer
  correction rather than Verdant exposure. Thus the current-code strength
  floor remains 4/200 and Phase 2 stays locked; the Verdant fix is retained
  because it independently recovers both affected wins on the disjoint
  201--250 panel.
- Full public trace review of disjoint near-miss seed 205 finds the first
  actionable strategic error at the ante-five boss shop. The policy sells
  Misprint for The Family because `BuildPlan.favored_tags` expands Pair and
  Two Pair to the entire rank-family, even though the controller never targets
  Four of a Kind. Family remains inactive and the next Small Blind ends at
  19,945/20,000. Repair only deterministic hand-specific x-mult valuation:
  Duo, Trio, Family, Order, and Tribe count as build-usable only if the actual
  primary or secondary hand contains their trigger. Preserve the broad
  archetype relation for every other Joker and preserve all purchase,
  replacement, reserve, and tactical rules. Add exact Pair/Two Pair,
  Three/Four-of-a-Kind, Straight/Flush, and hidden-twin tests. Screen first on
  corrected disjoint seeds 201--250; keep it only if all runs complete without
  rejection, wins 201/242/243 remain, at least one candidate-only win appears,
  and paired round/ante totals are positive with more improvements than
  regressions. This is narrower than the rejected global pair-family fit and
  owned-x-mult commitment experiments: it changes only whether an offer can
  ever trigger under the already-chosen build.
- Reject that exact-hand x-mult slice after its prespecified disjoint screen.
  The 201--250 panel completes 50/50 runs and preserves the corrected wins on
  seeds 201, 242, and 243. It advances seed 203 by seven rounds/two antes and
  seed 205 by one round, with no terminal regressions, but creates no
  candidate-only win. Because the gate required at least one new win, remove
  the policy and test changes and retain
  `phase1-exact-hand-xmult-v1-red-white-seeds201-250.json` only as negative
  evidence.
- Freeze the corrected disjoint control before the next experiment. The
  Verdant-compatible strategic policy completes 50/50 seeds 201--250 with
  zero rejected decisions, wins seeds 201, 242, and 243, and averages
  ante 4.50/round 13.04. This is the paired control for subsequent disjoint
  Phase 1 screens.
- A public shop audit finds a semantic mismatch between scoring and portfolio
  classification. `_joker_supplies_usable_xmult` recognizes only runtime,
  unconditional, or hand-family multipliers, so it reports that a lineup has
  no usable x-mult even when the Phase 1 scorer already models an owned
  Acrobat, Card Sharp, Photograph, Blackboard, Bloodstone, Ancient Joker,
  Flower Pot, Seeing Double, Baron, or Loyalty Card. The resulting false
  deficit authorizes repeated upgrade rerolls. Repair only that predicate:
  require Phase 1 scoring support; treat a visible runtime x-mult counter as
  usable only above one; retain exact primary/secondary fit for the five
  hand-family multipliers; and classify every other supported catalogued
  x-mult scorer as a usable conditional source. Do not change Joker values,
  purchases, replacements, reserves, action budgets, or scoring. Add modeled,
  unsupported, hand-family, and inactive-runtime tests. Screen on corrected
  seeds 201--250; keep the policy change only if all runs complete without
  rejection, wins 201/242/243 remain, at least one candidate-only win appears,
  and total rounds and antes are positive with more improved than regressed
  seeds.
- Reject the broader modeled-x-mult classification after its disjoint screen.
  All 50 runs complete without rejection and wins 201/242/243 remain, but only
  seed 212 changes: it gains two rounds and one ante and still loses. No
  candidate-only win appears, so the required gate fails. Restore the retained
  predicate and keep
  `phase1-modeled-xmult-v1-red-white-seeds201-250.json` as negative evidence.
- Test the June planner's missing-x-mult structural emergency without
  reopening the rejected general per-shop churn. At ante four or later, a
  previous run-level replacement may stop blocking one later shop only when
  the full current lineup contains no supported modeled x-mult source and a
  visible supported x-mult offer is active for the current build. A visible
  runtime multiplier at x1 is inactive; the five hand-family multipliers still
  require existing build fit; unsupported effects remain closed. The ordinary
  replacement selector retains its material-margin, affordability, reserve,
  additive-Mult, known-card, Eternal/Negative, and action-budget gates, and a
  sale in the current shop always blocks another. Do not change values,
  first replacements, direct purchases, rerolls, or scoring. Add past-shop,
  same-shop, non-x-mult, unsupported, and inactive-runtime tests. Kill the
  slice on a targeted seed-212 replay if it does not materially advance; if it
  does, screen corrected seeds 201--250 with the same completion, retained-win,
  candidate-only-win, positive aggregate, and improvement-count gate.
- Reject this structural-emergency slice at its seed-212 kill test and delete
  it before a panel run. The audited lineup already owns Bloodstone, whose
  expected multiplier is modeled by the public scorer; only the narrower
  reroll predicate misclassified it as missing x-mult. The proposed broader
  portfolio predicate correctly blocks the extra sale, leaving the run exactly
  at ante 6/round 18. Replacing a modeled multiplier with another multiplier
  is not the claimed structural emergency. Preserve the targeted report as an
  empty-treatment diagnostic and retain the lifetime replacement cap.
- The largest named boss loss cluster exposes an independent tactical gap.
  `_boss_hidden_discard` cycles hidden cards only for The House. Pinned source
  shows that discard redraws are also informative for every other typed
  face-down mode: The Fish's flip flag is consumed by the redraw after a play,
  The Mark hides only redrawn face ranks, and The Wheel independently rerolls
  its one-in-seven flip per card. When the best visible legal play cannot clear
  and a discard remains, cycle up to five explicitly hidden slots for House,
  Fish, Mark, or Wheel. Never infer their identities, alter the public deck
  multiset, or use this path for non-face-down bosses; preserve the existing
  clear-now, boss-legality, selection-limit, and legal-action gates. Add one
  regression per mode plus no-discard/non-boss checks. Screen first on
  corrected seeds 201--250 and retain only with complete rejection-free runs,
  wins 201/242/243 preserved, at least one candidate-only win, positive total
  rounds and antes, and more improvements than regressions.
- The expanded face-down discard slice fails its prespecified win screen and
  is deleted as a standalone policy change. All 50 runs complete without
  rejection and wins 201/242/243 remain. Seeds 217 and 226 improve by a total
  of seven rounds and three antes, no seed regresses, but neither becomes a
  win. Preserve
  `phase1-hidden-boss-discard-v1-red-white-seeds201-250.json` as positive
  mechanical evidence, not promotion evidence.
- Re-plan the micro-change screen after three independent, public-only slices
  each improved disjoint progression without a regression but were discarded
  solely for lacking an immediate 50-seed win: exact trigger fit for the five
  hand-family x-mult Jokers, modeled conditional-x-mult portfolio
  classification, and informative hidden-card cycling for typed face-down
  bosses. A 50-run slice has only three control wins and is underpowered to
  require every additive correction to create another. Reintroduce those
  source-correct changes together as one frozen `phase1_correctness_bundle`,
  without adding new behavior or tuning thresholds. Validate their focused
  contracts, then screen the bundle on a new seeds 251--300 panel against an
  unchanged control generated before the bundle. Require complete
  rejection-free runs, no control-only win, at least one bundle-only win,
  positive total rounds and antes, and more improvements than regressions
  before the 200-seed strength gate. If the bundle fails, remove all three;
  their individual reports remain diagnostic evidence.
- The frozen correctness bundle passes the untouched seeds 251--300 screen.
  All 50 runs complete without rejection; control win 290 remains and seed
  284 becomes a bundle-only win. Seeds 256, 281, 284, and 286 improve, none
  regress, and aggregate progression is +18 rounds/+8 antes. Every changed
  trajectory first diverges while cycling public hidden cards under The Mark
  or The Fish, so the face-down boss correction is the dominant causal part;
  exact hand-x-mult fit and broader modeled-x-mult classification remain
  included only as the predeclared source-correct bundle. Promote the frozen
  bundle to the paired seeds 1--200 Phase 1 gate. The required floor remains
  at least 20/200 complete candidate wins before any Phase 2 implementation.
- The correctness bundle completes the 200-seed gate without rejection but
  remains at 4/200 wins (6, 44, 59, 189), so Phase 2 stays locked. Against the
  corrected control it improves 19 seeds, regresses eight, and gains 33 total
  rounds/14 antes while preserving every win. Retain it as the new Phase 1
  heuristic floor because it passed the untouched 251--300 win gate and is
  paired-positive without a lost gate win; do not describe it as meeting the
  20/200 strength floor.
- The category model currently prices every supported x-mult Joker at the
  always-on value of Cavendish before exact public score ranking. This
  overstates conditional multipliers: on the prior 200-run control,
  Photograph appears in 31 terminal lineups and wins none; Acrobat,
  Blackboard, Seeing Double, and Bloodstone are likewise common despite
  depending on hand state or chance. Introduce one category-level conditional
  discount, not a per-key tier list. Runtime x-mult above one and the two
  unconditional sources retain realized/full value; an exactly build-active
  Duo/Trio/Family/Order/Tribe retains full value; every other supported
  static x-mult scorer receives the retrigger-tier base value. Preserve the
  exact public score tiebreaker, editions, build tags, support gate, purchases,
  reserves, and replacement margin. Add unconditional, runtime, exact-family,
  conditional, and unsupported tests. Screen against the frozen correctness
  bundle on seeds 251--300; require 50/50 complete, wins 284/290 retained, no
  control-only win, at least one candidate-only win, positive round/ante
  totals, and more improvements than regressions before a 200-run gate.
- The category-level conditional-x-mult discount fails that screen. The frozen
  report `phase1-conditional-xmult-value-v1-red-white-seeds251-300.json`
  completed 50/50 and retained wins 284/290, but produced no candidate-only
  win, changed seven seeds with five improved and two regressed, gained three
  rounds, and lost one ante. Preserve the report as negative evidence and
  revert the valuation and its experiment-only tests. The correctness bundle
  remains the active Phase 1 floor; Phase 2 remains locked at 4/200.
- A read-only shop audit on untouched seeds 251--300 finds 14 settled decisions
  where the full-lineup upgrade branch rerolls before considering an already
  affordable committed Planet. The Planet is a guaranteed public build level;
  the reroll is an uncertain offer search, and the existing Planet block would
  buy the card if it ran first. Test only this priority correction: keep direct
  Joker and voucher priority unchanged, move the existing primary/secondary
  Planet purchase block immediately ahead of `needs_upgrade` rerolls, and
  preserve its capacity, affordability, reserve, and value rules verbatim.
  Add primary, secondary, unaffordable, full-capacity, noncommitted, and voucher
  priority tests. Screen against the frozen correctness-bundle control on
  seeds 301--350 (50/50 complete, one win at seed 347, averages ante 3.86 and
  round 11.64). Retain only if there is no control-only win, at least one
  candidate-only win, positive total round and ante deltas, and more improved
  than regressed seeds; otherwise preserve the report and revert the change.
- The Planet-before-reroll variant fails that gate and is reverted. Its report
  `phase1-planet-before-reroll-v1-red-white-seeds301-350.json` completed 50/50
  and retained control win 347, but added no win, improved only seed 307,
  regressed seeds 309 and 341, and lost four rounds plus one ante in aggregate.
  Guaranteed immediate level value does not dominate the existing upgrade
  reroll's continuation value. Preserve the report as negative evidence and
  retain the original reroll-before-Planet order.
- The typed boss catalog declares The Serpent's three-card post-action draw,
  but the generic discard selector may still discard five cards and shrink its
  own hand by two. A read-only in-memory shadow on the retained 1--200 panel
  found 17 Serpent decisions across three seeds and oversized discards on two:
  capping only those discards to three advanced seed 10 by two rounds/one ante,
  raised seed 134 from 17,505 to 20,570 chips, and produced zero terminal
  regressions; seeds 201--250 were neutral with no exposure. Correct this typed
  resource invariant by passing the active boss's `draw_count_override` into
  `_coverage_discard` and limiting its already-prioritized candidate list only
  when that override applies. Preserve ordinary five-card discards, target
  keep-sets, Green/Ramen suppression, hidden-card behavior, and play scoring.
  Add active-Serpent, ordinary-blind, fewer-than-three, and suppression tests.
  Screen on the frozen 301--350 control; retain if the control win is not lost
  and paired progression has no regression (an exposure-free panel is neutral),
  then rerun the full 1--200 evidence panel before naming a new floor.
- The Serpent cap's fresh report
  `phase1-serpent-draw-cap-v1-red-white-seeds301-350.json` is exactly neutral
  against the frozen control: 50/50 complete, the same seed-347 win, and the
  same 3.86/11.64 ante/round averages. This is the allowed exposure-free result.
  Retain the source-correct cap and freeze a new 1--200 report to reproduce the
  shadowed progression gain; it does not by itself raise the 4/200 strength
  result or unlock Phase 2.
- The first frozen 1--200 attempt was exactly neutral because the implementation
  incorrectly waited for a pre-action hands/discards counter. Jackdaw applies
  the Serpent limit after incrementing the current action's counter, so the
  first play or discard is already a three-card draw. Treat the neutral report
  as an implementation diagnostic, remove the pre-action gate, and rerun the
  same panel under a new source digest.
- Reconciliation with the shadow audit invalidates its claimed progression
  gain: the shadow truncated the final slot-sorted action, while the real fix
  caps the discard-priority candidate list before slot sorting. That accidental
  difference chose different cards. Direct corrected replays reduce seed 10's
  discarded-card total by one but preserve its 39,025/40,000 terminal result;
  seed 134 is unchanged. Keep the pure cap as a source-correct resource
  invariant, but record it as terminal-neutral and make no strength claim.
- The Mouth currently locks the first played family, but the policy may discard
  or open with a one-off higher hand even when its committed primary family is
  already visible. A read-only probe over the seven retained terminal Mouth
  seeds changes only the unlocked opening: if the primary build family has a
  legal play, choose its highest exact public score immediately; preserve an
  already-clearing best play and fall back unchanged when the family is absent.
  This advanced seed 165 by two rounds/one ante and raised seed 42 from 14,826
  to 29,266/40,000 with no ante/round regression. Do not add the separately
  tested High-Card fallback, which regressed three seeds. Add tests for primary
  commitment, immediate clear, existing Mouth lock, and absent-family fallback.
  Screen the isolated rule against the frozen Serpent-cap control on untouched
  seeds 351--400 (50/50 complete, zero wins, averages 3.96/11.58). Require at
  least one candidate win, positive round and ante totals, and more improved
  than regressed seeds before a 1--200 gate.
- The Mouth commitment variant fails the untouched strength screen and is
  reverted. `phase1-mouth-commit-v1-red-white-seeds351-400.json` completes
  50/50 with zero wins and identical 3.96/11.58 average ante/round; it changes
  two trajectories, with only a 50-chip terminal gain on seed 352. Preserve the
  report as negative evidence. Boss-specific tactical polish is not the missing
  order-of-magnitude Phase 1 strength lever.
- Ante-one trace review finds the bootstrap controller discarding a visible
  above-pace hand solely because it is not the primary build family. Seed 5,
  for example, discards a 96-chip Two Pair with four hands against a 300-chip
  blind, then exhausts all hands at 248. A public-only shadow on untouched
  seeds 351--400 tests a deliberately pre-build rule: while ante is one, no
  Joker is owned, and no boss is active, play the already-computed exact best
  hand whenever it meets the remaining target divided by hands left. It changes
  49 decisions and gains 28 rounds plus 11 antes, including seed 353 reaching
  ante eight, with no candidate win on the zero-win control. Implement only
  that bootstrap predicate; preserve all boss handling, later build pacing,
  Joker interactions, scorer semantics, and discard selection. Add above/below
  pace, owned-Joker, later-ante, and boss exclusions. Freeze the official
  351--400 report and require complete rejection-free runs, positive total
  rounds and antes, and more improved than regressed seeds. Then require a win
  gain on the full 1--200 panel before naming it a strength improvement.
- The official bootstrap-pacing screen rejects the rule. The report
  `phase1-ante1-prebuild-pace-v1-red-white-seeds351-400.json` completed all 50
  runs with zero rejected decisions and changed 19 terminal trajectories; 11
  improved and eight regressed, but it lost four rounds in aggregate, gained
  only one ante, and added no win. The shadow's large progression gain came
  from a wrapper interaction that did not reproduce in the integrated policy.
  Preserve the report, delete the predicate and experiment-only tests, and do
  not tune its cutoff on this panel.
- The next scorer correction closes an explicit known-initial-state mismatch.
  Green Joker and Ride the Bus are intentionally supported immediately after
  acquisition even though their serialized `current_mult` field is absent
  until the first mutation. Pinned Jackdaw initializes both counters from
  public zero before scoring that first hand: Green gains +1 on every play;
  Bus gains +1 only when no visible scoring face card is present. On seeds
  351--370 this omission causes seven exact score mismatches across 23 exposed
  selecting-hand states, including 264 versus 330 and 90 versus 108. Teach
  `_joker_main_effect` only those two source-defined zero initial values and
  preserve fail-closed behavior for every other absent runtime. Add Green,
  face-free Bus, face-reset Bus, and unrelated-missing-runtime tests. Screen
  against the frozen correctness-bundle control; require complete
  rejection-free runs, no lost win, positive round and ante totals, and more
  improvements than regressions before a full 200-seed strength gate.
- The fresh-scaler scorer report
  `phase1-fresh-scaler-score-v1-red-white-seeds351-400.json` completes 50/50
  runs with zero rejected decisions and no regression. It raises seed 388's
  terminal chips from 4,725 to 4,989 and advances seed 397 by two rounds, for
  +2 rounds and zero antes overall, but adds no win. This fails the declared
  strength gate and does not warrant a 200-seed run. Retain the two exact
  source-defined initial states as scorer correctness; make no strength claim
  and keep Phase 2 locked.
- The next broad Phase 1 experiment fixes an over-narrow definition of build
  commitment. `_build_pace_play` currently accepts only the exact primary hand
  label, so a Pair build may ignore a higher-scoring Two Pair, Trips, Full
  House, or Quads even though those hands contain a Pair and activate the same
  typed Pair-family Jokers. Treat a legal play as committed when the existing
  source-audited `_hand_matches` predicate proves that its classified hand
  contains the primary family. Preserve exact public scoring, the per-hand
  pace threshold, boss eligibility, and the existing exact-label behavior for
  families without containment semantics. Do not change build inference,
  discard selection, shop values, Planet targeting, or hand statistics.
  Add Pair-to-Two-Pair, Two-Pair-to-Full-House, incompatible-family, and boss
  eligibility regressions. Seeds 401--450 are frozen as the development
  control at 50/50 complete, zero wins, average ante/round 4.28/12.54. The
  official candidate must complete without rejections, add at least one paired
  win, gain both total rounds and antes, and improve more seeds than it
  regresses. If it passes, the 1--200 evidence panel must preserve all four
  retained wins, add at least one paired win, and gain total rounds and antes
  before this becomes the new floor. The Phase 2 lock remains 20/200 regardless
  of incremental retention.
- The official containment report
  `phase1-build-containment-v1-red-white-seeds401-450.json` reproduces the
  shadow result: 50/50 complete, zero rejected decisions, one candidate-only
  win at seed 446, +37 rounds, +7 antes, and 14 improved versus 10 regressed
  seeds. Average ante/round rises from 4.28/12.54 to 4.42/13.28. The broad
  development gate passes; retain the implementation while running the
  prespecified 1--200 evidence gate. This is still candidate screening, not an
  authority win or permission to enter Phase 2.
- The first 1--200 containment gate aborted before report creation on seed 79,
  decision 194. After clearing Cerulean Bell, Jackdaw carried three
  `forced_selection` ability flags into the next ante; one stale card was dealt
  into the Small Blind hand, where the public adapter correctly rejected a
  forced marker without an active Cerulean Bell. Repair the candidate boundary,
  not the adapter: at the existing cash-out compatibility step, clear the
  round-local marker from every distinct playing card only when the completed
  blind is Cerulean Bell. Validate the private candidate shape and preserve the
  fail-closed public invariant for every selecting-hand observation. Add a
  focused cleanup test and rerun seed 79 through the formerly failing next-blind
  transition before restarting the immutable 1--200 gate. The aborted process
  produced no report and provides no strength evidence.
- The repaired broad-containment report
  `phase1-build-containment-v1-red-white-seeds1-200.json` completes all 200
  runs and reaches six wins, +92 rounds, and +33 antes, but it loses retained
  win 189 while adding wins 62, 79, and 163. It therefore fails the
  predeclared no-control-only-win gate and is not the new floor. The first
  divergence on seed 189 explains the regression without a seed-specific
  exception: a four-card Two Pair already met pace at 576, but the broad rule
  consumed a fifth held card for a 640-point Full House and destroyed the next
  hand's setup. Refine the rule to preserve the best exact primary hand whenever
  any exact-primary play meets pace; consult stronger containing families only
  as a fallback when no exact primary reaches pace. Keep every other boundary
  unchanged and add a regression for preserving an adequate exact primary.
  A read-only public-only shadow of this exact-first rule on seeds 1--200 keeps
  all four retained wins, adds 62, 79, and 163, gains 73 rounds and 26 antes,
  and completes every run. Replace the failed broad rule with this refinement,
  re-run focused tests and the official 401--450 development gate, then freeze
  a new official 1--200 report under its own policy/source identity. Shadow
  results are diagnostic only.
- The official exact-first development report
  `phase1-exact-first-containment-v2-red-white-seeds401-450.json` completes
  50/50 without rejections, retains the new seed-446 win, gains 20 rounds and
  three antes, and improves 13 seeds versus 11 regressions. Average ante/round
  is 4.34/12.94 versus 4.28/12.54. The refined development gate passes; run
  the official 1--200 evidence panel before naming a new floor.
- The official exact-first evidence report
  `phase1-exact-first-containment-v2-red-white-seeds1-200.json` passes its
  paired gate: 200/200 complete, zero rejections, seven wins, and no lost
  retained win. It preserves 6, 44, 59, and 189; adds 62, 79, and 163; gains
  73 rounds and 26 antes; and improves 51 seeds versus 42 regressions. Average
  ante/round rises from 4.23/12.49 to 4.36/12.855. Retain exact-first
  containment as the new Phase 1 floor. Seven wins still fail the required
  20/200 strength floor, so Phase 2 remains locked.
- The next scorer repair derives Loyalty Card's legitimately public countdown
  from action history. The adapter's typed runtime currently stays at five,
  while pinned Jackdaw triggers the current play after 5, 11, 17, ... accepted
  `PlayCards` actions since the card was created. In the prior retained panel,
  12 runs bought Loyalty Card and nine encountered 33 trigger hands, so the
  mismatch is material scorer exposure. Enrich only an internal frozen
  observation copy: require exactly one current Loyalty Card and a contiguous
  history ending at the current observation; find the most recent unambiguous
  zero-to-one ownership transition; reject duplicate/reacquisition ambiguity;
  count later accepted plays; and overwrite only `loyalty_remaining`. Missing
  or ambiguous provenance clears the counter and fails closed. Do not add a
  schema field, trust the stale engine value, or expose candidate state. Apply
  the same enrichment to the historical pre-play observation used by the exact
  shop scorer. Add countdown, non-play, ambiguity, reacquisition, fail-closed,
  scoring-trigger, and shop-reproduction tests. Retain the correction on source
  correctness; require a new paired win before calling it a strength gain.
- The Loyalty repair and its conservative provenance rules pass the focused
  policy/candidate suite. A public-only 1--200 shadow is exactly terminal-neutral
  against the seven-win floor: the same seven wins, 872 total antes, and 2,571
  total rounds, with every run complete. Retain the history-derived counter as
  scorer correctness, but do not spend an official strength report or claim a
  gain for it.
- Two public-only tactical shadows reject broader fallback play. Consulting the
  build plan's secondary lane when no primary play meets pace finishes at
  5/200 and loses retained wins 79 and 189. Playing any off-build hand that
  meets the same pace finishes at 4/200 and loses three retained wins. Do not
  weaken exact-primary commitment with either rule.
- Replace one-off shop thresholds with a bounded category calibration screen.
  Freeze seeds 451--500 as development data. Cross six prespecified Joker role
  vectors (current, x-mult-heavy, growth-heavy, additive-heavy, balanced, and
  reduced-conditional-x-mult) with late-game public economy reserves of $25,
  $20, and $15. Preserve every action ordering rule, support gate, build-fit
  predicate, purchase threshold, replacement margin, pack rule, and early-ante
  reserve. This is a Phase 1 parameter screen over public category metadata,
  not rollout search; it may observe only terminal candidate outcomes from the
  development seeds. Rank configurations lexicographically by wins, total
  rounds, then total antes. Advance only a configuration with more wins than
  the current policy, positive round and ante deltas, and no incomplete or
  rejected run. Freeze the chosen constants in source and validate them on
  fresh seeds 501--700. The fresh gate must reach at least 20/200 complete wins
  before Phase 2 can start; otherwise retain the seven-win exact-first floor
  and reject the tuned constants as insufficient or overfit.
- Reject the category/reserve calibration screen. All 18 public-only
  configurations complete seeds 451--500 without errors and all win 0/50. The
  current profile at $25 totals 610 rounds/206 antes; the best survival result,
  current values with a $15 late reserve, reaches 626/211 but adds no win and
  therefore fails the prespecified gate. Do not freeze any tuned constants or
  spend a fresh 200-seed panel on them.
- Test one structural shop alternative on the same zero-win development panel:
  define `building` as fewer than three modeled scoring Jokers instead of fewer
  than two. Preserve the current role values, exact score rank, reserves,
  voucher readiness, replacement logic, pack classes, reroll budget, and all
  tactical decisions. This lets a two-scorer lineup continue using the existing
  build-strength acquisition, Buffoon, and reroll lanes without introducing a
  new option value. It advances only if it adds a development win, gains total
  rounds and antes, improves more seeds than it regresses, and completes every
  run; otherwise restore the two-scorer boundary.
- Reject the three-scorer boundary: it completes all 50 development runs and
  gains 19 rounds/six antes, but still wins 0/50 and fails the mandatory win
  gate. A separate public audit of all 695 Celestial purchases on the 1--200
  floor finds zero purchases with full consumable slots, so no capacity-unblock
  rule has treatment exposure.
- Test strict target-family discard retention on seeds 451--500. When the
  primary hand is not made, preserve `_keep_slots_for_hand`'s best primary
  fragment and remove only the generic fallback that replaces it with a longer
  unrelated pair, suit, or straight fragment. Preserve made-hand handling,
  exact-primary play pacing, hidden cards, last-hand survival fishing,
  Green/Ramen suppression, Serpent caps, discard ordering, and all shop logic.
  Advance only if the isolated public-only variant adds a development win,
  gains total rounds and antes, improves more seeds than it regresses, and
  completes every run; otherwise keep the flexible fragment fallback.
- Reject strict target-family retention. It completes all 50 development runs
  without rejected decisions and improves survival from 610 to 657 total
  rounds and 206 to 219 total antes, but still wins 0/50. Restore the flexible
  fragment fallback: the survival signal is real, but the prespecified gate
  requires an actual conversion before changing the floor.
- Test the prespecified interaction suggested by the two independent survival
  screens, still on seeds 451--500: strict target-family retention plus a $15
  late reserve from ante 4 onward. Keep the existing Seed Money/Money Tree cap
  and Bull/Bootstraps reserve protection; change no valuations, thresholds, or
  action ordering. This asks whether the extra primary-hand consistency can
  convert only when the shop may spend another $10, rather than treating either
  individually winless rule as strength. Retain the bundle only if it completes
  every run, adds at least one win, gains total rounds and antes over the current
  610/206 development floor, and improves more seeds than it regresses. If it
  passes, ablate both components before any 200-seed evidence run.
- Reject the interaction bundle. It completes 50/50 without rejected
  decisions and reaches 664 total rounds/218 antes, but remains at 0/50 wins.
  Restore both the flexible fragment fallback and the $25 late reserve. The
  accumulated depth gains without conversions point away from further tuning
  of these two thresholds and toward missed score or ordering inside late
  blinds.
- Test score-improving Joker reordering before build-pacing plays on seeds
  451--500. Today an exact-primary hand that meets the pace threshold returns
  before `_score_improving_joker_reorder`, even when an adjacent public swap
  raises that same hand's modeled score. Move only the existing deterministic
  adjacent-swap check ahead of `_build_pace_play` for non-clearing states; keep
  clear hands, selected cards, the scorer, discard logic, shop behavior, and
  boss eligibility unchanged. Repeated free reorder actions may converge over
  successive observations. Advance only if every run completes, at least one
  development win is added, total rounds and antes exceed 610/206, and more
  seeds improve than regress. Add a regression showing that a paced primary
  hand no longer suppresses a beneficial swap before retaining it.
- Reject reorder-before-pace. The candidate completes 50/50 with no rejected
  decisions but remains at 0/50, totals only 613 rounds/207 antes, and exposes
  just two extra Joker reorder actions. Restore the prior ordering. Audit
  modeled play scores against observed public chip deltas before changing
  another tactical priority.
- The play-score audit reproduces 1,239 of 1,342 observed public scoring
  transitions exactly on seeds 451--500. Most residuals are expected from
  Misprint, Bloodstone, fractional counters before final flooring, hidden
  cards, or The Hook's random held-card removal. One large deterministic error
  remains: Flower Pot under The Plant is modeled at 1,610 while Jackdaw scores
  4,830 because vanilla counts a debuffed non-Wild scoring card's printed suit
  for Flower Pot. Correct Flower Pot's public suit test, including one-suit-per
  live Wild fill, and add focused debuffed/Wild regressions. Retain this as a
  scorer correctness repair even if terminal outcomes are neutral; run the
  451--500 panel once to establish the corrected development floor before the
  next strength screen.
- After the Flower Pot correction, test a late-boss same-width containment
  escape hatch. In `_build_pace_play`, retain exact-first behavior everywhere
  except ante 4+ bosses: when both exact-primary and containing-family plays
  meet pace, allow the containing play only if it uses no more cards and scores
  strictly higher than the best exact play. This excludes the seed-189 failure
  (a five-card Full House displaced a four-card exact Pair) while addressing
  two observed terminal conversions: seed 464 left 4,932 modeled chips unused
  against a 4,033 deficit, and seed 499 left 227 unused before dying 92 short.
  Add late-boss, larger-hand, early-ante, non-boss, non-improving, and
  boss-ineligible tests. Screen on 451--500 and advance only with at least one
  win, complete/rejection-free execution, positive round and ante deltas, and
  more improved than regressed seeds.
- The corrected Flower Pot development report
  `phase1-flower-pot-correctness-v1-red-white-seeds451-500.json` is 50/50
  complete and rejection-free. It remains at 0/50 wins but improves the prior
  control by three rounds and one ante, to 613/207. Retain the typed scorer
  correction and use this report as the exact development control.
- Reject late-boss same-width containment alone. It is narrowly positive and
  behaves as designed: only seeds 464 and 499 change, both improve with no
  regression, and totals rise to 617 rounds/209 antes. It still wins 0/50,
  however, so it fails the mandatory gate and is not independently retained.
- Test the only evidence-backed interaction: strict target-family discard
  retention plus late-boss same-width containment, with the corrected Flower
  Pot scorer and the original $25 reserve. The discard screen previously added
  44 rounds over the old control; seed 499 then died only 92 chips short on the
  exact boss that same-width containment clears. Change no other behavior.
  Both components have already been ablated independently on this panel.
  Retain the bundle only if it produces at least one complete win, finishes
  50/50 without rejections, beats 613/207 total rounds/antes, and improves more
  seeds than it regresses.
- Reject the discard/containment bundle. It completes 50/50 without rejected
  decisions, improves 20 seeds versus nine regressions, and reaches 662 total
  rounds/222 antes, but it still wins 0/50. Restore both tactical components;
  retain only the Flower Pot scorer correction. Do not combine further
  hand-shape thresholds on this panel. Continue Phase 1 at the missing public
  Joker-runtime and scoring-support boundary, where actual build strength is
  still invisible to purchase and play decisions.
- Test Arcana pack acquisition on the corrected 451--500 control. The policy
  already enumerates legal targeted and untargeted Tarot picks and consumes
  them immediately from packs, but `_strategic_shop_action` currently refuses
  every Arcana pack before seeing its contents. Admit Arcana alongside
  Celestial packs at the same `min(12, interest_floor)` reserve; preserve pack
  choice values, target legality, shop action limits, Joker/Planet priority,
  and all other pack classes. This is the missing purchase edge for an already
  public typed policy, not search. Retain only if the panel completes without
  rejections, adds a win, beats 613 rounds/207 antes, and improves more seeds
  than it regresses.
- Reject Arcana pack acquisition. It has substantial treatment exposure (141
  Arcana purchases and 268 Tarot picks), completes 50/50 without rejections,
  and improves 14 seeds versus eight regressions, but remains at 0/50 and adds
  only one total round (614) despite two extra total antes (209). Restore the
  Celestial/Buffoon-only purchase rule.
- Repair the modeled-Joker purchase support gate for Blueprint, Brainstorm,
  and Hiker, then screen seeds 451--500. Their scoring behavior is already
  explicitly implemented from public ordered Jokers/cards, including copy
  fail-closed whitelists and Hiker's permanent-bonus progression, but none is
  in `_STATIC_PHASE1_JOKERS`; `_phase1_joker_supported` therefore values every
  offer at zero. Admit only these already-modeled keys. Preserve their current
  category values, copy whitelist, shop threshold/order, and all other policy
  behavior. Add support/value regressions. Retain as a correctness repair only
  if execution stays complete and rejection-free; call it a strength gain and
  replace the development floor only if it adds a win, beats 613/207, and
  improves more seeds than it regresses.
- The modeled-support screen completes 50/50 without rejections, acquires the
  newly admitted Jokers seven times, improves three seeds with zero
  regressions, and raises totals to 624 rounds/211 antes. It still wins 0/50.
  Retain the three keys as a correctness repair because their scorer was
  already authoritative and the previous zero purchase value was internally
  inconsistent; make no strength claim and use 624/211 as the corrected
  development control.
- Before freezing that support bundle, ablate Hiker. The panel contains four
  Blueprint acquisitions, three Hiker acquisitions, and no Brainstorm
  acquisition; an older floor found Hiker purchase support regressive because
  its long-term mutation value was not captured by an immediate offer score.
  Keep Blueprint/Brainstorm admitted because their ordered copy scorer gives a
  direct offer value, but remove Hiker unless the isolated 451--500 rerun
  preserves or improves the bundle's terminal results. This is attribution of
  the predeclared bundle, not a new threshold screen.
- The Hiker ablation confirms the full modeled-support bundle is better on the
  current floor. Blueprint/Brainstorm alone improve seeds 470 and 472 with no
  regression and reach 622 rounds/210 antes; adding Hiker further advances
  seed 491 and reaches 624/211, again without a regression. Retain all three
  already-modeled keys. The earlier Hiker-only negative result does not
  reproduce after the intervening scorer/build corrections, but the bundle
  still adds no win and remains a correctness-only change.
- A unique public-shop/pack audit on seeds 451--500 finds the remaining
  unsupported scoring offers: Fortune Teller 23, Flash Card 10, Idol nine,
  Driver's License six, Ceremonial Dagger five, and Baseball Card four. Do not
  revive Fortune Teller's previously regressive acquisition, admit destructive
  Ceremonial Dagger without ordering policy, or guess Idol/Driver/Baseball
  state. Test Flash Card alone: its source-defined initial Mult is zero, which
  Jackdaw omits until the first public reroll, while the existing typed
  `current_mult` path scores all later values. Admit the fresh zero state in
  `_STATIC_PHASE1_JOKERS` without fabricating a score. Add value and zero-score
  regressions, then screen 451--500 against 624/211. Retain only with complete
  rejection-free execution and no terminal regression; require a new win and
  positive round/ante totals for a strength claim.
- The Flash Card screen completes 50/50 without rejections, acquires three
  copies, improves seeds 485, 494, and 497 with no regressions, and raises the
  corrected development totals from 624/211 to 635 rounds/215 antes. It still
  wins 0/50. Retain the known-zero support as a correctness change and use
  635/215 as the next development control; make no strength claim.
- Test copy-Joker reorder priority on that control. A purchased Blueprint is
  appended rightmost and copies nothing, while `_build_pace_play` currently
  returns before the existing free score-improving adjacent swap. For
  non-clearing hands containing Blueprint or Brainstorm only, consult the
  existing exact reorder scorer before build pacing; leave every non-copy
  lineup and already-clearing play unchanged. This is narrower than the
  rejected global reorder-before-pace rule and has new treatment exposure from
  the modeled-support repair. Add copy/non-copy, clearing, and beneficial-swap
  tests. Retain only if the 451--500 panel completes without rejections, adds a
  win, beats 635/215, and improves more seeds than it regresses.
- Reject copy-Joker reorder priority. It adds five total reorder actions but
  remains at 0/50, regresses seed 472 from ante six to ante four, improves no
  seed, and falls to 630 rounds/213 antes. Restore the existing reorder
  position after build pacing.
- Freeze the retained source-correct Phase 1 bundle—Flower Pot suit semantics,
  Blueprint/Brainstorm/Hiker acquisition support, and fresh Flash Card—on the
  original paired seeds 1--200 panel. Require 200/200 complete without
  rejections and preservation of all seven exact-first wins. Promote it as a
  new strength floor only if it adds at least one win and gains aggregate
  rounds and antes; otherwise keep only corrections that remain non-regressive
  on their isolated development evidence. The absolute Phase 2 lock remains
  20/200 complete wins.
- The full correctness bundle report
  `phase1-modeled-support-correctness-bundle-v2-red-white-seeds1-200.json`
  completes 200/200 without rejected decisions and preserves exactly the seven
  prior wins (6, 44, 59, 62, 79, 163, 189). It acquires Blueprint three times,
  Brainstorm nine, Hiker 11, and Flash Card six; improves nine terminal seeds,
  regresses seven, and gains seven rounds/two antes (2,578/874). It adds no
  win, so it is a source-correct active floor but not a strength promotion.
  Phase 2 remains locked at 7/200 versus the required 20/200.
- Freeze seeds 501--550 as a fresh development control for contextual boss
  inventory. Then test Luchador acquisition only while the visible upcoming
  boss has the typed `high_target` rule (Wall or Violet Vessel), at ante four
  or later. If a slot is open, buy an affordable visible Luchador while keeping
  $12. If full, permit one coherent weakest-slot sale only when the sellable
  non-Negative, non-Eternal Joker is worth at most 65, selling it would not
  remove the sole additive-Mult source, the visible Luchador remains affordable
  with $12, and the shop action budget can complete the purchase. The existing
  `_boss_disable_sale` remains the only in-blind authority and immediately
  sells Luchador to disable the boss. Do not assign Luchador a global category
  value or buy it for ordinary bosses. Add open/full, reserve, weak-slot,
  additive protection, ordinary/unknown boss, and in-blind sale regressions.
  Advance only if both 50-run panels complete without rejection and the
  candidate adds a fresh-panel win with positive total round/ante deltas and
  more improvements than regressions. Seed 40 is causal evidence, not a gate
  seed.
- The fresh control completes 50/50 without rejections at 0 wins, 706 rounds,
  and 236 antes. The Luchador candidate has zero exposure and is terminally
  identical. A diagnostic seed-40 replay does buy Luchador but regresses from
  the ante-eight boss to the preceding Big Blind: selling Even Steven removes
  enough score that the inventory never reaches Violet Vessel. Delete the
  acquisition rule. Boss relief cannot be priced without the opportunity cost
  of the scoring slot it displaces.
- Test a non-destructive Mr. Bones fallback on seeds 501--550. Only at ante six
  or later, only with an open Joker slot, and only after all existing supported
  Joker, voucher, reroll, Planet, and pack choices decline, buy a visible Mr.
  Bones while preserving $12. Assign it no scoring/category value and never
  sell a scorer to make room; Jackdaw's normal public game transition owns its
  25%-of-target rescue and self-destruction. This isolates late survival
  inventory from the Luchador opportunity-cost failure. Add late/open-slot,
  early/full/reserve, and higher-priority-offer tests. Retain only if the fresh
  panel completes without rejection, adds a win, beats 706/236, and improves
  more seeds than it regresses.
- Reject the Mr. Bones fallback. It has zero treatment exposure on seeds
  501--550 and is terminally identical to the 706/236 control, so it fails the
  required win gate and is removed.
- Correct Verdant Leaf's forced sale selection using the existing exact public
  scorer. Once any visible Joker is sold, the boss re-enables the fully public
  hand. For each legal non-Eternal/non-Negative sale, construct only that
  post-disable public hand and lineup, score its best legal play, and choose the
  sale with the highest immediate score; break ties by lower owned contextual
  value, higher sell value, then stable slot. Keep Luchador's typed priority and
  the existing fallback if no scoreable public play exists. Seed 506 proves
  causal exposure on the fresh panel: the category rule sells Clever Joker and
  models 14,400 on the first hand, while selling non-triggering Acrobat keeps
  Clever and models 24,000. Add exact-choice, tie/fallback, Eternal/Negative,
  and Luchador-priority tests. Screen on 501--550; retain only if all runs
  complete without rejection, seed 506 becomes a win, aggregate rounds/antes
  exceed 706/236, and more seeds improve than regress.
- The immediate-score version fails the causal replay: it sells Acrobat as
  intended by the one-hand metric but seed 506 still loses 88,416/100,000,
  worse than the 91,416 control. Re-plan the metric before the panel. For each
  candidate sale, reuse the same re-enabled public hand only as a neutral score
  probe at every remaining `hands_left` value and sum the best modeled score.
  This captures public last-hand effects such as Acrobat and Dusk without
  drawing cards or mutating future state. On seed 506 it ranks selling Ride the
  Bus at 161,700 projected capacity, ahead of Acrobat 120,000 and Clever
  100,800. Keep the same tie-breaks and gate; do not retain the failed
  immediate-score version.
- Retain the multi-hand Verdant capacity rule. The frozen fresh-panel report
  `phase1-verdant-sale-capacity-v1-red-white-seeds501-550.json` completes all
  50 runs without rejection, changes only the causal seed 506, and converts it
  from a 91,416/100,000 loss into a win at ante nine. The candidate records
  1/50 wins, 706 total rounds, and 237 total antes versus 0/50, 706, and 236;
  there are no paired regressions. The round total necessarily ties because
  the loss-to-win conversion resolves on the same round. Accept the paired
  win-rate gain and positive ante delta under Phase 0's primary promotion
  metric instead of requiring an impossible extra round from this terminal
  conversion. Add a representative regression where preserving Acrobat's
  last-hand multiplier makes the capacity choice differ from the greedy
  immediate-score sale.
- Correct the Eye-specific play/discard conflict next. The typed
  `repeat_hand_restriction` rule and `_boss_eligible_plays` already remove hand
  families used this round, but the build-pacing layer then rejects an
  otherwise eligible off-build hand and falls through to a discard. Only for a
  current boss with `repeat_hand_restriction`, play the best eligible public
  hand when its exact modeled score meets the remaining-target-per-hand pace,
  even if it is outside the committed build family. Keep the ordinary build
  rule unchanged: the prior global off-build pace probe was regressive. Add a
  focused Eye regression, replay causal seed 541, then screen the frozen
  Verdant-plus-Eye candidate on seeds 501--550. Retain only if all runs
  complete, seed 506 remains a win, seed 541 does not regress, total wins
  increase, and there are no control-only wins.
- Retain the Eye-specific pace escape. The causal seed-541 replay completes and
  turns the ante-six Eye loss into an ante-nine win. The frozen combined report
  `phase1-verdant-eye-v1-red-white-seeds501-550.json` completes 50/50 without
  rejection at 2 wins, 712 rounds, and 240 antes versus the frozen control's
  0 wins, 706 rounds, and 236 antes. Only seeds 506 and 541 improve; no seed
  regresses and there are no control-only wins. The pinned-Jackdaw focused suite
  passes 276 tests and Ruff plus `git diff --check` pass. Promote this combined
  policy as the Phase 1 development floor, but keep Phase 2 locked: the fresh
  200-seed gate still requires at least 20 complete wins.
- The established seeds 1--200 development sweep confirms that the typed boss
  repairs are sparse, not the broad strength lever. The combined policy remains
  at the same seven wins and 874 total antes, loses one total round because
  seed 180 exits one round earlier, and preserves all seven winning seeds.
  Retain it on the stronger fresh paired evidence, but do not count it as a
  development-panel win-rate gain.
- Fix the replacement lifecycle before changing reserve levels. The current
  `already_replaced` guard scans the entire run history, so the first Joker
  sale permanently disables full-slot upgrades in every later shop. It should
  enforce the documented one-replacement budget only within the current shop,
  using the same round-evaluation-to-shop boundary as the shop action counter.
  Seed 505 exposes the bug organically: after a prior sale, the ante-six shop
  has $38, a full build, and visible Brainstorm; the category rule values
  Brainstorm at 85 and Even Steven at 55, and the sale-plus-buy is affordable,
  but the stale lifetime flag buys a voucher and Celestial pack instead. Add a
  regression proving a sale before the current shop does not block replacement
  while a sale within the current shop still does. Replay seed 505, then screen
  seeds 501--550 against the frozen Verdant-plus-Eye floor. Retain only if both
  existing wins survive, all runs complete, total wins or paired progression
  improves, and there are no control-only wins.
- Reject the unrestricted per-shop lifecycle correction. It completes 50/50
  and raises progression from 712 rounds/240 antes to 723/243, improving seeds
  505, 515, 535, and 542, but it loses the established seed-541 win and
  regresses seeds 509 and 525. The damaging action is identifiable: after the
  original lifetime-budget replacement sells Brainstorm for Card Sharp in the
  ante-seven shop, the unrestricted rule performs another replacement two
  rounds later, selling Banner for Photograph, and the run dies before the
  final ante. Preserve one replacement per shop, but after the first run-wide
  replacement admit only another visible Blueprint or Brainstorm offer. This
  retains the seed-505 causal upgrade while excluding the seed-541 Photograph
  churn. Add tests for a prior-shop copy offer, a prior-shop ordinary offer,
  and the existing same-shop stop; rerun causal seeds 505 and 541 before the
  50-seed screen. Retain only with both wins preserved and no paired
  regressions.
- Retain the copy-only repeat-replacement rule. Causal seed 505 buys the
  visible Brainstorm after its earlier ordinary upgrade and advances from
  round 21/ante seven to round 24/ante eight; causal seed 541 keeps its win
  because the later Photograph replacement remains blocked. The frozen report
  `phase1-repeat-copy-replacement-v1-red-white-seeds501-550.json` completes
  50/50 at the same two wins, raises totals from 712/240 rounds/antes to
  715/241, improves only seed 505, and has no regressions. The pinned focused
  suite passes 278 tests with Ruff and `git diff --check`. Promote this as the
  development floor, but do not relax the 20/200 Phase 1 lock.
- Preserve the exact shop score context across actions within one public shop.
  `_shop_score_context` currently accepts only the two history entries
  immediately after cash-out, so a voucher purchase, reroll, or pack visit
  discards an otherwise exactly reproduced public play. Find the latest typed
  `ROUND_EVAL -> SHOP` cash-out boundary, require the same public ante and round
  and only SHOP/PACK steps since that boundary, then reuse the existing
  historical score reproduction and current public lineup/stats. Add a reroll
  regression and keep malformed or cross-round histories fail-closed. This is
  a prerequisite for replacing static repeat-upgrade guesses with observed
  score deltas; screen any behavior change before promotion.
- Replace the temporary copy-only repeat exception with an exact public-score
  gate. After any prior shop replacement, consider another category-qualified
  sell-plus-buy only when the persisted context reproduces the last observed
  score exactly and the resulting lineup, with the bought Joker appended in
  the real shop order, scores strictly more on that same public hand. Fail
  closed when the context is stochastic or unavailable; keep the existing
  category margin, affordability, additive-Mult protection, and one-sale-per-
  shop limit. Organic diagnostics separate the cases: seed 505's Brainstorm-
  for-Even-Steven swap gains 6,262 modeled chips on the reproduced hand, while
  seed 541's later Photograph-for-Banner swap loses 10,440. Add positive copy,
  positive ordinary x-mult, negative conditional, same-shop, and missing-
  context regressions. Replay seeds 505/541, then require both existing wins,
  no paired regressions, and positive progression on 501--550.
- Reject using the persisted context for general offer ranking. The combined
  screen stays at two wins and nets +2 rounds/+1 ante, but regresses seed 503
  by one round while improving seed 517 by three. Neither changed seed performs
  a new Joker sale; their acquisitions diverge because the broader context
  changes post-action offer ranking (Green Joker instead of Flower Pot on 503,
  then a larger cascade on 517). Preserve the existing strict immediate-post-
  cash-out context for ordinary buys. Expose the within-shop persisted variant
  only to the exact repeat-replacement gate, where it is needed to score the
  concrete sell-plus-buy option after vouchers or rerolls. Recheck changed
  seeds 503/517 and causal seeds 505/541 before another panel.
- Retain the narrow persisted-context repeat-replacement gate. The frozen
  `phase1-narrow-exact-repeat-replacement-v1-red-white-seeds501-550.json`
  report completes 50/50, preserves wins 506 and 541, improves seed 517 from
  round 12/ante four to round 15/ante five, and has no regressions. Totals rise
  from 715 rounds/241 antes to 718/242. The strict context remains in force for
  ordinary offer ranking; only repeat sell-plus-buy evaluation scans back to
  the current shop boundary. The pinned focused suite passes 280 tests with
  Ruff and `git diff --check`. Promote this as the development floor; Phase 2
  remains locked far below 20/200.
- Extend the exact survival purchase override to the next mechanic-free Big
  Blind. The current ranker only runs after a Big Blind, only for a typed
  high-target boss, and only when one offer closes the entire gap; 15 of the 48
  fresh-panel losses instead die on Small or Big Blinds. After an exactly
  reproduced Small-Blind play, compare current and offered four-hand capacity
  with the visible upcoming Big-Blind target. If the current lineup is short
  and a modeled offer strictly reduces the deficit, allow that Joker to spend
  down to the existing emergency $3 floor and rank full closure ahead of
  partial gap reduction. Preserve the strict immediate-cash-out context and
  keep ordinary effect-boss projections disabled; the existing typed high-
  target boss case remains. Add deficit, adequate-capacity, missing-context,
  and effect-boss regressions. Screen 501--550; retain only if both wins remain,
  all runs complete, and no seed regresses.
- Reject the Big-Blind survival-spend override. It changes one shop trajectory
  on seeds 501--550, leaves all 50 terminal win/round/ante tuples unchanged,
  and stays at 2/50. Restore the high-target-boss-only ranker and its original
  affordability rule; the exact score context is too rarely available in the
  low-cash open-slot states for this to be a useful Phase 1 lever.
- Test a bounded strong-tag skip policy on that corrected control. On Small
  Blinds only, skip for guaranteed economy tags (`Investment Tag`, `Coupon
  Tag`) or premium Joker tags (`Negative Tag`, `Polychrome Tag`, `Rare Tag`)
  when the visible upcoming boss is known and is not a typed high-target boss.
  The existing public shop/pack policy still decides whether to take the
  resulting offer, so unsupported rewards remain fail-closed. Preserve the
  existing Economy Tag rule, all Big/Boss selections, and Meteor/Top-up's prior
  rejection. Add tag-class, Big-Blind, unknown/high-target boss, and ordinary
  tag regressions. Retain only if the 451--500 panel completes without
  rejections, adds a win, beats 624/211, and improves more seeds than it
  regresses.
- Reject the strong-tag bundle. It executes 50 skips and completes every run
  without rejection, but stays at 0/50, falls to 577 rounds/210 antes, and
  regresses 20 seeds while improving ten. Restore Economy Tag as the only
  admitted skip. Under the current continuation policy, lost shops and scaling
  hands dominate these delayed rewards.
- Test public sampled discard choice as the next broad tactical slice. The
  retained controller chooses one fixed keep-set and discards whenever build
  pacing fails; it neither compares that discard with playing now nor uses the
  public remaining-deck composition. At ordinary Small and Big Blinds only,
  form a bounded semantic candidate set from the retained discard plus the
  inferred primary/secondary build and Pair, Two Pair, Straight, and Flush
  keep-sets. Evaluate each refill on a small fixed set of shared deterministic
  permutations of the canonical public remaining-deck multiset, decrementing
  the public discard resources before scoring. Choose a discard only when its
  mean next-play score strictly exceeds the current exact play; otherwise keep
  the retained play. The samples are keyed only by the public observation
  digest and a fixed policy nonce, never the live seed or candidate RNG.
  Preserve the existing boss, hidden-card, Green Joker/Ramen, legality,
  Serpent, and malformed-belief fallbacks. Add deterministic, hidden-twin,
  deck-order, draw-composition, play-dominates, discard-dominates, and fallback
  tests. Screen against the frozen narrow-replacement floor on seeds 501--550;
  retain only if all runs complete without rejection, wins 506/541 remain, at
  least one additional paired win appears, aggregate rounds and antes rise,
  and more seeds improve than regress. Otherwise delete the slice and preserve
  its immutable report.
- Reject the sampled discard slice after its frozen screen and delete it. The
  report `phase1-public-sampled-discard-v1-red-white-seeds501-550.json`
  completes 50/50 without rejection and preserves wins 506/541, but adds no
  paired win. It improves 18 seeds, regresses six, and gains 42 rounds/11
  antes at 43.70 decisions/s. This confirms that public deck-aware discard
  choice affects progression, but it fails the predeclared win gate and the
  eight-sample mean is not a justified strength dependency. Restore the exact
  retained discard controller and its action-level regressions.
- A no-file shadow also rejects capping Seed Money/Money Tree reserves at the
  ordinary $25 interest line. On seeds 501--550 it loses established win 506,
  adds no win, and falls from 718/242 to 716/241 total rounds/antes. Keep the
  source-defined extended interest cap; late cash by itself does not justify a
  global reserve relaxation.
- Implement the missing history-independent shop survival projection as the
  next coherent Phase 1 increment. At a settled shop the public remaining-deck
  multiset is the full current deck, so synthesize one deterministic
  representative hand for the inferred primary build using only visible card
  semantics, levels, ordered Jokers, resources, and the current hand limit.
  Select a source-valid Pair/Two Pair/Trips/Straight/Flush/full-house family
  template, prefer visible card traits activated by the current lineup, fill
  held slots deterministically, reset only per-blind public counters, and score
  it with `_play_score`. Compare the current lineup and each concrete visible
  offer against the visible next-boss target over the public hands-per-blind.
  Use this projection only when the stricter reproduced-last-play probe is
  unavailable: it may admit a supported open-slot scorer below the ordinary
  reserve only when it reduces a positive boss-capacity deficit, and may admit
  a later full-slot replacement only when the same concrete post-sale lineup
  reduces that deficit while preserving the existing category margin,
  additive-Mult, sticker, affordability, and action-budget gates. It never
  predicts draws, shops, boss RNG, or a candidate transition. Unknown build
  templates, incomplete deck composition, hidden semantics, stochastic
  scorers, and malformed resources fail closed. Add representative-hand,
  lineup-delta, next-boss, exact-probe priority, affordability, replacement,
  and hidden-twin tests. Screen 501--550 first; retain only with complete
  execution, wins 506/541 preserved, at least one added win, positive total
  rounds/antes, and more improvements than regressions before a fresh 200-seed
  strength gate.
- Reject and delete the representative-shop fallback after its frozen screen.
  `phase1-representative-shop-survival-v1-red-white-seeds501-550.json`
  completes 50/50 and preserves wins 506/541 but adds no win. Seeds 520/540
  improve, seeds 503/538 regress, and the aggregate gains only six rounds/three
  antes. The deterministic best build hand is both optimistic about draw
  consistency and unable to price conditional effects such as Flower Pot; it
  is not a safe fallback when the exact historical score context is absent.
  Restore the strict exact-context shop controller and do not elaborate this
  synthetic projection before fair rollouts are unlocked.
- Replace the optimistic representative hand with a bounded public deal-profile
  experiment. At a settled shop, form eight shared deterministic without-
  replacement hands from the canonical full-deck multiset using only the
  public observation digest and a fixed policy nonce. For the current lineup
  and each concrete supported offer, reset public per-blind counters and score
  the exact best visible play in each hand; do not step Jackdaw or model any
  subsequent action. Rank only on lower-quartile four-hand capacity against the
  visible boss target, then mean immediate-score delta. A positive deficit
  reduction may use the existing $3 emergency floor; later repeat replacement
  still requires the category margin, additive-Mult, sticker, affordability,
  and action-budget gates. Direct exact historical score evidence remains a
  separate higher-confidence rank. Sampled hands are common across sibling
  offers and invariant to deck-entry order; malformed/full-deck-inconsistent
  observations fail closed. Add sampling, hidden-twin, order-invariance,
  score-profile, affordability, and replacement tests. Screen seeds 501--550
  with the same complete-run, retained-wins, added-win, positive aggregate,
  and improvement-count gate. Delete the experiment if it adds no win.
- Reject and delete the public deal-profile experiment. The frozen report
  `phase1-public-deal-shop-profile-v1-red-white-seeds501-550.json` completes
  50/50 and creates a new win on seed 542, but loses established win 506. It
  improves five seeds, regresses ten, loses four total rounds, and has zero
  ante gain while slowing the policy to 36.68 decisions/s. Public next-hand
  consistency is action-sensitive, but no one-step shop score statistic
  captures the continuation value of a sale or purchase. Restore the strict
  exact-context controller; defer distributional shop evaluation to the fair
  rollout phase after the Phase 1 win gate.
- Test a stochastic-clear safety rule against the restored floor. The current
  scorer correctly uses expectation for Misprint and Bloodstone when ranking
  hands, but the controller also treats that expectation as a guaranteed blind
  clear and as sufficient build pace. Seed 518 exposes the distinction: it
  dies 128 chips short with all five public discards unused after an expected
  Misprint score was accepted as safe. Keep expected score for option ranking,
  but compute a second source-defined lower bound (zero bonus Mult for
  Misprint and no random Bloodstone trigger) for clear and pace authority.
  When expectation clears but the lower bound does not, continue through the
  existing reorder/discard path; do not invent a probability, sample private
  RNG, or change deterministic lineups. Add exact mean/lower-bound and policy
  regressions. Screen seeds 501--550 and retain only if wins 506/541 survive,
  at least one paired win is added, every run completes, aggregate rounds and
  antes rise, and no baseline win is lost.
- Reject and delete the stochastic-clear safety rule. Its frozen report
  `phase1-stochastic-clear-floor-v1-red-white-seeds501-550.json` completes all
  50 runs, preserves wins 506/541, and makes seed 518 spend all six available
  discards instead of dying 128 chips short with five unused. That run advances
  only one Big Blind and still loses; no other terminal result changes, so the
  screen remains at 2/50 with +1 round and zero ante gain. Keep expected-value
  scoring for both ranking and pace until a policy can value the full stochastic
  continuation rather than substituting an over-conservative lower bound.
- Test fresh Ramen as the first source-audited Joker-support closure. Pinned
  Jackdaw initializes Ramen at x2 Mult and only serializes the typed `x_mult`
  counter after a public discard mutates it. The current support gate therefore
  rejects a legitimately visible fresh offer even though the scorer and discard
  policy already handle owned Ramen. Admit only this exact initial state, score
  it at x2 when the typed counter is absent, and continue using the counter once
  present. Do not infer other missing counters or relax build, replacement, or
  reserve gates. Add fresh/mutated value and score regressions. Screen seeds
  501--550; retain only if runs are complete, wins 506/541 survive, at least one
  paired win is added, aggregate rounds and antes rise, and no baseline win is
  lost.
- Reject and delete fresh-Ramen support after its frozen screen. The candidate
  completes 50/50 with the same wins 506/541 and exactly the same terminal
  win/round/ante tuple on every seed. Both artifacts acquire Ramen once on seed
  533 after a typed counter is already available; admitting the absent-counter
  offer creates no additional purchase because the observed seed-542 offers
  sit behind a full lineup and the conservative repeat-replacement proof gate.
  The report `phase1-fresh-ramen-support-v1-red-white-seeds501-550.json` is
  retained as negative evidence. Do not weaken the support gate independently
  of the concrete sell-plus-buy proof.
- Test an exact public score-interval proof for repeat replacements when the
  prior score cannot be reproduced solely because Misprint or Bloodstone is
  stochastic. Reconstruct the same last visible public play and current shop
  lineup as the persisted exact context, but calculate source-defined lower
  and upper scores: Misprint contributes 0--23 Mult and each Bloodstone heart
  contributes x1--x1.5 in scoring order. For a concrete supported sale-plus-buy
  option, allow the replacement only if its lower score is strictly greater
  than the current lineup's upper score; otherwise fail closed. Preserve the
  category margin, additive-Mult protection, affordability, same-shop limit,
  and actual append order. This may justify unconditional x-mult without
  guessing the live random draw. Add interval, dominance, overlap, hidden,
  and deterministic-context-priority tests. Screen seeds 501--550 and retain
  only with wins 506/541 preserved, at least one added win, complete execution,
  positive round/ante totals, and no baseline-only win.
- Reject and delete the stochastic replacement interval after its frozen
  screen. The report
  `phase1-stochastic-replacement-interval-v1-red-white-seeds501-550.json`
  completes all 50 runs, preserves wins 506/541, and proves one conservative
  Ramen-for-Misprint replacement on seed 542. That seed advances four rounds
  and one ante to the ante-eight Violet Vessel with no paired regression, but
  still loses and the panel remains 2/50. The experiment therefore fails the
  mandatory added-win gate. Restore the exact deterministic-score replacement
  controller and remove fresh-Ramen support with it; a same-hand dominance
  proof does not value enough continuation to close the Phase 1 gap.
- Complete one coherent deterministic-Joker scorer slice. Add source-audited
  rarity to the 150-key catalog and implement the three high-impact effects
  whose current value needs no hidden or missing runtime state: Triboulet's x2
  on each scored King/Queen (including public retriggers and conservative copy
  resolution), Baseball Card's x1.5 after each non-debuffed Uncommon Joker in
  source scoring order, and Ramen's known fresh x2 before its typed decay
  counter appears. Derive Baseball rarity only from the pinned semantic-key
  catalog; never inspect an engine card or generic ability payload. Stateful
  Idol, Steel/Stone tallies, and Caino remain unsupported until their typed
  public inputs exist. Add catalog completeness, ordering, retrigger/copy,
  fresh/runtime, debuff, and score tests. Screen seeds 501--550 as one scorer
  coverage bundle; retain source-correct calculations only after exact fixture
  checks, and make a strength claim only if wins 506/541 survive and at least
  one paired win is added with complete execution and positive progression.
- Retain the deterministic Joker scorer layer as source correctness, not as a
  strength promotion. The frozen report
  `phase1-deterministic-joker-scorers-v1-red-white-seeds501-550.json` completes
  50/50, preserves wins 506/541, improves only seed 503 by one round, and has
  no regressions. It acquires Baseball once, Ramen once as before, and has no
  Triboulet exposure; the panel remains 2/50. Keep the complete 61/64/20/5
  rarity partition plus exact Baseball/Triboulet/Ramen scoring because their
  source fixtures pass and terminal evidence is non-regressive. Do not claim a
  win-rate gain or unlock Phase 2.
- Replace static targeted-consumable tie-breaking with deterministic public
  outcome scoring. For each legal Death, Strength, suit-conversion, or fixed
  enhancement target, transform only the visible selected hand cards according
  to the pinned semantic rule, then compare the best exact public play before
  and after under the current build/scorer. Rank by immediate score gain, build
  family improvement, and stable action order; retain the existing base value
  only as a positive eligibility prior. Destruction and random Spectral/Tarot
  effects remain on their existing explicit rules, hidden targets fail closed,
  and this does not reopen direct shop-card purchases. Reopen Arcana packs at
  the existing Celestial reserve only as part of this outcome-aware bundle;
  this is the missing causal model that distinguishes it from the rejected
  static-value Arcana screen. Add direction, rank wrap, suit, enhancement,
  hidden, pack-affordability, and action-choice tests. Screen
  501--550; retain only with complete runs, wins 506/541 preserved, an added
  paired win, positive rounds/antes, and no baseline-only win.
- Reject and delete the outcome-aware Arcana bundle before a third full panel.
  The first report,
  `phase1-outcome-aware-arcana-v1-red-white-seeds501-550.json`, is invalid:
  recomputing the unchanged best hand for every legal target exceeded the
  two-second isolated-policy budget on seed 502 and closed the shared child,
  so only 1/50 runs completed. Hoisting that unchanged score once per public
  decision cut the exercised eight-card Arcana decision from about 3.07 to
  1.52 seconds without pruning a target. The second diagnostic report,
  `phase1-outcome-aware-arcana-v2-red-white-seeds501-550.json`, then completed
  seeds 501--509 before an exact 243-action, ten-card Arcana choice on seed 510
  exceeded the same budget. This report is also invalid as a panel, but it
  already falsifies retention: baseline win 506 becomes an ante-six loss after
  buying eight Arcana packs, while seed 502 improves four rounds and two antes.
  Since losing any baseline win is a hard rejection regardless of later seeds,
  do not spend more evaluation budget on this bundle. Preserve both reports as
  failure diagnostics, restore the deterministic-Joker floor, and do not claim
  metrics from either incomplete panel.
- Test role-completion rerolls as the next bounded shop correction. The current
  controller stops searching as soon as it owns two scoring Jokers unless all
  Joker slots are full, even when it has no build-usable x-mult; 55 of 142
  seed-1--200 losses reaching ante four have no catalogued x-mult at death, and
  30 of those still hold at least $25. From ante three onward, treat a lineup
  without usable x-mult as incomplete whether or not it has open slots, and use
  the existing at-most-three rerolls only from money above the unchanged
  interest reserve. Preserve the existing early two-scorer build rule, exact
  offer valuation, replacement proof, and all buy/reserve gates. Stop rerolling
  immediately when a build-usable x-mult is owned. Add open-slot, completed-role,
  reserve, and bounded-shop regressions. Screen seeds 501--550; retain only with
  complete runs, wins 506/541 preserved, at least one added paired win, positive
  aggregate rounds/antes, and no baseline-only win.
- Reject and delete role-completion rerolls. The frozen report
  `phase1-role-completion-reroll-v1-red-white-seeds501-550.json` completes
  50/50 and preserves wins 506/541, but adds no win, loses four aggregate rounds
  and one ante, and sends seed 547 back nine rounds. Five seeds improve and
  three regress; aggregate reroll count is unchanged, showing that forcing the
  same bounded rerolls earlier merely changes which offers the policy can
  afford. Restore the full-lineup upgrade condition.
- Test horizon-aware endgame reserves. The controller currently protects the
  full $25 interest cap even in ante eight, where cash left after the boss has
  no survival value. On the fresh panel, seed 505 dies only 3,988 chips short
  at the ante-eight Amber Acorn while holding $74, and seed 542 dies 5,450
  short in ante seven while holding $54. For builds without Bull or Bootstraps,
  reduce the reserve to $12 in ante seven and $3 in ante eight or later; keep
  the existing cap for money-scaling Jokers and every earlier ante. All
  existing purchase, reroll-count, score-proof, and affordability gates remain
  unchanged. Add ante-six/seven/eight and money-scaling regressions. First run
  causal seeds 505/506/541/542/543, then screen 501--550 only if both retained
  wins survive. Retain only with complete runs, wins 506/541 preserved, an
  added paired win, positive aggregate rounds/antes, and no baseline-only win.
- Reject and delete the horizon-aware reserve probe after exhausting its
  causal surface rather than running an uninformative full panel. The change is
  dormant before ante seven, so only fresh-panel losses 505, 529, 535, 542,
  and 543 can differ; direct isolated runs also recheck wins 506 and 541. Both
  wins survive. Seed 542 advances two rounds to the ante-seven Pillar, but 543
  regresses three rounds, 529 regresses slightly, and 505/535 are unchanged;
  none wins. Restore the fixed reserve. The result also shows why cash alone is
  not the missing policy: seed 505 keeps $74 because its already-full lineup is
  considered complete, so a lower floor creates no legal strategic spend.
- Fix the Mouth opening commitment using exact public pace and hand-family
  repeatability. A score-fidelity replay exposes the causal error on fresh seed
  501: before any hand is established, a visible Pair scores 1,374 against a
  1,000-per-remaining-hand pace, but the generic Three-of-a-Kind build vote
  discards twice and eventually establishes Straight. Three Straights score
  3,654/4,000; the final hand has no Straight and the off-family Full House
  correctly scores zero. Only while the current typed boss is the Mouth and no
  family has yet been played, rank families that meet exact remaining-target
  pace by guaranteed/repeatable simplicity (High Card, Pair, Two Pair, then
  progressively harder hands), and take the highest-scoring play within the
  first viable family. Preserve an immediate full-clear play, all established
  Mouth behavior, ordinary build pacing, and every other boss. Add opening,
  already-established, insufficient-pace, and ordinary-blind regressions.
  Replay seed 501, then screen 501--550; retain only if all runs complete,
  wins 506/541 survive, at least one win is added, aggregate rounds/antes rise,
  and there are no baseline-only wins.
- Reject and delete the repeatability-order Mouth opening after its causal
  seed-501 replay. It successfully establishes Pair immediately and scores on
  all four hands, but totals only 3,057/4,000 versus the control's 3,654 from
  three Straights plus one blocked hand. Availability order alone throws away
  too much score; choosing a Mouth family requires belief over future draws or
  a stronger public continuation estimate. Preserve the diagnostic and do not
  generalize this rule to the other 11 Mouth losses.
- Test an exact-context boss-survival purchase lane without relaxing the shop
  economy globally. Forty-one of the 193 frozen seed-1--200 losses finish
  within ten percent of target and 23 of those retain at least $20; the earlier
  broad reserve shadow converted seed 160 but lost wins 6 and 62 because
  vouchers consumed the newly available cash. At the shop immediately after a
  Big Blind, reuse the source-correct persisted last-play reproduction for the
  visible next boss. A direct, supported, non-stochastic Joker offer may bypass
  the ordinary category threshold and interest reserve down to $3 only when
  the current four-hand projection has a positive target deficit and the
  concrete appended lineup strictly reduces it. Do not authorize a reroll,
  voucher, pack, sale, replacement, or future-offer prediction, and preserve
  the ordinary controller when the historical score cannot be reproduced
  exactly. Add strict-improvement, no-deficit, stochastic, reserve, non-Joker,
  full-slot, and missing-context regressions. First replay near-loss seeds
  10/63/87/103/142/146/160/173/177 plus all seven frozen wins; require every
  win to survive and at least two losses to advance. Only then screen 501--550,
  followed by seeds 1--200; retain only if a complete panel adds a win with no
  baseline-only win and positive aggregate progression.

1. Remove the 512-action and 2,048-candidate prefix dependence. Generate and
   test relevant play/discard candidates for supported hand sizes without
   dropping pairs, singles, straights, or build targets.
2. Choose a revisable target hand family from public deck composition, Joker
   effects/order, and hand levels. Discard only when its expected survival gain
   exceeds playing now and its build-specific cost; there is no unconditional
   spend-all-discards rule.
3. Add a key-specific typed whitelist for legitimately visible Joker runtime
   values. Never expose a generic ability tree or parse localized effect text.
4. Cover all 150 base Joker keys in a source-audited catalog with an explicit
   valuation class, archetype tags, order sensitivity, runtime schema, and
   scoring support or a declared non-scoring classification. Validate scoring
   deltas on organic candidate and authority fixtures.
5. Encode all vanilla bosses by semantic identity and handle their public
   effects before using survival projections to value purchases.
6. Price coherent shop and pack choices against the minimum survival margin on
   the visible path to the boss. Preserve interest unless spending improves
   survival; price vouchers and tags; use or sell consumables; and support
   replacement and ordering where public legality is complete.

#### Phase 1 gates

- Correctness: every prespecified run completes without policy/legality errors,
  required diagnostics are present, hidden-twin/firewall checks pass, and
  exercised authority transitions replay exactly.
- Strength: double-digit candidate Red/White win rate is the screening floor.
  Promotion additionally requires a positive paired authoritative win-rate
  lower bound over a fresh frozen panel versus the Phase 0 baseline.

### Phase 2: Fair Jackdaw Belief Rollouts

- Build a backend-free `PublicBeliefState` from the current public observation
  plus sufficient typed public history. Persist sufficient public statistics
  rather than truncating history when synthesis needs them.
- Synthesize visible cards, items, areas, counters, prices, resources, blind
  state, and compatibility state exactly. Sample deck order, future RNG, VM
  order, and every unresolved latent only from policy-owned tapes.
- Drive all stochastic mechanisms from the synthetic RNG: shuffles, shops,
  packs, tags, vouchers, bosses, stickers, editions, random Joker/card effects,
  consumables, and card creation.
- Require root public round-trip equality, public-legality agreement, sibling
  tape sharing, hidden-twin identity, shuffled-action/target negative controls,
  and held-out chance-frequency calibration. Any unsupported field, mechanic,
  transition, or exhausted budget invalidates the whole option.
- Enumerate coherent shop/pack/skip options and use the same rollout mechanism
  for in-blind decisions. Continue with the frozen Phase 1 policy to the next
  boss under declared deterministic decision and sample limits.
- Benchmark synthesis, clone, transition, and process overhead before freezing
  worker count or per-root budgets.

#### Phase 2 gates

First require a paired candidate win-rate gain over Phase 1 on a new 200-seed
panel. Then run both frozen policies directly in real Balatro on the same fresh
authority seeds; preserve every loss, require normal completion, apply the
preregistered paired confidence criterion, and replay every authority trajectory
through pinned Jackdaw with zero observed-state mismatch.

### Phase 3: Learning as Compression, Then Gold

Distill only public sibling comparisons from a Phase 2 artifact that passed its
gates. Use the compact value model to prune options and improve continuation;
do not replace exact public legality or the authority boundary. Freeze and test
the distilled artifact on disjoint panels, then progress through the cumulative
stakes while attributing failures to scoring, economy, boss, sticker, and debt
mechanisms. Final evaluation remains a frozen artifact on evaluator-secret
seeds under real Balatro.

## Superseded Objective (2026-09-01): Single-Machine Red/Gold Solver

The current policy is a fair one-seed White-stake solver, not a generally winning agent. Do not scale the failed hashed-GRU, behavior-cloning, sparse-PPO, or short-horizon action-value lanes. Keep the authority, information firewall, pinned Jackdaw candidate, and exact replay system; replace the intelligence loop with a solver-first hierarchy that spends compute only on consequential uncertainty.

### Fixed constraints

- The development and final artifact run on the repository host class: one Apple M2 Pro with 32 GB memory. External rollout farms and hidden-state oracles are outside this milestone.
- The policy and search receive only `PublicObservation`, typed public actions, bounded public history, and a policy-owned search nonce. The live seed, private clones, actual RNG state, hidden deck order, and future shops never enter search or training labels.
- Jackdaw executes and validates candidate transitions. It does not define policy observations, public legality, belief state, or the learned action representation.
- Real Balatro under the pinned BalatroBot/LÖVE stack remains authoritative. Candidate wins and snapshot branches never count as wins.
- Promotion uses win probability. Average ante, rounds, prediction loss, search visits, and candidate-only outcomes are diagnostics.

### Architecture

1. **Action-sufficient public contract.** Own phase-specific legality in this repository. Represent every visible input needed for Cerulean Bell, targeted held consumables, targeted Arcana/Spectral pack choices, selling and replacement, multi-pick packs, ordering, and Gold-stake stickers/counters. Compile typed primitives independently to BalatroBot and Jackdaw, and revalidate after every primitive in a multi-step option.
2. **Exact tactical solver.** Enumerate or beam-search play/discard/target/order choices with exact public scoring, mechanical-equivalence reduction, transposition caching, and exact without-replacement draw beliefs. The search ends at the current blind boundary and optimizes survival probability rather than raw expected chips.
3. **Strategic option search.** Search coherent public shop/pack options such as sell-then-buy, bounded rerolls, pack multi-picks, consumable use, and build reordering. Pareto-prune on money, interest, guaranteed scoring floor, scaling, slot flexibility, rental liability, perishable lifetime, and Eternal commitment.
4. **Fair uncertainty.** Draws use the exact public deck multiset. Future offers use source-defined public conditional distributions and policy-owned random tapes keyed by public digest, search nonce, and rollout index. Sibling options share tapes; sequential elimination spends additional samples only on close choices. The initial horizon ends at the next boss.
5. **Learning as compression.** Only after learner-free search beats the frozen heuristic, fit a small structured ranking/distributional-value model from belief-averaged sibling comparisons. Encode explicit card/item entities, runtime counters, order, sticker liabilities, hand-family contributions, and low-rank Joker interactions. Search disagreements and uncertain high-impact roots receive priority; raw PPO and imitation remain closed.

### Build and kill gates

- [ ] Close the public action/schema gaps and require hidden twins to produce identical observations, legal options, random tapes, search statistics, and actions.
- [ ] Produce a Red/Gold mechanism-by-phase-by-action coverage matrix with exact complete authority traces and zero waivers. Keep Jackdaw untrusted outside the certified envelope.
- [ ] Implement a cached tactical scorer/solver and show exact agreement with candidate and authority outcomes over the covered mechanics.
- [ ] Implement learner-free one-shop-to-next-boss option search. On a locked paired Red/Gold candidate panel it must produce action-sensitive sibling returns, strictly more wins than the unchanged strategic heuristic, and a positive paired survival lower bound on a separate replication panel.
- [ ] Reject the search target if shuffled action identities or shuffled targets retain ranking performance. Reject the chance model if held-out public transition frequencies are miscalibrated.
- [ ] Transfer the unchanged promoted search artifact through complete Red/Gold authority traces spanning every action family it uses. Any executor rejection, hidden-twin difference, mismatch, or incomplete run kills promotion.
- [ ] Distill only after search passes. The compact artifact must retain most of the paired search gain on disjoint seeds under the declared candidate-transition and decision limits.
- [ ] Freeze the final artifact before generating evaluator-secret seeds. Compare one attempt per seed against a preregistered qualified strong-human Red/Gold cohort under identical rules; failures count as losses and the confidence interval for the paired win-rate advantage must clear the declared material margin.

### First decisive experiment

Build the action-complete Gold public contract and a learner-free one-shop-to-next-boss search slice. Collect naturally reached Red/Gold shop roots with the frozen heuristic, stratified by ante and sticker mix. Generate legal public option beams, compare siblings on shared independently sampled futures, run the selected option organically, and evaluate against the unchanged heuristic on disjoint paired seeds. Include hidden-twin and shuffled-option negatives and replay representative promoted trajectories in real Balatro. If this slice cannot create fair action-sensitive paired improvement, revise the abstraction before adding a value model or increasing compute.

#### Re-plan after the first reachability diagnostic

The pre-boss-only guard failed as a useful primary intervention surface: 50 complete Red/Gold candidate runs produced zero wins, reached only two eligible search roots, and selected one buy. Keep it as a unit-tested fairness slice, but do not scale particles or train on it. Expand the same shared-public-particle comparison to every organically reached shop whose next blind is already visible. Compare the search choice with the frozen baseline's actual directly representable option, permit one search override per shop, and then return control to the baseline instead of forcing an early exit. Record root reachability, baseline/selected sibling returns, and intervention counts. If this broader slice still cannot create paired survival gains, stop extending shop heuristics and move the exact public tactical solver ahead of strategic learning.

The broader 50-seed paired candidate diagnostic created a real but insufficient signal: 23 runs reached a represented search root, six final recorded choices differed from the baseline, five seeds survived farther, none regressed, and the paired total gained 18 rounds and three antes. Both policies still won zero runs. Treat this as permission to keep the public shared-particle abstraction, not as promotion evidence. The existing uncached one-card discard expectimax was stopped after sustained full-core execution because its repeated score enumeration is unsuitable for the single-machine controller. The next tactical slice must gate search on survival relevance, reuse score/transposition results, and prove gain per evaluated state before it is combined with strategic search.

A bounded per-hand survival heuristic also failed its kill gate and was deleted: on 10 paired Red/Gold seeds it improved two runs, regressed four, lost two total rounds, and won none. The failure is conceptual rather than a threshold issue. Averaging the remaining blind target over hands does not correctly price guaranteed chip progress, hand depletion, or future draw opportunity. The replacement must solve the blind as a finite-horizon public belief process with play and discard transitions sharing cached hand-score results; do not revive per-hand pacing or uncached one-draw expectimax.

The first finite-horizon particle beam is also rejected as evidence, despite advancing two of the first five paired candidate seeds from ante one to ante two. It consumed roughly 117 seconds for those five runs versus roughly one second for the heuristic, and its per-particle beam selected continuation branches using unseen tape tails. That strategy fusion is an oracle evaluation, not an executable public policy. Retain shared public particles and root comparison only. The replacement evaluates each root under one deterministic continuation policy that is a function of the simulated public state and uses a deterministic candidate-count budget. Its initial scorer-supported envelope is deliberately tiny: Red/Gold Small and Big Blinds with visible, unmodified base cards and no Observatory. Refill-to-capacity, public-equivalent hand sorting, integer score flooring, and complete hand-stat rows are part of the transition contract. Eleven stateless Jokers (`Bull`, `Crafty Joker`, `Droll Joker`, `Greedy Joker`, `Gluttonous Joker`, `Joker`, `Lusty Joker`, `Mystic Summit`, `Riff-Raff`, `Scary Face`, and `Wily Joker`) were added only after evaluator-only organic candidate states matched all 436 legal play/discard transitions for their observed single-Joker or interacting builds. Each additional mechanic expands only with the same differential proof.

The corrected fixed-continuation search is efficient enough for the declared machine and shows a small honest candidate signal. On the frozen paired Red/Gold seeds 1–30, all 60 runs completed with no illegal actions or policy timeouts under the same source digest. After the shop simulator was restricted to the same certified scoring envelope and deterministic play/discard continuation, with held consumables failing closed, search improved terminal progress on three seeds, regressed none by terminal ante/round, gained seven total rounds and three total antes, and took roughly 46 seconds versus nine seconds for the heuristic. Both policies still won zero runs. This passes the narrow non-regression/relevance check, not the strategic promotion gate: the mechanism envelope and shop option model remain far too small for a winning policy.

#### Re-plan after the checkpoint audit

The pre-commit audit found that `HiddenHandCard.aura_eligible` revealed whether a face-down card already had an edition even though the normal card-back rendering does not expose that fact. Remove the predicate from the public contract and make Aura fail closed on face-down targets. It also found that public affordability retained Credit Card's debt floor while the Joker was debuffed; condition that rule on an active, nondebuffed Credit Card and add a shared-legality regression. These are checkpoint blockers, not tolerated limitations.

The repository-local editable pinned Jackdaw checkout passes the complete candidate suite, but a fresh `uv --all-extras` installation currently loses Jackdaw's JSON data files. Keep the untracked lockfile outside the checkpoint and do not claim clean-install reproducibility until the upstream packaging boundary is repaired. This does not weaken the public search result, but it remains an evidence-infrastructure gap.

### Active Increment: High-Coverage Exact Joker Envelope

- A read-only scan of the frozen Red/Gold seeds 1–30 found 442 Small/Big-Blind decisions. Search admitted 147; 253 were blocked solely by an unsupported owned Joker. Sly Joker, Faceless Joker, Drunkard, Credit Card, and Banner are the smallest low-complexity set with the largest measured reach: together they account for 68 blocked blind decisions across nine seeds and 11 otherwise-compatible shop roots.
- Centralize the certified tactical and pre-blind shop Joker sets. Keep Riff-Raff tactical-only because its blind-setup creation is outside the shop rollout transition. Unknown, debuffed, stateful, stochastic, retrigger, copy, and order-sensitive mechanics continue to fail closed.
- Reuse the existing exact-in-envelope score rules for Sly Joker and Banner. Credit Card and an already-owned Drunkard are scoring-neutral during a blind; when the shop rollout buys Drunkard, add exactly one discard to the next blind unless the boss sets discards to zero.
- Add public money to the simulated blind state. Faceless Joker awards $5 per active copy after a discard containing at least three visible face cards; subsequent observations and score calls receive the updated money so Bull interactions remain exact. The current base-card/no-debuff capability gate avoids Stone, debuff, and face-classification ambiguity.
- Do not expose raw Joker ability trees or add runtime fields for immutable vanilla constants. Source review confirms this slice is determined by existing public keys, cards, counters, money, and Joker order.
- Admit each key only after organically reached Red/Gold states match every legal play/discard transition in pinned Jackdaw, including score, money, resources, hand refill/order, and hand statistics. Add a purchase-to-next-blind Drunkard regression. Synthetic tests remain regressions, not differential evidence.
- Rerun the frozen paired Red/Gold panel with zero illegal actions/timeouts. The wiring gate requires the expected capability reach increase; retention additionally requires actual newly enabled interventions and no terminal-progress regressions. Candidate improvement is not an authoritative Balatro win, and real Joker-bearing traces remain required before promotion.

#### Replication result and correctness re-plan

The frozen seeds 1–30 development panel retained the slice as candidate mechanics: all runs completed, 92 tactical roots contained a new key, 13 changed the baseline action, and search gained eight total rounds and three total antes with no terminal regression. Both policies still won zero games. On the preregistered disjoint seeds 31–60, search improved seed 49 by three rounds and one ante but regressed seed 32 by two rounds and one ante; the net was one round, equal average ante, and zero wins for both. The seed-32 divergence occurred Jokerless, so the certified Joker transition expansion is not the cause. Retain the mechanics and their differential tests, but reject this as a strength or promotion result. The fixed eight-particle root selector remains an uncalibrated tactical heuristic; do not tune it on these panels or scale particles as the next move.

Adversarial review also found that the pre-blind evaluator compared one-purchase counterfactuals while the executed strategic baseline could continue shopping. Restrict search to roots where the baseline would leave, and execute an overriding purchase as the complete option `buy then leave`. Do not use one-card rollout values to override a baseline purchase until coherent multi-action shop continuation exists. Credit Card's debt floor also stacks per active nondebuffed copy; make public legality count copies and retain the debuff regression.

### Active Increment: Exact Public Tactical DAG

- Replace sampled current-blind overrides with a learner-free, memoized public-state DAG. The solver state contains only the visible hand, public remaining-deck count vector, public round resources, chips, money, and hand statistics; the root observation supplies the already-certified blind and Joker mechanics.
- Enumerate refill outcomes as exact multivariate-hypergeometric count selections. Treat draw order as exchangeable only inside the current base-card, order-insensitive certified envelope, and retain exact multiplicities with `Fraction` probabilities.
- Reduce play/discard actions only when selected and retained visible-card multisets make their transition semantics identical. Preserve one concrete legal representative, retain the caller's baseline action on an equivalent tie, and never use raw object IDs or hidden deck order.
- Return `Outcome(clear_probability: Fraction, expected_capped_chips: Fraction, complete: bool)`. A state-budget, transition-budget, chance-branch limit, unsupported mechanic, missing public stat, or any incomplete child makes the root decision incomplete and forces the unchanged strategic baseline. A complete exact tie also keeps the baseline.
- Cache state values, score evaluations, and draw compositions. Begin with a bounded two-decision tactical horizon and the existing exact base-card/stateless-Joker envelope; widen only from measured cache/branch profiles, not by increasing particles or weakening completeness.
- Prove the kernel against an uncached exhaustive oracle on tiny labeled and duplicate-card decks. Add hidden-twin, shuffled remaining-deck/action iteration, semantic-duplicate, fresh/warm-cache, cache-key mutation, exact-probability, budget-incomplete, and tie-to-baseline regressions.
- Retire the sampled tactical selector from the deployed Red/Gold policy while retaining its certified one-step transition model for differential tests. Seeds 1-60 and the organic Joker fixtures are development evidence only. Freeze any widened exact artifact before a new disjoint candidate panel; replay representative promoted decisions and every claimed win through real Balatro.

#### Re-plan after the strict action-complete probe

The first strict all-action implementation completed zero of 27 attempted tactical roots on development seeds 1-5. Most roots correctly failed the two-decision horizon; the one eligible last-hand/last-discard root exhausted 100,000 transitions because every multi-card discard and every exact refill had to feed a complete final-play decision. Do not raise that budget or call partial enumeration exact. Keep the action-complete kernel and tiny oracle as a correctness reference, but deploy the smallest conservative exact improver: compare the actual baseline with every immediate play and every one-card discard, collapse only semantic duplicates, and require every represented action/chance child to complete. A multi-card baseline remains represented and therefore may still make the decision fail closed. An override claims only strict exact improvement over the baseline inside this declared proposal, never global tactical optimality. Record proposal completeness separately from mechanical/draw exactness and widen the proposal only through symbolic reductions or measured cache reuse.

The conservative proposal is implemented and the sampled tactical selector is no longer deployed. Exact count-vector draws, terminal-before-refill absorption, remaining-deck depletion, Faceless-to-Bull money, hand statistics, semantic duplicate actions, per-decision state/score/draw caches, and every deterministic budget are covered by fractional tiny-deck oracles and atomic fallback tests. Two consecutive organic Red/Gold Jackdaw discards match a member of the exact public successor distribution with the correct exact mass; this is candidate evidence, not Balatro authority. The dirty development panels complete without timeouts: on seeds 1-30 the exact policy improves only seed 5, from ante 1/round 2 to ante 2/round 6, moving the average from 4.733 to 4.867 rounds and 1.800 to 1.833 antes with no regressions; seeds 31-60 are identical to the baseline. All policies still win 0/60. Retain the exact mechanism as a safer tactical floor, but do not promote a strength claim or spend a fresh replication panel until a symbolic multi-card-discard reduction creates broader interventions.

#### Re-plan after the first Red/Gold authority transfer

The clean revision-`43a3cd0` Red/Gold seed-5 authority run completed as a loss at ante 1 after 16 decisions, but candidate replay failed at transition 6 before the candidate-only tactical improvement. Balatro generated the first-shop Crafty Joker with a Rental sticker and a $1 buy cost; pinned Jackdaw generated the same Crafty Joker without Rental at $4. The authority policy consequently bought both Crafty Joker and To Do List, while the candidate trajectory could buy only To Do List. The later authority state contained unsupported To Do List and never entered the exact tactical solver. This run neither validates nor contradicts the exact decision; it invalidates seed 5 as a transfer case and exposes a Gold-stake sticker-RNG parity blocker.

Stop policy panels and proposal widening until the first-shop sticker divergence is fixed at its source and regressed. The repair must reproduce the organic Rental assignment and price from the same public action prefix without reading authority state into the candidate, then pass the complete authority trace from transition zero with no mismatch or waiver. After that, rerun the unchanged frozen policy through a fresh exclusive authority trace. Only a mismatch-free trajectory that actually records a complete exact-search decision can validate the mechanism. Do not compensate in the public adapter by copying authority stickers or repricing offers independently of Jackdaw's private simulated state.

The blocker was Jackdaw flag plumbing, not RNG: initialized runs store Eternal, Perishable, and Rental enablement under `game_state["modifiers"]`, while the pinned card factory reads those three booleans from the top level. Seed 5's first two `ssjr1` rolls already exactly predict Rental Crafty Joker followed by plain To Do List. The candidate wrapper now temporarily exposes only those candidate-owned nested booleans at the card-factory boundary, fails closed on inconsistent state, and removes the aliases after every call. It does not copy an authority sticker or independently alter a price. An organic regression reproduces the $1 Rental Crafty Joker and $4 plain To Do List from the original public action prefix.

That repair advanced immutable-trace replay to the terminal transition, where BalatroBot observes `GAME_OVER` before Rental's queued dollar event runs but Jackdaw had deducted the fee synchronously. The wrapper now restores only that terminal queued charge while retaining synchronous end-of-round Joker and Perishable mutations; winning-round Rental charges are unchanged. The complete authority trace now replays exactly for 16/16 transitions. This closes the discovered Red/Gold candidate parity defects, not the tactical authority gate: the real trajectory owns unsupported To Do List, `PublicBlindBeliefSearch` correctly stays inactive, and no exact-search decision is present. Find a natural supported authority root or widen To Do List only after exact scoring and organic differential evidence; do not label this trace mechanism validation.

Correct Gold stickers supersede the earlier seeds 1–60 tactical result: those trajectories were generated by a kernel that never applied organically configured Eternal, Perishable, or Rental stickers. On the corrected dirty development seeds 1–30, the unchanged strategic and exact policies are identical on every seed: both complete 30/30, win 0/30, and average 5.400 rounds and 2.067 antes. A reachability audit explains the null result. Across 640 hand decisions, 459 are in Small or Big Blinds. Of 145 otherwise admitted search attempts, 139 fail closed because more than two play/discard decisions remain; only six complete, and none changes the baseline. Nineteen Small/Big states satisfy the two-decision horizon, but 13 contain at least one unsupported Joker and only six reach the exact proposal. The primary bottleneck is therefore the horizon, not proposal width or any single missing Joker.

Do not respond by raising transition budgets, restoring particles, or adding isolated Joker keys. The next tactical increment must symbolically reduce earlier decisions: compute admissible survival bounds and mechanically dominated play/discard classes from public score histograms and exact remaining-deck counts, expanding a branch only while its upper bound can beat the baseline. It must remain exact inside a declared proposal and fall back atomically when bounds cannot prove completeness. Require a material increase in completed roots and at least one action-sensitive paired improvement before another authority transfer; otherwise stop widening current-blind search and move effort to the action-complete shop contract.

## Execution Status (2026-08-08)

The failed independent simulator, planner, imitation pipeline, rule-presence gate, and their scripts/tests have been removed. The first foundation is implemented: typed public observations and actions, an adversarial information firewall, a strict BalatroBot observed-state backend, stable canonical state, provenance-rich tamper-evident traces, and no-waiver differential replay. The replacement test suite passes. Across 68 retained real-trace files, the canonicalizer accepts all 20,542 snapshots; the firewall accepts all 20,532 settled decisions and rejects only 10 transient `HAND_PLAYED`/`DRAW_TO_HAND` states.

A fresh public-action Red/White seed-1 smoke run completed in real Balatro and its five decisions reproduced exactly in a second real run. Jackdaw is pinned at `dbedc66255fe594cce7b7cccc188c8a11649d9ec`; its upstream suite passes 1,561 tests. Its raw bridge initially had 638 representational differences from BalatroBot. A narrow adapter now derives BalatroBot's representation from Jackdaw's own state. The clean schema-v4 campaign reproduced 765/765 transitions across seeds 9-25; all 17 runs lost. Policy and environment processes are now isolated, the real-game snapshot spike is complete, and public-history recurrent training exists. Jackdaw remains an untrusted candidate and every trained checkpoint still has zero wins. Schema v5 supersedes v4 after strategic exploration exposed previously unrepresented permanent card bonuses. Fresh schema-v5 seed-1 coverage and strategic traces reproduce 25/25 and 23/23 transitions exactly; both are terminal losses and only narrow authority evidence.

The first real solve boundary is now clean. At repository revision `b821b5b`, the frozen public strategic baseline completes candidate Red/White seeds 1-100 with 1 win, 7.89 average rounds, and 2.69 average ante. On real seed 63, the same policy reaches Balatro's `ROUND_EVAL`, `won=true`, ante-9 boundary after 212 decisions; all 212 transitions replay exactly in pinned Jackdaw with no mismatch. This establishes that the rebuilt system can beat one normal run. It remains a handcrafted baseline with a 1% candidate win rate, not a learned model and not a superhuman claim.

### Active Increment: Deterministic Differential Campaign

- Add a deterministic coverage policy driven only by `PublicObservation`, public history, and an explicit policy seed.
- Keep action selection bounded and family-aware; never enumerate the factorial reorder tail or enable actions whose public legality is incomplete.
- Record one exclusive authority trace per game, replay it immediately through pinned Jackdaw, and stop at the first exact mismatch.
- Run repeated fresh authority processes for the same run and deterministic policy before candidate replay. Compare canonical states exactly and report the first authority self-divergence; any process-specific runtime input must then be modeled explicitly and kept private from the policy.
- The benchmark mod set is Lovely, Steamodded, and BalatroBot only. UI/preview mods are disabled because they are not part of the game authority. Health reports the active mod IDs and every evidence script rejects an undeclared or missing mod.
- Begin with a small Red/White development panel. A terminal loss is acceptable coverage evidence but never policy-strength evidence.
- Promote neither the candidate nor policy work until the panel is complete and mismatch-free; every divergence becomes a candidate/adapter regression test.
- Schema-v1 seed-1 and seed-2 traces found and regressed real transport and candidate bugs, but are no longer promotion evidence after the canonical schema changed. The authority now requires a cash-out button owned by the current `G.round_eval`, defensively enforces that precondition in `cash_out`, and waits for the Tarot/Spectral hand. Candidate regressions cover round-target timing, split ante setup, Standard-card deck insertion, Spectral hand dealing, voucher activation, and pack/shop persistence.
- Seed 3 showed that numbered vanilla Booster suffixes are artwork variants chosen from presentation-sensitive global Lua RNG. Canonical schema v2 preserves the raw suffix but compares and exposes the known vanilla variants by their semantic Booster key. The adapter's attempted global-RNG emulation has been deleted.
- The next seed-3 divergence exposed an undeclared environment input: the local career profile had Mr. Bones unlocked and Seeing Double locked while Jackdaw assumes a fully unlocked profile. Benchmark authority launches now use a transient `all_unlocked` mode equivalent to Balatro's normal profile action, report it through health, and seal it in the trace manifest. Scripts fail closed on a missing or different profile mode; career-profile runs are diagnostics only. Under schema v2, clean seed 1 (skip), seed 2 (pick), and seed 3 (mixed) traces passed 91/91 transitions. Schema v3 supersedes that evidence by recording another private runtime input, so those traces are now historical regressions and must be regenerated before promotion.
- Seed 5 exposed two authority defects before candidate work could continue. Blind-skip tag packs return to `BLIND_SELECT`, not always `SHOP`, and To Do List's visible live target is `card.ability.to_do_poker_hand`, not its prototype `extra.poker_hand`.
- Repeated probes proved the remaining To Do variation is vanilla LuaJIT behavior, not extra RNG consumption: the source builds the chance pool with `pairs(G.GAME.hands)`, fresh VMs produced different visible-hand iteration orders, and both selected index 3 from the named RNG stream. Canonical schema v3 records that order as private runtime state. Candidate replay receives it before reset and uses it for the same To Do List/Orbital Tag pools; the policy firewall discards it. A fresh minimal-mod seed-5 trace then replayed exactly for 19/19 transitions. This is parity evidence from a dirty development revision, not promotion evidence or a win.
- The clean schema-v3 panel then reached seeds 1-8: 250/250 transitions reproduced exactly through public actions. Those are losing engineering traces, not policy evidence, and schema v4 now supersedes them.
- Seed 9 proved the full 12-entry LuaJIT hand-table order is semantic, not only its nine currently visible entries. Vanilla's boss-advance tie loop never updates its order sentinel, so the last tied maximum in `pairs(G.GAME.hands)` wins. Schema v4 records the full private iteration order, keeps it behind the policy firewall, and normalizes floats to Lua JSON's 14 significant digits. The schema-v4 seed-9 development trace passes 35/35 transitions.
- Seed 10 made the discard pile part of the exact private state. That exposed three source-level candidate defects: The Hook's forced discards must be sorted by hand position before effects and pile insertion; Standard-pack playing cards must be repriced after an edition is assigned; and blind-select UI consumes and stores three Orbital choices every ante before a tag fires. With those rules modeled, the schema-v4 seed-10 development trace passes 61/61 transitions. Fresh clean schema-v4 traces are required after commit before this becomes promotion evidence.
- Commit `b145c9b` produced the first clean schema-v4 evidence: seed 9 passes 35/35 transitions and seed 10 passes 61/61. Seed 11 then exposed Swashbuckler's per-frame `Card:update` state: its displayed mult is the sell-value sum of the other owned jokers even when the Swashbuckler itself is only a shop or pack offer. Updating that persistent ability field from candidate state makes the clean seed-11 authority trace replay 63/63. All three runs lost.
- Commit `d29094e` then produced clean exact traces for seed 11 (63/63), seed 12 (35/35), and seed 13 (43/43). Seed 14 exposed a shared affordability bug: Jackdaw updated `bankrupt_at` when Credit Card was acquired, but card, voucher, pack, and reroll handlers still compared costs to cash alone. Applying the source debt floor at that shared boundary makes seed 14 replay 121/121 through terminal loss at ante 4.
- Commit `9ea19ab` cleanly reproduced seed 14 (121/121), seed 15 (16/16), seed 16 (27/27), and seed 17 (18/18). Seed 18 received Voucher Tag and exposed an obsolete adapter constant that forced the voucher area limit to one even though Jackdaw had correctly created and serialized two offers. Deleting that override makes seed 18 replay 29/29. All runs remain terminal losses.
- Commit `c2d592f` then cleanly reproduced seed 18 (29/29) and seed 19 (27/27). Seed 20 bought its only voucher and exposed the inverse capacity case: an empty voucher list still has a one-card shop area. Candidate shops now persist a base capacity of one, raised by temporary Voucher Tag offers and unchanged by purchases; seed 20 replays 25/25. All runs remain terminal losses.
- Commit `7a054ad` completed the clean schema-v4 Red/White panel through seed 25. Exactly one clean trace per seed 9-25 gives 17 complete terminal losses and 765/765 exact transitions; the deepest runs reached ante 4 (seed 14, 121 transitions) and ante 5 (seed 21, 116 transitions). This is candidate-fidelity evidence only: there are zero wins and no trained model.

### Active Increment: Public Action Coverage

- The clean seed 9-25 corpus covers every decision phase and 11 action families, including both pack outcomes, blind skips, vouchers, and purchases.
- It never exercises rerolls, held-consumable use, selling, or reorder actions. Do not manufacture coverage by destructively selling useful state or enumerating factorial reorder tails.
- Add one explicit extended coverage mode. In that mode, reroll once at the start of a shop when publicly affordable, then follow the existing bounded purchase policy.
- Encode and exercise only held Planet use first. Planets are visible, no-target consumables with a source-defined legal use in `SELECTING_HAND` and `SHOP`; all targeted Tarot/Spectral rules remain fail-closed.
- Extended coverage is complete only when both `reroll_shop` and `use_consumable` occur in addition to the existing mixed-pack contract. Run a separate clean lane so the original seed 9-25 corpus remains immutable.
- Commit `75669b4` added that mode without opening targeted consumables, selling, or reorder actions. A clean seed 26-35 lane then reproduced 230/230 transitions across 10 terminal losses. It exercised 18 rerolls, one held-Planet use, three pack choices, and two pack skips. This closes the narrow extended-action gate; it does not show policy strength.

### Active Increment: Real-Kernel Snapshot Benchmark

- Prove the existing game-native file save/load path before adding a second persistence mechanism. Save one settled parent, explore a bounded suffix chosen only from public observations, restore the parent repeatedly, and replay the exact public actions.
- Require exact branch-local canonical equality at the restored parent and after every replayed action. Report the first mismatch; never reduce this to public-digest equality or tolerate RNG drift.
- Record snapshot bytes, SHA-256, save latency, restore latencies, replay depth, versions, mods, and run configuration. Keep the blob and filesystem path private and ephemeral.
- Do not add snapshot methods to the shared `GameBackend` protocol or advertise snapshot/restore capability yet. The first harness is privileged evaluation infrastructure, not a policy feature.
- Only after the file path passes should BalatroBot store the game's packed `save_run` representation in a private in-memory registry. Snapshot IDs and blobs never enter `PublicObservation`, public history, or the deployed policy process.
- Remove inactive debug/mutation and disabled-mod scoring endpoints from the benchmark authority registration when the authority patch is next revised; they are not part of the clean public-action or snapshot contract.
- Commit `48a1cce` produced a clean file-path baseline on Red/White seed 26: a 7,558-byte save restored in 61.9 ms median and replayed an eight-action suffix exactly five times (40/40 transitions). The suffix crossed draws, scoring, cash-out, shop generation, pack opening, and pack choice. This proves exact observed continuation for that checkpoint, not complete Lua-state capture.
- The in-memory spike reuses the same packed `save_run` representation, unpacks a fresh table on every restore, caps storage at 64 explicit entries, and clears stale entries on menu/start/file-load. The evaluator receives only an opaque ID and byte count. The authority registration drops screenshot, debug mutation, and disabled-DV scoring endpoints instead of carrying them into the benchmark runtime.
- Commit `eddae29` passed the same seed-26 branch through in-memory restore for 40/40 exact transitions: 2.9 ms capture and 56.5 ms median restore. The refactored file path then passed 24/24 at 59.1 ms median, and a fresh extended-policy seed-28 run passed candidate lockstep 22/22. Rebuilding the actual run/UI dominates restore, so the real kernel is an oracle/audit worker rather than the high-volume training kernel. Snapshot/restore capabilities remain unadvertised until broader checkpoints and uncaptured mod/global-state risks are tested.

### Active Increment: Honest Strength Baselines

- Add a bounded deterministic-random public policy and a greedy immediate-score public policy. Both consume only `PublicObservation`, legal public actions, and public history; neither receives a simulator handle or seed.
- Random excludes factorial reorder actions from its bounded sample. Greedy selects blinds, plays the highest visible immediate-score hand, cashes out, leaves shops, and skips packs; it intentionally has no strategic economy so later search has a clear floor.
- Evaluate fixed development seed ranges in pinned Jackdaw for throughput and outcome diagnostics, then run representative policies unchanged through clean BalatroBot differential traces. Fast results alone are not strength evidence.
- Freeze baseline name, code revision, policy seed, deck/stake, and seed range in every report. Report all losses and incomplete runs; never tune on the claimed comparison range.
- Before accepting a sweep, make terminal detection exact at the decision-budget boundary, require every run to terminate normally, record terminal-reason counts, label candidate-only diagnostics explicitly, and verify that the imported Jackdaw tree is the clean pinned revision.
- Commit `4f0d42e` hardened that evidence path. On candidate Red/White seeds 1-100, greedy completed 100/100 with 0 wins and average ante 1.05; deterministic-random completed 100/100 with 0 wins and average ante 1.0. The unchanged seed-1 policies then ran through real Balatro and reproduced in Jackdaw for 18/18 and 11/11 transitions respectively, both terminal losses at ante 1. These controls establish a trustworthy floor and no more.

### Active Increment: Fair Public-Belief Search

- Introduce a backend-free belief surface derived only from `PublicObservation` and public action/observation history. It must not import Jackdaw, BalatroBot, snapshots, seeds, RNG objects, raw states, or private IDs.
- Start with exact without-replacement draw probabilities over the public remaining-deck multiset. This is a chance model, not a clone of the live game and not yet full-run search.
- Require public hidden twins to produce identical beliefs, action rankings, and policy distributions. Malformed counts and unsupported hidden mechanics fail closed.
- Use the public chance model to build a bounded tactical search baseline before introducing learned values or latent particles for future shops and RNG streams.
- Commits `d1866af`, `0a4f323`, and `b8f1759` added exact public hypergeometric beliefs, a bounded one-ply single-card-discard expectimax policy, and a semantics-preserving scoring optimization. The frozen optimized policy completed candidate Red/White seeds 1-100 with 0 wins, average ante 1.23, average round 2.90, and only 2.80 decisions/s. Its unchanged seed-1 run reproduced through real Balatro for 27/27 transitions and lost at ante 1.
- This closes the one-ply baseline as a negative result: it is fair and reproducible, but neither strong nor fast enough for expert iteration. Do not deepen the same Python enumerator.
- Naive rejection sampling over candidate seeds is also rejected as the rollout architecture: matching a public hand makes acceptance exponentially small. A usable particle worker must sample latent states from the correct public-history conditional distribution, including VM-order and RNG latents, without using the live seed or snapshot.

### Active Increment: Policy Process Isolation

- Move the policy callback behind a strict JSON-lines child-process boundary before adding any model or training loop. The parent sends only canonical `PublicObservation`, public legal actions, and bounded public history.
- Reject unknown fields, raw authority state, seed/RNG/snapshot tokens, oversized messages, malformed actions, stale observations, timeouts, crashes, and extra stdout. Revalidate returned actions against the parent observation before execution.
- Keep environment kernels and private candidate state entirely in the parent/evaluator process. The child process must not import Jackdaw or BalatroBot.
- Once isolation passes adversarial hidden-twin tests, choose between public-history recurrent RL and a conditional latent-state worker based on measured feasibility; do not build seed-rejection particles.
- Commits `abebc01`, `1067577`, and `b75831c` moved policy contracts out of the BalatroBot package, added a strict public-state codec and bounded stateful JSON-lines protocol, and made all non-coverage evaluation policies run in the child by default. The parent kills the child on timeout, crash, malformed/oversized output, stale request or digest, extra stdout, out-of-set action, or independently illegal action.
- The process boundary passes 139 tests with 10 candidate-only skips. It deliberately scrubs the child environment down to the repository and basic runtime variables and asserts that neither Jackdaw nor BalatroBot was imported. This is accidental-leak isolation, not a hostile-code filesystem/network sandbox.
- Clean isolated candidate evidence at `b75831c`: greedy 0/100 at 94.50 decisions/s, deterministic-random 0/100 at 90.45 decisions/s, and tactical 0/20 with average ante 1.30, average round 3.05, and 6.95 decisions/s. The isolated tactical seed-1 policy then reproduced through real Balatro for 27/27 transitions and lost at ante 1.
- This closes the process-isolation gate for the current baselines. The next architecture decision must be measured: prototype a public-history recurrent training loop and a conditional latent-state sampler behind the same boundary, then keep only the approach that can produce useful decisions without private-state leakage or rejection-sampling collapse.

### Active Increment: Public Training Environment

- Run the pinned Python 3.12 Jackdaw candidate in a separate environment worker. The Python 3.11 training/orchestration side receives only strict `PublicObservation` frames and sends typed public actions; it never imports Jackdaw or receives raw state, `_gs`, RNG, snapshots, RPC details, or private IDs.
- Reuse the strict public codec, canonical action codec, bounded JSON-lines framing, deadlines, request/digest checks, and process cleanup already proven for policy isolation. Factor shared transport code instead of copying another subprocess implementation.
- The minimum environment protocol is reset, step, and close. Reset configuration belongs to the environment driver; seed values and seed manifests never enter model observations, action features, recurrent state, or rewards.
- Use `sparse_terminal_v1`: +1 for a public terminal win, -1 for a public terminal loss, and 0 otherwise. Any future shaping reward must be declared, public-state-derived, and evaluated separately.
- Benchmark Red/White seeds 1-20 and 1-100 with a frozen public baseline through this reversed boundary. Require the same outcomes as direct candidate evaluation and report steps/s, episodes/s, failures, worker provenance, and config/seed-manifest digests.
- Only after the worker passes should an optional PyTorch recurrent policy/value module be added in Python 3.11: compositional public card/item/set encoders, a GRU public-history state, dynamic legal-action scoring, and masked on-policy training. Behavior cloning of current baselines is a plumbing smoke test only; strength training uses public-history RL or later fair belief targets, never clairvoyant labels.
- Commit `5ddbd88` added the isolated Python 3.12 candidate worker, strict reset/step/close protocol, sparse terminal reward, explicit step-limit truncation, process-group cleanup, and benchmark-grade provenance. A clean Red/White greedy panel matched the frozen direct-candidate result per seed for both 20/20 and 100/100 complete episodes. The 100-seed worker sustained 178.53 decisions/s and reproduced the same zero wins, average ante 1.05, and average round 2.22. This proves boundary and outcome equivalence, not policy strength.
- Commit `f8b4d9a` added the optional Python 3.11 recurrent model: deterministic public feature hashing, a single GRU cell, dynamic legal-action scoring, a value head, strict checkpoint loading, and an initial no-reorder enumerative proposal. Its first frozen 20-seed evaluation failed closed when a 14-card hand produced 6,944 play/discard combinations; raising the bound again was rejected. Model format v2 now chooses play/discard at the top level and selects one to five increasing hand slots autoregressively. The proposal is bounded independently of hand size, sampled action log-probabilities replay exactly, and the 20-seed diagnostic completes without truncation. The model remains untrained in strength terms and has no wins.

### Active Increment: Public On-Policy Training

- Train only through `PublicEnvironmentProcess`; the trainer receives public observations, public rewards, and typed public actions. Environment seeds stay in the driver and never enter model features, recurrent state, advantages, or rewards.
- Use multiple independent candidate workers and batch model inference across them. Environment steps may run concurrently, but one worker remains one mutable episode and every reset/step response keeps the existing strict process contract.
- Start with clipped PPO over bounded `factorized_tactical_no_reorder_v2` decisions, fixed-length contiguous recurrent rollouts, GAE, normalized advantages, gradient clipping, and exact recurrent resets. Truncations bootstrap from their final public observation but never carry advantage into the next episode. Do not backpropagate through private environment state or reconstruct actions from simulator IDs.
- Keep `sparse_terminal_v1` as the promotion objective. The first `public_progress_v1` diagnostic was invalid as useful shaping because public `round_no` advances when a blind starts, so nearly every loss received the same bonus. That schema is deleted. A separately named `public_blind_clear_v1` training reward may add only a bounded bonus on the public `SELECTING_HAND -> ROUND_EVAL` transition; reports separate environment reward from shaped training reward, and final evaluation uses sparse terminal outcomes only.
- Save only model configuration, tensor weights, and a digest. Reports record repository/candidate revisions, reward schema, action-proposal schema, optimizer configuration, seed-manifest digest, episode outcomes, and all truncations/errors. Do not add replay databases, imitation datasets, dashboards, or distributed infrastructure for this smoke increment.
- The trainer is accepted only when a short deterministic smoke run produces finite losses, changes model weights, writes a loadable checkpoint, closes every worker, and the frozen checkpoint executes through the public environment without illegal actions. A strength claim requires a separately frozen evaluation with real wins and later clean Balatro reproduction.
- Commit `99e1e3c` replaced the failed enumerative tactical head with the factorized model. A clean 20,480-step PPO continuation then completed 1,985 training episodes at 122.23 steps/s with zero wins; 1,984 died in round 1, one reached round 2, and frozen held-out evaluation stayed at 0/100 with average round 1.0. This is a kill result for raw random-initialized PPO, not a reason to tune it further.
- The next bounded curriculum step behavior-clones the existing frozen greedy public policy only to initialize legal tactical play and passive control. It then trains with `public_blind_clear_v1` on disjoint environment seeds. Imitation accuracy is a plumbing/curriculum metric, never strength evidence; if the frozen model cannot at least recover the greedy baseline's held-out survival, stop model training and move directly to fair search targets.
- The clean 100-episode bootstrap reached 64.45% sampled exact action accuracy, but the frozen model averaged only round 1.16 on held-out seeds 1-100 versus the greedy controller's 2.22. It therefore fails the curriculum gate; do not tune imitation further.
- The replacement is a hybrid search-first control surface. A frozen public tactical controller owns `SELECTING_HAND`; fixed public flow selects blinds and cashes out. The learned recurrent policy owns only `SHOP` and `PACK`, with all ownership recorded in the artifact schema. PPO policy loss applies only to learned strategic decisions, while the public value loss and GAE span the complete trajectory. This preserves a known tactical floor, reaches strategic states without private information, and avoids teaching a neural network to poorly approximate code that is already exact.
- The first 8-worker hybrid run found an environment-schema defect rather than a training failure: buying Hiker created a visible `perma_bonus`, and canonicalization rejected that valid field once the card entered the discard pile. Schema v5 now records the bonus, the public firewall exposes it without deck-order leakage, the greedy scorer and model encode it, and the exact seed-40096 eight-action regression passes in pinned Jackdaw. A repeated 2,560-step hybrid diagnostic completed 146 episodes at 90.45 steps/s with zero truncations, zero worker failures, and zero wins. This validates the repair and training path only; strategic strength is still absent.

### Active Increment: Public Strategic Baseline

- Establish a fair strategic floor before generating search or model targets. Keep the existing bounded immediate-score tactical controller, but add public-only shop and pack decisions using semantic item keys, visible prices and slot counts, declared economy floors, safe held-Planet use, and bounded rerolls.
- Reuse the existing `PublicObservation`, legal-action iterator, bounded history, and isolated policy process. Do not import Jackdaw/BalatroBot, inspect ability trees, parse locale-dependent tooltip prose, branch the live private state, or receive seed/RNG/snapshot data.
- Support only actions whose public legality is already complete: Joker/Planet purchases, vouchers, boosters, rerolls, safe Planet use, and legal Joker/Planet/playing-card pack picks. Targeted Tarot/Spectral use, replacement sales, and reorder search remain fail-closed.
- Treat the pinned candidate's private-state smart heuristic only as a diagnostic ceiling: it wins 1/100 Red/White seeds and averages 7.67 rounds, but it is not fair evidence and none of its private inputs may be ported.
- Freeze and evaluate the public port on candidate Red/White seeds 1-100. Keep it only if it materially beats the 2.22-round greedy floor without truncations or policy errors, then reproduce the unchanged policy through a fresh real Balatro schema-v5 trace.
- Commit `7a8cc74` passed that retention gate. Its clean isolated candidate panel completed 100/100 episodes without truncation or policy error at 100.84 decisions/s, averaging 6.95 rounds versus greedy's 2.22; it still won 0/100. The unchanged seed-1 policy then reproduced 23/23 schema-v5 transitions in real Balatro and lost at ante 1.
- A 10-card hand exposed noncanonical discard ordering and an out-of-proposal tactical choice; selections are now increasing and strategic tactics optimize strictly within the 512 transported public actions. Commit `9840961` orders the unchanged complete legal set largest-first so the bound includes strategically useful five-card actions. Its clean candidate panel completes 100/100 at 101.50 decisions/s, averages 7.29 rounds and 2.50 ante, and still wins 0/100. The unchanged seed-1 policy reproduces 23/23 real Balatro transitions exactly and loses at ante 1.

### Active Increment: Strategic Value Learning

- Reuse the existing public recurrent model, isolated environment worker, evaluator, and PPO loop. Do not add a second dataset format, replay service, model family, or private simulator callback.
- Bootstrap only `SHOP` and `PACK` decisions from the frozen `PublicStrategicPolicy`; fixed public tactical control continues to own blind flow and hand play because the earlier model failed to recover that deterministic floor.
- Resume the strategic checkpoint with on-policy `public_blind_clear_v1` returns. The learned policy owns only shop and pack actions; episode seeds remain environment-driver inputs and never become observation, history, feature, reward, or recurrent-state fields.
- Training metrics, imitation accuracy, and candidate loss reductions are diagnostics. Keep the learner only if its frozen evaluation on disjoint Red/White seeds beats the 7.29-round strategic floor or records a complete win; validate any retained policy unchanged through real Balatro lockstep.
- Commit `ccca3e4` implements that bounded path. A clean 200-episode strategic bootstrap reaches 86.96% sampled shop/pack imitation accuracy, but its frozen seeds 1-100 evaluation averages only 6.84 rounds with 0 wins. A 20,480-step public-return PPO continuation recovers to 7.03 rounds with 0 wins, still below the 7.29 teacher. This closes imitation and PPO tuning as failed strength paths.

### Active Increment: Public Joker-Aware Tactics

- Fix the public tactical surrogate before training another strategic model. Only cards that actually score contribute card chips, enhancements, and editions; selected kickers no longer create imaginary score.
- Apply deterministic joker effects sequentially in visible joker order using public semantic keys and public state. Start with fixed hand-family effects, visible money/discard/deck-count effects, card-rank/suit effects, and editions. Do not parse locale-dependent tooltip prose or invent hidden scaling counters.
- For scaling jokers whose accumulated value is not yet structured, model only the action-dependent public delta: Runner gains on Straights, Spare Trousers on Two Pair/Full House, and Square Joker on four-card hands. Their unknown current constant must not be guessed.
- Keep the patch only if the frozen Red/White seeds 1-100 panel materially beats 7.29 rounds or produces a complete win, then replay the unchanged policy through real Balatro lockstep.
- Commit `cf324f6` passes the retention threshold: its clean frozen panel completes 100/100 episodes at 96.98 decisions/s, average round rises from 7.29 to 7.86 and average ante from 2.50 to 2.67. Seed 63 reaches ante 7 instead of ante 6. The unchanged seed-1 policy reproduces 23/23 real Balatro transitions exactly and loses at ante 1. This is the new honest floor, not a solve: it still wins 0/100.

### Active Increment: Replacement-Aware Joker Slots

- Fix the smallest directly observed strategic dead end: a full joker area currently makes every better shop Joker disappear from the legal buy set, so the policy never upgrades. On candidate seed 63 it kept Business Card, Blue Joker, Banner, and Runner while passing on The Order at ante 6, then died at ante 7.
- Starting at ante 6, inspect only the visible shop offers and owned public Joker descriptors. If the best affordable visible Joker exceeds the weakest sellable owned Joker by a fixed material margin, sell that owned Joker; on the next public decision the existing buy path purchases the still-visible offer. Permit at most one such replacement per run. Earlier and repeated replacement churn is excluded because the first bounded panel regressed after selling Banner in ante 2, and the seed-63 probe later tried to replace Banner with the build-incompatible Idol after correctly acquiring The Order.
- Count the sale against the existing bounded shop-action budget, require purchase affordability after the visible sell proceeds, and never sell an Eternal Joker. If no material replacement is visible, preserve the current behavior.
- Do not enable selling during an open pack, synthesize a combined sell-and-buy action, reserve a slot speculatively, parse tooltip prose, or add private candidate state. Pack-time selling is still outside the current verified public action contract.
- Keep the patch only if hidden-twin and explicit replacement tests pass and a frozen Red/White seeds 1-100 panel beats the 7.86-round floor or records a complete win. Any retained policy then runs unchanged through a clean real Balatro differential trace that reaches the replacement action when feasible.
- The dirty development panel passes that gate: 100/100 runs complete, average round rises from 7.86 to 7.89, and seed 63 clears ante 8 after replacing Business Card with The Order. This is candidate-only evidence from an unfrozen revision; commit, clean rerun, and exact real Balatro replay remain mandatory.

### Active Increment: Win-Boundary Integrity

- Candidate-only evidence originally led to a false compatibility rule that forced an ante-8 clear directly to `GAME_OVER`. The completed real seed-63 trace corrects the contract: Balatro returns `ROUND_EVAL`, increments to ante 9, and sets `won=true`. Cashing out opts into Endless Mode; it is not required to establish the win.
- Remove the candidate-only terminal conversion and the suppression of ante advancement. Make the authority runner treat the first settled public observation with `won=true` as a complete terminal result, before any cash-out or Endless action. Losses remain complete only at `GAME_OVER`.
- Add a runner regression for `ROUND_EVAL` plus `won=true`, replay the completed diagnostic trace through the corrected candidate to verify the winning transition, then capture a fresh trace that closes immediately at the win. A solve trace must end at that boundary and pass exact differential replay; post-win Endless transitions are outside the run being evaluated.
- Historical candidate panels that used the false forced-`GAME_OVER` state are retained only as strategy-development evidence. Rerun the frozen panel under the corrected terminal contract before quoting its outcome metrics at the new revision.
- The corrected candidate now matches the completed diagnostic authority trace through the win transition and 27 further optional Endless transitions: 240 transitions are exact. The next mismatch is an Endless-only deck-capacity difference at transition 241. This is useful simulator work later, but it is outside the declared run endpoint; the next clean trace must stop at the already-exact `won=true` boundary.
- A fresh clean trace does stop at that boundary after 212 decisions, and every recorded transition matches. The differential gate still rejects it only because its final assertion hardcodes `state=GAME_OVER`; update that assertion to accept either `GAME_OVER` or canonical `won=true`, while continuing to require an exact complete authority trace and exact final canonical transition.

### Active Increment: Empty-Shop Authority Settling

- A frozen seed-63 authority replay reached ante 7 twice, then failed deterministically after using a held Planet and attempting to buy the final remaining shop Planet. Both 40-poll and 200-poll runs ended `unsettled` because the backend rejects every shop whose card, pack, and voucher areas are all empty.
- Keep fresh-shop and reroll settling strict: an empty shop can be a transient animation state and must not be accepted merely because two polls match.
- Permit an empty shop only when the preceding canonical state plus public action proves that the last known offer was consumed: buying the sole remaining shop card or voucher while the other offer areas were already empty, or returning from a pack whose persisted shop areas were already empty. Once that empty shop is canonically established, normal use, sell, and leave actions may remain there; rerolls still require visible generated offers.
- Add positive and negative settling regressions, then retry the frozen seed-63 authority run. The two incomplete traces remain failure diagnostics and never count as evidence.

### Active Increment: Vanilla Mega-Pack Endpoint Completion

- The frozen seed-63 authority replay now reaches ante 8 and opens a Mega Standard Pack, but its first public pack selection times out after Balatro accepts the card. The authority log has no Lua error and shows `G.FUNCS.use_card` ran; the endpoint response condition never becomes true.
- Fix the pinned BalatroBot endpoint at the root cause. Capture the public pack state before `G.FUNCS.use_card`; when a multi-choice pack decrements `pack_choices` by one, require the same state to be restored, a live pack area, and `G.STATE_COMPLETE`. This follows Balatro's own `use_card` contract and covers vanilla and SMODS pack states without admitting unrelated states.
- Add a regression that opens a vanilla Mega Standard Pack, verifies the first selection returns in `STANDARD_PACK` with the pack still open, and verifies the second selection closes back to `SHOP`. Do not solve this with a longer transport timeout, an unconditional response, or a policy-side pack skip.
- Regenerate the tracked authority patch digest, commit the authority fix, and rerun the unchanged frozen seed-63 policy. The run counts only if it reaches `run_end` and differential replay reports zero mismatches, zero unchecked transitions, and zero waivers.

### Active Increment: Joker Stencil Runtime State

- The patched authority completed the frozen seed-63 run with `won=true`, but differential replay stopped at transition 71. In the ante-4 shop, Balatro's visible Joker Stencil had runtime `enhancement_x_mult=0`; Jackdaw emitted the same Joker without that field.
- Mirror vanilla `Card:update` in the existing candidate compatibility refresh. For every owned, shop, and pack Joker Stencil, set runtime `ability.x_mult` to `joker_slots - owned_joker_count + owned_stencil_count` before serialization. Preserve zero because it is a real visible runtime value; do not erase it in canonicalization or add a parity waiver.
- Add focused full-slot and owned-Stencil regressions, rerun the project suite, then replay the already-complete authority trace without launching Balatro. Continue stop-on-first-mismatch until the entire winning trace is exact.
- The Stencil runtime correction moves the stop-on-first-mismatch boundary from transition 71 to transition 202.

### Active Increment: Open-Pack Capacity

- With Joker Stencil fixed, the completed seed-63 trace matches through 201 transitions. After the first Mega Standard selection, both kernels retain four offers, but Balatro keeps the pack area's original `limit=5` while the candidate rewrites the limit to the remaining count of four.
- Track the active candidate pack list by object identity and capture its size when the pack opens. Preserve that capacity while selections mutate the same list; clear it when the pack closes, and replace it when a queued/new pack installs a new list. Pass the tracked value into bridge normalization instead of deriving capacity from the shrinking offer count.
- Add a focused normalization/tracking regression, rerun the suite, and replay the same immutable authority trace. Do not canonicalize `limit` away: it is visible UI capacity and affects observation equality.
- Preserving the active pack capacity moves the mismatch boundary from transition 202 to the previously incorrect win-boundary compatibility at transition 212.

## Design

Use a two-kernel architecture. Actual Balatro under a pinned BalatroBot/LÖVE build is the authority. A pinned, independently audited Jackdaw fork is the candidate high-throughput training/search kernel. Expose the same typed state/action contract from both and continuously compare organic trajectories. In parallel, prototype in-memory snapshot/restore and batch rollouts inside real Balatro; use the real kernel directly wherever its measured throughput permits.

Keep privileged state behind a process boundary. The deployed policy and online search receive only `PublicObservation` plus public action/observation history. They never receive the run seed, shuffled deck order, future RNG, private object identifiers, or a clone of the live hidden state. Fair search creates belief particles consistent with public history and samples unknown events from the correct conditional distribution.

The system has five layers:

1. Public/private contract: an observation firewall, typed visible action candidates, public history, private canonical state, and adversarial hidden-state-twin tests.
2. Dual environment: real Balatro authority plus a differentially certified fast candidate, both exposing reset, action, settle, observation, terminal outcome, and event trace.
3. Search: belief-state planning over hidden information, exhaustive tactical action generation where affordable, and sampled strategic rollouts for shops, packs, skips, and consumables.
4. Learning: policy and distributional value networks trained by expert iteration from belief-averaged search targets, with item/card/joker instances represented compositionally rather than by one flat linear ranker.
5. Evaluation: frozen agents, evaluator-secret seeds generated after freeze, immutable traces, confidence intervals, and direct comparison with human and program baselines across decks and stakes.

## Acceptance Standard

- No debug mutation endpoints and no injected state.
- Policy input and search contain no seed, hidden deck order, future shop contents, actual RNG state, or hidden-state-dependent legal-action leak.
- Every reported agent is identified by code revision, configuration, model digest, game/mod versions, and seed manifest.
- Every benchmark declares its profile mode. The canonical benchmark uses the normal fully-unlocked card pool; ambient career-profile unlock history is never an implicit input.
- Promotion metrics come only from authoritative-engine or clean live runs of that exact frozen artifact.
- The final superhuman claim requires a predeclared benchmark over all 15 standard decks at Gold stake, evaluator-secret seeds, enough games for simultaneous confidence bounds, and performance exceeding a preregistered elite-human reference under the same rules and information.

## Build Order

### 1. Prove the information boundary and environments

- Implement explicit `PublicObservation`, `PrivateState`, `PublicActionCandidate`, and public-history types before policy work.
- Add public-twins tests: changing only inaccessible hidden state must not change policy input, visible legal candidates, or the action distribution.
- Pin and audit Jackdaw instead of building another independent simulator from scratch.
- Prototype BalatroBot in-memory snapshots and batched real-game rollouts using the game's own save representation; verify snapshot/RNG fidelity before using it for search.
- Build an organic differential corpus from real public-action traces and require exact next-state agreement for the complete canonical semantic state, not a hand-selected projection.
- Make unsupported actions or state fields fail closed. There are no waivers in acceptance traces.

Exit criterion: randomized action-sequence differential tests pass on a broad source-derived state/action coverage matrix, including stochastic branches and persistent card/joker state; the observation firewall passes adversarial leakage tests; throughput is measured under the intended belief-search workload.

### 2. Establish honest baselines

- Random legal agent.
- Greedy immediate-score tactical agent.
- Handcrafted search baseline with no learned value.
- Human-reference benchmark collected under the same observation and seed rules.

Exit criterion: every baseline is reproducible from a frozen artifact and evaluated on separate development and test seed manifests.

### 3. Build search before learning

- Enumerate or beam-search tactical play/discard actions with the authoritative kernel.
- Use root-sampled POMCP, stochastic MCTS, or sampled expectimax for hidden shops, packs, tags, and draws.
- Share determinizations across sibling actions to avoid optimism bias.
- Recondition the particle belief after every public observation; never clone or inspect the actual live hidden state for a deployed decision.
- Search complete run actions, including selling, ordering, targeting, rerolling, skipping, and multi-pick packs.

Exit criterion: search materially beats the handcrafted baseline on held-out authoritative runs and transfers unchanged to clean live execution.

### 4. Add learned policy and value models

- Encode card and joker instances, consumables, vouchers, blinds, tags, and typed action candidates with embeddings, modifiers, counters, order, targets, and set/graph structure. Include Gold-stake mechanics in the schema from the start.
- Train a policy prior from belief-averaged search visit counts and a calibrated distributional survival/win head from authoritative outcomes.
- Use expert iteration/self-generated play; retain hard states from live and authoritative evaluations for regression and targeted replay.
- Calibrate the value model by ante, stake, deck, and build archetype before allowing it to prune search aggressively.

Exit criterion: the learned-search agent beats search alone on a locked held-out suite without increasing live/authoritative disagreement.

### 5. Curriculum and final evaluation

- Red/White is an engineering smoke test, then train across decks and stakes; do not treat White success as strategic promotion evidence.
- Increase each stake's training weight only after its authoritative coverage exists; Gold-stake mechanics remain present in the observation and model schema from the start.
- Lock architecture and hyperparameters before the final Gold-stake benchmark.
- Generate the sealed final seed manifest only after the artifact is frozen, run one attempt per condition, and publish all traces, failures, model metadata, compute limits, and confidence intervals.

Exit criterion: the frozen agent clears the predeclared superhuman benchmark across all decks at Gold stake.

## Kill Criteria

- Stop policy work if authoritative and live outcomes diverge for any agent-relevant transition.
- Stop if changing only private state changes a deployed decision.
- Stop if search receives the live seed, hidden deck order, actual future RNG, or a private clone.
- Stop training if improvements appear only in a surrogate environment.
- Reject a milestone if the evaluated policy changed during the seed sweep.
- Reject parity or coverage metrics based only on identifier presence, shape checks, tolerated mismatches, or waived behavior.
- Replace the environment approach if it cannot clone/step fast enough for useful search without changing game semantics.

## First Milestone

The public/private contract, no-waiver replay loop, extended-action lane, process isolation, real-kernel snapshot benchmark, and public recurrent-training path are complete. The fair strategic baseline now has one exact real win and a 1/100 clean candidate win rate. The immediate milestone is a public-only action-value/search teacher that turns this isolated solve into broad multi-seed strength; further blind PPO or imitation tuning is explicitly rejected.

### Completed Negative Probe: Quick Action-Value Scalability

- Test the smallest falsifiable version before building the full recurrent action-value trainer. Before each episode, use an experiment RNG independent of the game seed to draw a bounded SHOP/PACK root index and an action nonce, run the frozen `PublicStrategicPolicy`, replay the selected public prefix exactly, randomize one legal action at that root, and then return control to the baseline. This covers both early and late SHOP/PACK states without selecting on the episode's hidden future or cloning live state.
- The sample contains only the public observation, public previous action, public candidates, the frozen base model's public-history hidden tensor, chosen action, behavior probability, and the next three public blind clears; it contains no seed, candidate state, snapshot, RNG state, or counterfactual branch. Stop the branch after three clears or normal terminal so this probe tests a dense short-horizon signal rather than being blocked by unrelated unimplemented late-game public affordances.
- Reuse an existing `PublicRecurrentPolicyValue` checkpoint. Freeze the observation encoder, action encoder, recurrent cell, and value head; reset only `policy_head` from the same training seed for every slice so obsolete PPO logit scale cannot saturate the regression, then train that head against the next-three-clear target divided by three. Do not add a second model family or modify deployed checkpoint semantics for this disposable probe.
- Train from identical initialization on nested sample counts and evaluate every frozen scorer on one untouched paired seed panel, intervening at the same single public decision. Compare average round, average ante, win count, and paired per-seed round deltas against the unchanged baseline.
- The probe succeeds only if held-out outcome improves with additional samples, the largest model beats the baseline on paired average round, all episodes terminate cleanly, and a shuffled-target negative control fails. Prediction loss without policy improvement is a failure.
- Keep the experiment candidate-only and provenance-rich. If it succeeds, replace the probe with the full recurrent public Monte Carlo Q pipeline; if it fails, delete the probe instead of tuning it into another training framework.

The probe is complete and does not pass its scale gate. A candidate-only run collected 1,024 exact public interventions from 1,407 attempted Red/White episodes in 557.9 seconds: 967 SHOP roots, 57 PACK roots, and next-three-clear targets distributed as 154 zero, 116 one, 123 two, and 631 three. Held-out Huber loss on 256 new interventions improved monotonically from 0.0722 at 128 samples to 0.0669 at 1,024, but the shuffled-target control reached 0.0682 because most states clear all three blinds regardless of the selected action. The representation can fit public survival context, but the target is only weakly action-sensitive.

Policy outcomes reject the scaling claim. On seeds 60001-60100, the frozen strategic baseline averaged 7.17 rounds; the 128/256/512/1024 models averaged 3.44/6.85/7.54/7.17, and the shuffled control averaged 3.43. The post-hoc 512 peak had a paired round-delta confidence interval spanning zero. On the untouched replication seeds 61001-61200, the predeclared 1,024-sample model averaged 7.125 rounds versus 7.295 for the baseline, a paired delta of -0.17 with bootstrap 95% interval [-0.74, 0.40]; both won 0/200. Do not scale this frozen-encoder/three-blind objective or call its decreasing prediction loss strategic progress. The disposable probe implementation and tests are deleted after recording the result.

Unbounded exploration also exposed a real public-contract gap before the target was narrowed. Candidate seed 50455, root 9, publicly sold Loyalty Card and later reached Cerulean Bell; the public legal-action surface allowed a five-card play that omitted the visibly forced card, and Jackdaw rejected it with `Forced card (Cerulean Bell) must be in the selection`. The forced public hand slot is currently absent from `PublicObservation`. Fix that schema/action-legality root cause before any full-horizon learner or broader exploratory campaign.

- Cerulean contract repair: preserve BalatroBot's visible forced-selection marker as a typed required hand slot, reject malformed or non-visible markers at the adapter boundary, and require that slot in every public play, discard, and hand-targeting consumable action. The missing marker was a Jackdaw bridge representation bug: empty card state arrived as `[]`, so normalization never added the visible forced marker. Normalize both empty-list and object forms without exposing identity, require exactly one marker while Cerulean Bell is active, and fail closed otherwise. Codec, hidden-twin, legality, adapter, and bridge regressions pass (61 focused tests); exploration may resume only under this corrected contract.
