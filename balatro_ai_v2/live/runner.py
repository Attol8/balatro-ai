"""Real-game episodes and durable public decision traces.

There is deliberately no automatic retry around a mutating RPC: a timeout does
not prove that the game failed to apply an action.
"""

from __future__ import annotations

import hashlib
import json
import platform
import statistics
import subprocess
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from balatro_ai_v2.live.observation import active_blind, numeric, public_observation
from balatro_ai_v2.live.outcome import normalize_outcome
from balatro_ai_v2.live.policy import BaselinePolicy, Decision

SCHEMA_VERSION = 1
SEARCH_VARIANTS = {
    "search": {},
    "search-planets": {"evaluate_planets": True},
    "search-green": {"model_green_joker": True},
    "search-boss": {"project_next_boss": True},
    "search-order": {"optimize_order": True},
}
POLICY_NAMES = ("baseline", "strategic", *SEARCH_VARIANTS)
DECISION_STATES = {
    "BLIND_SELECT", "SELECTING_HAND", "ROUND_EVAL", "SHOP",
    "SMODS_BOOSTER_OPENED", "TAROT_PACK", "PLANET_PACK", "SPECTRAL_PACK",
    "STANDARD_PACK", "BUFFOON_PACK",
}


class Client(Protocol):
    def rpc(self, method: str, params: dict | None = None) -> dict: ...


class Policy(Protocol):
    def choose(self, state: dict) -> Decision: ...


@dataclass(frozen=True)
class RunConfig:
    deck: str = "RED"
    stake: str = "WHITE"
    split: str = "dev"
    max_decisions: int = 2000
    endless: bool = False
    max_ante: int = 16
    settle_polls: int = 100
    stable_reads: int = 2
    poll_interval: float = 0.1
    policy: str = "baseline"
    expected_profile: str | None = None

    def __post_init__(self) -> None:
        if self.max_decisions < 1 or self.settle_polls < 1 or self.max_ante < 1 or self.stable_reads < 1:
            raise ValueError("decision, poll, and ante limits must be positive")
        if self.poll_interval < 0 or self.split not in {"dev", "heldout"}:
            raise ValueError("invalid poll interval or seed split")
        if self.policy not in POLICY_NAMES:
            raise ValueError(f"unknown policy: {self.policy}")


class Trace:
    def __init__(self, path: Path):
        self.file = path.open("x", encoding="utf-8")

    def write(self, event: str, **fields: Any) -> None:
        self.file.write(json.dumps(
            {"event": event, **fields}, sort_keys=True, allow_nan=False,
        ) + "\n")
        self.file.flush()

    def close(self) -> None:
        self.file.close()


def action_record(decision: Decision) -> dict:
    method, params = decision.action.to_balatrobot_rpc()
    result = {"method": method, "params": params}
    if hasattr(decision.action, "public_action"):
        result["public_action"] = decision.action.public_action
    return result


def make_policy(name: str) -> Policy:
    if name == "baseline":
        return BaselinePolicy()
    if name == "strategic":
        from balatro_ai_v2.live.strategic import StrategicPolicy
        return StrategicPolicy()
    if name in SEARCH_VARIANTS:
        from balatro_ai_v2.live.strategic import SearchPolicy
        return SearchPolicy(**SEARCH_VARIANTS[name])
    raise ValueError(f"unknown policy: {name}")


def record_transition(policy: Policy, before: dict, action: dict, after: dict) -> None:
    callback = getattr(policy, "record_transition", None)
    if callback is not None:
        callback(before, action, after)


def _settle(client: Client, state: dict, config: RunConfig) -> dict:
    # Decision phases may precede queued effects, such as Verdant Leaf disabling.
    # Compare public API snapshots without deriving typed policy state.
    previous = None
    stable = 0
    for poll in range(config.settle_polls + 1):
        if state.get("state") in DECISION_STATES | {"GAME_OVER"}:
            public = public_observation(state)
            stable = stable + 1 if public == previous else 1
            previous = public
            if stable >= config.stable_reads:
                return state
        else:
            previous = None
            stable = 0
        if state.get("state") == "MENU":
            raise RuntimeError("game unexpectedly returned to MENU")
        if poll == config.settle_polls:
            break
        time.sleep(config.poll_interval)
        state = client.rpc("gamestate")
    raise RuntimeError(f"game did not settle; last state: {state.get('state')!r}")


def run_episode(
    client: Client,
    policy: Policy,
    seed: str,
    trace_path: Path,
    config: RunConfig,
) -> dict:
    """Start from MENU; return a result even on an execution failure."""
    trace = Trace(trace_path)
    result: dict[str, Any] = {
        "seed": seed, "split": config.split, "status": "error", "won": False,
        "reason": "not_started", "ante_reached": 0, "round_reached": 0,
        "decisions": 0, "peak_hand_score": 0.0, "peak_blind_score": 0.0,
        "trajectory": trace_path.name,
    }
    state: dict = {}
    started = time.monotonic()
    trace.write("episode", schema_version=SCHEMA_VERSION, seed=seed, config=asdict(config))

    def observe(raw: dict) -> dict:
        raw = normalize_outcome(raw, previously_won=result["won"])
        if config.policy == "strategic" or config.policy in SEARCH_VARIANTS:
            from balatro_ai_v2.live.strategic import project_strategic_observation
            public = project_strategic_observation(raw)
        else:
            public = public_observation(raw)
        result["won"] = result["won"] or public.get("won") is True
        result["ante_reached"] = max(result["ante_reached"], int(numeric(public.get("ante_num"))))
        result["round_reached"] = max(result["round_reached"], int(numeric(public.get("round_num"))))
        result["peak_blind_score"] = max(
            result["peak_blind_score"], numeric(public.get("round", {}).get("chips")),
        )
        return public

    try:
        params = {"deck": config.deck, "stake": config.stake, "seed": seed}
        trace.write("rpc_attempt", method="start", params=params)
        raw = _settle(client, client.rpc("start", params), config)
        if raw.get("seed") != seed:
            raise RuntimeError(f"requested seed {seed!r}, game returned {raw.get('seed')!r}")
        if raw.get("deck") != config.deck or raw.get("stake") != config.stake:
            raise RuntimeError("game started with a different deck or stake")
        state = observe(raw)
        trace.write("started", observation=state)
        unchanged = 0
        while True:
            if state.get("state") == "GAME_OVER":
                result.update(status="won" if result["won"] else "lost", reason="game_over")
                break
            if result["won"] and not config.endless:
                result.update(status="won", reason="ante_8_cleared")
                break
            if config.endless and result["ante_reached"] > config.max_ante:
                result.update(status="truncated", reason="ante_limit")
                break
            if result["decisions"] >= config.max_decisions:
                result.update(status="truncated", reason="decision_limit")
                break
            decision = policy.choose(state)
            action = action_record(decision)
            index = result["decisions"]
            trace.write(
                "decision", index=index, observation=state, action=action,
                reason=decision.reason, predicted_score=decision.predicted_score,
                limitations=list(decision.limitations),
                diagnostics=decision.diagnostics,
            )
            result["decisions"] += 1
            # Do not expose the original seed, deck order, or hidden identities.
            after = observe(_settle(client, client.rpc(**{
                "method": action["method"], "params": action["params"],
            }), config))
            observed_score = None
            prediction_error = None
            if action["method"] == "play" and after.get("round_num") == state.get("round_num"):
                observed_score = max(0.0, numeric(after.get("round", {}).get("chips"))
                                     - numeric(state.get("round", {}).get("chips")))
                result["peak_hand_score"] = max(result["peak_hand_score"], observed_score)
                if decision.predicted_score is not None:
                    prediction_error = observed_score - decision.predicted_score
            trace.write(
                "transition", index=index, observation=after,
                observed_score=observed_score, prediction_error=prediction_error,
            )
            record_transition(policy, state, action, after)
            unchanged = unchanged + 1 if after == state else 0
            state = after
            if unchanged >= 3:
                raise RuntimeError("three actions returned an unchanged public state")
    except KeyboardInterrupt:
        result.update(status="truncated", reason="interrupted")
        trace.write("error", message="interrupted; pending RPC outcome may be unknown", observation=state)
    except Exception as exc:
        result.update(status="error", reason=f"{type(exc).__name__}: {exc}")
        trace.write("error", message=result["reason"], observation=state)
    finally:
        blind = active_blind(state)
        result["final_context"] = {
            "phase": state.get("state"), "blind": blind.get("name"),
            "blind_type": blind.get("type"), "required_score": blind.get("score"),
            "round": state.get("round", {}), "money": state.get("money"),
            "jokers": [card.get("key", "hidden") for card in state.get("jokers", {}).get("cards", [])],
        }
        result["seconds"] = round(time.monotonic() - started, 3)
        trace.write("result", **result)
        trace.close()
    return result


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(results: list[dict], requested: int) -> dict:
    completed = [r for r in results if r["status"] in {"won", "lost"}]
    scores = [r["peak_hand_score"] for r in completed]
    wins = sum(r["won"] for r in results)
    n = len(results)
    # Wilson 95% interval: includes errors/truncations without a victory as failures.
    interval = None
    if n:
        p, z = wins / n, 1.96
        divisor = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / divisor
        margin = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5 / divisor
        interval = [max(0, centre - margin), min(1, centre + margin)]
    return {
        "requested": requested, "attempted": n, "not_attempted": requested - n,
        "status_counts": dict(Counter(r["status"] for r in results)),
        "ante_8_wins": wins,
        "win_rate_attempted": wins / n if n else None,
        "win_rate_95pct_wilson": interval,
        "win_rate_completed": sum(r["won"] for r in completed) / len(completed) if completed else None,
        "completed_peak_hand_score": {
            "count": len(scores), "median": statistics.median(scores) if scores else None,
            "p90": _percentile(scores, .9), "max": max(scores) if scores else None,
        },
        "ante_reached_counts": dict(sorted(Counter(str(r["ante_reached"]) for r in results).items())),
        "losses_by_blind": dict(Counter(
            r["final_context"].get("blind") or "unknown" for r in results if r["status"] == "lost"
        )),
        "runs": results,
    }


def _write_json(path: Path, value: dict) -> None:
    # Output lives in a newly created batch directory; a replace gives readers
    # either the previous complete summary or the next complete summary.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _revision() -> dict:
    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        sha, dirty = None, None
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if ".venv" in path.parts:
            continue
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return {"git_revision": sha, "dirty": dirty, "python_source_sha256": digest.hexdigest()}


def run_batch(
    client: Client, seeds: list[str], output: Path, config: RunConfig,
    *, reset: bool = False, progress: Any = print,
) -> dict:
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("provide a nonempty list of distinct seeds")
    if any(not seed or len(seed) > 8 or not seed.isascii() or not seed.isalnum() for seed in seeds):
        raise ValueError("seeds must be 1–8 ASCII letters or digits")
    health = client.rpc("health")
    if config.expected_profile is not None and health.get("profile_mode") != config.expected_profile:
        raise RuntimeError(f"server profile is {health.get('profile_mode')!r}; expected {config.expected_profile!r}. "
                           "Start BalatroBot with BALATROBOT_ALL_UNLOCKED=1 for comparable all-unlocked runs.")
    initial = client.rpc("gamestate")
    if initial.get("state") not in {"MENU", "GAME_OVER"} and not reset:
        raise RuntimeError("an existing game is active; use --reset to explicitly replace it")
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "manifest.json", {
        "schema_version": SCHEMA_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
        "config": asdict(config), "seeds": seeds, "policy": config.policy,
        "python": platform.python_version(), "server": health, **_revision(),
        "information": "public observations only; no oracle or checkpoint search",
    })
    results = []
    summary = summarize(results, len(seeds))
    _write_json(output / "summary.json", summary)
    for index, seed in enumerate(seeds):
        if index or initial.get("state") != "MENU":
            try:
                client.rpc("menu")
            except Exception as exc:
                summary["batch_error"] = f"menu reset failed: {type(exc).__name__}: {exc}"
                _write_json(output / "summary.json", summary)
                return summary
        result = run_episode(client, make_policy(config.policy), seed, output / f"{index:04d}-{seed}.jsonl", config)
        results.append(result)
        summary = summarize(results, len(seeds))
        _write_json(output / "summary.json", summary)
        progress(f"{index + 1}/{len(seeds)} seed={seed} {result['status']} "
                 f"ante={result['ante_reached']} peak={result['peak_hand_score']:g} "
                 f"decisions={result['decisions']}")
        if result["status"] == "error" or result["reason"] == "interrupted":
            # Preserve the failure state for diagnosis rather than starting over.
            break
    return summary


def replay(path: Path, policy: Policy | None = None) -> dict:
    """Compare current policy decisions with a public trace; never calls the game."""
    compared = 0
    differences = []
    finished = False
    partial_tail = False
    pending = None
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                if line.endswith("\n"):
                    raise
                # The file ended during an append. Complete preceding records
                # remain usable; malformed newline-terminated records are errors.
                partial_tail = True
                break
            if event["event"] == "result":
                finished = True
            if event["event"] == "episode" and policy is None:
                policy = make_policy(event.get("config", {}).get("policy", "baseline"))
            if event["event"] == "transition" and pending is not None and policy is not None:
                record_transition(policy, pending["observation"], pending["action"], event["observation"])
                pending = None
            if event["event"] != "decision":
                continue
            if policy is None:
                policy = make_policy("baseline")
            pending = event
            # Reapply redaction even when loading an externally produced trace.
            current = action_record(policy.choose(public_observation(event["observation"])))
            compared += 1
            if current != event["action"]:
                differences.append({"index": event["index"], "recorded": event["action"], "current": current})
    result = {"decisions": compared, "matching": compared - len(differences),
              "complete_trace": finished and not partial_tail, "differences": differences}
    if partial_tail:
        result["warning"] = "ignored an incomplete trailing record"
    return result
