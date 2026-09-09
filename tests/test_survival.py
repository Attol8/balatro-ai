from dataclasses import replace

import pytest

from balatro_ai.analysis import analyze
from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.state import PublicItem, PublicJokerRuntime
from balatro_ai.survival import survival_context
from tests.game.state_factory import state


def test_black_gold_uses_observed_resources_and_exposes_risks():
    base = to_public_observation(state("SHOP"))
    observation = replace(
        base,
        deck="BLACK",
        stake="GOLD",
        money=4,
        joker_limit=7,
        round=replace(base.round, hands_left=4, discards_left=2),
        jokers=(
            PublicItem("j_joker", "Joker", "JOKER", eternal=True),
            PublicItem(
                "j_greedy_joker",
                "Greedy Joker",
                "JOKER",
                rental=True,
                perishable_rounds=0,
                debuffed=True,
            ),
            PublicItem("j_blue_joker", "Blue Joker", "JOKER", rental=True, perishable_rounds=1),
        ),
    )
    result = analyze(observation)["survival_context"]
    assert (result["hands_left"], result["discards_left"], result["joker_limit"]) == (4, 2, 7)
    assert result["visible_rental_charge_per_round"] == 6
    assert result["money_less_visible_rent_only"] == -2
    assert result["eternal_slots"] == [0]
    assert result["non_eternal_slots"] == [1, 2]
    assert result["perishables"][0]["expired"] is True
    assert result["perishables"][0]["expires_at_next_round_end"] is False
    assert result["perishables"][1]["expires_at_next_round_end"] is True


def test_offered_rental_does_not_count_as_owned_charge():
    base = to_public_observation(state("SHOP"))
    observation = replace(
        base, jokers=(), shop=(PublicItem("j_mime", "Mime", "JOKER", rental=True, eternal=True),)
    )
    result = survival_context(observation)
    assert result["visible_rental_charge_per_round"] == 0
    assert result["stickered_offers"] == [
        {
            "zone": "shop",
            "slot": 0,
            "key": "j_mime",
            "eternal": True,
            "rental_charge_per_round": 3,
            "perishable_rounds": None,
        }
    ]


def test_ordinary_red_white_packet_does_not_gain_survival_context():
    observation = replace(to_public_observation(state("SHOP")), jokers=(), shop=())
    assert "survival_context" not in analyze(observation)


def test_owned_decay_triggers_context_without_black_gold_or_stickers():
    base = to_public_observation(state("SHOP"))
    observation = replace(
        base,
        jokers=(
            PublicItem(
                "j_ice_cream", "Ice Cream", "JOKER", runtime=PublicJokerRuntime(current_chips=35)
            ),
            PublicItem(
                "j_popcorn", "Popcorn", "JOKER", runtime=PublicJokerRuntime(current_mult=12)
            ),
            PublicItem(
                "j_turtle_bean",
                "Turtle Bean",
                "JOKER",
                runtime=PublicJokerRuntime(current_hand_size_bonus=3),
            ),
        ),
        shop=(),
    )
    rows = analyze(observation)["survival_context"]["decaying_jokers"]
    assert [
        (row["slot"], row["current_value"], row["next_value_if_still_active"]) for row in rows
    ] == [(0, 35, 30), (1, 12, 8), (2, 3, 2)]
    assert [(row["decay_amount"], row["value_unit"], row["decay_trigger"]) for row in rows] == [
        (5, "chips", "after_played_hand"),
        (4, "mult", "round_end"),
        (1, "hand_size_bonus", "round_end"),
    ]
    assert all(row["removed_at_next_trigger_if_still_active"] is False for row in rows)


@pytest.mark.parametrize("runtime", [None, PublicJokerRuntime()])
@pytest.mark.parametrize("key", ["j_ice_cream", "j_popcorn", "j_turtle_bean"])
def test_missing_decay_runtime_keeps_values_unknown(key, runtime):
    base = to_public_observation(state("SHOP"))
    item = PublicItem(key, key, "JOKER", runtime=runtime, effect_text="Visible decay effect")
    row = survival_context(replace(base, jokers=(item,), shop=()))["decaying_jokers"][0]
    assert row["current_value"] is None
    assert row["current_effect_value"] is None
    assert row["next_value_if_still_active"] is None
    assert row["removed_at_next_trigger_if_still_active"] is None
    assert row["effect_text"] == "Visible decay effect"


@pytest.mark.parametrize(
    "key,field,value",
    [
        ("j_ice_cream", "current_chips", 5),
        ("j_popcorn", "current_mult", 4),
        ("j_turtle_bean", "current_hand_size_bonus", 1),
    ],
)
@pytest.mark.parametrize("debuffed", [False, True])
def test_decay_terminal_value_and_debuff_pause(key, field, value, debuffed):
    base = to_public_observation(state("SHOP"))
    item = PublicItem(
        key, key, "JOKER", runtime=PublicJokerRuntime(**{field: value}), debuffed=debuffed
    )
    row = survival_context(replace(base, jokers=(item,), shop=()))["decaying_jokers"][0]
    assert row["current_value"] == value
    assert row["current_effect_value"] == (0 if debuffed else value)
    assert row["decays_while_debuffed"] is False
    assert row["next_value_if_still_active"] == (None if debuffed else 0)
    assert row["removed_at_next_trigger_if_still_active"] is (None if debuffed else True)


def test_decay_and_stickers_remain_separate_and_do_not_mutate_observation():
    base = to_public_observation(state("SHOP"))
    item = PublicItem(
        "j_popcorn",
        "Popcorn",
        "JOKER",
        runtime=PublicJokerRuntime(current_mult=12),
        rental=True,
        perishable_rounds=1,
    )
    observation = replace(base, jokers=(item,), shop=())
    result = survival_context(observation)
    assert result["decaying_jokers"][0]["next_value_if_still_active"] == 8
    assert result["perishables"][0]["expires_at_next_round_end"] is True
    assert result["visible_rental_charge_per_round"] == 3
    assert observation.jokers[0].runtime.current_mult == 12
    assert observation.jokers[0].perishable_rounds == 1
    assert observation.jokers[0].debuffed is False


def test_shop_decay_offer_does_not_create_owned_decay_advice():
    base = to_public_observation(state("SHOP"))
    observation = replace(base, jokers=(), shop=(PublicItem("j_popcorn", "Popcorn", "JOKER"),))
    assert survival_context(observation) == {}
