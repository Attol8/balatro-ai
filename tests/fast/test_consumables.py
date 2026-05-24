from balatro_ai_v2.fast.card_state import FastCardState
from balatro_ai_v2.fast.cards import NUM_RANKS
from balatro_ai_v2.fast.consumables import apply_consumable
from balatro_ai_v2.fast.hand import PAIR
from balatro_ai_v2.fast.modifiers import Edition, Enhancement, Seal


def card(rank: int, suit: int) -> FastCardState:
    return FastCardState(suit * NUM_RANKS + rank)


def test_suit_conversion_preserves_rank_and_card_state() -> None:
    original = card(12, 3)

    result = apply_consumable("c_world", (original,), (0,))

    assert result.cards[0].rank == 12
    assert result.cards[0].suit == 0


def test_enhancement_tarot_sets_target_enhancements() -> None:
    cards = (card(3, 0), card(7, 1), card(9, 2))

    result = apply_consumable("c_empress", cards, (0, 2))

    assert result.cards[0].enhancement == Enhancement.MULT
    assert result.cards[1].enhancement == Enhancement.BASE
    assert result.cards[2].enhancement == Enhancement.MULT


def test_strength_increases_rank_and_caps_at_ace() -> None:
    cards = (card(11, 0), card(12, 1))

    result = apply_consumable("c_strength", cards, (0, 1))

    assert result.cards[0].rank == 12
    assert result.cards[1].rank == 12


def test_hanged_man_removes_selected_cards() -> None:
    cards = (card(1, 0), card(2, 0), card(3, 0), card(4, 0))

    result = apply_consumable("c_hanged_man", cards, (1, 3))

    assert result.cards == (cards[0], cards[2])
    assert result.destroyed_indices == (1, 3)


def test_death_copies_right_card_onto_left_card() -> None:
    cards = (
        card(2, 0),
        FastCardState(card_id=3 * NUM_RANKS + 10, enhancement=Enhancement.GLASS, seal=Seal.RED),
    )

    result = apply_consumable("c_death", cards, (0, 1))

    assert result.cards[0] == cards[1]
    assert result.cards[1] == cards[1]


def test_planet_card_increments_matching_hand_level() -> None:
    levels = (1,) * 12

    result = apply_consumable("c_mercury", (), (), levels)

    assert result.hand_levels[PAIR] == 2
    assert sum(result.hand_levels) == 13


def test_black_hole_increments_every_hand_level() -> None:
    result = apply_consumable("c_black_hole", (), (), (1,) * 12)

    assert result.hand_levels == (2,) * 12


def test_money_tarots_return_exact_money_delta() -> None:
    hermit = apply_consumable("c_hermit", (), money=50)
    temperance = apply_consumable("c_temperance", (), joker_sell_total=63)

    assert hermit.money_delta == 20
    assert temperance.money_delta == 50


def test_spectral_seal_card_sets_target_seal() -> None:
    cards = (card(4, 0),)

    result = apply_consumable("c_deja_vu", cards, (0,))

    assert result.cards[0].seal == Seal.RED


def test_cryptid_duplicates_target_card_twice() -> None:
    cards = (card(4, 0), card(8, 1))

    result = apply_consumable("c_cryptid", cards, (1,))

    assert result.cards == (cards[0], cards[1], cards[1], cards[1])


def test_immolate_destroys_targets_and_grants_money() -> None:
    cards = (card(1, 0), card(2, 0), card(3, 0))

    result = apply_consumable("c_immolate", cards, (0, 2))

    assert result.cards == (cards[1],)
    assert result.money_delta == 20


def test_create_consumables_return_resolved_created_kinds_or_keys() -> None:
    assert apply_consumable("c_fool", (), last_consumable_key="c_death").created_keys == ("c_death",)
    assert apply_consumable("c_emperor", ()).created_kinds == ("Tarot", "Tarot")
    assert apply_consumable("c_high_priestess", ()).created_kinds == ("Planet", "Planet")
    assert apply_consumable("c_judgement", ()).created_kinds == ("Joker",)
    assert apply_consumable("c_soul", ()).created_kinds == ("Legendary Joker",)

    wraith = apply_consumable("c_wraith", (), money=17)
    assert wraith.created_kinds == ("Rare Joker",)
    assert wraith.money_delta == -17


def test_randomized_card_spectrals_accept_resolved_source_rng_output() -> None:
    cards = (card(1, 0), card(2, 1), card(3, 2))
    created = (FastCardState(4), FastCardState(5))

    familiar = apply_consumable("c_familiar", cards, (0,), created_cards=created)
    sigil = apply_consumable("c_sigil", cards, chosen_suit=3)
    ouija = apply_consumable("c_ouija", cards, chosen_rank=8)

    assert familiar.cards == (cards[1], cards[2], *created)
    assert familiar.destroyed_indices == (0,)
    assert {card.suit for card in sigil.cards} == {3}
    assert {card.rank for card in ouija.cards} == {8}
    assert ouija.hand_size_delta == -1


def test_joker_edition_spectrals_return_exact_joker_side_effects() -> None:
    cards = (card(1, 0),)

    aura = apply_consumable("c_aura", cards, (0,), chosen_edition="e_foil")
    wheel_hit = apply_consumable("c_wheel_of_fortune", (), chosen_edition="e_holo", probability_success=True)
    wheel_miss = apply_consumable("c_wheel_of_fortune", (), chosen_edition="e_holo", probability_success=False)
    ankh = apply_consumable("c_ankh", ())
    hex_result = apply_consumable("c_hex", ())
    ectoplasm = apply_consumable("c_ectoplasm", ())

    assert aura.cards[0].edition == Edition.FOIL
    assert wheel_hit.joker_edition_key == "e_holo"
    assert wheel_miss.joker_edition_key is None
    assert ankh.duplicated_joker
    assert ankh.destroy_other_jokers
    assert hex_result.joker_edition_key == "e_polychrome"
    assert hex_result.destroy_other_jokers
    assert ectoplasm.joker_edition_key == "e_negative"
    assert ectoplasm.hand_size_delta == -1
