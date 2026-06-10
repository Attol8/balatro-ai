"""Mirror a live BalatroBot state into a FastFullGameEnv for planning.

Visible state (hand, deck order, shop offers, prices, jokers, levels) is
copied exactly; only future RNG streams (next shops, pack contents) come from
the env's own seeded generators, which `determinize` varies per sample.
"""

from __future__ import annotations

from typing import Any

from balatro_ai_v2.balatrobot.adapter import card_to_fast_id, hand_to_fast_ids
from balatro_ai_v2.balatrobot.imitation_policy import _area_cards, _buy_cost, _run_phase
from balatro_ai_v2.balatrobot.tactical_planner import (
    _active_required_score,
    _deck_ids,
    _hand_levels,
    _jokers,
)
from balatro_ai_v2.fast.blinds import BLIND_RULES
from balatro_ai_v2.fast.full_game import FastFullGameEnv, MAX_SHOP_OBS
from balatro_ai_v2.fast.hand import HAND_KIND_NAMES
from balatro_ai_v2.fast.jokers import IMPLEMENTED_JOKERS, PROBABILISTIC_SCORE_JOKERS, Joker

# Jokers the live planner must never buy because exact score replay is
# impossible: probabilistic triggers, or float-drift state the snapshot
# reports rounded (Ramen's x_mult decays by 0.01 in Lua floats).
LIVE_UNSAFE_JOKERS = PROBABILISTIC_SCORE_JOKERS | {"j_ramen", "j_raised_fist"}
from balatro_ai_v2.fast.run import BlindKind, RunPhase


class MirrorError(ValueError):
    """The live state cannot be represented in the fast env."""


def mirror_live_state(state: dict[str, Any], *, deck_key: str = "b_red") -> FastFullGameEnv:
    phase = _run_phase(state)
    if phase == RunPhase.GAME_OVER:
        raise MirrorError(f"cannot mirror state {state.get('state')!r}")

    env = FastFullGameEnv(deck_key=deck_key)
    env.reset(seed=_mirror_seed(state))
    run = env.run

    run.ante = max(int(state.get("ante_num") or 1), 1)
    run.round_num = max(int(state.get("round_num") or 1) - 1, 0)
    run.money = int(state.get("money") or 0)
    run.phase = phase
    run.blind_kind = _blind_kind(state, phase)

    env.hand_levels = list(_hand_levels(state))
    env.hand_play_counts = _hand_play_counts(state)
    env.jokers = list(_mirror_jokers(state))
    env.consumables = [
        str(card.get("key") or "")
        for card in _area_cards(state, "consumables")
        if str(card.get("key") or "").startswith("c_")
    ]
    env.purchased_vouchers = [
        str(card.get("key") or "") for card in _area_cards(state, "used_vouchers")
    ]

    deck_ids = list(_deck_ids(state))
    hand_ids = list(hand_to_fast_ids(state))
    # Live draws come from the deck tail; the env draws from the front.
    run.deck = list(reversed(deck_ids))
    run.deck_pos = 0
    env.deck_cards = sorted(deck_ids + hand_ids)

    boss_key = _ante_boss_key(state)
    if boss_key is not None:
        env.boss_key = boss_key
    env.run.required_score = _active_required_score(state)

    round_state = state.get("round") or {}
    env.hands_remaining = int(round_state.get("hands_left") or 0)
    env.discards_remaining = int(round_state.get("discards_left") or 0)
    run.score = int(round_state.get("chips") or 0)
    env.rounds_cleared = run.round_num

    if phase == RunPhase.SELECTING_HAND:
        run.hand = hand_ids
        env.round_hand_size = max(len(hand_ids), 1)
        env.first_hand_kind_this_round = _first_hand_kind(state)
        env.played_hand_kinds_this_round = set(_played_hand_kinds(state))
    elif phase == RunPhase.SHOP:
        _mirror_shop(env, state)
    elif phase == RunPhase.PACK:
        pack_area = state.get("pack") or {}
        env.pack_cards = [str(card.get("key") or "") for card in _area_cards(state, "pack")]
        # Unmodeled or live-unsafe jokers inside packs must never be picked
        # (the shop's 999-pricing cannot guard free pack picks).
        env.pack_banned_indices = {
            index
            for index, key in enumerate(env.pack_cards)
            if key.startswith("j_")
            and (key not in IMPLEMENTED_JOKERS or key in LIVE_UNSAFE_JOKERS)
        }
        # Mega packs allow two picks; live state reports remaining picks as
        # the pack area's highlighted_limit.
        env.pack_choices = max(
            int(pack_area.get("choices") or pack_area.get("highlighted_limit") or 1), 1
        )

    return env


def determinize(env: FastFullGameEnv, sample: int) -> FastFullGameEnv:
    """Clone with a varied seed so hidden future RNG differs per sample."""
    clone = env.clone()
    if sample:
        clone.seed = (clone.seed * 1_000_003 + sample * 7_919_993) % (2**31 - 1)
    return clone


def _mirror_seed(state: dict[str, Any]) -> int:
    seed_text = str(state.get("seed") or "0")
    try:
        return int(seed_text) & 0x7FFFFFFF
    except ValueError:
        return hash(seed_text) & 0x7FFFFFFF


def _blind_kind(state: dict[str, Any], phase: RunPhase) -> BlindKind:
    blinds = state.get("blinds") or {}
    wanted = "SELECT" if phase == RunPhase.BLIND_SELECT else "CURRENT"
    for name, blind in blinds.items():
        if not isinstance(blind, dict) or blind.get("status") != wanted:
            continue
        blind_type = str(blind.get("type") or name).upper()
        if "BOSS" in blind_type:
            return BlindKind.BOSS
        if "BIG" in blind_type:
            return BlindKind.BIG
        return BlindKind.SMALL
    return BlindKind.SMALL


def _ante_boss_key(state: dict[str, Any]) -> str | None:
    """The boss blind of the current ante, visible in any phase."""
    blinds = state.get("blinds") or {}
    for name, blind in blinds.items():
        if not isinstance(blind, dict):
            continue
        blind_type = str(blind.get("type") or name).upper()
        if "BOSS" not in blind_type:
            continue
        blind_name = str(blind.get("name") or "")
        for key, rule in BLIND_RULES.items():
            if rule.name == blind_name:
                return key
    return None


def _mirror_jokers(state: dict[str, Any]) -> tuple[Joker, ...]:
    implemented = {joker.key: joker for joker in _jokers(state)}
    out: list[Joker] = []
    for card in _area_cards(state, "jokers"):
        key = str(card.get("key") or "")
        if key in implemented:
            out.append(implemented[key])
        else:
            # Unmodeled jokers mirror as inert: they keep their slot and sell
            # value but score nothing, which only underestimates the build.
            sell_value = int(((card.get("cost") or {}).get("sell") or 0))
            out.append(Joker(key=key, sell_value=sell_value))
    return tuple(out)


def _hand_play_counts(state: dict[str, Any]) -> list[int]:
    hands = state.get("hands") or {}
    return [
        int((hands.get(hand_name) or {}).get("played") or 0)
        for hand_name in HAND_KIND_NAMES
    ]


def _played_hand_kinds(state: dict[str, Any]) -> tuple[int, ...]:
    hands = state.get("hands") or {}
    return tuple(
        kind
        for kind, hand_name in enumerate(HAND_KIND_NAMES)
        if int((hands.get(hand_name) or {}).get("played_this_round") or 0) > 0
    )


def _first_hand_kind(state: dict[str, Any]) -> int | None:
    played = _played_hand_kinds(state)
    if len(played) == 1:
        return played[0]
    return None


def _mirror_shop(env: FastFullGameEnv, state: dict[str, Any]) -> None:
    run = env.run
    costs: dict[str, int] = {}

    shop_cards = _area_cards(state, "shop")[:MAX_SHOP_OBS]
    run.shop.item_keys = []
    for card in shop_cards:
        key = str(card.get("key") or "")
        run.shop.item_keys.append(key)
        # Jokers the sim cannot score (unmodeled) or cannot score exactly
        # (probabilistic) must never be bought live; price them unaffordable
        # instead of dropping them so shop indices stay aligned.
        if key.startswith("j_") and (
            key not in IMPLEMENTED_JOKERS or key in LIVE_UNSAFE_JOKERS
        ):
            costs[key] = 999
        else:
            costs[key] = _buy_cost(card)

    pack_keys: list[str] = []
    for card in _area_cards(state, "packs")[:2]:
        key = str(card.get("key") or "")
        pack_keys.append(key)
        costs[key] = _buy_cost(card)
    env.pack_keys_override = tuple(pack_keys)

    vouchers = _area_cards(state, "vouchers")
    if vouchers:
        key = str(vouchers[0].get("key") or "")
        env.available_voucher = key
        costs[key] = _buy_cost(vouchers[0])
    else:
        env.available_voucher = None

    run.shop.reroll_cost = int((state.get("round") or {}).get("reroll_cost") or run.base_reroll_cost)
    env.cost_overrides = costs
    env.shop_item_editions = {}
    env.free_shop_item_indices = set()
    env.bought_pack_indices = set()
