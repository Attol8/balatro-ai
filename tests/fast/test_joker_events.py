from balatro_ai_v2.fast.joker_events import (
    EVENT_JOKERS,
    JokerEventContext,
    on_end_of_round,
    on_ending_shop,
    on_first_hand_drawn,
    on_game_over,
    on_before_hand,
    on_discard,
    on_open_booster,
    on_scored_card,
    on_selling_self,
    on_setting_blind,
    copy_target_index,
)
from balatro_ai_v2.fast.jokers import Joker


def test_event_joker_set_tracks_source_event_hooks() -> None:
    assert EVENT_JOKERS == {
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


def test_setting_blind_event_jokers_match_source_effects() -> None:
    context = JokerEventContext(
        is_boss_blind=True,
        joker_slots_free=3,
        consumable_slots_free=1,
        current_discards_left=2,
    )

    assert on_setting_blind(Joker("j_burglar"), context).hands_delta == 3
    assert on_setting_blind(Joker("j_burglar"), context).set_discards_to == 0
    assert on_setting_blind(Joker("j_chicot"), context).disabled_boss_blind
    assert on_setting_blind(Joker("j_riff_raff"), context).created_kinds == ("Joker", "Joker")
    assert on_setting_blind(Joker("j_cartomancer"), context).created_kinds == ("Tarot",)
    assert on_setting_blind(Joker("j_marble"), context).created_keys == ("m_stone",)
    assert on_setting_blind(Joker("j_ring_master"), context).allow_duplicate_shop_cards


def test_sell_and_round_end_event_jokers_match_source_effects() -> None:
    boss_context = JokerEventContext(is_boss_blind=True)

    assert on_selling_self(Joker("j_luchador"), boss_context).disabled_boss_blind
    assert on_selling_self(Joker("j_diet_cola"), boss_context).tags_created == ("tag_double",)
    assert on_selling_self(
        Joker("j_invisible"),
        JokerEventContext(rounds_elapsed=2, other_jokers_count=1),
    ).duplicated_joker
    assert on_end_of_round(Joker("j_egg"), JokerEventContext()).sell_value_delta == 3
    assert on_end_of_round(Joker("j_gift"), JokerEventContext()).all_sell_value_delta == 1
    assert on_end_of_round(
        Joker("j_turtle_bean"),
        JokerEventContext(current_hand_size_delta=3),
    ).hand_size_delta == -1
    assert on_end_of_round(
        Joker("j_turtle_bean"),
        JokerEventContext(current_hand_size_delta=1),
    ).destroyed_self


def test_create_and_save_event_jokers_match_source_effects() -> None:
    assert on_first_hand_drawn(Joker("j_certificate")).playing_cards_created == 1
    assert on_game_over(Joker("j_mr_bones"), chips_scored=25, blind_chips=100).destroyed_self
    assert on_ending_shop(
        Joker("j_perkeo"),
        JokerEventContext(consumables_available=1),
    ).created_keys == ("e_negative_consumable_copy",)


def test_copycat_and_card_mutation_event_jokers_match_source_effects() -> None:
    assert copy_target_index("j_blueprint", own_index=1, joker_count=3) == 2
    assert copy_target_index("j_brainstorm", own_index=2, joker_count=3) == 0
    assert on_scored_card(
        Joker("j_8_ball"),
        JokerEventContext(selected_rank=6, probability_success=True),
    ).created_kinds == ("Tarot",)
    assert on_scored_card(Joker("j_hiker"), JokerEventContext()).card_bonus_chips_delta == 5
    assert on_scored_card(
        Joker("j_midas_mask"),
        JokerEventContext(card_is_face=True),
    ).card_enhancement_key == "m_gold"


def test_consumable_creation_and_level_event_jokers_match_source_effects() -> None:
    assert on_before_hand(
        Joker("j_space"),
        JokerEventContext(probability_success=True),
    ).level_up_played_hand
    assert on_before_hand(
        Joker("j_sixth_sense"),
        JokerEventContext(is_first_hand=True, selected_count=1, selected_rank=4, consumable_slots_free=1),
    ).created_kinds == ("Spectral",)
    assert on_before_hand(
        Joker("j_superposition"),
        JokerEventContext(played_hand_has_ace=True, played_hand_is_straight=True, consumable_slots_free=1),
    ).created_kinds == ("Tarot",)
    assert on_before_hand(
        Joker("j_seance"),
        JokerEventContext(played_hand_is_straight_flush=True, consumable_slots_free=1),
    ).created_kinds == ("Spectral",)
    assert on_before_hand(
        Joker("j_vagabond"),
        JokerEventContext(money=4, consumable_slots_free=1),
    ).created_kinds == ("Tarot",)
    assert on_discard(Joker("j_burnt"), JokerEventContext(is_first_hand=True)).level_up_played_hand
    assert on_discard(
        Joker("j_dna"),
        JokerEventContext(is_first_hand=True, selected_count=1),
    ).playing_cards_created == 1
    assert on_open_booster(
        Joker("j_hallucination"),
        JokerEventContext(probability_success=True, consumable_slots_free=1),
    ).created_kinds == ("Tarot",)
