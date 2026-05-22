from balatro_ai_v2.engine.blind import BlindConfig, discard_cards, play_cards, start_blind
from balatro_ai_v2.engine.cards import Deck, standard_deck


def test_start_blind_draws_initial_hand_from_seeded_deck() -> None:
    deck = standard_deck().shuffle(13)
    state = start_blind(deck, BlindConfig(required_score=300))

    assert len(state.hand) == 8
    assert len(state.deck.cards) == 44
    assert state.hand == deck.cards[:8]
    assert state.score == 0


def test_play_cards_scores_and_replaces_cards() -> None:
    state = start_blind(standard_deck(), BlindConfig(required_score=10_000))
    played = state.hand[:5]

    next_state, result = play_cards(state, played)

    assert next_state.score == result.total
    assert next_state.hands_remaining == state.hands_remaining - 1
    assert next_state.discards_remaining == state.discards_remaining
    assert len(next_state.hand) == state.config.hand_size
    assert next_state.hand[:3] == state.hand[5:]


def test_discard_cards_replaces_cards_without_scoring() -> None:
    state = start_blind(standard_deck(), BlindConfig(required_score=10_000))
    discarded = state.hand[:3]

    next_state = discard_cards(state, discarded)

    assert next_state.score == 0
    assert next_state.hands_remaining == state.hands_remaining
    assert next_state.discards_remaining == state.discards_remaining - 1
    assert len(next_state.hand) == state.config.hand_size
    assert next_state.hand[:5] == state.hand[3:]


def test_blind_clears_when_score_reaches_requirement() -> None:
    state = start_blind(standard_deck(), BlindConfig(required_score=1))

    next_state, _ = play_cards(state, (state.hand[0],))

    assert next_state.is_cleared
    assert next_state.is_over


def test_depleted_deck_keeps_smaller_hand() -> None:
    deck = Deck(standard_deck().cards[:9])
    state = start_blind(deck, BlindConfig(required_score=10_000, hand_size=8))

    next_state, _ = play_cards(state, state.hand[:5])

    assert len(next_state.hand) == 4
    assert len(next_state.deck.cards) == 0
