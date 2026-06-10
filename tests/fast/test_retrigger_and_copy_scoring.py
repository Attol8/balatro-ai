"""Retrigger jokers and Blueprint/Brainstorm copies in the scoring engine."""

from balatro_ai_v2.fast.cards import NUM_RANKS
from balatro_ai_v2.fast.hand import HIGH_CARD, PAIR, FastScore
from balatro_ai_v2.fast.jokers import (
    Joker,
    ScoreContext,
    apply_additive_jokers,
    canonical_joker_order,
    resolve_joker_copies,
)


def card(rank: int, suit: int) -> int:
    return suit * NUM_RANKS + rank


def base_score(cards: tuple[int, ...], kind: int, chips: int, mult: int) -> FastScore:
    return FastScore(
        kind=kind,
        chips=chips,
        mult=mult,
        total=chips * mult,
        scoring_mask=(1 << len(cards)) - 1,
    )


def test_hack_retriggers_low_card_chips_and_card_phase_jokers() -> None:
    cards = (card(1, 0),)  # a 3 of spades: 3 chips
    score = base_score(cards, HIGH_CARD, chips=5 + 3, mult=1)

    plain = apply_additive_jokers(score, cards, 1, (Joker("j_fibonacci"),))
    hacked = apply_additive_jokers(score, cards, 1, (Joker("j_fibonacci"), Joker("j_hack")))

    # One retrigger: +3 base chips and Fibonacci's +8 mult fires again.
    assert hacked.chips == plain.chips + 3
    assert hacked.mult == plain.mult + 8


def test_dusk_retriggers_only_on_final_hand() -> None:
    cards = (card(7, 0),)  # a 9: 9 chips
    score = base_score(cards, HIGH_CARD, chips=5 + 9, mult=1)
    final = ScoreContext(hands_left=0)
    not_final = ScoreContext(hands_left=2)

    assert (
        apply_additive_jokers(score, cards, 1, (Joker("j_dusk"),), final).chips
        == apply_additive_jokers(score, cards, 1, (Joker("j_dusk"),), not_final).chips + 9
    )


def test_hanging_chad_retriggers_first_scoring_card_twice() -> None:
    cards = (card(12, 0), card(12, 1))  # pair of aces: 11 chips each
    score = base_score(cards, PAIR, chips=10 + 22, mult=2)

    plain = apply_additive_jokers(score, cards, 2, ())
    chad = apply_additive_jokers(score, cards, 2, (Joker("j_hanging_chad"),))

    assert chad.chips == plain.chips + 2 * 11


def test_sock_and_buskin_retriggers_faces_and_photograph() -> None:
    cards = (card(10, 0),)  # king: 10 chips
    score = base_score(cards, HIGH_CARD, chips=5 + 10, mult=1)

    photo = apply_additive_jokers(score, cards, 1, (Joker("j_photograph"),))
    both = apply_additive_jokers(
        score, cards, 1, (Joker("j_photograph"), Joker("j_sock_and_buskin"))
    )

    # Photograph doubles on each trigger of the first face card.
    assert photo.mult == 2.0
    assert both.mult == 4.0
    assert both.chips == photo.chips + 10


def test_mime_retriggers_held_baron() -> None:
    held = (card(11, 0), card(11, 1))  # two kings... actually rank 11 = king
    score = base_score((card(2, 0),), HIGH_CARD, chips=5 + 4, mult=1)
    context = ScoreContext(held_cards=held)

    baron = apply_additive_jokers(score, (card(2, 0),), 1, (Joker("j_baron"),), context)
    mimed = apply_additive_jokers(
        score, (card(2, 0),), 1, (Joker("j_baron"), Joker("j_mime")), context
    )

    assert baron.mult == 1.5**2
    assert mimed.mult == 1.5**4


def test_blueprint_copies_right_neighbor_xmult() -> None:
    cards = (card(2, 0),)
    score = base_score(cards, HIGH_CARD, chips=9, mult=1)
    jokers = (Joker("j_blueprint"), Joker("j_cavendish"))

    result = apply_additive_jokers(score, cards, 1, jokers)

    assert result.mult == 9.0  # x3 twice


def test_brainstorm_copies_leftmost_joker() -> None:
    cards = (card(2, 0),)
    score = base_score(cards, HIGH_CARD, chips=9, mult=1)
    jokers = (Joker("j_joker"), Joker("j_brainstorm"))

    result = apply_additive_jokers(score, cards, 1, jokers)

    assert result.mult == 1 + 4 + 4


def test_copy_of_uncopyable_or_missing_target_is_inert() -> None:
    cards = (card(2, 0),)
    score = base_score(cards, HIGH_CARD, chips=9, mult=1)

    alone = apply_additive_jokers(score, cards, 1, (Joker("j_blueprint"),))
    passive = apply_additive_jokers(
        score, cards, 1, (Joker("j_blueprint"), Joker("j_pareidolia"))
    )

    assert alone.mult == 1.0
    assert passive.mult == 1.0


def test_copy_resolution_keeps_copier_edition_and_sell_value() -> None:
    jokers = (
        Joker("j_blueprint", sell_value=7, edition=2),
        Joker("j_green_joker", scaling=9, sell_value=2),
    )

    resolved = resolve_joker_copies(jokers)

    assert resolved[0].key == "j_green_joker"
    assert resolved[0].scaling == 9
    assert resolved[0].sell_value == 7
    assert resolved[0].edition == 2


def test_copy_chain_cycle_is_inert() -> None:
    jokers = (Joker("j_brainstorm"), Joker("j_blueprint"))
    # brainstorm -> leftmost (itself) cycle; blueprint -> nothing to the right
    resolved = resolve_joker_copies(jokers)
    assert resolved[0].key == "j_brainstorm"
    assert resolved[1].key == "j_blueprint"


def test_canonical_order_places_copiers_before_xmult_tail() -> None:
    keys = ["j_cavendish", "j_blueprint", "j_joker"]
    order = canonical_joker_order(keys)
    ordered = [keys[index] for index in order]
    assert ordered == ["j_joker", "j_blueprint", "j_cavendish"]


def test_selzer_retriggers_every_card() -> None:
    cards = (card(12, 0), card(12, 1))
    score = base_score(cards, PAIR, chips=10 + 22, mult=2)

    plain = apply_additive_jokers(score, cards, 2, ())
    selzer = apply_additive_jokers(score, cards, 2, (Joker("j_selzer", scaling=10),))

    assert selzer.chips == plain.chips + 22


def test_local_retrigger_keys_match_repetition_module() -> None:
    from balatro_ai_v2.fast.joker_repetitions import RETRIGGER_JOKERS
    from balatro_ai_v2.fast.jokers import _RETRIGGER_KEYS

    assert _RETRIGGER_KEYS == RETRIGGER_JOKERS
