"""Run deterministic public-action traces through real Balatro and Jackdaw."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.baselines import (
    PUBLIC_BASELINE_NAMES,
    DeterministicCoveragePolicy,
    build_public_baseline,
)
from balatro_ai_v2.balatrobot.backend import BalatroBotBackend
from balatro_ai_v2.balatrobot.client import BalatroBotClient, BalatroBotError
from balatro_ai_v2.balatrobot.process import (
    build_launch_command,
    build_launch_environment,
    require_active_mods,
    require_profile_mode,
    stop_balatrobot_server,
    wait_for_balatrobot,
)
from balatro_ai_v2.balatrobot.runner import AuthorityRunner
from balatro_ai_v2.balatrobot.tracing import AuthorityTraceWriter, build_manifest, read_verified_trace
from balatro_ai_v2.differential import replay_authority_trace
from balatro_ai_v2.jackdaw import (
    JACKDAW_REVISION,
    JackdawBackend,
    JackdawUnavailable,
    verify_jackdaw_runtime,
)
from balatro_ai_v2.policy_process import PolicyProcess


def main() -> None:
    args = build_parser().parse_args()
    profile_mode = "all_unlocked"
    if args.seeds < 1 or args.max_shop_actions < 0 or args.policy_timeout <= 0:
        raise SystemExit(
            "--seeds and --policy-timeout must be positive; --max-shop-actions must be non-negative"
        )
    root = Path(__file__).resolve().parents[1]
    client = BalatroBotClient(host=args.host, port=args.port, timeout=args.timeout)
    process: subprocess.Popen[bytes] | None = None
    candidate: JackdawBackend | None = None
    policy_process: PolicyProcess | None = None
    try:
        verify_jackdaw_runtime()
        candidate = JackdawBackend()
        args.output_dir.mkdir(parents=True, exist_ok=False)
        if args.launch_server:
            command = build_launch_command(
                args.launch_command,
                host=args.host,
                port=args.port,
                fast_server=args.fast_server,
                headless_server=args.headless_server,
            )
            process = subprocess.Popen(command, env=build_launch_environment(profile_mode=profile_mode))
            wait_for_balatrobot(
                client,
                timeout=args.launch_timeout,
                poll_delay=args.launch_poll_delay,
                process=process,
            )
            if args.post_launch_delay:
                time.sleep(args.post_launch_delay)
        health = client.health()
        require_profile_mode(health, expected=profile_mode)
        require_active_mods(health, identities=tuple(args.mod))

        authority = BalatroBotBackend(
            client,
            max_settle_polls=args.max_settle_polls,
            settle_poll_delay=args.settle_poll_delay,
            backend_version=args.balatrobot_version,
            game_version=args.game_version,
            runtime_version=args.runtime_version,
        )
        if args.policy == "coverage":
            policy = DeterministicCoveragePolicy(
                policy_seed=args.policy_seed,
                max_shop_actions=args.max_shop_actions,
                pack_strategy=args.pack_strategy,
                coverage_mode=args.coverage_mode,
            )
            policy_name = f"DeterministicCoveragePolicy:{args.policy_seed}:{args.coverage_mode}"
        else:
            _, implementation_name = build_public_baseline(args.policy, args.policy_seed)
            policy_process = PolicyProcess(
                args.policy,
                policy_seed=args.policy_seed,
                timeout_seconds=args.policy_timeout,
            )
            policy = policy_process
            policy_name = f"{implementation_name}:process-v1"
        for seed_number in range(args.seed_start, args.seed_start + args.seeds):
            seed = str(seed_number)
            spec = RunSpec(args.deck, args.stake, seed)
            trace_path = args.output_dir / f"{args.deck.lower()}-{args.stake.lower()}-seed{seed}.jsonl"
            manifest = build_manifest(
                repository_root=root,
                command=tuple(sys.argv),
                policy_name=policy_name,
                backend=authority.metadata,
                run=spec,
                max_decisions=args.max_decisions,
                max_settle_polls=args.max_settle_polls,
                launch_fast=args.fast_server,
                launch_headless=args.headless_server,
                profile_mode=profile_mode,
                inference_budget=(
                    "tactical_candidates<=2048;transported_public_actions<=512;"
                    "random_public_actions<=256;draw_branches<=512;"
                    f"shop_actions<={args.max_shop_actions};policy_timeout_seconds={args.policy_timeout}"
                ),
                mods=tuple(args.mod),
            )
            result = AuthorityRunner(
                backend=authority,
                policy=policy,
                max_decisions=args.max_decisions,
                trace=AuthorityTraceWriter(trace_path, manifest),
            ).run(spec)
            if not result.complete:
                print(
                    json.dumps(
                        {
                            "authority_complete": False,
                            "seed": seed,
                            "terminal_reason": result.terminal_reason,
                            "trace": str(trace_path),
                        },
                        sort_keys=True,
                    )
                )
                raise SystemExit(2)

            report = replay_authority_trace(trace_path, candidate)
            coverage = (
                summarize_trace_coverage(
                    trace_path,
                    pack_strategy=args.pack_strategy,
                    coverage_mode=args.coverage_mode,
                )
                if args.policy == "coverage"
                else None
            )
            payload = {
                "ante": result.ante,
                "authority_complete": True,
                "candidate_revision": JACKDAW_REVISION,
                "coverage": coverage,
                "decisions": result.decisions,
                "differential": asdict(report),
                "seed": seed,
                "trace": str(trace_path),
                "won": result.won,
            }
            print(json.dumps(payload, sort_keys=True))
            if not report.observed_lockstep:
                raise SystemExit(1)
    except JackdawUnavailable as exc:
        raise SystemExit(f"Jackdaw candidate unavailable: {exc}") from exc
    except BalatroBotError as exc:
        raise SystemExit(f"BalatroBot authority failed: {exc}") from exc
    finally:
        if policy_process is not None:
            policy_process.close()
        if candidate is not None:
            candidate.close()
        if process is not None:
            stop_balatrobot_server(process)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stop-on-first-mismatch campaign against real Balatro and pinned Jackdaw"
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--policy-seed", default="coverage-v1")
    parser.add_argument(
        "--policy", choices=("coverage", *PUBLIC_BASELINE_NAMES), default="coverage"
    )
    parser.add_argument("--max-shop-actions", type=int, default=3)
    parser.add_argument("--pack-strategy", choices=("mixed", "skip", "pick"), default="mixed")
    parser.add_argument("--coverage-mode", choices=("default", "extended"), default="default")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12346)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--max-decisions", type=int, default=800)
    parser.add_argument("--max-settle-polls", type=int, default=40)
    parser.add_argument("--settle-poll-delay", type=float, default=0.02)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--policy-timeout", type=float, default=5.0)
    parser.add_argument("--balatrobot-version", required=True)
    parser.add_argument("--game-version", required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--mod", action="append", default=[])
    parser.add_argument("--launch-server", action="store_true")
    parser.add_argument(
        "--launch-command",
        default=os.environ.get("BALATROBOT_LAUNCH_COMMAND", "uvx balatrobot serve"),
    )
    parser.add_argument("--fast-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--headless-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--launch-timeout", type=float, default=90.0)
    parser.add_argument("--launch-poll-delay", type=float, default=0.2)
    parser.add_argument("--post-launch-delay", type=float, default=1.0)
    return parser


_BASELINE_REQUIRED_ACTIONS = {
    "cash_out",
    "discard_cards",
    "leave_shop",
    "play_cards",
    "select_blind",
}


def summarize_trace_coverage(
    path: Path,
    *,
    pack_strategy: str,
    coverage_mode: str = "default",
) -> dict[str, object]:
    rows = read_verified_trace(path)
    accepted_counts: Counter[str] = Counter()
    phase_counts: Counter[str] = Counter()
    opportunity_counts: Counter[str] = Counter()
    current_public: dict[str, Any] | None = None
    for row in rows:
        if row.get("event") == "run_start":
            public = row.get("public")
            current_public = public if isinstance(public, dict) else None
            continue
        if row.get("event") != "transition":
            continue
        if current_public is not None:
            phase = current_public.get("phase")
            if isinstance(phase, str):
                phase_counts[phase] += 1
            _accumulate_opportunities(opportunity_counts, current_public)
        if row.get("status") != "accepted":
            continue
        action = row.get("action")
        if isinstance(action, dict):
            family = str(action.get("type") or "unknown")
            accepted_counts[family] += 1
        public_after = row.get("public_after")
        current_public = public_after if isinstance(public_after, dict) else None

    required = set(_BASELINE_REQUIRED_ACTIONS)
    if pack_strategy == "skip":
        required.update({"buy_pack", "skip_pack"})
    elif pack_strategy == "pick":
        required.update({"buy_pack", "choose_pack_card"})
    elif pack_strategy == "mixed":
        required.update({"buy_pack", "skip_pack", "choose_pack_card"})
    else:
        raise ValueError(f"unsupported pack strategy {pack_strategy!r}")
    if coverage_mode == "extended":
        required.update({"reroll_shop", "use_consumable"})
    elif coverage_mode != "default":
        raise ValueError(f"unsupported coverage mode {coverage_mode!r}")

    return {
        "accepted_action_counts": dict(sorted(accepted_counts.items())),
        "coverage_mode": coverage_mode,
        "coverage_complete": all(accepted_counts.get(family, 0) > 0 for family in required),
        "opportunity_counts": dict(sorted(opportunity_counts.items())),
        "pack_strategy": pack_strategy,
        "phase_counts": dict(sorted(phase_counts.items())),
        "required_action_counts": {family: accepted_counts.get(family, 0) for family in sorted(required)},
    }


def _accumulate_opportunities(counts: Counter[str], public: dict[str, Any]) -> None:
    phase = public.get("phase")
    if not isinstance(phase, str):
        return

    if phase == "BLIND_SELECT":
        if _has_selected_blind(public):
            counts["action:select_blind"] += 1
    elif phase == "SELECTING_HAND":
        if _count_list(public, "hand") > 0:
            counts["action:play_cards"] += 1
        if _count_list(public, "hand") > 0 and _round_value(public, "discards_left") > 0:
            counts["action:discard_cards"] += 1
        if _has_held_planet(public):
            counts["action:use_consumable"] += 1
    elif phase == "ROUND_EVAL":
        counts["action:cash_out"] += 1
    elif phase == "SHOP":
        counts["action:leave_shop"] += 1
        if _has_affordable_reroll(public):
            counts["action:reroll_shop"] += 1
        if _has_held_planet(public):
            counts["action:use_consumable"] += 1
        if _has_affordable_pack(public):
            counts["action:buy_pack"] += 1
            counts["shop_with_pack_offers"] += 1
    elif phase == "PACK":
        counts["action:skip_pack"] += 1
        if _has_safe_pack_choice(public):
            counts["action:choose_pack_card"] += 1
            counts["pack_with_choices"] += 1


def _has_selected_blind(public: dict[str, Any]) -> bool:
    blinds = public.get("blinds")
    if not isinstance(blinds, list):
        return False
    return any(
        isinstance(blind, dict) and blind.get("status") == "SELECT"
        for blind in blinds
    )


def _round_value(public: dict[str, Any], key: str) -> int:
    round_state = public.get("round")
    if not isinstance(round_state, dict):
        return 0
    value = round_state.get(key)
    return value if isinstance(value, int) else 0


def _count_list(public: dict[str, Any], name: str) -> int:
    values = public.get(name)
    return len(values) if isinstance(values, list) else 0


def _has_affordable_pack(public: dict[str, Any]) -> bool:
    money = public.get("money")
    packs = public.get("packs")
    if not isinstance(money, int) or not isinstance(packs, list):
        return False
    return any(
        isinstance(pack, dict)
        and isinstance(pack.get("buy_cost"), int)
        and pack["buy_cost"] <= money
        for pack in packs
    )


def _has_affordable_reroll(public: dict[str, Any]) -> bool:
    money = public.get("money")
    round_state = public.get("round")
    cost = round_state.get("reroll_cost") if isinstance(round_state, dict) else None
    if not isinstance(money, int) or not isinstance(cost, int):
        return False
    jokers = public.get("jokers")
    credit = isinstance(jokers, list) and any(
        isinstance(joker, dict) and joker.get("key") == "j_credit_card" for joker in jokers
    )
    return money - cost >= (-20 if credit else 0)


def _has_held_planet(public: dict[str, Any]) -> bool:
    consumables = public.get("consumables")
    return isinstance(consumables, list) and any(
        isinstance(item, dict) and str(item.get("kind", "")).upper() == "PLANET"
        for item in consumables
    )


def _has_safe_pack_choice(public: dict[str, Any]) -> bool:
    cards = public.get("opened_pack")
    if not isinstance(cards, list):
        return False
    joker_room = _count_list(public, "jokers") < public.get("joker_limit", 0)
    return any(
        isinstance(card, dict)
        and (
            (isinstance(card.get("rank"), str) and isinstance(card.get("suit"), str))
            or card.get("kind") == "PLANET"
            or (card.get("kind") == "JOKER" and joker_room)
        )
        for card in cards
    )


if __name__ == "__main__":
    main()
