from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from balatro_ai_v2.actions import GameAction
from balatro_ai_v2.balatrobot.imitation_policy import (
    balatrobot_state_to_full_fast_observation,
    fast_legal_full_actions,
    game_action_to_full_fast_action,
)
from balatro_ai_v2.balatrobot.policy import BalatroBotPolicy
from balatro_ai_v2.learning.trajectories import TrajectoryStep


@dataclass(frozen=True, slots=True)
class TraceOracleStats:
    examples: int
    skipped: int
    illegal: int


def iter_balatrobot_trace_oracle_steps(
    rows: Iterable[dict[str, Any]],
    *,
    policy: BalatroBotPolicy | None = None,
    strict: bool = False,
) -> Iterator[TrajectoryStep]:
    oracle = policy or BalatroBotPolicy()
    step_index = 0
    for row in rows:
        step = _trajectory_step_from_trace_row(row, oracle=oracle, step=step_index, strict=strict)
        if step is None:
            continue
        yield step
        step_index += 1


def write_balatrobot_trace_oracle_data(
    input_paths: Iterable[Path],
    output_path: Path,
    *,
    policy: BalatroBotPolicy | None = None,
    strict: bool = False,
) -> TraceOracleStats:
    rows = _read_jsonl_rows(input_paths)
    skipped = 0
    illegal = 0
    steps: list[TrajectoryStep] = []
    oracle = policy or BalatroBotPolicy()
    for row in rows:
        if row.get("event") != "transition" or not isinstance(row.get("before"), dict):
            skipped += 1
            continue
        step = _trajectory_step_from_trace_row(row, oracle=oracle, step=len(steps), strict=strict)
        if step is None:
            if _row_has_illegal_oracle_action(row, oracle):
                illegal += 1
            else:
                skipped += 1
            continue
        steps.append(step)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for step in steps:
            handle.write(json.dumps(step.to_jsonable(), separators=(",", ":"), sort_keys=True) + "\n")
    return TraceOracleStats(examples=len(steps), skipped=skipped, illegal=illegal)


def oracle_action_for_state(
    state: dict[str, Any],
    policy: BalatroBotPolicy,
) -> GameAction | None | object:
    match state.get("state"):
        case "BLIND_SELECT":
            return policy.blind_action(state)
        case "SELECTING_HAND":
            return policy.tactical_action(state)
        case "ROUND_EVAL":
            return policy.round_eval_action(state)
        case "SHOP":
            return policy.shop_action(state)
        case (
            "SMODS_BOOSTER_OPENED"
            | "PLANET_PACK"
            | "TAROT_PACK"
            | "SPECTRAL_PACK"
            | "STANDARD_PACK"
            | "BUFFOON_PACK"
        ):
            return policy.pack_action(state)
        case _:
            return _UNSUPPORTED_STATE


def _trajectory_step_from_trace_row(
    row: dict[str, Any],
    *,
    oracle: BalatroBotPolicy,
    step: int,
    strict: bool,
) -> TrajectoryStep | None:
    if row.get("event") != "transition":
        return None
    state = row.get("before")
    if not isinstance(state, dict):
        return None
    action = oracle_action_for_state(state, oracle)
    if action is _UNSUPPORTED_STATE:
        return None
    observation = balatrobot_state_to_full_fast_observation(state)
    legal_actions = fast_legal_full_actions(state)
    action_id = game_action_to_full_fast_action(action)
    if action_id not in legal_actions:
        message = (
            f"oracle emitted illegal action {action_id} for "
            f"state={state.get('state')} seed={state.get('seed')}"
        )
        if strict:
            raise ValueError(message)
        return None
    after = row.get("after") if isinstance(row.get("after"), dict) else {}
    terminated = after.get("state") == "GAME_OVER"
    return TrajectoryStep(
        seed=_trace_seed(state, fallback=step),
        step=step,
        observation=observation,
        legal_actions=legal_actions,
        action=action_id,
        reward=0.0,
        terminated=terminated,
        won=bool(after.get("won")) if terminated else False,
        rounds_cleared=max(int((after or state).get("round_num") or 1) - 1, 0),
        info={
            "source": "balatrobot_trace_oracle",
            "phase": str(state.get("state") or ""),
            "oracle_action": _action_name(action),
            "executed_method": str((row.get("action") or {}).get("method") or ""),
        },
    )


def _row_has_illegal_oracle_action(row: dict[str, Any], oracle: BalatroBotPolicy) -> bool:
    state = row.get("before")
    if not isinstance(state, dict):
        return False
    action = oracle_action_for_state(state, oracle)
    if action is _UNSUPPORTED_STATE:
        return False
    return game_action_to_full_fast_action(action) not in fast_legal_full_actions(state)


def _read_jsonl_rows(input_paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    for path in input_paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    if isinstance(row, dict):
                        yield row


def _trace_seed(state: dict[str, Any], *, fallback: int) -> int:
    try:
        return int(str(state.get("seed") or ""))
    except ValueError:
        return fallback


def _action_name(action: GameAction | None | object) -> str:
    if action is None:
        return "next_round"
    if isinstance(action, GameAction):
        return action.kind.value
    return "unsupported"


_UNSUPPORTED_STATE = object()
