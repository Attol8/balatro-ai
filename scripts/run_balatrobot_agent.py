from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.balatrobot.client import BalatroBotClient, BalatroBotError
from balatro_ai_v2.balatrobot.policy import BalatroBotPolicy
from balatro_ai_v2.balatrobot.policy_config import load_policy_config
from balatro_ai_v2.balatrobot.runner import evaluate_balatrobot
from balatro_ai_v2.balatrobot.tracing import JsonlTraceWriter


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the red-deck agent through BalatroBot")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12346)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=800)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--trace-jsonl", type=Path)
    parser.add_argument("--trace-compact", action="store_true")
    parser.add_argument("--policy-config", type=Path)
    args = parser.parse_args()

    client = BalatroBotClient(host=args.host, port=args.port, timeout=args.timeout)
    try:
        client.health()
    except BalatroBotError as exc:
        raise SystemExit(f"BalatroBot is not reachable at {client.url}: {exc}") from exc
    seeds = [str(seed) for seed in range(args.seed_start, args.seed_start + args.seeds)]
    policy = BalatroBotPolicy(config=load_policy_config(args.policy_config))
    trace_writer = (
        JsonlTraceWriter(args.trace_jsonl, include_states=not args.trace_compact)
        if args.trace_jsonl is not None
        else None
    )
    metrics = evaluate_balatrobot(
        seeds,
        client=client,
        deck=args.deck,
        stake=args.stake,
        max_steps=args.max_steps,
        trace=args.trace,
        policy=policy,
        trace_writer=trace_writer,
    )
    for key, value in metrics.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
