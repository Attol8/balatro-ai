"""Relational policy/value model over the strict public Balatro contract.

Unlike :mod:`balatro_ai_v2.public_model`, this model does not flatten an
observation into hashed bags.  Cards, Jokers, consumables, blinds, offers, and
hand statistics remain separate entities.  Legal actions carry explicit
relations to the entities they select, buy, sell, use, or reorder.

The tensorizer deliberately fails closed when an entity or action has semantics
outside the pinned public catalogs.  Display labels and effect prose are never
features: stable public keys and audited semantic metadata are sufficient.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from enum import IntEnum
from pathlib import Path
from typing import Final, Sequence

try:
    import torch
    from torch import Tensor, nn
except ImportError as exc:  # pragma: no cover - exercised in base-only installs
    raise RuntimeError("install the 'model' extra to use the strategy model") from exc

from balatro_ai_v2.actions import (
    BuyMode,
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
    is_legal,
)
from balatro_ai_v2.boss_rules import BOSS_RULES, BossConstraint, boss_rule
from balatro_ai_v2.consumable_rules import public_consumable_rule
from balatro_ai_v2.joker_catalog import JOKER_CATALOG
from balatro_ai_v2.public_state import (
    HiddenHandCard,
    HiddenJokerSlot,
    OBSCURED_CARD_ATTRIBUTE,
    PublicItem,
    PublicObservation,
    PublicShopPlayingCard,
    VisiblePlayingCard,
)
from balatro_ai_v2.strategy_engine import CopyKind, RunRoute, derive_engine_state
from balatro_ai_v2.strategy_context import PublicStrategyContext
from balatro_ai_v2.strategy_options import StrategyIntent


STRATEGY_MODEL_FORMAT_VERSION: Final = 11


class StrategyModelError(RuntimeError):
    """The public state cannot be represented without inventing semantics."""


class EntityKind(IntEnum):
    GLOBAL = 0
    BLIND = 1
    HAND_CARD = 2
    DECK_CARD = 3
    HAND_STAT = 4
    JOKER = 5
    CONSUMABLE = 6
    SHOP_ITEM = 7
    VOUCHER = 8
    BOOSTER = 9
    OPENED_ITEM = 10
    USED_VOUCHER = 11
    LAST_CONSUMABLE = 12
    FULL_DECK_CARD = 13


class ActionKind(IntEnum):
    SELECT_BLIND = 0
    SKIP_BLIND = 1
    CASH_OUT = 2
    LEAVE_SHOP = 3
    REROLL_SHOP = 4
    PLAY_CARDS = 5
    DISCARD_CARDS = 6
    BUY_SHOP_CARD = 7
    BUY_VOUCHER = 8
    BUY_PACK = 9
    SELL_JOKER = 10
    SELL_CONSUMABLE = 11
    USE_CONSUMABLE = 12
    CHOOSE_PACK_CARD = 13
    SKIP_PACK = 14
    REORDER_HAND = 15
    REORDER_JOKERS = 16
    REORDER_CONSUMABLES = 17
    REROLL_BOSS = 18


_ACTION_KIND = {
    SelectBlind: ActionKind.SELECT_BLIND,
    SkipBlind: ActionKind.SKIP_BLIND,
    CashOut: ActionKind.CASH_OUT,
    LeaveShop: ActionKind.LEAVE_SHOP,
    RerollShop: ActionKind.REROLL_SHOP,
    RerollBoss: ActionKind.REROLL_BOSS,
    PlayCards: ActionKind.PLAY_CARDS,
    DiscardCards: ActionKind.DISCARD_CARDS,
    BuyShopCard: ActionKind.BUY_SHOP_CARD,
    BuyVoucher: ActionKind.BUY_VOUCHER,
    BuyPack: ActionKind.BUY_PACK,
    SellJoker: ActionKind.SELL_JOKER,
    SellConsumable: ActionKind.SELL_CONSUMABLE,
    UseConsumable: ActionKind.USE_CONSUMABLE,
    ChoosePackCard: ActionKind.CHOOSE_PACK_CARD,
    SkipPack: ActionKind.SKIP_PACK,
    ReorderHand: ActionKind.REORDER_HAND,
    ReorderJokers: ActionKind.REORDER_JOKERS,
    ReorderConsumables: ActionKind.REORDER_CONSUMABLES,
}

_RANKS = (
    "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A",
    OBSCURED_CARD_ATTRIBUTE,
)
_SUITS = ("S", "H", "D", "C", OBSCURED_CARD_ATTRIBUTE)
_ENHANCEMENTS = ("BONUS", "MULT", "WILD", "GLASS", "STEEL", "STONE", "GOLD", "LUCKY")
_EDITIONS = ("FOIL", "HOLO", "HOLOGRAPHIC", "POLYCHROME", "NEGATIVE")
_SEALS = ("RED", "BLUE", "GOLD", "GOLD SEAL", "PURPLE")
_DECKS = (
    "RED",
    "BLUE",
    "YELLOW",
    "GREEN",
    "BLACK",
    "MAGIC",
    "NEBULA",
    "GHOST",
    "ABANDONED",
    "CHECKERED",
    "ZODIAC",
    "PAINTED",
    "ANAGLYPH",
    "PLASMA",
    "ERRATIC",
)
_STAKES = ("WHITE", "RED", "GREEN", "BLACK", "BLUE", "PURPLE", "ORANGE", "GOLD")
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
_ITEM_KINDS = ("JOKER", "TAROT", "PLANET", "SPECTRAL", "VOUCHER", "BOOSTER")
_JOKER_ROLES = (
    "x_mult",
    "scaling",
    "retrigger",
    "flat_mult",
    "chips",
    "economy",
    "utility",
)
_ARCHETYPE_TAGS = tuple(
    sorted({tag for profile in JOKER_CATALOG.values() for tag in profile.tags})
)
_BOSS_CONSTRAINTS = tuple(constraint.value for constraint in BossConstraint)
_BLIND_STATUSES = ("SELECT", "CURRENT", "UPCOMING", "DEFEATED", "SKIPPED")
_PHASES = ("BLIND_SELECT", "SELECTING_HAND", "ROUND_EVAL", "SHOP", "PACK", "GAME_OVER")
_PACK_KINDS = ("ARCANA", "CELESTIAL", "SPECTRAL", "STANDARD", "BUFFOON")
_TAGS = (
    "Uncommon Tag",
    "Rare Tag",
    "Negative Tag",
    "Foil Tag",
    "Holographic Tag",
    "Polychrome Tag",
    "Investment Tag",
    "Voucher Tag",
    "Boss Tag",
    "Standard Tag",
    "Charm Tag",
    "Meteor Tag",
    "Buffoon Tag",
    "Handy Tag",
    "Garbage Tag",
    "Ethereal Tag",
    "Coupon Tag",
    "Double Tag",
    "Juggle Tag",
    "D6 Tag",
    "Top-up Tag",
    "Speed Tag",
    "Orbital Tag",
    "Economy Tag",
    "Skip Tag",
)
_INTENT_VALUES = ("<none>", *(intent.value for intent in StrategyIntent))
_ROUTE_VALUES = ("<none>", *(route.value for route in RunRoute))

_CONSUMABLE_KEYS = frozenset(
    {
        "c_magician",
        "c_empress",
        "c_heirophant",
        "c_lovers",
        "c_chariot",
        "c_justice",
        "c_strength",
        "c_hanged_man",
        "c_death",
        "c_devil",
        "c_tower",
        "c_star",
        "c_moon",
        "c_sun",
        "c_world",
        "c_talisman",
        "c_aura",
        "c_deja_vu",
        "c_trance",
        "c_medium",
        "c_cryptid",
        "c_mercury",
        "c_venus",
        "c_earth",
        "c_mars",
        "c_jupiter",
        "c_saturn",
        "c_uranus",
        "c_neptune",
        "c_pluto",
        "c_planet_x",
        "c_ceres",
        "c_eris",
        "c_hermit",
        "c_temperance",
        "c_black_hole",
        "c_high_priestess",
        "c_emperor",
        "c_fool",
        "c_judgement",
        "c_soul",
        "c_wraith",
        "c_wheel_of_fortune",
        "c_ectoplasm",
        "c_hex",
        "c_familiar",
        "c_grim",
        "c_incantation",
        "c_immolate",
        "c_sigil",
        "c_ouija",
        "c_ankh",
    }
)
_VOUCHER_KEYS = frozenset(
    {
        "v_antimatter",
        "v_blank",
        "v_clearance_sale",
        "v_crystal_ball",
        "v_directors_cut",
        "v_glow_up",
        "v_grabber",
        "v_hieroglyph",
        "v_hone",
        "v_illusion",
        "v_liquidation",
        "v_magic_trick",
        "v_money_tree",
        "v_nacho_tong",
        "v_observatory",
        "v_omen_globe",
        "v_overstock_norm",
        "v_overstock_plus",
        "v_paint_brush",
        "v_palette",
        "v_petroglyph",
        "v_planet_merchant",
        "v_planet_tycoon",
        "v_recyclomancy",
        "v_reroll_glut",
        "v_reroll_surplus",
        "v_retcon",
        "v_seed_money",
        "v_tarot_merchant",
        "v_tarot_tycoon",
        "v_telescope",
        "v_wasteful",
    }
)
_BOOSTER_IDENTITIES = ("ARCANA", "CELESTIAL", "SPECTRAL", "STANDARD", "BUFFOON")
_BOOSTER_KEYS_BY_IDENTITY = {
    # ``semantic_card_key`` collapses audited artwork variants to these exact
    # gameplay identities before a PublicObservation reaches the policy.
    "ARCANA": frozenset({"p_arcana_normal", "p_arcana_jumbo", "p_arcana_mega"}),
    "CELESTIAL": frozenset(
        {"p_celestial_normal", "p_celestial_jumbo", "p_celestial_mega"}
    ),
    "SPECTRAL": frozenset({"p_spectral_normal", "p_spectral_jumbo", "p_spectral_mega"}),
    "STANDARD": frozenset({"p_standard_normal", "p_standard_jumbo", "p_standard_mega"}),
    "BUFFOON": frozenset({"p_buffoon_normal", "p_buffoon_jumbo", "p_buffoon_mega"}),
}
_IDENTITY_TOKENS = (
    "<global>",
    "<visible-card>",
    "<hidden-card>",
    "<hidden-joker>",
    "<deck-card>",
    "<full-deck-card>",
    "<small-blind>",
    "<big-blind>",
    *sorted(JOKER_CATALOG),
    *sorted(_CONSUMABLE_KEYS),
    *sorted(_VOUCHER_KEYS),
    *(f"boss:{rule.name}" for rule in BOSS_RULES),
    *(f"hand:{name}" for name in _HAND_NAMES),
    *(f"booster:{name}" for name in _BOOSTER_IDENTITIES),
)
_IDENTITY_TO_ID = {token: index for index, token in enumerate(_IDENTITY_TOKENS)}

_SCALARS = (
    "bias",
    "position",
    "zone_size",
    "count",
    "ante",
    "round_no",
    "money",
    "round_chips",
    "round_log_chips",
    "hands_left",
    "discards_left",
    "hands_played",
    "discards_used",
    "reroll_cost",
    "boss_rerolled",
    "hand_limit",
    "selection_limit",
    "draw_count",
    "deck_size",
    "remaining_deck_count",
    "remaining_deck_distinct",
    "full_deck_count",
    "full_deck_distinct",
    "joker_count",
    "joker_limit",
    "consumable_count",
    "consumable_limit",
    "antes_cleared",
    "context_shop_actions",
    "context_shop_sale",
    "context_prior_shop_sale",
    "context_loyalty_known",
    "context_loyalty_remaining",
    "context_best_hand_log_score",
    "won",
    "required",
    "debuffed",
    "permanent_bonus",
    "eternal",
    "perishable_rounds",
    "rental",
    "buy_cost",
    "sell_cost",
    "current_mult",
    "current_chips",
    "current_x_mult",
    "current_dollars",
    "remaining_hands",
    "loyalty_remaining",
    "driver_tally",
    "blind_score",
    "blind_log_score",
    "blind_disabled",
    "hand_level",
    "hand_chips",
    "hand_log_chips",
    "hand_mult",
    "hand_log_mult",
    "hand_played",
    "hand_played_this_round",
    "score_effect",
    "order_sensitive",
    "pack_choices_remaining",
    "action_selection_size",
    "action_primary_slot",
    "action_secondary_slot",
    "action_cost",
    "action_buy_and_use",
)
_FEATURE_NAMES = (
    *_SCALARS,
    *(f"rank:{value}" for value in _RANKS),
    *(f"suit:{value}" for value in _SUITS),
    *(f"enhancement:{value}" for value in _ENHANCEMENTS),
    *(f"edition:{value}" for value in _EDITIONS),
    *(f"seal:{value}" for value in _SEALS),
    *(f"deck:{value}" for value in _DECKS),
    *(f"stake:{value}" for value in _STAKES),
    *(f"item_kind:{value}" for value in _ITEM_KINDS),
    *(f"joker_role:{value}" for value in _JOKER_ROLES),
    *(f"joker_tag:{value}" for value in _ARCHETYPE_TAGS),
    *(f"boss:{value}" for value in _BOSS_CONSTRAINTS),
    *(f"blind_status:{value}" for value in _BLIND_STATUSES),
    *(f"phase:{value}" for value in _PHASES),
    *(f"pack_kind:{value}" for value in _PACK_KINDS),
    *(f"ancient_suit:{value}" for value in _SUITS),
    *(f"target_hand:{value}" for value in _HAND_NAMES),
    *(f"tag:{value}" for value in _TAGS),
    *(f"intent:{value}" for value in _INTENT_VALUES),
    *(f"route:{value}" for value in _ROUTE_VALUES),
)
if len(_FEATURE_NAMES) != len(set(_FEATURE_NAMES)):
    raise RuntimeError("strategy feature names must be unique")
_FEATURE_INDEX = {name: index for index, name in enumerate(_FEATURE_NAMES)}
ENTITY_FEATURE_DIM: Final = len(_FEATURE_NAMES)
ACTION_RELATION_DIM: Final = 3
ENTITY_RELATION_DIM: Final = 4
RELATION_PRESENT: Final = 0
RELATION_BLUEPRINT: Final = 1
RELATION_BRAINSTORM: Final = 2
RELATION_PUBLICLY_ENABLED: Final = 3


def _model_schema_digest() -> str:
    joker_semantics = {
        key: {
            "role": profile.role,
            "tags": sorted(profile.tags),
            "route_tags": sorted(profile.route_tags),
            "order_sensitive": profile.order_sensitive,
            "score_effect": profile.score_effect,
        }
        for key, profile in sorted(JOKER_CATALOG.items())
    }
    boss_semantics = {
        rule.name: sorted(constraint.value for constraint in rule.constraints)
        for rule in BOSS_RULES
    }
    schema = {
        "entity_features": _FEATURE_NAMES,
        "entity_kinds": {kind.name: int(kind) for kind in EntityKind},
        "entity_identities": _IDENTITY_TOKENS,
        "entity_relation_channels": (
            "present",
            "blueprint",
            "brainstorm",
            "publicly_enabled",
        ),
        "action_kinds": {kind.name: int(kind) for kind in ActionKind},
        "action_relation_channels": ("involved", "argument_order", "new_position"),
        "strategy_intents": _INTENT_VALUES,
        "run_routes": _ROUTE_VALUES,
        "output_semantics": (
            "per_candidate_baseline_relative_search_utility_score_and_"
            "five_per_candidate_value_heads_v3"
        ),
        "public_shop_offer_contract": "item_or_structured_playing_card_v1",
        "public_blind_contract": "required_disabled_v1",
        "public_joker_contract": "visible_item_or_anonymous_hidden_slot_v1",
        "deck_entity_compaction": (
            "retain_all_targetable_entities_then_balance_remaining_and_full_deck_"
            "buckets_by_route_salience_then_raw_count_v2"
        ),
        "calibration_fields": (
            "policy_temperature",
            "current_blind_bias",
            "current_blind_temperature",
            "next_boss_bias",
            "next_boss_temperature",
            "ante8_bias",
            "ante8_temperature",
            "endless_ante_bias",
            "log_score_bias",
            "policy_override_margin",
            "calibrated",
        ),
        "provenance_statuses": ("untrained", "trained"),
        "trained_influence_modes": ("diagnostic", "leaf", "shadow"),
        "trained_provenance_fields": (
            "training_status",
            "influence_mode",
            "dataset_sha256",
            "collection_report_sha256",
            "teacher_config_digest",
            "strategy_model_schema_digest",
            "split",
            "trainer",
            "calibration",
        ),
        "calibration_gate_fields": (
            "safe_policy_recommendations",
            "positive_recommendation_coverage",
            "policy_agreement_beats_baseline",
            "zero_recommendation_errors",
            "zero_false_tie_overrides",
            "non_positive_recommendation_regret",
            "positive_recommended_utility_gain",
            "head_improvements",
            "all_heads_beat_train_only_baselines",
            "offline_gate_passed",
            "authorizes_action_influence",
        ),
        "jokers": joker_semantics,
        "bosses": boss_semantics,
        "consumables": sorted(_CONSUMABLE_KEYS),
        "vouchers": sorted(_VOUCHER_KEYS),
        "boosters": {
            identity: sorted(keys)
            for identity, keys in sorted(_BOOSTER_KEYS_BY_IDENTITY.items())
        },
    }
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


STRATEGY_MODEL_SCHEMA_DIGEST: Final = _model_schema_digest()


@dataclass(frozen=True, slots=True)
class StrategyModelConfig:
    hidden_size: int = 96
    attention_heads: int = 4
    attention_layers: int = 2
    feedforward_size: int = 192
    dropout: float = 0.0
    max_entities: int = 256
    max_actions: int = 512

    def __post_init__(self) -> None:
        dimensions = (
            self.hidden_size,
            self.attention_heads,
            self.attention_layers,
            self.feedforward_size,
            self.max_entities,
            self.max_actions,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in dimensions
        ):
            raise ValueError("strategy model dimensions must be integers")
        if min(dimensions) <= 0:
            raise ValueError("strategy model dimensions must be positive")
        if self.hidden_size % self.attention_heads:
            raise ValueError("hidden size must be divisible by attention heads")
        if (
            isinstance(self.dropout, bool)
            or not isinstance(self.dropout, int | float)
            or not 0.0 <= self.dropout < 1.0
            or not math.isfinite(self.dropout)
        ):
            raise ValueError("dropout must be finite and in [0, 1)")


@dataclass(frozen=True, slots=True)
class StrategyCalibration:
    """Frozen post-training transforms and the shadow override threshold."""

    policy_temperature: float = 1.0
    current_blind_bias: float = 0.0
    current_blind_temperature: float = 1.0
    next_boss_bias: float = 0.0
    next_boss_temperature: float = 1.0
    ante8_bias: float = 0.0
    ante8_temperature: float = 1.0
    endless_ante_bias: float = 0.0
    log_score_bias: float = 0.0
    policy_override_margin: float = 0.0
    calibrated: bool = False

    def __post_init__(self) -> None:
        values = tuple(
            getattr(self, field)
            for field in (
                "policy_temperature",
                "current_blind_bias",
                "current_blind_temperature",
                "next_boss_bias",
                "next_boss_temperature",
                "ante8_bias",
                "ante8_temperature",
                "endless_ante_bias",
                "log_score_bias",
                "policy_override_margin",
            )
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int | float)
            for value in values
        ):
            raise ValueError("strategy calibration values must be numbers")
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("strategy calibration values must be finite")
        if (
            min(
                self.policy_temperature,
                self.current_blind_temperature,
                self.next_boss_temperature,
                self.ante8_temperature,
            )
            <= 0
        ):
            raise ValueError("strategy calibration temperatures must be positive")
        if self.policy_override_margin < 0:
            raise ValueError("policy override margin must be non-negative")
        if not isinstance(self.calibrated, bool):
            raise ValueError("calibrated must be boolean")


UNTRAINED_PROVENANCE: Final = {"training_status": "untrained"}
_TRAINED_PROVENANCE_FIELDS: Final = frozenset(
    {
        "training_status",
        "influence_mode",
        "dataset_sha256",
        "collection_report_sha256",
        "teacher_config_digest",
        "strategy_model_schema_digest",
        "split",
        "trainer",
        "calibration",
    }
)
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class StrategyTensorBatch:
    entity_features: Tensor
    entity_kinds: Tensor
    entity_identities: Tensor
    entity_mask: Tensor
    entity_relations: Tensor
    action_features: Tensor
    action_kinds: Tensor
    action_mask: Tensor
    action_relations: Tensor

    def validate(self) -> None:
        if (
            self.entity_features.ndim != 3
            or self.entity_features.shape[-1] != ENTITY_FEATURE_DIM
        ):
            raise StrategyModelError("entity features have the wrong shape")
        batch, entities, _ = self.entity_features.shape
        if batch == 0 or entities == 0:
            raise StrategyModelError("strategy tensor batches must be non-empty")
        if self.entity_features.dtype != torch.float32:
            raise StrategyModelError("entity features must use float32")
        if self.entity_kinds.shape != (batch, entities):
            raise StrategyModelError("entity kinds have the wrong shape")
        if self.entity_kinds.dtype != torch.long:
            raise StrategyModelError("entity kinds must use int64")
        if self.entity_identities.shape != (batch, entities):
            raise StrategyModelError("entity identities have the wrong shape")
        if self.entity_identities.dtype != torch.long:
            raise StrategyModelError("entity identities must use int64")
        if (
            self.entity_mask.shape != (batch, entities)
            or self.entity_mask.dtype != torch.bool
        ):
            raise StrategyModelError("entity mask has the wrong shape or dtype")
        if self.entity_relations.shape != (
            batch,
            entities,
            entities,
            ENTITY_RELATION_DIM,
        ):
            raise StrategyModelError("entity relations have the wrong shape")
        if self.entity_relations.dtype != torch.float32:
            raise StrategyModelError("entity relations must use float32")
        if self.action_features.ndim != 3 or self.action_features.shape[0] != batch:
            raise StrategyModelError("action features have the wrong shape")
        actions = self.action_features.shape[1]
        if self.action_features.shape[2] != ENTITY_FEATURE_DIM:
            raise StrategyModelError("action features have the wrong width")
        if self.action_features.dtype != torch.float32:
            raise StrategyModelError("action features must use float32")
        if self.action_kinds.shape != (batch, actions):
            raise StrategyModelError("action kinds have the wrong shape")
        if self.action_kinds.dtype != torch.long:
            raise StrategyModelError("action kinds must use int64")
        if (
            self.action_mask.shape != (batch, actions)
            or self.action_mask.dtype != torch.bool
        ):
            raise StrategyModelError("action mask has the wrong shape or dtype")
        if self.action_relations.shape != (
            batch,
            actions,
            entities,
            ACTION_RELATION_DIM,
        ):
            raise StrategyModelError("action relations have the wrong shape")
        if self.action_relations.dtype != torch.float32:
            raise StrategyModelError("action relations must use float32")
        if not self.entity_mask.any(dim=1).all():
            raise StrategyModelError(
                "every observation must contain at least one entity"
            )
        if not self.action_mask.any(dim=1).all():
            raise StrategyModelError(
                "every observation must contain at least one legal action"
            )
        if not torch.isfinite(self.entity_features).all():
            raise StrategyModelError("entity features must be finite")
        if not torch.isfinite(self.entity_relations).all():
            raise StrategyModelError("entity relations must be finite")
        if not torch.isfinite(self.action_features).all():
            raise StrategyModelError("action features must be finite")
        if not torch.isfinite(self.action_relations).all():
            raise StrategyModelError("action relations must be finite")
        entity_present = self.entity_relations[..., RELATION_PRESENT]
        if not ((entity_present == 0) | (entity_present == 1)).all():
            raise StrategyModelError("entity relation presence must be binary")
        if (
            self.entity_relations[..., RELATION_BLUEPRINT]
            + self.entity_relations[..., RELATION_BRAINSTORM]
            != entity_present
        ).any():
            raise StrategyModelError(
                "each entity relation must have exactly one copy kind"
            )
        entity_enabled = self.entity_relations[..., RELATION_PUBLICLY_ENABLED]
        if (
            not ((entity_enabled == 0) | (entity_enabled == 1)).all()
            or (entity_enabled > entity_present).any()
        ):
            raise StrategyModelError(
                "entity relation enabled state must be binary and attached"
            )
        valid_entity_pairs = self.entity_mask.unsqueeze(2) & self.entity_mask.unsqueeze(
            1
        )
        if ((entity_present != 0) & ~valid_entity_pairs).any():
            raise StrategyModelError("a padded entity carries a relation")
        active_relations = self.action_relations[..., 0] != 0
        involvement = self.action_relations[..., 0]
        if not ((involvement == 0) | (involvement == 1)).all():
            raise StrategyModelError("relation involvement must be binary")
        if (self.action_relations[..., 1:][~active_relations] != 0).any():
            raise StrategyModelError("inactive relations must have zero attributes")
        valid_pairs = self.action_mask.unsqueeze(-1) & self.entity_mask.unsqueeze(1)
        if (active_relations & ~valid_pairs).any():
            raise StrategyModelError("a padded action or entity carries a relation")

    def to(self, device: torch.device | str) -> StrategyTensorBatch:
        return StrategyTensorBatch(
            *(
                field.to(device)
                for field in (
                    self.entity_features,
                    self.entity_kinds,
                    self.entity_identities,
                    self.entity_mask,
                    self.entity_relations,
                    self.action_features,
                    self.action_kinds,
                    self.action_mask,
                    self.action_relations,
                )
            )
        )


@dataclass(frozen=True, slots=True)
class StrategyModelOutput:
    policy_logits: Tensor
    legal_mask: Tensor
    current_blind_survival: Tensor
    next_boss_survival: Tensor
    ante8_win: Tensor
    endless_ante: Tensor
    log_score: Tensor


@dataclass(frozen=True, slots=True)
class _Entity:
    kind: EntityKind
    identity: int
    features: tuple[float, ...]
    retention_priority: tuple[int, int] = (0, 0)


class PublicStrategyTensorizer:
    """Convert public observations and legal actions into relational tensors."""

    def __init__(self, config: StrategyModelConfig = StrategyModelConfig()) -> None:
        self.config = config

    def tensorize(
        self,
        observations: Sequence[PublicObservation],
        legal_actions: Sequence[Sequence[PublicAction]],
        action_intents: Sequence[Sequence[StrategyIntent | None]] | None = None,
        contexts: Sequence[PublicStrategyContext] | None = None,
        action_routes: Sequence[Sequence[RunRoute | None]] | None = None,
    ) -> StrategyTensorBatch:
        if not observations or len(observations) != len(legal_actions):
            raise StrategyModelError(
                "observations and legal actions need the same non-zero batch size"
            )
        if action_intents is not None and len(action_intents) != len(observations):
            raise StrategyModelError("action intents have the wrong batch size")
        if contexts is not None and len(contexts) != len(observations):
            raise StrategyModelError("public contexts have the wrong batch size")
        if action_routes is not None and len(action_routes) != len(observations):
            raise StrategyModelError("action routes have the wrong batch size")
        context_rows = (
            tuple(PublicStrategyContext() for _ in observations)
            if contexts is None
            else tuple(contexts)
        )
        if not all(
            isinstance(context, PublicStrategyContext) for context in context_rows
        ):
            raise StrategyModelError("public context has the wrong type")

        rows: list[tuple[list[_Entity], dict[tuple[str, int], int]]] = []
        action_rows: list[tuple[PublicAction, ...]] = []
        intent_rows: list[tuple[StrategyIntent | None, ...]] = []
        route_rows: list[tuple[RunRoute | None, ...]] = []
        for row, (observation, supplied_actions, context) in enumerate(
            zip(observations, legal_actions, context_rows, strict=True)
        ):
            entities, locations = self._entities(observation, context)
            actions = tuple(supplied_actions)
            intents = (
                (None,) * len(actions)
                if action_intents is None
                else tuple(action_intents[row])
            )
            routes = (
                (None,) * len(actions)
                if action_routes is None
                else tuple(action_routes[row])
            )
            if not actions:
                raise StrategyModelError(
                    "each observation needs at least one legal action"
                )
            if len(intents) != len(actions):
                raise StrategyModelError(
                    "every action needs exactly one supplied intent"
                )
            if len(routes) != len(actions):
                raise StrategyModelError(
                    "every action needs exactly one supplied route"
                )
            if any(
                intent is not None and not isinstance(intent, StrategyIntent)
                for intent in intents
            ):
                raise StrategyModelError(
                    "action intents must be StrategyIntent values or None"
                )
            if any(
                route is not None and not isinstance(route, RunRoute)
                for route in routes
            ):
                raise StrategyModelError(
                    "action routes must be RunRoute values or None"
                )
            if len(entities) > self.config.max_entities:
                raise StrategyModelError(
                    "observation exceeds the configured entity limit"
                )
            if len(actions) > self.config.max_actions:
                raise StrategyModelError(
                    "observation exceeds the configured action limit"
                )
            unique_candidates = tuple(
                zip(actions, intents, routes, strict=True)
            )
            if len(set(unique_candidates)) != len(actions):
                raise StrategyModelError(
                    "action/intent/route candidate triples must be unique"
                )
            rows.append((entities, locations))
            action_rows.append(actions)
            intent_rows.append(intents)
            route_rows.append(routes)

        batch = len(rows)
        entity_width = max(len(entities) for entities, _ in rows)
        action_width = max(len(actions) for actions in action_rows)
        entity_features = torch.zeros(
            batch, entity_width, ENTITY_FEATURE_DIM, dtype=torch.float32
        )
        entity_kinds = torch.zeros(batch, entity_width, dtype=torch.long)
        entity_identities = torch.zeros(batch, entity_width, dtype=torch.long)
        entity_mask = torch.zeros(batch, entity_width, dtype=torch.bool)
        entity_relations = torch.zeros(
            batch, entity_width, entity_width, ENTITY_RELATION_DIM, dtype=torch.float32
        )
        action_features = torch.zeros(
            batch, action_width, ENTITY_FEATURE_DIM, dtype=torch.float32
        )
        action_kinds = torch.zeros(batch, action_width, dtype=torch.long)
        action_mask = torch.zeros(batch, action_width, dtype=torch.bool)
        action_relations = torch.zeros(
            batch, action_width, entity_width, ACTION_RELATION_DIM, dtype=torch.float32
        )

        for row, (
            (entities, locations),
            observation,
            actions,
            intents,
            routes,
        ) in enumerate(
            zip(
                rows,
                observations,
                action_rows,
                intent_rows,
                route_rows,
                strict=True,
            )
        ):
            for column, entity in enumerate(entities):
                entity_features[row, column] = torch.tensor(entity.features)
                entity_kinds[row, column] = int(entity.kind)
                entity_identities[row, column] = entity.identity
                entity_mask[row, column] = True
            for (source, target), relation in self._entity_relations(
                observation, locations
            ).items():
                entity_relations[row, source, target] = torch.tensor(relation)
            for column, (action, intent, route) in enumerate(
                zip(actions, intents, routes, strict=True)
            ):
                kind, features, relations = self._action(
                    observation, action, locations, intent, route
                )
                action_features[row, column] = torch.tensor(features)
                action_kinds[row, column] = int(kind)
                action_mask[row, column] = True
                for entity_index, relation in relations.items():
                    action_relations[row, column, entity_index] = torch.tensor(relation)

        result = StrategyTensorBatch(
            entity_features,
            entity_kinds,
            entity_identities,
            entity_mask,
            entity_relations,
            action_features,
            action_kinds,
            action_mask,
            action_relations,
        )
        result.validate()
        return result

    def _entity_relations(
        self,
        observation: PublicObservation,
        locations: dict[tuple[str, int], int],
    ) -> dict[tuple[int, int], tuple[float, float, float, float]]:
        """Return public copy topology without asserting copy compatibility.

        Blueprint points at its immediate right-hand Joker. Brainstorm points
        at the leftmost Joker; when Brainstorm itself is leftmost, the explicit
        self-cycle is retained but marked disabled. ``publicly_enabled`` is
        the shared engine projection's conservative visible gate: source and
        target are not debuffed and are not the same slot. It makes no claim
        that the target mechanic is copy-compatible.
        """

        relations: dict[tuple[int, int], tuple[float, float, float, float]] = {}
        public_relations = derive_engine_state(observation).scoring.copy_relations
        for relation in public_relations:
            source = locations[("joker", relation.source_slot)]
            target = locations[("joker", relation.target_slot)]
            if relation.kind == CopyKind.BLUEPRINT_RIGHT:
                blueprint, brainstorm = 1.0, 0.0
            elif relation.kind == CopyKind.BRAINSTORM_LEFTMOST:
                blueprint, brainstorm = 0.0, 1.0
            else:  # pragma: no cover - enum exhaustiveness guard
                raise StrategyModelError(f"unsupported copy relation {relation.kind!r}")
            relations[(source, target)] = (
                1.0,
                blueprint,
                brainstorm,
                float(relation.publicly_enabled),
            )
        return relations

    def _entities(
        self,
        observation: PublicObservation,
        context: PublicStrategyContext,
    ) -> tuple[list[_Entity], dict[tuple[str, int], int]]:
        if observation.deck not in _DECKS:
            raise StrategyModelError(f"unsupported public deck {observation.deck!r}")
        if observation.stake not in _STAKES:
            raise StrategyModelError(f"unsupported public stake {observation.stake!r}")
        entities: list[_Entity] = []
        locations: dict[tuple[str, int], int] = {}

        global_features = _features()
        for name, value, scale in (
            ("ante", observation.ante, 16),
            ("round_no", observation.round_no, 64),
            ("money", observation.money, 100),
            ("round_chips", observation.round.chips, 1_000_000),
            ("hands_left", observation.round.hands_left, 10),
            ("discards_left", observation.round.discards_left, 10),
            ("hands_played", observation.round.hands_played, 10),
            ("discards_used", observation.round.discards_used, 10),
            ("reroll_cost", observation.round.reroll_cost, 20),
            ("boss_rerolled", int(observation.round.boss_rerolled), 1),
            ("hand_limit", observation.hand_limit, 20),
            ("selection_limit", observation.selection_limit, 10),
            ("draw_count", observation.draw_count, 52),
            ("deck_size", observation.deck_size, 104),
            (
                "remaining_deck_count",
                sum(card.count for card in observation.remaining_deck),
                512,
            ),
            ("remaining_deck_distinct", len(observation.remaining_deck), 512),
            (
                "full_deck_count",
                sum(card.count for card in observation.full_deck),
                512,
            ),
            ("full_deck_distinct", len(observation.full_deck), 512),
            ("joker_count", len(observation.jokers), 10),
            ("joker_limit", observation.joker_limit, 10),
            ("consumable_count", len(observation.consumables), 10),
            ("consumable_limit", observation.consumable_limit, 10),
            ("antes_cleared", observation.antes_cleared, 16),
        ):
            _put_scaled(global_features, name, value, scale)
        _put_log_scaled(
            global_features, "round_log_chips", observation.round.chips, 100
        )
        _put(global_features, "won", float(observation.won))
        _put_scaled(
            global_features, "context_shop_actions", context.current_shop_actions, 10
        )
        _put(
            global_features,
            "context_shop_sale",
            float(context.current_shop_has_joker_sale),
        )
        _put(
            global_features,
            "context_prior_shop_sale",
            float(context.prior_shop_has_joker_sale),
        )
        _put(
            global_features,
            "context_loyalty_known",
            float(context.loyalty_remaining is not None),
        )
        if context.loyalty_remaining is not None:
            _put_scaled(
                global_features,
                "context_loyalty_remaining",
                context.loyalty_remaining,
                5,
            )
        _put_scaled(
            global_features,
            "context_best_hand_log_score",
            context.best_hand_log_score,
            16,
        )
        if context.incoming_intent is not None:
            _put_category(
                global_features,
                "intent",
                context.incoming_intent.value,
                _INTENT_VALUES,
            )
        if context.incoming_route is not None:
            _put_category(
                global_features,
                "route",
                context.incoming_route.value,
                _ROUTE_VALUES,
            )
        _put_category(global_features, "deck", observation.deck, _DECKS)
        _put_category(global_features, "stake", observation.stake, _STAKES)
        _put_category(global_features, "phase", observation.phase.value, _PHASES)
        if observation.round.ancient_suit is not None:
            _put_category(
                global_features, "ancient_suit", observation.round.ancient_suit, _SUITS
            )
        if observation.pack_kind is not None:
            _put_category(
                global_features, "pack_kind", observation.pack_kind, _PACK_KINDS
            )
        _put_scaled(
            global_features,
            "pack_choices_remaining",
            observation.pack_choices_remaining,
            5,
        )
        entities.append(_entity(EntityKind.GLOBAL, "<global>", global_features, 0, 1))
        locations[("global", 0)] = 0

        def append(zone: str, index: int, entity: _Entity) -> None:
            locations[(zone, index)] = len(entities)
            entities.append(entity)

        for index, blind in enumerate(observation.blinds):
            features = _features()
            _put_scaled(features, "blind_score", blind.score, 1_000_000)
            _put_log_scaled(features, "blind_log_score", blind.score, 100)
            if blind.disabled:
                _put(features, "blind_disabled", 1.0)
            _put_category(features, "blind_status", blind.status, _BLIND_STATUSES)
            if blind.tag_name:
                _put_category(features, "tag", blind.tag_name, _TAGS)
            kind = blind.kind.upper()
            if kind == "BOSS":
                rule = boss_rule(blind.name)
                if rule is None:
                    raise StrategyModelError(f"unsupported public boss {blind.name!r}")
                identity = f"boss:{rule.name}"
                for constraint in rule.constraints:
                    _put(features, f"boss:{constraint.value}", 1.0)
            elif kind in {"SMALL", "BIG"}:
                identity = f"<{kind.casefold()}-blind>"
            else:
                raise StrategyModelError(f"unsupported blind kind {blind.kind!r}")
            append(
                "blind",
                index,
                _entity(
                    EntityKind.BLIND, identity, features, index, len(observation.blinds)
                ),
            )

        for index, card in enumerate(observation.hand):
            features = _features()
            _put(features, "required", float(index in observation.required_hand_slots))
            identity = "<hidden-card>"
            if isinstance(card, VisiblePlayingCard):
                _card_features(features, card)
                identity = "<visible-card>"
            elif not isinstance(card, HiddenHandCard):
                raise StrategyModelError(
                    f"unsupported hand entity {type(card).__name__}"
                )
            append(
                "hand",
                index,
                _entity(
                    EntityKind.HAND_CARD,
                    identity,
                    features,
                    index,
                    len(observation.hand),
                ),
            )

        canonical_deck = sorted(
            observation.remaining_deck,
            key=lambda entry: (
                entry.card.rank,
                entry.card.suit,
                entry.card.enhancement or "",
                entry.card.edition or "",
                entry.card.seal or "",
                entry.card.debuffed,
                entry.card.permanent_bonus,
            ),
        )
        for index, entry in enumerate(canonical_deck):
            if entry.count <= 0:
                raise StrategyModelError("remaining-deck counts must be positive")
            features = _features()
            _card_features(features, entry.card)
            _put_scaled(features, "count", entry.count, 52)
            append(
                "deck",
                index,
                _entity(
                    EntityKind.DECK_CARD,
                    "<deck-card>",
                    features,
                    index,
                    len(canonical_deck),
                    retention_priority=_deck_retention_priority(
                        entry.card, entry.count
                    ),
                ),
            )

        canonical_full_deck = sorted(
            observation.full_deck,
            key=lambda entry: (
                entry.card.rank,
                entry.card.suit,
                entry.card.enhancement or "",
                entry.card.edition or "",
                entry.card.seal or "",
                entry.card.permanent_bonus,
            ),
        )
        for index, entry in enumerate(canonical_full_deck):
            features = _features()
            _card_features(features, entry.card)
            _put_scaled(features, "count", entry.count, 52)
            append(
                "full_deck",
                index,
                _entity(
                    EntityKind.FULL_DECK_CARD,
                    "<full-deck-card>",
                    features,
                    index,
                    len(canonical_full_deck),
                    retention_priority=_deck_retention_priority(
                        entry.card, entry.count
                    ),
                ),
            )

        for index, stat in enumerate(observation.hand_stats):
            if stat.name not in _HAND_NAMES:
                raise StrategyModelError(f"unsupported poker hand {stat.name!r}")
            features = _features()
            for name, value, scale in (
                ("hand_level", stat.level, 100),
                ("hand_chips", stat.chips, 100_000),
                ("hand_mult", stat.mult, 10_000),
                ("hand_played", stat.played, 1_000),
                ("hand_played_this_round", stat.played_this_round, 20),
            ):
                _put_scaled(features, name, value, scale)
            _put_log_scaled(features, "hand_log_chips", stat.chips, 100)
            _put_log_scaled(features, "hand_log_mult", stat.mult, 100)
            append(
                "hand_stat",
                index,
                _entity(
                    EntityKind.HAND_STAT,
                    f"hand:{stat.name}",
                    features,
                    index,
                    len(observation.hand_stats),
                ),
            )

        self._append_items(
            entities, locations, "joker", observation.jokers, EntityKind.JOKER
        )
        self._append_items(
            entities,
            locations,
            "consumable",
            observation.consumables,
            EntityKind.CONSUMABLE,
        )
        self._append_shop_offers(entities, locations, observation)
        self._append_items(
            entities, locations, "voucher", observation.vouchers, EntityKind.VOUCHER
        )
        self._append_items(
            entities, locations, "pack", observation.packs, EntityKind.BOOSTER
        )

        for index, offer in enumerate(observation.opened_pack):
            if isinstance(offer, VisiblePlayingCard):
                features = _features()
                _card_features(features, offer)
                append(
                    "opened",
                    index,
                    _entity(
                        EntityKind.OPENED_ITEM,
                        "<visible-card>",
                        features,
                        index,
                        len(observation.opened_pack),
                    ),
                )
            elif isinstance(offer, PublicItem):
                append(
                    "opened",
                    index,
                    self._item_entity(
                        offer,
                        EntityKind.OPENED_ITEM,
                        index,
                        len(observation.opened_pack),
                    ),
                )
            else:
                raise StrategyModelError(
                    f"unsupported pack offer {type(offer).__name__}"
                )

        for index, key in enumerate(observation.used_vouchers):
            if key not in _VOUCHER_KEYS:
                raise StrategyModelError(f"unsupported used voucher {key!r}")
            append(
                "used_voucher",
                index,
                _entity(
                    EntityKind.USED_VOUCHER,
                    key,
                    _features(),
                    index,
                    len(observation.used_vouchers),
                ),
            )
        if observation.last_tarot_planet is not None:
            key = observation.last_tarot_planet
            if key not in _CONSUMABLE_KEYS:
                raise StrategyModelError(f"unsupported last Tarot/Planet {key!r}")
            append(
                "last_consumable",
                0,
                _entity(EntityKind.LAST_CONSUMABLE, key, _features(), 0, 1),
            )
        return self._bounded_entities(entities, locations)

    def _bounded_entities(
        self,
        entities: list[_Entity],
        locations: dict[tuple[str, int], int],
    ) -> tuple[list[_Entity], dict[tuple[str, int], int]]:
        """Compact only untargeted deck buckets to the configured hard bound."""

        if len(entities) <= self.config.max_entities:
            return entities, locations
        deck_kinds = (EntityKind.DECK_CARD, EntityKind.FULL_DECK_CARD)
        essential = {
            index for index, entity in enumerate(entities) if entity.kind not in deck_kinds
        }
        budget = self.config.max_entities - len(essential)
        if budget < 0:
            raise StrategyModelError(
                "non-deck observation exceeds the configured entity limit"
            )
        groups = [
            sorted(
                (
                    index
                    for index, entity in enumerate(entities)
                    if entity.kind == kind
                ),
                key=lambda index: (
                    -entities[index].retention_priority[0],
                    -entities[index].retention_priority[1],
                    entities[index].features,
                ),
            )
            for kind in deck_kinds
        ]
        retained_deck: list[int] = []
        group_positions = [0] * len(groups)
        while len(retained_deck) < budget and any(
            position < len(group)
            for position, group in zip(group_positions, groups, strict=True)
        ):
            for group_index, group in enumerate(groups):
                position = group_positions[group_index]
                if position < len(group) and len(retained_deck) < budget:
                    retained_deck.append(group[position])
                    group_positions[group_index] += 1
        retained = essential | set(retained_deck)
        old_to_new: dict[int, int] = {}
        bounded: list[_Entity] = []
        for old_index, entity in enumerate(entities):
            if old_index in retained:
                old_to_new[old_index] = len(bounded)
                bounded.append(entity)
        bounded_locations = {
            location: old_to_new[index]
            for location, index in locations.items()
            if index in old_to_new
        }
        return bounded, bounded_locations

    def _append_items(
        self,
        entities: list[_Entity],
        locations: dict[tuple[str, int], int],
        zone: str,
        items: tuple[PublicItem | HiddenJokerSlot, ...],
        kind: EntityKind,
    ) -> None:
        for index, item in enumerate(items):
            locations[(zone, index)] = len(entities)
            if isinstance(item, HiddenJokerSlot):
                if zone != "joker" or kind != EntityKind.JOKER:
                    raise StrategyModelError(
                        "anonymous hidden slots are valid only in the Joker area"
                    )
                entities.append(
                    _entity(kind, "<hidden-joker>", _features(), index, len(items))
                )
            else:
                entities.append(self._item_entity(item, kind, index, len(items)))

    def _append_shop_offers(
        self,
        entities: list[_Entity],
        locations: dict[tuple[str, int], int],
        observation: PublicObservation,
    ) -> None:
        for index, offer in enumerate(observation.shop):
            locations[("shop", index)] = len(entities)
            if isinstance(offer, PublicItem):
                entity = self._item_entity(
                    offer, EntityKind.SHOP_ITEM, index, len(observation.shop)
                )
            elif isinstance(offer, PublicShopPlayingCard):
                features = _features()
                _card_features(features, offer.card)
                _put_scaled(features, "buy_cost", offer.buy_cost, 100)
                entity = _entity(
                    EntityKind.SHOP_ITEM,
                    "<visible-card>",
                    features,
                    index,
                    len(observation.shop),
                )
            else:  # pragma: no cover - guarded by the public observation type
                raise StrategyModelError(
                    f"unsupported shop offer {type(offer).__name__}"
                )
            entities.append(entity)

    def _item_entity(
        self, item: PublicItem, entity_kind: EntityKind, position: int, size: int
    ) -> _Entity:
        kind = item.kind.upper()
        if kind not in _ITEM_KINDS:
            raise StrategyModelError(f"unsupported public item kind {item.kind!r}")
        features = _features()
        _put_category(features, "item_kind", kind, _ITEM_KINDS)
        _put(features, "eternal", float(item.eternal))
        _put(features, "rental", float(item.rental))
        _put(features, "debuffed", float(item.debuffed))
        if item.perishable_rounds is not None:
            _put_scaled(features, "perishable_rounds", item.perishable_rounds, 10)
        if item.buy_cost is not None:
            _put_scaled(features, "buy_cost", item.buy_cost, 100)
        if item.sell_cost is not None:
            _put_scaled(features, "sell_cost", item.sell_cost, 100)
        if item.edition is not None:
            _put_category(features, "edition", item.edition, _EDITIONS)

        if kind == "JOKER":
            profile = JOKER_CATALOG.get(item.key)
            if profile is None:
                raise StrategyModelError(f"unsupported public Joker {item.key!r}")
            _put(features, f"joker_role:{profile.role}", 1.0)
            for tag in profile.tags:
                _put(features, f"joker_tag:{tag}", 1.0)
            _put(features, "score_effect", float(profile.score_effect))
            _put(features, "order_sensitive", float(profile.order_sensitive))
            if item.runtime is not None:
                runtime = item.runtime
                for name, value, scale in (
                    ("current_mult", runtime.current_mult, 1_000),
                    ("current_chips", runtime.current_chips, 100_000),
                    ("current_x_mult", runtime.current_x_mult, 100),
                    ("current_dollars", runtime.current_dollars, 1_000),
                    ("remaining_hands", runtime.remaining_hands, 20),
                    ("loyalty_remaining", runtime.loyalty_remaining, 10),
                    ("driver_tally", runtime.driver_tally, 52),
                ):
                    if value is not None:
                        _put_scaled(features, name, value, scale)
                if (
                    runtime.target_hand is not None
                    and runtime.target_hand not in _HAND_NAMES
                ):
                    raise StrategyModelError(
                        f"unsupported runtime target hand {runtime.target_hand!r}"
                    )
                if runtime.target_hand is not None:
                    _put_category(
                        features, "target_hand", runtime.target_hand, _HAND_NAMES
                    )
                if runtime.target_rank is not None:
                    _put_category(features, "rank", runtime.target_rank, _RANKS)
                if runtime.target_suit is not None:
                    _put_category(features, "suit", runtime.target_suit, _SUITS)
            identity = item.key
        elif kind in {"TAROT", "PLANET", "SPECTRAL"}:
            if item.key not in _CONSUMABLE_KEYS or public_consumable_rule(item) is None:
                raise StrategyModelError(f"unsupported public consumable {item.key!r}")
            identity = item.key
        elif kind == "VOUCHER":
            if item.key not in _VOUCHER_KEYS:
                raise StrategyModelError(f"unsupported public voucher {item.key!r}")
            identity = item.key
        elif kind == "BOOSTER":
            booster = _booster_identity(item.key)
            identity = f"booster:{booster}"
        else:  # pragma: no cover - guarded by the admitted kind set
            raise StrategyModelError(f"unsupported public item kind {kind!r}")
        return _entity(entity_kind, identity, features, position, size)

    def _action(
        self,
        observation: PublicObservation,
        action: PublicAction,
        locations: dict[tuple[str, int], int],
        intent: StrategyIntent | None,
        route: RunRoute | None,
    ) -> tuple[ActionKind, tuple[float, ...], dict[int, tuple[float, float, float]]]:
        kind = _ACTION_KIND.get(type(action))
        if kind is None:
            raise StrategyModelError(
                f"unsupported public action {type(action).__name__}"
            )
        if not is_legal(observation, action):
            raise StrategyModelError(f"supplied action is not legal: {action!r}")
        features = _features()
        _put_category(
            features,
            "intent",
            "<none>" if intent is None else intent.value,
            _INTENT_VALUES,
        )
        _put_category(
            features,
            "route",
            "<none>" if route is None else route.value,
            _ROUTE_VALUES,
        )
        relations: dict[int, tuple[float, float, float]] = {}

        def relate(
            zone: str,
            index: int,
            argument_order: float = 1.0,
            new_position: float = 0.0,
        ) -> None:
            entity = locations.get((zone, index))
            if entity is None:
                raise StrategyModelError(
                    f"action target {zone}[{index}] has no public entity"
                )
            relations[entity] = (1.0, argument_order, new_position)

        relate("global", 0)
        if isinstance(action, (SelectBlind, SkipBlind)):
            selected = next(
                (
                    i
                    for i, blind in enumerate(observation.blinds)
                    if blind.status == "SELECT"
                ),
                None,
            )
            if selected is None:
                raise StrategyModelError("blind action has no selected public blind")
            relate("blind", selected)
        elif isinstance(action, RerollBoss):
            boss = next(
                (
                    i
                    for i, blind in enumerate(observation.blinds)
                    if blind.kind == "BOSS"
                    and blind.status in {"SELECT", "UPCOMING"}
                ),
                None,
            )
            if boss is None:
                raise StrategyModelError("boss reroll has no public Boss Blind")
            relate("blind", boss)
            _put_scaled(features, "action_cost", 10, 100)
        elif isinstance(action, (PlayCards, DiscardCards)):
            _put_scaled(features, "action_selection_size", len(action.cards), 5)
            for order, slot in enumerate(action.cards):
                relate("hand", slot.value, (order + 1) / len(action.cards))
        elif isinstance(action, BuyShopCard):
            relate("shop", action.card.value)
            if action.mode == BuyMode.USE:
                features[_FEATURE_INDEX["action_buy_and_use"]] = 1.0
            _put_scaled(
                features,
                "action_primary_slot",
                action.card.value + 1,
                max(1, len(observation.shop)),
            )
            cost = observation.shop[action.card.value].buy_cost
            if cost is not None:
                _put_scaled(features, "action_cost", cost, 100)
        elif isinstance(action, BuyVoucher):
            relate("voucher", action.voucher.value)
            cost = observation.vouchers[action.voucher.value].buy_cost
            if cost is not None:
                _put_scaled(features, "action_cost", cost, 100)
        elif isinstance(action, BuyPack):
            relate("pack", action.pack.value)
            cost = observation.packs[action.pack.value].buy_cost
            if cost is not None:
                _put_scaled(features, "action_cost", cost, 100)
        elif isinstance(action, SellJoker):
            relate("joker", action.joker.value)
        elif isinstance(action, SellConsumable):
            relate("consumable", action.consumable.value)
        elif isinstance(action, UseConsumable):
            relate("consumable", action.consumable.value)
            for order, target in enumerate(action.targets):
                relate("hand", target.value, (order + 1) / max(1, len(action.targets)))
            _put_scaled(features, "action_selection_size", len(action.targets), 5)
        elif isinstance(action, ChoosePackCard):
            relate("opened", action.card.value)
            for order, target in enumerate(action.targets):
                relate("hand", target.value, (order + 1) / max(1, len(action.targets)))
            _put_scaled(features, "action_selection_size", len(action.targets), 5)
        elif isinstance(action, ReorderHand):
            _reorder_relations(relate, "hand", action.order)
        elif isinstance(action, ReorderJokers):
            _reorder_relations(relate, "joker", action.order)
        elif isinstance(action, ReorderConsumables):
            _reorder_relations(relate, "consumable", action.order)
        elif not isinstance(
            action, (CashOut, LeaveShop, RerollShop, RerollBoss, SkipPack)
        ):
            raise StrategyModelError(
                f"unsupported public action semantics for {action!r}"
            )
        return kind, tuple(features), relations


class RelationalStrategyPolicyValue(nn.Module):
    """Attention over public entities with action-to-entity relational scoring."""

    def __init__(
        self,
        config: StrategyModelConfig = StrategyModelConfig(),
        calibration: StrategyCalibration = StrategyCalibration(),
        provenance: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__()
        if not isinstance(calibration, StrategyCalibration):
            raise ValueError("strategy calibration has the wrong type")
        self.config = config
        self.calibration = calibration
        self.provenance = _normalize_provenance(
            UNTRAINED_PROVENANCE if provenance is None else provenance
        )
        if self.provenance.get("training_status") == "trained":
            if (
                self.provenance["strategy_model_schema_digest"]
                != STRATEGY_MODEL_SCHEMA_DIGEST
            ):
                raise ValueError("trained provenance has the wrong model schema digest")
            calibration_metadata = self.provenance["calibration"]
            if not isinstance(calibration_metadata, dict) or calibration_metadata[
                "parameters"
            ] != asdict(calibration):
                raise ValueError("trained provenance disagrees with model calibration")
        hidden = config.hidden_size
        self.entity_kind_embedding = nn.Embedding(len(EntityKind), hidden)
        self.identity_embedding = nn.Embedding(len(_IDENTITY_TOKENS), hidden)
        self.action_kind_embedding = nn.Embedding(len(ActionKind), hidden)
        self.entity_feature_encoder = nn.Linear(ENTITY_FEATURE_DIM, hidden)
        self.action_feature_encoder = nn.Linear(ENTITY_FEATURE_DIM, hidden)
        self.entity_relation_encoder = nn.Linear(
            ENTITY_RELATION_DIM, hidden, bias=False
        )
        self.entity_message = nn.Sequential(nn.Linear(hidden, hidden), nn.GELU())
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden,
            nhead=config.attention_heads,
            dim_feedforward=config.feedforward_size,
            dropout=config.dropout,
            batch_first=True,
            norm_first=True,
            activation="gelu",
        )
        self.entity_attention = nn.TransformerEncoder(
            encoder_layer,
            config.attention_layers,
            enable_nested_tensor=False,
        )
        self.relation_encoder = nn.Linear(ACTION_RELATION_DIM, hidden, bias=False)
        self.policy_head = nn.Sequential(
            nn.Linear(hidden * 4, hidden), nn.GELU(), nn.Linear(hidden, 1)
        )
        self.current_blind_head = nn.Linear(hidden * 4, 1)
        self.next_boss_head = nn.Linear(hidden * 4, 1)
        self.ante8_head = nn.Linear(hidden * 4, 1)
        self.endless_ante_head = nn.Linear(hidden * 4, 1)
        self.log_score_head = nn.Linear(hidden * 4, 1)

    def forward(self, batch: StrategyTensorBatch) -> StrategyModelOutput:
        batch.validate()
        device = next(self.parameters()).device
        batch = batch.to(device)
        if batch.entity_kinds.min() < 0 or batch.entity_kinds.max() >= len(EntityKind):
            raise StrategyModelError(
                "entity kind index is outside the admitted vocabulary"
            )
        if batch.entity_identities.min() < 0 or batch.entity_identities.max() >= len(
            _IDENTITY_TOKENS
        ):
            raise StrategyModelError(
                "entity identity index is outside the admitted vocabulary"
            )
        if batch.action_kinds.min() < 0 or batch.action_kinds.max() >= len(ActionKind):
            raise StrategyModelError(
                "action kind index is outside the admitted vocabulary"
            )

        entity_tokens = (
            self.entity_feature_encoder(batch.entity_features)
            + self.entity_kind_embedding(batch.entity_kinds)
            + self.identity_embedding(batch.entity_identities)
        )
        copy_presence = batch.entity_relations[..., RELATION_PRESENT]
        copy_payload = entity_tokens.unsqueeze(1) + self.entity_relation_encoder(
            batch.entity_relations
        )
        copy_messages = torch.einsum("bij,bijh->bih", copy_presence, copy_payload)
        copy_counts = copy_presence.sum(dim=-1, keepdim=True)
        copy_messages = copy_messages / copy_counts.clamp_min(1.0)
        entity_tokens = entity_tokens + self.entity_message(copy_messages) * (
            copy_counts > 0
        )
        encoded = self.entity_attention(
            entity_tokens, src_key_padding_mask=~batch.entity_mask
        )
        mask = batch.entity_mask.unsqueeze(-1)
        pooled = (encoded * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1)

        action_tokens = self.action_feature_encoder(
            batch.action_features
        ) + self.action_kind_embedding(batch.action_kinds)
        involvement = batch.action_relations[..., 0] * (
            batch.entity_mask.unsqueeze(1) & batch.action_mask.unsqueeze(-1)
        )
        weights = involvement / involvement.sum(dim=-1, keepdim=True).clamp_min(1.0)
        target_context = torch.einsum("bae,beh->bah", weights, encoded)
        relation_context = self.relation_encoder(batch.action_relations).sum(dim=2) / (
            involvement.sum(dim=-1, keepdim=True).clamp_min(1.0)
        )
        pooled_actions = pooled.unsqueeze(1).expand(-1, action_tokens.shape[1], -1)
        action_context = torch.cat(
            (pooled_actions, action_tokens, target_context, relation_context), dim=-1
        )
        raw_logits = self.policy_head(action_context).squeeze(-1)
        logits = raw_logits / self.calibration.policy_temperature
        logits = logits.masked_fill(~batch.action_mask, torch.finfo(logits.dtype).min)

        current_blind = self.current_blind_head(action_context).squeeze(-1)
        next_boss = self.next_boss_head(action_context).squeeze(-1)
        ante8 = self.ante8_head(action_context).squeeze(-1)

        result = StrategyModelOutput(
            policy_logits=logits,
            legal_mask=batch.action_mask,
            current_blind_survival=torch.sigmoid(
                (current_blind + self.calibration.current_blind_bias)
                / self.calibration.current_blind_temperature
            ),
            next_boss_survival=torch.sigmoid(
                (next_boss + self.calibration.next_boss_bias)
                / self.calibration.next_boss_temperature
            ),
            ante8_win=torch.sigmoid(
                (ante8 + self.calibration.ante8_bias)
                / self.calibration.ante8_temperature
            ),
            endless_ante=(
                nn.functional.softplus(
                    self.endless_ante_head(action_context).squeeze(-1)
                )
                + self.calibration.endless_ante_bias
            ).clamp_min(0.0),
            log_score=(
                nn.functional.softplus(self.log_score_head(action_context).squeeze(-1))
                + self.calibration.log_score_bias
            ).clamp_min(0.0),
        )
        tensors = (
            result.policy_logits,
            result.current_blind_survival,
            result.next_boss_survival,
            result.ante8_win,
            result.endless_ante,
            result.log_score,
        )
        if not all(torch.isfinite(value).all() for value in tensors):
            raise StrategyModelError("strategy model produced a non-finite output")
        return result


def _features() -> list[float]:
    values = [0.0] * ENTITY_FEATURE_DIM
    values[_FEATURE_INDEX["bias"]] = 1.0
    return values


def _put(features: list[float], name: str, value: float) -> None:
    if not math.isfinite(value):
        raise StrategyModelError(f"public feature {name!r} is not finite")
    features[_FEATURE_INDEX[name]] = value


def _put_scaled(
    features: list[float], name: str, value: int | float, scale: float
) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise StrategyModelError(f"public feature {name!r} is not a finite number")
    if isinstance(value, float) and not math.isfinite(value):
        raise StrategyModelError(f"public feature {name!r} is not a finite number")
    if isinstance(value, int) and abs(value) > scale * 20:
        scaled = 1.0 if value > 0 else -1.0
    else:
        scaled = math.tanh(float(value) / scale)
    _put(features, name, scaled)


def _put_log_scaled(
    features: list[float],
    name: str,
    value: int | float,
    exponent_scale: float,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise StrategyModelError(f"public feature {name!r} is not a finite number")
    if isinstance(value, float) and not math.isfinite(value):
        raise StrategyModelError(f"public feature {name!r} is not a finite number")
    if value == 0:
        encoded = 0.0
    else:
        absolute = abs(value)
        exponent = math.log10(absolute) if absolute > 1 else math.log10(1 + absolute)
        signed_exponent = exponent if value > 0 else -exponent
        encoded = math.tanh(signed_exponent / exponent_scale)
    _put(features, name, encoded)


def _put_category(
    features: list[float], prefix: str, value: str, admitted: tuple[str, ...]
) -> None:
    if value not in admitted:
        raise StrategyModelError(f"unsupported {prefix} value {value!r}")
    _put(features, f"{prefix}:{value}", 1.0)


def _entity(
    kind: EntityKind,
    identity: str,
    features: list[float],
    position: int,
    size: int,
    *,
    retention_priority: tuple[int, int] = (0, 0),
) -> _Entity:
    identity_id = _IDENTITY_TO_ID.get(identity)
    if identity_id is None:
        raise StrategyModelError(f"unsupported public identity {identity!r}")
    _put_scaled(features, "position", position, max(1, size - 1))
    _put_scaled(features, "zone_size", size, 64)
    return _Entity(kind, identity_id, tuple(features), retention_priority)


def _deck_retention_priority(
    card: VisiblePlayingCard,
    count: int,
) -> tuple[int, int]:
    """Keep rare public payloads used by known high-ceiling routes."""

    route_salience = sum(
        (
            4 if card.seal == "RED" else 0,
            3 if card.enhancement in {"STEEL", "GLASS"} else 0,
            2 if card.rank == "K" else 0,
            2 if card.seal == "BLUE" else 0,
            1 if card.enhancement in {"GOLD", "WILD"} else 0,
            1 if card.edition in {"FOIL", "HOLOGRAPHIC", "POLYCHROME"} else 0,
        )
    )
    return route_salience, count


def _card_features(features: list[float], card: VisiblePlayingCard) -> None:
    _put_category(features, "rank", card.rank, _RANKS)
    _put_category(features, "suit", card.suit, _SUITS)
    if card.enhancement is not None:
        _put_category(features, "enhancement", card.enhancement, _ENHANCEMENTS)
    if card.edition is not None:
        _put_category(features, "edition", card.edition, _EDITIONS)
    if card.seal is not None:
        _put_category(features, "seal", card.seal, _SEALS)
    _put(features, "debuffed", float(card.debuffed))
    _put_scaled(features, "permanent_bonus", card.permanent_bonus, 1_000)


def _booster_identity(key: str) -> str:
    matches = [
        identity
        for identity, admitted_keys in _BOOSTER_KEYS_BY_IDENTITY.items()
        if key in admitted_keys
    ]
    if len(matches) != 1:
        raise StrategyModelError(f"unsupported public booster {key!r}")
    return matches[0]


def _normalize_provenance(provenance: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(provenance, Mapping):
        raise ValueError("strategy provenance must be a JSON-safe mapping")

    def normalize(value: object, path: str) -> object:
        if value is None or isinstance(value, str | bool | int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"strategy provenance {path} must be finite")
            return value
        if isinstance(value, list):
            return [normalize(item, f"{path}[]") for item in value]
        if isinstance(value, Mapping):
            if not all(isinstance(key, str) for key in value):
                raise ValueError(f"strategy provenance {path} keys must be strings")
            return {
                key: normalize(item, f"{path}.{key}") for key, item in value.items()
            }
        raise ValueError(f"strategy provenance {path} is not exactly JSON-safe")

    normalized = normalize(provenance, "root")
    if not isinstance(normalized, dict):  # pragma: no cover - outer guard
        raise AssertionError("normalized provenance is not a dictionary")
    status = normalized.get("training_status")
    if status == "untrained":
        if normalized != UNTRAINED_PROVENANCE:
            raise ValueError("untrained provenance must be the exact marker")
    elif status != "trained":
        raise ValueError("strategy provenance needs a trained or untrained status")
    else:
        _validate_trained_provenance(normalized)
    # A JSON round trip is a final guard against permissive Mapping subclasses.
    try:
        if json.loads(json.dumps(normalized, allow_nan=False)) != normalized:
            raise ValueError("strategy provenance does not round trip exactly")
    except (TypeError, ValueError) as exc:
        raise ValueError("strategy provenance is not exactly JSON-safe") from exc
    return normalized


def _validate_trained_provenance(provenance: dict[str, object]) -> None:
    if set(provenance) != _TRAINED_PROVENANCE_FIELDS:
        raise ValueError("trained provenance fields are invalid")
    if provenance["influence_mode"] not in {"diagnostic", "shadow", "leaf"}:
        raise ValueError("trained provenance influence mode is invalid")
    for key in (
        "dataset_sha256",
        "collection_report_sha256",
        "teacher_config_digest",
        "strategy_model_schema_digest",
    ):
        value = provenance[key]
        if not isinstance(value, str) or _HEX_DIGEST.fullmatch(value) is None:
            raise ValueError(f"trained provenance {key} must be SHA-256")

    split = provenance["split"]
    split_fields = {
        "train_groups",
        "calibration_groups",
        "holdout_groups",
        "train_digest",
        "calibration_digest",
        "holdout_digest",
    }
    if not isinstance(split, dict) or set(split) != split_fields:
        raise ValueError("trained provenance split fields are invalid")
    group_sets: list[set[str]] = []
    for name in ("train_groups", "calibration_groups", "holdout_groups"):
        groups = split[name]
        if (
            not isinstance(groups, list)
            or not groups
            or not all(
                isinstance(group, str) and re.fullmatch(r"origin-[0-9a-f]{32}", group)
                for group in groups
            )
            or len(set(groups)) != len(groups)
        ):
            raise ValueError("trained provenance contains invalid run groups")
        group_sets.append(set(groups))
    if any(
        group_sets[left] & group_sets[right] for left, right in ((0, 1), (0, 2), (1, 2))
    ):
        raise ValueError("trained provenance run groups overlap")
    for name in ("train_digest", "calibration_digest", "holdout_digest"):
        digest = split[name]
        if not isinstance(digest, str) or _HEX_DIGEST.fullmatch(digest) is None:
            raise ValueError("trained provenance split digest is invalid")
    for group_name, digest_name in (
        ("train_groups", "train_digest"),
        ("calibration_groups", "calibration_digest"),
        ("holdout_groups", "holdout_digest"),
    ):
        expected = hashlib.sha256(
            "\n".join(sorted(split[group_name])).encode()
        ).hexdigest()
        if split[digest_name] != expected:
            raise ValueError("trained provenance split digest disagrees with groups")

    trainer = provenance["trainer"]
    trainer_fields = {
        "training_seed",
        "split_nonce",
        "epochs",
        "learning_rate",
        "weight_decay",
        "max_gradient_norm",
        "device",
        "python_version",
        "torch_version",
        "source_digest",
        "loss_weights",
        "objective",
    }
    if not isinstance(trainer, dict) or set(trainer) != trainer_fields:
        raise ValueError("trained provenance trainer fields are invalid")
    if (
        isinstance(trainer["training_seed"], bool)
        or not isinstance(trainer["training_seed"], int)
        or isinstance(trainer["epochs"], bool)
        or not isinstance(trainer["epochs"], int)
        or trainer["epochs"] <= 0
        or not isinstance(trainer["split_nonce"], str)
        or not trainer["split_nonce"]
        or not isinstance(trainer["device"], str)
        or not trainer["device"]
        or not isinstance(trainer["python_version"], str)
        or not trainer["python_version"]
        or not isinstance(trainer["torch_version"], str)
        or not trainer["torch_version"]
        or not isinstance(trainer["source_digest"], str)
        or _HEX_DIGEST.fullmatch(trainer["source_digest"]) is None
    ):
        raise ValueError("trained provenance trainer values are invalid")
    for name in ("learning_rate", "weight_decay", "max_gradient_norm"):
        value = trainer[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise ValueError("trained provenance optimizer values are invalid")
    weights = trainer["loss_weights"]
    if not isinstance(weights, dict) or set(weights) != {
        "policy",
        "paired_utility",
        "ordering",
        "current_blind",
        "next_boss",
        "ante8",
        "endless_ante",
        "log_score",
    }:
        raise ValueError("trained provenance loss weights are invalid")
    if trainer["objective"] != {
        "name": "paired_baseline_relative_search_utility_v1",
        "regression": "smooth_l1",
        "ordering": "signed_softplus;exact_ties=squared_delta",
        "weighting": "run_then_decision_then_alternative_equal",
    }:
        raise ValueError("trained provenance objective is invalid")

    calibration = provenance["calibration"]
    if not isinstance(calibration, dict) or set(calibration) != {
        "parameters",
        "metrics",
        "holdout_metrics",
        "empirical_baseline_metrics",
        "gate",
    }:
        raise ValueError("trained provenance calibration fields are invalid")
    if not all(
        isinstance(calibration[name], dict)
        for name in (
            "parameters",
            "metrics",
            "holdout_metrics",
            "empirical_baseline_metrics",
            "gate",
        )
    ):
        raise ValueError("trained provenance calibration values are invalid")
    _validate_metric_bundle(calibration["metrics"], calibration=True)
    _validate_metric_bundle(calibration["holdout_metrics"], calibration=False)
    _validate_baseline_metrics(calibration["empirical_baseline_metrics"])
    gate = calibration["gate"]
    gate_fields = {
        "safe_policy_recommendations",
        "positive_recommendation_coverage",
        "policy_agreement_beats_baseline",
        "zero_recommendation_errors",
        "zero_false_tie_overrides",
        "non_positive_recommendation_regret",
        "positive_recommended_utility_gain",
        "head_improvements",
        "all_heads_beat_train_only_baselines",
        "offline_gate_passed",
        "authorizes_action_influence",
    }
    if not isinstance(gate, dict) or set(gate) != gate_fields:
        raise ValueError("trained provenance calibration gate is invalid")
    head_improvements = gate["head_improvements"]
    if not isinstance(head_improvements, dict) or set(head_improvements) != {
        "current_blind",
        "next_boss",
        "ante8",
        "endless_ante",
        "log_score",
    }:
        raise ValueError("trained provenance head gate is invalid")
    boolean_values = (
        gate["safe_policy_recommendations"],
        gate["positive_recommendation_coverage"],
        gate["policy_agreement_beats_baseline"],
        gate["zero_recommendation_errors"],
        gate["zero_false_tie_overrides"],
        gate["non_positive_recommendation_regret"],
        gate["positive_recommended_utility_gain"],
        gate["all_heads_beat_train_only_baselines"],
        gate["offline_gate_passed"],
        gate["authorizes_action_influence"],
        *head_improvements.values(),
    )
    if not all(isinstance(value, bool) for value in boolean_values):
        raise ValueError("trained provenance gate values must be boolean")
    expected_all_heads = all(head_improvements.values())
    holdout = calibration["holdout_metrics"]
    baseline = calibration["empirical_baseline_metrics"]
    policy = holdout["policy"]
    baseline_policy = baseline["policy"]
    expected_coverage = policy["recommendations"] > 0
    expected_policy_improvement = policy["agreement"] > baseline_policy["agreement"]
    expected_zero_errors = policy["recommendation_errors"] == 0
    expected_zero_false_ties = policy["false_tie_overrides"] == 0
    expected_non_positive_regret = policy["mean_recommendation_regret"] <= 0.0
    expected_positive_utility = policy["mean_recommended_utility_gain"] > 0.0
    expected_head_improvements = {
        name: holdout[name]["count"] > 0
        and holdout[name][
            "brier" if name in {"current_blind", "next_boss", "ante8"} else "mae"
        ]
        < baseline[name][
            "brier" if name in {"current_blind", "next_boss", "ante8"} else "mae"
        ]
        for name in head_improvements
    }
    expected_safe_policy = (
        expected_coverage
        and expected_zero_errors
        and expected_zero_false_ties
        and expected_non_positive_regret
        and expected_positive_utility
    )
    expected_offline = gate["safe_policy_recommendations"]
    if (
        head_improvements != expected_head_improvements
        or gate["positive_recommendation_coverage"] != expected_coverage
        or gate["policy_agreement_beats_baseline"] != expected_policy_improvement
        or gate["zero_recommendation_errors"] != expected_zero_errors
        or gate["zero_false_tie_overrides"] != expected_zero_false_ties
        or gate["non_positive_recommendation_regret"] != expected_non_positive_regret
        or gate["positive_recommended_utility_gain"] != expected_positive_utility
        or expected_all_heads != all(expected_head_improvements.values())
        or gate["safe_policy_recommendations"] != expected_safe_policy
        or gate["all_heads_beat_train_only_baselines"] != expected_all_heads
        or gate["offline_gate_passed"] != expected_offline
        or gate["authorizes_action_influence"] is not False
    ):
        raise ValueError("trained provenance calibration gate is inconsistent")


def _validate_metric_bundle(bundle: dict[str, object], *, calibration: bool) -> None:
    fields = {
        "records",
        "groups",
        "weighting",
        "policy",
        "current_blind",
        "next_boss",
        "ante8",
        "endless_ante",
        "log_score",
        "strata",
    }
    if calibration:
        fields.add("error_radii")
    if (
        set(bundle) != fields
        or bundle["weighting"] != "inverse_eligible_targets_per_run_and_head"
    ):
        raise ValueError("trained provenance metric bundle is invalid")
    if not _nonnegative_integer(bundle["records"]) or not _nonnegative_integer(
        bundle["groups"]
    ):
        raise ValueError("trained provenance metric counts are invalid")
    _validate_policy_metrics(bundle["policy"])
    for name in ("current_blind", "next_boss", "ante8"):
        _validate_head_metrics(bundle[name], ("count", "brier", "log_loss"))
    for name in ("endless_ante", "log_score"):
        _validate_head_metrics(bundle[name], ("count", "mae", "rmse"))
    strata = bundle["strata"]
    if not isinstance(strata, dict):
        raise ValueError("trained provenance metric strata are invalid")
    for value in strata.values():
        if (
            not isinstance(value, dict)
            or set(value) != {"records", "teacher_selection_rate"}
            or not _nonnegative_integer(value["records"])
            or not _finite_number(value["teacher_selection_rate"])
            or not 0 <= value["teacher_selection_rate"] <= 1
        ):
            raise ValueError("trained provenance metric stratum is invalid")
    if calibration:
        radii = bundle["error_radii"]
        if (
            not isinstance(radii, dict)
            or set(radii)
            != {
                "current_blind",
                "next_boss",
                "ante8",
                "endless_ante",
                "log_score",
            }
            or not all(_finite_number(value) and value >= 0 for value in radii.values())
        ):
            raise ValueError("trained provenance calibration radii are invalid")


def _validate_baseline_metrics(bundle: dict[str, object]) -> None:
    if (
        set(bundle)
        != {
            "weighting",
            "policy",
            "current_blind",
            "next_boss",
            "ante8",
            "endless_ante",
            "log_score",
        }
        or bundle["weighting"] != "inverse_eligible_targets_per_run_and_head"
    ):
        raise ValueError("trained provenance baseline metrics are invalid")
    policy = bundle["policy"]
    if (
        not isinstance(policy, dict)
        or set(policy) != {"agreement"}
        or not _finite_number(policy["agreement"])
        or not 0 <= policy["agreement"] <= 1
    ):
        raise ValueError("trained provenance baseline policy metric is invalid")
    for name in ("current_blind", "next_boss", "ante8"):
        _validate_head_metrics(bundle[name], ("count", "brier", "log_loss"))
    for name in ("endless_ante", "log_score"):
        _validate_head_metrics(bundle[name], ("count", "mae", "rmse"))


def _validate_policy_metrics(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "agreement",
        "recommendations",
        "recommendation_groups",
        "recommendation_errors",
        "false_tie_overrides",
        "mean_recommended_utility_gain",
        "mean_recommendation_regret",
        "override_margin",
    }:
        raise ValueError("trained provenance policy metrics are invalid")
    if (
        not _finite_number(value["agreement"])
        or not 0 <= value["agreement"] <= 1
        or not _nonnegative_integer(value["recommendations"])
        or not _nonnegative_integer(value["recommendation_groups"])
        or value["recommendation_groups"] > value["recommendations"]
        or not _nonnegative_integer(value["recommendation_errors"])
        or not _nonnegative_integer(value["false_tie_overrides"])
        or value["recommendation_errors"] > value["recommendations"]
        or value["false_tie_overrides"] > value["recommendations"]
        or not _finite_number(value["mean_recommended_utility_gain"])
        or not _finite_number(value["mean_recommendation_regret"])
        or value["mean_recommendation_regret"] < 0
        or not _finite_number(value["override_margin"])
        or value["override_margin"] < 0
    ):
        raise ValueError("trained provenance policy metric values are invalid")


def _validate_head_metrics(value: object, fields: tuple[str, ...]) -> None:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("trained provenance head metrics are invalid")
    if not all(_finite_number(value[field]) and value[field] >= 0 for field in fields):
        raise ValueError("trained provenance head metric values are invalid")


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_checkpoint_state(state_dict: Mapping[str, object]) -> None:
    if not state_dict or not all(isinstance(key, str) for key in state_dict):
        raise ValueError(
            "strategy checkpoint state must be a non-empty string-keyed mapping"
        )
    for key, value in state_dict.items():
        if not isinstance(value, Tensor):
            raise ValueError(f"strategy checkpoint parameter {key!r} is not a tensor")
        if (value.is_floating_point() or value.is_complex()) and not torch.isfinite(
            value
        ).all():
            raise ValueError(f"strategy checkpoint parameter {key!r} is not finite")


def save_strategy_model(path: Path, model: RelationalStrategyPolicyValue) -> str:
    """Write a new immutable checkpoint and return its SHA-256 digest."""

    state_dict = model.state_dict()
    _validate_checkpoint_state(state_dict)
    payload = {
        "format_version": STRATEGY_MODEL_FORMAT_VERSION,
        "schema_digest": STRATEGY_MODEL_SCHEMA_DIGEST,
        "config": asdict(model.config),
        "calibration": asdict(model.calibration),
        "provenance": _normalize_provenance(model.provenance),
        "state_dict": state_dict,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            torch.save(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_strategy_model(
    path: Path,
    *,
    device: torch.device | str = "cpu",
) -> RelationalStrategyPolicyValue:
    """Load only the exact current strategy checkpoint contract."""

    try:
        payload = torch.load(path, map_location=device, weights_only=True)
    except (OSError, RuntimeError, EOFError, ValueError) as exc:
        raise StrategyModelError(
            f"cannot load strategy model checkpoint: {exc}"
        ) from exc
    required = {
        "format_version",
        "schema_digest",
        "config",
        "calibration",
        "provenance",
        "state_dict",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise StrategyModelError("strategy model checkpoint fields are invalid")
    if (
        type(payload["format_version"]) is not int
        or payload["format_version"] != STRATEGY_MODEL_FORMAT_VERSION
        or not isinstance(payload["schema_digest"], str)
        or payload["schema_digest"] != STRATEGY_MODEL_SCHEMA_DIGEST
        or not isinstance(payload["config"], dict)
        or not isinstance(payload["calibration"], dict)
        or not isinstance(payload["provenance"], dict)
        or not isinstance(payload["state_dict"], dict)
    ):
        raise StrategyModelError(
            "strategy model checkpoint version or payload is invalid"
        )
    try:
        config_fields = {field.name for field in fields(StrategyModelConfig)}
        calibration_fields = {field.name for field in fields(StrategyCalibration)}
        if set(payload["config"]) != config_fields:
            raise ValueError("strategy model config fields are invalid")
        if set(payload["calibration"]) != calibration_fields:
            raise ValueError("strategy calibration fields are invalid")
        config = StrategyModelConfig(**payload["config"])
        calibration = StrategyCalibration(**payload["calibration"])
        provenance = _normalize_provenance(payload["provenance"])
        _validate_checkpoint_state(payload["state_dict"])
        model = RelationalStrategyPolicyValue(config, calibration, provenance).to(
            device
        )
        model.load_state_dict(payload["state_dict"], strict=True)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise StrategyModelError(
            f"strategy model checkpoint is incompatible: {exc}"
        ) from exc
    return model


def _reorder_relations(relate, zone: str, order: tuple[object, ...]) -> None:
    size = len(order)
    for new_position, slot in enumerate(order):
        old_position = getattr(slot, "value", None)
        if not isinstance(old_position, int):
            raise StrategyModelError("reorder action contains an unsupported slot")
        relate(
            zone,
            old_position,
            (old_position + 1) / max(1, size),
            (new_position + 1) / max(1, size),
        )


__all__ = [
    "ACTION_RELATION_DIM",
    "ENTITY_FEATURE_DIM",
    "ENTITY_RELATION_DIM",
    "RELATION_BRAINSTORM",
    "RELATION_BLUEPRINT",
    "RELATION_PRESENT",
    "RELATION_PUBLICLY_ENABLED",
    "STRATEGY_MODEL_FORMAT_VERSION",
    "STRATEGY_MODEL_SCHEMA_DIGEST",
    "ActionKind",
    "EntityKind",
    "PublicStrategyTensorizer",
    "RelationalStrategyPolicyValue",
    "StrategyCalibration",
    "StrategyModelConfig",
    "StrategyModelError",
    "StrategyModelOutput",
    "StrategyTensorBatch",
    "load_strategy_model",
    "save_strategy_model",
]
