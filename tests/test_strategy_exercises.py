"""Small offline exercises for score-sensitive Joker choices."""

from __future__ import annotations

import math
from dataclasses import replace
from fractions import Fraction

import pytest

from balatro_ai.game.actions import HandSlot
from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.scoring import score_play
from balatro_ai.game.state import DeckCardCount, HandStat, PublicItem, VisiblePlayingCard
from tests.game.state_factory import state


def _high_card_observation(base_mult: int, held: tuple[VisiblePlayingCard, ...]):
    observation = to_public_observation(state("SELECTING_HAND"))
    return replace(
        observation,
        hand=(VisiblePlayingCard("2", "S"), *held),
        hand_stats=(HandStat("High Card", 1, 5, base_mult, 0, 0),),
    )


@pytest.mark.parametrize("base_mult", [1, 50])
@pytest.mark.parametrize("steel_count", range(5))
def test_mime_vs_holographic_cloud_9_grid(base_mult: int, steel_count: int) -> None:
    """Compare hand score only; Cloud 9's end-of-round income is external."""
    held = tuple(
        VisiblePlayingCard(str(rank), "H", enhancement="STEEL")
        for rank in range(2, 2 + steel_count)
    )
    observation = _high_card_observation(base_mult, held)
    chips = 7  # High Card's 5 base chips plus the played 2.
    mime = PublicItem("j_mime", "Mime", "JOKER")
    cloud = PublicItem("j_cloud_9", "Cloud 9", "JOKER", edition="HOLO")

    mime_score = score_play(replace(observation, jokers=(mime,)), (HandSlot(0),))[0]
    cloud_score = score_play(replace(observation, jokers=(cloud,)), (HandSlot(0),))[0]

    assert mime_score == chips * base_mult * Fraction(3, 2) ** (2 * steel_count)
    assert cloud_score == chips * (base_mult * Fraction(3, 2) ** steel_count + 10)
    assert (mime_score > cloud_score) is (
        base_mult * Fraction(3, 2) ** (2 * steel_count)
        > base_mult * Fraction(3, 2) ** steel_count + 10
    )


def test_photograph_and_hanging_chad_retrigger_x8_instead_of_x2() -> None:
    observation = _high_card_observation(1, ())
    observation = replace(observation, hand=(VisiblePlayingCard("K", "S"),))
    photograph = PublicItem("j_photograph", "Photograph", "JOKER")
    chad = PublicItem("j_hanging_chad", "Hanging Chad", "JOKER")

    photograph_score = score_play(replace(observation, jokers=(photograph,)), (HandSlot(0),))[0]
    chad_score = score_play(replace(observation, jokers=(photograph, chad)), (HandSlot(0),))[0]

    assert photograph_score == (5 + 10) * 2
    # Chad repeats both the King's +10 chips and Photograph twice more.
    assert chad_score == (5 + 3 * 10) * 8


def test_blueprint_position_selects_mime_x8_or_baron_x9_arithmetic() -> None:
    held_king = VisiblePlayingCard("K", "H", enhancement="STEEL", seal="RED")
    observation = _high_card_observation(1, (held_king,))
    blueprint = PublicItem("j_blueprint", "Blueprint", "JOKER")
    mime = PublicItem("j_mime", "Mime", "JOKER")
    baron = PublicItem("j_baron", "Baron", "JOKER")

    copy_mime = score_play(replace(observation, jokers=(blueprint, mime, baron)), (HandSlot(0),))[0]
    copy_baron = score_play(replace(observation, jokers=(mime, blueprint, baron)), (HandSlot(0),))[
        0
    ]

    assert copy_mime == 7 * Fraction(3, 2) ** 8
    assert copy_baron == 7 * Fraction(3, 2) ** 9
    assert copy_baron == copy_mime * Fraction(3, 2)


def test_fibonacci_is_reapplied_when_hack_retriggers_a_two() -> None:
    observation = _high_card_observation(1, ())
    fibonacci = PublicItem("j_fibonacci", "Fibonacci", "JOKER")
    hack = PublicItem("j_hack", "Hack", "JOKER")

    score, family = score_play(replace(observation, jokers=(fibonacci, hack)), (HandSlot(0),))

    assert family == "High Card"
    assert score == (5 + 2 * 2) * (1 + 2 * 8) == 153


def test_sock_retrigger_reapplies_triboulet_to_a_king() -> None:
    observation = replace(_high_card_observation(1, ()), hand=(VisiblePlayingCard("K", "S"),))
    triboulet = PublicItem("j_triboulet", "Triboulet", "JOKER")
    sock = PublicItem("j_sock_and_buskin", "Sock and Buskin", "JOKER")

    score, family = score_play(replace(observation, jokers=(triboulet, sock)), (HandSlot(0),))

    assert family == "High Card"
    assert score == (5 + 2 * 10) * 2**2 == 100


def test_four_fingers_and_shortcut_make_a_four_card_gapped_straight() -> None:
    observation = _high_card_observation(1, ())
    observation = replace(
        observation,
        hand=tuple(
            VisiblePlayingCard(rank, suit)
            for rank, suit in zip(("2", "4", "6", "8"), ("S", "H", "D", "C"), strict=True)
        ),
        hand_stats=(HandStat("Straight", 1, 30, 4, 0, 0),),
        jokers=(
            PublicItem("j_four_fingers", "Four Fingers", "JOKER"),
            PublicItem("j_shortcut", "Shortcut", "JOKER"),
        ),
    )

    score, family = score_play(observation, tuple(HandSlot(i) for i in range(4)))

    assert family == "Straight"
    assert score == (30 + 2 + 4 + 6 + 8) * 4 == 200


def _interest(dollars: int, cap: int = 25) -> int:
    """At cash out Balatro pays $1 per $5 held, up to cap/5 dollars."""
    return min(dollars // 5, cap // 5)


@pytest.mark.parametrize(
    ("cap", "maximum", "held_for_maximum"),
    [(25, 5, 25), (50, 10, 50), (100, 20, 100)],
)
def test_interest_caps_match_the_base_seed_money_and_money_tree_rules(
    cap: int, maximum: int, held_for_maximum: int
) -> None:
    """Base cap $25, Seed Money $50, Money Tree $100; income is $1 per $5 held."""
    assert _interest(held_for_maximum, cap) == maximum
    assert _interest(held_for_maximum + 5, cap) == maximum
    assert _interest(held_for_maximum - 5, cap) == maximum - 1
    assert _interest(0, cap) == 0
    assert _interest(4, cap) == 0


def test_spending_across_a_five_dollar_step_costs_exactly_one_interest() -> None:
    assert _interest(20) - _interest(19) == 1
    assert _interest(24) == _interest(20) == 4


def test_reroll_surplus_repays_its_ten_dollars_after_five_rerolls() -> None:
    """Reroll Surplus lowers each reroll by $2; the $10 voucher is the break-even."""
    saved_per_reroll = 2
    assert 4 * saved_per_reroll < 10 <= 5 * saved_per_reroll


@pytest.mark.parametrize(
    ("edition", "expected"),
    [
        (None, Fraction(7 * 5)),
        ("FOIL", Fraction((7 + 50) * 5)),
        ("HOLO", Fraction(7 * (5 + 10))),
        ("POLYCHROME", Fraction(7 * 5 * 3, 2)),
    ],
)
def test_joker_editions_add_fifty_chips_ten_mult_or_multiply_by_one_and_a_half(
    edition: str | None, expected: Fraction
) -> None:
    """A played 2 with High Card 5/1 and a +4 Mult Joker isolates the edition."""
    observation = _high_card_observation(1, ())
    joker = PublicItem("j_joker", "Joker", "JOKER", edition=edition)

    score, family = score_play(replace(observation, jokers=(joker,)), (HandSlot(0),))

    assert family == "High Card"
    assert score == expected


# --- Headless run TAF7DNTX -------------------------------------------------
#
# The engine that reached Ante 13 was Photograph, Blueprint, Hanging Chad,
# Brainstorm in that order: Blueprint copies its right neighbour (Chad) and
# Brainstorm copies the leftmost Joker (Photograph). Chad and its copy retrigger
# the first played card twice each, so that one card scores five times and every
# effect on it is applied five times.

_TAF_ENGINE = (
    PublicItem("j_photograph", "Photograph", "JOKER"),
    PublicItem("j_blueprint", "Blueprint", "JOKER"),
    PublicItem("j_hanging_chad", "Hanging Chad", "JOKER"),
    PublicItem("j_brainstorm", "Brainstorm", "JOKER"),
)


def _taf_engine_observation(card: VisiblePlayingCard):
    observation = _high_card_observation(1, ())
    return replace(observation, hand=(card,), jokers=_TAF_ENGINE)


@pytest.mark.parametrize(
    ("lead", "expected", "factor_per_trigger"),
    [
        (VisiblePlayingCard("K", "S", enhancement="GLASS"), 1_802_240, 8),
        (VisiblePlayingCard("K", "S"), 56_320, 4),
        (VisiblePlayingCard("T", "S", enhancement="GLASS"), 1_760, 2),
    ],
)
def test_only_a_glass_face_lead_gets_every_multiplier_five_times(
    lead: VisiblePlayingCard, expected: int, factor_per_trigger: int
) -> None:
    """Glass X2, Photograph X2 and Brainstorm's copy of it X2 all ride slot 0."""
    score, family = score_play(_taf_engine_observation(lead), (HandSlot(0),))

    chips = 5 + 5 * 10  # High Card's 5 base chips plus five triggers of a 10-chip card.
    assert family == "High Card"
    assert score == chips * factor_per_trigger**5 == expected


def test_a_glass_face_lead_beats_a_plain_face_by_thirty_two() -> None:
    glass = _taf_engine_observation(VisiblePlayingCard("K", "S", enhancement="GLASS"))
    plain = _taf_engine_observation(VisiblePlayingCard("K", "S"))

    assert score_play(glass, (HandSlot(0),))[0] == 32 * score_play(plain, (HandSlot(0),))[0]


@pytest.mark.parametrize(
    ("disabled", "expected"),
    [("j_photograph", 1_760), ("j_brainstorm", 56_320), ("j_blueprint", 17_920)],
)
def test_crimson_heart_costs_double_when_it_disables_the_copied_joker(
    disabled: str, expected: int
) -> None:
    """Disabling Photograph also silences the Brainstorm copying it: X32 twice over."""
    observation = _taf_engine_observation(VisiblePlayingCard("K", "S", enhancement="GLASS"))
    jokers = tuple(
        replace(joker, debuffed=True) if joker.key == disabled else joker
        for joker in observation.jokers
    )

    score = score_play(replace(observation, jokers=jokers), (HandSlot(0),))[0]

    assert score == expected
    if disabled == "j_photograph":
        assert score * 32 == 56_320  # the Brainstorm-only loss


@pytest.mark.parametrize("steel", [0, 2, 4, 9])
def test_steel_joker_reads_the_whole_deck_and_ignores_the_played_card(steel: int) -> None:
    """The recorded copy went from two Steel cards at Ante 8 to nine at Ante 13."""
    observation = _high_card_observation(1, ())
    entries = tuple(
        DeckCardCount(VisiblePlayingCard(rank, "H", enhancement="STEEL"), 1)
        for rank in ("2", "3", "4", "5", "6", "7", "8", "9", "T")[:steel]
    )
    observation = replace(
        observation,
        hand=(VisiblePlayingCard("2", "C"),),
        jokers=(PublicItem("j_steel_joker", "Steel Joker", "JOKER"),),
        full_deck=(*entries, DeckCardCount(VisiblePlayingCard("2", "S"), 52 - steel)),
        deck_size=52,
    )

    assert score_play(observation, (HandSlot(0),))[0] == 7 * (1 + Fraction(steel, 5))


def test_the_tooth_charges_one_dollar_for_every_card_played() -> None:
    """The recorded boss ran $6 to -$10 over hands of five, five, five and one."""
    money = 6
    for cards in (5, 5, 5, 1):
        money -= cards
    assert money == -10


def test_the_recorded_endless_cash_outs_paid_a_quarter_of_the_seed_money_cap() -> None:
    """Money held at the last eight cash outs of TAF7DNTX, Seed Money owned."""
    held = (30, 14, 22, 40, 22, 2, 0, 6)
    paid = [_interest(dollars, 50) for dollars in held]

    assert paid == [6, 2, 4, 8, 4, 0, 0, 1]
    assert sum(paid) == 25
    assert len(held) * _interest(50, 50) == 80


def _taf_recorded_observation(index: int):
    """The public observation the coach saw before the transition at 04:index."""
    from balatro_ai.game.codec import public_observation_from_data
    from tests.test_strategy import recorded

    for offset in range(0, 8):
        event = recorded("04", index - offset, run="TAF7DNTX")
        if event.get("event") == "rpc_attempt" and "observation" in event:
            return public_observation_from_data(event["observation"])
    raise AssertionError(f"no observation before 04:{index}")


def test_the_recorded_tooth_hand_left_three_orders_of_magnitude_on_the_table() -> None:
    """04:948 led a Steel Ace and left the red-seal Glass Ten out of the flush."""
    observation = _taf_recorded_observation(948)
    played = (0, 1, 3, 4, 7)  # AS Steel, KS Steel, 7S, 6S, 3S Steel
    glass_led = (1, 0, 2, 3, 4)  # KS Steel first, with the Glass Ten scoring

    as_played = score_play(observation, tuple(HandSlot(i) for i in played))
    alternative = score_play(observation, tuple(HandSlot(i) for i in glass_led))

    assert as_played == (764_127, "Flush")
    assert alternative == (1_222_760_448, "Flush")
    assert alternative[0] // as_played[0] == 1600


def test_the_recorded_crimson_heart_disable_cost_sixty_four_times() -> None:
    """04:290 cleared 100,000 with Photograph, and Brainstorm's copy of it, gone."""
    observation = _taf_recorded_observation(290)
    played = tuple(HandSlot(i) for i in (1, 2, 3, 4, 5))
    undebuffed = replace(
        observation, jokers=tuple(replace(j, debuffed=False) for j in observation.jokers)
    )

    disabled, family = score_play(observation, played)
    intact = score_play(undebuffed, played)[0]

    assert [j.key for j in observation.jokers if j.debuffed] == ["j_photograph"]
    assert family == "Flush"
    assert math.floor(disabled) == 180_442  # exactly the recorded chips
    assert math.floor(intact) == 11_548_293
    assert intact // disabled == 64  # Photograph and the Brainstorm copying it
