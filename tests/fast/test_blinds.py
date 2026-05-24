from balatro_ai_v2.fast.blinds import (
    BLIND_RULES,
    SPADES,
    blind_blocks_hand,
    blind_debuffs_card,
    blind_rule,
)
from balatro_ai_v2.fast.card_state import FastCardState, make_card


def test_all_source_blinds_have_rule_specs() -> None:
    assert len(BLIND_RULES) == 30
    assert blind_rule("bl_small").dollars == 3
    assert blind_rule("bl_big").score_mult == 1.5
    assert blind_rule("bl_final_vessel").score_mult == 6
    assert blind_rule("bl_final_bell").showdown


def test_suit_and_face_blinds_debuff_matching_cards() -> None:
    spade_two = FastCardState(make_card(0, SPADES))
    heart_jack = FastCardState(make_card(9, 1))

    assert blind_debuffs_card("bl_goad", spade_two)
    assert not blind_debuffs_card("bl_head", spade_two)
    assert blind_debuffs_card("bl_plant", heart_jack)


def test_stateful_hand_blocking_blinds() -> None:
    assert blind_blocks_hand("bl_psychic", hand_name="Pair", hand_size=4)
    assert not blind_blocks_hand("bl_psychic", hand_name="Pair", hand_size=5)
    assert blind_blocks_hand(
        "bl_eye",
        hand_name="Flush",
        hand_size=5,
        previous_hand_names=("Flush",),
    )
    assert blind_blocks_hand(
        "bl_mouth",
        hand_name="Pair",
        hand_size=5,
        first_hand_name="High Card",
    )
    assert blind_blocks_hand(
        "bl_ox",
        hand_name="High Card",
        hand_size=5,
        most_played_hand_name="High Card",
    )


def test_played_this_ante_and_leaf_debuffs() -> None:
    card = FastCardState(make_card(12, 3))

    assert blind_debuffs_card("bl_pillar", card, played_this_ante=True)
    assert not blind_debuffs_card("bl_pillar", card, played_this_ante=False)
    assert blind_debuffs_card("bl_final_leaf", card)
