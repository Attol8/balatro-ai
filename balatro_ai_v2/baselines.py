"""Small public-information baselines for coverage and later comparison.

These policies are deliberately not learning agents.  They exist to drive
organic public actions through both kernels and expose the first divergence.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import combinations, islice
from typing import Literal

from balatro_ai_v2.actions import (
    BuyPack,
    BuyShopCard,
    BuyVoucher,
    CashOut,
    ChoosePackCard,
    ConsumableSlot,
    DiscardCards,
    HandSlot,
    JokerSlot,
    LeaveShop,
    PlayCards,
    PublicAction,
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    RerollShop,
    SelectBlind,
    SellJoker,
    SkipBlind,
    SkipPack,
    UseConsumable,
    action_to_data,
    is_legal,
)
from balatro_ai_v2.belief import PublicDrawBelief
from balatro_ai_v2.policy import ActionSource, PublicHistoryStep, PublicPolicy
from balatro_ai_v2.public_state import (
    HandStat,
    HiddenHandCard,
    Phase,
    PublicItem,
    PublicObservation,
    VisiblePlayingCard,
)


_RANK_CHIPS = {"A": 11, "K": 10, "Q": 10, "J": 10, "T": 10, **{str(value): value for value in range(2, 10)}}
_RANK_ORDER = {"A": 14, "K": 13, "Q": 12, "J": 11, "T": 10, **{str(value): value for value in range(2, 10)}}
_REORDER_TYPES = (ReorderHand, ReorderJokers, ReorderConsumables)
_MAX_TACTICAL_CANDIDATES = 2048
_MAX_PUBLIC_ACTIONS = 256
_MAX_STRATEGIC_ACTIONS = 512
_MAX_PUBLIC_DRAW_BRANCHES = 512
PUBLIC_BASELINE_NAMES = (
    "random",
    "greedy",
    "tactical",
    "strategic",
    "preboss_search",
    "red_gold_search",
)

_TYPE_MULT_JOKERS = {
    "j_jolly": ("Pair", 8),
    "j_zany": ("Three of a Kind", 12),
    "j_mad": ("Two Pair", 10),
    "j_crazy": ("Straight", 12),
    "j_droll": ("Flush", 10),
}
_TYPE_CHIP_JOKERS = {
    "j_sly": ("Pair", 50),
    "j_wily": ("Three of a Kind", 100),
    "j_clever": ("Two Pair", 80),
    "j_devious": ("Straight", 100),
    "j_crafty": ("Flush", 80),
}
_TYPE_XMULT_JOKERS = {
    "j_duo": ("Pair", 2),
    "j_trio": ("Three of a Kind", 3),
    "j_family": ("Four of a Kind", 4),
    "j_order": ("Straight", 3),
    "j_tribe": ("Flush", 2),
}
_SUIT_MULT_JOKERS = {
    "j_greedy_joker": "D",
    "j_lusty_joker": "H",
    "j_wrathful_joker": "S",
    "j_gluttenous_joker": "C",
}
_FACE_RANKS = {"J", "Q", "K"}
_FIBONACCI_RANKS = {"A", "2", "3", "5", "8"}

_GREAT_JOKERS = {
    "j_blackboard",
    "j_blueprint",
    "j_brainstorm",
    "j_duo",
    "j_family",
    "j_hologram",
    "j_order",
    "j_steel_joker",
    "j_stencil",
    "j_tribe",
    "j_trio",
}
_GOOD_JOKERS = {
    "j_ancient",
    "j_blue_joker",
    "j_business",
    "j_chaos",
    "j_cloud_9",
    "j_constellation",
    "j_delayed_grat",
    "j_dusk",
    "j_faceless",
    "j_golden",
    "j_green_joker",
    "j_hack",
    "j_hanging_chad",
    "j_ice_cream",
    "j_idol",
    "j_loyalty_card",
    "j_obelisk",
    "j_photograph",
    "j_red_card",
    "j_ride_the_bus",
    "j_runner",
    "j_sock_and_buskin",
    "j_swashbuckler",
    "j_to_the_moon",
    "j_trousers",
}
_SCALING_JOKERS = {
    "j_green_joker",
    "j_ride_the_bus",
    "j_runner",
    "j_square",
    "j_trousers",
}
_ECONOMY_JOKERS = {
    "j_business",
    "j_cloud_9",
    "j_delayed_grat",
    "j_faceless",
    "j_golden",
    "j_to_the_moon",
}
_REPLACEMENT_MARGIN = 20


def build_public_baseline(name: str, policy_seed: str) -> tuple[PublicPolicy, str]:
    if name == "random":
        return DeterministicRandomPolicy(policy_seed), f"DeterministicRandomPolicy:{policy_seed}"
    if name == "greedy":
        return GreedyImmediatePolicy(), "GreedyImmediatePolicy"
    if name == "tactical":
        return PublicBeliefTacticalPolicy(), "PublicBeliefTacticalPolicy"
    if name == "strategic":
        return PublicStrategicPolicy(), "PublicStrategicPolicy"
    if name == "preboss_search":
        from balatro_ai_v2.preboss_search import PublicPreBossSearchPolicy

        return (
            PublicPreBossSearchPolicy(search_nonce=policy_seed),
            f"PublicPreBossSearchPolicy:{policy_seed}",
        )
    if name == "red_gold_search":
        from balatro_ai_v2.solver_policy import PublicRedGoldSearchPolicy

        return (
            PublicRedGoldSearchPolicy(search_nonce=policy_seed),
            f"PublicRedGoldSearchPolicy:{policy_seed}",
        )
    raise ValueError(f"unknown public baseline {name!r}")


@dataclass(frozen=True, slots=True)
class DeterministicRandomPolicy:
    """Bounded random legal-action control using public state only."""

    policy_seed: str = "random-v1"

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        actions = _bounded_actions(legal_actions())
        if not actions:
            raise RuntimeError(f"no bounded public action for {observation.phase.value}")
        payload = f"{self.policy_seed}\0{len(history)}\0{observation.digest()}"
        number = int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")
        return actions[number % len(actions)]


@dataclass(frozen=True, slots=True)
class GreedyImmediatePolicy:
    """Immediate visible-score baseline with no strategic shop model."""

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        del history
        if observation.phase == Phase.SELECTING_HAND:
            return _best_play(observation, 0)[0]
        return _passive_control_action(observation, legal_actions)


@dataclass(frozen=True, slots=True)
class PublicBeliefTacticalPolicy:
    """One-ply public expectimax over a bounded visible-score surrogate."""

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        del history
        if observation.phase == Phase.SELECTING_HAND:
            return _belief_tactical_action(observation)
        return _passive_control_action(observation, legal_actions)


@dataclass(frozen=True, slots=True)
class PublicStrategicPolicy:
    """Bounded strategic baseline using only explicit public state."""

    max_shop_actions: int = 6

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        if observation.phase == Phase.BLIND_SELECT:
            return SelectBlind()
        if observation.phase == Phase.SELECTING_HAND:
            actions = _bounded_actions(legal_actions(), _MAX_STRATEGIC_ACTIONS)
            planet = _held_planet_action(observation)
            if planet is not None and planet in actions:
                return planet
            best, hand_name = _best_available_play(observation, actions)
            discard = _coverage_discard(observation, best, hand_name)
            return discard if discard in actions else best
        if observation.phase == Phase.ROUND_EVAL:
            return CashOut()
        actions = _bounded_actions(legal_actions())
        if observation.phase == Phase.SHOP:
            return _strategic_shop_action(observation, actions, history, self.max_shop_actions)
        if observation.phase == Phase.PACK:
            return _strategic_pack_action(observation, actions)
        raise RuntimeError(f"no strategic action for {observation.phase.value}")


@dataclass(frozen=True, slots=True)
class DeterministicCoveragePolicy:
    """Exercise public action families without consulting privileged state."""

    policy_seed: str = "coverage-v1"
    max_shop_actions: int = 3
    pack_strategy: Literal["mixed", "skip", "pick"] = "mixed"
    coverage_mode: Literal["default", "extended"] = "default"

    def __post_init__(self) -> None:
        if self.max_shop_actions < 0:
            raise ValueError("max_shop_actions must be non-negative")
        if self.coverage_mode not in {"default", "extended"}:
            raise ValueError(f"unsupported coverage mode {self.coverage_mode!r}")

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        if observation.phase == Phase.BLIND_SELECT:
            actions = _bounded_actions(legal_actions())
            skips = [action for action in actions if isinstance(action, SkipBlind)]
            if skips and self._number(observation, history, "blind") % 5 == 0:
                return skips[0]
            return next(action for action in actions if isinstance(action, SelectBlind))

        if observation.phase == Phase.SELECTING_HAND:
            planet = _held_planet_action(observation)
            if self.coverage_mode == "extended" and planet is not None:
                return planet
            best, hand_name = _best_play(observation, self._number(observation, history, "tactical"))
            discard = _coverage_discard(observation, best, hand_name)
            if discard is not None:
                return discard
            return best

        if observation.phase == Phase.ROUND_EVAL:
            return CashOut()

        if observation.phase == Phase.SHOP:
            actions = _bounded_actions(legal_actions())
            shop_steps = _current_shop_action_count(history)
            if shop_steps >= self.max_shop_actions:
                return next(action for action in actions if isinstance(action, LeaveShop))
            rerolls = [action for action in actions if isinstance(action, RerollShop)]
            if self.coverage_mode == "extended" and rerolls and shop_steps == 0:
                return rerolls[0]
            planet = _held_planet_action(observation)
            if self.coverage_mode == "extended" and planet is not None:
                return planet
            pack_purchases = [action for action in actions if isinstance(action, BuyPack)]
            if pack_purchases and self.pack_strategy != "mixed" and shop_steps == 0:
                return self._pick(pack_purchases, observation, history, "pack-buy")
            purchases = [
                action for action in actions if isinstance(action, (BuyShopCard, BuyPack, BuyVoucher))
            ]
            if purchases and (shop_steps == 0 or self._number(observation, history, "buy") % 3):
                return self._pick(purchases, observation, history, "buy-choice")
            if rerolls and shop_steps == 0:
                return rerolls[0]
            return next(action for action in actions if isinstance(action, LeaveShop))

        if observation.phase == Phase.PACK:
            actions = _bounded_actions(legal_actions())
            if self.pack_strategy == "skip":
                return next(action for action in actions if isinstance(action, SkipPack))
            choices = [action for action in actions if isinstance(action, ChoosePackCard)]
            if choices and (
                self.pack_strategy == "pick" or self._number(observation, history, "pack") % 4
            ):
                return self._pick(choices, observation, history, "pack-choice")
            return next(action for action in actions if isinstance(action, SkipPack))

        raise RuntimeError(f"no coverage action for {observation.phase.value}")

    def _pick(
        self,
        actions: list[PublicAction],
        observation: PublicObservation,
        history: tuple[PublicHistoryStep, ...],
        label: str,
    ) -> PublicAction:
        ordered = sorted(actions, key=lambda action: json.dumps(action_to_data(action), sort_keys=True))
        return ordered[self._number(observation, history, label) % len(ordered)]

    def _number(
        self,
        observation: PublicObservation,
        history: tuple[PublicHistoryStep, ...],
        label: str,
    ) -> int:
        payload = f"{self.policy_seed}\0{label}\0{len(history)}\0{observation.digest()}"
        return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def _best_play(observation: PublicObservation, tie_seed: int) -> tuple[PlayCards, str]:
    action, hand_name, _ = _best_play_with_score(observation, tie_seed)
    return action, hand_name


def _best_play_with_score(
    observation: PublicObservation,
    tie_seed: int,
    hand_stats: Mapping[str, HandStat] | None = None,
) -> tuple[PlayCards, str, int | Fraction]:
    slots = tuple(HandSlot(index) for index in range(len(observation.hand)))
    maximum = min(5, observation.selection_limit, len(slots))
    candidate_slots = islice(
        (
            selected
            for size in range(maximum, 0, -1)
            for selected in combinations(slots, size)
            if set(observation.required_hand_slots).issubset(
                slot.value for slot in selected
            )
        ),
        _MAX_TACTICAL_CANDIDATES,
    )
    stats = hand_stats if hand_stats is not None else {hand.name: hand for hand in observation.hand_stats}
    best: tuple[int | Fraction, int, tuple[HandSlot, ...], str] | None = None
    for selected in candidate_slots:
        score, hand_name = _play_score(observation, selected, stats)
        tie = (tie_seed ^ sum((slot.value + 1) * 0x9E3779B1 for slot in selected)) & 0xFFFFFFFF
        candidate = (score, tie, selected, hand_name)
        if best is None or (candidate[0], candidate[1]) > (best[0], best[1]):
            best = candidate
    if best is None:
        raise RuntimeError("selecting-hand state has no legal cards")
    score, _, selected, hand_name = best
    return PlayCards(selected), hand_name, score


def _best_available_play(
    observation: PublicObservation,
    actions: list[PublicAction],
) -> tuple[PlayCards, str]:
    stats = {hand.name: hand for hand in observation.hand_stats}
    plays = [action for action in actions if isinstance(action, PlayCards)]
    if not plays:
        raise RuntimeError("strategic proposal contains no playable hand")
    scored = [(*_play_score(observation, action.cards, stats), action) for action in plays]
    _, hand_name, best = max(
        scored,
        key=lambda row: (row[0], tuple(-slot.value for slot in row[2].cards)),
    )
    return best, hand_name


def _play_score(
    observation: PublicObservation,
    selected: tuple[HandSlot, ...],
    stats: Mapping[str, HandStat],
) -> tuple[int | Fraction, str]:
    cards = tuple(observation.hand[slot.value] for slot in selected)
    hand_name = _classify(cards)
    stat = stats.get(hand_name)
    scoring_cards = (
        tuple(card for card in cards if isinstance(card, VisiblePlayingCard))
        if any(joker.key == "j_splash" for joker in observation.jokers)
        else _scoring_cards(cards, hand_name)
    )
    chips = (stat.chips if stat is not None else 0) + sum(
        _card_chips(card) for card in scoring_cards
    )
    mult: int | Fraction = (stat.mult if stat is not None else 1) + sum(
        4
        for card in scoring_cards
        if card.enhancement == "MULT" and not card.debuffed
    )
    mult += sum(
        10
        for card in scoring_cards
        if card.edition in {"HOLO", "HOLOGRAPHIC"} and not card.debuffed
    )
    multiplier: int | Fraction = 1
    for card in scoring_cards:
        if card.enhancement == "GLASS" and not card.debuffed:
            multiplier *= 2
        if card.edition == "POLYCHROME" and not card.debuffed:
            multiplier *= Fraction(3, 2)
    selected_slots = {slot.value for slot in selected}
    for index, card in enumerate(observation.hand):
        if (
            index not in selected_slots
            and isinstance(card, VisiblePlayingCard)
            and card.enhancement == "STEEL"
            and not card.debuffed
        ):
            multiplier *= Fraction(3, 2)

    for joker in observation.jokers:
        if joker.debuffed:
            continue
        card_chips, card_mult = _card_joker_effect(joker.key, scoring_cards)
        chips += card_chips
        mult += card_mult
        joker_chips, joker_mult, joker_xmult = _joker_main_effect(
            observation,
            cards,
            hand_name,
            stats,
            joker.key,
        )
        chips += joker_chips
        mult += joker_mult
        mult *= joker_xmult
        if joker.edition == "FOIL":
            chips += 50
        elif joker.edition in {"HOLO", "HOLOGRAPHIC"}:
            mult += 10
        elif joker.edition == "POLYCHROME":
            mult *= Fraction(3, 2)
    return chips * mult * multiplier, hand_name


def _card_joker_effect(
    key: str,
    cards: tuple[VisiblePlayingCard, ...],
) -> tuple[int, int]:
    chips = 0
    mult = 0
    for card in cards:
        if card.debuffed:
            continue
        if key in _SUIT_MULT_JOKERS and card.suit == _SUIT_MULT_JOKERS[key]:
            mult += 3
        elif key == "j_fibonacci" and card.rank in _FIBONACCI_RANKS:
            mult += 8
        elif key == "j_even_steven" and card.rank in {"2", "4", "6", "8", "T"}:
            mult += 4
        elif key == "j_odd_todd" and card.rank in {"A", "3", "5", "7", "9"}:
            chips += 31
        elif key == "j_scary_face" and card.rank in _FACE_RANKS:
            chips += 30
        elif key == "j_smiley" and card.rank in _FACE_RANKS:
            mult += 5
        elif key == "j_scholar" and card.rank == "A":
            chips += 20
            mult += 4
        elif key == "j_walkie_talkie" and card.rank in {"4", "T"}:
            chips += 10
            mult += 4
    return chips, mult


def _joker_main_effect(
    observation: PublicObservation,
    cards: tuple[VisiblePlayingCard | HiddenHandCard, ...],
    hand_name: str,
    stats: Mapping[str, HandStat],
    key: str,
) -> tuple[int, int, int | Fraction]:
    chips = 0
    mult = 0
    xmult: int | Fraction = 1
    if key == "j_joker":
        mult += 4
    if key in _TYPE_MULT_JOKERS:
        family, value = _TYPE_MULT_JOKERS[key]
        mult += value if _hand_matches(cards, hand_name, family) else 0
    if key in _TYPE_CHIP_JOKERS:
        family, value = _TYPE_CHIP_JOKERS[key]
        chips += value if _hand_matches(cards, hand_name, family) else 0
    if key in _TYPE_XMULT_JOKERS:
        family, value = _TYPE_XMULT_JOKERS[key]
        xmult *= value if _hand_matches(cards, hand_name, family) else 1
    if key == "j_half" and len(cards) <= 3:
        mult += 20
    elif key == "j_abstract":
        mult += 3 * len(observation.jokers)
    elif key == "j_acrobat" and observation.round.hands_left == 1:
        xmult *= 3
    elif key == "j_mystic_summit" and observation.round.discards_left == 0:
        mult += 15
    elif key == "j_banner":
        chips += 30 * observation.round.discards_left
    elif key == "j_supernova":
        stat = stats.get(hand_name)
        mult += (stat.played + 1) if stat is not None else 1
    elif key == "j_blue_joker":
        chips += 2 * observation.draw_count
    elif key == "j_bull":
        chips += 2 * max(0, observation.money)
    elif key == "j_stuntman":
        chips += 250
    elif key == "j_gros_michel":
        mult += 15
    elif key == "j_cavendish":
        xmult *= 3
    elif key == "j_card_sharp":
        stat = stats.get(hand_name)
        if stat is not None and stat.played_this_round >= 1:
            xmult *= 3
    elif key == "j_bootstraps":
        mult += 2 * (max(0, observation.money) // 5)
    elif key == "j_runner" and _hand_matches(cards, hand_name, "Straight"):
        chips += 15
    elif key == "j_square" and len(cards) == 4:
        chips += 4
    elif key == "j_trousers" and hand_name in {"Two Pair", "Full House", "Flush House"}:
        mult += 2
    return chips, mult, xmult


def _belief_tactical_action(observation: PublicObservation) -> PublicAction:
    hand_stats = {hand.name: hand for hand in observation.hand_stats}
    play, _, current_score = _best_play_with_score(observation, 0, hand_stats)
    if (
        observation.round.discards_left <= 0
        or any(isinstance(card, HiddenHandCard) for card in observation.hand)
        or not observation.hand
    ):
        return play
    try:
        belief = PublicDrawBelief.from_observation(observation)
    except ValueError:
        return play
    if belief.draw_count == 0:
        return play

    candidates = tuple(HandSlot(index) for index in range(len(observation.hand)))
    if len(candidates) * len(belief.remaining_deck) > _MAX_PUBLIC_DRAW_BRANCHES:
        return play

    ranked: list[tuple[Fraction, int, DiscardCards]] = []
    for slot in candidates:
        discard = DiscardCards((slot,))
        if not is_legal(observation, discard):
            continue
        weighted_score = Fraction(0)
        for entry in belief.remaining_deck:
            hand = list(observation.hand)
            hand[slot.value] = entry.card
            hypothetical = replace(observation, hand=tuple(hand))
            _, _, score = _best_play_with_score(hypothetical, 0, hand_stats)
            weighted_score += entry.count * score
        expected_score = weighted_score / belief.draw_count
        ranked.append((expected_score, -slot.value, discard))
    if not ranked:
        return play
    expected_score, _, discard = max(ranked, key=lambda item: (item[0], item[1]))
    return discard if expected_score > current_score else play


def _passive_control_action(
    observation: PublicObservation,
    legal_actions: ActionSource,
) -> PublicAction:
    actions = _bounded_actions(legal_actions())
    expected = {
        Phase.BLIND_SELECT: SelectBlind,
        Phase.ROUND_EVAL: CashOut,
        Phase.SHOP: LeaveShop,
        Phase.PACK: SkipPack,
    }.get(observation.phase)
    if expected is None:
        raise RuntimeError(f"no passive action for {observation.phase.value}")
    return next(action for action in actions if isinstance(action, expected))


def _held_planet_action(observation: PublicObservation) -> UseConsumable | None:
    for index, item in enumerate(observation.consumables):
        if item.kind.upper() == "PLANET":
            action = UseConsumable(ConsumableSlot(index))
            return action if is_legal(observation, action) else None
    return None


def _strategic_shop_action(
    observation: PublicObservation,
    actions: list[PublicAction],
    history: tuple[PublicHistoryStep, ...],
    max_shop_actions: int,
) -> PublicAction:
    planet = _held_planet_action(observation)
    if planet is not None and planet in actions:
        return planet
    shop_steps = _current_shop_action_count(history)
    if shop_steps >= max_shop_actions:
        return _action_of_type(actions, LeaveShop)

    building = len(observation.jokers) < min(4, observation.joker_limit)
    interest_floor = 0 if observation.ante <= 2 and len(observation.jokers) < 3 else 5
    if observation.ante > 5:
        interest_floor = 10
    spendable = observation.money - interest_floor

    replacement = _replacement_sale(
        observation,
        actions,
        shop_steps=shop_steps,
        max_shop_actions=max_shop_actions,
        interest_floor=interest_floor,
        already_replaced=any(isinstance(step.action, SellJoker) for step in history),
    )
    if replacement is not None:
        return replacement

    joker_buys = [
        action
        for action in actions
        if isinstance(action, BuyShopCard)
        and observation.shop[action.card.value].kind.upper() == "JOKER"
    ]
    affordable_jokers = [
        action
        for action in joker_buys
        if (observation.shop[action.card.value].buy_cost or 0) <= observation.money
    ]
    if affordable_jokers:
        best_joker = max(
            affordable_jokers,
            key=lambda action: (
                _joker_value(observation.shop[action.card.value]),
                -(observation.shop[action.card.value].buy_cost or 0),
                -action.card.value,
            ),
        )
        item = observation.shop[best_joker.card.value]
        cost = item.buy_cost or 0
        item_value = _joker_value(item)
        if (building or item_value >= 25) and cost <= spendable:
            return best_joker

    rerolls = [action for action in actions if isinstance(action, RerollShop)]
    if building and not affordable_jokers and rerolls and shop_steps < 3:
        if observation.round.reroll_cost <= spendable:
            return rerolls[0]

    vouchers = [action for action in actions if isinstance(action, BuyVoucher)]
    if vouchers:
        return min(
            vouchers,
            key=lambda action: (
                observation.vouchers[action.voucher.value].buy_cost or 0,
                action.voucher.value,
            ),
        )

    pack_buys = [
        action
        for action in actions
        if isinstance(action, BuyPack)
        and (observation.packs[action.pack.value].buy_cost or 0) <= spendable
    ]
    if pack_buys:
        return max(
            pack_buys,
            key=lambda action: (
                int(
                    building
                    and observation.packs[action.pack.value].key.startswith("p_buffoon")
                ),
                -(observation.packs[action.pack.value].buy_cost or 0),
                -action.pack.value,
            ),
        )

    if len(observation.consumables) < observation.consumable_limit:
        planet_buys = [
            action
            for action in actions
            if isinstance(action, BuyShopCard)
            and observation.shop[action.card.value].kind.upper() == "PLANET"
            and (observation.shop[action.card.value].buy_cost or 0) <= spendable
        ]
        if planet_buys:
            return min(planet_buys, key=lambda action: action.card.value)

    if rerolls and observation.round.reroll_cost == 0:
        return rerolls[0]
    return _action_of_type(actions, LeaveShop)


def _strategic_pack_action(
    observation: PublicObservation,
    actions: list[PublicAction],
) -> PublicAction:
    choices = [action for action in actions if isinstance(action, ChoosePackCard)]
    if not choices:
        return _action_of_type(actions, SkipPack)

    def value(action: ChoosePackCard) -> tuple[int, int]:
        offer = observation.opened_pack[action.card.value]
        if isinstance(offer, VisiblePlayingCard):
            return 5, -action.card.value
        if offer.kind.upper() == "PLANET":
            return 70, -action.card.value
        if offer.kind.upper() == "JOKER":
            return 40 + _joker_value(offer), -action.card.value
        return 0, -action.card.value

    return max(choices, key=value)


def _joker_value(item: PublicItem) -> int:
    if item.key in _GREAT_JOKERS:
        value = 90
    elif item.key in _GOOD_JOKERS:
        value = 60
    else:
        value = 15
    if item.edition == "POLYCHROME":
        value += 25
    elif item.edition in {"FOIL", "HOLO", "HOLOGRAPHIC"}:
        value += 10
    if item.rental:
        value -= 25
    if item.perishable_rounds is not None:
        value -= 10
    return value


def _owned_joker_value(item: PublicItem, ante: int) -> int:
    value = _joker_value(item)
    if item.key in _SCALING_JOKERS:
        value += 20
    if ante >= 4 and item.key in _ECONOMY_JOKERS:
        value -= 50
    return value


def _replacement_sale(
    observation: PublicObservation,
    actions: list[PublicAction],
    *,
    shop_steps: int,
    max_shop_actions: int,
    interest_floor: int,
    already_replaced: bool,
) -> SellJoker | None:
    if observation.ante < 6 or already_replaced:
        return None
    if observation.joker_limit <= 0 or len(observation.jokers) != observation.joker_limit:
        return None
    if shop_steps + 1 >= max_shop_actions:
        return None

    sellable = [
        (index, item)
        for index, item in enumerate(observation.jokers)
        if not item.eternal
        and item.edition != "NEGATIVE"
        and item.sell_cost is not None
        and item.sell_cost >= 0
    ]
    if not sellable:
        return None
    weakest_index, weakest = min(
        sellable,
        key=lambda entry: (
            _owned_joker_value(entry[1], observation.ante),
            -entry[1].sell_cost,
            entry[0],
        ),
    )

    owned_keys = {item.key for item in observation.jokers}
    building_after_sale = len(observation.jokers) - 1 < min(4, observation.joker_limit)
    offers = [
        item
        for item in observation.shop
        if item.kind.upper() == "JOKER"
        and item.key not in owned_keys
        and item.buy_cost is not None
        and item.buy_cost >= 0
        and (building_after_sale or _joker_value(item) >= 25)
        and observation.money + weakest.sell_cost - item.buy_cost >= interest_floor
    ]
    if not offers:
        return None
    best_offer = max(offers, key=lambda item: (_joker_value(item), -item.buy_cost, item.key))
    if _joker_value(best_offer) < _owned_joker_value(weakest, observation.ante) + _REPLACEMENT_MARGIN:
        return None

    action = SellJoker(JokerSlot(weakest_index))
    return action if action in actions else None


def _action_of_type(
    actions: list[PublicAction],
    action_type: type[object],
) -> PublicAction:
    return next(action for action in actions if isinstance(action, action_type))


def _coverage_discard(
    observation: PublicObservation,
    best: PlayCards,
    hand_name: str,
) -> DiscardCards | None:
    if observation.round.discards_left <= 0 or observation.round.discards_used >= 2:
        return None
    if any(joker.key in {"j_green_joker", "j_ramen"} for joker in observation.jokers):
        return None
    if hand_name not in {"High Card", "Pair", "Two Pair", "Three of a Kind"}:
        return None

    visible = {
        index: card for index, card in enumerate(observation.hand) if isinstance(card, VisiblePlayingCard)
    }
    rank_counts = Counter(card.rank for card in visible.values())
    suit_counts = Counter(card.suit for card in visible.values())
    kept = {index for index, card in visible.items() if rank_counts[card.rank] >= 2}
    if suit_counts:
        suit, count = suit_counts.most_common(1)[0]
        if count >= 3 and count > len(kept):
            kept = {index for index, card in visible.items() if card.suit == suit}

    candidates = [
        index
        for index, card in sorted(visible.items(), key=lambda pair: (_card_chips(pair[1]), pair[0]))
        if index not in kept
    ]
    if not candidates:
        best_slots = {slot.value for slot in best.cards}
        candidates = [index for index in visible if index not in best_slots]
    limit = min(5, observation.selection_limit, len(candidates))
    selected = sorted(candidates[:limit])
    return DiscardCards(tuple(HandSlot(index) for index in selected)) if selected else None


def _classify(cards: tuple[VisiblePlayingCard | HiddenHandCard, ...]) -> str:
    playing = tuple(
        card for card in cards if isinstance(card, VisiblePlayingCard) and card.enhancement != "STONE"
    )
    ranks = [_RANK_ORDER.get(card.rank, 0) for card in playing]
    counts = sorted(Counter(ranks).values(), reverse=True)
    flush = len(playing) == 5 and len({card.suit for card in playing}) == 1
    unique = sorted(set(ranks))
    straight = len(unique) == 5 and (
        unique[-1] - unique[0] == 4 or unique == [2, 3, 4, 5, 14]
    )
    if counts[:1] == [5]:
        return "Flush Five" if flush else "Five of a Kind"
    if counts == [3, 2] and flush:
        return "Flush House"
    if straight and flush:
        return "Straight Flush"
    if counts[:1] == [4]:
        return "Four of a Kind"
    if counts == [3, 2]:
        return "Full House"
    if flush:
        return "Flush"
    if straight:
        return "Straight"
    if counts[:1] == [3]:
        return "Three of a Kind"
    if counts[:2] == [2, 2]:
        return "Two Pair"
    if counts[:1] == [2]:
        return "Pair"
    return "High Card"


def _scoring_cards(
    cards: tuple[VisiblePlayingCard | HiddenHandCard, ...],
    hand_name: str,
) -> tuple[VisiblePlayingCard, ...]:
    visible = tuple(card for card in cards if isinstance(card, VisiblePlayingCard))
    stones = tuple(card for card in visible if card.enhancement == "STONE")
    playing = tuple(card for card in visible if card.enhancement != "STONE")
    if hand_name == "High Card":
        if not playing:
            return stones
        highest = max(_RANK_ORDER.get(card.rank, 0) for card in playing)
        ranked = tuple(card for card in playing if _RANK_ORDER.get(card.rank, 0) == highest)
        return (*ranked, *stones)
    rank_counts = Counter(card.rank for card in playing)
    minimum = {
        "Pair": 2,
        "Three of a Kind": 3,
        "Four of a Kind": 4,
    }.get(hand_name)
    if minimum is not None:
        ranked = tuple(card for card in playing if rank_counts[card.rank] >= minimum)
        return (*ranked, *stones)
    if hand_name == "Two Pair":
        ranked = tuple(card for card in playing if rank_counts[card.rank] >= 2)
        return (*ranked, *stones)
    return (*playing, *stones)


def _hand_matches(
    cards: tuple[VisiblePlayingCard | HiddenHandCard, ...],
    hand_name: str,
    family: str,
) -> bool:
    ranks = Counter(
        card.rank
        for card in cards
        if isinstance(card, VisiblePlayingCard) and card.enhancement != "STONE"
    )
    if family == "Pair":
        return any(count >= 2 for count in ranks.values())
    if family == "Two Pair":
        return sum(count >= 2 for count in ranks.values()) >= 2 or hand_name in {
            "Full House",
            "Flush House",
        }
    if family == "Three of a Kind":
        return any(count >= 3 for count in ranks.values())
    if family == "Four of a Kind":
        return any(count >= 4 for count in ranks.values())
    if family == "Straight":
        return hand_name in {"Straight", "Straight Flush"}
    if family == "Flush":
        return hand_name in {"Flush", "Straight Flush", "Flush House", "Flush Five"}
    return hand_name == family


def _card_chips(card: VisiblePlayingCard | HiddenHandCard) -> int:
    if not isinstance(card, VisiblePlayingCard) or card.debuffed:
        return 0
    if card.enhancement == "STONE":
        return 50
    chips = _RANK_CHIPS.get(card.rank, 0)
    if card.enhancement == "BONUS":
        chips += 30
    if card.edition == "FOIL":
        chips += 50
    return chips + card.permanent_bonus


def _bounded_actions(
    actions: Iterator[PublicAction],
    limit: int = _MAX_PUBLIC_ACTIONS,
) -> list[PublicAction]:
    return [
        action
        for action in islice(actions, limit)
        if not isinstance(action, _REORDER_TYPES)
    ]


def _current_shop_action_count(history: tuple[PublicHistoryStep, ...]) -> int:
    count = 0
    for step in reversed(history):
        if step.before.phase == Phase.ROUND_EVAL and step.after.phase == Phase.SHOP:
            break
        if step.before.phase == Phase.SHOP:
            count += 1
    return count
