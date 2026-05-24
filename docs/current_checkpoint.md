# Current Checkpoint

Date: 2026-05-24

## Stable State

The fast gym has moved from tactical-only play/discard training to explicit
full-run actions:

- blind select and skip
- cash out and next round
- shop reroll
- buy shop card, pack, and voucher
- sell joker
- use consumable
- pack select and skip

The fast shop is deterministic and training-oriented. It now includes weighted
joker/planet shop cards, booster spec costs/sizes/choices, persistent voucher
offers, rerolls, discounts, extra hands/discards/slots, economy vouchers, and
pack choices that fit the current 8-card tactical action encoding.

## Verified Results

Full test suite:

```bash
python -m pytest
```

Result: 172 passed.

Fast full-action smoke with voucher shop expansion:

The scratch files from this smoke were intentionally removed after recording the
metrics, so these commands are a historical reproduction recipe rather than live
inputs for future runs.

```bash
python scripts/generate_fast_oracle_data.py --deck b_red --seed-start 1 --seeds 4 --max-steps 80 --output-jsonl runs/fast_full_action_voucher_oracle_smoke.jsonl
python scripts/train_fast_imitation_policy.py --data-jsonl runs/fast_full_action_voucher_oracle_smoke.jsonl --output-model runs/fast_full_action_voucher_linear_smoke.json --model-type linear --epochs 2
python scripts/evaluate_fast_imitation_policy.py --model runs/fast_full_action_voucher_linear_smoke.json --deck b_red --seed-start 1 --seeds 4 --max-steps 80
```

Result: 320 examples, 0 terminal wins, 0.7125 training accuracy, 0 real wins,
5.75 average fast-gym rounds cleared.

Visible BalatroBot replay of that trained model:

The trace and smoke model from this run were also intentionally removed after
recording the metrics. Future BalatroBot tests should generate fresh traces from
the current adapter and policy.

```bash
python scripts/run_balatrobot_agent.py --launch-server --fast-server --no-headless-server --deck RED --stake WHITE --seed-start 1 --seeds 1 --max-steps 250 --poll-delay 0.05 --trace-jsonl runs/red_deck_seed1_visible_policy_try.jsonl --imitation-model runs/fast_full_action_voucher_linear_smoke.json
python scripts/game_parity_gate.py runs/red_deck_seed1_visible_policy_try.jsonl
```

Result: 0 wins, ante 1, 18 steps. Parity gate checked 18/18 transitions, 5
scores, and 6 draws with 0 mismatches and 0 unchecked transitions.

## Important Interpretation

The fast trained-policy result did not reproduce as policy strength in
BalatroBot. The reason is not an observed parity mismatch in the visible trace.
The reason is a policy-contract mismatch:

- fast evaluation used a full-action model inside `FastFullGameEnv`
- live BalatroBot used the model only for tactical play/discard decisions
- live blind, shop, voucher, and pack decisions still used the heuristic
  BalatroBot planners

Therefore, fast-gym average rounds are not valid solve evidence until the same
full-action policy is replayed through BalatroBot phase by phase.

## Next Required Work

Implemented full-action model replay through BalatroBot after this checkpoint
was written:

1. Live observations now use the same full-run layout as `FastFullGameEnv`.
2. Legal fast action ids are built for blind, round-eval, shop, pack, and
   tactical phases.
3. Predicted full-action ids are converted into `GameAction` RPCs.
4. `scripts/run_balatrobot_agent.py` accepts `--full-action-model`.
5. Visible BalatroBot replay was run with a scratch full-action model.

Visible full-action replay result:

```bash
python scripts/run_balatrobot_agent.py --launch-server --fast-server --no-headless-server --deck RED --stake WHITE --seed-start 1 --seeds 1 --max-steps 250 --poll-delay 0.05 --trace-jsonl /private/tmp/red_deck_seed1_full_action_visible.jsonl --full-action-model /private/tmp/balatro_full_action_model.json
python scripts/game_parity_gate.py /private/tmp/red_deck_seed1_full_action_visible.jsonl
```

Result: 0 wins, ante 1, 16 steps. The model selected blinds, cashed out, bought
a voucher, advanced to the next round, and chose tactical play/discard actions.
Parity checked 16/16 transitions, 5 scores, and 6 draws with 0 mismatches and 0
unchecked transitions.

The replay contract now exists, but policy quality is still poor. The next
useful work is to compare fast and live action choices on the same seed and fix
remaining observation/action mismatches before improving oracle search or
training quality.
