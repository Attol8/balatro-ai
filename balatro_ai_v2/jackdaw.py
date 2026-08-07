"""Pinned Jackdaw candidate backend.

Jackdaw is a fast candidate, never an authority.  The import is lazy so the
authority-only project remains dependency-free on Python 3.11; candidate work
uses Python 3.12 and the pinned optional dependency.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from types import MethodType
from typing import Any

from balatro_ai_v2.actions import PublicAction
from balatro_ai_v2.backend import (
    AuthorityObservation,
    BackendCapabilities,
    BackendMetadata,
    RunSpec,
    StepResult,
)
from balatro_ai_v2.balatrobot.adapter import action_to_rpc, to_public_observation
from balatro_ai_v2.canonical import BalatroBotCanonicalizer


JACKDAW_REVISION = "dbedc66255fe594cce7b7cccc188c8a11649d9ec"

_SECRET_HANDS = {
    "Flush Five": {"order": 1, "level": 1, "chips": 160, "mult": 16, "played": 0, "played_this_round": 0},
    "Flush House": {"order": 2, "level": 1, "chips": 140, "mult": 14, "played": 0, "played_this_round": 0},
    "Five of a Kind": {"order": 3, "level": 1, "chips": 120, "mult": 12, "played": 0, "played_this_round": 0},
}
_SUIT_LETTER = {"Spades": "S", "Hearts": "H", "Clubs": "C", "Diamonds": "D"}
_OPTIONAL_AREAS = {"shop", "vouchers", "packs", "pack"}
_PRIVATE_AREA_KEYS = {
    "cards": "deck",
    "hand": "hand",
    "jokers": "jokers",
    "consumables": "consumables",
    "shop": "shop_cards",
    "vouchers": "shop_vouchers",
    "packs": "shop_boosters",
    "pack": "pack_cards",
}
_PACK_STATES = {
    "Arcana": "TAROT_PACK",
    "Celestial": "PLANET_PACK",
    "Spectral": "SPECTRAL_PACK",
    "Standard": "STANDARD_PACK",
    "Buffoon": "BUFFOON_PACK",
}


class JackdawUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class JackdawBackend:
    canonicalizer: BalatroBotCanonicalizer = field(default_factory=BalatroBotCanonicalizer)
    metadata: BackendMetadata = field(init=False)
    _backend: Any = field(init=False, repr=False)
    _rpc_error: type[Exception] = field(init=False, repr=False)
    _current: AuthorityObservation | None = field(default=None, init=False, repr=False)
    _round_targets_rolled: bool = field(default=False, init=False, repr=False)
    _global_tw_state: list[int] | None = field(default=None, init=False, repr=False)
    _stale_shop_areas: dict[str, dict[str, Any]] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        try:
            from jackdaw.bridge.backend import RPCError, SimBackend
        except ImportError as exc:
            raise JackdawUnavailable(
                "install the pinned 'candidate' extra under Python 3.12 to use Jackdaw"
            ) from exc
        self._backend = SimBackend()
        self._rpc_error = RPCError
        self.metadata = BackendMetadata(
            backend_name="Jackdaw",
            backend_version=f"0.1.0+{JACKDAW_REVISION}",
            adapter_version="1",
            game_version="Balatro-1.0.1o-model",
            runtime_version="Python",
            capabilities=BackendCapabilities(
                authoritative=False,
                complete_private_state=True,
                snapshot=False,
                restore=False,
                batch_rollout=False,
            ),
        )

    def reset(self, spec: RunSpec) -> AuthorityObservation:
        self.canonicalizer.reset()
        self._round_targets_rolled = False
        self._global_tw_state = None
        self._stale_shop_areas = None
        self._backend.handle("menu", {})
        raw = self._backend.handle(
            "start",
            {"deck": spec.deck, "stake": spec.stake, "seed": spec.seed or "DEFAULT"},
        )
        self._current = self._observation(raw)
        return self._current

    def observe(self) -> AuthorityObservation:
        self._current = self._observation(self._backend.handle("gamestate", {}))
        return self._current

    def step(self, action: PublicAction) -> StepResult:
        if self._current is None:
            raise RuntimeError("reset must be called before step")
        before = self._current
        raw_before = json.loads(before.observed.raw_json)
        method, params = action_to_rpc(action, to_public_observation(raw_before))
        if method == "next_round":
            self._stale_shop_areas = _empty_shop_areas(raw_before)
        try:
            if method == "cash_out" and self._round_targets_rolled:
                with self._cash_out_compatibility():
                    raw_after = self._backend.handle(method, params)
                self._finish_cash_out_compatibility()
                raw_after = self._backend.handle("gamestate", {})
                self._round_targets_rolled = False
                self._stale_shop_areas = None
            else:
                raw_after = self._backend.handle(method, params)
        except self._rpc_error as exc:
            return StepResult(
                status="rejected",
                action=action,
                before=before,
                rpc_method=method,
                rpc_params=params,
                rpc_observations=(),
                after=None,
                error=str(exc),
            )
        if method == "play" and raw_after.get("state") == "ROUND_EVAL":
            self._roll_round_targets()
            self._round_targets_rolled = True
            raw_after = self._backend.handle("gamestate", {})
        after = self._observation(raw_after)
        self._current = after
        return StepResult(
            status="accepted",
            action=action,
            before=before,
            rpc_method=method,
            rpc_params=params,
            rpc_observations=(after.observed.raw_json,),
            after=after,
        )

    def close(self) -> None:
        self._backend.handle("menu", {})
        self._current = None
        self._round_targets_rolled = False
        self._global_tw_state = None
        self._stale_shop_areas = None

    def _observation(self, raw: dict[str, Any]) -> AuthorityObservation:
        # Both adapters must pass independently.  The public conversion catches
        # leaks/unsupported shapes; canonicalization catches semantic drift.
        normalized = _normalize_jackdaw_bridge(
            raw,
            getattr(self._backend, "_gs", None),
            self._stale_shop_areas,
        )
        to_public_observation(normalized)
        observed = self.canonicalizer.canonicalize(normalized)
        return AuthorityObservation(observed=observed, settled=True, polls=(observed.raw_json,))

    def _roll_round_targets(self) -> None:
        from jackdaw.engine.round_lifecycle import reset_round_targets

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        rng = game_state.get("rng")
        round_resets = game_state.get("round_resets")
        if rng is None or not isinstance(round_resets, Mapping):
            raise RuntimeError("Jackdaw round-target state is incomplete")
        ante = int(round_resets.get("ante", 1))
        reset_round_targets(rng, ante, game_state)
        rng_state = getattr(rng, "state", None)
        if not isinstance(rng_state, Mapping):
            raise RuntimeError("Jackdaw RNG state is unavailable")
        self._global_tw_state = _tw_state_after_one_draw(rng, float(rng_state[f"cas{ante}"]))

    def _finish_cash_out_compatibility(self) -> None:
        """Apply vanilla's immediate public cash-out resets missing in Jackdaw."""

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        current_round = game_state.get("current_round")
        round_resets = game_state.get("round_resets")
        round_bonus = game_state.get("round_bonus")
        if not all(isinstance(item, Mapping) for item in (current_round, round_resets, round_bonus)):
            raise RuntimeError("Jackdaw cash-out state is incomplete")
        current_round["jokers_purchased"] = 0
        current_round["discards_left"] = max(
            0,
            int(round_resets["discards"]) + int(round_bonus["discards"]),
        )
        current_round["hands_left"] = max(
            1,
            int(round_resets["hands"]) + int(round_bonus["next_hands"]),
        )
        game_state["chips"] = 0

    @contextmanager
    def _cash_out_compatibility(self) -> Iterator[None]:
        """Match vanilla's target timing and unseeded first-Buffoon roll."""

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        rng = game_state.get("rng")
        if rng is None:
            raise RuntimeError("Jackdaw RNG state is unavailable")

        from jackdaw.engine import round_lifecycle, shop
        from jackdaw.engine.rng import _luajit_random, _luajit_random_int, _luajit_seed

        original_reset = round_lifecycle.reset_round_targets
        original_get_pack = shop.get_pack
        original_random = rng.random
        original_element = rng.element
        original_shuffle = rng.shuffle

        def tracked_random(_rng: object, key: object, min_val: int | None = None, max_val: int | None = None) -> object:
            result = original_random(key, min_val, max_val)
            numeric_seed = _numeric_seed_after_call(rng, key)
            state = _luajit_seed(numeric_seed)
            if min_val is not None and max_val is not None:
                _luajit_random_int(state, min_val, max_val)
            else:
                _luajit_random(state)
            self._global_tw_state = state
            return result

        def tracked_element(_rng: object, table: object, seed_value: float) -> object:
            result = original_element(table, seed_value)
            state = _luajit_seed(seed_value)
            _luajit_random(state)
            self._global_tw_state = state
            return result

        def tracked_shuffle(_rng: object, values: list[object], seed_value: float) -> None:
            original_shuffle(values, seed_value)
            state = _luajit_seed(seed_value)
            for upper in range(len(values), 1, -1):
                _luajit_random_int(state, 1, upper)
            self._global_tw_state = state

        def vanilla_get_pack(
            pack_rng: object,
            ante: int,
            key: str = "shop_pack",
            *,
            first_shop: bool = False,
            banned_keys: set[str] | None = None,
        ) -> str:
            banned = banned_keys or set()
            if first_shop and "p_buffoon_normal_1" not in banned:
                if self._global_tw_state is None:
                    raise RuntimeError("global LuaJIT RNG state is unavailable for first Buffoon pack")
                variant = _luajit_random_int(self._global_tw_state, 1, 2)
                return f"p_buffoon_normal_{variant}"
            return original_get_pack(
                pack_rng,
                ante,
                key,
                first_shop=first_shop,
                banned_keys=banned_keys,
            )

        round_lifecycle.reset_round_targets = lambda *_args, **_kwargs: None
        shop.get_pack = vanilla_get_pack
        rng.random = MethodType(tracked_random, rng)
        rng.element = MethodType(tracked_element, rng)
        rng.shuffle = MethodType(tracked_shuffle, rng)
        try:
            yield
        finally:
            round_lifecycle.reset_round_targets = original_reset
            shop.get_pack = original_get_pack
            del rng.random
            del rng.element
            del rng.shuffle


def _numeric_seed_after_call(rng: object, key: object) -> float:
    if isinstance(key, str):
        state = getattr(rng, "state", None)
        hashed_seed = getattr(rng, "hashed_seed", None)
        if not isinstance(state, Mapping) or key not in state or not isinstance(hashed_seed, float):
            raise RuntimeError(f"Jackdaw RNG stream {key!r} is unavailable")
        return (float(state[key]) + hashed_seed) / 2
    if isinstance(key, int | float):
        return float(key)
    raise RuntimeError(f"unsupported Jackdaw RNG seed {key!r}")


def _tw_state_after_one_draw(rng: object, stream_state: float) -> list[int]:
    from jackdaw.engine.rng import _luajit_random, _luajit_seed

    hashed_seed = getattr(rng, "hashed_seed", None)
    if not isinstance(hashed_seed, float):
        raise RuntimeError("Jackdaw hashed seed is unavailable")
    state = _luajit_seed((stream_state + hashed_seed) / 2)
    _luajit_random(state)
    return state


def _normalize_jackdaw_bridge(
    raw: dict[str, Any],
    game_state: object,
    stale_shop_areas: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Translate Jackdaw serializer defaults into BalatroBot's observed schema.

    This function may normalize representation only. Values come from
    Jackdaw's actual state; it must never invent a result to satisfy a trace.
    """

    result = deepcopy(raw)
    private = game_state if isinstance(game_state, Mapping) else {}
    phase = result.get("state")
    if phase == "SMODS_BOOSTER_OPENED":
        pack_type = private.get("pack_type")
        if pack_type not in _PACK_STATES:
            raise RuntimeError(f"unsupported Jackdaw pack type {pack_type!r}")
        phase = result["state"] = _PACK_STATES[str(pack_type)]

    for name in _OPTIONAL_AREAS:
        area = result.get(name)
        relevant = (phase == "SHOP" and name in {"shop", "vouchers", "packs"}) or (
            phase in {"SMODS_BOOSTER_OPENED", "PLANET_PACK", "TAROT_PACK", "SPECTRAL_PACK", "STANDARD_PACK", "BUFFOON_PACK"}
            and name == "pack"
        )
        if isinstance(area, Mapping) and not area.get("cards") and not relevant:
            result.pop(name, None)

    limits = {
        "cards": 5,
        "hand": 5,
        "jokers": 1,
        "consumables": 1,
        "shop": 1,
        "vouchers": 1,
        "packs": 1,
        "pack": 1,
    }
    for area_name, highlighted_limit in limits.items():
        area = result.get(area_name)
        if isinstance(area, dict):
            area["highlighted_limit"] = highlighted_limit
    deck_area = result.get("cards")
    if isinstance(deck_area, dict):
        permanent_deck_size = private.get("playing_cards_count") if isinstance(private, Mapping) else None
        if not isinstance(permanent_deck_size, int) and isinstance(private, Mapping):
            piles = (private.get("deck"), private.get("hand"), private.get("discard_pile"))
            if all(isinstance(pile, list) for pile in piles):
                permanent_deck_size = sum(len(pile) for pile in piles)
        if isinstance(permanent_deck_size, int):
            deck_area["limit"] = permanent_deck_size

    for area_name in ("cards", "hand", "jokers", "consumables", "shop", "vouchers", "packs", "pack"):
        area = result.get(area_name)
        if not isinstance(area, Mapping) or not isinstance(area.get("cards"), list):
            continue
        private_cards = private.get(_PRIVATE_AREA_KEYS[area_name])
        if not isinstance(private_cards, list) or len(private_cards) != len(area["cards"]):
            raise RuntimeError(f"Jackdaw {area_name} serializer is out of sync with engine state")
        if area_name == "shop":
            shop_config = private.get("shop")
            if not isinstance(shop_config, Mapping) or not isinstance(shop_config.get("joker_max"), int):
                raise RuntimeError("Jackdaw shop capacity is unavailable")
            area["limit"] = shop_config["joker_max"]
        elif area_name == "vouchers":
            area["limit"] = 1
        elif area_name == "packs":
            area["limit"] = 2
        elif area_name == "pack":
            area["limit"] = len(private_cards)
        for card, private_card in zip(area["cards"], private_cards, strict=True):
            if not isinstance(card, dict):
                continue
            modifier = card.get("modifier")
            if isinstance(modifier, Mapping):
                normalized_modifier = {
                    str(key): value for key, value in modifier.items() if value is not None and value is not False
                }
                _apply_balatrobot_card_modifiers(normalized_modifier, private_card)
                card["modifier"] = normalized_modifier or []
            state = card.get("state")
            if isinstance(state, Mapping):
                semantic_state = {
                    str(key): value for key, value in state.items() if value is not None and value is not False
                }
                if area_name == "cards":
                    semantic_state["hidden"] = True
                card["state"] = semantic_state or []
            value = card.get("value")
            if isinstance(value, dict):
                _apply_balatrobot_card_values(value, private_card)
            if str(card.get("set") or "").upper() == "DEFAULT":
                card["cost"] = {"buy": 1, "sell": 1}

    hands = result.get("hands")
    if isinstance(hands, dict):
        for name, hand in _SECRET_HANDS.items():
            hands.setdefault(name, dict(hand))

    round_state = result.get("round")
    current_round = private.get("current_round") if isinstance(private, Mapping) else None
    round_resets = private.get("round_resets") if isinstance(private, Mapping) else None
    if isinstance(round_state, dict) and isinstance(current_round, Mapping):
        if phase == "BLIND_SELECT" and isinstance(round_resets, Mapping):
            round_state["hands_left"] = round_resets.get("hands", round_state.get("hands_left", 0))
            round_state["discards_left"] = round_resets.get("discards", round_state.get("discards_left", 0))
        ancient = current_round.get("ancient_card")
        if isinstance(ancient, Mapping) and ancient.get("suit") in _SUIT_LETTER:
            round_state["ancient_suit"] = _SUIT_LETTER[str(ancient["suit"])]
        most_played = current_round.get("most_played_poker_hand")
        if isinstance(most_played, str) and most_played:
            round_state["most_played_poker_hand"] = most_played

    if stale_shop_areas is not None and phase in {"BLIND_SELECT", "SELECTING_HAND", "ROUND_EVAL", "GAME_OVER"}:
        for name in ("shop", "vouchers", "packs"):
            if name not in result and name in stale_shop_areas:
                result[name] = deepcopy(stale_shop_areas[name])

    return result


def _empty_shop_areas(raw: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in ("shop", "vouchers", "packs"):
        area = raw.get(name)
        if not isinstance(area, Mapping):
            raise RuntimeError(f"Jackdaw left SHOP without a {name} area")
        result[name] = {
            "cards": [],
            "count": area.get("count"),
            "highlighted_limit": area.get("highlighted_limit"),
            "limit": area.get("limit"),
        }
    return result


def _apply_balatrobot_card_values(value: dict[str, Any], card: object) -> None:
    """Mirror BalatroBot's source-backed ``extract_card_value`` ability fields."""

    for key in ("rank", "suit", "rarity", "effect", "perma_bonus"):
        if key in value and value[key] is None:
            value.pop(key, None)

    ability = getattr(card, "ability", None)
    if not isinstance(ability, Mapping):
        value.pop("ability", None)
        return

    perma_bonus = ability.get("perma_bonus")
    if isinstance(perma_bonus, int | float) and not isinstance(perma_bonus, bool) and perma_bonus != 0:
        value["perma_bonus"] = perma_bonus
    else:
        value.pop("perma_bonus", None)

    center = _jackdaw_center(card)
    rarity = center.get("rarity")
    if isinstance(rarity, int | float) and not isinstance(rarity, bool):
        value["rarity"] = rarity
    else:
        value.pop("rarity", None)

    serialized: dict[str, Any] = {}
    extra = ability.get("extra")
    if isinstance(extra, Mapping):
        serialized.update(
            (str(key), item)
            for key, item in extra.items()
            if isinstance(item, bool | int | float | str)
        )
    elif extra is not None:
        serialized["extra"] = extra

    for key in ("t_mult", "t_chips", "mult", "x_mult"):
        item = ability.get(key)
        if isinstance(item, int | float) and not isinstance(item, bool) and item != 0:
            serialized[key] = item
    driver_tally = ability.get("driver_tally")
    if driver_tally is not None and driver_tally is not False:
        serialized["driver_tally"] = driver_tally
    if "loyalty_remaining" in ability and ability["loyalty_remaining"] is not None:
        serialized["loyalty_remaining"] = ability["loyalty_remaining"]

    if serialized:
        value["ability"] = serialized
    else:
        value.pop("ability", None)


def _apply_balatrobot_card_modifiers(modifier: dict[str, Any], card: object) -> None:
    """Mirror BalatroBot's source-backed ``extract_card_modifier`` fields."""

    ability = getattr(card, "ability", None)
    edition = getattr(card, "edition", None)
    if isinstance(edition, Mapping):
        for source, destination in (
            ("mult", "edition_mult"),
            ("chips", "edition_chips"),
            ("x_mult", "edition_x_mult"),
        ):
            item = edition.get(source)
            if isinstance(item, int | float) and not isinstance(item, bool) and item != 0:
                modifier[destination] = item
    if not isinstance(ability, Mapping):
        return
    center = _jackdaw_center(card)
    effect = ability.get("effect") if "effect" in center else None
    if isinstance(effect, str) and effect != "Base":
        modifier["enhancement"] = effect.replace(" Card", "").upper()
        x_mult = ability.get("x_mult")
        if isinstance(x_mult, int | float) and not isinstance(x_mult, bool) and x_mult != 1:
            modifier["enhancement_x_mult"] = x_mult


def _jackdaw_center(card: object) -> Mapping[str, Any]:
    center_key = getattr(card, "center_key", None)
    if not isinstance(center_key, str):
        return {}
    try:
        from jackdaw.engine.card import _resolve_center
    except ImportError:
        return {}
    return _resolve_center(center_key)
