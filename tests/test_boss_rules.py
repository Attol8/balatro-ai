from balatro_ai_v2.boss_rules import (
    BossConstraint,
    FaceDownMode,
    JokerDisruption,
    all_boss_rules,
    boss_rule,
)


def test_catalog_has_exactly_28_unique_vanilla_names():
    rules = all_boss_rules()
    assert len(rules) == 28
    assert len({rule.name for rule in rules}) == 28


def test_representative_public_constraints():
    assert boss_rule("The Wall").score_multiplier == 4
    assert boss_rule("  the wall ").high_target
    assert boss_rule("The Psychic").min_selected_cards == 5
    assert boss_rule("The Water").discards_forced == 0
    assert boss_rule("The Needle").hands_forced == 1
    assert boss_rule("The Club").suit_debuff == ("C",)
    assert boss_rule("The Plant").face_debuff
    assert boss_rule("The Arm").level_reduction == 1
    assert boss_rule("The Eye").repeat_hand_restriction
    assert boss_rule("The Mouth").single_hand_family
    assert boss_rule("Crimson Heart").joker_debuff
    assert boss_rule("Verdant Leaf").sell_to_disable
    assert BossConstraint.SCORE_REDUCTION in boss_rule("The Flint").constraints
    assert boss_rule("The Serpent").draw_count_override == 3
    assert boss_rule("The Ox").money_reset_on_most_played_hand
    assert boss_rule("The Tooth").money_per_card == 1
    assert boss_rule("The Fish").face_down_mode == FaceDownMode.AFTER_PLAY
    assert boss_rule("The House").face_down_mode == FaceDownMode.FIRST_HAND
    assert boss_rule("The Mark").face_down_mode == FaceDownMode.FACE_RANKS
    assert boss_rule("The Wheel").face_down_mode == FaceDownMode.RANDOM_DRAW
    assert boss_rule("Amber Acorn").joker_disruption == JokerDisruption.SHUFFLE_FACE_DOWN


def test_unknown_names_fail_closed():
    assert boss_rule("Not a vanilla boss") is None
    assert boss_rule(42) is None
