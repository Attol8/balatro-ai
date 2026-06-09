from __future__ import annotations

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.fast.full_game import (
    FastFullGameEnv,
    RolloutSearchRunAgent,
    SearchRunAgent,
)


def _build_agent(name: str):
    if name == "search":
        return SearchRunAgent()
    if name == "rollout":
        return RolloutSearchRunAgent()
    if name == "planner":
        from balatro_ai_v2.planner import PlannerAgent

        return PlannerAgent()
    raise ValueError(f"unknown agent: {name}")


def _eval_seed(spec: tuple[str, str, int, int]) -> dict[str, float | int | bool]:
    agent_name, deck_key, seed, max_steps = spec
    agent = _build_agent(agent_name)
    env = FastFullGameEnv(deck_key=deck_key)
    env.reset(seed=seed)
    started = time.perf_counter()
    terminated = False
    steps = 0
    while not terminated and steps < max_steps:
        result = env.step(agent.act(env))
        terminated = result.terminated
        steps += 1
    return {
        "seed": seed,
        "won": env.won,
        "rounds_cleared": env.rounds_cleared,
        "ante": env.run.ante,
        "steps": steps,
        "wall_time_s": round(time.perf_counter() - started, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a fast full-game agent")
    parser.add_argument("--deck", default="b_red")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=32)
    parser.add_argument("--max-steps", type=int, default=600)
    parser.add_argument("--agent", choices=("search", "rollout", "planner"), default="search")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    specs = [
        (args.agent, args.deck, seed, args.max_steps)
        for seed in range(args.seed_start, args.seed_start + args.seeds)
    ]
    if args.workers > 1:
        with Pool(args.workers) as pool:
            rows = pool.map(_eval_seed, specs)
    else:
        rows = [_eval_seed(spec) for spec in specs]

    seed_count = len(rows)
    wins = sum(int(row["won"]) for row in rows)
    summary = {
        "agent": args.agent,
        "deck": args.deck,
        "max_steps": args.max_steps,
        "seeds": seed_count,
        "wins": wins,
        "win_rate": wins / max(seed_count, 1),
        "avg_rounds_cleared": sum(row["rounds_cleared"] for row in rows) / max(seed_count, 1),
        "avg_steps": sum(row["steps"] for row in rows) / max(seed_count, 1),
        "total_wall_time_s": round(sum(row["wall_time_s"] for row in rows), 2),
    }
    for row in rows:
        print(
            f"seed {row['seed']}: won={row['won']} rounds={row['rounds_cleared']} "
            f"ante={row['ante']} steps={row['steps']} time={row['wall_time_s']}s"
        )
    for key, value in summary.items():
        print(f"{key}: {value}")
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps({"summary": summary, "seeds": rows}, indent=2))
        print(f"wrote {args.json_out}")


if __name__ == "__main__":
    main()
