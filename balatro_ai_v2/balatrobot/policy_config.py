from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class TacticalPolicyConfig:
    beam_width: int = 96
    action_beam: int = 48


@dataclass(frozen=True, slots=True)
class ShopPolicyConfig:
    min_value_margin: float = 0.0
    modeled_joker_fallback_value: float = 10.0
    valuable_no_target_consumable_value: float = 16.0
    high_priestess_min_money: int = 14
    planet_played_base_value: float = 18.0
    planet_played_increment: float = 6.0
    planet_common_unplayed_value: float = 12.0
    planet_unplayed_value: float = 4.0
    joker_value_overrides: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    tactical: TacticalPolicyConfig = field(default_factory=TacticalPolicyConfig)
    shop: ShopPolicyConfig = field(default_factory=ShopPolicyConfig)


DEFAULT_POLICY_CONFIG = PolicyConfig()


def load_policy_config(path: str | Path | None) -> PolicyConfig:
    if path is None:
        return DEFAULT_POLICY_CONFIG
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError("policy config must be a JSON object")
    return policy_config_from_dict(data)


def policy_config_from_dict(data: dict[str, Any]) -> PolicyConfig:
    tactical_data = _object(data.get("tactical"))
    shop_data = _object(data.get("shop"))
    overrides = shop_data.get("joker_value_overrides", ())
    if isinstance(overrides, dict):
        overrides = tuple((str(key), float(value)) for key, value in overrides.items())
    elif isinstance(overrides, list):
        overrides = tuple((str(key), float(value)) for key, value in overrides)
    elif overrides in (None, ()):
        overrides = ()
    else:
        raise ValueError("shop.joker_value_overrides must be an object or list of pairs")

    return PolicyConfig(
        tactical=TacticalPolicyConfig(
            beam_width=int(tactical_data.get("beam_width", TacticalPolicyConfig.beam_width)),
            action_beam=int(tactical_data.get("action_beam", TacticalPolicyConfig.action_beam)),
        ),
        shop=ShopPolicyConfig(
            min_value_margin=float(shop_data.get("min_value_margin", ShopPolicyConfig.min_value_margin)),
            modeled_joker_fallback_value=float(
                shop_data.get("modeled_joker_fallback_value", ShopPolicyConfig.modeled_joker_fallback_value)
            ),
            valuable_no_target_consumable_value=float(
                shop_data.get(
                    "valuable_no_target_consumable_value",
                    ShopPolicyConfig.valuable_no_target_consumable_value,
                )
            ),
            high_priestess_min_money=int(
                shop_data.get("high_priestess_min_money", ShopPolicyConfig.high_priestess_min_money)
            ),
            planet_played_base_value=float(
                shop_data.get("planet_played_base_value", ShopPolicyConfig.planet_played_base_value)
            ),
            planet_played_increment=float(
                shop_data.get("planet_played_increment", ShopPolicyConfig.planet_played_increment)
            ),
            planet_common_unplayed_value=float(
                shop_data.get("planet_common_unplayed_value", ShopPolicyConfig.planet_common_unplayed_value)
            ),
            planet_unplayed_value=float(shop_data.get("planet_unplayed_value", ShopPolicyConfig.planet_unplayed_value)),
            joker_value_overrides=overrides,
        ),
    )


def _object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("policy config sections must be JSON objects")
    return value
