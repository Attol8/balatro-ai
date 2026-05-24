from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.balatrobot.adapter import card_to_fast_id, hand_to_fast_ids, sort_balatro_hand
from balatro_ai_v2.balatrobot.policy_config import DEFAULT_POLICY_CONFIG, TacticalPolicyConfig
from balatro_ai_v2.fast.cards import chips as card_chips
from balatro_ai_v2.fast.cards import suit
from balatro_ai_v2.fast.env import MAX_SELECTED_CARDS
from balatro_ai_v2.fast.hand import HAND_KIND_NAMES, FastScore, score_cards_with_levels
from balatro_ai_v2.fast.jokers import IMPLEMENTED_JOKERS, Joker, ScoreContext, apply_additive_jokers


@dataclass(frozen=True, slots=True)
class TacticalPlan:
    action: GameAction
    clears: bool
    projected_score: int


def plan_tactical_action(
    state: dict[str, Any],
    *,
    config: TacticalPolicyConfig = DEFAULT_POLICY_CONFIG.tactical,
) -> TacticalPlan:
    hand = hand_to_fast_ids(state)
    if not hand:
        raise ValueError("BalatroBot state has no hand cards")

    deck = _deck_ids(state)
    required = _active_required_score(state)
    current_score = int((state.get("round") or {}).get("chips") or 0)
    hands_left = int((state.get("round") or {}).get("hands_left") or 0)
    discards_left = int((state.get("round") or {}).get("discards_left") or 0)
    highlighted_limit = _highlighted_limit(state)
    levels = _hand_levels(state)
    jokers = _jokers(state)
    money = int(state.get("money") or 0)
    joker_slots = int(((state.get("jokers") or {}).get("limit") or 5))
    debuffed_suits = _active_debuffed_suits(state)
    states: list[tuple[GameAction | None, tuple[int, ...], tuple[int, ...], int, int, int]] = [
        (None, hand, deck, current_score, hands_left, discards_left)
    ]
    best_action: GameAction | None = None
    best_score = current_score
    clears = current_score >= required

    max_depth = max(hands_left + discards_left, 1)
    for _ in range(max_depth):
        next_states: list[tuple[GameAction, tuple[int, ...], tuple[int, ...], int, int, int]] = []
        for first_action, hand_state, deck_state, score_state, hands_state, discards_state in states:
            if score_state >= required:
                assert first_action is not None
                return TacticalPlan(first_action, clears=True, projected_score=score_state)
            if hands_state <= 0 or not hand_state:
                continue

            for mask, scored in _ranked_play_masks(
                hand_state,
                highlighted_limit,
                levels,
                jokers,
                money,
                discards_state,
                hands_state,
                len(deck_state),
                joker_slots,
                debuffed_suits,
                config.action_beam,
            ):
                action = _action_from_mask(mask, is_discard=False)
                next_hand, next_deck = _replace_selected(hand_state, deck_state, mask)
                next_score = score_state + scored.total
                candidate_first = first_action or action
                if next_score > best_score:
                    best_score = next_score
                    best_action = candidate_first
                    clears = next_score >= required
                if next_score >= required:
                    return TacticalPlan(candidate_first, clears=True, projected_score=next_score)
                next_states.append(
                    (candidate_first, next_hand, next_deck, next_score, hands_state - 1, discards_state)
                )

            if discards_state > 0:
                for mask in _discard_candidates(hand_state, deck_state, highlighted_limit, levels, config.action_beam):
                    action = _action_from_mask(mask, is_discard=True)
                    next_hand, next_deck = _replace_selected(hand_state, deck_state, mask)
                    candidate_first = first_action or action
                    next_states.append(
                        (candidate_first, next_hand, next_deck, score_state, hands_state, discards_state - 1)
                    )

        if not next_states:
            break
        next_states.sort(
            key=lambda item: (
                item[3] >= required,
                item[3],
                item[4],
                item[5],
            ),
            reverse=True,
        )
        states = next_states[: config.beam_width]

    if best_action is None:
        best_action, best_play = best_play_action(state)
        best_score = current_score + best_play.total
    return TacticalPlan(
        action=best_action,
        clears=clears,
        projected_score=best_score,
    )


def best_play_action(state: dict[str, Any]) -> tuple[GameAction, FastScore]:
    hand = hand_to_fast_ids(state)
    best_mask = -1
    best_score: FastScore | None = None
    for mask in _legal_masks(len(hand), _highlighted_limit(state)):
        score = _score_mask(
            hand,
            mask,
            levels=_hand_levels(state),
            jokers=_jokers(state),
            money=int(state.get("money") or 0),
            discards_left=int((state.get("round") or {}).get("discards_left") or 0),
            hands_left=max(int((state.get("round") or {}).get("hands_left") or 0) - 1, 0),
            deck_count=int(((state.get("cards") or {}).get("count") or 52)),
            joker_slots=int(((state.get("jokers") or {}).get("limit") or 5)),
            debuffed_suits=_active_debuffed_suits(state),
        )
        if best_score is None or score.total > best_score.total:
            best_mask = mask
            best_score = score
    if best_score is None:
        raise ValueError("BalatroBot state has no playable hand cards")
    return _action_from_mask(best_mask, is_discard=False), best_score


def score_play_action(state: dict[str, Any], action: GameAction) -> FastScore:
    if action.kind != ActionKind.PLAY:
        raise ValueError(f"cannot score non-play action: {action.kind.value}")
    hand = hand_to_fast_ids(state)
    mask = sum(1 << index for index in action.indices)
    if mask <= 0:
        raise ValueError("play action must select at least one card")
    if mask >= (1 << len(hand)):
        raise ValueError("play action references cards outside current hand")
    if mask.bit_count() > _highlighted_limit(state):
        raise ValueError("play action exceeds highlighted card limit")
    return _score_mask(
        hand,
        mask,
        levels=_hand_levels(state),
        jokers=_jokers(state),
        money=int(state.get("money") or 0),
        discards_left=int((state.get("round") or {}).get("discards_left") or 0),
        hands_left=max(int((state.get("round") or {}).get("hands_left") or 0) - 1, 0),
        deck_count=int(((state.get("cards") or {}).get("count") or 52)),
        joker_slots=int(((state.get("jokers") or {}).get("limit") or 5)),
        debuffed_suits=_active_debuffed_suits(state),
        debuffed_card_ids=_debuffed_card_ids(state, "hand"),
    )


def _score_mask(
    hand: tuple[int, ...],
    mask: int,
    *,
    levels: tuple[int, ...],
    jokers: tuple[Joker, ...],
    money: int,
    discards_left: int,
    hands_left: int,
    deck_count: int,
    joker_slots: int,
    debuffed_suits: frozenset[int] = frozenset(),
    debuffed_card_ids: frozenset[int] = frozenset(),
) -> FastScore:
    selected = tuple(card for index, card in enumerate(hand) if mask & (1 << index))
    sorted_cards = tuple(sorted(selected))
    base = _apply_debuffs(
        score_cards_with_levels(sorted_cards, levels),
        sorted_cards,
        debuffed_suits,
        debuffed_card_ids,
    )
    context = ScoreContext(
        held_cards=tuple(card for index, card in enumerate(hand) if not mask & (1 << index)),
        money=money,
        discards_left=discards_left,
        hands_left=hands_left,
        deck_count=deck_count,
        joker_slots=joker_slots,
        is_final_hand=hands_left <= 0,
    )
    return apply_additive_jokers(base, sorted_cards, len(selected), jokers, context)


def _ranked_play_masks(
    hand: tuple[int, ...],
    highlighted_limit: int,
    levels: tuple[int, ...],
    jokers: tuple[Joker, ...],
    money: int,
    discards_left: int,
    hands_left: int,
    deck_count: int,
    joker_slots: int,
    debuffed_suits: frozenset[int],
    beam: int,
) -> tuple[tuple[int, FastScore], ...]:
    scored = [
        (
            mask,
            _score_mask(
                hand,
                mask,
                levels=levels,
                jokers=jokers,
                money=money,
                discards_left=discards_left,
                hands_left=max(hands_left - 1, 0),
                deck_count=deck_count,
                joker_slots=joker_slots,
                debuffed_suits=debuffed_suits,
            ),
        )
        for mask in _legal_masks(len(hand), highlighted_limit)
    ]
    scored.sort(key=lambda item: item[1].total, reverse=True)
    return tuple(scored[:beam])


def _discard_candidates(
    hand: tuple[int, ...],
    deck: tuple[int, ...],
    highlighted_limit: int,
    levels: tuple[int, ...],
    beam: int,
) -> tuple[int, ...]:
    scored: list[tuple[int, int]] = []
    for mask in _legal_masks(len(hand), highlighted_limit):
        next_hand, _ = _replace_selected(hand, deck, mask)
        if not next_hand:
            continue
        best_next = max(
            score_cards_with_levels(
                tuple(sorted(card for index, card in enumerate(next_hand) if play_mask & (1 << index))),
                levels,
            ).total
            for play_mask in _legal_masks(len(next_hand), highlighted_limit)
        )
        scored.append((best_next, mask))
    scored.sort(reverse=True)
    return tuple(mask for _, mask in scored[:beam])


def _replace_selected(
    hand: tuple[int, ...],
    deck: tuple[int, ...],
    mask: int,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    kept = tuple(card for index, card in enumerate(hand) if not mask & (1 << index))
    draw_count = min(len(hand) - len(kept), len(deck))
    drawn = deck[-draw_count:] if draw_count else ()
    next_deck = deck[:-draw_count] if draw_count else deck
    return sort_balatro_hand(kept + drawn), next_deck


def _legal_masks(hand_len: int, highlighted_limit: int) -> tuple[int, ...]:
    max_selected = min(highlighted_limit, MAX_SELECTED_CARDS, hand_len)
    return tuple(
        mask
        for mask in range(1, 1 << hand_len)
        if mask.bit_count() <= max_selected
    )


def _action_from_mask(mask: int, *, is_discard: bool) -> GameAction:
    indices = tuple(index for index in range(mask.bit_length()) if mask & (1 << index))
    return GameAction(
        kind=ActionKind.DISCARD if is_discard else ActionKind.PLAY,
        indices=indices,
    )


def _deck_ids(state: dict[str, Any]) -> tuple[int, ...]:
    cards = ((state.get("cards") or {}).get("cards") or [])
    out: list[int] = []
    for card in cards:
        if isinstance(card, dict):
            out.append(card_to_fast_id(card))
    return tuple(out)


def _apply_debuffs(
    score: FastScore,
    sorted_cards: tuple[int, ...],
    debuffed_suits: frozenset[int],
    debuffed_card_ids: frozenset[int] = frozenset(),
) -> FastScore:
    if not debuffed_suits and not debuffed_card_ids:
        return score
    debuffed_scoring_mask = 0
    chip_penalty = 0
    for index, card in enumerate(sorted_cards):
        if not score.scoring_mask & (1 << index):
            continue
        if suit(card) not in debuffed_suits and card not in debuffed_card_ids:
            continue
        debuffed_scoring_mask |= 1 << index
        chip_penalty += card_chips(card)
    if chip_penalty <= 0:
        return score
    chips = max(score.chips - chip_penalty, 0)
    return FastScore(
        kind=score.kind,
        chips=chips,
        mult=score.mult,
        total=int(chips * score.mult),
        scoring_mask=score.scoring_mask & ~debuffed_scoring_mask,
    )


def _active_debuffed_suits(state: dict[str, Any]) -> frozenset[int]:
    active = _active_blind(state)
    if not active:
        return frozenset()
    text = f"{active.get('name') or ''} {active.get('effect') or ''}".lower()
    debuffed: set[int] = set()
    if "spade" in text and "debuff" in text:
        debuffed.add(0)
    if "heart" in text and "debuff" in text:
        debuffed.add(1)
    if "club" in text and "debuff" in text:
        debuffed.add(2)
    if "diamond" in text and "debuff" in text:
        debuffed.add(3)
    return frozenset(debuffed)


def _debuffed_card_ids(state: dict[str, Any], area: str) -> frozenset[int]:
    cards = ((state.get(area) or {}).get("cards") or [])
    out: set[int] = set()
    for card in cards:
        if not isinstance(card, dict):
            continue
        card_state = card.get("state") or {}
        if isinstance(card_state, dict) and card_state.get("debuff"):
            out.add(card_to_fast_id(card))
    return frozenset(out)


def _active_blind(state: dict[str, Any]) -> dict[str, Any] | None:
    blinds = state.get("blinds") or {}
    for blind in blinds.values():
        if isinstance(blind, dict) and blind.get("status") == "CURRENT":
            return blind
    return None


def _active_required_score(state: dict[str, Any]) -> int:
    blinds = state.get("blinds") or {}
    for blind in blinds.values():
        if isinstance(blind, dict) and blind.get("status") == "CURRENT":
            return int(blind.get("score") or 1)
    return max(
        (
            int(blind.get("score") or 0)
            for blind in blinds.values()
            if isinstance(blind, dict)
        ),
        default=1,
    )


def _hand_levels(state: dict[str, Any]) -> tuple[int, ...]:
    hands = state.get("hands") or {}
    return tuple(
        int((hands.get(hand_name) or {}).get("level") or 1)
        for hand_name in HAND_KIND_NAMES
    )


def _jokers(state: dict[str, Any]) -> tuple[Joker, ...]:
    cards = ((state.get("jokers") or {}).get("cards") or [])
    jokers: list[Joker] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        key = card.get("key")
        if key not in IMPLEMENTED_JOKERS:
            continue
        ability = (card.get("value") or {}).get("ability") or {}
        if key == "j_ride_the_bus":
            scaling = _ability_number(ability, "mult")
        else:
            scaling = _ability_number(ability, "extra", "mult", "chips", "t_mult", "t_chips")
        x_mult = float(ability.get("Xmult") or ability.get("x_mult") or 1.0)
        sell_value = int(((card.get("cost") or {}).get("sell") or 0))
        jokers.append(Joker(key=key, scaling=scaling, x_mult=x_mult, sell_value=sell_value))
    return tuple(jokers)


def _ability_number(ability: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = ability.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _highlighted_limit(state: dict[str, Any]) -> int:
    return int(((state.get("hand") or {}).get("highlighted_limit") or MAX_SELECTED_CARDS))
