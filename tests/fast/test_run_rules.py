from balatro_ai_v2.fast.run import BlindKind, FastRunState, blind_required_score, round_reward
from balatro_ai_v2.fast.run_rules import (
    RunModifiers,
    apply_deck,
    apply_voucher,
    starting_deck,
    tag_money_delta,
)


def test_core_vouchers_update_run_modifiers() -> None:
    modifiers = RunModifiers()

    modifiers = apply_voucher(modifiers, "v_overstock_norm")
    modifiers = apply_voucher(modifiers, "v_reroll_surplus")
    modifiers = apply_voucher(modifiers, "v_crystal_ball")
    modifiers = apply_voucher(modifiers, "v_grabber")
    modifiers = apply_voucher(modifiers, "v_wasteful")
    modifiers = apply_voucher(modifiers, "v_seed_money")
    modifiers = apply_voucher(modifiers, "v_antimatter")
    modifiers = apply_voucher(modifiers, "v_paint_brush")

    assert modifiers.shop_slots == 3
    assert modifiers.base_reroll_cost == 3
    assert modifiers.consumable_slots == 3
    assert modifiers.hands == 5
    assert modifiers.discards == 4
    assert modifiers.interest_cap == 50
    assert modifiers.joker_slots == 6
    assert modifiers.hand_size == 9


def test_decks_update_starting_modifiers() -> None:
    assert apply_deck(RunModifiers(), "b_red").discards == 4
    assert apply_deck(RunModifiers(), "b_blue").hands == 5
    assert apply_deck(RunModifiers(), "b_yellow").money == 14
    assert apply_deck(RunModifiers(), "b_black").joker_slots == 6
    assert apply_deck(RunModifiers(), "b_painted").hand_size == 10
    assert apply_deck(RunModifiers(), "b_plasma").blind_requirement_multiplier == 2.0


def test_special_starting_decks_have_expected_composition() -> None:
    abandoned = starting_deck("b_abandoned")
    checkered = starting_deck("b_checkered")
    erratic = starting_deck("b_erratic", seed=1)

    assert len(abandoned) == 40
    assert {card.rank for card in abandoned}.isdisjoint({9, 10, 11})
    assert len(checkered) == 52
    assert {card.suit for card in checkered} == {0, 1}
    assert len(erratic) == 52


def test_green_deck_reward_uses_discards_not_interest_or_hands() -> None:
    modifiers = apply_deck(RunModifiers(), "b_green")

    reward = round_reward(
        BlindKind.SMALL,
        money=100,
        hands_remaining=4,
        discards_remaining=3,
        earns_interest=modifiers.earns_interest,
        earns_hand_money=modifiers.earns_hand_money,
        earns_discard_money=modifiers.earns_discard_money,
    )

    assert reward == 3 + 3


def test_fast_run_reset_applies_deck_modifiers() -> None:
    run = FastRunState(deck_key="b_black").reset(seed=1)

    assert run.joker_slots == 6
    assert run.hands == 3


def test_plasma_deck_doubles_blind_requirement() -> None:
    assert blind_required_score(1, BlindKind.SMALL, blind_requirement_multiplier=2.0) == 600


def test_money_tags_return_exact_money_delta() -> None:
    assert tag_money_delta("tag_handy", hands_played=7) == 7
    assert tag_money_delta("tag_garbage", discards_unused=3) == 3
    assert tag_money_delta("tag_investment") == 25
    assert tag_money_delta("tag_economy", money=100) == 40
