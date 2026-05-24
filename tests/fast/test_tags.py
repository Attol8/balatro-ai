from balatro_ai_v2.fast.tags import TAG_RULES, TagTrigger, tag_money_delta, tag_rule


def test_all_source_tags_have_rule_specs() -> None:
    assert len(TAG_RULES) == 24
    assert tag_rule("tag_uncommon").trigger == TagTrigger.STORE_JOKER_CREATE
    assert tag_rule("tag_negative").joker_edition == "negative"
    assert tag_rule("tag_charm").free_pack_keys == ("p_arcana_mega_1", "p_arcana_mega_2")
    assert tag_rule("tag_double").duplicates_next_tag
    assert tag_rule("tag_d_six").free_reroll


def test_tag_money_delta_matches_source_configs() -> None:
    assert tag_money_delta("tag_handy", hands_played=7) == 7
    assert tag_money_delta("tag_garbage", discards_unused=3) == 3
    assert tag_money_delta("tag_investment") == 25
    assert tag_money_delta("tag_economy", money=100) == 40
    assert tag_money_delta("tag_economy", money=-2) == 0
    assert tag_money_delta("tag_skip", skips=4) == 20


def test_non_money_tags_have_zero_money_delta() -> None:
    assert tag_money_delta("tag_charm") == 0
    assert tag_money_delta("tag_coupon") == 0
