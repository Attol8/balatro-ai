from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from random import Random

from balatro_ai_v2.fast.cards import NUM_CARDS, rank, shuffled_deck, suit
from balatro_ai_v2.fast.hand import (
    HAND_KIND_NAMES,
    FastScore,
    best_score,
    score_cards_with_levels,
)

DISCARD_ACTION_OFFSET = 256
ACTION_SPACE_SIZE = 512
DEFAULT_HAND_SIZE = 8
MAX_SELECTED_CARDS = 5


@dataclass(frozen=True, slots=True)
class StepResult:
    observation: tuple[int, ...]
    reward: float
    terminated: bool
    info: dict[str, int | bool | tuple[int, ...]]


@dataclass(slots=True)
class FastBalatroEnv:
    """Small, allocation-light training env for tactical Balatro research.

    The action space is fixed:
    - 0..255: play the bitmask of current hand positions
    - 256..511: discard the bitmask of current hand positions

    This is deliberately not a BalatroBot wrapper. It is the local hot-loop env
    that search/self-play should use.
    """

    required_score: int = 300
    hands: int = 4
    discards: int = 3
    hand_size: int = DEFAULT_HAND_SIZE
    seed: int = 0

    deck: list[int] | None = None
    deck_pos: int = 0
    hand: list[int] | None = None
    score: int = 0
    hands_remaining: int = 0
    discards_remaining: int = 0
    rng: Random | None = None
    hand_levels: list[int] | None = None

    def reset(self, seed: int | None = None) -> tuple[int, ...]:
        if seed is not None:
            self.seed = seed
        self.rng = Random(self.seed)
        self.deck = shuffled_deck(self.seed)
        self.deck_pos = 0
        self.hand = self._draw(self.hand_size)
        self.score = 0
        self.hands_remaining = self.hands
        self.discards_remaining = self.discards
        self.hand_levels = [1] * len(HAND_KIND_NAMES)
        return self.observation()

    def legal_action_ids(self) -> tuple[int, ...]:
        self._require_active()
        assert self.hand is not None
        return _legal_actions(len(self.hand), self.discards_remaining > 0)

    def action_mask(self) -> tuple[int, ...]:
        self._require_active()
        assert self.hand is not None
        return _action_mask(len(self.hand), self.discards_remaining > 0)

    def greedy_play_action(self) -> int:
        assert self.hand is not None
        action_id, _ = best_score(tuple(self.hand), _legal_masks(len(self.hand)))
        return action_id

    def sample_legal_action(self) -> int:
        self._require_active()
        assert self.rng is not None
        actions = self.legal_action_ids()
        return actions[self.rng.randrange(len(actions))]

    def step(self, action_id: int) -> StepResult:
        self._require_active()
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
            reward = -0.01
            hand_kind = -1
            hand_score = 0
        else:
            assert self.hand is not None
            selected = tuple(card for index, card in enumerate(self.hand) if mask & (1 << index))
            assert self.hand_levels is not None
            score = score_cards_with_levels(selected, tuple(self.hand_levels))
            hand_score = score.total
            hand_kind = score.kind
            self.score += hand_score
            self.hands_remaining -= 1
            self._replace_selected(mask)
            reward = hand_score / max(self.required_score, 1)

        terminated = self.score >= self.required_score or self.hands_remaining <= 0
        if terminated:
            reward += 1.0 if self.score >= self.required_score else -1.0

        return StepResult(
            observation=self.observation(),
            reward=reward,
            terminated=terminated,
            info={
                "score": self.score,
                "required_score": self.required_score,
                "hands_remaining": self.hands_remaining,
                "discards_remaining": self.discards_remaining,
                "selected": selected,
                "is_discard": is_discard,
                "hand_score": hand_score,
                "hand_kind": hand_kind,
            },
        )

    def observation(self) -> tuple[int, ...]:
        assert self.hand is not None
        padded_hand = tuple(self.hand + [-1] * (self.hand_size - len(self.hand)))
        return (
            self.score,
            self.required_score,
            self.hands_remaining,
            self.discards_remaining,
            self.deck_pos,
            *(self.hand_levels or [1] * len(HAND_KIND_NAMES)),
            *padded_hand,
        )

    def feature_vector(self) -> tuple[float, ...]:
        assert self.hand is not None
        rank_counts = [0] * 13
        suit_counts = [0] * 4
        for card in self.hand:
            rank_counts[rank(card)] += 1
            suit_counts[suit(card)] += 1
        return (
            self.score / max(self.required_score, 1),
            self.hands_remaining / max(self.hands, 1),
            self.discards_remaining / max(self.discards, 1),
            (NUM_CARDS - self.deck_pos) / NUM_CARDS,
            *((level - 1) / 10 for level in (self.hand_levels or [1] * len(HAND_KIND_NAMES))),
            *(count / self.hand_size for count in rank_counts),
            *(count / self.hand_size for count in suit_counts),
        )

    def _draw(self, count: int) -> list[int]:
        assert self.deck is not None
        end = min(self.deck_pos + count, len(self.deck))
        drawn = self.deck[self.deck_pos : end]
        self.deck_pos = end
        return drawn

    def _replace_selected(self, mask: int) -> tuple[int, ...]:
        assert self.hand is not None
        selected: list[int] = []
        kept: list[int] = []
        for index, card in enumerate(self.hand):
            if mask & (1 << index):
                selected.append(card)
            else:
                kept.append(card)
        self.hand = kept + self._draw(self.hand_size - len(kept))
        return tuple(selected)

    def _validate_mask(self, mask: int) -> None:
        assert self.hand is not None
        if mask <= 0:
            raise ValueError("action must select at least one card")
        if mask >= (1 << len(self.hand)):
            raise ValueError("action references cards outside current hand")
        if mask.bit_count() > MAX_SELECTED_CARDS:
            raise ValueError("action cannot select more than five cards")

    def _require_active(self) -> None:
        if self.hand is None or self.deck is None:
            raise ValueError("environment has not been reset")
        if self.score >= self.required_score or self.hands_remaining <= 0:
            raise ValueError("environment episode is over")


def play_action(mask: int) -> int:
    if mask <= 0 or mask >= DISCARD_ACTION_OFFSET:
        raise ValueError("play mask must be in 1..255")
    return mask


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
