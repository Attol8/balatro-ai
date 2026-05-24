from balatro_ai_v2.fast.stakes import STAKE_RULES, stake_rule


def test_all_source_stakes_have_rule_specs() -> None:
    assert len(STAKE_RULES) == 8
    assert stake_rule("stake_white").level == 1
    assert stake_rule("stake_gold").level == 8


def test_cumulative_stake_modifiers_match_source_order() -> None:
    assert stake_rule("stake_red").no_small_blind_reward
    assert stake_rule("stake_green").scaling == 2
    assert stake_rule("stake_black").enable_eternals_in_shop
    assert stake_rule("stake_blue").discard_delta == -1
    assert stake_rule("stake_purple").scaling == 3
    assert stake_rule("stake_orange").enable_perishables_in_shop
    assert stake_rule("stake_gold").enable_rentals_in_shop
