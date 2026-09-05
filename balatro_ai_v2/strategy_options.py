"""Public strategy intents and revalidated first-action options.

An option is deliberately not a macro action.  It carries a persistent intent
while exposing exactly one action from the ordinary public legal-action set;
the intent must be re-evaluated after every observed transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from balatro_ai_v2.actions import (
    BuyPack,
    BuyShopCard,
    BuyVoucher,
    CashOut,
    ChoosePackCard,
    DiscardCards,
    LeaveShop,
    PlayCards,
    PublicAction,
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    RerollBoss,
    RerollShop,
    SelectBlind,
    SellConsumable,
    SellJoker,
    SkipBlind,
    SkipPack,
    UseConsumable,
    iter_legal_actions,
)
from balatro_ai_v2.consumable_rules import public_consumable_rule
from balatro_ai_v2.joker_catalog import JOKER_CATALOG
from balatro_ai_v2.public_state import (
    HiddenJokerSlot,
    PublicItem,
    PublicObservation,
    PublicShopPlayingCard,
    VisiblePlayingCard,
)
from balatro_ai_v2.strategy_engine import (
    KNOWN_VOUCHERS,
    PublicEngineState,
    RunGoal,
    derive_engine_state,
)


class StrategyIntent(str, Enum):
    STABILIZE = "stabilize"
    ECONOMY = "economy"
    RELIABLE_HAND = "reliable_hand"
    DECK_SCULPT = "deck_sculpt"
    HELD_RETRIGGER_ENGINE = "held_retrigger_engine"
    PLAYED_RETRIGGER_ENGINE = "played_retrigger_engine"
    CONSUMABLE_GENERATION = "consumable_generation"
    BOSS_PREPARATION = "boss_preparation"
    ENDLESS_GROWTH = "endless_growth"


@dataclass(frozen=True, slots=True)
class StrategicOption:
    intent: StrategyIntent
    first_action: PublicAction
    evidence: tuple[str, ...]

    def is_legal(self, observation: PublicObservation) -> bool:
        return self.first_action in set(iter_legal_actions(observation))


@dataclass(frozen=True, slots=True)
class PersistentIntent:
    """Public continuation context; it contains no simulated or hidden state."""

    intent: StrategyIntent
    goal: RunGoal
    started_ante: int
    decisions: int
    evidence: tuple[str, ...]

    @classmethod
    def start(
        cls,
        option: StrategicOption,
        engine: PublicEngineState,
    ) -> PersistentIntent:
        return cls(option.intent, engine.goal, engine.ante, 1, option.evidence)

    def advance(
        self,
        option: StrategicOption,
        engine: PublicEngineState,
    ) -> PersistentIntent:
        if option.intent == self.intent and engine.goal == self.goal:
            return PersistentIntent(
                intent=self.intent,
                goal=self.goal,
                started_ante=self.started_ante,
                decisions=self.decisions + 1,
                evidence=option.evidence,
            )
        return PersistentIntent.start(option, engine)


_REORDER_ACTIONS = (ReorderHand, ReorderJokers, ReorderConsumables)


@dataclass(frozen=True, slots=True)
class StrategyCandidateRoot:
    """Canonical public identity shared by search, teachers, and shadows."""

    action: PublicAction
    intent: StrategyIntent | None
    option: StrategicOption | None = None

    def __post_init__(self) -> None:
        if self.option is not None and (
            self.option.first_action != self.action or self.option.intent != self.intent
        ):
            raise ValueError("strategy candidate disagrees with its option")

    @property
    def identity(self) -> tuple[PublicAction, StrategyIntent | None]:
        return self.action, self.intent


def build_strategy_candidates(
    observation: PublicObservation,
    legal_actions: tuple[PublicAction, ...],
    control_action: PublicAction,
    *,
    active_intent: PersistentIntent | None = None,
    include_reorders: bool = False,
    intent_aware: bool = True,
    engine: PublicEngineState | None = None,
) -> tuple[StrategyCandidateRoot, ...]:
    """Build one ordered action/intent space for every strategy consumer."""

    legal_set = set(legal_actions)
    if control_action not in legal_set:
        raise ValueError("control action is absent from the supplied legal actions")
    all_options = iter_strategy_options(
        observation,
        engine,
        legal_actions=legal_actions,
    )
    options = tuple(
        option
        for option in all_options
        if include_reorders or not isinstance(option.first_action, _REORDER_ACTIONS)
    )
    if any(option.first_action not in legal_set for option in options):
        raise ValueError("strategy option action is absent from supplied legal actions")
    baseline_option = next(
        (
            option
            for option in all_options
            if intent_aware
            and active_intent is not None
            and option.first_action == control_action
            and option.intent == active_intent.intent
        ),
        None,
    )
    baseline = StrategyCandidateRoot(
        control_action,
        baseline_option.intent if baseline_option is not None else None,
        baseline_option,
    )
    roots = [baseline]
    seen = {baseline.identity}
    for option in options:
        root = StrategyCandidateRoot(
            option.first_action,
            option.intent if intent_aware else None,
            option if intent_aware else None,
        )
        if root.identity not in seen:
            seen.add(root.identity)
            roots.append(root)
    return tuple(roots)


_ECONOMY_CONSUMABLES = frozenset({"c_hermit", "c_temperance"})
_GENERATOR_CONSUMABLES = frozenset({"c_high_priestess", "c_emperor", "c_fool"})
_HELD_ENGINE_KEYS = frozenset(
    {
        "j_baron",
        "j_blackboard",
        "j_mime",
        "j_raised_fist",
        "j_reserved_parking",
        "c_chariot",
        "c_deja_vu",
        "c_cryptid",
    }
)
_PLAYED_ENGINE_KEYS = frozenset(
    {
        "j_bloodstone",
        "j_dusk",
        "j_hack",
        "j_idol",
        "j_selzer",
        "j_sock_and_buskin",
        "j_triboulet",
        "c_deja_vu",
        "c_justice",
        "c_magician",
    }
)
_BOSS_PREP_KEYS = frozenset({"j_luchador", "v_directors_cut", "v_retcon"})
_COPY_KEYS = frozenset({"j_blueprint", "j_brainstorm"})
_ECONOMY_VOUCHERS = frozenset(
    {
        "v_clearance_sale",
        "v_liquidation",
        "v_money_tree",
        "v_overstock_norm",
        "v_overstock_plus",
        "v_reroll_glut",
        "v_reroll_surplus",
        "v_seed_money",
    }
)
_RELIABILITY_VOUCHERS = frozenset(
    {
        "v_antimatter",
        "v_grabber",
        "v_nacho_tong",
        "v_paint_brush",
        "v_palette",
        "v_recyclomancy",
        "v_wasteful",
    }
)
_CONSUMABLE_VOUCHERS = frozenset(
    {
        "v_crystal_ball",
        "v_observatory",
        "v_omen_globe",
        "v_planet_merchant",
        "v_planet_tycoon",
        "v_tarot_merchant",
        "v_tarot_tycoon",
        "v_telescope",
    }
)
_SCULPT_VOUCHERS = frozenset({"v_illusion", "v_magic_trick"})
_ARCANA_PACKS = frozenset({"p_arcana_normal", "p_arcana_jumbo", "p_arcana_mega"})
_CELESTIAL_PACKS = frozenset(
    {"p_celestial_normal", "p_celestial_jumbo", "p_celestial_mega"}
)
_SPECTRAL_PACKS = frozenset(
    {"p_spectral_normal", "p_spectral_jumbo", "p_spectral_mega"}
)
_STANDARD_PACKS = frozenset(
    {"p_standard_normal", "p_standard_jumbo", "p_standard_mega"}
)
_BUFFOON_PACKS = frozenset({"p_buffoon_normal", "p_buffoon_jumbo", "p_buffoon_mega"})


def iter_strategy_options(
    observation: PublicObservation,
    engine: PublicEngineState | None = None,
    *,
    legal_actions: tuple[PublicAction, ...] | None = None,
) -> tuple[StrategicOption, ...]:
    """Return intent-tagged, legal first actions using public mechanics only.

    Unsupported item keys receive no speculative intent.  Progress actions
    remain available under ``STABILIZE`` so an option consumer can always make
    forward progress in ordinary phases.
    """

    public_engine = engine or derive_engine_state(observation)
    captured_actions = (
        tuple(iter_legal_actions(observation))
        if legal_actions is None
        else legal_actions
    )
    options: list[StrategicOption] = []
    seen: set[tuple[StrategyIntent, PublicAction]] = set()
    for action in captured_actions:
        for intent, evidence in _classify_action(observation, public_engine, action):
            key = (intent, action)
            if key not in seen:
                seen.add(key)
                options.append(StrategicOption(intent, action, evidence))
    return tuple(options)


def options_for_intent(
    observation: PublicObservation,
    intent: StrategyIntent,
    engine: PublicEngineState | None = None,
) -> tuple[StrategicOption, ...]:
    """Revalidate a persistent intent against the newly observed state."""

    return tuple(
        option
        for option in iter_strategy_options(observation, engine)
        if option.intent == intent
    )


def _classify_action(
    observation: PublicObservation,
    engine: PublicEngineState,
    action: PublicAction,
) -> tuple[tuple[StrategyIntent, tuple[str, ...]], ...]:
    classified: list[tuple[StrategyIntent, tuple[str, ...]]] = []

    if isinstance(action, (SelectBlind, CashOut, LeaveShop, SkipPack)):
        classified.append((StrategyIntent.STABILIZE, ("advance_public_phase",)))
    elif isinstance(action, SkipBlind):
        classified.extend(_classify_skip(observation))
    elif isinstance(action, RerollShop):
        classified.append((StrategyIntent.STABILIZE, ("search_visible_shop",)))
    elif isinstance(action, RerollBoss):
        classified.append(
            (StrategyIntent.BOSS_PREPARATION, ("reroll_visible_boss",))
        )
    elif isinstance(action, (PlayCards, DiscardCards)):
        classified.extend(_classify_hand_action(observation, engine, action))
    elif isinstance(action, BuyShopCard):
        offer = observation.shop[action.card.value]
        if isinstance(offer, PublicShopPlayingCard):
            classified.append(
                (StrategyIntent.DECK_SCULPT, ("buy_shop_playing_card",))
            )
            classified.extend(_held_card_intents((offer.card,), engine))
            classified.extend(_played_card_intents((offer.card,)))
        else:
            classified.extend(_classify_item(offer, engine, "buy_shop_item"))
    elif isinstance(action, BuyVoucher):
        classified.extend(
            _classify_item(observation.vouchers[action.voucher.value], engine, "buy_voucher")
        )
    elif isinstance(action, BuyPack):
        pack = observation.packs[action.pack.value]
        classified.extend(_classify_pack(pack, engine))
    elif isinstance(action, ChoosePackCard):
        offer = observation.opened_pack[action.card.value]
        if isinstance(offer, VisiblePlayingCard):
            classified.append((StrategyIntent.DECK_SCULPT, ("add_visible_playing_card",)))
            classified.extend(_held_card_intents((offer,), engine))
            classified.extend(_played_card_intents((offer,)))
        else:
            classified.extend(_classify_item(offer, engine, "choose_pack_item"))
    elif isinstance(action, UseConsumable):
        item = observation.consumables[action.consumable.value]
        classified.extend(_classify_consumable(item, engine, "use_consumable"))
    elif isinstance(action, SellJoker):
        joker = observation.jokers[action.joker.value]
        if isinstance(joker, HiddenJokerSlot):
            raise ValueError("cannot classify a hidden Joker sale")
        if joker.key == "j_luchador":
            classified.append((StrategyIntent.BOSS_PREPARATION, ("disable_current_boss",)))
        classified.append((StrategyIntent.ECONOMY, ("realize_public_sell_value",)))
    elif isinstance(action, SellConsumable):
        classified.append(
            (StrategyIntent.ECONOMY, ("realize_public_sell_value", "free_consumable_slot"))
        )
        classified.append(
            (StrategyIntent.CONSUMABLE_GENERATION, ("free_consumable_slot",))
        )
    elif isinstance(action, ReorderJokers):
        classified.extend(_classify_joker_reorder(engine))
    elif isinstance(action, ReorderHand):
        reordered = tuple(observation.hand[slot.value] for slot in action.order)
        visible = tuple(card for card in reordered if isinstance(card, VisiblePlayingCard))
        classified.extend(_held_card_intents(visible, engine))
        classified.extend(_played_card_intents(visible))
    elif isinstance(action, ReorderConsumables):
        if any(key in engine.consumables.keys for key in {"c_fool", "c_cryptid"}):
            classified.append(
                (StrategyIntent.CONSUMABLE_GENERATION, ("consumable_order_matters",))
            )

    if engine.goal == RunGoal.ENDLESS and _supports_endless(observation, action):
        classified.append((StrategyIntent.ENDLESS_GROWTH, ("public_win_already_recorded",)))
    return tuple(classified)


def _classify_hand_action(
    observation: PublicObservation,
    engine: PublicEngineState,
    action: PlayCards | DiscardCards,
) -> list[tuple[StrategyIntent, tuple[str, ...]]]:
    selected_slots = {slot.value for slot in action.cards}
    selected = tuple(observation.hand[slot] for slot in selected_slots)
    visible = tuple(card for card in selected if isinstance(card, VisiblePlayingCard))
    held = tuple(
        card
        for slot, card in enumerate(observation.hand)
        if slot not in selected_slots and isinstance(card, VisiblePlayingCard)
    )
    result: list[tuple[StrategyIntent, tuple[str, ...]]] = [
        (StrategyIntent.STABILIZE, ("score_or_improve_public_hand",)),
        (
            StrategyIntent.RELIABLE_HAND,
            (f"primary_hand:{engine.hand_development.primary_hand}",),
        ),
    ]
    result.extend(_played_card_intents(visible))
    result.extend(_held_card_intents(held, engine))
    if isinstance(action, DiscardCards):
        result.append((StrategyIntent.DECK_SCULPT, ("discard_visible_cards",)))
    return result


def _classify_item(
    item: PublicItem,
    engine: PublicEngineState,
    source: str,
) -> list[tuple[StrategyIntent, tuple[str, ...]]]:
    kind = item.kind.upper()
    if kind in {"TAROT", "PLANET", "SPECTRAL"}:
        return _classify_consumable(item, engine, source)
    if kind == "VOUCHER":
        return _classify_voucher(item, source)
    profile = JOKER_CATALOG.get(item.key) if kind == "JOKER" else None
    result: list[tuple[StrategyIntent, tuple[str, ...]]] = []
    if profile is not None:
        evidence = (source, f"joker_role:{profile.role}")
        if profile.role == "economy":
            result.append((StrategyIntent.ECONOMY, evidence))
        if profile.tags.intersection(
            {"pair", "two_pair", "three_of_a_kind", "four_of_a_kind", "straight", "flush"}
        ):
            result.append((StrategyIntent.RELIABLE_HAND, evidence))
        if item.key in _HELD_ENGINE_KEYS or "held_cards" in profile.tags:
            result.append((StrategyIntent.HELD_RETRIGGER_ENGINE, evidence))
        if item.key in _PLAYED_ENGINE_KEYS or (
            profile.role == "retrigger" and "held_cards" not in profile.tags
        ):
            result.append((StrategyIntent.PLAYED_RETRIGGER_ENGINE, evidence))
        if "consumables" in profile.tags or item.key == "j_perkeo":
            result.append((StrategyIntent.CONSUMABLE_GENERATION, evidence))
        if item.key in _BOSS_PREP_KEYS:
            result.append((StrategyIntent.BOSS_PREPARATION, evidence))
        if profile.score_effect:
            result.append((StrategyIntent.STABILIZE, evidence))
        if not result:
            result.append((StrategyIntent.STABILIZE, (*evidence, "known_joker_capability")))
    elif item.key in _BOSS_PREP_KEYS:
        result.append((StrategyIntent.BOSS_PREPARATION, (source, "audited_boss_control")))
    # Unknown item identities intentionally receive no guessed classification.
    return result


def _classify_voucher(
    item: PublicItem,
    source: str,
) -> list[tuple[StrategyIntent, tuple[str, ...]]]:
    evidence = (source, f"voucher:{item.key}")
    result: list[tuple[StrategyIntent, tuple[str, ...]]] = []
    if item.key in _ECONOMY_VOUCHERS:
        result.append((StrategyIntent.ECONOMY, evidence))
    if item.key in _RELIABILITY_VOUCHERS:
        result.append((StrategyIntent.RELIABLE_HAND, evidence))
        result.append((StrategyIntent.STABILIZE, evidence))
    if item.key in _CONSUMABLE_VOUCHERS:
        result.append((StrategyIntent.CONSUMABLE_GENERATION, evidence))
    if item.key in _SCULPT_VOUCHERS:
        result.append((StrategyIntent.DECK_SCULPT, evidence))
    if item.key in _BOSS_PREP_KEYS:
        result.append((StrategyIntent.BOSS_PREPARATION, evidence))
    if item.key in KNOWN_VOUCHERS and not result:
        result.append((StrategyIntent.STABILIZE, (*evidence, "known_voucher_capability")))
    return result


def _classify_skip(
    observation: PublicObservation,
) -> list[tuple[StrategyIntent, tuple[str, ...]]]:
    selected = next((blind for blind in observation.blinds if blind.status == "SELECT"), None)
    if selected is None or not selected.tag_name:
        return []
    tag = selected.tag_name
    evidence = ("skip_visible_blind", f"tag:{tag}")
    if tag in {"Investment Tag", "Economy Tag", "Handy Tag", "Garbage Tag", "Speed Tag", "Coupon Tag", "D6 Tag"}:
        return [(StrategyIntent.ECONOMY, evidence)]
    if tag in {"Charm Tag", "Ethereal Tag"}:
        return [
            (StrategyIntent.CONSUMABLE_GENERATION, evidence),
            (StrategyIntent.DECK_SCULPT, evidence),
        ]
    if tag == "Meteor Tag":
        return [(StrategyIntent.RELIABLE_HAND, evidence)]
    if tag == "Standard Tag":
        return [(StrategyIntent.DECK_SCULPT, evidence)]
    if tag == "Boss Tag":
        return [(StrategyIntent.BOSS_PREPARATION, evidence)]
    if tag == "Orbital Tag":
        return [(StrategyIntent.RELIABLE_HAND, evidence)]
    if tag in {
        "Uncommon Tag", "Rare Tag", "Negative Tag", "Foil Tag", "Holographic Tag",
        "Polychrome Tag", "Voucher Tag", "Buffoon Tag", "Double Tag", "Juggle Tag",
        "Top-up Tag",
    }:
        return [(StrategyIntent.STABILIZE, evidence)]
    return []


def _classify_consumable(
    item: PublicItem,
    engine: PublicEngineState,
    source: str,
) -> list[tuple[StrategyIntent, tuple[str, ...]]]:
    rule = public_consumable_rule(item)
    if rule is None:
        return []
    evidence = (source, f"consumable:{item.key}")
    result: list[tuple[StrategyIntent, tuple[str, ...]]] = []
    if item.key in _ECONOMY_CONSUMABLES:
        result.append((StrategyIntent.ECONOMY, evidence))
    if item.key in _GENERATOR_CONSUMABLES:
        result.append((StrategyIntent.CONSUMABLE_GENERATION, evidence))
    if item.kind.upper() == "PLANET":
        result.append((StrategyIntent.RELIABLE_HAND, evidence))
    if rule.maximum_targets > 0 or item.kind.upper() == "SPECTRAL":
        result.append((StrategyIntent.DECK_SCULPT, evidence))
    if item.key in _HELD_ENGINE_KEYS:
        result.append((StrategyIntent.HELD_RETRIGGER_ENGINE, evidence))
    if item.key in _PLAYED_ENGINE_KEYS:
        result.append((StrategyIntent.PLAYED_RETRIGGER_ENGINE, evidence))
    return result


def _classify_pack(
    item: PublicItem,
    engine: PublicEngineState,
) -> list[tuple[StrategyIntent, tuple[str, ...]]]:
    # Exact vanilla pack key families are public semantic identities.  No
    # tooltip parsing is used for unknown/modded boosters.
    key = item.key
    evidence = ("buy_pack", f"pack:{key}")
    if key in _ARCANA_PACKS:
        return [
            (StrategyIntent.DECK_SCULPT, evidence),
            (StrategyIntent.CONSUMABLE_GENERATION, evidence),
        ]
    if key in _CELESTIAL_PACKS:
        return [(StrategyIntent.RELIABLE_HAND, evidence)]
    if key in _SPECTRAL_PACKS:
        return [
            (StrategyIntent.DECK_SCULPT, evidence),
            (StrategyIntent.CONSUMABLE_GENERATION, evidence),
        ]
    if key in _STANDARD_PACKS:
        return [(StrategyIntent.DECK_SCULPT, evidence)]
    if key in _BUFFOON_PACKS:
        return [(StrategyIntent.STABILIZE, evidence)]
    return []


def _held_card_intents(
    cards: tuple[VisiblePlayingCard, ...],
    engine: PublicEngineState,
) -> list[tuple[StrategyIntent, tuple[str, ...]]]:
    result: list[tuple[StrategyIntent, tuple[str, ...]]] = []
    if any(
        card.enhancement in {"STEEL", "GOLD"} or card.rank == "K" or card.seal == "BLUE"
        for card in cards
    ) and engine.scoring.archetype_tags.intersection({"held_cards", "kings"}):
        result.append((StrategyIntent.HELD_RETRIGGER_ENGINE, ("visible_held_card_synergy",)))
    if any(card.seal == "BLUE" for card in cards):
        result.append((StrategyIntent.CONSUMABLE_GENERATION, ("hold_visible_blue_seal",)))
    return result


def _played_card_intents(
    cards: tuple[VisiblePlayingCard, ...],
) -> list[tuple[StrategyIntent, tuple[str, ...]]]:
    result: list[tuple[StrategyIntent, tuple[str, ...]]] = []
    if any(
        card.enhancement in {"GLASS", "LUCKY"} or card.seal == "RED"
        for card in cards
    ):
        result.append((StrategyIntent.PLAYED_RETRIGGER_ENGINE, ("visible_played_card_synergy",)))
    return result


def _classify_joker_reorder(
    engine: PublicEngineState,
) -> list[tuple[StrategyIntent, tuple[str, ...]]]:
    if not engine.scoring.copy_relations and not engine.scoring.order_sensitive_slots:
        return []
    evidence = ("public_joker_order", "copy_or_trigger_relation")
    result: list[tuple[StrategyIntent, tuple[str, ...]]] = []
    if engine.scoring.archetype_tags.intersection({"held_cards", "kings", "steel_cards"}):
        result.append((StrategyIntent.HELD_RETRIGGER_ENGINE, evidence))
    if engine.scoring.count_role("retrigger") or not result:
        result.append((StrategyIntent.PLAYED_RETRIGGER_ENGINE, evidence))
    return result


def _supports_endless(observation: PublicObservation, action: PublicAction) -> bool:
    item: PublicItem | None = None
    if isinstance(action, BuyShopCard):
        offer = observation.shop[action.card.value]
        if isinstance(offer, PublicShopPlayingCard):
            return True
        item = offer
    elif isinstance(action, ChoosePackCard):
        offer = observation.opened_pack[action.card.value]
        item = offer if isinstance(offer, PublicItem) else None
    elif isinstance(action, UseConsumable):
        item = observation.consumables[action.consumable.value]
    elif isinstance(action, (ReorderHand, ReorderJokers, ReorderConsumables, PlayCards)):
        return True
    if item is None:
        return False
    profile = JOKER_CATALOG.get(item.key)
    return (
        item.key in _COPY_KEYS
        or item.key in {"j_perkeo", "c_cryptid", "c_deja_vu"}
        or profile is not None
        and profile.role in {"x_mult", "scaling", "retrigger"}
    )


__all__ = [
    "PersistentIntent",
    "StrategicOption",
    "StrategyCandidateRoot",
    "StrategyIntent",
    "build_strategy_candidates",
    "iter_strategy_options",
    "options_for_intent",
]
