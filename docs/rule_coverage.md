# Rule Coverage

The target is full Balatro rule coverage in the local simulator. BalatroBot is
for validation and real-game execution, not training rollouts.

## Current Implemented Coverage

- Standard 52-card deck.
- Seeded shuffle/draw.
- Base poker hand classification.
- Base hand score chips/mult.
- Source-derived hand level chip/mult increments.
- Deterministic played-card enhancement/edition scoring:
  Bonus, Mult, Wild as suit support placeholder, Glass, Gold, Foil,
  Holographic, Polychrome.
- Initial deterministic additive joker scoring:
  Joker, Greedy/Lusty/Wrathful/Gluttonous Joker, Jolly/Zany/Mad/Crazy/Droll,
  Sly/Wily/Clever/Devious/Crafty, Half Joker, Even Steven, Odd Todd, Scholar.
- Run/economy scaffold:
  blind selection phases, small/big/boss blind order, ante progression,
  white-stake blind score multipliers, base blind rewards, hand bonus,
  interest cap, reroll cost growth, deterministic placeholder shop population.
- Minimal blind hand/discard loop.
- Fixed action ids and legal masks for tactical training.

## Required Full Coverage

- Remaining card modifier behavior:
  Steel held-in-hand scoring, Lucky min/exact/max, Stone hand classification
  parity, seals, glass destruction.
- Joker trigger pipeline and every vanilla joker.
- Consumables: Tarot, Planet, Spectral.
- Shop generation, packs, buys, sells, rerolls, pricing.
- Money, interest, rewards, and economy effects.
- Vouchers.
- Tags.
- Boss blinds and stake modifiers.
- Deck/back modifiers.
- Ante progression and blind score scaling.
- Source-compatible seeded RNG streams.

## Process

1. Extract rule object inventory from the local Lua dump.
2. Implement one rule family at a time in `balatro_ai_v2.fast`.
3. Add local deterministic tests.
4. Add BalatroBot validation fixtures for real-game parity.
5. Keep training rollouts entirely local.

Run the local coverage counter:

```bash
python scripts/rule_coverage_report.py
```
