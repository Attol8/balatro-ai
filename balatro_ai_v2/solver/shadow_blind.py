"""Offline CLI for public-only shop rollouts on a recorded decision.

Run with Python 3.12 and the pinned candidate extra. This module has no live
transport dependency and cannot apply its hypothetical actions to Balatro.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from .actions import action_from_data
from .blind_rollout import compare_next_blind
from .policy import PublicHistoryStep
from .public_codec import public_observation_from_data


class SearchContinuation:
    """Public-policy adapter for the frozen V6 options; never calls live RPC."""

    def __init__(self):
        from balatro_ai_v2.live.strategic import SearchPolicy
        self.policy = SearchPolicy(
            model_green_joker=True, project_next_boss=True, optimize_order=True,
            model_hidden_jokers=True, evaluate_blueprint_placement=True,
            prioritize_all_jokers=False, model_static_debuffs=True,
            preserve_green_plays=True, project_static_bosses=True,
        )

    def choose_action(self, observation, legal_actions, history):
        self.policy.history = list(history)
        return self.policy.select(observation)[0]


def load_decision(path: Path, index: int):
    """Decode only typed public states/actions; metadata and raw fields ignored."""
    history = []
    pending = None
    expected = 0
    with path.open() as stream:
        for line in stream:
            event = json.loads(line)
            if event.get("event") == "decision":
                if pending is not None or event["index"] != expected:
                    raise ValueError("noncontiguous decision trace")
                obs = public_observation_from_data(event["observation"]["public_solver"])
                if history and history[-1].after != obs:
                    raise ValueError("public state changed outside recorded transition")
                if event["index"] == index:
                    return obs, tuple(history)
                pending = (obs, action_from_data(event["action"]["public_action"]))
            elif event.get("event") == "transition":
                if pending is None or event["index"] != expected:
                    raise ValueError("noncontiguous transition trace")
                after = public_observation_from_data(event["observation"]["public_solver"])
                history.append(PublicHistoryStep(*pending, after))
                pending = None
                expected += 1
    raise ValueError(f"decision {index} not found")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--decision", type=int, required=True)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--horizon", choices=("next-blind", "ante"), default="next-blind")
    parser.add_argument("--antes", type=int, choices=(1, 2), default=1)
    parser.add_argument("--continuation", choices=("strategic", "search-v6"), default="strategic")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--nonce", default=None)
    parser.add_argument("--root-actions", type=Path,
                        help="JSON array of explicit legal ante-root actions")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.horizon != "ante" and args.antes != 1:
        parser.error("--antes requires --horizon ante")
    if args.root_actions is not None and args.horizon != "ante":
        parser.error("--root-actions requires --horizon ante")
    if args.output.exists():
        parser.error("output already exists; choose a new evidence path")
    from .baselines import PublicStrategicPolicy
    from .jackdaw import verify_jackdaw_runtime
    from .public_root import construct_public_root

    runtime = verify_jackdaw_runtime()
    observation, history = load_decision(args.trace, args.decision)
    roots = None
    if args.root_actions is not None:
        data = json.loads(args.root_actions.read_text())
        if not isinstance(data, list):
            parser.error("root actions must be a JSON array")
        roots = tuple(action_from_data(a) for a in data)
    nonce = args.nonce or ("public-ante-v1" if args.horizon == "ante" else "public-next-blind-v1")
    compare = compare_next_blind
    if args.horizon == "ante":
        from .blind_rollout import compare_ante
        compare = compare_ante
    default_steps = (512 if args.antes == 2 else 200) if args.horizon == "ante" else 64
    max_steps = args.max_steps if args.max_steps is not None else default_steps
    solver_hash = hashlib.sha256(b"".join(
        p.name.encode() + b"\0" + p.read_bytes()
        for p in sorted(Path(__file__).parent.glob("*.py")))).hexdigest()
    continuation_hash = (
        hashlib.sha256((Path(__file__).parent.parent / "live" / "strategic.py").read_bytes()).hexdigest()
        if args.continuation == "search-v6" else None
    )
    comparison = compare(
        observation, history, root_factory=construct_public_root,
        continuation_factory=(SearchContinuation if args.continuation == "search-v6"
                              else PublicStrategicPolicy), samples=args.samples,
        max_steps=max_steps,
        nonce=nonce,
        **({"antes": args.antes, "roots": roots} if args.horizon == "ante" else {}),
    )
    report = {
        "schema_version": 1, "evidence_kind": "shadow_candidate_not_authority",
        "decision": args.decision, "samples": args.samples,
        "max_steps": max_steps, "horizon": args.horizon, "runtime": runtime,
        "antes": args.antes, "continuation": args.continuation,
        "nonce": nonce, "root_selection": "explicit" if roots is not None else "all",
        "continuation_source_sha256": continuation_hash,
        "solver_sha256": solver_hash,
        "comparison": asdict(comparison),
        "complete": comparison.complete, "clear_rates": comparison.clear_rates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"complete": comparison.complete,
                      "clear_rates": comparison.clear_rates,
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()
