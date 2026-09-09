"""One bounded real game; no strategic fallback and no mutation retries."""

from __future__ import annotations

import fcntl
import json
import math
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, fields, replace
from importlib.resources import files
from itertools import islice
from pathlib import Path

from .analysis import analyze
from .client import BalatroBotClient, BalatroBotError, BalatroBotRejected
from .game.actions import (
    CashOut,
    PublicAction,
    action_to_data,
    canonical_action_from_data,
    is_legal,
    iter_legal_actions,
)
from .game.adapter import ObservationError, action_to_rpc, to_public_observation
from .game.codec import public_observation_from_data, public_observation_to_data
from .game.history import HistoryStep, enrich_runtime
from .game.state import Phase, PublicObservation

DECKS = (
    "RED",
    "BLUE",
    "YELLOW",
    "GREEN",
    "BLACK",
    "MAGIC",
    "NEBULA",
    "GHOST",
    "ABANDONED",
    "CHECKERED",
    "ZODIAC",
    "PAINTED",
    "ANAGLYPH",
    "PLASMA",
    "ERRATIC",
)
STAKES = ("WHITE", "RED", "GREEN", "BLACK", "BLUE", "PURPLE", "ORANGE", "GOLD")


def resolve_settings(deck=None, stake=None, *, saved=None):
    """Default fresh games; inherit and protect the settings of saved games."""

    resolved = []
    for name, requested, default, choices in (
        ("deck", deck, "RED", DECKS),
        ("stake", stake, "WHITE", STAKES),
    ):
        previous = saved.get(name, default) if saved is not None else default
        value = previous if requested is None else requested
        if value not in choices:
            raise ValueError(f"invalid {name}: {value!r}")
        if saved is not None and value != previous:
            raise ValueError(f"cannot change {name} on resume: saved {previous}, requested {value}")
        resolved.append(value)
    return tuple(resolved)


def saved_settings(directory):
    path = Path(directory) / "manifest.json"
    # Legacy evidence may predate deck/stake fields (or the manifest itself).
    return json.loads(path.read_text()) if path.exists() else {}


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
    prior_forced: int = 0
    prior_followups: int = 0
    prior_timeouts: int = 0
    # Observation fields the live game had already moved on by when resuming.
    adjusted_fields: tuple[str, ...] = ()
    deck: str = "RED"
    stake: str = "WHITE"


def load_resume(client, directory) -> Continuation:
    """Rebuild a continuation from a stopped run directory and the live game.

    Delayed effects can settle after the last recorded transition, so the live
    observation wins; the difference is reported instead of refusing to resume.
    """

    directory = Path(directory)
    deck, stake = resolve_settings(saved=saved_settings(directory))
    result_path = directory / "result.json"
    if result_path.exists():
        previous = json.loads(result_path.read_text())
    else:
        # The process died without its finally block (for example killed by the
        # operating system). Rebuild the counters from the trajectory and the run it
        # continued, and leave that reconstruction on disk, clearly marked.
        previous = reconstruct_result(directory)
        write_json(result_path, previous)
    if previous.get("status") in {"won", "lost"}:
        raise ValueError(f"{directory} already finished: {previous.get('status')}")
    history: list[HistoryStep] = []
    plan = ""
    for line in (directory / "trajectory.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event.get("event") == "transition":
            history.append(
                HistoryStep(
                    public_observation_from_data(event["before"]),
                    canonical_action_from_data(event["action"]),
                    public_observation_from_data(event["after"]),
                )
            )
        elif event.get("event") == "coach_response":
            response = event.get("response")
            if isinstance(response, dict) and isinstance(response.get("plan"), str):
                plan = response["plan"]
    if not history:
        raise ValueError(f"{directory} recorded no transition to resume from")
    deadline = time.monotonic() + 60
    raw = game_rpc(client, "gamestate", None, deadline)
    if raw.get("state") == "MENU":
        raise ValueError("cannot resume: the live game is at MENU")
    if raw.get("deck") != deck or raw.get("stake") != stake:
        raise ValueError("cannot resume: live deck or stake differs from the saved run")
    live = settle(client, raw, deadline)
    if live.phase == Phase.GAME_OVER:
        raise ValueError("cannot resume: the live game is over")
    adjusted = tuple(
        field.name
        for field in fields(live)
        if getattr(history[-1].after, field.name) != getattr(live, field.name)
    )
    if adjusted:
        history[-1] = replace(history[-1], after=live)
    return Continuation(
        observation=live,
        plan=plan,
        history=tuple(history),
        prior_calls=previous.get("coach_requests", 0),
        prior_actions=previous.get("decisions", 0),
        prior_seconds=previous.get("seconds", 0),
        prior_peak=previous.get("peak_hand_score", 0),
        source=str(directory),
        prior_forced=previous.get("forced_actions", 0),
        prior_followups=previous.get("followup_actions", 0),
        prior_timeouts=previous.get("coach_timeouts", 0),
        adjusted_fields=adjusted,
        deck=deck,
        stake=stake,
    )


def reconstruct_result(directory: Path) -> dict[str, object]:
    """Derive a result record for a run that never wrote one.

    Counters are the previous segment's cumulative counters (found through the
    manifest's continuation_of) plus this segment's own events. Wall-clock seconds
    cannot be recovered and stay at the previous segment's value.
    """

    manifest_path = directory / "manifest.json"
    prior: dict[str, object] = {}
    if manifest_path.exists():
        source = json.loads(manifest_path.read_text()).get("continuation_of")
        if source:
            for candidate in (Path(source), directory.parent / Path(source).name):
                if (candidate / "result.json").exists():
                    prior = json.loads((candidate / "result.json").read_text())
                    break
    counts = dict(
        decisions=0, coach_requests=0, followup_actions=0, forced_actions=0, coach_timeouts=0
    )
    peak = 0
    won = bool(prior.get("won", False))
    ante = prior.get("ante_reached", 0)
    trajectory = directory / "trajectory.jsonl"
    if trajectory.exists():
        for line in trajectory.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("event")
            if kind == "coach_request":
                counts["coach_requests"] += 1
            elif kind == "coach_timeout":
                counts["coach_timeouts"] += 1
            elif kind == "transition":
                counts["decisions"] += 1
                source = event.get("source")
                if source == "coach_followup":
                    counts["followup_actions"] += 1
                elif source == "forced":
                    counts["forced_actions"] += 1
                before, after = event.get("before", {}), event.get("after", {})
                if after.get("round_no") == before.get("round_no"):
                    gained = (after.get("round") or {}).get("chips", 0) - (
                        (before.get("round") or {}).get("chips", 0)
                    )
                    peak = max(peak, gained)
                won = won or bool(after.get("won"))
                ante = max(ante or 0, after.get("ante") or 0)
    return {
        "status": "stopped",
        "reason": "process ended without writing a result; reconstructed from the trajectory",
        "reconstructed": True,
        "won": won,
        "ante_8_cleared": won,
        "ante_reached": ante,
        "decisions": int(prior.get("decisions", 0)) + counts["decisions"],
        "coach_requests": int(prior.get("coach_requests", 0)) + counts["coach_requests"],
        "followup_actions": int(prior.get("followup_actions", 0)) + counts["followup_actions"],
        "forced_actions": int(prior.get("forced_actions", 0)) + counts["forced_actions"],
        "coach_timeouts": int(prior.get("coach_timeouts", 0)) + counts["coach_timeouts"],
        "rpc_timeouts_recovered": int(prior.get("rpc_timeouts_recovered", 0)),
        "peak_hand_score": max(int(prior.get("peak_hand_score", 0)), peak),
        "seconds": prior.get("seconds", 0),
    }


# A timed-out model call mutated nothing, so the same decision may be re-asked.
COACH_ATTEMPTS = 6
# Service stalls arrive in patches; pause before the third and later attempts.
COACH_RETRY_PAUSE_SECONDS = 20.0
_COACH_RETRY_SECONDS = 30
# One reply may carry a bounded chain of follow-up actions.  Every entry is
# re-validated against the state the previous action settled into.
MAX_FOLLOWUPS = 6
MAX_REPEAT = 6
_FOLLOWUP_FIELDS = {"action_json", "repeat", "until"}
_UNTIL_FIELDS = {"shop_has_any", "money_at_least"}
# Hand slots move under the coach's feet, so they are never chained blindly.
_HAND_ACTIONS = {"play_cards", "discard_cards", "choose_pack_card", "reorder_hand"}
_KEYED_FIELDS = {
    "buy_shop_card": ("card", "shop"),
    "buy_voucher": ("voucher", "vouchers"),
    "buy_pack": ("pack", "packs"),
    "sell_joker": ("joker", "jokers"),
    "sell_consumable": ("consumable", "consumables"),
    "use_consumable": ("consumable", "consumables"),
}


@dataclass(frozen=True)
class FollowUp:
    """One validated follow-up action, resolved against fresh state later."""

    action_type: str
    template: dict[str, object]
    field: str | None
    zone: str | None
    key: str | None
    repeat: int
    shop_has_any: tuple[str, ...]
    money_at_least: int | None

    def describe(self) -> str:
        return f"{self.action_type} key {self.key}" if self.key else self.action_type

    def action(self, observation: PublicObservation) -> PublicAction:
        """Build the canonical action, resolving any item key against ``observation``."""

        data = dict(self.template)
        if self.key is not None:
            matches = [
                index
                for index, item in enumerate(getattr(observation, self.zone))
                if getattr(item, "key", None) == self.key
            ]
            if len(matches) != 1:
                found = "is ambiguous in" if matches else "not in"
                raise ValueError(f"{self.describe()} {found} {self.zone}")
            data[self.field] = matches[0]
        return canonical_action_from_data(data)

    def reroll_stop(self, observation: PublicObservation) -> str | None:
        """Report why this reroll must not happen, so the coach sees the reason."""

        offered = {
            getattr(item, "key", None)
            for item in (*observation.shop, *observation.vouchers, *observation.packs)
        }
        matched = sorted(offered.intersection(self.shop_has_any))
        if matched:
            return f"the shop offers {matched[0]}"
        if (
            self.money_at_least is not None
            and observation.money - observation.round.reroll_cost < self.money_at_least
        ):
            return f"another reroll would drop money below {self.money_at_least}"
        return None


def _validate_followups(value) -> tuple[FollowUp, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_FOLLOWUPS:
        raise ValueError(f"then must be a list of at most {MAX_FOLLOWUPS} follow-up actions")
    return tuple(_validate_followup(entry) for entry in value)


def _validate_followup(entry) -> FollowUp:
    if (
        not isinstance(entry, dict)
        or "action_json" not in entry
        or not set(entry) <= _FOLLOWUP_FIELDS
    ):
        raise ValueError("each then entry needs action_json and may set repeat and until")
    if not isinstance(entry["action_json"], str) or len(entry["action_json"]) > 4096:
        raise ValueError("invalid follow-up action_json")
    data = json.loads(entry["action_json"])
    if not isinstance(data, dict):
        raise ValueError("follow-up action must be a JSON object")
    kind = data.get("type")
    if kind in _HAND_ACTIONS or data.get("targets"):
        raise ValueError("follow-up actions cannot use hand slots")
    field = zone = key = None
    named = _KEYED_FIELDS.get(kind)
    if named is not None and isinstance(data.get(named[0]), dict):
        field, zone = named
        reference = data[field]
        if set(reference) != {"key"} or not isinstance(reference["key"], str):
            raise ValueError('a follow-up item reference must be {"key": "<item key>"}')
        key = reference["key"]
        # The slot is a placeholder until the fresh observation resolves the key.
        data = dict(data, **{field: 0})
    canonical_action_from_data(data)
    repeat = _validate_repeat(entry.get("repeat"))
    shop_has_any, money_at_least = _validate_until(entry.get("until"))
    if kind != "reroll_shop" and (repeat != 1 or shop_has_any or money_at_least is not None):
        raise ValueError("repeat and until are accepted only on reroll_shop")
    return FollowUp(kind, data, field, zone, key, repeat, shop_has_any, money_at_least)


def _validate_repeat(value) -> int:
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_REPEAT:
        raise ValueError(f"repeat must be an integer in [1, {MAX_REPEAT}]")
    return value


def _validate_until(value) -> tuple[tuple[str, ...], int | None]:
    if value is None:
        return (), None
    if not isinstance(value, dict) or not set(value) <= _UNTIL_FIELDS:
        raise ValueError("until accepts only shop_has_any and money_at_least")
    keys = value.get("shop_has_any")
    if keys is not None and (
        not isinstance(keys, list) or not all(isinstance(key, str) for key in keys)
    ):
        raise ValueError("until.shop_has_any must be a list of item keys")
    money = value.get("money_at_least")
    if money is not None and (isinstance(money, bool) or not isinstance(money, int)):
        raise ValueError("until.money_at_least must be an integer")
    return tuple(keys or ()), money


def write_json(path: Path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def validate_response(response, request_id, observation):
    required = {"request_id", "action_json", "plan"}
    if not isinstance(response, dict) or not required <= set(response) <= required | {
        "then",
        "explanation",
    }:
        raise ValueError(
            "coach response must contain request_id, action_json and plan, and may add then and explanation"
        )
    if response["request_id"] != request_id:
        raise ValueError("stale coach response")
    if not isinstance(response["plan"], str) or len(response["plan"]) > 2000:
        raise ValueError("coach plan exceeds 2000 characters")
    explanation = response.get("explanation")
    if explanation is not None and (not isinstance(explanation, str) or len(explanation) > 500):
        raise ValueError("coach explanation must be null or a string of at most 500 characters")
    if not isinstance(response["action_json"], str) or len(response["action_json"]) > 4096:
        raise ValueError("invalid action_json")
    action = canonical_action_from_data(json.loads(response["action_json"]))
    if not is_legal(observation, action):
        raise ValueError("coach selected an illegal action")
    return action, response["plan"], _validate_followups(response.get("then"))


def _observation_diff(before, after):
    """Names of the public fields that differ between two observations."""
    return [
        field.name
        for field in fields(after)
        if getattr(before, field.name) != getattr(after, field.name)
    ]


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


_PACK_STATES = frozenset(
    {
        "PACK",
        "SMODS_BOOSTER_OPENED",
        "TAROT_PACK",
        "PLANET_PACK",
        "SPECTRAL_PACK",
        "STANDARD_PACK",
        "BUFFOON_PACK",
    }
)
# A skip tag that opens a pack does so after an animation; at visible game speeds
# the mod still reports BLIND_SELECT for a while. Waiting longer than this means
# the tag did not open a pack after all.
PACK_TAG_SECONDS = 8.0


def skip_opens_pack(observation) -> bool:
    """Whether skipping the offered blind hands out a tag that opens a pack."""
    return any(
        blind.status == "SELECT" and "pack" in blind.tag_effect.lower()
        for blind in observation.blinds
    )


def await_pack(client, raw, deadline, seconds=PACK_TAG_SECONDS):
    """Poll until the pack a skip tag opens is reported, or give up after ``seconds``."""
    until = min(deadline, time.monotonic() + seconds)
    while raw.get("state") not in _PACK_STATES and time.monotonic() < until:
        time.sleep(0.1)
        raw = game_rpc(client, "gamestate", None, deadline)
    return raw


_SETTLED_STATES = (
    frozenset({"BLIND_SELECT", "SELECTING_HAND", "ROUND_EVAL", "SHOP", "GAME_OVER"}) | _PACK_STATES
)


def _dealing(raw) -> bool:
    """An open pack whose cards have not been dealt yet is mid-animation."""
    return raw.get("state") in _PACK_STATES and not (raw.get("pack") or {}).get("cards")


def _stable_reads(raw) -> int:
    """Identical consecutive reads, 0.1 s apart, before a state counts as settled.

    Pack cards are dealt one at a time at visible game speeds, so a pack has to
    hold still for longer than the other states."""
    return 6 if raw.get("state") in _PACK_STATES else 2


def settle(client, raw, deadline):
    previous, stable = None, 0
    for _ in range(100):
        if time.monotonic() >= deadline:
            raise TimeoutError("game time limit reached while settling")
        if raw.get("state") == "MENU":
            raise RuntimeError("game unexpectedly returned to MENU")
        state = None
        if raw.get("state") in _SETTLED_STATES and not _dealing(raw):
            try:
                state = public_state(raw)
            except ObservationError as exc:
                # A card area whose count disagrees with its cards is still being
                # dealt; anything else is a real observation problem.
                if "unsettled" not in str(exc):
                    raise
        if state is None:
            previous, stable = None, 0
        else:
            stable = stable + 1 if state == previous else 1
            previous = state
            if stable >= _stable_reads(raw):
                return state
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
    deck=None,
    stake=None,
    continuation: Continuation | None = None,
    endless: bool = False,
):
    deck, stake = resolve_settings(
        deck,
        stake,
        saved=dict(deck=continuation.deck, stake=continuation.stake) if continuation else None,
    )
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
        coach_timeouts=0,
        forced_actions=0,
        followup_actions=0,
        rpc_timeouts_recovered=0,
        ante_reached=0,
        peak_hand_score=0,
    )
    lock = None
    history = []
    # Why each recorded step happened, and how its reply chain ended.
    step_sources: list[str] = []
    step_chains: list[str | None] = []
    plan = ""
    if continuation:
        history = list(continuation.history)
        step_sources = ["previous_run"] * len(history)
        step_chains = [None] * len(history)
        plan = continuation.plan
        result.update(
            coach_requests=continuation.prior_calls,
            decisions=continuation.prior_actions,
            peak_hand_score=continuation.prior_peak,
            coach_timeouts=continuation.prior_timeouts,
            forced_actions=continuation.prior_forced,
            followup_actions=continuation.prior_followups,
        )
    instructions = files("balatro_ai").joinpath("prompts/coach.md").read_text()
    if endless:
        instructions = instructions.replace(
            "Your objective is to clear Ante 8.",
            "Your objective is to survive as far as possible in endless mode, beyond Ante 8. "
            "Seek enough multiplicative scaling for rising targets; clearing Ante 8 is a milestone, not the stopping point.",
        )
    trace = (output / "trajectory.jsonl").open("x")
    trace_started = time.monotonic()

    def record(event, **data):
        row = dict(
            event=event,
            recorded_at=time.time(),
            elapsed_seconds=time.monotonic() - trace_started,
            **data,
        )
        trace.write(json.dumps(row, allow_nan=False) + "\n")
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
                requested_model=getattr(coach, "model", "gpt-6-astra"),
                requested_reasoning_effort=getattr(coach, "reasoning_effort", "low"),
                transport=type(coach).__name__,
                limits=asdict(limits),
                seed=seed,
                deck=deck,
                stake=stake,
                profile="all_unlocked",
                endless=endless,
                continuation_of=continuation.source if continuation else None,
                resume_adjusted=bool(continuation.adjusted_fields) if continuation else None,
                resume_diff=list(continuation.adjusted_fields) if continuation else None,
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
        params = dict(deck=deck, stake=stake)
        if seed is not None:
            params["seed"] = seed
        if continuation is None:
            record("rpc_attempt", method="start", params=params)
            raw = game_rpc(client, "start", params, deadline)
        else:
            if seed is None:
                raise ValueError("continuation requires the expected seed")
            raw = initial
        if raw.get("deck") != deck or raw.get("stake") != stake:
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
        refused = 0
        validation_feedback = None

        def perform(action, observation, state, source):
            """Execute one settled mutation and record it exactly once."""

            nonlocal unchanged
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
            # An uncertain mutation is never re-sent blindly. When the reply never
            # arrives, the game itself says what happened: an unchanged public state
            # means the action did not land and the send may be repeated once; a
            # changed state means it landed, and play continues from that state.
            recovered = None
            try:
                raw = game_rpc(client, method, params, deadline)
                if method == "skip" and skip_opens_pack(observation):
                    raw = await_pack(client, raw, deadline)
                after = settle(client, raw, deadline)
            except BalatroBotError as exc:
                if "timed out" not in str(exc):
                    raise
                live = settle(client, game_rpc(client, "gamestate", None, deadline), deadline)
                if live == state:
                    recovered = "resent after a reply timeout; the state had not changed"
                    after = settle(client, game_rpc(client, method, params, deadline), deadline)
                else:
                    recovered = "reply timed out; the live state shows the action landed"
                    after = live
                result["rpc_timeouts_recovered"] += 1
                record("rpc_timeout", method=method, params=params, recovery=recovered)
            record(
                "transition",
                before=public_observation_to_data(state),
                action=action_to_data(action),
                after=public_observation_to_data(after),
                source=source,
                **({"recovered": recovered} if recovered else {}),
            )
            history.append(HistoryStep(state, action, after))
            step_sources.append(source)
            step_chains.append(None)
            result["decisions"] += 1
            if after.round_no == state.round_no:
                result["peak_hand_score"] = max(
                    result["peak_hand_score"], after.round.chips - state.round.chips
                )
            unchanged = unchanged + 1 if after == state else 0
            return after

        def run_chain(followups, state):
            """Run the reply's follow-ups; the first problem ends the chain silently."""

            executed = 0
            stopped = None
            for entry in followups:
                for _ in range(entry.repeat):
                    if result["decisions"] >= limits.max_actions:
                        stopped = "the action limit was reached"
                    elif time.monotonic() >= deadline:
                        stopped = "the game time limit was reached"
                    if stopped:
                        break
                    observation = enrich_runtime(state, tuple(history))
                    try:
                        if entry.action_type == "reroll_shop":
                            stopped = entry.reroll_stop(observation)
                            if stopped:
                                break
                        action = entry.action(observation)
                        if not is_legal(observation, action):
                            raise ValueError(f"{entry.describe()} is no longer legal")
                    except ValueError as exc:
                        stopped = str(exc)
                        break
                    try:
                        state = perform(action, observation, state, "coach_followup")
                    except BalatroBotRejected as exc:
                        stopped = f"the game refused {entry.describe()}: {exc}"
                        break
                    executed += 1
                    result["followup_actions"] += 1
                if stopped:
                    break
            step_chains[-1] = f"{executed} follow-up actions ran from one reply" + (
                f"; chain stopped: {stopped}" if stopped else "; chain complete"
            )
            return state

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
            followups = ()
            if state.phase == Phase.ROUND_EVAL:
                action, source = CashOut(), "automatic"
            elif len(forced := list(islice(iter_legal_actions(observation), 2))) == 1:
                # Only one legal move exists: asking the coach cannot change it.
                action, source = forced[0], "forced"
                result["forced_actions"] += 1
            else:
                if result["coach_requests"] >= limits.max_calls:
                    result.update(status="stopped", reason="coach_call_limit")
                    break
                preparation_started = time.monotonic()
                # Eight hex characters: long enough to never repeat within a run, short
                # enough that the model copies it back without dropping characters.
                request_id = uuid.uuid4().hex[:8]
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
                            source=source_of,
                            chain=chain_of,
                            before_round=h.before.round_no,
                            after_round=h.after.round_no,
                            before_chips=h.before.round.chips,
                            after_chips=h.after.round.chips,
                            before_money=h.before.money,
                            after_money=h.after.money,
                        )
                        for h, source_of, chain_of in list(
                            zip(history, step_sources, step_chains, strict=True)
                        )[-3:]
                    ],
                )
                preparation_seconds = time.monotonic() - preparation_started
                attempt = 0
                while True:
                    attempt += 1
                    if attempt > 1:
                        # The packet is unchanged; only its request id is fresh.
                        request_id = uuid.uuid4().hex[:8]
                        packet["request_id"] = request_id
                    record("coach_request", **packet)
                    result["coach_requests"] += 1
                    budget()
                    call_started = time.monotonic()
                    try:
                        response = coach.choose(
                            packet, min(limits.call_seconds, deadline - time.monotonic())
                        )
                        break
                    except TimeoutError as exc:
                        result["coach_timeouts"] += 1
                        record(
                            "coach_timeout",
                            request_id=request_id,
                            seconds=round(time.monotonic() - call_started, 3),
                            attempt=attempt,
                            detail=str(exc)[:2000],
                        )
                        # Only the model call is retried, and only while the run
                        # budget still fits another one.
                        if (
                            attempt >= COACH_ATTEMPTS
                            or result["coach_requests"] >= limits.max_calls
                            or deadline - time.monotonic()
                            < min(limits.call_seconds, _COACH_RETRY_SECONDS)
                        ):
                            raise
                        if attempt >= 2:
                            time.sleep(
                                max(
                                    0.0,
                                    min(
                                        COACH_RETRY_PAUSE_SECONDS,
                                        deadline - time.monotonic() - limits.call_seconds,
                                    ),
                                )
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
                    action, plan, followups = validate_response(response, request_id, observation)
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
            try:
                state = perform(action, observation, state, source)
            except BalatroBotRejected as exc:
                # The game refused the action, so nothing changed.
                if source != "coach":
                    raise
                live = settle(client, game_rpc(client, "gamestate", None, deadline), deadline)
                if live != state:
                    # The coach answered a stale observation: the game had moved on
                    # after the last action settled (a skip tag opening a pack, for
                    # example). The reply was not wrong, so adopt the live state and
                    # ask again from it without feedback.
                    record(
                        "state_refreshed",
                        reason=f"the game refused the action: {exc}",
                        diff=_observation_diff(state, live),
                    )
                    state = live
                    validation_feedback = None
                    continue
                # For a model choice that is a rejected reply: say why and ask again.
                refused += 1
                validation_feedback = dict(
                    error=f"the game refused the action: {exc}",
                    rejected_response=response,
                    instruction="No game action was executed. Choose a different legal action.",
                )
                record("coach_rejected", **validation_feedback)
                if refused >= 3:
                    raise ValueError(
                        "three consecutive coach actions were refused by the game"
                    ) from exc
                continue
            refused = 0
            if followups:
                state = run_chain(followups, state)
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
