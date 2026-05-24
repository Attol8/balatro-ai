from __future__ import annotations

from dataclasses import dataclass

from balatro_ai_v2.fast.jokers import Joker


@dataclass(frozen=True, slots=True)
class JokerEventResult:
    hands_delta: int = 0
    discards_delta: int = 0
    set_discards_to: int | None = None
    joker_slots_used_delta: int = 0
    consumable_slots_used_delta: int = 0
    playing_cards_created: int = 0
    created_keys: tuple[str, ...] = ()
    created_kinds: tuple[str, ...] = ()
    tags_created: tuple[str, ...] = ()
    disabled_boss_blind: bool = False
    sell_value_delta: int = 0
    all_sell_value_delta: int = 0
    x_mult_delta: float = 0.0
    hand_size_delta: int = 0
    destroyed_self: bool = False
    destroyed_selected_card: bool = False
    copied_joker_index: int | None = None
    duplicated_joker: bool = False
    allow_duplicate_shop_cards: bool = False
    card_bonus_chips_delta: int = 0
    card_enhancement_key: str | None = None
    level_up_played_hand: bool = False


@dataclass(frozen=True, slots=True)
class JokerEventContext:
    is_boss_blind: bool = False
    boss_blind_disabled: bool = False
    joker_slots_free: int = 0
    consumable_slots_free: int = 0
    current_discards_left: int = 0
    current_x_mult: float = 1.0
    current_hand_size_delta: int = 0
    rounds_elapsed: int = 0
    consumables_available: int = 0
    money: int = 0
    probability_success: bool = False
    is_first_hand: bool = False
    selected_count: int = 0
    selected_rank: int | None = None
    played_hand_kind: int | None = None
    played_hand_has_ace: bool = False
    played_hand_is_straight: bool = False
    played_hand_is_straight_flush: bool = False
    card_is_face: bool = False
    other_jokers_count: int = 0


EVENT_JOKERS = frozenset(
    {
        "j_burglar",
        "j_8_ball",
        "j_blueprint",
        "j_brainstorm",
        "j_burnt",
        "j_cartomancer",
        "j_certificate",
        "j_chicot",
        "j_diet_cola",
        "j_dna",
        "j_egg",
        "j_gift",
        "j_hallucination",
        "j_hiker",
        "j_invisible",
        "j_luchador",
        "j_marble",
        "j_midas_mask",
        "j_mr_bones",
        "j_perkeo",
        "j_riff_raff",
        "j_ring_master",
        "j_seance",
        "j_sixth_sense",
        "j_space",
        "j_superposition",
        "j_turtle_bean",
        "j_vagabond",
    }
)


def copy_target_index(joker_key: str, own_index: int, joker_count: int) -> int | None:
    if joker_key == "j_blueprint" and own_index + 1 < joker_count:
        return own_index + 1
    if joker_key == "j_brainstorm" and joker_count > 0:
        return 0
    if joker_key in EVENT_JOKERS:
        return None
    raise NotImplementedError(f"copy target is not implemented: {joker_key}")


def on_setting_blind(joker: Joker, context: JokerEventContext) -> JokerEventResult:
    if joker.key == "j_burglar":
        return JokerEventResult(hands_delta=3, set_discards_to=0)
    if joker.key == "j_chicot" and context.is_boss_blind and not context.boss_blind_disabled:
        return JokerEventResult(disabled_boss_blind=True)
    if joker.key == "j_riff_raff" and context.joker_slots_free > 0:
        count = min(2, context.joker_slots_free)
        return JokerEventResult(joker_slots_used_delta=count, created_kinds=("Joker",) * count)
    if joker.key == "j_cartomancer" and context.consumable_slots_free > 0:
        return JokerEventResult(consumable_slots_used_delta=1, created_kinds=("Tarot",))
    if joker.key == "j_marble":
        return JokerEventResult(playing_cards_created=1, created_keys=("m_stone",))
    if joker.key == "j_ring_master":
        return JokerEventResult(allow_duplicate_shop_cards=True)
    if joker.key in EVENT_JOKERS:
        return JokerEventResult()
    raise NotImplementedError(f"setting-blind event is not implemented: {joker.key}")


def on_first_hand_drawn(joker: Joker) -> JokerEventResult:
    if joker.key == "j_certificate":
        return JokerEventResult(playing_cards_created=1, created_keys=("seal_random",))
    if joker.key in EVENT_JOKERS:
        return JokerEventResult()
    raise NotImplementedError(f"first-hand-drawn event is not implemented: {joker.key}")


def on_scored_card(joker: Joker, context: JokerEventContext) -> JokerEventResult:
    if joker.key == "j_8_ball" and context.selected_rank == 6 and context.probability_success:
        return JokerEventResult(consumable_slots_used_delta=1, created_kinds=("Tarot",))
    if joker.key == "j_hiker":
        return JokerEventResult(card_bonus_chips_delta=5)
    if joker.key == "j_midas_mask" and context.card_is_face:
        return JokerEventResult(card_enhancement_key="m_gold")
    if joker.key in EVENT_JOKERS:
        return JokerEventResult()
    raise NotImplementedError(f"scored-card event is not implemented: {joker.key}")


def on_before_hand(joker: Joker, context: JokerEventContext) -> JokerEventResult:
    if joker.key == "j_space" and context.probability_success:
        return JokerEventResult(level_up_played_hand=True)
    if (
        joker.key == "j_sixth_sense"
        and context.is_first_hand
        and context.selected_count == 1
        and context.selected_rank == 4
        and context.consumable_slots_free > 0
    ):
        return JokerEventResult(
            consumable_slots_used_delta=1,
            created_kinds=("Spectral",),
            destroyed_selected_card=True,
        )
    if (
        joker.key == "j_superposition"
        and context.played_hand_has_ace
        and context.played_hand_is_straight
        and context.consumable_slots_free > 0
    ):
        return JokerEventResult(consumable_slots_used_delta=1, created_kinds=("Tarot",))
    if joker.key == "j_seance" and context.played_hand_is_straight_flush and context.consumable_slots_free > 0:
        return JokerEventResult(consumable_slots_used_delta=1, created_kinds=("Spectral",))
    if joker.key == "j_vagabond" and context.money <= 4 and context.consumable_slots_free > 0:
        return JokerEventResult(consumable_slots_used_delta=1, created_kinds=("Tarot",))
    if joker.key in EVENT_JOKERS:
        return JokerEventResult()
    raise NotImplementedError(f"before-hand event is not implemented: {joker.key}")


def on_discard(joker: Joker, context: JokerEventContext) -> JokerEventResult:
    if joker.key == "j_burnt" and context.is_first_hand:
        return JokerEventResult(level_up_played_hand=True)
    if joker.key == "j_dna" and context.is_first_hand and context.selected_count == 1:
        return JokerEventResult(playing_cards_created=1)
    if joker.key in EVENT_JOKERS:
        return JokerEventResult()
    raise NotImplementedError(f"discard event is not implemented: {joker.key}")


def on_open_booster(joker: Joker, context: JokerEventContext) -> JokerEventResult:
    if joker.key == "j_hallucination" and context.probability_success and context.consumable_slots_free > 0:
        return JokerEventResult(consumable_slots_used_delta=1, created_kinds=("Tarot",))
    if joker.key in EVENT_JOKERS:
        return JokerEventResult()
    raise NotImplementedError(f"open-booster event is not implemented: {joker.key}")


def on_selling_self(joker: Joker, context: JokerEventContext) -> JokerEventResult:
    if joker.key == "j_luchador" and context.is_boss_blind and not context.boss_blind_disabled:
        return JokerEventResult(disabled_boss_blind=True)
    if joker.key == "j_diet_cola":
        return JokerEventResult(tags_created=("tag_double",))
    if joker.key == "j_invisible" and context.rounds_elapsed >= 2 and context.other_jokers_count > 0:
        return JokerEventResult(duplicated_joker=True)
    if joker.key in EVENT_JOKERS:
        return JokerEventResult()
    raise NotImplementedError(f"selling-self event is not implemented: {joker.key}")


def on_end_of_round(joker: Joker, context: JokerEventContext) -> JokerEventResult:
    if joker.key == "j_egg":
        return JokerEventResult(sell_value_delta=3)
    if joker.key == "j_gift":
        return JokerEventResult(all_sell_value_delta=1)
    if joker.key == "j_turtle_bean":
        if context.current_hand_size_delta <= 1:
            return JokerEventResult(destroyed_self=True)
        return JokerEventResult(hand_size_delta=-1)
    if joker.key in EVENT_JOKERS:
        return JokerEventResult()
    raise NotImplementedError(f"end-of-round event is not implemented: {joker.key}")


def on_game_over(joker: Joker, chips_scored: int, blind_chips: int) -> JokerEventResult:
    if joker.key == "j_mr_bones" and chips_scored / max(blind_chips, 1) >= 0.25:
        return JokerEventResult(destroyed_self=True)
    if joker.key in EVENT_JOKERS:
        return JokerEventResult()
    raise NotImplementedError(f"game-over event is not implemented: {joker.key}")


def on_ending_shop(joker: Joker, context: JokerEventContext) -> JokerEventResult:
    if joker.key == "j_perkeo" and context.consumables_available > 0:
        return JokerEventResult(consumable_slots_used_delta=1, created_keys=("e_negative_consumable_copy",))
    if joker.key in EVENT_JOKERS:
        return JokerEventResult()
    raise NotImplementedError(f"ending-shop event is not implemented: {joker.key}")
