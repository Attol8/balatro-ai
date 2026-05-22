from balatro_ai_v2.engine.cards import standard_deck


def test_standard_deck_has_52_unique_cards() -> None:
    deck = standard_deck()

    assert len(deck.cards) == 52
    assert len(set(deck.cards)) == 52


def test_shuffle_is_seeded_and_replayable() -> None:
    deck = standard_deck()

    assert deck.shuffle(7).cards == deck.shuffle(7).cards
    assert deck.shuffle(7).cards != deck.shuffle(8).cards


def test_draw_returns_cards_and_remaining_deck() -> None:
    deck = standard_deck().shuffle(1)

    drawn, remaining = deck.draw(8)

    assert len(drawn) == 8
    assert len(remaining.cards) == 44
    assert drawn == deck.cards[:8]

