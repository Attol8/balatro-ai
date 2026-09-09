from dataclasses import replace

import pytest

from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.state import (
    DeckCardCount,
    HandStat,
    PublicBlind,
    PublicItem,
    PublicJokerRuntime,
    VisiblePlayingCard,
)
from balatro_ai.readiness import boss_readiness
from tests.game.state_factory import state


def observation(phase="SHOP", *, target=25000, current=False, jokers=()):
    raw = state("SMODS_BOOSTER_OPENED" if phase == "PACK" else phase)
    if phase == "PACK":
        raw["pack_choices_remaining"] = 1
    obs = to_public_observation(raw)
    bases = [
        ("High Card", 5, 1),
        ("Pair", 10, 2),
        ("Two Pair", 20, 2),
        ("Three of a Kind", 30, 3),
        ("Straight", 30, 4),
        ("Flush", 35, 4),
        ("Full House", 40, 4),
        ("Four of a Kind", 60, 7),
        ("Straight Flush", 100, 8),
    ]
    return replace(
        obs,
        deck="BLACK",
        full_deck=tuple(
            DeckCardCount(VisiblePlayingCard(r, s), 1) for r in "23456789TJQKA" for s in "SHCD"
        ),
        deck_size=52,
        draw_count=44,
        jokers=jokers,
        hand_stats=tuple(HandStat(n, 1, c, m, 0, 0) for n, c, m in bases),
        round=replace(obs.round, chips=0, hands_left=1, hands_played=0),
        blinds=(
            PublicBlind(
                "BOSS",
                "CURRENT" if current else "UPCOMING",
                "The Needle",
                "Play only 1 hand",
                target,
                False,
            ),
        ),
    )


@pytest.mark.parametrize(
    "jokers,expected",
    [
        ((), (100 + 51) * 8),
        ((PublicItem("j_joker", "Joker", "JOKER"),), (100 + 51) * (8 + 4)),
        ((PublicItem("j_joker", "Joker", "JOKER", edition="FOIL"),), (100 + 51 + 50) * (8 + 4)),
    ],
)
def test_independent_straight_flush_arithmetic_and_different_builds(jokers, expected):
    row = boss_readiness(observation(jokers=jokers))
    assert row["current_build_optimistic_one_hand_ceiling"] == expected
    assert row["snapshot_ceiling_below_target"]
    assert "Snapshot-only" in row["scope"]
    assert "not guaranteed" in row["scope"]
    assert "can still grow" in row["preparation_note"]
    reversed_row = boss_readiness(observation(target=expected, jokers=jokers))
    assert not reversed_row["snapshot_ceiling_below_target"]


def test_fixed_additive_build_counter_and_card_arithmetic():
    jokers = tuple(
        PublicItem(k, k, "JOKER", runtime=PublicJokerRuntime(current_mult=m))
        for k, m in [("j_green_joker", 14), ("j_trousers", 26)]
    ) + tuple(
        PublicItem(k, k, "JOKER", edition="FOIL" if k == "j_sock_and_buskin" else None)
        for k in ["j_blue_joker", "j_supernova", "j_sock_and_buskin", "j_walkie_talkie"]
    )
    obs = observation("SELECTING_HAND", current=True, jokers=jokers)
    obs = replace(
        obs,
        hand_stats=tuple(
            replace(s, chips=60, mult=4, played=11) if s.name == "Two Pair" else s
            for s in obs.hand_stats
        ),
    )
    row = boss_readiness(obs)
    # Two tens + two fours; Walkie adds 40 chips/16 Mult, foil adds 50 chips,
    # Blue adds 88 chips, Green grows to 15, Trousers to 28, Supernova to 12.
    assert row["current_build_optimistic_one_hand_ceiling"] == (60 + 28 + 40 + 88 + 50) * (
        4 + 16 + 15 + 28 + 12
    )
    assert row["best_family"] == "Two Pair"


def test_future_blue_uses_optimistic_full_pile_not_stale_round_pile():
    jokers = (PublicItem("j_blue_joker", "Blue", "JOKER"),)
    future = boss_readiness(replace(observation(jokers=jokers), draw_count=0))
    current = boss_readiness(observation("SELECTING_HAND", current=True, jokers=jokers))
    assert future["status"] == "upcoming"
    assert current["status"] == "current"
    assert future["current_build_optimistic_one_hand_ceiling"] == (100 + 51 + 104) * 8
    assert current["current_build_optimistic_one_hand_ceiling"] == (100 + 51 + 88) * 8


@pytest.mark.parametrize(
    "joker",
    [
        PublicItem("j_baron", "Baron", "JOKER"),
        PublicItem("j_green_joker", "Green", "JOKER"),
        PublicItem("j_trousers", "Trousers", "JOKER"),
        PublicItem("j_joker", "Joker", "JOKER", edition="POLYCHROME"),
        PublicItem("j_joker", "Joker", "JOKER", debuffed=True),
        PublicItem("j_blue_joker", "Blue", "JOKER", runtime=PublicJokerRuntime(current_chips=10)),
        PublicItem(
            "j_green_joker",
            "Green",
            "JOKER",
            runtime=PublicJokerRuntime(current_mult=1, current_x_mult=2),
        ),
    ],
)
def test_unsupported_jokers_and_runtime_suppress_numbers(joker):
    row = boss_readiness(observation(jokers=(joker,)))
    assert not row["ceiling_available"]
    assert "current_build_optimistic_one_hand_ceiling" not in row
    assert row["ceiling_unavailable_reason"]


@pytest.mark.parametrize(
    "change", ["enhancement", "seal", "edition", "bonus", "deck", "consumable", "stats", "played"]
)
def test_unsupported_cards_decks_or_state(change):
    obs = observation("SELECTING_HAND", current=True)
    card_changes = {
        "enhancement": {"enhancement": "MULT"},
        "seal": {"seal": "RED"},
        "edition": {"edition": "FOIL"},
        "bonus": {"permanent_bonus": 10},
    }
    if change in card_changes:
        first = replace(
            obs.full_deck[0], card=replace(obs.full_deck[0].card, **card_changes[change])
        )
        obs = replace(obs, full_deck=(first, *obs.full_deck[1:]))
    elif change == "deck":
        obs = replace(obs, deck="PLASMA")
    elif change == "consumable":
        obs = replace(obs, consumables=(PublicItem("c_pluto", "Pluto", "PLANET"),))
    elif change == "stats":
        obs = replace(obs, hand_stats=obs.hand_stats[:1])
    else:
        obs = replace(obs, round=replace(obs.round, hands_played=1))
    assert not boss_readiness(obs)["ceiling_available"]


@pytest.mark.parametrize(
    "name,phrase",
    [
        ("The Wall", "Larger target"),
        ("Violet Vessel", "Much larger"),
        ("The Plant", "Face cards"),
        ("The Psychic", "five cards"),
        ("The Eye", "several"),
        ("The Mouth", "one poker-hand"),
        ("The Flint", "halved"),
        ("The Water", "zero discards"),
        ("The Manacle", "reduced by one"),
    ],
)
@pytest.mark.parametrize("phase", ["SHOP", "PACK", "BLIND_SELECT"])
def test_public_boss_hints(name, phrase, phase):
    obs = observation(phase)
    obs = replace(obs, blinds=(replace(obs.blinds[0], name=name, effect="Visible effect"),))
    row = boss_readiness(obs)
    assert phrase in row["preparation"]
    assert row["effect"] == "Visible effect"
    assert not row["ceiling_available"]


def test_completed_disabled_and_not_current_bosses():
    obs = observation()
    assert boss_readiness(replace(obs, blinds=(replace(obs.blinds[0], status="DEFEATED"),))) == {}
    assert boss_readiness(observation("SELECTING_HAND")) == {}
    obs = observation("SELECTING_HAND", current=True)
    row = boss_readiness(replace(obs, blinds=(replace(obs.blinds[0], disabled=True),)))
    assert not row["ceiling_available"]
    assert "disabled" in row["preparation"]


def test_modified_held_cards_suppress_ceiling_even_if_composition_is_inconsistent():
    obs = observation("SELECTING_HAND", current=True)
    obs = replace(obs, hand=(VisiblePlayingCard("K", "S", enhancement="STEEL"),))
    assert not boss_readiness(obs)["ceiling_available"]


def test_select_status_supported():
    obs = observation("BLIND_SELECT")
    obs = replace(obs, blinds=(replace(obs.blinds[0], status="SELECT"),))
    assert boss_readiness(obs)["ceiling_available"]
