# Current Checkpoint

Date: 2026-06-10 (evening)

## Architecture: planner core

Strategy lives in `balatro_ai_v2/planner/` — online planning with the fast
simulator as world model in both evaluation paths:

- `evaluation.py` — `run_value()`: projected best-hand capability (4 sample
  hands from the persistent deck, scored over structured candidate masks
  with current jokers + levels) against the boss-aware requirement curve,
  plus economy/scaling/build/consumable-hold terms. Decaying jokers
  (Seltzer, Ice Cream, Popcorn, Turtle Bean) carry negative scaling rates.
- `tactics.py` — in-blind beam search (exact scoring).
- `core.py` — shop/pack/blind by rollout expectimax. Rollouts use
  `rollout_play_action` (structured candidate masks: all 5-card picks +
  rank groups; verified lossless vs full enumeration on 300 hands).
  Hidden-information candidates (reroll, blind skip) carry a flat optimism
  penalty: determinized rollouts SEE the sampled shop/tag, so E[max] >
  max[E] versus visible purchases.
- `mirror.py` — live state -> env; unsafe shop jokers priced 999, unsafe
  PACK jokers banned via `pack_banned_indices` (a free pack pick of Ramen
  slipped through pricing once), mega-pack picks from `highlighted_limit`.
- `live_policy.py` — planner-driven live play; targeted tarots and
  hand-required spectrals (Familiar/Grim/Incantation/Ouija/Sigil) spent
  in-blind; `suppressed_consumables` for repeated live refusals.

Speed: mean decision 0.14s, worst 0.3s through ante 6 (was 30-90s stalls).

## Scoring engine (live-verified trigger order)

1. card phase — per scoring card: enhancement/edition, then every joker's
   per-card trigger L2R; retriggers (Dusk, Hack, Sock and Buskin, Hanging
   Chad, Seltzer) re-fire base chips + enhancements + joker card-triggers,
   editions once.
2. held phase — held cards trigger ONE AT A TIME in hand order; each card
   fires every joker's held effect before the next card. A Baron king
   sorted left of a Shoot the Moon queen multiplies BEFORE the +13 —
   verified to the chip against live seed 17 (3007 and 4148 exact). Mime
   retriggers per held card.
3. joker phase — each joker once L2R, additive and x-mult IN ORDER,
   edition at each joker's turn. Blueprint/Brainstorm resolve to their copy
   target (copier keeps own edition/sell value; passives uncopyable).

Canonical joker order: additive jokers, then copiers, then x-mult tail;
env auto-sorts and live policy issues `rearrange`.

## Joker coverage: 136/150

All deterministic, representable jokers are implemented, including the
event/economy layer (Burglar, Chicot, Riff-Raff, Cartomancer, Turtle Bean,
DNA, Sixth Sense, Superposition, Seance, Vagabond, Rough Gem, Matador,
To Do List, Burnt, Trading, Mail, Faceless, Gift, Diet Cola, Mr. Bones,
Ring Master) and seeded-random creators (visible-after-creation = parity
safe). Permanently excluded (probabilistic triggers or per-card state the
int-card env cannot represent): 8 Ball, Business, Space, Oops,
Hallucination, Reserved Parking, Invisible, Perkeo, Certificate, Hiker,
Ticket, Midas Mask, Marble, Luchador. Live-unsafe (never bought/picked):
Bloodstone, Ramen, Raised Fist.

Consumables: 52/52 usable. Fool/Soul/Familiar/Grim/Incantation modeled;
enhancement/seal tarots are live-spent in-blind and carry hold value in
run_value (their effects are not representable on int cards: undervalue
only).

## Verified results

Fast sim (Red/White, seeds 1-20 tune): 30-45% across eval runs on the
corrected engine (±2 wins run-to-run noise at n=20). Retune toward the
50% target is the open strength lever; x-mult acquisition priority is the
visible gap (deaths cluster at ante 5-7 with additive-heavy boards).

Live (Red/White, `--planner`): **M3 MET — two ante-8 wins with clean
gates**: seed 17 (planner_live_seed17_20.jsonl) and seed 38
(planner_live_seed36_39.jsonl), both passing
`game_parity_gate.py --require-complete` with 0 mismatches. Every active
trace seeds 1-39 gates clean. Late triage discoveries, each verified to
the chip against live scores: held STEEL x1.5, Supernova counters never
threaded (scored zero in sim AND replay), Spare Trousers ability key,
red-seal retriggers, display-order "first card" for Hanging
Chad/Photograph, Misprint banned (random 0-23 mult), Boss Tag reroll
desyncs the displayed boss from active rules (policy never skips into
one), The Serpent's draw-3.

Async-lag defenses in the runner: shop-settle polling, pack-cards polling,
hand-settle polling, swallowed-action re-polls, "cannot be used at this
time" refusal suppression (3 strikes per round).

Tests: 328 passing.

## Known gaps / next work

1. Weight retune on the corrected engine (~35% tune vs 50% target);
   x-mult acquisition priority is the candidate lever.
2. Targeted tarots in packs opened outside a blind remain unusable
   (BalatroBot exposes no targeting hand) — skipped by design.
3. Hidden-info penalty (250) is a first-order bias correction; a proper
   fix would share determinization samples across candidates.
4. Phase 6 cleanup (M4): delete legacy value tables/skip rules, dedupe
   tactical_planner helpers into fast/, deprecate the imitation path.
