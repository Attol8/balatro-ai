from __future__ import annotations

from dataclasses import dataclass, field
from time import sleep
from typing import Any
from uuid import uuid4

from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.balatrobot.client import BalatroBotClient, BalatroBotError
from balatro_ai_v2.balatrobot.policy import BalatroBotPolicy
from balatro_ai_v2.balatrobot.tracing import JsonlTraceWriter, action_payload


@dataclass(frozen=True, slots=True)
class BalatroBotRunResult:
    won: bool
    ante: int
    round_num: int
    steps: int
    seed: str
    final_state: dict[str, Any]


@dataclass(slots=True)
class BalatroBotRunner:
    client: BalatroBotClient
    policy: BalatroBotPolicy = field(default_factory=BalatroBotPolicy)
    trace: bool = False
    trace_writer: JsonlTraceWriter | None = None
    poll_delay: float = 0.02
    retry_delay: float = 0.05
    pack_in_progress_retries: int = 10
    shop_settle_retries: int = 8
    use_refusal_retries: int = 3
    _run_id: str = field(default="", init=False)
    _pack_retry_counts: dict[tuple[Any, ...], int] = field(default_factory=dict, init=False)
    _shop_settle_count: int = field(default=0, init=False)
    _use_refusal_counts: dict[str, int] = field(default_factory=dict, init=False)

    def start_run(self, *, deck: str = "RED", stake: str = "WHITE", seed: str | None = None) -> dict[str, Any]:
        self.client.menu()
        return self.client.start(deck=deck, stake=stake, seed=seed)

    def play_run(
        self,
        *,
        deck: str = "RED",
        stake: str = "WHITE",
        seed: str | None = None,
        max_steps: int = 800,
    ) -> BalatroBotRunResult:
        self._run_id = f"{deck}:{stake}:{seed or ''}:{uuid4().hex}"
        self._pack_retry_counts.clear()
        state = self.start_run(deck=deck, stake=stake, seed=seed)
        self._record("run_start", state=state, deck=deck, stake=stake, requested_seed=seed)
        steps = 0
        while state.get("state") != "GAME_OVER" and steps < max_steps:
            if self.trace:
                print(_trace_state(state))
            state = self.step_state(state)
            steps += 1
        if self.trace:
            print(_trace_state(state))
        self._record("run_end", state=state, steps=steps)
        return BalatroBotRunResult(
            won=bool(state.get("won")),
            ante=int(state.get("ante_num") or 0),
            round_num=int(state.get("round_num") or 0),
            steps=steps,
            seed=str(state.get("seed") or seed or ""),
            final_state=state,
        )

    def step_state(self, state: dict[str, Any]) -> dict[str, Any]:
        action: dict[str, Any]
        match state.get("state"):
            case "BLIND_SELECT":
                game_action = self.policy.blind_action(state)
                if self.trace:
                    print(f"action: {game_action.kind.value}")
                next_state, executed = self._execute_tracked(game_action)
                action = action_payload(game_action) if executed else action_payload(method="gamestate")
            case "SELECTING_HAND":
                game_action = self.policy.tactical_action(state)
                if self.trace:
                    print(f"action: {game_action.kind.value} {game_action.indices}")
                next_state, executed = self._execute_tracked(game_action)
                action = action_payload(game_action) if executed else action_payload(method="gamestate")
                if not executed and game_action.kind == ActionKind.USE_CONSUMABLE:
                    self._note_use_refusal(state, game_action)
            case "ROUND_EVAL":
                self._use_refusal_counts.clear()
                suppressed = getattr(self.policy, "suppressed_consumables", None)
                if suppressed is not None:
                    suppressed.clear()
                game_action = self.policy.round_eval_action(state)
                if self.trace:
                    print(f"action: {game_action.kind.value}")
                next_state, executed = self._execute_tracked(game_action)
                action = action_payload(game_action) if executed else action_payload(method="gamestate")
            case "SHOP" if not _shop_settled(state) and self._shop_settle_count < self.shop_settle_retries:
                # Right after cash-out the shop and payout land asynchronously;
                # acting on the stale snapshot shops with understated money.
                self._shop_settle_count += 1
                if self.poll_delay > 0:
                    sleep(self.poll_delay)
                action = action_payload(method="gamestate")
                next_state = self.client.gamestate()
            case "SHOP":
                self._shop_settle_count = 0
                game_action = self.policy.shop_action(state)
                if game_action is not None:
                    if self.trace:
                        print(f"action: {game_action.kind.value} {game_action.index}")
                    next_state, executed = self._execute_tracked(game_action)
                    action = action_payload(game_action) if executed else action_payload(method="gamestate")
                else:
                    if self.trace:
                        print("action: next_round")
                    action = action_payload(method="next_round")
                    next_state = self.client.call_action("next_round")
            case "SMODS_BOOSTER_OPENED" | "PLANET_PACK" | "TAROT_PACK" | "SPECTRAL_PACK" | "STANDARD_PACK" | "BUFFOON_PACK":
                if not _pack_cards_available(state):
                    if self.poll_delay > 0:
                        sleep(self.poll_delay)
                    action = action_payload(method="gamestate")
                    next_state = self.client.gamestate()
                else:
                    game_action = self.policy.pack_action(state)
                    if self.trace:
                        if game_action.kind == ActionKind.PACK_SKIP:
                            print("action: pack_skip")
                        else:
                            print(f"action: pack {game_action.index}")
                    action = action_payload(game_action)
                    try:
                        next_state = self._execute(game_action)
                        self._pack_retry_counts.pop(_pack_retry_key(state), None)
                    except BalatroBotError as exc:
                        if "Pack selection already in progress" not in str(exc):
                            raise
                        key = _pack_retry_key(state)
                        retries = self._pack_retry_counts.get(key, 0) + 1
                        self._pack_retry_counts[key] = retries
                        if retries < self.pack_in_progress_retries:
                            if self.poll_delay > 0:
                                sleep(self.poll_delay)
                            action = action_payload(method="gamestate")
                            next_state = self.client.gamestate()
                        else:
                            self._pack_retry_counts.pop(key, None)
                            game_action = GameAction(kind=ActionKind.PACK_SKIP)
                            action = action_payload(game_action)
                            next_state = self._execute(game_action)
            case _:
                if self.poll_delay > 0:
                    sleep(self.poll_delay)
                action = action_payload(method="gamestate")
                next_state = self.client.gamestate()
        self._record("transition", before=state, action=action, after=next_state)
        return next_state

    def _execute(self, action: GameAction) -> dict[str, Any]:
        state, _executed = self._execute_tracked(action)
        return state

    def _execute_tracked(self, action: GameAction) -> tuple[dict[str, Any], bool]:
        method, params = action.to_balatrobot_rpc()
        try:
            return self.client.call_action(method, params), True
        except BalatroBotError as exc:
            message = str(exc)
            # The game can advance between the poll and the action (async
            # animations); re-read state instead of crashing the run.
            recoverable = (
                "failed to connect" in message
                or "requires one of these states" in message
                or "cannot be used at this time" in message
            )
            if not recoverable:
                raise
            if self.retry_delay > 0:
                sleep(self.retry_delay)
            return self.client.gamestate(), False

    def _note_use_refusal(self, state: dict[str, Any], action: GameAction) -> None:
        """Stop proposing a consumable the game keeps refusing to use.

        A refusal right after dealing is usually an animation race that a
        re-poll resolves; a persistent one would loop forever, so after a few
        attempts the consumable key is suppressed for the rest of the round.
        """
        cards = (state.get("consumables") or {}).get("cards") or []
        index = action.index if action.index is not None else -1
        if not 0 <= index < len(cards) or not isinstance(cards[index], dict):
            return
        key = str(cards[index].get("key") or "")
        if not key:
            return
        self._use_refusal_counts[key] = self._use_refusal_counts.get(key, 0) + 1
        if self._use_refusal_counts[key] >= self.use_refusal_retries:
            suppressed = getattr(self.policy, "suppressed_consumables", None)
            if suppressed is not None:
                suppressed.add(key)

    def _record(self, event: str, **payload: Any) -> None:
        if self.trace_writer is None:
            return
        serializable = {"run_id": self._run_id}
        for key, value in payload.items():
            serializable[key] = self.trace_writer.state_payload(value) if key in {"state", "before", "after"} else value
        self.trace_writer.record(event, **serializable)


def _shop_settled(state: dict[str, Any]) -> bool:
    for area in ("shop", "packs", "vouchers"):
        if ((state.get(area) or {}).get("cards")) :
            return True
    return False


def _pack_cards_available(state: dict[str, Any]) -> bool:
    cards = ((state.get("pack") or {}).get("cards") or [])
    return any(isinstance(card, dict) for card in cards)


def _pack_retry_key(state: dict[str, Any]) -> tuple[Any, ...]:
    cards = tuple(
        (card.get("id"), card.get("key"))
        for card in ((state.get("pack") or {}).get("cards") or [])
        if isinstance(card, dict)
    )
    return (state.get("seed"), state.get("ante_num"), state.get("round_num"), state.get("state"), cards)


def evaluate_balatrobot(
    seeds: list[str],
    *,
    client: BalatroBotClient | None = None,
    policy: BalatroBotPolicy | None = None,
    deck: str = "RED",
    stake: str = "WHITE",
    max_steps: int = 800,
    trace: bool = False,
    trace_writer: JsonlTraceWriter | None = None,
    poll_delay: float = 0.02,
    retry_delay: float = 0.05,
) -> dict[str, float | int]:
    runner = BalatroBotRunner(
        client or BalatroBotClient(),
        policy=policy or BalatroBotPolicy(),
        trace=trace,
        trace_writer=trace_writer,
        poll_delay=poll_delay,
        retry_delay=retry_delay,
    )
    wins = 0
    antes = 0
    steps = 0
    for seed in seeds:
        result = runner.play_run(deck=deck, stake=stake, seed=seed, max_steps=max_steps)
        wins += int(result.won)
        antes += result.ante
        steps += result.steps
    total = len(seeds)
    return {
        "seeds": total,
        "wins": wins,
        "win_rate": wins / max(total, 1),
        "avg_ante": antes / max(total, 1),
        "avg_steps": steps / max(total, 1),
    }


def _trace_state(state: dict[str, Any]) -> str:
    state_name = state.get("state")
    round_info = state.get("round") or {}
    shop = _card_summary(state, "shop")
    pack = _card_summary(state, "pack")
    consumables = _card_summary(state, "consumables")
    jokers = _card_summary(state, "jokers")
    return (
        f"state={state_name} ante={state.get('ante_num')} round={state.get('round_num')} "
        f"money={state.get('money')} chips={round_info.get('chips')} "
        f"hands={round_info.get('hands_left')} discards={round_info.get('discards_left')} "
        f"shop=[{shop}] pack=[{pack}] consumables=[{consumables}] jokers=[{jokers}]"
    )


def _card_summary(state: dict[str, Any], area: str) -> str:
    cards = ((state.get(area) or {}).get("cards") or [])
    parts = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        key = card.get("key")
        cost = (card.get("cost") or {}).get("buy")
        parts.append(f"{key}:${cost}")
    return ", ".join(parts)
