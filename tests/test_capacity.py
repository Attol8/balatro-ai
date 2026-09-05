from __future__ import annotations

import math
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.belief import PublicDrawBelief
from balatro_ai_v2.capacity import estimate_capacity, log_margin, project_capacity
from balatro_ai_v2.public_state import HiddenHandCard
from state_factory import item_card, state


def test_visible_hand_capacity_is_the_best_legal_public_play() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))

    estimate = estimate_capacity(
        observation,
        PublicDrawBelief.from_observation(observation),
        samples=32,
    )

    assert estimate.available
    assert estimate.mean_best_score == 15
    assert estimate.samples == 1
    assert estimate.sample_method == "visible-hand-v1"
    assert estimate.best_hand is not None
    assert estimate.best_hand.hand_name == "High Card"


def test_small_future_hand_distribution_is_exact_without_replacement() -> None:
    raw = state("SHOP")
    raw["hand"]["limit"] = 2
    observation = to_public_observation(raw)
    belief = PublicDrawBelief.from_observation(observation)

    estimate = estimate_capacity(observation, belief, samples=3)

    assert estimate.available
    assert estimate.sample_method == "exact-public-hypergeometric-v1"
    assert estimate.samples == 3
    # The visible next boss is The Head, so the sampled heart is debuffed.
    assert estimate.mean_best_score == 13
    assert sum((row.probability for row in estimate.breakdown), Fraction(0)) == 1


def test_sampling_is_reproducible_and_deck_multiset_order_invariant() -> None:
    raw = state("SHOP")
    raw["hand"]["limit"] = 2
    observation = to_public_observation(raw)
    belief = PublicDrawBelief.from_observation(observation)
    reordered = replace(observation, remaining_deck=tuple(reversed(observation.remaining_deck)))
    reordered_belief = PublicDrawBelief.from_observation(reordered)

    first = estimate_capacity(observation, belief, samples=2)
    second = estimate_capacity(reordered, reordered_belief, samples=2)

    assert first == second
    assert first.sample_method.startswith("public-digest-monte-carlo")


def test_future_hand_clears_pack_phase_metadata() -> None:
    raw = state("BUFFOON_PACK")
    raw["hand"]["limit"] = 2
    observation = to_public_observation(raw)

    estimate = estimate_capacity(
        observation,
        PublicDrawBelief.from_observation(observation),
        samples=3,
    )

    assert estimate.available
    assert estimate.samples == 3


def test_hidden_and_unsupported_mechanics_fail_closed() -> None:
    visible = to_public_observation(state("SELECTING_HAND"))
    hidden = replace(visible, hand=(HiddenHandCard(), *visible.hand[1:]))
    raw = state("SELECTING_HAND")
    raw["jokers"]["cards"] = [item_card("j_square", card_id=20, kind="JOKER")]
    raw["jokers"]["count"] = 1
    unsupported = to_public_observation(raw)

    hidden_result = estimate_capacity(
        hidden, PublicDrawBelief.from_observation(hidden), samples=16
    )
    unsupported_result = estimate_capacity(
        unsupported,
        PublicDrawBelief.from_observation(unsupported),
        samples=16,
    )

    assert not hidden_result.available
    assert hidden_result.unavailable_reason == "hidden hand cards are unsupported"
    assert hidden_result.mean_best_score is None
    assert not unsupported_result.available
    assert unsupported_result.unavailable_reason == "unsupported Joker state for j_square"


def test_unknown_boss_and_preblind_riff_raff_fail_closed() -> None:
    unknown_raw = state("SHOP")
    unknown_raw["hand"]["limit"] = 2
    unknown_raw["blinds"]["boss"]["name"] = "Unmodeled Boss"
    unknown = to_public_observation(unknown_raw)
    riff_raw = state("SHOP")
    riff_raw["hand"]["limit"] = 2
    riff_raw["jokers"]["cards"] = [
        item_card("j_riff_raff", card_id=20, kind="JOKER")
    ]
    riff_raw["jokers"]["count"] = 1
    riff = to_public_observation(riff_raw)

    unknown_result = estimate_capacity(
        unknown, PublicDrawBelief.from_observation(unknown), samples=16
    )
    riff_result = estimate_capacity(
        riff, PublicDrawBelief.from_observation(riff), samples=16
    )

    assert not unknown_result.available
    assert unknown_result.unavailable_reason == "unknown next boss blind 'Unmodeled Boss'"
    assert not riff_result.available
    assert riff_result.unavailable_reason == "unsupported Joker j_riff_raff"


def test_disabled_unknown_current_boss_is_effectless_for_visible_capacity() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(
        name="Unmodeled Boss", status="CURRENT", disabled=True
    )
    observation = to_public_observation(raw)

    estimate = estimate_capacity(
        observation,
        PublicDrawBelief.from_observation(observation),
        samples=32,
    )

    assert estimate.available
    assert estimate.mean_best_score == 15


def test_unmodeled_next_boss_information_fails_closed() -> None:
    raw = state("SHOP")
    raw["hand"]["limit"] = 2
    raw["blinds"]["boss"]["name"] = "The House"
    observation = to_public_observation(raw)

    estimate = estimate_capacity(
        observation,
        PublicDrawBelief.from_observation(observation),
        samples=16,
    )

    assert not estimate.available
    assert estimate.unavailable_reason == (
        "unsupported next-boss mechanics for The House: face_down"
    )


def test_unknown_voucher_fails_closed() -> None:
    raw = state("SHOP")
    raw["hand"]["limit"] = 2
    raw["used_vouchers"] = ["v_future_unknown"]
    observation = to_public_observation(raw)

    estimate = estimate_capacity(
        observation,
        PublicDrawBelief.from_observation(observation),
        samples=16,
    )

    assert not estimate.available
    assert estimate.unavailable_reason == "unsupported voucher v_future_unknown"


def test_future_capacity_resets_round_local_state() -> None:
    raw = state("SHOP")
    raw["hand"]["limit"] = 2
    raw["round"].update(hands_left=1, discards_left=0)
    raw["hands"]["High Card"]["played_this_round"] = 3
    raw["jokers"]["cards"] = [
        item_card("j_banner", card_id=20, kind="JOKER")
    ]
    raw["jokers"]["count"] = 1
    observation = to_public_observation(raw)

    estimate = estimate_capacity(
        observation,
        PublicDrawBelief.from_observation(observation),
        samples=3,
    )

    # Red Deck starts the next round with four discards, so Banner adds 120
    # chips even though the previous round ended with none.
    assert estimate.available
    assert estimate.mean_best_score == 133


def test_margin_and_flat_projection_use_only_visible_requirement() -> None:
    raw = state("SHOP")
    raw["hand"]["limit"] = 2
    observation = to_public_observation(raw)
    belief = PublicDrawBelief.from_observation(observation)
    estimate = estimate_capacity(observation, belief, samples=3)

    margin = log_margin(observation, estimate)
    projection = project_capacity(observation, belief, samples=3, rounds=4)

    assert margin.available
    assert margin.boss_requirement == 600
    assert margin.log_margin == math.log(13) - math.log(600)
    assert projection.available
    assert projection.projected_mean_best_score == 13
    assert projection.growth_rate == 0


def test_capacity_module_has_no_engine_or_raw_state_dependency() -> None:
    source = (Path(__file__).resolve().parents[1] / "balatro_ai_v2" / "capacity.py").read_text()

    assert "balatrobot" not in source.lower()
    assert "jackdaw" not in source.lower()
    assert "balatro_ai_v2.canonical" not in source
    assert "baselines" not in source.lower()
