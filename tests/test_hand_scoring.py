from balatro_ai_v2.engine.cards import Card, Rank, Suit
from balatro_ai_v2.engine.hand import HandKind, evaluate_hand
from balatro_ai_v2.engine.scoring import ScoreEvent, score_play


def c(rank: Rank, suit: Suit) -> Card:
    return Card(rank, suit)


def test_pair_scores_only_pair_cards() -> None:
    cards = (
        c(Rank.ACE, Suit.SPADES),
        c(Rank.ACE, Suit.HEARTS),
        c(Rank.KING, Suit.CLUBS),
        c(Rank.SEVEN, Suit.DIAMONDS),
        c(Rank.TWO, Suit.SPADES),
    )

    result = score_play(cards)

    assert result.hand_kind == HandKind.PAIR
    assert result.scoring_cards == (
        c(Rank.ACE, Suit.SPADES),
        c(Rank.ACE, Suit.HEARTS),
    )
    assert result.chips == 32
    assert result.mult == 2
    assert result.total == 64


def test_full_house_scores_all_cards() -> None:
    cards = (
        c(Rank.QUEEN, Suit.SPADES),
        c(Rank.QUEEN, Suit.HEARTS),
        c(Rank.QUEEN, Suit.CLUBS),
        c(Rank.FOUR, Suit.DIAMONDS),
        c(Rank.FOUR, Suit.SPADES),
    )

    result = score_play(cards)

    assert result.hand_kind == HandKind.FULL_HOUSE
    assert result.chips == 40 + 10 + 10 + 10 + 4 + 4
    assert result.mult == 4
    assert result.total == 312


def test_ace_low_straight_is_supported() -> None:
    cards = (
        c(Rank.ACE, Suit.SPADES),
        c(Rank.TWO, Suit.HEARTS),
        c(Rank.THREE, Suit.CLUBS),
        c(Rank.FOUR, Suit.DIAMONDS),
        c(Rank.FIVE, Suit.SPADES),
    )

    assert evaluate_hand(cards).kind == HandKind.STRAIGHT


def test_straight_flush_beats_plain_flush() -> None:
    cards = (
        c(Rank.NINE, Suit.HEARTS),
        c(Rank.TEN, Suit.HEARTS),
        c(Rank.JACK, Suit.HEARTS),
        c(Rank.QUEEN, Suit.HEARTS),
        c(Rank.KING, Suit.HEARTS),
    )

    result = score_play(cards)

    assert result.hand_kind == HandKind.STRAIGHT_FLUSH
    assert result.mult == 8


def test_score_log_is_inspectable() -> None:
    cards = (c(Rank.ACE, Suit.SPADES),)

    result = score_play(cards)

    assert [step.event for step in result.events] == [
        ScoreEvent.HAND_BASE,
        ScoreEvent.CARD_CHIPS,
        ScoreEvent.TOTAL,
    ]
    assert result.events[-1].message == "16 chips x 1 mult = 16"

