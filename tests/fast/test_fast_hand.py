import pytest

from balatro_ai_v2.fast.cards import NUM_RANKS
from balatro_ai_v2.fast.card_state import FastCardState
from balatro_ai_v2.fast.hand import (
    FLUSH,
    HIGH_CARD,
    PAIR,
    STRAIGHT,
    STRAIGHT_FLUSH,
    held_card_end_money,
    score_cards,
    score_card_states,
    score_cards_with_levels,
    score_cards_with_joker_rules,
    score_cards_with_jokers,
    score_cards_with_modifiers,
    score_cards_with_modifiers_exact,
)
from balatro_ai_v2.fast.jokers import Joker, ScoreContext, apply_additive_jokers
from balatro_ai_v2.fast.joker_money import (
    DollarBonusContext,
    MoneyEventContext,
    discard_money_delta,
    hand_money_delta,
    joker_dollar_bonus,
    scored_card_money_delta,
    total_joker_dollar_bonus,
)
from balatro_ai_v2.fast.modifiers import (
    Edition,
    Enhancement,
    Seal,
    edition_card_limit_delta,
    edition_chip_bonus,
    edition_mult_bonus,
    edition_xmult,
)


def card(rank: int, suit: int) -> int:
    return suit * NUM_RANKS + rank


def test_pair_scores_only_pair_cards() -> None:
    result = score_cards(
        (
            card(12, 0),
            card(12, 1),
            card(11, 2),
            card(5, 3),
            card(0, 0),
        )
    )

    assert result.kind == PAIR
    assert result.chips == 32
    assert result.mult == 2
    assert result.total == 64


def test_ace_low_straight() -> None:
    result = score_cards(
        (
            card(12, 0),
            card(0, 1),
            card(1, 2),
            card(2, 3),
            card(3, 0),
        )
    )

    assert result.kind == STRAIGHT


def test_straight_flush_beats_flush() -> None:
    result = score_cards(
        (
            card(7, 1),
            card(8, 1),
            card(9, 1),
            card(10, 1),
            card(11, 1),
        )
    )

    assert result.kind == STRAIGHT_FLUSH


def test_plain_flush() -> None:
    result = score_cards(
        (
            card(0, 2),
            card(3, 2),
            card(6, 2),
            card(8, 2),
            card(11, 2),
        )
    )

    assert result.kind == FLUSH


def test_hand_levels_apply_source_derived_chip_and_mult_increments() -> None:
    levels = [1] * 12
    levels[PAIR] = 3

    result = score_cards_with_levels(
        (
            card(12, 0),
            card(12, 1),
            card(11, 2),
            card(5, 3),
            card(0, 0),
        ),
        tuple(levels),
    )

    assert result.kind == PAIR
    assert result.chips == 32 + 2 * 15
    assert result.mult == 2 + 2 * 1
    assert result.total == 62 * 4


def test_deterministic_played_card_modifiers_score_in_scoring_order() -> None:
    levels = [1] * 12
    result = score_cards_with_modifiers(
        (
            card(12, 0),
            card(12, 1),
            card(11, 2),
            card(5, 3),
            card(0, 0),
        ),
        tuple(levels),
        (
            Enhancement.BONUS,
            Enhancement.MULT,
            Enhancement.BASE,
            Enhancement.BASE,
            Enhancement.BASE,
        ),
        (
            Edition.FOIL,
            Edition.HOLOGRAPHIC,
            Edition.BASE,
            Edition.BASE,
            Edition.BASE,
        ),
    )

    assert result.kind == PAIR
    assert result.chips == 32 + 30 + 50
    assert result.mult == 2 + 4 + 10
    assert result.total == 112 * 16


def test_probabilistic_lucky_modifier_is_not_silently_approximated() -> None:
    levels = [1] * 12

    with pytest.raises(NotImplementedError):
        score_cards_with_modifiers(
            (card(12, 0),),
            tuple(levels),
            (Enhancement.LUCKY,),
            (Edition.BASE,),
        )


def test_lucky_modifier_exact_path_uses_resolved_rng_triggers() -> None:
    levels = [1] * 12

    result = score_cards_with_modifiers_exact(
        (card(12, 0),),
        tuple(levels),
        (Enhancement.LUCKY,),
        (Edition.BASE,),
        lucky_mult_triggers=(True,),
        lucky_money_triggers=(True,),
    )

    assert result.score.chips == 16
    assert result.score.mult == 21
    assert result.score.total == 336
    assert result.money_delta == 20


def test_negative_edition_increases_card_limit_without_score_change() -> None:
    assert edition_card_limit_delta(Edition.BASE) == 0
    assert edition_card_limit_delta(Edition.NEGATIVE) == 1
    assert edition_chip_bonus(Edition.NEGATIVE) == 0
    assert edition_mult_bonus(Edition.NEGATIVE) == 0
    assert edition_xmult(Edition.NEGATIVE) == 1.0


def test_additive_joker_scores_flat_mult() -> None:
    levels = [1] * 12

    result = score_cards_with_jokers((card(12, 0),), tuple(levels), ("j_joker",))

    assert result.chips == 16
    assert result.mult == 5


def test_stored_value_jokers_apply_deterministic_score_modifiers() -> None:
    levels = [1] * 12
    base = score_cards_with_levels((card(12, 0),), tuple(levels))

    result = apply_additive_jokers(
        base,
        (card(12, 0),),
        1,
        (
            Joker("j_ceremonial", scaling=7),
            Joker("j_flash", scaling=4),
            Joker("j_trousers", scaling=6),
            Joker("j_square", scaling=12),
            Joker("j_stone", scaling=2),
        ),
    )

    assert result.chips == base.chips + 12 + 50
    assert result.mult == base.mult + 7 + 4 + 6


def test_growing_jokers_apply_current_hand_increment_before_scoring() -> None:
    levels = [1] * 12
    four_cards = tuple(sorted((
        card(8, 0),
        card(8, 1),
        card(6, 2),
        card(6, 3),
    )))
    base_two_pair = score_cards_with_levels(four_cards, tuple(levels))

    square_trousers = apply_additive_jokers(
        base_two_pair,
        four_cards,
        len(four_cards),
        (
            Joker("j_square", scaling=12),
            Joker("j_trousers", scaling=6),
        ),
    )

    assert square_trousers.chips == base_two_pair.chips + 16
    assert square_trousers.mult == base_two_pair.mult + 8

    straight_cards = tuple(sorted((
        card(4, 0),
        card(5, 1),
        card(6, 2),
        card(7, 3),
        card(8, 0),
    )))
    base_straight = score_cards_with_levels(straight_cards, tuple(levels))
    runner_green = apply_additive_jokers(
        base_straight,
        straight_cards,
        len(straight_cards),
        (
            Joker("j_runner", scaling=30),
            Joker("j_green_joker", scaling=4),
        ),
    )

    assert runner_green.chips == base_straight.chips + 45
    assert runner_green.mult == base_straight.mult + 5


def test_held_card_jokers_apply_per_card_effects() -> None:
    levels = [1] * 12
    base = score_cards_with_levels((card(12, 0),), tuple(levels))

    result = apply_additive_jokers(
        base,
        (card(12, 0),),
        1,
        (Joker("j_shoot_the_moon"), Joker("j_baron")),
        ScoreContext(held_cards=(card(10, 0), card(11, 1), card(11, 2))),
    )

    assert result.mult == base.mult + 13
    assert result.total == int(result.chips * result.mult * 2.25)


def test_raised_fist_is_disabled_when_lowest_held_card_is_debuffed() -> None:
    levels = [1] * 12
    base = score_cards_with_levels((card(12, 0),), tuple(levels))

    active = apply_additive_jokers(
        base,
        (card(12, 0),),
        1,
        (Joker("j_raised_fist"),),
        ScoreContext(held_cards=(card(6, 3), card(10, 0))),
    )
    debuffed_lowest = apply_additive_jokers(
        base,
        (card(12, 0),),
        1,
        (Joker("j_raised_fist"),),
        ScoreContext(held_cards=(card(6, 3), card(10, 0)), debuffed_held_suits=frozenset({3})),
    )

    assert active.mult == base.mult + 16
    assert debuffed_lowest.mult == base.mult


def test_card_sharp_requires_repeated_hand_this_round() -> None:
    levels = [1] * 12
    base = score_cards_with_levels((card(12, 0),), tuple(levels))

    inactive = apply_additive_jokers(
        base,
        (card(12, 0),),
        1,
        (Joker("j_card_sharp"),),
        ScoreContext(hand_times_played_round={base.kind: 1}),
    )
    active = apply_additive_jokers(
        base,
        (card(12, 0),),
        1,
        (Joker("j_card_sharp"),),
        ScoreContext(hand_times_played_round={base.kind: 2}),
    )

    assert inactive.total == base.total
    assert active.total == base.total * 3


def test_hand_rule_jokers_modify_hand_detection_and_scoring_mask() -> None:
    levels = [1] * 12

    four_finger_flush = score_cards_with_joker_rules(
        (card(2, 0), card(4, 0), card(6, 0), card(8, 0), card(12, 1)),
        tuple(levels),
        ("j_four_fingers",),
    )
    shortcut_straight = score_cards_with_joker_rules(
        (card(0, 0), card(2, 1), card(4, 2), card(6, 3), card(8, 0)),
        tuple(levels),
        ("j_shortcut",),
    )
    smeared_flush = score_cards_with_joker_rules(
        (card(2, 0), card(4, 2), card(6, 0), card(8, 2), card(12, 0)),
        tuple(levels),
        ("j_smeared",),
    )
    splash_high_card = score_cards_with_joker_rules(
        (card(2, 0), card(5, 1), card(8, 2)),
        tuple(levels),
        ("j_splash",),
    )

    assert four_finger_flush.kind == FLUSH
    assert four_finger_flush.scoring_mask.bit_count() == 4
    assert shortcut_straight.kind == STRAIGHT
    assert smeared_flush.kind == FLUSH
    assert splash_high_card.kind == HIGH_CARD
    assert splash_high_card.scoring_mask == 0b111


def test_pareidolia_makes_face_card_jokers_treat_all_scoring_cards_as_faces() -> None:
    levels = [1] * 12
    base = score_cards_with_levels((card(2, 0), card(5, 1)), tuple(levels))

    result = apply_additive_jokers(
        base,
        tuple(sorted((card(2, 0), card(5, 1)))),
        2,
        (Joker("j_pareidolia"), Joker("j_scary_face"), Joker("j_smiley")),
    )

    assert result.chips == base.chips + 30
    assert result.mult == base.mult + 5


def test_source_backed_context_jokers_apply_score_effects() -> None:
    levels = [1] * 12
    played = tuple(sorted((
        card(7, 0),
        card(7, 1),
        card(7, 2),
        card(7, 3),
        card(12, 0),
    )))
    base = score_cards_with_levels(played, tuple(levels))

    result = apply_additive_jokers(
        base,
        played,
        len(played),
        (
            Joker("j_ancient"),
            Joker("j_idol"),
            Joker("j_flower_pot"),
            Joker("j_drivers_license"),
            Joker("j_loyalty_card"),
        ),
        ScoreContext(
            current_ancient_suit=0,
            current_idol_rank=7,
            current_idol_suit=1,
            enhanced_card_count=16,
            loyalty_remaining=0,
        ),
    )

    assert result.total == int(result.chips * result.mult * 108)


def test_stored_state_and_deck_count_jokers_apply_score_effects() -> None:
    levels = [1] * 12
    base = score_cards_with_levels((card(12, 0),), tuple(levels))

    result = apply_additive_jokers(
        base,
        (card(12, 0),),
        1,
        (
            Joker("j_erosion"),
            Joker("j_fortune_teller"),
            Joker("j_raised_fist"),
            Joker("j_red_card", scaling=6),
            Joker("j_wee", scaling=16),
            Joker("j_castle", scaling=9),
            Joker("j_hologram", x_mult=1.5),
            Joker("j_campfire", x_mult=2.0),
        ),
        ScoreContext(
            held_cards=(card(0, 0), card(11, 1)),
            starting_deck_size=52,
            playing_card_count=49,
            tarot_cards_used=4,
        ),
    )

    assert result.chips == base.chips + 25
    assert result.mult == base.mult + 12 + 4 + 4 + 6
    assert result.total == int(result.chips * result.mult * 3)


def test_cash_out_joker_dollar_bonuses_are_source_backed() -> None:
    context = DollarBonusContext(
        deck_cards=(card(7, 0), card(7, 1), card(12, 0)),
        discards_used=0,
        discards_left=3,
        planets_used=frozenset({"c_pluto", "c_jupiter"}),
    )

    assert joker_dollar_bonus(Joker("j_golden"), context) == 4
    assert joker_dollar_bonus(Joker("j_cloud_9"), context) == 2
    assert joker_dollar_bonus(Joker("j_rocket", scaling=5), context) == 5
    assert joker_dollar_bonus(Joker("j_satellite"), context) == 2
    assert joker_dollar_bonus(Joker("j_delayed_grat"), context) == 6
    assert total_joker_dollar_bonus((Joker("j_golden"), Joker("j_cloud_9")), context) == 6


def test_money_event_jokers_are_source_backed() -> None:
    levels = [1] * 12
    score = score_cards_with_levels((card(12, 0),), tuple(levels))

    assert scored_card_money_delta(
        Joker("j_business"),
        card(9, 0),
        MoneyEventContext(probability_success=True),
    ) == 2
    assert scored_card_money_delta(
        Joker("j_reserved_parking"),
        card(2, 0),
        MoneyEventContext(probability_success=True, all_cards_are_face=True),
    ) == 1
    assert scored_card_money_delta(Joker("j_rough_gem"), card(2, 3)) == 1
    assert scored_card_money_delta(
        Joker("j_ticket"),
        card(2, 0),
        MoneyEventContext(card_has_gold_enhancement=True),
    ) == 4
    assert discard_money_delta(
        Joker("j_mail"),
        card(5, 0),
        MoneyEventContext(current_mail_rank=5),
    ) == 5
    assert discard_money_delta(
        Joker("j_faceless"),
        context=MoneyEventContext(discarded_face_count=3),
    ) == 5
    assert discard_money_delta(
        Joker("j_trading"),
        context=MoneyEventContext(discards_used=0, selected_count=1),
    ) == 3
    assert hand_money_delta(Joker("j_matador"), score, MoneyEventContext(blind_triggered=True)) == 8
    assert hand_money_delta(Joker("j_todo_list"), score, MoneyEventContext(todo_hand_kind=score.kind)) == 4


def test_additive_joker_scores_type_chips_and_mult() -> None:
    levels = [1] * 12

    result = score_cards_with_jokers(
        (
            card(12, 0),
            card(12, 1),
            card(11, 2),
            card(5, 3),
            card(0, 0),
        ),
        tuple(levels),
        ("j_jolly", "j_sly"),
    )

    assert result.kind == PAIR
    assert result.chips == 32 + 50
    assert result.mult == 2 + 8
    assert result.total == 82 * 10


def test_contained_hand_type_jokers_trigger_on_full_house() -> None:
    levels = [1] * 12

    result = score_cards_with_jokers(
        (
            card(12, 0),
            card(12, 1),
            card(12, 2),
            card(5, 3),
            card(5, 0),
        ),
        tuple(levels),
        ("j_jolly", "j_sly"),
    )

    assert result.chips == 40 + 11 + 11 + 11 + 7 + 7 + 50
    assert result.mult == 4 + 8


def test_additive_joker_scores_per_scored_suit_card() -> None:
    levels = [1] * 12

    result = score_cards_with_jokers(
        (
            card(12, 3),
            card(12, 1),
            card(11, 2),
            card(5, 3),
            card(0, 0),
        ),
        tuple(levels),
        ("j_greedy_joker",),
    )

    assert result.kind == PAIR
    assert result.mult == 2 + 3
    assert result.total == result.chips * 5


def test_additive_joker_scores_rank_condition_cards() -> None:
    levels = [1] * 12

    result = score_cards_with_jokers(
        (
            card(12, 0),
            card(12, 1),
        ),
        tuple(levels),
        ("j_scholar",),
    )

    assert result.kind == PAIR
    assert result.chips == 10 + 11 + 11 + 40
    assert result.mult == 2 + 8


def test_global_xmult_joker_scores_hand_family() -> None:
    levels = [1] * 12

    result = score_cards_with_jokers(
        (card(12, 0), card(12, 1)),
        tuple(levels),
        ("j_duo",),
    )

    assert result.chips == 32
    assert result.mult == 2
    assert result.total == 32 * 2 * 2


def test_money_and_deck_count_jokers_use_context() -> None:
    from balatro_ai_v2.fast.jokers import Joker, ScoreContext, apply_additive_jokers

    levels = [1] * 12
    base = score_cards_with_levels((card(12, 0),), tuple(levels))
    result = apply_additive_jokers(
        base,
        (card(12, 0),),
        1,
        (Joker("j_bull"), Joker("j_blue_joker")),
        ScoreContext(money=20, deck_count=40),
    )

    assert result.chips == 16 + 40 + 80
    assert result.total == 136


def test_state_scorer_applies_stone_cards_as_always_scoring() -> None:
    levels = [1] * 12
    result = score_card_states(
        (
            FastCardState(card(12, 0)),
            FastCardState(card(4, 1), enhancement=Enhancement.STONE),
        ),
        tuple(levels),
    )

    assert result.score.chips == 5 + 11 + 50
    assert result.score.mult == 1
    assert result.scoring_indices == (0, 1)


def test_state_scorer_applies_held_steel_cards() -> None:
    levels = [1] * 12
    result = score_card_states(
        (FastCardState(card(12, 0)),),
        tuple(levels),
        (FastCardState(card(2, 1), enhancement=Enhancement.STEEL),),
    )

    assert result.score.chips == 16
    assert result.score.mult == 1.5
    assert result.score.total == 24


def test_state_scorer_red_seal_retriggers_scored_card() -> None:
    levels = [1] * 12
    result = score_card_states(
        (
            FastCardState(
                card(12, 0),
                enhancement=Enhancement.MULT,
                edition=Edition.FOIL,
                seal=Seal.RED,
            ),
        ),
        tuple(levels),
    )

    assert result.score.chips == 16 + 50 + 50
    assert result.score.mult == 1 + 4 + 4
    assert result.score.total == 116 * 9


def test_state_scorer_gold_seal_grants_money_when_scored() -> None:
    levels = [1] * 12
    result = score_card_states(
        (FastCardState(card(12, 0), seal=Seal.GOLD),),
        tuple(levels),
    )

    assert result.money_delta == 3


def test_held_gold_cards_grant_end_round_money() -> None:
    assert (
        held_card_end_money(
            (
                FastCardState(card(3, 0), enhancement=Enhancement.GOLD),
                FastCardState(card(4, 0), enhancement=Enhancement.BASE),
            )
        )
        == 3
    )
