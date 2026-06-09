from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.balatrobot.adapter import card_to_fast_id, hand_to_fast_ids, sort_balatro_hand
from balatro_ai_v2.balatrobot.policy_config import DEFAULT_POLICY_CONFIG, TacticalPolicyConfig
from balatro_ai_v2.fast.blinds import BLIND_RULES, blind_blocks_hand
from balatro_ai_v2.fast.cards import chips as card_chips
from balatro_ai_v2.fast.cards import rank, suit
from balatro_ai_v2.fast.env import MAX_SELECTED_CARDS
from balatro_ai_v2.fast.hand import (
    BASE_CHIPS,
    BASE_MULT,
    FULL_HOUSE,
    HAND_KIND_NAMES,
    LEVEL_CHIPS,
    LEVEL_MULT,
    STRAIGHT,
    TWO_PAIR,
    FastScore,
    score_cards_with_joker_rules,
    score_cards_with_levels,
)
from balatro_ai_v2.fast.jokers import IMPLEMENTED_JOKERS, Joker, ScoreContext, apply_additive_jokers
from balatro_ai_v2.fast.modifiers import (
    Edition,
    Enhancement,
    edition_chip_bonus,
    edition_mult_bonus,
    edition_xmult,
    enhancement_chip_bonus,
    enhancement_mult_bonus,
    enhancement_xmult,
)

_LIVE_ENHANCEMENTS = {
    "BONUS": Enhancement.BONUS,
    "MULT": Enhancement.MULT,
    "WILD": Enhancement.WILD,
    "GLASS": Enhancement.GLASS,
    "STEEL": Enhancement.STEEL,
    "STONE": Enhancement.STONE,
    "GOLD": Enhancement.GOLD,
    "LUCKY": Enhancement.LUCKY,
}

_LIVE_EDITIONS = {
    "FOIL": Edition.FOIL,
    "HOLO": Edition.HOLOGRAPHIC,
    "HOLOGRAPHIC": Edition.HOLOGRAPHIC,
    "POLYCHROME": Edition.POLYCHROME,
    "NEGATIVE": Edition.NEGATIVE,
}


def _card_modifiers(card: dict[str, Any]) -> tuple[Enhancement, Edition]:
    modifier = card.get("modifier")
    enhancement = Enhancement.BASE
    edition = Edition.BASE
    if isinstance(modifier, dict):
        enhancement = _LIVE_ENHANCEMENTS.get(str(modifier.get("enhancement") or "").upper(), Enhancement.BASE)
        edition = _LIVE_EDITIONS.get(str(modifier.get("edition") or "").upper(), Edition.BASE)
    return enhancement, edition


@dataclass(frozen=True, slots=True)
class TacticalPlan:
    action: GameAction
    clears: bool
    projected_score: int


def plan_tactical_action(
    state: dict[str, Any],
    *,
    config: TacticalPolicyConfig = DEFAULT_POLICY_CONFIG.tactical,
    _use_cache: bool = True,
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
    joker_count = _joker_card_count(state)
    money = int(state.get("money") or 0)
    joker_slots = int(((state.get("jokers") or {}).get("limit") or 5))
    debuffed_suits = _active_debuffed_suits(state)
    debuffed_card_ids = _debuffed_card_ids(state, "hand") | _debuffed_card_ids(state, "cards")
    active_blind_key = _active_blind_key(state)
    previous_hand_names = _played_hand_names_this_round(state)
    states: list[tuple[GameAction | None, tuple[int, ...], tuple[int, ...], int, int, int, tuple[Joker, ...], tuple[str, ...]]] = [
        (None, hand, deck, current_score, hands_left, discards_left, jokers, previous_hand_names)
    ]
    best_action: GameAction | None = None
    best_score = current_score
    clears = current_score >= required
    ranked_cache: dict[
        tuple[
            tuple[int, ...],
            int,
            tuple[int, ...],
            tuple[Joker, ...],
            tuple[str, ...],
            int,
            int,
            int,
            int,
            int,
            int,
            str,
            frozenset[int],
            frozenset[int],
            int,
        ],
        tuple[tuple[int, FastScore], ...],
    ] = {}
    discard_cache: dict[tuple, tuple[int, ...]] = {}
    replace_cache: dict[tuple[tuple[int, ...], tuple[int, ...], int], tuple[tuple[int, ...], tuple[int, ...]]] = {}
    selected_cache: dict[tuple[tuple[int, ...], int], tuple[int, ...]] = {}
    action_cache: dict[tuple[int, bool], GameAction] = {}

    def ranked_play_masks_cached(
        hand_value: tuple[int, ...],
        jokers_value: tuple[Joker, ...],
        previous_hand_names_value: tuple[str, ...],
        discards_value: int,
        hands_value: int,
        deck_count_value: int,
    ) -> tuple[tuple[int, FastScore], ...]:
        key = (
            hand_value,
            highlighted_limit,
            levels,
            jokers_value,
            previous_hand_names_value,
            money,
            discards_value,
            hands_value,
            deck_count_value,
            joker_slots,
            joker_count,
            active_blind_key or "",
            debuffed_suits,
            debuffed_card_ids,
            config.action_beam,
        )
        if _use_cache and key in ranked_cache:
            return ranked_cache[key]
        result = _ranked_play_masks(
            hand_value,
            highlighted_limit,
            levels,
            jokers_value,
            previous_hand_names_value,
            money,
            discards_value,
            hands_value,
            deck_count_value,
            joker_slots,
            joker_count,
            active_blind_key,
            debuffed_suits,
            debuffed_card_ids,
            config.action_beam,
        )
        if _use_cache:
            ranked_cache[key] = result
        return result

    def discard_candidates_cached(
        hand_value: tuple[int, ...],
        deck_value: tuple[int, ...],
        jokers_value: tuple[Joker, ...],
        previous_hand_names_value: tuple[str, ...],
        discards_value: int,
        hands_value: int,
    ) -> tuple[int, ...]:
        key = (
            hand_value,
            deck_value,
            highlighted_limit,
            levels,
            jokers_value,
            previous_hand_names_value,
            money,
            discards_value,
            hands_value,
            joker_slots,
            joker_count,
            active_blind_key or "",
            debuffed_suits,
            debuffed_card_ids,
            config.action_beam,
        )
        if _use_cache and key in discard_cache:
            return discard_cache[key]
        result = _discard_candidates(
            hand_value,
            deck_value,
            highlighted_limit,
            levels,
            jokers_value,
            money,
            discards_value,
            hands_value,
            joker_slots,
            joker_count,
            active_blind_key,
            previous_hand_names_value,
            debuffed_suits,
            debuffed_card_ids,
            config.action_beam,
        )
        if _use_cache:
            discard_cache[key] = result
        return result

    def replace_selected_cached(
        hand_value: tuple[int, ...],
        deck_value: tuple[int, ...],
        mask_value: int,
    ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        key = (hand_value, deck_value, mask_value)
        if _use_cache and key in replace_cache:
            return replace_cache[key]
        result = _replace_selected(hand_value, deck_value, mask_value)
        if _use_cache:
            replace_cache[key] = result
        return result

    def selected_cards_cached(hand_value: tuple[int, ...], mask_value: int) -> tuple[int, ...]:
        key = (hand_value, mask_value)
        if _use_cache and key in selected_cache:
            return selected_cache[key]
        result = tuple(card for index, card in enumerate(hand_value) if mask_value & (1 << index))
        if _use_cache:
            selected_cache[key] = result
        return result

    def action_from_mask_cached(mask_value: int, *, is_discard: bool) -> GameAction:
        key = (mask_value, is_discard)
        if _use_cache and key in action_cache:
            return action_cache[key]
        result = _action_from_mask(mask_value, is_discard=is_discard)
        if _use_cache:
            action_cache[key] = result
        return result

    max_depth = max(hands_left + discards_left, 1)
    for _ in range(max_depth):
        next_states: list[tuple[GameAction, tuple[int, ...], tuple[int, ...], int, int, int, tuple[Joker, ...], tuple[str, ...]]] = []
        for first_action, hand_state, deck_state, score_state, hands_state, discards_state, jokers_state, previous_hand_names_state in states:
            if score_state >= required:
                assert first_action is not None
                return TacticalPlan(first_action, clears=True, projected_score=score_state)
            if hands_state <= 0 or not hand_state:
                continue

            for mask, scored in ranked_play_masks_cached(
                hand_state,
                jokers_state,
                previous_hand_names_state,
                discards_state,
                hands_state,
                len(deck_state),
            ):
                action = action_from_mask_cached(mask, is_discard=False)
                selected = selected_cards_cached(hand_state, mask)
                next_hand, next_deck = replace_selected_cached(hand_state, deck_state, mask)
                next_score = score_state + scored.total
                next_jokers = _jokers_after_play(jokers_state, scored, selected)
                next_previous_hand_names = previous_hand_names_state + (HAND_KIND_NAMES[scored.kind],)
                candidate_first = first_action or action
                if next_score > best_score:
                    best_score = next_score
                    best_action = candidate_first
                    clears = next_score >= required
                if next_score >= required:
                    return TacticalPlan(candidate_first, clears=True, projected_score=next_score)
                next_states.append(
                    (
                        candidate_first,
                        next_hand,
                        next_deck,
                        next_score,
                        hands_state - 1,
                        discards_state,
                        next_jokers,
                        next_previous_hand_names,
                    )
                )

            if discards_state > 0:
                for mask in discard_candidates_cached(
                    hand_state,
                    deck_state,
                    jokers_state,
                    previous_hand_names_state,
                    discards_state,
                    hands_state,
                ):
                    action = action_from_mask_cached(mask, is_discard=True)
                    next_hand, next_deck = replace_selected_cached(hand_state, deck_state, mask)
                    candidate_first = first_action or action
                    next_jokers = _jokers_after_discard(jokers_state)
                    next_states.append(
                        (
                            candidate_first,
                            next_hand,
                            next_deck,
                            score_state,
                            hands_state,
                            discards_state - 1,
                            next_jokers,
                            previous_hand_names_state,
                        )
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
    if not clears and _should_retry_wide_search(config, hands_left, discards_left):
        wide_config = TacticalPolicyConfig(
            beam_width=max(config.beam_width, 96),
            action_beam=max(config.action_beam, 96),
        )
        wide_plan = plan_tactical_action(state, config=wide_config, _use_cache=_use_cache)
        if wide_plan.clears or wide_plan.projected_score > best_score:
            return wide_plan
    return TacticalPlan(
        action=best_action,
        clears=clears,
        projected_score=best_score,
    )


def _should_retry_wide_search(config: TacticalPolicyConfig, hands_left: int, discards_left: int) -> bool:
    if config.beam_width >= 96 and config.action_beam >= 96:
        return False
    return hands_left >= 2 and discards_left > 0


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
            joker_count=_joker_card_count(state),
            active_blind_key=_active_blind_key(state),
            previous_hand_names=_played_hand_names_this_round(state),
            debuffed_suits=_active_debuffed_suits(state),
        )
        if best_score is None or score.total > best_score.total:
            best_mask = mask
            best_score = score
    if best_score is None:
        raise ValueError("BalatroBot state has no playable hand cards")
    return _action_from_mask(best_mask, is_discard=False), best_score


def score_play_action(
    state: dict[str, Any],
    action: GameAction,
    *,
    tarot_cards_used: int = 0,
) -> FastScore:
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
    levels = _hand_levels(state)
    hand_cards = (state.get("hand") or {}).get("cards") or []
    selected_pairs = sorted(
        (
            (hand[index], *_card_modifiers(hand_cards[index]))
            for index in action.indices
            if index < len(hand_cards)
        ),
        key=lambda item: item[0],
    )
    selected_enhancements = tuple(int(pair[1]) for pair in selected_pairs)
    selected_editions = tuple(int(pair[2]) for pair in selected_pairs)
    if _active_blind_key(state) == "bl_arm":
        # The Arm lowers the played hand's level before it scores.
        selected = tuple(sorted(card for index, card in enumerate(hand) if mask & (1 << index)))
        kind = score_cards_with_joker_rules(
            selected, levels, tuple(joker.key for joker in _jokers(state))
        ).kind
        if levels[kind] > 1:
            levels = tuple(
                level - 1 if index == kind else level for index, level in enumerate(levels)
            )
    return _score_mask(
        hand,
        mask,
        levels=levels,
        tarot_cards_used=tarot_cards_used,
        selected_enhancements=selected_enhancements,
        selected_editions=selected_editions,
        jokers=_jokers(state),
        money=int(state.get("money") or 0),
        discards_left=int((state.get("round") or {}).get("discards_left") or 0),
        hands_left=max(int((state.get("round") or {}).get("hands_left") or 0) - 1, 0),
        deck_count=int(((state.get("cards") or {}).get("count") or 52)),
        joker_slots=int(((state.get("jokers") or {}).get("limit") or 5)),
        joker_count=_joker_card_count(state),
        active_blind_key=_active_blind_key(state),
        previous_hand_names=_played_hand_names_this_round(state),
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
    joker_count: int | None = None,
    active_blind_key: str | None = None,
    previous_hand_names: tuple[str, ...] = (),
    debuffed_suits: frozenset[int] = frozenset(),
    debuffed_card_ids: frozenset[int] = frozenset(),
    tarot_cards_used: int = 0,
    selected_enhancements: tuple[int, ...] = (),
    selected_editions: tuple[int, ...] = (),
) -> FastScore:
    selected = tuple(card for index, card in enumerate(hand) if mask & (1 << index))
    sorted_cards = tuple(sorted(selected))
    held_cards = tuple(card for index, card in enumerate(hand) if not mask & (1 << index))
    return _score_selected_held(
        sorted_cards,
        held_cards,
        levels,
        jokers,
        money,
        discards_left,
        hands_left,
        deck_count,
        joker_slots,
        joker_count,
        active_blind_key,
        previous_hand_names,
        debuffed_suits,
        debuffed_card_ids,
        tarot_cards_used,
        selected_enhancements,
        selected_editions,
    )


def _score_selected_held(
    sorted_cards: tuple[int, ...],
    held_cards: tuple[int, ...],
    levels: tuple[int, ...],
    jokers: tuple[Joker, ...],
    money: int,
    discards_left: int,
    hands_left: int,
    deck_count: int,
    joker_slots: int,
    joker_count: int | None,
    active_blind_key: str | None,
    previous_hand_names: tuple[str, ...],
    debuffed_suits: frozenset[int],
    debuffed_card_ids: frozenset[int],
    tarot_cards_used: int = 0,
    selected_enhancements: tuple[int, ...] = (),
    selected_editions: tuple[int, ...] = (),
) -> FastScore:
    base = _apply_debuffs(
        _base_score_cached(sorted_cards, levels, tuple(joker.key for joker in jokers)),
        sorted_cards,
        debuffed_suits,
        debuffed_card_ids,
    )
    if active_blind_key and blind_blocks_hand(
        active_blind_key,
        hand_name=HAND_KIND_NAMES[base.kind],
        hand_size=len(sorted_cards),
        previous_hand_names=previous_hand_names,
        first_hand_name=previous_hand_names[0] if previous_hand_names else None,
    ):
        return FastScore(kind=base.kind, chips=0, mult=0, total=0, scoring_mask=0)
    if active_blind_key and BLIND_RULES[active_blind_key].halves_base_score:
        base = _halve_base_score(base, levels)
    context = ScoreContext(
        held_cards=held_cards,
        money=money,
        discards_left=discards_left,
        hands_left=hands_left,
        deck_count=deck_count,
        joker_count=joker_count,
        joker_slots=joker_slots,
        is_final_hand=hands_left <= 0,
        debuffed_held_suits=debuffed_suits,
        debuffed_held_cards=debuffed_card_ids,
        tarot_cards_used=tarot_cards_used,
        scoring_enhancements=selected_enhancements,
        scoring_editions=selected_editions,
    )
    return apply_additive_jokers(base, sorted_cards, len(sorted_cards), jokers, context)


def _halve_base_score(score: FastScore, levels: tuple[int, ...]) -> FastScore:
    level = max(levels[score.kind], 1)
    hand_chips = BASE_CHIPS[score.kind] + (level - 1) * LEVEL_CHIPS[score.kind]
    hand_mult = BASE_MULT[score.kind] + (level - 1) * LEVEL_MULT[score.kind]
    card_chips = score.chips - hand_chips
    halved_chips = max(int(hand_chips * 0.5 + 0.5), 0)
    halved_mult = max(int(hand_mult * 0.5 + 0.5), 1)
    chips = halved_chips + card_chips
    return FastScore(
        kind=score.kind,
        chips=chips,
        mult=halved_mult,
        total=int(chips * halved_mult),
        scoring_mask=score.scoring_mask,
    )


@lru_cache(maxsize=262_144)
def _base_score_cached(
    sorted_cards: tuple[int, ...],
    levels: tuple[int, ...],
    joker_keys: tuple[str, ...],
) -> FastScore:
    return score_cards_with_joker_rules(sorted_cards, levels, joker_keys)


def _ranked_play_masks(
    hand: tuple[int, ...],
    highlighted_limit: int,
    levels: tuple[int, ...],
    jokers: tuple[Joker, ...],
    previous_hand_names: tuple[str, ...],
    money: int,
    discards_left: int,
    hands_left: int,
    deck_count: int,
    joker_slots: int,
    joker_count: int | None,
    active_blind_key: str | None,
    debuffed_suits: frozenset[int],
    debuffed_card_ids: frozenset[int],
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
                joker_count=joker_count,
                active_blind_key=active_blind_key,
                previous_hand_names=previous_hand_names,
                debuffed_suits=debuffed_suits,
                debuffed_card_ids=debuffed_card_ids,
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
    jokers: tuple[Joker, ...],
    money: int,
    discards_left: int,
    hands_left: int,
    joker_slots: int,
    joker_count: int | None,
    active_blind_key: str | None,
    previous_hand_names: tuple[str, ...],
    debuffed_suits: frozenset[int],
    debuffed_card_ids: frozenset[int],
    beam: int,
) -> tuple[int, ...]:
    base_scored: list[tuple[int, int]] = []
    for mask in _legal_masks(len(hand), highlighted_limit):
        next_hand, next_deck = _replace_selected(hand, deck, mask)
        if not next_hand:
            continue
        base_scored.append((_best_score_with_levels(next_hand, highlighted_limit, levels), mask))
    base_scored.sort(reverse=True)
    shortlist = tuple(mask for _, mask in base_scored[: max(beam + beam // 2, 24)])
    if not _needs_joker_aware_discard(active_blind_key, jokers):
        return shortlist[:beam]

    scored: list[tuple[int, int]] = []
    for mask in shortlist:
        next_hand, next_deck = _replace_selected(hand, deck, mask)
        scored.append((
            _best_score_after_discard(
                next_hand,
                highlighted_limit,
                levels,
                jokers,
                money,
                max(discards_left - 1, 0),
                hands_left,
                len(next_deck),
                joker_slots,
                joker_count,
                active_blind_key,
                previous_hand_names,
                debuffed_suits,
                debuffed_card_ids,
            ),
            mask,
        ))
    scored.sort(reverse=True)
    return tuple(mask for _, mask in scored[:beam])


def _needs_joker_aware_discard(active_blind_key: str | None, jokers: tuple[Joker, ...]) -> bool:
    if active_blind_key in {"bl_mouth", "bl_eye", "bl_psychic"}:
        return True
    payoff_jokers = {"j_duo", "j_trio", "j_order", "j_tribe", "j_family", "j_card_sharp"}
    return any(joker.key in payoff_jokers for joker in jokers)


@lru_cache(maxsize=65_536)
def _best_score_after_discard(
    hand: tuple[int, ...],
    highlighted_limit: int,
    levels: tuple[int, ...],
    jokers: tuple[Joker, ...],
    money: int,
    discards_left: int,
    hands_left: int,
    deck_count: int,
    joker_slots: int,
    joker_count: int | None,
    active_blind_key: str | None,
    previous_hand_names: tuple[str, ...],
    debuffed_suits: frozenset[int],
    debuffed_card_ids: frozenset[int],
) -> int:
    return max(
        (
            _score_mask(
                hand,
                play_mask,
                levels=levels,
                jokers=jokers,
                money=money,
                discards_left=discards_left,
                hands_left=max(hands_left - 1, 0),
                deck_count=deck_count,
                joker_slots=joker_slots,
                joker_count=joker_count,
                active_blind_key=active_blind_key,
                previous_hand_names=previous_hand_names,
                debuffed_suits=debuffed_suits,
                debuffed_card_ids=debuffed_card_ids,
            ).total
            for play_mask in _legal_masks(len(hand), highlighted_limit)
        ),
        default=0,
    )


@lru_cache(maxsize=4096)
def _best_score_with_levels(hand: tuple[int, ...], highlighted_limit: int, levels: tuple[int, ...]) -> int:
    return max(
        score_cards_with_levels(
            tuple(sorted(card for index, card in enumerate(hand) if play_mask & (1 << index))),
            levels,
        ).total
        for play_mask in _legal_masks(len(hand), highlighted_limit)
    )


def _jokers_after_play(jokers: tuple[Joker, ...], score: FastScore, selected: tuple[int, ...]) -> tuple[Joker, ...]:
    out: list[Joker] = []
    selected_count = len(selected)
    has_scored_face = any(
        score.scoring_mask & (1 << index) and rank(card) in {9, 10, 11}
        for index, card in enumerate(tuple(sorted(selected)))
    )
    for joker in jokers:
        if joker.key == "j_square" and selected_count == 4:
            out.append(_replace_joker(joker, scaling=joker.scaling + 4))
        elif joker.key == "j_runner" and score.kind == STRAIGHT:
            out.append(_replace_joker(joker, scaling=joker.scaling + 15))
        elif joker.key == "j_trousers" and score.kind in {TWO_PAIR, FULL_HOUSE}:
            out.append(_replace_joker(joker, scaling=joker.scaling + 2))
        elif joker.key == "j_green_joker":
            out.append(_replace_joker(joker, scaling=joker.scaling + 1))
        elif joker.key == "j_ride_the_bus":
            out.append(_replace_joker(joker, scaling=0 if has_scored_face else joker.scaling + 1))
        else:
            out.append(joker)
    return tuple(out)


def _jokers_after_discard(jokers: tuple[Joker, ...]) -> tuple[Joker, ...]:
    out: list[Joker] = []
    for joker in jokers:
        if joker.key == "j_green_joker":
            out.append(_replace_joker(joker, scaling=max(joker.scaling - 1, 0)))
        else:
            out.append(joker)
    return tuple(out)


def _replace_joker(
    joker: Joker,
    *,
    scaling: int | None = None,
    x_mult: float | None = None,
) -> Joker:
    return Joker(
        key=joker.key,
        scaling=joker.scaling if scaling is None else scaling,
        x_mult=joker.x_mult if x_mult is None else x_mult,
        sell_value=joker.sell_value,
        edition=joker.edition,
    )


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


@lru_cache(maxsize=32)
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


def _active_blind_key(state: dict[str, Any]) -> str | None:
    active = _active_blind(state)
    if not active:
        return None
    name = str(active.get("name") or "")
    for key, rule in BLIND_RULES.items():
        if rule.name == name:
            return key
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


def _played_hand_names_this_round(state: dict[str, Any]) -> tuple[str, ...]:
    hands = state.get("hands") or {}
    return tuple(
        hand_name
        for hand_name in HAND_KIND_NAMES
        if int((hands.get(hand_name) or {}).get("played_this_round") or 0) > 0
    )


def _jokers(state: dict[str, Any]) -> tuple[Joker, ...]:
    cards = ((state.get("jokers") or {}).get("cards") or [])
    jokers: list[Joker] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        key = card.get("key")
        if key not in IMPLEMENTED_JOKERS:
            # Unmodeled jokers stay as inert slot-holders: they score nothing
            # themselves, but their edition bonus (foil/holo/poly) always
            # applies in the live game and must be replayed.
            jokers.append(
                Joker(
                    key=str(key or ""),
                    sell_value=int(((card.get("cost") or {}).get("sell") or 0)),
                    edition=int(_joker_edition(card)),
                )
            )
            continue
        ability = (card.get("value") or {}).get("ability") or {}
        if key == "j_ride_the_bus":
            scaling = _ability_number(ability, "mult")
        else:
            scaling = _ability_number(ability, "extra", "mult", "chips", "t_mult", "t_chips")
        x_mult = float(ability.get("Xmult") or ability.get("x_mult") or 1.0)
        sell_value = int(((card.get("cost") or {}).get("sell") or 0))
        jokers.append(
            Joker(
                key=key,
                scaling=scaling,
                x_mult=x_mult,
                sell_value=sell_value,
                edition=int(_joker_edition(card)),
            )
        )
    return tuple(jokers)


def _joker_card_count(state: dict[str, Any]) -> int:
    joker_area = state.get("jokers") or {}
    cards = joker_area.get("cards") or []
    return int(joker_area.get("count") or len([card for card in cards if isinstance(card, dict)]))


def _ability_number(ability: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = ability.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _joker_edition(card: dict[str, Any]) -> Edition:
    values: list[str] = []
    modifier = card.get("modifier")
    if isinstance(modifier, dict):
        values.extend(str(value) for value in modifier.values())
        values.extend(str(key) for key in modifier.keys())
    state = card.get("state")
    if isinstance(state, dict):
        values.extend(str(value) for value in state.values())
        values.extend(str(key) for key in state.keys())

    normalized = {value.lower() for value in values}
    if normalized & {"foil", "e_foil"}:
        return Edition.FOIL
    if normalized & {"holo", "holographic", "e_holo"}:
        return Edition.HOLOGRAPHIC
    if normalized & {"polychrome", "e_polychrome"}:
        return Edition.POLYCHROME
    if normalized & {"negative", "e_negative"}:
        return Edition.NEGATIVE
    return Edition.BASE


def _highlighted_limit(state: dict[str, Any]) -> int:
    return int(((state.get("hand") or {}).get("highlighted_limit") or MAX_SELECTED_CARDS))
