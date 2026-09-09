"""Independent arithmetic and legality checks for constructed decision probes."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest

from balatro_ai.game.actions import (
    HandSlot,
    JokerSlot,
    LeaveShop,
    PlayCards,
    SellJoker,
    canonical_action_from_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai.game.codec import public_observation_from_data
from balatro_ai.game.scoring import score_play

CASES = json.loads((Path(__file__).parent / "fixtures" / "decision_probes.json").read_text())


def observation(case_id):
    row = next(row for row in CASES if row["id"] == case_id)
    return public_observation_from_data(row["observation"])


@pytest.mark.parametrize("row", CASES, ids=lambda row: row["id"])
def test_constructed_oracles_are_legal_and_deck_counts_coherent(row):
    obs = public_observation_from_data(row["observation"])
    assert row["provenance"] == "constructed"
    assert row["objective"] in {"ante8", "endless"}
    assert row["accepted_actions"]
    for data in row["accepted_actions"]:
        assert is_legal(obs, canonical_action_from_data(data))
    assert sum(entry.count for entry in obs.full_deck) == obs.deck_size
    assert sum(entry.count for entry in obs.remaining_deck) == obs.draw_count
    assert obs.draw_count + len(obs.hand) <= obs.deck_size
    full = {entry.card: entry.count for entry in obs.full_deck}
    for card in obs.hand:
        assert full[card] > 0
        full[card] -= 1


@pytest.mark.parametrize(
    "case_id,expected,alternatives",
    [
        ("black_gold_last_hand_face_retrigger", (5 + 3 * 10) * 2**3, [38, 38]),
        (
            "black_gold_endless_hold_red_steel_king",
            ((95 + 11) * 10 * Fraction(3, 2) ** 6) // 1,
            [1150, 1060],
        ),
    ],
)
def test_last_hand_oracle_is_the_only_immediately_winning_play(case_id, expected, alternatives):
    obs = observation(case_id)
    assert obs.round.hands_left == 1
    assert obs.round.discards_left == obs.draw_count == 0
    deficit = next(b.score for b in obs.blinds if b.status == "CURRENT") - obs.round.chips
    assert score_play(obs, (HandSlot(0),))[0] == expected >= deficit
    assert [
        score_play(obs, cards)[0] for cards in [(HandSlot(1),), (HandSlot(0), HandSlot(1))]
    ] == alternatives
    assert all(value < deficit for value in alternatives)
    winning = [
        action
        for action in iter_legal_actions(obs)
        if isinstance(action, PlayCards) and score_play(obs, action.cards)[0] >= deficit
    ]
    assert winning == [PlayCards((HandSlot(0),))]


@pytest.mark.parametrize(
    "case_id,nines",
    [
        ("gold_sell_unproductive_rental", 0),
        ("gold_keep_productive_rental", 10),
    ],
)
def test_rental_cashflow_is_independent_of_future_draws(case_id, nines):
    obs = observation(case_id)
    joker = obs.jokers[0]
    assert joker.key == "j_cloud_9" and joker.rental and not joker.eternal
    assert sum(entry.count for entry in obs.full_deck if entry.card.rank == "9") == nines
    # Cloud 9 pays once per 9 in the full deck; rental charges $3 per round.
    assert nines - 3 == (-3 if nines == 0 else 7)
    assert ((nines - 3) > joker.sell_cost) is (nines == 10)
    assert obs.money == 0 and not (obs.shop or obs.vouchers or obs.packs)


def test_eternal_rental_has_only_leave_shop_legal():
    obs = observation("gold_eternal_rental_cannot_sell")
    assert obs.jokers[0].eternal and obs.jokers[0].rental
    assert not is_legal(obs, SellJoker(JokerSlot(0)))
    assert list(iter_legal_actions(obs)) == [LeaveShop()]
