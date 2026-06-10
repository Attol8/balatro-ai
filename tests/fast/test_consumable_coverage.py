"""Fool, Soul, and the deck-mutating spectrals in the fast env."""

from balatro_ai_v2.fast.cards import rank
from balatro_ai_v2.fast.full_game import FastFullGameEnv
from balatro_ai_v2.fast.jokers import Joker


def make_env() -> FastFullGameEnv:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=21)
    return env


def test_fool_copies_last_used_tarot() -> None:
    env = make_env()
    env.consumables = []
    env._apply_consumable("c_hermit")
    env._apply_consumable("c_fool")

    assert env.consumables == ["c_hermit"]


def test_fool_does_not_copy_itself_or_nothing() -> None:
    env = make_env()
    env.consumables = []
    env._apply_consumable("c_fool")
    assert env.consumables == []


def test_soul_creates_unowned_legendary() -> None:
    env = make_env()
    env.jokers = [Joker("j_triboulet")]

    env._apply_consumable("c_soul")

    assert len(env.jokers) == 2
    new = [j for j in env.jokers if j.key != "j_triboulet"]
    assert new[0].key in {"j_yorick", "j_chicot", "j_caino"}


def test_familiar_swaps_one_card_for_three_faces() -> None:
    env = make_env()
    size = len(env.deck_cards)

    env._apply_consumable("c_familiar")

    assert len(env.deck_cards) == size + 2  # -1 destroyed, +3 created
    faces = [card for card in env.deck_cards if rank(card) in {9, 10, 11}]
    assert len(faces) >= 12 + 3 - 1  # standard deck has 12 faces; one may be destroyed


def test_grim_creates_two_aces() -> None:
    env = make_env()
    aces_before = sum(1 for card in env.deck_cards if rank(card) == 12)

    env._apply_consumable("c_grim")

    aces_after = sum(1 for card in env.deck_cards if rank(card) == 12)
    assert aces_after >= aces_before + 1  # +2 created, at most 1 destroyed


def test_incantation_creates_four_numbered_cards() -> None:
    env = make_env()
    size = len(env.deck_cards)

    env._apply_consumable("c_incantation")

    assert len(env.deck_cards) == size + 3
