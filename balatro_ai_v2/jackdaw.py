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
from threading import RLock
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
_JACKDAW_PATCH_LOCK = RLock()

_SECRET_HANDS = {
    "Flush Five": {"order": 1, "level": 1, "chips": 160, "mult": 16, "played": 0, "played_this_round": 0},
    "Flush House": {"order": 2, "level": 1, "chips": 140, "mult": 14, "played": 0, "played_this_round": 0},
    "Five of a Kind": {"order": 3, "level": 1, "chips": 120, "mult": 12, "played": 0, "played_this_round": 0},
}
_SUIT_LETTER = {"Spades": "S", "Hearts": "H", "Clubs": "C", "Diamonds": "D"}
_OPTIONAL_AREAS = {"shop", "vouchers", "packs", "pack"}
_PRIVATE_AREA_KEYS = {
    "cards": "deck",
    "discard": "discard_pile",
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
_DEFAULT_POKER_HAND_ITERATION_ORDER = (
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


class JackdawUnavailable(RuntimeError):
    pass


def _vanilla_most_played_hand(
    hand_levels: Any,
    iteration_order: tuple[str, ...] | None,
) -> Any:
    """Match vanilla's process-order tie bug at a defeated boss blind."""

    from jackdaw.engine.data.hands import HandType

    order = iteration_order or _DEFAULT_POKER_HAND_ITERATION_ORDER
    best = HandType.HIGH_CARD
    best_count = -1
    for name in order:
        hand_type = HandType(name)
        count = hand_levels.get_state(hand_type).played
        # Vanilla never updates its `_order` sentinel, so every later hand with
        # the same maximum replaces the earlier one.
        if count >= best_count:
            best = hand_type
            best_count = count
    return best


def _refresh_swashbuckler_mult(game_state: Mapping[str, Any]) -> None:
    """Mirror ``Card:update`` for owned, shop, and pack Swashbucklers."""

    jokers = game_state.get("jokers")
    if not isinstance(jokers, list):
        raise RuntimeError("Jackdaw joker state is unavailable")
    owned_sell_total = sum(int(getattr(card, "sell_cost", 0)) for card in jokers)
    for area_name in ("jokers", "shop_cards", "pack_cards"):
        cards = game_state.get(area_name, [])
        if not isinstance(cards, list):
            raise RuntimeError(f"Jackdaw {area_name} state is unavailable")
        for card in cards:
            if getattr(card, "center_key", None) != "j_swashbuckler":
                continue
            ability = getattr(card, "ability", None)
            if not isinstance(ability, dict):
                raise RuntimeError("Jackdaw Swashbuckler ability state is unavailable")
            is_owned = any(card is owned_card for owned_card in jokers)
            own_sell_cost = int(getattr(card, "sell_cost", 0)) if is_owned else 0
            ability["mult"] = owned_sell_total - own_sell_cost


@dataclass(slots=True)
class JackdawBackend:
    profile_mode: str = field(default="all_unlocked", init=False)
    canonicalizer: BalatroBotCanonicalizer = field(default_factory=BalatroBotCanonicalizer)
    metadata: BackendMetadata = field(init=False)
    _backend: Any = field(init=False, repr=False)
    _rpc_error: type[Exception] = field(init=False, repr=False)
    _current: AuthorityObservation | None = field(default=None, init=False, repr=False)
    _round_targets_rolled: bool = field(default=False, init=False, repr=False)
    _stale_shop_areas: dict[str, dict[str, Any]] | None = field(default=None, init=False, repr=False)
    _pending_ante_setup: int | None = field(default=None, init=False, repr=False)
    _poker_hand_iteration_order: tuple[str, ...] | None = field(default=None, init=False, repr=False)

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
        self._stale_shop_areas = None
        self._pending_ante_setup = None
        self._handle("menu", {})
        raw = self._handle(
            "start",
            {"deck": spec.deck, "stake": spec.stake, "seed": spec.seed or "DEFAULT"},
        )
        self._initialize_orbital_choices()
        raw = self._handle("gamestate", {})
        self._current = self._observation(raw)
        return self._current

    def observe(self) -> AuthorityObservation:
        self._current = self._observation(self._handle("gamestate", {}))
        return self._current

    def configure_replay(self, authority_start: object) -> None:
        """Use private VM-order metadata from an authority trace during replay."""

        if not isinstance(authority_start, Mapping):
            raise RuntimeError("authority replay start state is not a mapping")
        order = authority_start.get("poker_hand_iteration_order")
        hands = authority_start.get("hands")
        if not isinstance(order, list) or not order or not isinstance(hands, Mapping):
            raise RuntimeError("authority replay is missing visible poker-hand order")
        if len(order) != len(hands) or not all(
            isinstance(name, str) and name in hands for name in order
        ):
            raise RuntimeError("authority replay has an invalid poker-hand iteration order")
        if len(set(order)) != len(order):
            raise RuntimeError("authority replay poker-hand order contains duplicates")
        self._poker_hand_iteration_order = tuple(order)

    def step(self, action: PublicAction) -> StepResult:
        if self._current is None:
            raise RuntimeError("reset must be called before step")
        before = self._current
        raw_before = json.loads(before.observed.raw_json)
        method, params = action_to_rpc(action, to_public_observation(raw_before))
        if method == "next_round":
            self._stale_shop_areas = _empty_shop_areas(raw_before)
        standard_pack_card = self._selected_standard_pack_card(method, params)
        voucher_effect = self._selected_voucher_effect(method, params)
        try:
            if method == "play":
                with self._play_compatibility(), self._round_end_compatibility():
                    raw_after = self._handle(method, params)
            elif method == "cash_out" and self._round_targets_rolled:
                with self._cash_out_compatibility():
                    raw_after = self._handle(method, params)
                self._finish_cash_out_compatibility()
                raw_after = self._handle("gamestate", {})
                self._round_targets_rolled = False
                self._stale_shop_areas = None
            else:
                raw_after = self._handle(method, params)
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
        if standard_pack_card is not None and self._place_standard_pack_card(standard_pack_card):
            raw_after = self._handle("gamestate", {})
        if voucher_effect is not None and self._apply_immediate_voucher_effect(voucher_effect):
            raw_after = self._handle("gamestate", {})
        if method == "next_round" and raw_after.get("state") == "BLIND_SELECT":
            self._initialize_orbital_choices()
        if method == "play" and raw_after.get("state") == "ROUND_EVAL":
            self._roll_round_targets()
            self._round_targets_rolled = True
            raw_after = self._handle("gamestate", {})
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
        self._handle("menu", {})
        self._current = None
        self._round_targets_rolled = False
        self._stale_shop_areas = None
        self._pending_ante_setup = None
        self._poker_hand_iteration_order = None

    def _handle(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._poker_hand_order_compatibility(), self._standard_pack_cost_compatibility():
            with self._credit_compatibility(method, params) as used_credit:
                raw = self._backend.handle(method, params)
            return self._backend.handle("gamestate", {}) if used_credit else raw

    @contextmanager
    def _credit_compatibility(
        self,
        method: str,
        params: Mapping[str, Any],
    ) -> Iterator[bool]:
        """Let Jackdaw purchase handlers honor Balatro's ``bankrupt_at`` floor."""

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            yield False
            return
        cost = self._purchase_cost(method, params, game_state)
        dollars = game_state.get("dollars")
        bankrupt_at = game_state.get("bankrupt_at")
        if (
            cost is None
            or not isinstance(dollars, int)
            or not isinstance(bankrupt_at, int)
            or bankrupt_at >= 0
            or cost <= dollars
            or cost > dollars - bankrupt_at
        ):
            yield False
            return
        game_state["dollars"] = dollars - bankrupt_at
        try:
            yield True
        finally:
            game_state["dollars"] += bankrupt_at

    @staticmethod
    def _purchase_cost(
        method: str,
        params: Mapping[str, Any],
        game_state: Mapping[str, Any],
    ) -> int | None:
        if method == "reroll":
            current_round = game_state.get("current_round")
            if not isinstance(current_round, Mapping):
                return None
            if int(current_round.get("free_rerolls", 0)) > 0:
                return 0
            cost = current_round.get("reroll_cost")
            return cost if isinstance(cost, int) else None
        if method != "buy":
            return None
        for parameter, area_name in (
            ("card", "shop_cards"),
            ("voucher", "shop_vouchers"),
            ("pack", "shop_boosters"),
        ):
            index = params.get(parameter)
            cards = game_state.get(area_name)
            if not isinstance(index, int) or isinstance(index, bool) or not isinstance(cards, list):
                continue
            if not 0 <= index < len(cards):
                return None
            cost = getattr(cards[index], "cost", None)
            return cost if isinstance(cost, int) else None
        return None

    @contextmanager
    def _poker_hand_order_compatibility(self) -> Iterator[None]:
        order = self._poker_hand_iteration_order
        if order is None:
            yield
            return
        from jackdaw.engine import tags
        from jackdaw.engine.data.hands import HandType

        with _JACKDAW_PATCH_LOCK:
            original_hands = tags._ORBITAL_HANDS
            original_apply = tags.Tag.apply
            tags._ORBITAL_HANDS = [HandType(name) for name in order]

            def vanilla_apply(
                tag: Any,
                context: str,
                game_state: dict[str, Any],
                rng: Any = None,
                **kwargs: Any,
            ) -> Any:
                if context == "immediate" and tag.key == "tag_orbital":
                    ante = game_state.get("round_resets", {}).get("ante")
                    blind_type = game_state.get("blind_on_deck")
                    choices = game_state.get("orbital_choices", {}).get(ante, {})
                    hand_type = choices.get(blind_type)
                    if hand_type is None:
                        raise RuntimeError("Jackdaw Orbital Tag choice was not initialized")
                    return tags.TagResult(level_up=(hand_type, tag.config["levels"]))
                return original_apply(tag, context, game_state, rng, **kwargs)

            tags.Tag.apply = vanilla_apply
            try:
                yield
            finally:
                tags.Tag.apply = original_apply
                tags._ORBITAL_HANDS = original_hands

    def _initialize_orbital_choices(self) -> None:
        """Mirror blind-select UI's three once-per-ante Orbital rolls."""

        from jackdaw.engine.data.hands import HandType

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        round_resets = game_state.get("round_resets")
        rng = game_state.get("rng")
        hand_levels = game_state.get("hand_levels")
        if not isinstance(round_resets, Mapping) or rng is None or hand_levels is None:
            raise RuntimeError("Jackdaw Orbital choice state is incomplete")
        ante = round_resets.get("ante")
        if not isinstance(ante, int):
            raise RuntimeError("Jackdaw ante is unavailable for Orbital choices")
        all_choices = game_state.setdefault("orbital_choices", {})
        if ante in all_choices:
            return
        order = self._poker_hand_iteration_order or _DEFAULT_POKER_HAND_ITERATION_ORDER
        visible = [
            HandType(name)
            for name in order
            if hand_levels.get_state(HandType(name)).visible
        ]
        if not visible:
            raise RuntimeError("Jackdaw has no visible poker hands for Orbital choices")
        choices: dict[str, Any] = {}
        for blind_type in ("Small", "Big", "Boss"):
            index = rng.random(rng.seed("orbital"), 1, len(visible))
            choices[blind_type] = visible[index - 1]
        all_choices[ante] = choices

    @contextmanager
    def _standard_pack_cost_compatibility(self) -> Iterator[None]:
        """Reprice Standard-pack cards after their edition is assigned."""

        from jackdaw.engine import packs

        original_generate = packs._gen_standard

        def vanilla_generate(rng: Any, ante: int, game_state: dict[str, Any]) -> Any:
            card = original_generate(rng, ante, game_state)
            card.set_cost(
                inflation=game_state.get("inflation", 0),
                discount_percent=game_state.get("discount_percent", 0),
                ante=ante,
            )
            return card

        with _JACKDAW_PATCH_LOCK:
            packs._gen_standard = vanilla_generate
            try:
                yield
            finally:
                packs._gen_standard = original_generate

    def _observation(self, raw: dict[str, Any]) -> AuthorityObservation:
        # Both adapters must pass independently.  The public conversion catches
        # leaks/unsupported shapes; canonicalization catches semantic drift.
        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        _refresh_swashbuckler_mult(game_state)
        normalized = _normalize_jackdaw_bridge(
            raw,
            game_state,
            self._stale_shop_areas,
            self._poker_hand_iteration_order,
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

    def _selected_standard_pack_card(self, method: str, params: Mapping[str, Any]) -> object | None:
        """Capture a Standard-pack pick before Jackdaw removes it from the pack."""

        if method != "pack":
            return None
        index = params.get("card")
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        pack_cards = game_state.get("pack_cards")
        if not isinstance(pack_cards, list) or not 0 <= index < len(pack_cards):
            return None
        card = pack_cards[index]
        ability = getattr(card, "ability", None)
        card_set = ability.get("set") if isinstance(ability, Mapping) else None
        return card if card_set in {"Default", "Enhanced"} else None

    def _selected_voucher_effect(
        self,
        method: str,
        params: Mapping[str, Any],
    ) -> tuple[str, int, int] | None:
        """Capture immediate public counter changes missing from Jackdaw vouchers."""

        if method != "buy":
            return None
        index = params.get("voucher")
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        vouchers = game_state.get("shop_vouchers")
        current_round = game_state.get("current_round")
        if not isinstance(vouchers, list) or not 0 <= index < len(vouchers):
            return None
        if not isinstance(current_round, Mapping):
            raise RuntimeError("Jackdaw current-round state is unavailable before voucher purchase")
        key = getattr(vouchers[index], "center_key", "")
        effects = {
            "v_grabber": ("hands_left", 1),
            "v_nacho_tong": ("hands_left", 1),
            "v_wasteful": ("discards_left", 1),
            "v_recyclomancy": ("discards_left", 1),
            "v_hieroglyph": ("hands_left", -1),
        }
        effect = effects.get(key)
        if effect is None:
            return None
        field, delta = effect
        before = current_round.get(field)
        if not isinstance(before, int):
            raise RuntimeError(f"Jackdaw current-round {field} is unavailable before voucher purchase")
        return field, before, delta

    def _apply_immediate_voucher_effect(self, effect: tuple[str, int, int]) -> bool:
        field, before, delta = effect
        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        current_round = game_state.get("current_round")
        if not isinstance(current_round, dict):
            raise RuntimeError("Jackdaw current-round state is unavailable after voucher purchase")
        actual = current_round.get(field)
        expected = before + delta
        if actual == expected:
            return False
        if actual != before:
            raise RuntimeError(f"Jackdaw {field} changed unexpectedly during voucher purchase")
        current_round[field] = expected
        return True

    def _place_standard_pack_card(self, card: object) -> bool:
        """Match ``G.deck:emplace``: a picked playing card goes to the deck front."""

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        deck = game_state.get("deck")
        if not isinstance(deck, list):
            raise RuntimeError("Jackdaw deck state is unavailable after Standard-pack pick")
        indices = [index for index, candidate in enumerate(deck) if candidate is card]
        if len(indices) != 1:
            raise RuntimeError("Jackdaw did not add the selected Standard-pack card exactly once")
        playing_cards_count = game_state.get("playing_cards_count")
        if not isinstance(playing_cards_count, int):
            raise RuntimeError("Jackdaw playing-card count is unavailable after Standard-pack pick")
        piles = (deck, game_state.get("hand"), game_state.get("discard_pile"))
        if not all(isinstance(pile, list) for pile in piles):
            raise RuntimeError("Jackdaw playing-card piles are unavailable after Standard-pack pick")
        expected_count = sum(len(pile) for pile in piles)
        changed = playing_cards_count != expected_count
        game_state["playing_cards_count"] = expected_count
        index = indices[0]
        if index == 0:
            return changed
        deck.insert(0, deck.pop(index))
        return True

    @contextmanager
    def _play_compatibility(self) -> Iterator[None]:
        """Sort Hook discards by hand position, as vanilla does before moving them."""

        from jackdaw.engine import game

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        hand = game_state.get("hand")
        if not isinstance(hand, list):
            raise RuntimeError("Jackdaw hand state is unavailable before play")
        hand_positions = {id(card): index for index, card in enumerate(hand)}

        original_fire_discard_effects = game._fire_discard_effects

        def vanilla_fire_discard_effects(
            state: dict[str, Any],
            discarded: list[Any],
            *,
            hook: bool,
        ) -> None:
            if hook:
                missing = [card for card in discarded if id(card) not in hand_positions]
                if missing:
                    raise RuntimeError("Jackdaw Hook discarded a card absent from the pre-play hand")
                discarded = sorted(discarded, key=lambda card: hand_positions[id(card)])
            original_fire_discard_effects(state, discarded, hook=hook)

        with _JACKDAW_PATCH_LOCK:
            game._fire_discard_effects = vanilla_fire_discard_effects
            try:
                yield
            finally:
                game._fire_discard_effects = original_fire_discard_effects

    @contextmanager
    def _round_end_compatibility(self) -> Iterator[None]:
        """Keep next-ante blind setup in vanilla's split round-end/cash-out order."""

        from jackdaw.engine import game

        with _JACKDAW_PATCH_LOCK:
            original_advance_ante = game._advance_ante
            game._advance_ante = self._advance_ante_at_round_end
            try:
                yield
            finally:
                game._advance_ante = original_advance_ante

    def _advance_ante_at_round_end(self, game_state: dict[str, Any]) -> None:
        from jackdaw.engine.vouchers import get_next_voucher_key

        hand_levels = game_state.get("hand_levels")
        current_round = game_state.get("current_round")
        round_resets = game_state.get("round_resets")
        rng = game_state.get("rng")
        if hand_levels is None or not isinstance(current_round, dict):
            raise RuntimeError("Jackdaw hand-level state is unavailable at ante advance")
        if not isinstance(round_resets, dict) or rng is None:
            raise RuntimeError("Jackdaw ante/RNG state is unavailable at ante advance")
        if self._pending_ante_setup is not None:
            raise RuntimeError(f"Jackdaw ante {self._pending_ante_setup} setup is already pending")

        most_played = _vanilla_most_played_hand(
            hand_levels,
            self._poker_hand_iteration_order,
        )
        current_round["most_played_poker_hand"] = most_played.value
        round_resets["ante"] += 1
        ante = int(round_resets["ante"])
        used_vouchers = {key: True for key in game_state.get("used_vouchers", [])}
        current_round["voucher"] = get_next_voucher_key(
            rng,
            used_vouchers,
            in_shop=None,
            ante=ante,
        )
        self._pending_ante_setup = ante

    def _apply_pending_ante_setup(self, game_state: dict[str, Any]) -> None:
        pending_ante = self._pending_ante_setup
        if pending_ante is None:
            return

        from jackdaw.engine.blind import get_new_boss
        from jackdaw.engine.pools import pick_card_from_pool

        round_resets = game_state["round_resets"]
        ante = int(round_resets["ante"])
        if ante != pending_ante:
            raise RuntimeError(f"pending ante {pending_ante} does not match active ante {ante}")
        rng = game_state.get("rng")
        if rng is None:
            raise RuntimeError("Jackdaw RNG state is unavailable for ante setup")
        used_vouchers = set(game_state.get("used_vouchers", []))
        round_resets["blind_ante"] = ante
        round_resets["blind_tags"] = {
            "Small": pick_card_from_pool("Tag", rng, ante, used_vouchers=used_vouchers),
            "Big": pick_card_from_pool("Tag", rng, ante, used_vouchers=used_vouchers),
        }
        round_resets["blind_choices"]["Boss"] = get_new_boss(
            ante,
            game_state.setdefault("bosses_used", {}),
            rng,
            win_ante=game_state.get("win_ante", 8),
        )
        round_resets["blind_states"] = {
            "Small": "Upcoming",
            "Big": "Upcoming",
            "Boss": "Upcoming",
        }
        round_resets["boss_rerolled"] = False
        game_state["blind_on_deck"] = "Small"

    @contextmanager
    def _cash_out_compatibility(self) -> Iterator[None]:
        """Match vanilla's target and next-ante setup timing."""

        from jackdaw.engine import game, round_lifecycle

        original_reset = round_lifecycle.reset_round_targets
        original_populate_shop = game._populate_shop

        def vanilla_populate_shop(populate_state: dict[str, Any]) -> None:
            self._apply_pending_ante_setup(populate_state)
            original_populate_shop(populate_state)
            self._pending_ante_setup = None

        with _JACKDAW_PATCH_LOCK:
            round_lifecycle.reset_round_targets = lambda *_args, **_kwargs: None
            game._populate_shop = vanilla_populate_shop
            try:
                yield
            finally:
                round_lifecycle.reset_round_targets = original_reset
                game._populate_shop = original_populate_shop


def _normalize_jackdaw_bridge(
    raw: dict[str, Any],
    game_state: object,
    stale_shop_areas: Mapping[str, Mapping[str, Any]] | None = None,
    poker_hand_iteration_order: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Translate Jackdaw serializer defaults into BalatroBot's observed schema.

    This function may normalize representation only. Values come from
    Jackdaw's actual state; it must never invent a result to satisfy a trace.
    """

    result = deepcopy(raw)
    private = game_state if isinstance(game_state, Mapping) else {}
    if poker_hand_iteration_order is None:
        poker_hand_iteration_order = _DEFAULT_POKER_HAND_ITERATION_ORDER
    result["poker_hand_iteration_order"] = list(poker_hand_iteration_order)
    discard_pile = private.get("discard_pile")
    if not isinstance(discard_pile, list):
        raise RuntimeError("Jackdaw discard pile is unavailable")
    if discard_pile:
        from jackdaw.bridge.serializer import serialize_area

        result["discard"] = serialize_area(discard_pile, 500, 5)
    else:
        result["discard"] = {"cards": [], "count": 0, "highlighted_limit": 5, "limit": 500}
    used_vouchers = result.get("used_vouchers")
    if isinstance(used_vouchers, Mapping):
        result["used_vouchers"] = {str(key): "" for key in used_vouchers}
    phase = result.get("state")
    if phase == "SMODS_BOOSTER_OPENED":
        pack_type = private.get("pack_type")
        if pack_type not in _PACK_STATES:
            raise RuntimeError(f"unsupported Jackdaw pack type {pack_type!r}")
        phase = result["state"] = _PACK_STATES[str(pack_type)]

    in_pack = phase in {
        "SMODS_BOOSTER_OPENED",
        "PLANET_PACK",
        "TAROT_PACK",
        "SPECTRAL_PACK",
        "STANDARD_PACK",
        "BUFFOON_PACK",
    }
    pack_from_shop = str(private.get("shop_return_phase")) == "shop"
    for name in _OPTIONAL_AREAS:
        area = result.get(name)
        relevant = (
            (phase == "SHOP" or (in_pack and pack_from_shop))
            and name in {"shop", "vouchers", "packs"}
        ) or (in_pack and name == "pack")
        if isinstance(area, Mapping) and not area.get("cards") and not relevant:
            result.pop(name, None)

    limits = {
        "cards": 5,
        "discard": 5,
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

    for area_name in (
        "cards",
        "discard",
        "hand",
        "jokers",
        "consumables",
        "shop",
        "vouchers",
        "packs",
        "pack",
    ):
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
                if area_name in {"cards", "discard"}:
                    semantic_state["hidden"] = True
                card["state"] = semantic_state or []
            value = card.get("value")
            if isinstance(value, dict):
                _apply_balatrobot_card_values(value, private_card)
            if str(card.get("set") or "").upper() in {"DEFAULT", "ENHANCED"}:
                card["cost"] = {
                    "buy": max(1, int(getattr(private_card, "cost", 0))),
                    "sell": max(1, int(getattr(private_card, "sell_cost", 0))),
                }

    hands = result.get("hands")
    if isinstance(hands, dict):
        for name, hand in _SECRET_HANDS.items():
            hands.setdefault(name, dict(hand))

    round_state = result.get("round")
    current_round = private.get("current_round") if isinstance(private, Mapping) else None
    if isinstance(round_state, dict) and isinstance(current_round, Mapping):
        before_first_blind = private.get("round", 0) == 0 and (
            phase == "BLIND_SELECT" or (in_pack and not pack_from_shop)
        )
        if before_first_blind:
            round_resets = private.get("round_resets")
            if not isinstance(round_resets, Mapping):
                raise RuntimeError("Jackdaw initial round-reset state is unavailable")
            round_state["hands_left"] = round_resets.get("hands", round_state.get("hands_left", 0))
            round_state["discards_left"] = round_resets.get(
                "discards", round_state.get("discards_left", 0)
            )
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
    to_do_poker_hand = ability.get("to_do_poker_hand")
    if isinstance(to_do_poker_hand, str):
        serialized["poker_hand"] = to_do_poker_hand

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
