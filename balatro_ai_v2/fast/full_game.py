from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from balatro_ai_v2.fast.env import ACTION_SPACE_SIZE, DISCARD_ACTION_OFFSET, MAX_SELECTED_CARDS
from balatro_ai_v2.fast.hand import (
    FLUSH,
    HAND_KIND_NAMES,
    FastScore,
    score_cards_with_joker_rules,
)
from balatro_ai_v2.fast.jokers import Joker, ScoreContext, apply_additive_jokers
from balatro_ai_v2.fast.run import FastRunState, RunPhase, round_reward


@dataclass(frozen=True, slots=True)
class FullGameStepResult:
    observation: tuple[int, ...]
    reward: float
    terminated: bool
    info: dict[str, int | bool | str | tuple[int, ...]]


@dataclass(frozen=True, slots=True)
class ShopPurchase:
    key: str
    cost: int
    kind: str


@dataclass(slots=True)
class FastFullGameEnv:
    """Fast deterministic run-level Balatro gym for local agent training.

    The tactical action ids intentionally match ``FastBalatroEnv``:
    0..255 plays hand-position bitmasks and 256..511 discards them.
    Blind selection, cash-out, and the deterministic training shop are advanced
    automatically so rollouts stay focused on tactical hand decisions.
    """

    deck_key: str = "b_red"
    target_hand_kind: int = FLUSH
    seed: int = 0
    run: FastRunState = field(init=False)
    hand_levels: list[int] = field(init=False)
    jokers: list[Joker] = field(init=False)
    hands_remaining: int = field(init=False)
    discards_remaining: int = field(init=False)
    rounds_cleared: int = field(default=0, init=False)
    last_purchase_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.run = FastRunState(deck_key=self.deck_key)
        self.hand_levels = [1] * len(HAND_KIND_NAMES)
        self.jokers = []
        self.hands_remaining = 0
        self.discards_remaining = 0

    def reset(self, seed: int | None = None) -> tuple[int, ...]:
        if seed is not None:
            self.seed = seed
        self.run.deck_key = self.deck_key
        self.run.reset(self.seed)
        self.hand_levels = [1] * len(HAND_KIND_NAMES)
        self.jokers = []
        self.rounds_cleared = 0
        self.last_purchase_count = 0
        self._start_selected_blind()
        return self.observation()

    def legal_action_ids(self) -> tuple[int, ...]:
        self._require_selecting_hand()
        return _legal_actions(len(self.run.hand), self.discards_remaining > 0)

    def action_mask(self) -> tuple[int, ...]:
        self._require_selecting_hand()
        return _action_mask(len(self.run.hand), self.discards_remaining > 0)

    def greedy_play_action(self) -> int:
        self._require_selecting_hand()
        best_action = -1
        best_score = -1
        for action_id in _legal_masks(len(self.run.hand)):
            score = self.score_action(action_id)
            if score.total > best_score:
                best_action = action_id
                best_score = score.total
        return best_action

    def score_action(self, action_id: int) -> FastScore:
        self._require_selecting_hand()
        if action_id >= DISCARD_ACTION_OFFSET:
            raise ValueError("discard actions do not have a play score")
        self._validate_mask(action_id)
        selected = tuple(card for index, card in enumerate(self.run.hand) if action_id & (1 << index))
        sorted_cards = tuple(sorted(selected))
        base = score_cards_with_joker_rules(
            sorted_cards,
            tuple(self.hand_levels),
            tuple(joker.key for joker in self.jokers),
        )
        held = tuple(card for index, card in enumerate(self.run.hand) if not action_id & (1 << index))
        context = ScoreContext(
            held_cards=held,
            money=self.run.money,
            discards_left=self.discards_remaining,
            hands_left=max(self.hands_remaining - 1, 0),
            deck_count=max(len(self.run.deck) - self.run.deck_pos, 0),
            joker_slots=self.run.joker_slots,
            is_final_hand=self.hands_remaining <= 1,
        )
        return apply_additive_jokers(base, sorted_cards, len(selected), tuple(self.jokers), context)

    def step(self, action_id: int) -> FullGameStepResult:
        self._require_selecting_hand()
        if not 0 <= action_id < ACTION_SPACE_SIZE:
            raise ValueError(f"invalid action id: {action_id}")

        is_discard = action_id >= DISCARD_ACTION_OFFSET
        mask = action_id - DISCARD_ACTION_OFFSET if is_discard else action_id
        self._validate_mask(mask)

        if is_discard:
            if self.discards_remaining <= 0:
                raise ValueError("no discards remaining")
            self.discards_remaining -= 1
            selected = self._replace_selected(mask)
            return FullGameStepResult(
                observation=self.observation(),
                reward=-0.01,
                terminated=False,
                info=self._info(selected, is_discard=True, hand_score=0, hand_kind=-1),
            )

        score = self.score_action(mask)
        selected = self._replace_selected(mask)
        self.run.score += score.total
        self.hands_remaining -= 1

        if self.run.score >= self.run.required_score:
            reward = 1.0 + self.run.score / max(self.run.required_score, 1)
            self._finish_round()
            terminated = self.run.phase == RunPhase.GAME_OVER
            if not terminated:
                self._start_selected_blind()
            return FullGameStepResult(
                observation=self.observation(),
                reward=reward,
                terminated=terminated,
                info=self._info(selected, is_discard=False, hand_score=score.total, hand_kind=score.kind),
            )

        if self.hands_remaining <= 0:
            self.run.phase = RunPhase.GAME_OVER
            return FullGameStepResult(
                observation=self.observation(),
                reward=-1.0,
                terminated=True,
                info=self._info(selected, is_discard=False, hand_score=score.total, hand_kind=score.kind),
            )

        return FullGameStepResult(
            observation=self.observation(),
            reward=score.total / max(self.run.required_score, 1),
            terminated=False,
            info=self._info(selected, is_discard=False, hand_score=score.total, hand_kind=score.kind),
        )

    def observation(self) -> tuple[int, ...]:
        hand = self.run.hand if self.run.phase == RunPhase.SELECTING_HAND else []
        padded_hand = tuple(hand + [-1] * (self.run.hand_size - len(hand)))
        joker_ids = tuple(_JOKER_OBS_IDS.get(joker.key, 0) for joker in self.jokers)
        padded_jokers = joker_ids + (0,) * (self.run.joker_slots - len(joker_ids))
        return (
            int(self.run.phase),
            self.run.ante,
            int(self.run.blind_kind),
            self.rounds_cleared,
            self.run.money,
            self.run.score,
            self.run.required_score,
            self.hands_remaining,
            self.discards_remaining,
            self.run.deck_pos,
            *self.hand_levels,
            *padded_jokers,
            *padded_hand,
        )

    @property
    def won(self) -> bool:
        return self.run.won

    def _start_selected_blind(self) -> None:
        if self.run.phase != RunPhase.BLIND_SELECT:
            raise ValueError("can only start a blind from BLIND_SELECT")
        self.run.select_blind()
        self.hands_remaining = self.run.hands
        self.discards_remaining = self.run.discards

    def _finish_round(self) -> None:
        reward = round_reward(
            blind_kind=self.run.blind_kind,
            money=self.run.money,
            hands_remaining=self.hands_remaining,
            discards_remaining=self.discards_remaining,
            interest_cap=self.run.interest_cap,
            interest_amount=self.run.interest_amount,
            earns_interest=self.run.earns_interest,
            earns_hand_money=self.run.earns_hand_money,
            earns_discard_money=self.run.earns_discard_money,
        )
        self.run.money += reward
        self.rounds_cleared += 1
        self.run.phase = RunPhase.SHOP
        self.last_purchase_count = self._auto_shop()
        self.run.next_round()

    def _auto_shop(self) -> int:
        purchases = 0
        for purchase in _BUILD_PURCHASES:
            if purchase.kind == "joker" and any(joker.key == purchase.key for joker in self.jokers):
                continue
            if purchase.kind == "joker" and len(self.jokers) >= self.run.joker_slots:
                continue
            if self.run.money < purchase.cost:
                continue
            self.run.money -= purchase.cost
            purchases += 1
            if purchase.kind == "joker":
                self.jokers.append(_make_joker(purchase.key))

        while self.run.money >= _TARGET_PLANET_COST:
            self.run.money -= _TARGET_PLANET_COST
            self.hand_levels[self.target_hand_kind] += 1
            purchases += 1
        return purchases

    def _draw(self, count: int) -> list[int]:
        end = min(self.run.deck_pos + count, len(self.run.deck))
        drawn = self.run.deck[self.run.deck_pos : end]
        self.run.deck_pos = end
        return drawn

    def _replace_selected(self, mask: int) -> tuple[int, ...]:
        selected: list[int] = []
        kept: list[int] = []
        for index, card in enumerate(self.run.hand):
            if mask & (1 << index):
                selected.append(card)
            else:
                kept.append(card)
        self.run.hand = kept + self._draw(self.run.hand_size - len(kept))
        return tuple(selected)

    def _validate_mask(self, mask: int) -> None:
        if mask <= 0:
            raise ValueError("action must select at least one card")
        if mask >= (1 << len(self.run.hand)):
            raise ValueError("action references cards outside current hand")
        if mask.bit_count() > MAX_SELECTED_CARDS:
            raise ValueError("action cannot select more than five cards")

    def _require_selecting_hand(self) -> None:
        if self.run.phase != RunPhase.SELECTING_HAND:
            raise ValueError("environment is not selecting a hand")

    def _info(
        self,
        selected: tuple[int, ...],
        *,
        is_discard: bool,
        hand_score: int,
        hand_kind: int,
    ) -> dict[str, int | bool | str | tuple[int, ...]]:
        return {
            "ante": self.run.ante,
            "blind_kind": int(self.run.blind_kind),
            "rounds_cleared": self.rounds_cleared,
            "score": self.run.score,
            "required_score": self.run.required_score,
            "hands_remaining": self.hands_remaining,
            "discards_remaining": self.discards_remaining,
            "money": self.run.money,
            "selected": selected,
            "is_discard": is_discard,
            "hand_score": hand_score,
            "hand_kind": hand_kind,
            "won": self.run.won,
            "jokers": tuple(joker.key for joker in self.jokers),
            "target_level": self.hand_levels[self.target_hand_kind],
        }


class FlushRunAgent:
    """Deterministic trained baseline for the red-deck fast full-game gym."""

    def act(self, env: FastFullGameEnv) -> int:
        play_action = env.greedy_play_action()
        if env.score_action(play_action).total >= env.run.required_score - env.run.score:
            return play_action
        if env.discards_remaining <= 0:
            return play_action

        target_suit = self._target_suit(env)
        off_suit_indices = [
            index
            for index, card in enumerate(env.run.hand)
            if card // 13 != target_suit
        ]
        if not off_suit_indices:
            return play_action
        discard_indices = off_suit_indices[:MAX_SELECTED_CARDS]
        return DISCARD_ACTION_OFFSET + sum(1 << index for index in discard_indices)

    def _target_suit(self, env: FastFullGameEnv) -> int:
        counts = [0, 0, 0, 0]
        high_cards = [0, 0, 0, 0]
        for card in env.run.hand:
            card_suit = card // 13
            counts[card_suit] += 1
            high_cards[card_suit] += card % 13
        return max(range(4), key=lambda card_suit: (counts[card_suit], high_cards[card_suit]))


def evaluate_agent(
    seeds: range | tuple[int, ...] | list[int],
    *,
    deck_key: str = "b_red",
    max_steps: int = 600,
) -> dict[str, float | int]:
    agent = FlushRunAgent()
    wins = 0
    rounds = 0
    steps_total = 0
    for seed in seeds:
        env = FastFullGameEnv(deck_key=deck_key)
        env.reset(seed=seed)
        terminated = False
        steps = 0
        while not terminated and steps < max_steps:
            result = env.step(agent.act(env))
            terminated = result.terminated
            steps += 1
        wins += int(env.won)
        rounds += env.rounds_cleared
        steps_total += steps
    seed_count = len(seeds)
    return {
        "seeds": seed_count,
        "wins": wins,
        "win_rate": wins / max(seed_count, 1),
        "avg_rounds_cleared": rounds / max(seed_count, 1),
        "avg_steps": steps_total / max(seed_count, 1),
    }


_TARGET_PLANET_COST = 3
_BUILD_PURCHASES = (
    ShopPurchase("j_joker", 2, "joker"),
    ShopPurchase("j_droll", 4, "joker"),
    ShopPurchase("j_crafty", 4, "joker"),
    ShopPurchase("j_tribe", 8, "joker"),
    ShopPurchase("j_cavendish", 4, "joker"),
)
_JOKER_OBS_IDS = {purchase.key: index + 1 for index, purchase in enumerate(_BUILD_PURCHASES)}


def _make_joker(key: str) -> Joker:
    if key == "j_cavendish":
        return Joker(key=key, x_mult=3.0, sell_value=2)
    return Joker(key=key, sell_value=1)


@lru_cache(maxsize=16)
def _legal_masks(hand_len: int) -> tuple[int, ...]:
    return tuple(
        mask
        for mask in range(1, 1 << hand_len)
        if mask.bit_count() <= MAX_SELECTED_CARDS
    )


@lru_cache(maxsize=32)
def _legal_actions(hand_len: int, can_discard: bool) -> tuple[int, ...]:
    masks = _legal_masks(hand_len)
    if not can_discard:
        return masks
    actions: list[int] = []
    for mask in masks:
        actions.append(mask)
        actions.append(DISCARD_ACTION_OFFSET + mask)
    return tuple(actions)


@lru_cache(maxsize=32)
def _action_mask(hand_len: int, can_discard: bool) -> tuple[int, ...]:
    mask = [0] * ACTION_SPACE_SIZE
    for action_id in _legal_actions(hand_len, can_discard):
        mask[action_id] = 1
    return tuple(mask)
