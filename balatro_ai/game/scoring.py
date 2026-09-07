"""Pure scoring of legal plays from the typed public observation.

This module has no authority, candidate-engine, raw-state, or policy dependency.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from balatro_ai.game.actions import HandSlot
from balatro_ai.game.boss_rules import BossRule, boss_rule
from balatro_ai.game.mechanics import joker_rarity, planet_hand
from balatro_ai.game.state import (
    HandStat,
    HiddenHandCard,
    HiddenJokerSlot,
    JokerCard,
    PublicItem,
    PublicObservation,
    VisiblePlayingCard,
)

_RANK_CHIPS = {
    "A": 11,
    "K": 10,
    "Q": 10,
    "J": 10,
    "T": 10,
    **{str(value): value for value in range(2, 10)},
}
_RANK_ORDER = {
    "A": 14,
    "K": 13,
    "Q": 12,
    "J": 11,
    "T": 10,
    **{str(value): value for value in range(2, 10)},
}
_HAND_LEVEL_GAINS = {
    "Flush Five": (50, 3),
    "Flush House": (40, 4),
    "Five of a Kind": (35, 3),
    "Straight Flush": (40, 4),
    "Four of a Kind": (30, 3),
    "Full House": (25, 2),
    "Flush": (15, 2),
    "Straight": (30, 3),
    "Three of a Kind": (20, 2),
    "Two Pair": (20, 1),
    "Pair": (15, 1),
    "High Card": (10, 1),
}
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
_THREE_HALVES = Fraction(3, 2)
_FIVE_FOURTHS = Fraction(5, 4)
_COPY_JOKERS = frozenset({"j_blueprint", "j_brainstorm"})
# Jokers whose whole main contribution is the tooltip-visible counter. Copying
# delegates to that same public runtime, never to the target's edition or
# growth mutation, so a copy without that public value has nothing to apply.
_COPY_MAIN_RUNTIME_FIELDS = {
    "j_caino": "current_x_mult",
    "j_campfire": "current_x_mult",
    "j_castle": "current_chips",
    "j_ceremonial": "current_mult",
    "j_constellation": "current_x_mult",
    "j_flash": "current_mult",
    "j_fortune_teller": "current_mult",
    "j_glass": "current_x_mult",
    "j_hit_the_road": "current_x_mult",
    "j_hologram": "current_x_mult",
    "j_ice_cream": "current_chips",
    "j_lucky_cat": "current_x_mult",
    "j_madness": "current_x_mult",
    "j_obelisk": "current_x_mult",
    "j_popcorn": "current_mult",
    "j_red_card": "current_mult",
    "j_throwback": "current_x_mult",
    "j_vampire": "current_x_mult",
    "j_yorick": "current_x_mult",
}
# Every key whose chips/Mult/xMult contribution comes from the Joker-main pass.
_MAIN_EFFECT_JOKERS = frozenset(
    {
        "j_abstract",
        "j_acrobat",
        "j_banner",
        "j_blackboard",
        "j_blue_joker",
        "j_bootstraps",
        "j_bull",
        "j_card_sharp",
        "j_cavendish",
        "j_drivers_license",
        "j_erosion",
        "j_flower_pot",
        "j_green_joker",
        "j_gros_michel",
        "j_half",
        "j_joker",
        "j_loyalty_card",
        "j_misprint",
        "j_mystic_summit",
        "j_ramen",
        "j_ride_the_bus",
        "j_runner",
        "j_seeing_double",
        "j_square",
        "j_steel_joker",
        "j_stencil",
        "j_stone",
        "j_stuntman",
        "j_supernova",
        "j_swashbuckler",
        "j_trousers",
        "j_wee",
    }
    | frozenset(_TYPE_MULT_JOKERS)
    | frozenset(_TYPE_CHIP_JOKERS)
    | frozenset(_TYPE_XMULT_JOKERS)
    | frozenset(_COPY_MAIN_RUNTIME_FIELDS)
)
_PLAYED_INDIVIDUAL_ADDITIVE_JOKERS = frozenset(
    {
        "j_fibonacci",
        "j_even_steven",
        "j_odd_todd",
        "j_scary_face",
        "j_smiley",
        "j_scholar",
        "j_walkie_talkie",
        "j_arrowhead",
        "j_onyx_agate",
    }
    | frozenset(_SUIT_MULT_JOKERS)
)
_PLAYED_INDIVIDUAL_XMULT_JOKERS = frozenset(
    {"j_photograph", "j_ancient", "j_idol", "j_triboulet", "j_bloodstone"}
)
_PLAYED_INDIVIDUAL_EFFECT_JOKERS = (
    _PLAYED_INDIVIDUAL_ADDITIVE_JOKERS | _PLAYED_INDIVIDUAL_XMULT_JOKERS
)
_PLAYED_RETRIGGER_JOKERS = frozenset(
    {"j_hack", "j_sock_and_buskin", "j_hanging_chad", "j_dusk", "j_selzer"}
)
_HELD_INDIVIDUAL_JOKERS = frozenset({"j_raised_fist", "j_shoot_the_moon", "j_baron"})
_HELD_RETRIGGER_JOKERS = frozenset({"j_mime"})
# Passive rules consumed by hand classification rather than by a scoring pass.
_PASSIVE_HAND_SHAPE_JOKERS = frozenset(
    {"j_four_fingers", "j_pareidolia", "j_shortcut", "j_smeared", "j_splash"}
)
# Passive rules applied across scoring cards or Jokers instead of at one slot.
_PASSIVE_GLOBAL_JOKERS = frozenset({"j_baseball", "j_hiker"})
# These are scored by their expectation, not by a public value. Copying them
# would compound an estimate, so Blueprint and Brainstorm decline the target.
_STOCHASTIC_ESTIMATE_JOKERS = frozenset({"j_misprint", "j_bloodstone"})

# Blueprint and Brainstorm delegate to any modeled effect in the pass where
# that effect applies. Vanilla game.lua marks every one of these targets
# blueprint_compat=true; the only modeled effects left out are the passive
# hand-shape Jokers, which vanilla itself marks blueprint_compat=false.
_COPY_MAIN_JOKERS = _MAIN_EFFECT_JOKERS - _STOCHASTIC_ESTIMATE_JOKERS
_COPY_PLAYED_INDIVIDUAL_JOKERS = _PLAYED_INDIVIDUAL_EFFECT_JOKERS - _STOCHASTIC_ESTIMATE_JOKERS
_COPY_PLAYED_RETRIGGER_JOKERS = _PLAYED_RETRIGGER_JOKERS
_COPY_HELD_INDIVIDUAL_JOKERS = _HELD_INDIVIDUAL_JOKERS
_COPY_HELD_RETRIGGER_JOKERS = _HELD_RETRIGGER_JOKERS

SCORING_RULE_JOKERS = (
    _MAIN_EFFECT_JOKERS
    | _PLAYED_INDIVIDUAL_EFFECT_JOKERS
    | _PLAYED_RETRIGGER_JOKERS
    | _HELD_INDIVIDUAL_JOKERS
    | _HELD_RETRIGGER_JOKERS
    | _PASSIVE_HAND_SHAPE_JOKERS
    | _PASSIVE_GLOBAL_JOKERS
    | _COPY_JOKERS
)
"""Every Joker key this module gives a chips, Mult or xMult rule."""

NO_SCORING_EFFECT_JOKERS = frozenset(
    {
        # Money, hand and discard economy, hand size, shop, deck edits, card
        # creation and probability rewrites. Each was checked against vanilla
        # card.lua: none of them returns chips, mult, x_mult or a *_mod, so
        # contributing nothing to a played hand is exact rather than a gap.
        "j_8_ball",
        "j_astronomer",
        "j_burglar",
        "j_burnt",
        "j_business",
        "j_cartomancer",
        "j_certificate",
        "j_chaos",
        "j_chicot",
        "j_cloud_9",
        "j_credit_card",
        "j_delayed_grat",
        "j_diet_cola",
        "j_dna",
        "j_drunkard",
        "j_egg",
        "j_faceless",
        "j_gift",
        "j_golden",
        "j_hallucination",
        "j_invisible",
        "j_juggler",
        "j_luchador",
        "j_mail",
        "j_marble",
        "j_matador",
        "j_merry_andy",
        "j_midas_mask",
        "j_mr_bones",
        "j_oops",
        "j_perkeo",
        "j_reserved_parking",
        "j_riff_raff",
        "j_ring_master",
        "j_rocket",
        "j_rough_gem",
        "j_satellite",
        "j_seance",
        "j_sixth_sense",
        "j_space",
        "j_superposition",
        "j_ticket",
        "j_to_the_moon",
        "j_todo_list",
        "j_trading",
        "j_troubadour",
        "j_turtle_bean",
        "j_vagabond",
    }
)
"""Joker keys that never touch chips, Mult or xMult during a played hand."""


@dataclass(frozen=True, slots=True)
class _PreparedScoreContext:
    observation: PublicObservation
    current_boss: BossRule | None
    active_keys: frozenset[str]
    baseball_count: int
    hiker_count: int
    played_individual_jokers: tuple[PublicItem, ...]
    played_retrigger_jokers: tuple[PublicItem, ...]
    held_individual_jokers: tuple[PublicItem, ...]
    held_retrigger_jokers: tuple[PublicItem, ...]
    main_jokers: tuple[PublicItem | None, ...]
    splash: bool
    misprint_value: int | None = None


def _prepare_score_context(observation: PublicObservation) -> _PreparedScoreContext:
    if any(isinstance(joker, HiddenJokerSlot) for joker in observation.jokers):
        raise ValueError("exact scoring is unavailable for face-down Jokers")
    active_jokers = tuple(
        joker
        for joker in observation.jokers
        if isinstance(joker, PublicItem) and not joker.debuffed
    )
    return _PreparedScoreContext(
        observation=observation,
        current_boss=_current_boss_rule(observation),
        active_keys=frozenset(joker.key for joker in active_jokers),
        baseball_count=sum(joker.key == "j_baseball" for joker in active_jokers),
        hiker_count=sum(joker.key == "j_hiker" for joker in active_jokers),
        played_individual_jokers=_effective_jokers_for_pass(
            observation.jokers,
            _COPY_PLAYED_INDIVIDUAL_JOKERS,
            _PLAYED_INDIVIDUAL_EFFECT_JOKERS,
        ),
        played_retrigger_jokers=_effective_jokers_for_pass(
            observation.jokers,
            _COPY_PLAYED_RETRIGGER_JOKERS,
        ),
        held_individual_jokers=_effective_jokers_for_pass(
            observation.jokers,
            _COPY_HELD_INDIVIDUAL_JOKERS,
        ),
        held_retrigger_jokers=_effective_jokers_for_pass(
            observation.jokers,
            _COPY_HELD_RETRIGGER_JOKERS,
        ),
        main_jokers=tuple(
            _effective_joker_for_pass(observation.jokers, index, _COPY_MAIN_JOKERS)
            for index in range(len(observation.jokers))
        ),
        splash=any(joker.key == "j_splash" for joker in active_jokers),
    )


def score_play(
    observation: PublicObservation,
    selected: tuple[HandSlot, ...],
    stats: Mapping[str, HandStat] | None = None,
) -> tuple[int | Fraction, str]:
    if any(isinstance(joker, HiddenJokerSlot) for joker in observation.jokers):
        raise ValueError("exact scoring is unavailable for face-down Jokers")
    return _score_play_prepared(
        observation,
        selected,
        stats,
        _prepare_score_context(observation),
    )


def _score_play_prepared(
    observation: PublicObservation,
    selected: tuple[HandSlot, ...],
    stats: Mapping[str, HandStat] | None,
    context: _PreparedScoreContext,
) -> tuple[int | Fraction, str]:
    if context.observation is not observation:
        raise ValueError("prepared score context belongs to a different observation")
    stats = stats if stats is not None else {hand.name: hand for hand in observation.hand_stats}
    cards = tuple(observation.hand[slot.value] for slot in selected)
    hand_name = _classify(cards, context.active_keys)
    stat = stats.get(hand_name)
    current_boss = context.current_boss
    if current_boss is not None:
        if (
            current_boss.min_selected_cards is not None
            and len(selected) < current_boss.min_selected_cards
        ):
            return 0, hand_name
        if current_boss.repeat_hand_restriction and stat is not None and stat.played_this_round > 0:
            return 0, hand_name
        if current_boss.single_hand_family and any(
            hand.played_this_round > 0 and hand.name != hand_name for hand in stats.values()
        ):
            return 0, hand_name
    scoring_cards = (
        tuple(card for card in cards if isinstance(card, VisiblePlayingCard))
        if context.splash
        else _scoring_cards(cards, hand_name)
    )
    base_chips = stat.chips if stat is not None else 0
    base_mult = stat.mult if stat is not None else 1
    if (
        current_boss is not None
        and current_boss.level_reduction > 0
        and stat is not None
        and stat.level > 1
    ):
        level_loss = min(current_boss.level_reduction, stat.level - 1)
        chip_gain, mult_gain = _HAND_LEVEL_GAINS[hand_name]
        base_chips = max(0, base_chips - chip_gain * level_loss)
        base_mult = max(1, base_mult - mult_gain * level_loss)
    if current_boss is not None and current_boss.score_reduction:
        # The Flint modifies only the poker-hand base before cards and Jokers
        # score: floor(x / 2 + 0.5), with a one-Mult floor.
        base_chips = (base_chips + 1) // 2
        base_mult = max(1, (base_mult + 1) // 2)
    chips = base_chips
    mult: int | Fraction = base_mult
    first_face_index = next(
        (index for index, card in enumerate(scoring_cards) if _is_face(card, context.active_keys)),
        None,
    )
    for index, card in enumerate(scoring_cards):
        repeats = _card_repetitions(
            observation,
            card,
            index,
            context.played_retrigger_jokers,
            context.active_keys,
        )
        hiker_bonus = 0
        for _ in range(1 + repeats):
            chips += _card_chips(card) + hiker_bonus
            if card.enhancement == "MULT" and not card.debuffed:
                mult += 4
            if card.enhancement == "GLASS" and not card.debuffed:
                mult *= 2
            if card.edition in {"HOLO", "HOLOGRAPHIC"} and not card.debuffed:
                mult += 10
            if card.edition == "POLYCHROME" and not card.debuffed:
                mult *= _THREE_HALVES
            for joker in context.played_individual_jokers:
                if joker.key in _PLAYED_INDIVIDUAL_ADDITIVE_JOKERS:
                    repeat_chips, repeat_mult = _card_joker_effect(
                        joker.key,
                        (card,),
                        context.active_keys,
                    )
                    if repeat_chips:
                        chips += repeat_chips
                    if repeat_mult:
                        mult += repeat_mult
                if joker.key in _PLAYED_INDIVIDUAL_XMULT_JOKERS:
                    repeat_xmult = _individual_joker_card_xmult(
                        observation,
                        card,
                        joker,
                        first_face=index == first_face_index,
                    )
                    if repeat_xmult != 1:
                        mult *= repeat_xmult
            hiker_bonus += 5 * context.hiker_count
    selected_slots = {slot.value for slot in selected}
    held = tuple(card for index, card in enumerate(observation.hand) if index not in selected_slots)
    visible_held = tuple(card for card in held if isinstance(card, VisiblePlayingCard))
    held_known = len(visible_held) == len(held)
    lowest_held_index: int | None = None
    if held_known:
        for index, card in enumerate(visible_held):
            if card.enhancement == "STONE":
                continue
            if lowest_held_index is None or _RANK_ORDER.get(card.rank, 0) <= _RANK_ORDER.get(
                visible_held[lowest_held_index].rank,
                0,
            ):
                # Vanilla's <= scan makes the last card win rank ties.
                lowest_held_index = index
    for index, card in enumerate(visible_held):
        if card.debuffed:
            continue
        held_repeats = (
            1
            + int(card.seal == "RED")
            + sum(joker.key == "j_mime" for joker in context.held_retrigger_jokers)
        )
        for _ in range(held_repeats):
            if card.enhancement == "STEEL":
                mult *= _THREE_HALVES
            for joker in context.held_individual_jokers:
                if joker.key == "j_raised_fist" and index == lowest_held_index:
                    mult += 2 * _RANK_CHIPS.get(card.rank, 0)
                elif joker.key == "j_shoot_the_moon" and card.rank == "Q":
                    mult += 13
                elif joker.key == "j_baron" and card.rank == "K":
                    mult *= _THREE_HALVES

    for source_joker, joker in zip(observation.jokers, context.main_jokers, strict=True):
        if joker is None:
            continue
        # Joker edition chips/Mult score before its main effect. Polychrome
        # scores after it, matching the left-to-right Joker pipeline.
        if isinstance(source_joker, HiddenJokerSlot):
            continue
        if source_joker.edition == "FOIL":
            chips += 50
        elif source_joker.edition in {"HOLO", "HOLOGRAPHIC"}:
            mult += 10
        joker_chips, joker_mult, joker_xmult = _joker_main_effect(
            observation,
            selected,
            cards,
            hand_name,
            stats,
            joker,
            misprint_value=context.misprint_value,
        )
        chips += joker_chips
        mult += joker_mult
        mult *= joker_xmult
        if context.baseball_count:
            try:
                source_rarity = joker_rarity(source_joker.key)
            except (TypeError, ValueError):
                source_rarity = 0
            if source_rarity == 2:
                mult *= _THREE_HALVES**context.baseball_count
        if source_joker.edition == "POLYCHROME":
            mult *= _THREE_HALVES
    if "v_observatory" in observation.used_vouchers:
        for consumable in observation.consumables:
            if (
                not consumable.debuffed
                and consumable.kind.upper() == "PLANET"
                and planet_hand(consumable.key) == hand_name
            ):
                mult *= _THREE_HALVES
    return chips * mult, hand_name


def _effective_joker_for_pass(
    jokers: tuple[JokerCard, ...],
    index: int,
    copyable_keys: frozenset[str],
) -> PublicItem | None:
    """Resolve a copied scoring effect using only ordered public slots.

    Normal Jokers keep their existing scorer behavior. Blueprint and Brainstorm
    may delegate only to the conservative per-pass whitelist; unknown,
    stochastic, mutation, passive-rule, debuffed, and cyclic targets no-op.
    """

    if index < 0 or index >= len(jokers):
        return None
    source = jokers[index]
    if isinstance(source, HiddenJokerSlot):
        return None
    if source.debuffed:
        return None
    if source.key not in _COPY_JOKERS:
        return source

    current = index
    visited: set[int] = set()
    for _ in range(len(jokers) + 2):
        if current in visited:
            return None
        visited.add(current)
        joker = jokers[current]
        if isinstance(joker, HiddenJokerSlot):
            return None
        if joker.debuffed:
            return None
        if joker.key not in _COPY_JOKERS:
            if joker.key not in copyable_keys:
                return None
            runtime_field = _COPY_MAIN_RUNTIME_FIELDS.get(joker.key)
            if runtime_field is not None and (
                joker.runtime is None or getattr(joker.runtime, runtime_field) is None
            ):
                return None
            if joker.key == "j_green_joker" and (
                joker.runtime is None or joker.runtime.current_mult is None
            ):
                return None
            if joker.key == "j_selzer" and (
                joker.runtime is None or joker.runtime.remaining_hands is None
            ):
                return None
            return joker
        target = current + 1 if joker.key == "j_blueprint" else 0
        if target < 0 or target >= len(jokers):
            return None
        current = target
    return None


def _effective_jokers_for_pass(
    jokers: tuple[JokerCard, ...],
    copyable_keys: frozenset[str],
    effect_keys: frozenset[str] | None = None,
) -> tuple[PublicItem, ...]:
    admitted_keys = copyable_keys if effect_keys is None else effect_keys
    return tuple(
        effective
        for index in range(len(jokers))
        if (effective := _effective_joker_for_pass(jokers, index, copyable_keys)) is not None
        and effective.key in admitted_keys
    )


def _card_joker_effect(
    key: str,
    cards: tuple[VisiblePlayingCard, ...],
    active_keys: frozenset[str] = frozenset(),
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
        elif key == "j_scary_face" and _is_face(card, active_keys):
            chips += 30
        elif key == "j_smiley" and _is_face(card, active_keys):
            mult += 5
        elif key == "j_scholar" and card.rank == "A":
            chips += 20
            mult += 4
        elif key == "j_walkie_talkie" and card.rank in {"4", "T"}:
            chips += 10
            mult += 4
        elif key == "j_arrowhead" and card.suit == "S":
            chips += 50
        elif key == "j_onyx_agate" and card.suit == "C":
            mult += 7
    return chips, mult


def _is_face(card: VisiblePlayingCard, active_keys: frozenset[str]) -> bool:
    return card.rank in _FACE_RANKS or "j_pareidolia" in active_keys


def _individual_joker_card_xmult(
    observation: PublicObservation,
    card: VisiblePlayingCard,
    joker: PublicItem,
    *,
    first_face: bool,
) -> int | Fraction:
    if card.debuffed:
        return 1
    joker_key = joker.key
    multiplier: int | Fraction = 1
    if joker_key == "j_photograph" and first_face:
        multiplier *= 2
    if joker_key == "j_ancient" and observation.round.ancient_suit == card.suit:
        multiplier *= _THREE_HALVES
    if joker_key == "j_idol" and _idol_target(joker) == (card.rank, card.suit):
        # The tooltip names one rank and suit; a card matching both gives X2.
        multiplier *= 2
    if joker_key == "j_triboulet" and card.rank in {"K", "Q"}:
        multiplier *= 2
    if joker_key == "j_bloodstone" and card.suit == "H":
        # The heuristic scores the public 1-in-2 trigger by its expectation.
        multiplier *= _FIVE_FOURTHS
    return multiplier


def _idol_target(joker: PublicItem) -> tuple[str, str] | None:
    """Return The Idol's public rank/suit target, or None when it is missing."""

    runtime = joker.runtime
    if runtime is None or runtime.target_rank is None or runtime.target_suit is None:
        return None
    return runtime.target_rank, runtime.target_suit


def _card_repetitions(
    observation: PublicObservation,
    card: VisiblePlayingCard,
    index: int,
    effective_jokers: tuple[PublicItem, ...],
    active_keys: frozenset[str],
) -> int:
    if card.debuffed:
        return 0
    repeats = int(card.seal == "RED")
    for joker in effective_jokers:
        if joker.key == "j_hack" and card.rank in {"2", "3", "4", "5"}:
            repeats += 1
        elif joker.key == "j_sock_and_buskin" and _is_face(card, active_keys):
            repeats += 1
        elif joker.key == "j_hanging_chad" and index == 0:
            repeats += 2
        elif joker.key == "j_dusk" and observation.round.hands_left == 1:
            repeats += 1
        elif (
            joker.key == "j_selzer"
            and joker.runtime is not None
            and (joker.runtime.remaining_hands or 0) > 0
        ):
            repeats += 1
    return repeats


def _joker_main_effect(
    observation: PublicObservation,
    selected: tuple[HandSlot, ...],
    cards: tuple[VisiblePlayingCard | HiddenHandCard, ...],
    hand_name: str,
    stats: Mapping[str, HandStat],
    joker: PublicItem,
    *,
    misprint_value: int | None = None,
) -> tuple[int, int | Fraction, int | Fraction]:
    key = joker.key
    runtime = joker.runtime
    chips = 0
    mult: int | Fraction = 0
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
    if runtime is not None and runtime.current_mult is not None:
        runtime_mult = runtime.current_mult
        if key == "j_green_joker":
            runtime_mult += 1
        elif key == "j_ride_the_bus":
            scoring = _scoring_cards(cards, hand_name)
            runtime_mult = (
                0
                if any(not card.debuffed and card.rank in _FACE_RANKS for card in scoring)
                else runtime_mult + 1
            )
        elif key == "j_trousers" and hand_name in {
            "Two Pair",
            "Full House",
            "Flush House",
        }:
            runtime_mult += 2
        mult += runtime_mult
    elif key == "j_green_joker":
        # Fresh Green Joker has no serialized counter until its first hand.
        # Vanilla initializes it from zero and applies the before-play +1
        # before the Joker-main scoring pass.
        mult += 1
    elif key == "j_ride_the_bus":
        # Fresh Ride the Bus follows the same source-defined zero initial
        # state. Its first non-face scoring hand becomes +1 immediately.
        scoring = _scoring_cards(cards, hand_name)
        if not any(not card.debuffed and card.rank in _FACE_RANKS for card in scoring):
            mult += 1
    if runtime is not None and runtime.current_chips is not None:
        runtime_chips = runtime.current_chips
        if key == "j_runner" and _hand_matches(cards, hand_name, "Straight"):
            runtime_chips += 15
        elif key == "j_square" and len(cards) == 4:
            runtime_chips += 4
        elif key == "j_wee":
            runtime_chips += 8 * sum(
                card.rank == "2" and not card.debuffed for card in _scoring_cards(cards, hand_name)
            )
        chips += runtime_chips
    if runtime is not None and runtime.current_x_mult is not None:
        # Public JSON floats expose binary artifacts (for example Ramen at
        # 1.7999999999999998). Vanilla xMult counters advance on small rational
        # steps, so recover that displayed value before flooring the score.
        xmult *= Fraction(runtime.current_x_mult).limit_denominator(1000)
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
    elif key == "j_ramen" and (runtime is None or runtime.current_x_mult is None):
        xmult *= 2
    elif key == "j_card_sharp":
        stat = stats.get(hand_name)
        if stat is not None and stat.played_this_round >= 1:
            xmult *= 3
    elif key == "j_bootstraps":
        mult += 2 * (max(0, observation.money) // 5)
    elif key == "j_misprint":
        mult += Fraction(23, 2) if misprint_value is None else misprint_value
    elif key == "j_erosion":
        starting_size = 40 if observation.deck.upper() == "ABANDONED" else 52
        chips += 4 * max(0, starting_size - observation.deck_size)
    elif key == "j_steel_joker":
        # Vanilla steel_tally counts Steel cards across the whole deck, not the
        # hand, and applies X(1 + 0.2 * tally).
        steel = _full_deck_enhancement_count(observation, "STEEL")
        if steel:
            xmult *= 1 + Fraction(steel, 5)
    elif key == "j_stone":
        # Vanilla stone_tally is the same full-deck scan, worth +25 Chips each.
        chips += 25 * _full_deck_enhancement_count(observation, "STONE")
    elif key == "j_stencil" and runtime is None:
        stencil_count = sum(
            item.key == "j_stencil" and not item.debuffed
            for item in observation.jokers
            if isinstance(item, PublicItem)
        )
        xmult *= max(1, observation.joker_limit - len(observation.jokers) + stencil_count)
    elif key == "j_swashbuckler" and runtime is None:
        mult += sum(
            item.sell_cost or 0
            for item in observation.jokers
            if isinstance(item, PublicItem) and item is not joker and not item.debuffed
        )
    elif key == "j_runner" and runtime is None and _hand_matches(cards, hand_name, "Straight"):
        chips += 15
    elif key == "j_square" and runtime is None and len(cards) == 4:
        chips += 4
    elif (
        key == "j_trousers"
        and runtime is None
        and hand_name in {"Two Pair", "Full House", "Flush House"}
    ):
        mult += 2
    elif key == "j_blackboard":
        selected_indexes = {slot.value for slot in selected}
        held = tuple(
            card for index, card in enumerate(observation.hand) if index not in selected_indexes
        )
        if all(isinstance(card, VisiblePlayingCard) and card.suit in {"C", "S"} for card in held):
            xmult *= 3
    elif key == "j_flower_pot":
        scoring = _scoring_cards(cards, hand_name)
        suits = {card.suit for card in scoring if card.enhancement != "WILD"}
        live_wilds = sum(card.enhancement == "WILD" and not card.debuffed for card in scoring)
        if len(suits) + live_wilds >= 4:
            xmult *= 3
    elif key == "j_seeing_double":
        suits = {card.suit for card in _scoring_cards(cards, hand_name) if not card.debuffed}
        if "C" in suits and bool(suits - {"C"}):
            xmult *= 2
    elif key == "j_drivers_license" and runtime is not None and (runtime.driver_tally or 0) >= 16:
        xmult *= 3
    elif key == "j_loyalty_card" and runtime is not None and runtime.loyalty_remaining == 0:
        xmult *= 4
    return chips, mult, xmult


def _full_deck_enhancement_count(observation: PublicObservation, enhancement: str) -> int:
    """Count one enhancement across the public full-deck composition."""

    return sum(
        entry.count for entry in observation.full_deck if entry.card.enhancement == enhancement
    )


def unmodelled_scoring_jokers(observation: PublicObservation) -> tuple[PublicItem, ...]:
    """Return active Jokers this scorer neither models nor knows to be inert.

    ``SCORING_RULE_JOKERS`` and ``NO_SCORING_EFFECT_JOKERS`` partition every
    vanilla key, so this is normally empty. It stays as the surface that makes
    a future gap visible: an unknown or modded key, and a modeled Joker whose
    required public target is absent, are reported instead of scored silently.
    """

    classified = SCORING_RULE_JOKERS | NO_SCORING_EFFECT_JOKERS
    return tuple(
        joker
        for joker in observation.jokers
        if isinstance(joker, PublicItem)
        and not joker.debuffed
        and (joker.key not in classified or (joker.key == "j_idol" and _idol_target(joker) is None))
    )


def _current_boss_rule(observation: PublicObservation) -> BossRule | None:
    current = next(
        (blind for blind in observation.blinds if blind.status == "CURRENT"),
        None,
    )
    if current is None or current.kind != "BOSS" or current.disabled:
        return None
    rule = boss_rule(current.name)
    if rule is None:
        raise RuntimeError(f"unknown current boss blind {current.name!r}")
    return rule


def _classify(
    cards: tuple[VisiblePlayingCard | HiddenHandCard, ...],
    joker_keys: frozenset[str] = frozenset(),
) -> str:
    playing = tuple(
        card
        for card in cards
        if isinstance(card, VisiblePlayingCard) and card.enhancement != "STONE"
    )
    ranks = [_RANK_ORDER.get(card.rank, 0) for card in playing]
    counts = sorted(Counter(ranks).values(), reverse=True)
    required = 4 if "j_four_fingers" in joker_keys else 5
    flush = _has_flush(playing, required, joker_keys)
    straight = _has_straight(
        ranks,
        required,
        shortcut="j_shortcut" in joker_keys,
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


def _has_flush(
    cards: tuple[VisiblePlayingCard, ...],
    required: int,
    joker_keys: frozenset[str],
) -> bool:
    if len(cards) < required:
        return False
    smeared = "j_smeared" in joker_keys
    for suit in ("H", "D", "S", "C"):
        matches = sum(
            card.enhancement == "WILD"
            or card.suit == suit
            or (smeared and {card.suit, suit}.issubset({"H", "D"}))
            or (smeared and {card.suit, suit}.issubset({"S", "C"}))
            for card in cards
        )
        if matches >= required:
            return True
    return False


def _has_straight(
    ranks: list[int],
    required: int,
    *,
    shortcut: bool,
) -> bool:
    unique = set(ranks)
    if 14 in unique:
        unique.add(1)
    ordered = sorted(unique)
    for start in range(len(ordered)):
        length = 1
        previous = ordered[start]
        for rank in ordered[start + 1 :]:
            gap = rank - previous
            if gap <= (2 if shortcut else 1):
                length += 1
                previous = rank
                if length >= required:
                    return True
            elif gap > (2 if shortcut else 1):
                break
        if length >= required:
            return True
    return False


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
