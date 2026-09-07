from balatro_ai.game.mechanics import joker_rarity, planet_hand, semantic_card_key


def test_public_mechanics_lookups() -> None:
    assert planet_hand("c_saturn") == "Straight"
    assert planet_hand("unknown") is None
    assert joker_rarity("j_joker") == 1
    assert joker_rarity("j_baseball") == 3
    assert joker_rarity("j_perkeo") == 4
    assert joker_rarity("j_future_mod") == 0
    assert semantic_card_key("BOOSTER", "p_arcana_normal_4") == "p_arcana_normal"
    assert semantic_card_key("JOKER", "j_joker") == "j_joker"
