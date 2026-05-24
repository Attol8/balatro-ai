from __future__ import annotations

from balatro_ai_v2.balatrobot.policy_config import TacticalPolicyConfig
from balatro_ai_v2.balatrobot.tactical_planner import plan_tactical_action


def test_cached_tactical_plan_matches_uncached_search_with_discards_and_jokers() -> None:
    state = _selecting_hand_state(
        hand=[
            _card("S", "K"),
            _card("D", "K"),
            _card("H", "Q"),
            _card("C", "9"),
            _card("S", "6"),
            _card("H", "5"),
            _card("C", "4"),
            _card("D", "2"),
        ],
        deck=[
            _card("S", "A"),
            _card("S", "Q"),
            _card("S", "J"),
            _card("S", "T"),
            _card("H", "K"),
            _card("C", "K"),
            _card("D", "Q"),
            _card("H", "9"),
            _card("C", "8"),
            _card("D", "7"),
            _card("S", "5"),
            _card("S", "4"),
        ],
        jokers=[
            _joker("j_green_joker", {"extra": 3}),
            _joker("j_runner", {"extra": 15}),
            _joker("j_ride_the_bus", {"mult": 4}),
        ],
        required_score=100_000,
        hands_left=3,
        discards_left=2,
    )
    config = TacticalPolicyConfig(beam_width=24, action_beam=16)

    cached = plan_tactical_action(state, config=config)
    uncached = plan_tactical_action(state, config=config, _use_cache=False)

    assert cached == uncached


def test_cached_tactical_plan_matches_uncached_when_play_can_clear() -> None:
    state = _selecting_hand_state(
        hand=[
            _card("S", "A"),
            _card("S", "K"),
            _card("S", "Q"),
            _card("S", "J"),
            _card("S", "T"),
            _card("H", "2"),
            _card("C", "3"),
            _card("D", "4"),
        ],
        deck=[_card("H", "A"), _card("C", "A"), _card("D", "A")],
        jokers=[_joker("j_joker", {})],
        required_score=100,
        hands_left=4,
        discards_left=3,
    )
    config = TacticalPolicyConfig(beam_width=24, action_beam=16)

    cached = plan_tactical_action(state, config=config)
    uncached = plan_tactical_action(state, config=config, _use_cache=False)

    assert cached == uncached


def _selecting_hand_state(
    *,
    hand: list[dict],
    deck: list[dict],
    jokers: list[dict],
    required_score: int,
    hands_left: int,
    discards_left: int,
) -> dict:
    return {
        "state": "SELECTING_HAND",
        "round_num": 1,
        "ante_num": 1,
        "money": 12,
        "seed": "cache-test",
        "round": {"hands_left": hands_left, "discards_left": discards_left, "chips": 0},
        "hands": {name: {"level": 1, "played": 0} for name in _HAND_NAMES},
        "blinds": {
            "small": {"type": "SMALL", "status": "CURRENT", "score": required_score},
            "big": {"type": "BIG", "status": "UPCOMING", "score": 150},
            "boss": {"type": "BOSS", "status": "UPCOMING", "score": 200},
        },
        "jokers": {"count": len(jokers), "limit": 5, "cards": jokers},
        "cards": {"count": len(deck), "limit": 52, "cards": deck},
        "hand": {"count": len(hand), "limit": 8, "highlighted_limit": 5, "cards": hand},
    }


def _card(suit: str, rank: str) -> dict:
    return {
        "key": f"{suit}_{rank}",
        "value": {"suit": suit, "rank": rank},
        "cost": {"buy": 0, "sell": 0},
    }


def _joker(key: str, ability: dict) -> dict:
    return {
        "key": key,
        "set": "JOKER",
        "value": {"ability": ability},
        "cost": {"buy": 0, "sell": 1},
    }


_HAND_NAMES = (
    "High Card",
    "Pair",
    "Two Pair",
    "Three of a Kind",
    "Straight",
    "Flush",
    "Full House",
    "Four of a Kind",
    "Straight Flush",
    "Five of a Kind",
    "Flush House",
    "Flush Five",
)
