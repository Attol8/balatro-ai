"""Determinize the candidate's private state for evaluator-parent search.

This module is parent-only.  It imports Jackdaw and touches private game
state, so it must never be importable from the policy child, the
continuation policy, or any model.  Its only sanctioned consumers return
per-root scalar values and aggregate diagnostics to the decision.

A determinization is a concrete Jackdaw game state whose public projection
equals the current ``PublicObservation`` and whose hidden parts are drawn
from policy-owned randomness:

* the run seed and every RNG stream are replaced by ``PseudoRandom(sample_seed)``;
* the draw pile is reshuffled with the fresh RNG;
* the ante voucher is re-rolled unless it is already public;
* discard and play piles are put in canonical order because their order is
  never observable and never affects play.

Anything hidden that cannot be resampled fails closed: face-down hand cards
and partially visible packs make the state unavailable.  Every sample is
verified by round trip: the scrubbed state's public projection must equal
the input observation exactly.
"""

from __future__ import annotations

import enum
import hashlib
import json
import pickle
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

from balatro_ai_v2.backend import AuthorityObservation
from balatro_ai_v2.jackdaw import JackdawBackend
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.public_state import HiddenHandCard, Phase, PublicObservation


class DeterminizationUnavailable(RuntimeError):
    """The public observation does not admit a sound determinization."""


STRATEGIC_PHASES = frozenset({Phase.BLIND_SELECT, Phase.SHOP, Phase.PACK})
SUPPORTED_PHASES = STRATEGIC_PHASES | {Phase.SELECTING_HAND}

_SAMPLE_SEED_STREAM = "determinize_shuffle"
_SCALAR_BRIDGE_FIELDS = (
    "_round_targets_rolled",
    "_pending_ante_setup",
    "_poker_hand_iteration_order",
    "_pack_card_limit",
    "_won",
    "_pending_skip_dollars",
)


@dataclass(frozen=True, slots=True)
class FrozenJackdawBackend:
    """One immutable serialization that can load independent backend clones."""

    _payload: bytes = field(repr=False)
    _current: AuthorityObservation | None = field(repr=False)
    current_public: PublicObservation | None

    def clone(self) -> JackdawBackend:
        """Load a fresh backend with the exact state captured by this snapshot."""

        clone: JackdawBackend | None = None
        try:
            (
                game_state,
                active_pack_cards,
                stale_shop_areas,
                scalar_bridge_values,
            ) = pickle.loads(self._payload)
            clone = JackdawBackend(lightweight=True)
            clone._backend._gs = game_state
            clone._active_pack_cards = active_pack_cards
            clone._stale_shop_areas = stale_shop_areas
            for name, value in zip(
                _SCALAR_BRIDGE_FIELDS, scalar_bridge_values, strict=True
            ):
                setattr(clone, name, value)
        except Exception as exc:
            if clone is not None:
                clone.close()
            raise DeterminizationUnavailable(
                f"frozen backend clone failed: {type(exc).__name__}"
            ) from exc
        # These observations are frozen values. Sharing them matches the legacy
        # clone contract while every mutable simulator object is deserialized.
        assert clone is not None
        clone._current = self._current
        clone.current_public = self.current_public
        return clone


def sample_seed(observation: PublicObservation, nonce: str, index: int) -> str:
    """Policy-owned sample seed: a function of public digest, nonce, and index only."""

    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("sample index must be a non-negative integer")
    material = f"{nonce}|{observation.digest()}|{index}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16].upper()


def freeze_backend(backend: JackdawBackend) -> FrozenJackdawBackend:
    """Serialize a candidate and its compatibility bridge exactly once."""

    source_state = getattr(backend._backend, "_gs", None)
    if not isinstance(source_state, dict):
        raise DeterminizationUnavailable(
            "Jackdaw backend has no active game state to clone"
        )
    # Keep one object graph so references shared by the game state and bridge
    # areas survive each load. Bytes plus the frozen wrapper cannot be mutated
    # by a rollout before another independent clone is requested.
    try:
        payload = pickle.dumps(
            (
                source_state,
                backend._active_pack_cards,
                backend._stale_shop_areas,
                tuple(getattr(backend, name) for name in _SCALAR_BRIDGE_FIELDS),
            ),
            protocol=pickle.HIGHEST_PROTOCOL,
        )
    except Exception as exc:
        raise DeterminizationUnavailable(
            f"freezing backend failed: {type(exc).__name__}"
        ) from exc
    return FrozenJackdawBackend(payload, backend._current, backend.current_public)


def clone_backend(backend: JackdawBackend) -> JackdawBackend:
    """Deep-copy the candidate and its bridge compatibility state into a fresh backend."""

    return freeze_backend(backend).clone()


def sample_candidate(
    backend: JackdawBackend,
    observation: PublicObservation,
    history: Sequence[PublicHistoryStep],
    seed: str,
) -> JackdawBackend:
    """Return a scrubbed clone whose public projection equals ``observation``."""

    _require_supported(observation)
    clone = clone_backend(backend)
    try:
        game_state = clone._backend._gs
        if not isinstance(game_state, dict):
            raise RuntimeError("cloned Jackdaw backend lost its game state")
        _require_visible_private_state(game_state)
        scrub_game_state(
            game_state,
            seed,
            voucher_public=_voucher_is_public(observation, history),
        )
        clone._current = clone.observe()
        projected = clone.current_public
        if projected != observation:
            raise DeterminizationUnavailable(
                "scrubbed state does not round-trip to the public observation"
            )
        return clone
    except Exception:
        clone.close()
        raise


def scrub_game_state(game_state: dict[str, Any], seed: str, *, voucher_public: bool) -> None:
    """Replace every hidden component of ``game_state`` with a sample from ``seed``."""

    from jackdaw.engine.rng import PseudoRandom
    from jackdaw.engine.vouchers import get_next_voucher_key

    rng = PseudoRandom(seed)
    game_state["seed"] = seed
    game_state["rng"] = rng
    deck = game_state.get("deck")
    if not isinstance(deck, list):
        raise DeterminizationUnavailable("game state has no draw pile")
    rng.shuffle(deck, rng.seed(_SAMPLE_SEED_STREAM))
    for pile_name in ("discard_pile", "played_cards_area"):
        pile = game_state.get(pile_name)
        if isinstance(pile, list):
            pile.sort(key=_card_canonical_key)
    if not voucher_public:
        current_round = game_state.setdefault("current_round", {})
        used = {key: True for key in game_state.get("used_vouchers", {})}
        ante = int(game_state.get("round_resets", {}).get("ante", 1))
        current_round["voucher"] = get_next_voucher_key(rng, used, in_shop=None, ante=ante)


def canonical_private_state(game_state: Mapping[str, Any]) -> str:
    """Canonical JSON of a private state with object identities normalized.

    Test helper for the twin property: two private states with identical
    public projections must scrub to identical canonical strings.
    """

    sort_ids = sorted({card.sort_id for card in _iter_cards(game_state)})
    ranks = {sort_id: index for index, sort_id in enumerate(sort_ids)}
    return json.dumps(_canonical(game_state, ranks), sort_keys=True, separators=(",", ":"))


def _require_supported(observation: PublicObservation) -> None:
    if observation.phase not in SUPPORTED_PHASES:
        raise DeterminizationUnavailable(f"phase {observation.phase.value} is not determinizable")
    if any(isinstance(card, HiddenHandCard) for card in observation.hand):
        raise DeterminizationUnavailable("face-down hand cards cannot be resampled soundly")


def _require_visible_private_state(game_state: Mapping[str, Any]) -> None:
    for area_name in ("hand", "jokers", "consumables", "shop_cards", "shop_vouchers", "shop_boosters", "pack_cards"):
        for card in game_state.get(area_name, ()) or ():
            if getattr(card, "facing", "front") != "front":
                raise DeterminizationUnavailable(f"{area_name} contains a face-down card")


def _voucher_is_public(observation: PublicObservation, history: Sequence[PublicHistoryStep]) -> bool:
    if observation.phase == Phase.SHOP:
        return True
    for step in history:
        for seen in (step.before, step.after):
            if seen.phase == Phase.SHOP and seen.ante == observation.ante:
                return True
    return False


def _card_canonical_key(card: Any) -> tuple[object, ...]:
    base = getattr(card, "base", None)
    return (
        str(getattr(card, "center_key", "")),
        str(getattr(card, "card_key", "") or ""),
        str(getattr(base, "suit", "") if base is not None else ""),
        str(getattr(base, "value", "") if base is not None else ""),
        json.dumps(getattr(card, "edition", None), sort_keys=True),
        str(getattr(card, "seal", None)),
        json.dumps(_canonical(getattr(card, "ability", {}), {}), sort_keys=True),
        int(getattr(card, "sort_id", 0)),
    )


def _iter_cards(value: Any):
    from jackdaw.engine.card import Card

    seen: set[int] = set()
    stack = [value]
    while stack:
        item = stack.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, Card):
            yield item
            stack.append(item.ability)
        elif isinstance(item, Mapping):
            stack.extend(item.values())
        elif isinstance(item, (list, tuple, set, frozenset)):
            stack.extend(item)
        elif is_dataclass(item) and not isinstance(item, type):
            stack.extend(getattr(item, field.name) for field in fields(item))
        elif hasattr(item, "__slots__") or hasattr(item, "__dict__"):
            if type(item).__module__.startswith("jackdaw"):
                stack.extend(_object_attributes(item).values())


def _object_attributes(item: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for cls in type(item).__mro__:
        for name in getattr(cls, "__slots__", ()):
            if hasattr(item, name):
                result[name] = getattr(item, name)
    result.update(getattr(item, "__dict__", {}))
    return result


def _canonical(value: Any, ranks: Mapping[int, int]) -> Any:
    from jackdaw.engine.card import Card
    from jackdaw.engine.rng import PseudoRandom

    if isinstance(value, Card):
        data = {name: _canonical(item, ranks) for name, item in _object_attributes(value).items()}
        data["sort_id"] = ranks.get(value.sort_id, -1)
        return data
    if isinstance(value, PseudoRandom):
        return {"rng": _canonical(value.get_state(), ranks)}
    if isinstance(value, enum.Enum):
        return str(value.value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(item, ranks) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item, ranks) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(json.dumps(_canonical(item, ranks), sort_keys=True) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _canonical(getattr(value, field.name), ranks) for field in fields(value)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if type(value).__module__.startswith("jackdaw"):
        return {name: _canonical(item, ranks) for name, item in _object_attributes(value).items()}
    return repr(value)
