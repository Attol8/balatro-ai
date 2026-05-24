from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.balatrobot.client import BalatroBotClient, BalatroBotError
from balatro_ai_v2.balatrobot.policy import BalatroBotPolicy
from balatro_ai_v2.balatrobot.policy_config import PolicyConfig, ShopPolicyConfig, TacticalPolicyConfig, load_policy_config
from balatro_ai_v2.balatrobot.runner import evaluate_balatrobot


def main() -> None:
    parser = argparse.ArgumentParser(description="Black-box search policy configs through clean BalatroBot runs")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12346)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--max-steps", type=int, default=800)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--trials", type=int, default=12)
    parser.add_argument("--search-seed", type=int, default=1)
    parser.add_argument("--baseline-config", type=Path)
    parser.add_argument("--output-jsonl", type=Path, default=Path("runs/balatrobot_policy_search.jsonl"))
    args = parser.parse_args()

    client = BalatroBotClient(host=args.host, port=args.port, timeout=args.timeout)
    try:
        client.health()
    except BalatroBotError as exc:
        raise SystemExit(f"BalatroBot is not reachable at {client.url}: {exc}") from exc

    seeds = [str(seed) for seed in range(args.seed_start, args.seed_start + args.seeds)]
    rng = random.Random(args.search_seed)
    configs = [load_policy_config(args.baseline_config)]
    configs.extend(_sample_config(rng) for _ in range(max(args.trials - 1, 0)))

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    for trial, config in enumerate(configs):
        metrics = evaluate_balatrobot(
            seeds,
            client=client,
            policy=BalatroBotPolicy(config=config),
            deck=args.deck,
            stake=args.stake,
            max_steps=args.max_steps,
        )
        row: dict[str, Any] = {
            "trial": trial,
            "seeds": seeds,
            "deck": args.deck,
            "stake": args.stake,
            "config": asdict(config),
            "metrics": metrics,
        }
        with args.output_jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
        print(
            f"trial={trial} wins={metrics['wins']}/{metrics['seeds']} "
            f"avg_ante={metrics['avg_ante']} avg_steps={metrics['avg_steps']}"
        )


def _sample_config(rng: random.Random) -> PolicyConfig:
    return PolicyConfig(
        tactical=TacticalPolicyConfig(
            beam_width=rng.choice((48, 96, 160, 224)),
            action_beam=rng.choice((24, 48, 80, 120)),
        ),
        shop=ShopPolicyConfig(
            min_value_margin=rng.choice((0.0, 1.0, 2.0, 4.0)),
            modeled_joker_fallback_value=rng.choice((6.0, 10.0, 14.0)),
            valuable_no_target_consumable_value=rng.choice((8.0, 12.0, 16.0, 22.0)),
            high_priestess_min_money=rng.choice((10, 14, 18, 999)),
            planet_played_base_value=rng.choice((12.0, 18.0, 24.0)),
            planet_played_increment=rng.choice((3.0, 6.0, 9.0)),
            planet_common_unplayed_value=rng.choice((6.0, 12.0, 18.0)),
            planet_unplayed_value=rng.choice((0.0, 4.0, 8.0)),
            joker_value_overrides=_sample_joker_overrides(rng),
        ),
    )


def _sample_joker_overrides(rng: random.Random) -> tuple[tuple[str, float], ...]:
    keys = ("j_bull", "j_bootstraps", "j_stuntman", "j_blue_joker", "j_abstract", "j_joker")
    return tuple((key, rng.choice((8.0, 14.0, 20.0, 28.0, 36.0, 44.0))) for key in keys if rng.random() < 0.5)


if __name__ == "__main__":
    main()
