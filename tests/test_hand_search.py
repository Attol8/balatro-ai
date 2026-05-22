from balatro_ai_v2.engine.cards import Card, Rank, Suit
from balatro_ai_v2.engine.hand import HandKind
from balatro_ai_v2.search.hand_play import best_play, enumerate_plays


def c(rank: Rank, suit: Suit) -> Card:
    return Card(rank, suit)


def test_enumerates_all_non_empty_plays_up_to_five_cards() -> None:
    hand = (
        c(Rank.ACE, Suit.SPADES),
        c(Rank.KING, Suit.SPADES),
        c(Rank.QUEEN, Suit.SPADES),
        c(Rank.JACK, Suit.SPADES),
        c(Rank.TEN, Suit.SPADES),
        c(Rank.TWO, Suit.CLUBS),
    )

    plays = enumerate_plays(hand)

    assert len(plays) == 6 + 15 + 20 + 15 + 6


def test_best_play_selects_highest_scoring_available_hand() -> None:
    hand = (
        c(Rank.ACE, Suit.SPADES),
        c(Rank.KING, Suit.SPADES),
        c(Rank.QUEEN, Suit.SPADES),
        c(Rank.JACK, Suit.SPADES),
        c(Rank.TEN, Suit.SPADES),
        c(Rank.TWO, Suit.CLUBS),
    )

    play = best_play(hand)

    assert play.score.hand_kind == HandKind.STRAIGHT_FLUSH
    assert play.score.total == (100 + 11 + 10 + 10 + 10 + 10) * 8

