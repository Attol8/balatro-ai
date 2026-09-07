"""One bounded real game; no strategic fallback and no mutation retries."""

from __future__ import annotations

import fcntl
import json
import math
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, replace
from importlib.resources import files
from pathlib import Path

from .analysis import analyze
from .client import BalatroBotClient
from .game.actions import CashOut, action_to_data, canonical_action_from_data, is_legal
from .game.adapter import action_to_rpc, to_public_observation
from .game.codec import public_observation_to_data
from .game.history import HistoryStep, enrich_runtime
from .game.state import Phase, PublicObservation


@dataclass(frozen=True)
class Limits:
    max_calls: int = 200
    max_actions: int = 400
    seconds: float = 3600
    call_seconds: float = 180

    def __post_init__(self):
        for value in (self.max_calls, self.max_actions):
            if type(value) is not int or value <= 0:
                raise ValueError("call/action limits must be positive integers")
        for value in (self.seconds, self.call_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("time limits must be positive and finite")


@dataclass(frozen=True)
class Continuation:
    """Explicitly reviewed recovery state. Never replays the previous mutation."""

    observation: PublicObservation
    plan: str
    history: tuple[HistoryStep, ...]
    prior_calls: int
    prior_actions: int
    prior_seconds: float
    prior_peak: float
    source: str


def write_json(path: Path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def validate_response(response, request_id, observation):
    if not isinstance(response, dict) or set(response) != {"request_id", "action_json", "plan"}:
        raise ValueError("coach response must contain request_id, action_json and plan")
    if response["request_id"] != request_id:
        raise ValueError("stale coach response")
    if not isinstance(response["plan"], str) or len(response["plan"]) > 2000:
        raise ValueError("coach plan exceeds 2000 characters")
    if not isinstance(response["action_json"], str) or len(response["action_json"]) > 4096:
        raise ValueError("invalid action_json")
    action = canonical_action_from_data(json.loads(response["action_json"]))
    if not is_legal(observation, action):
        raise ValueError("coach selected an illegal action")
    return action, response["plan"]


def public_state(raw):
    # BalatroBot can report won=True on a losing final boss. Ante advancement
    # is the independent confirmation required for an Ante 8 clear.
    raw = dict(raw)
    raw["won"] = raw.get("won") is True and raw.get("ante_num", 0) > 8
    return to_public_observation(raw)


def game_rpc(client, method, params, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("game time limit reached")
    if isinstance(client, BalatroBotClient):
        client = replace(client, timeout=min(client.timeout, remaining))
    return client.rpc(method, params)


def settle(client, raw, deadline):
    previous = None
    for _ in range(100):
        if time.monotonic() >= deadline:
            raise TimeoutError("game time limit reached while settling")
        if raw.get("state") == "MENU":
            raise RuntimeError("game unexpectedly returned to MENU")
        if raw.get("state") in {
            "BLIND_SELECT",
            "SELECTING_HAND",
            "ROUND_EVAL",
            "SHOP",
            "PACK",
            "SMODS_BOOSTER_OPENED",
            "TAROT_PACK",
            "PLANET_PACK",
            "SPECTRAL_PACK",
            "STANDARD_PACK",
            "BUFFOON_PACK",
            "GAME_OVER",
        }:
            state = public_state(raw)
            if state == previous:
                return state
            previous = state
        else:
            previous = None
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        raw = game_rpc(client, "gamestate", None, deadline)
    raise TimeoutError("game did not settle")


def run_game(
    client,
    coach,
    output: Path,
    *,
    limits=Limits(),
    seed=None,
    continuation: Continuation | None = None,
    endless: bool = False,
):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    prior_seconds = continuation.prior_seconds if continuation else 0
    deadline = started + limits.seconds - prior_seconds
    result = dict(
        status="error",
        won=False,
        reason="not_started",
        decisions=0,
        coach_requests=0,
        ante_reached=0,
        peak_hand_score=0,
    )
    lock = None
    history = []
    plan = ""
    if continuation:
        history = list(continuation.history)
        plan = continuation.plan
        result.update(
            coach_requests=continuation.prior_calls,
            decisions=continuation.prior_actions,
            peak_hand_score=continuation.prior_peak,
        )
    instructions = files("balatro_ai").joinpath("prompts/coach.md").read_text()
    if endless:
        instructions = instructions.replace(
            "Your objective is to clear Ante 8.",
            "Your objective is to survive as far as possible in endless mode, beyond Ante 8. "
            "Seek enough multiplicative scaling for rising targets; clearing Ante 8 is a milestone, not the stopping point.",
        )
    trace = (output / "trajectory.jsonl").open("x")

    def record(event, **data):
        trace.write(json.dumps(dict(event=event, **data), allow_nan=False) + "\n")
        trace.flush()

    def budget():
        if time.monotonic() >= deadline:
            raise TimeoutError("game time limit reached")

    try:
        # BalatroBot ports do not isolate its save/profile: serialize all runners.
        lock = open(Path(tempfile.gettempdir()) / "balatro-ai-game.lock", "a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another Balatro runner owns the game")
        write_json(
            output / "manifest.json",
            dict(
                model=getattr(coach, "model", None),
                reasoning_effort=getattr(coach, "reasoning_effort", None),
                requested_model="gpt-6-astra",
                requested_reasoning_effort="low",
                transport=type(coach).__name__,
                limits=asdict(limits),
                seed=seed,
                deck="RED",
                stake="WHITE",
                profile="all_unlocked",
                endless=endless,
                continuation_of=continuation.source if continuation else None,
            ),
        )
        if game_rpc(client, "health", None, deadline).get("profile_mode") != "all_unlocked":
            raise RuntimeError("BalatroBot must use the all_unlocked profile")
        initial = game_rpc(client, "gamestate", None, deadline)
        if continuation is None and initial.get("state") != "MENU":
            raise RuntimeError("an idle game at MENU is required")
        if hasattr(coach, "preflight"):
            coach.preflight(min(10, max(0.001, deadline - time.monotonic())))
        budget()
        params = dict(deck="RED", stake="WHITE")
        if seed is not None:
            params["seed"] = seed
        if continuation is None:
            record("rpc_attempt", method="start", params=params)
            raw = game_rpc(client, "start", params, deadline)
        else:
            if seed is None:
                raise ValueError("continuation requires the expected seed")
            raw = initial
        if raw.get("deck") != "RED" or raw.get("stake") != "WHITE":
            raise RuntimeError("game started with a different deck or stake")
        if seed is not None and raw.get("seed") != seed:
            raise RuntimeError("game started with a different seed")
        manifest = json.loads((output / "manifest.json").read_text())
        manifest["seed"] = raw.get("seed", seed)
        write_json(output / "manifest.json", manifest)
        state = settle(client, raw, deadline)
        if continuation:
            if state != continuation.observation:
                raise ValueError("live game differs from the reviewed continuation state")
            if history and history[-1].after != state:
                raise ValueError("continuation history does not end at the current state")
            record(
                "continued",
                source=continuation.source,
                observation=public_observation_to_data(state),
            )
        unchanged = 0
        rejected = 0
        validation_feedback = None
        while True:
            result["ante_reached"] = state.ante
            result["won"] = result["won"] or state.won
            result["ante_8_cleared"] = result["won"]
            if state.phase == Phase.GAME_OVER:
                result.update(status="lost", reason="endless_game_over" if endless else "game_over")
                break
            if state.won and not endless:
                result.update(status="won", reason="ante_8_cleared")
                break
            budget()
            if result["decisions"] >= limits.max_actions:
                result.update(status="stopped", reason="action_limit")
                break
            observation = enrich_runtime(state, tuple(history))
            if state.phase == Phase.ROUND_EVAL:
                action, source = CashOut(), "automatic"
            else:
                if result["coach_requests"] >= limits.max_calls:
                    result.update(status="stopped", reason="coach_call_limit")
                    break
                preparation_started = time.monotonic()
                request_id = uuid.uuid4().hex
                packet = dict(
                    request_id=request_id,
                    instructions=instructions,
                    plan=plan,
                    validation_feedback=validation_feedback,
                    observation=public_observation_to_data(observation),
                    analysis=analyze(observation),
                    recent_outcomes=[
                        dict(
                            action=action_to_data(h.action),
                            before_round=h.before.round_no,
                            after_round=h.after.round_no,
                            before_chips=h.before.round.chips,
                            after_chips=h.after.round.chips,
                            before_money=h.before.money,
                            after_money=h.after.money,
                        )
                        for h in history[-3:]
                    ],
                )
                preparation_seconds = time.monotonic() - preparation_started
                record("coach_request", **packet)
                result["coach_requests"] += 1
                budget()
                call_started = time.monotonic()
                response = coach.choose(
                    packet, min(limits.call_seconds, deadline - time.monotonic())
                )
                plan_unchanged = isinstance(response, dict) and response.get("plan") == "="
                if plan_unchanged:
                    response = dict(response, plan=plan)
                record(
                    "coach_response",
                    response=response,
                    plan_unchanged=plan_unchanged,
                    seconds=round(time.monotonic() - call_started, 3),
                    preparation_seconds=round(preparation_seconds, 6),
                    transport_timings=getattr(coach, "last_timings", {}),
                    sent_packet_bytes=getattr(coach, "last_request_bytes", None),
                    public_packet_bytes=len(json.dumps(packet, separators=(",", ":")).encode()),
                )
                try:
                    action, plan = validate_response(response, request_id, observation)
                except ValueError as exc:
                    rejected += 1
                    validation_feedback = dict(
                        error=str(exc),
                        rejected_response=response,
                        instruction="No game action was executed. Correct your response using the legal contract.",
                    )
                    record("coach_rejected", **validation_feedback)
                    if rejected >= 3:
                        raise ValueError(
                            "three consecutive coach responses failed validation"
                        ) from exc
                    continue
                rejected = 0
                validation_feedback = None
                source = "coach"
            budget()
            method, params = action_to_rpc(action, observation)
            record(
                "rpc_attempt",
                method=method,
                params=params,
                source=source,
                observation=public_observation_to_data(observation),
                action=action_to_data(action),
            )
            # An uncertain mutation is never retried: stop and preserve evidence.
            after = settle(client, game_rpc(client, method, params, deadline), deadline)
            record(
                "transition",
                before=public_observation_to_data(state),
                action=action_to_data(action),
                after=public_observation_to_data(after),
                source=source,
            )
            history.append(HistoryStep(state, action, after))
            result["decisions"] += 1
            if after.round_no == state.round_no:
                result["peak_hand_score"] = max(
                    result["peak_hand_score"], after.round.chips - state.round.chips
                )
            unchanged = unchanged + 1 if after == state else 0
            state = after
            if unchanged >= 3:
                raise RuntimeError("three actions produced no visible progress")
    except KeyboardInterrupt:
        result.update(status="stopped", reason="interrupted")
    except TimeoutError as exc:
        result.update(status="stopped", reason=str(exc))
    except Exception as exc:
        result.update(status="error", reason=f"{type(exc).__name__}: {exc}")
    finally:
        result["seconds"] = round(prior_seconds + time.monotonic() - started, 3)
        trace.close()
        if lock is not None:
            lock.close()
        write_json(output / "result.json", result)
        if hasattr(coach, "close"):
            coach.close()
    return result
