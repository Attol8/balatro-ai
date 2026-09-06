"""Pinned Jackdaw candidate backend.

Jackdaw is a fast candidate, never an authority.  The import is lazy so the
authority-only project remains dependency-free on Python 3.11; candidate work
uses Python 3.12 and the pinned optional dependency.
"""

from __future__ import annotations

import importlib.metadata
import hashlib
import json
import os
import subprocess
import tempfile
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
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
from balatro_ai_v2.canonical import BalatroBotCanonicalizer, CanonicalObservedState
from balatro_ai_v2.public_state import PublicObservation


JACKDAW_REVISION = "dbedc66255fe594cce7b7cccc188c8a11649d9ec"
_JACKDAW_PATCH_LOCK = RLock()
_JACKDAW_DATA_HASHES = {
    "blinds.json": "21df32cbd4b67e641ed991028ec0d2dc36ff69051d28460e45d26ae3ede385ad",
    "cards.json": "4bbd866f53531d954fed146060cea06a84c7c6bcdd4f5306d0ba7b0be5fddd61",
    "centers.json": "6de51cf3751ad957baf50fbe2ac632644b4f0178e82674e7f2e818e1befb5d71",
    "seals.json": "405f43b9f465f053a0a2f5e753840b52235e5cdd794177176ac4e1de9a783bae",
    "stakes.json": "6d1c74e7615b8becdec4755d5020c1286d77c504c4dbee5062568298023706d5",
    "tags.json": "7301c0f25f902385ed8e0d00d87ac4638a0c6783af590d58a2c80038a70923b5",
}

_SECRET_HANDS = {
    "Flush Five": {
        "order": 1,
        "level": 1,
        "chips": 160,
        "mult": 16,
        "played": 0,
        "played_this_round": 0,
    },
    "Flush House": {
        "order": 2,
        "level": 1,
        "chips": 140,
        "mult": 14,
        "played": 0,
        "played_this_round": 0,
    },
    "Five of a Kind": {
        "order": 3,
        "level": 1,
        "chips": 120,
        "mult": 12,
        "played": 0,
        "played_this_round": 0,
    },
}
_SUIT_LETTER = {"Spades": "S", "Hearts": "H", "Clubs": "C", "Diamonds": "D"}
_RANK_LETTER = {
    **{str(value): str(value) for value in range(2, 10)},
    "10": "T",
    "Jack": "J",
    "Queen": "Q",
    "King": "K",
    "Ace": "A",
}
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


def verify_jackdaw_runtime() -> dict[str, object]:
    """Fail closed unless the imported candidate is the clean pinned tree."""

    try:
        import jackdaw
    except ImportError as exc:
        raise JackdawUnavailable(
            "install the pinned 'candidate' extra under Python 3.12 to use Jackdaw"
        ) from exc
    revision, root = _jackdaw_install_provenance(jackdaw)
    dirty = False
    if root is not None:
        try:
            status_lines = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            # uv places an empty checkout-complete marker beside the pinned tree.
            # It is packaging metadata, not imported Jackdaw source.
            dirty = any(line != "?? .ok" for line in status_lines)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise JackdawUnavailable("cannot verify imported Jackdaw checkout") from exc
    if revision != JACKDAW_REVISION:
        raise JackdawUnavailable(
            f"Jackdaw revision {revision!r} does not match pinned {JACKDAW_REVISION!r}"
        )
    if dirty:
        raise JackdawUnavailable("imported Jackdaw checkout has modifications")
    _ensure_jackdaw_data(jackdaw)
    try:
        from jackdaw.bridge import backend as _bridge_backend  # noqa: F401
    except (ImportError, OSError, ValueError) as exc:
        raise JackdawUnavailable("pinned Jackdaw data failed to initialize") from exc
    return {
        "revision": revision,
        "dirty": dirty,
        "data_hashes": dict(sorted(_JACKDAW_DATA_HASHES.items())),
    }


def _ensure_jackdaw_data(module: Any) -> tuple[str, ...]:
    """Restore wheel-omitted pinned data, rejecting every unexpected byte."""

    target = Path(module.__file__).resolve().parent / "engine" / "data"
    source = Path(__file__).resolve().parent / "candidate_data" / "jackdaw"
    copied: list[str] = []
    with _JACKDAW_PATCH_LOCK:
        for name, expected_digest in _JACKDAW_DATA_HASHES.items():
            source_path = source / name
            try:
                payload = source_path.read_bytes()
            except OSError as exc:
                raise JackdawUnavailable(
                    f"bundled Jackdaw data is missing: {name}"
                ) from exc
            # Text patches retain a trailing newline; upstream's tracked JSON
            # does not. Normalize the bundled copy back to the pinned bytes.
            if payload.endswith(b"\n"):
                payload = payload[:-1]
            if hashlib.sha256(payload).hexdigest() != expected_digest:
                raise JackdawUnavailable(f"bundled Jackdaw data hash mismatch: {name}")

            target_path = target / name
            if target_path.exists():
                try:
                    installed_digest = hashlib.sha256(
                        target_path.read_bytes()
                    ).hexdigest()
                except OSError as exc:
                    raise JackdawUnavailable(
                        f"cannot verify installed Jackdaw data: {name}"
                    ) from exc
                if installed_digest != expected_digest:
                    raise JackdawUnavailable(
                        f"installed Jackdaw data hash mismatch: {name}"
                    )
                continue

            try:
                target.mkdir(parents=True, exist_ok=True)
                descriptor, temporary_name = tempfile.mkstemp(
                    dir=target,
                    prefix=f".{name}.",
                )
                try:
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary_name, target_path)
                    copied.append(name)
                except BaseException:
                    Path(temporary_name).unlink(missing_ok=True)
                    raise
            except OSError as exc:
                raise JackdawUnavailable(
                    f"cannot install pinned Jackdaw data: {name}"
                ) from exc
    return tuple(copied)


def _jackdaw_install_provenance(module: Any) -> tuple[str, Path | None]:
    """Read package provenance without confusing a parent repository for Jackdaw."""

    try:
        distribution = importlib.metadata.distribution(module.__package__ or "jackdaw")
        metadata_path = distribution.locate_file(
            "jackdaw-0.1.0.dist-info/direct_url.json"
        )
        data = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
        vcs = data.get("vcs_info", {})
        revision = vcs.get("commit_id")
        url = data.get("url")
        if (
            isinstance(revision, str)
            and isinstance(url, str)
            and url.endswith("jackdaw-balatro.git")
        ):
            root = Path(url[7:]).resolve() if url.startswith("file://") else None
            return revision, root
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        pass

    module_path = Path(module.__file__).resolve()
    root = next(
        (parent for parent in module_path.parents if (parent / ".git").exists()), None
    )
    if root is None:
        raise JackdawUnavailable(
            "cannot verify imported Jackdaw installation provenance"
        )
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise JackdawUnavailable("cannot verify imported Jackdaw revision") from exc
    return revision, root


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


def _refresh_stencil_x_mult(game_state: Mapping[str, Any]) -> None:
    """Mirror ``Card:update`` for owned, shop, and pack Joker Stencils."""

    jokers = game_state.get("jokers")
    joker_slots = game_state.get("joker_slots", 5)
    if not isinstance(jokers, list):
        raise RuntimeError("Jackdaw joker state is unavailable")
    if not isinstance(joker_slots, int) or isinstance(joker_slots, bool):
        raise RuntimeError("Jackdaw joker slot count is unavailable")
    stencil_count = sum(
        getattr(card, "center_key", None) == "j_stencil" for card in jokers
    )
    runtime_x_mult = joker_slots - len(jokers) + stencil_count
    for area_name in ("jokers", "shop_cards", "pack_cards"):
        cards = game_state.get(area_name, [])
        if not isinstance(cards, list):
            raise RuntimeError(f"Jackdaw {area_name} state is unavailable")
        for card in cards:
            if getattr(card, "center_key", None) != "j_stencil":
                continue
            ability = getattr(card, "ability", None)
            if not isinstance(ability, dict):
                raise RuntimeError("Jackdaw Joker Stencil ability state is unavailable")
            ability["x_mult"] = runtime_x_mult


def _refresh_drivers_license_tally(game_state: Mapping[str, Any]) -> None:
    """Mirror ``Card:update`` for the visible enhanced-card tally."""

    seen: set[int] = set()
    enhanced_count = 0
    for area_name in ("deck", "hand", "discard_pile", "play"):
        cards = game_state.get(area_name, [])
        if not isinstance(cards, list):
            raise RuntimeError(f"Jackdaw {area_name} state is unavailable")
        for card in cards:
            identity = id(card)
            if identity in seen:
                continue
            seen.add(identity)
            if getattr(card, "base", None) is not None and getattr(
                card, "center_key", ""
            ) not in {"", "c_base"}:
                enhanced_count += 1

    for area_name in ("jokers", "shop_cards", "pack_cards"):
        cards = game_state.get(area_name, [])
        if not isinstance(cards, list):
            raise RuntimeError(f"Jackdaw {area_name} state is unavailable")
        for card in cards:
            if getattr(card, "center_key", None) != "j_drivers_license":
                continue
            ability = getattr(card, "ability", None)
            if not isinstance(ability, dict):
                raise RuntimeError("Jackdaw Driver's License state is unavailable")
            ability["driver_tally"] = enhanced_count


def _refresh_deck_enhancements(game_state: dict[str, Any]) -> None:
    """Keep enhancement-gated Joker pools aligned with live permanent cards."""

    seen: set[int] = set()
    enhancements: set[str] = set()
    for area_name in ("deck", "hand", "discard_pile", "play"):
        cards = game_state.get(area_name, [])
        if not isinstance(cards, list):
            raise RuntimeError(f"Jackdaw {area_name} state is unavailable")
        for card in cards:
            identity = id(card)
            if identity in seen:
                continue
            seen.add(identity)
            center_key = getattr(card, "center_key", None)
            if getattr(card, "base", None) is not None and center_key not in {
                None,
                "",
                "c_base",
            }:
                enhancements.add(str(center_key))
    game_state["deck_enhancements"] = enhancements


def _clear_completed_cerulean_forced_selections(
    game_state: Mapping[str, Any],
) -> None:
    """Clear Cerulean Bell's round-local card marker after cash-out."""

    blind = game_state.get("blind")
    if getattr(blind, "name", None) != "Cerulean Bell":
        return
    seen: set[int] = set()
    for area_name in ("deck", "hand", "discard_pile", "play"):
        cards = game_state.get(area_name, [])
        if not isinstance(cards, list):
            raise RuntimeError(
                f"Jackdaw {area_name} state is invalid after Cerulean Bell"
            )
        for card in cards:
            identity = id(card)
            if identity in seen:
                continue
            seen.add(identity)
            ability = getattr(card, "ability", None)
            if not isinstance(ability, dict):
                raise RuntimeError(
                    "Jackdaw playing-card ability is invalid after Cerulean Bell"
                )
            ability.pop("forced_selection", None)


@dataclass(slots=True)
class JackdawBackend:
    profile_mode: str = field(default="all_unlocked", init=False)
    canonicalizer: BalatroBotCanonicalizer = field(
        default_factory=BalatroBotCanonicalizer
    )
    metadata: BackendMetadata = field(init=False)
    _backend: Any = field(init=False, repr=False)
    _rpc_error: type[Exception] = field(init=False, repr=False)
    _current: AuthorityObservation | None = field(default=None, init=False, repr=False)
    _round_targets_rolled: bool = field(default=False, init=False, repr=False)
    _stale_shop_areas: dict[str, dict[str, Any]] | None = field(
        default=None, init=False, repr=False
    )
    _pending_ante_setup: int | None = field(default=None, init=False, repr=False)
    _poker_hand_iteration_order: tuple[str, ...] | None = field(
        default=None, init=False, repr=False
    )
    _active_pack_cards: list[Any] | None = field(default=None, init=False, repr=False)
    _pack_card_limit: int | None = field(default=None, init=False, repr=False)
    _won: bool = field(default=False, init=False, repr=False)
    _pending_skip_dollars: int = field(default=0, init=False, repr=False)
    lightweight: bool = field(default=False)
    current_public: PublicObservation | None = field(
        default=None, init=False, repr=False
    )
    _lightweight_normalized: dict[str, Any] | None = field(
        default=None, init=False, repr=False
    )

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
            adapter_version="8",
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
        self._active_pack_cards = None
        self._pack_card_limit = None
        self._won = False
        self._pending_skip_dollars = 0
        self._lightweight_normalized = None
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
            raise RuntimeError(
                "authority replay has an invalid poker-hand iteration order"
            )
        if len(set(order)) != len(order):
            raise RuntimeError("authority replay poker-hand order contains duplicates")
        self._poker_hand_iteration_order = tuple(order)

    def step(self, action: PublicAction) -> StepResult:
        if self._current is None:
            raise RuntimeError("reset must be called before step")
        before = self._current
        raw_before = self._lightweight_normalized if self.lightweight else None
        if raw_before is None:
            decoded = json.loads(before.observed.raw_json)
            if not isinstance(decoded, dict):
                raise RuntimeError("Jackdaw current observation is invalid")
            raw_before = decoded
            if self.lightweight:
                self._lightweight_normalized = raw_before
        public_before = self.current_public
        if public_before is None:
            public_before = to_public_observation(raw_before)
        method, params = action_to_rpc(action, public_before)
        if method == "next_round":
            self._stale_shop_areas = _empty_shop_areas(raw_before)
        standard_pack_card = self._selected_standard_pack_card(method, params)
        pack_cryptid_snapshot = self._pack_cryptid_copy_snapshot(method, params)
        shop_playing_card = self._selected_shop_playing_card(method, params)
        voucher_effect = self._selected_voucher_effect(method, params)
        boss_disabling_sale = self._selected_boss_disabling_sale(method, params)
        self._apply_pending_skip_dollars()
        try:
            if method == "reroll_boss":
                raw_after = self._reroll_boss_compatibility()
            elif method == "buy" and params.get("mode") == "use":
                raw_after = self._buy_and_use_planet_compatibility(params)
            elif method == "play":
                with (
                    self._play_compatibility(),
                    self._observatory_scoring_compatibility(),
                    self._round_end_compatibility(),
                ):
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
        if boss_disabling_sale and self._apply_boss_disable_sale_compatibility():
            raw_after = self._handle("gamestate", {})
        if standard_pack_card is not None and self._place_standard_pack_card(
            standard_pack_card
        ):
            raw_after = self._handle("gamestate", {})
        if pack_cryptid_snapshot is not None and self._place_pack_cryptid_copies(
            pack_cryptid_snapshot
        ):
            raw_after = self._handle("gamestate", {})
        if shop_playing_card is not None and self._sync_shop_playing_card_count(
            shop_playing_card
        ):
            raw_after = self._handle("gamestate", {})
        if voucher_effect is not None and self._apply_immediate_voucher_effect(
            voucher_effect
        ):
            raw_after = self._handle("gamestate", {})
        if method == "skip" and self._defer_economy_tag_dollars(raw_before):
            raw_after = self._handle("gamestate", {})
        if method == "next_round" and raw_after.get("state") == "BLIND_SELECT":
            self._initialize_orbital_choices()
        if method == "play" and raw_after.get("state") == "ROUND_EVAL":
            self._clear_crimson_heart_debuffs_at_round_end()
            self._roll_round_targets()
            self._round_targets_rolled = True
            raw_after = self._handle("gamestate", {})
        self._won = self._won or raw_after.get("won") is True
        if self._won and raw_after.get("won") is not True:
            game_state = getattr(self._backend, "_gs", None)
            if not isinstance(game_state, dict):
                raise RuntimeError(
                    "Jackdaw game state is unavailable after an Endless loss"
                )
            game_state["won"] = True
            raw_after = self._handle("gamestate", {})
        after = self._observation(raw_after)
        self._current = after
        return StepResult(
            status="accepted",
            action=action,
            before=before,
            rpc_method=method,
            rpc_params=params,
            rpc_observations=() if self.lightweight else (after.observed.raw_json,),
            after=after,
        )

    def _reroll_boss_compatibility(self) -> dict[str, Any]:
        """Execute vanilla Director's Cut/Retcon semantics in pinned Jackdaw."""

        from jackdaw.engine.actions import GamePhase
        from jackdaw.engine.blind import get_new_boss

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            raise RuntimeError("Jackdaw game state is unavailable for boss reroll")
        if game_state.get("phase") != GamePhase.BLIND_SELECT:
            raise self._rpc_error(-32002, "Boss reroll requires BLIND_SELECT")
        round_resets = game_state.get("round_resets")
        used_vouchers = game_state.get("used_vouchers")
        if not isinstance(round_resets, dict) or not isinstance(used_vouchers, Mapping):
            raise RuntimeError("Jackdaw boss-reroll state is incomplete")
        available = int(game_state.get("dollars", 0)) - int(
            game_state.get("bankrupt_at", 0)
        )
        retcon = bool(used_vouchers.get("v_retcon"))
        directors_cut = bool(used_vouchers.get("v_directors_cut"))
        if available < 10:
            raise self._rpc_error(-32003, "Cannot afford boss reroll")
        if not retcon and not (
            directors_cut and round_resets.get("boss_rerolled") is False
        ):
            raise self._rpc_error(-32003, "Boss reroll voucher is unavailable")
        rng = game_state.get("rng")
        if rng is None:
            raise RuntimeError("Jackdaw boss-reroll RNG is unavailable")
        bosses_used = game_state.setdefault("bosses_used", {})
        if not isinstance(bosses_used, dict):
            raise RuntimeError("Jackdaw boss usage state is invalid")

        game_state["dollars"] = int(game_state.get("dollars", 0)) - 10
        round_resets["boss_rerolled"] = True
        round_resets.setdefault("blind_choices", {})["Boss"] = get_new_boss(
            int(round_resets.get("ante", 1)),
            bosses_used,
            rng,
            win_ante=game_state.get("win_ante", 8),
        )
        return self._backend.handle("gamestate", {})

    def _buy_and_use_planet_compatibility(
        self, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Mirror vanilla's atomic shop Planet buy-and-use transaction."""

        from jackdaw.engine.actions import GamePhase
        from jackdaw.engine.consumables import _PLANET_HAND, can_use_consumable
        from jackdaw.engine.data.hands import HandType
        from jackdaw.engine.game import (
            _fire_shop_joker_context,
            _release_used_key,
            _use_consumable_card,
        )
        from jackdaw.engine.shop import reprice_shop

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            raise RuntimeError("Jackdaw game state is unavailable for buy-and-use")
        if game_state.get("phase") != GamePhase.SHOP:
            raise self._rpc_error(-32002, "Buy-and-use requires SHOP")
        index = params.get("card")
        shop_cards = game_state.get("shop_cards")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not isinstance(shop_cards, list)
            or not 0 <= index < len(shop_cards)
        ):
            raise self._rpc_error(-32602, "Invalid buy-and-use shop index")
        card = shop_cards[index]
        ability = getattr(card, "ability", None)
        planet_hand = _PLANET_HAND.get(getattr(card, "center_key", None))
        if (
            not isinstance(ability, dict)
            or ability.get("set") != "Planet"
            or planet_hand is None
        ):
            raise self._rpc_error(-32003, "Buy-and-use supports known Planets only")
        dollars = game_state.get("dollars")
        bankrupt_at = game_state.get("bankrupt_at")
        cost = getattr(card, "cost", None)
        if (
            not isinstance(dollars, int)
            or isinstance(dollars, bool)
            or not isinstance(bankrupt_at, int)
            or isinstance(bankrupt_at, bool)
            or not isinstance(cost, int)
            or isinstance(cost, bool)
            or dollars - cost < bankrupt_at
        ):
            raise self._rpc_error(-32003, "Cannot afford buy-and-use Planet")
        consumables = game_state.get("consumables")
        jokers = game_state.get("jokers")
        if not isinstance(consumables, list) or not isinstance(jokers, list):
            raise RuntimeError("Jackdaw buy-and-use inventory state is invalid")
        if not can_use_consumable(
            card,
            highlighted=[],
            hand_cards=game_state.get("hand", []),
            jokers=jokers,
            consumables=consumables,
            joker_limit=game_state.get("joker_slots", 5),
            consumable_limit=game_state.get("consumable_slots", 2),
            game_state=game_state,
        ):
            raise self._rpc_error(-32003, "Planet cannot be bought and used")
        hand_levels = game_state.get("hand_levels")
        if hand_levels is None:
            raise RuntimeError("Jackdaw hand levels are unavailable for buy-and-use")
        hand_type = HandType(planet_hand)
        initial_level = hand_levels.get_state(hand_type).level
        initial_shop_count = len(shop_cards)
        initial_consumable_count = len(consumables)
        initial_consumable_slots = game_state.get("consumable_slots")
        initial_cards_purchased = game_state.get("cards_purchased", 0)
        if (
            not isinstance(initial_consumable_slots, int)
            or isinstance(initial_consumable_slots, bool)
            or not isinstance(initial_cards_purchased, int)
            or isinstance(initial_cards_purchased, bool)
        ):
            raise RuntimeError("Jackdaw buy-and-use accounting state is invalid")

        snapshot = deepcopy(game_state)
        try:
            shop_cards.pop(index)
            card.add_to_deck(game_state)
            # Pinned Jackdaw's JokerContext has no purchased-card field; none of
            # its implemented buying-card effects consumes that identity.
            _fire_shop_joker_context(game_state, buying_card=True)
            game_state["cards_purchased"] = initial_cards_purchased + 1
            if game_state.get("inflation_modifier"):
                game_state["inflation"] = int(game_state.get("inflation", 0)) + 1
                reprice_shop(game_state)
            game_state["dollars"] = dollars - cost
            _use_consumable_card(game_state, card)
            card.remove_from_deck(game_state)
            _release_used_key(game_state, card)

            if (
                len(shop_cards) != initial_shop_count - 1
                or len(consumables) != initial_consumable_count
                or game_state.get("consumable_slots") != initial_consumable_slots
                or game_state.get("dollars") != dollars - cost
                or game_state.get("cards_purchased") != initial_cards_purchased + 1
                or game_state.get("last_tarot_planet") != card.center_key
                or hand_levels.get_state(hand_type).level != initial_level + 1
            ):
                raise RuntimeError("Jackdaw buy-and-use postcondition mismatch")
        except BaseException:
            game_state.clear()
            game_state.update(snapshot)
            raise
        return self._backend.handle("gamestate", {})

    def close(self) -> None:
        self._handle("menu", {})
        self._current = None
        self._round_targets_rolled = False
        self._stale_shop_areas = None
        self._pending_ante_setup = None
        self._poker_hand_iteration_order = None
        self._active_pack_cards = None
        self._pack_card_limit = None
        self._won = False
        self._pending_skip_dollars = 0
        self._lightweight_normalized = None

    def _handle(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        terminal_turtle_snapshot = self._terminal_turtle_bean_snapshot(method)
        with (
            self._poker_hand_order_compatibility(),
            self._shop_sticker_stake_compatibility(),
            self._standard_pack_cost_compatibility(),
            self._original_suit_nominal_compatibility(),
            self._secret_hand_visibility_compatibility(),
            self._crimson_heart_order_compatibility(method),
        ):
            with self._credit_compatibility(method, params) as used_credit:
                raw = self._backend.handle(method, params)
                if method == "play" and raw.get("state") == "GAME_OVER":
                    self._defer_terminal_rental_charge()
                    self._restore_terminal_turtle_bean(terminal_turtle_snapshot)
                    raw = self._backend.handle("gamestate", {})
            return self._backend.handle("gamestate", {}) if used_credit else raw

    @contextmanager
    def _crimson_heart_order_compatibility(self, method: str) -> Iterator[None]:
        """Select Crimson Heart's Joker by creation order, as vanilla does."""

        from jackdaw.engine.blind import Blind

        original_drawn_to_hand = Blind.drawn_to_hand

        def vanilla_drawn_to_hand(
            blind: Any,
            hand_cards: list[Any],
            joker_cards: list[Any] | None = None,
            rng: Any | None = None,
        ) -> dict[str, Any]:
            if getattr(blind, "name", None) != "Crimson Heart":
                return original_drawn_to_hand(blind, hand_cards, joker_cards, rng)
            if getattr(blind, "disabled", False):
                blind.prepped = False
                return {}
            if method != "select" and not getattr(blind, "prepped", False):
                return {}

            result: dict[str, Any] = {}
            if rng is not None and joker_cards:
                eligible = [
                    joker
                    for joker in joker_cards
                    if not getattr(joker, "debuff", False) or len(joker_cards) < 2
                ]
                for joker in joker_cards:
                    set_debuff = getattr(joker, "set_debuff", None)
                    if not callable(set_debuff):
                        raise RuntimeError(
                            "Jackdaw Crimson Heart Joker cannot be debuffed"
                        )
                    set_debuff(False)
                if eligible:
                    chosen, _ = rng.element(eligible, rng.seed("crimson_heart"))
                    chosen.set_debuff(True)
                    result["debuffed_joker_index"] = next(
                        index
                        for index, joker in enumerate(joker_cards)
                        if joker is chosen
                    )
            blind.prepped = False
            return result

        with _JACKDAW_PATCH_LOCK:
            Blind.drawn_to_hand = vanilla_drawn_to_hand
            try:
                yield
            finally:
                Blind.drawn_to_hand = original_drawn_to_hand

    def _defer_terminal_rental_charge(self) -> None:
        """Match the authority snapshot before queued Rental dollar events run."""

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            raise RuntimeError("Jackdaw game state is unavailable at game over")
        jokers = game_state.get("jokers")
        dollars = game_state.get("dollars")
        rental_rate = game_state.get("rental_rate")
        if (
            not isinstance(jokers, list)
            or not isinstance(dollars, int)
            or isinstance(dollars, bool)
            or not isinstance(rental_rate, int)
            or isinstance(rental_rate, bool)
            or rental_rate < 0
        ):
            raise RuntimeError("Jackdaw Rental state is invalid at game over")
        rental_count = 0
        for joker in jokers:
            ability = getattr(joker, "ability", None)
            is_rental = getattr(joker, "rental", False) or (
                isinstance(ability, Mapping) and ability.get("rental") is True
            )
            rental_count += int(is_rental)
        game_state["dollars"] = dollars + rental_rate * rental_count

    def _terminal_turtle_bean_snapshot(
        self, method: str
    ) -> int | None:
        """Capture non-expiring Turtle Bean state before a possible loss."""

        if method != "play":
            return None
        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw game state is unavailable before play")
        hand_size = game_state.get("hand_size")
        jokers = game_state.get("jokers")
        if not isinstance(hand_size, int) or isinstance(hand_size, bool):
            raise RuntimeError("Jackdaw hand size is unavailable before play")
        if not isinstance(jokers, list):
            raise RuntimeError("Jackdaw Joker state is unavailable before play")
        for card in jokers:
            if getattr(card, "center_key", None) != "j_turtle_bean":
                continue
            ability = getattr(card, "ability", None)
            extra = ability.get("extra") if isinstance(ability, Mapping) else None
            if not isinstance(extra, dict) or not isinstance(extra.get("h_size"), int):
                raise RuntimeError("Jackdaw Turtle Bean state is unavailable before play")
            if int(extra["h_size"]) <= int(extra.get("h_mod", 1)):
                continue
            return hand_size
        return None

    def _restore_terminal_turtle_bean(
        self,
        snapshot: int | None,
    ) -> None:
        """Keep queued Turtle Bean decay out of the immediate loss snapshot."""

        if snapshot is None:
            return
        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            raise RuntimeError("Jackdaw terminal Turtle Bean state is unavailable")
        game_state["hand_size"] = snapshot

    def _apply_pending_skip_dollars(self) -> None:
        if not self._pending_skip_dollars:
            return
        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict) or not isinstance(
            game_state.get("dollars"), int
        ):
            raise RuntimeError("Jackdaw delayed skip-tag money state is invalid")
        game_state["dollars"] += self._pending_skip_dollars
        self._pending_skip_dollars = 0

    def _defer_economy_tag_dollars(self, raw_before: Mapping[str, Any]) -> bool:
        """Match Economy Tag's queued payout appearing on the next action."""

        blinds = raw_before.get("blinds")
        if not isinstance(blinds, Mapping):
            raise RuntimeError("Jackdaw blind state is unavailable before skip")
        selected = next(
            (
                blind
                for blind in blinds.values()
                if isinstance(blind, Mapping) and blind.get("status") == "SELECT"
            ),
            None,
        )
        if (
            not isinstance(selected, Mapping)
            or selected.get("tag_name") != "Economy Tag"
        ):
            return False
        game_state = getattr(self._backend, "_gs", None)
        before_dollars = raw_before.get("money")
        if (
            not isinstance(game_state, dict)
            or not isinstance(before_dollars, int)
            or isinstance(before_dollars, bool)
            or not isinstance(game_state.get("dollars"), int)
        ):
            raise RuntimeError("Jackdaw Economy Tag money state is invalid")
        delta = game_state["dollars"] - before_dollars
        if delta < 0:
            raise RuntimeError("Jackdaw Economy Tag reduced dollars")
        game_state["dollars"] = before_dollars
        self._pending_skip_dollars = delta
        return True

    def _clear_crimson_heart_debuffs_at_round_end(self) -> None:
        """Match the defeated boss clearing its transient Joker debuff."""

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            raise RuntimeError("Jackdaw game state is unavailable at round end")
        blind = game_state.get("blind")
        if getattr(blind, "name", None) != "Crimson Heart":
            return
        jokers = game_state.get("jokers")
        if not isinstance(jokers, list):
            raise RuntimeError(
                "Jackdaw Joker state is invalid at Crimson Heart round end"
            )
        for joker in jokers:
            ability = getattr(joker, "ability", None)
            if ability is not None and not isinstance(ability, Mapping):
                raise RuntimeError(
                    "Jackdaw Joker ability is invalid at Crimson Heart round end"
                )
            perishable = getattr(joker, "perishable", False) or (
                isinstance(ability, Mapping) and ability.get("perishable") is True
            )
            perish_tally = (
                ability["perish_tally"]
                if isinstance(ability, Mapping) and "perish_tally" in ability
                else getattr(joker, "perish_tally", 0)
            )
            if perishable:
                if not isinstance(perish_tally, int) or isinstance(perish_tally, bool):
                    raise RuntimeError(
                        "Jackdaw Perishable tally is invalid at Crimson Heart round end"
                    )
                if perish_tally <= 0:
                    continue
            set_debuff = getattr(joker, "set_debuff", None)
            if not callable(set_debuff):
                raise RuntimeError(
                    "Jackdaw Joker cannot clear its Crimson Heart debuff"
                )
            set_debuff(False)

    @contextmanager
    def _shop_sticker_stake_compatibility(self) -> Iterator[None]:
        """Expose Jackdaw's nested stake flags where its card factory reads them."""

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            yield
            return
        modifiers = game_state.get("modifiers")
        if not isinstance(modifiers, Mapping):
            yield
            return

        keys = (
            "enable_eternals_in_shop",
            "enable_perishables_in_shop",
            "enable_rentals_in_shop",
        )
        inserted: list[str] = []
        for key in keys:
            nested = modifiers.get(key, False)
            if not isinstance(nested, bool):
                raise RuntimeError(f"Jackdaw stake modifier {key!r} is not boolean")
            if key in game_state:
                if game_state[key] is not nested:
                    raise RuntimeError(
                        f"Jackdaw stake modifier {key!r} is inconsistent"
                    )
                continue
            game_state[key] = nested
            inserted.append(key)
        try:
            yield
        finally:
            for key in inserted:
                game_state.pop(key, None)

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
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or not isinstance(cards, list)
            ):
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
                        raise RuntimeError(
                            "Jackdaw Orbital Tag choice was not initialized"
                        )
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

    @contextmanager
    def _original_suit_nominal_compatibility(self) -> Iterator[None]:
        """Preserve vanilla's original-suit hand-sort tiebreaker."""

        from jackdaw.engine.card import Card

        original_set_base = Card.set_base

        def vanilla_set_base(
            card: Any,
            card_key: str,
            suit: str,
            value: str,
        ) -> None:
            base = getattr(card, "base", None)
            original_suit = getattr(base, "suit_nominal_original", None)
            original_set_base(card, card_key, suit, value)
            if original_suit is not None:
                card.base.suit_nominal_original = original_suit

        with _JACKDAW_PATCH_LOCK:
            Card.set_base = vanilla_set_base
            try:
                yield
            finally:
                Card.set_base = original_set_base

    @contextmanager
    def _secret_hand_visibility_compatibility(self) -> Iterator[None]:
        """Reveal a secret poker hand when vanilla first records its play."""

        from jackdaw.engine.hand_levels import HandLevels

        original_record_play = HandLevels.record_play

        def vanilla_record_play(hand_levels: Any, hand_type: Any) -> None:
            original_record_play(hand_levels, hand_type)
            hand_levels.get_state(hand_type).visible = True

        with _JACKDAW_PATCH_LOCK:
            HandLevels.record_play = vanilla_record_play
            try:
                yield
            finally:
                HandLevels.record_play = original_record_play

    def _observation(self, raw: dict[str, Any]) -> AuthorityObservation:
        # Both adapters must pass independently.  The public conversion catches
        # leaks/unsupported shapes; canonicalization catches semantic drift.
        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        _refresh_deck_enhancements(game_state)
        _refresh_swashbuckler_mult(game_state)
        _refresh_stencil_x_mult(game_state)
        _refresh_drivers_license_tally(game_state)
        pack_card_limit = self._track_pack_card_limit(game_state)
        normalized = _normalize_jackdaw_bridge(
            raw,
            game_state,
            self._stale_shop_areas,
            self._poker_hand_iteration_order,
            pack_card_limit,
            copy_raw=not self.lightweight,
        )
        self.current_public = to_public_observation(normalized)
        if self.lightweight:
            # The normalized bridge frame is private rollout state. Lightweight
            # clones own it directly; hash-chained JSON belongs only to traces.
            self._lightweight_normalized = normalized
            observed = CanonicalObservedState(
                raw_json="", canonical_json="", raw_digest="", canonical_digest=""
            )
            return AuthorityObservation(observed=observed, settled=True, polls=())
        self._lightweight_normalized = None
        observed = self.canonicalizer.canonicalize(normalized)
        return AuthorityObservation(
            observed=observed, settled=True, polls=(observed.raw_json,)
        )

    def _track_pack_card_limit(self, game_state: Mapping[str, Any]) -> int | None:
        pack_cards = game_state.get("pack_cards")
        if pack_cards is None:
            self._active_pack_cards = None
            self._pack_card_limit = None
            return None
        if not isinstance(pack_cards, list):
            raise RuntimeError("Jackdaw pack state is unavailable")
        if not pack_cards:
            self._active_pack_cards = None
            self._pack_card_limit = None
            return None
        if pack_cards is not self._active_pack_cards:
            self._active_pack_cards = pack_cards
            self._pack_card_limit = len(pack_cards)
        return self._pack_card_limit

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
        if not all(
            isinstance(item, Mapping)
            for item in (current_round, round_resets, round_bonus)
        ):
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
        _clear_completed_cerulean_forced_selections(game_state)

    def _selected_standard_pack_card(
        self, method: str, params: Mapping[str, Any]
    ) -> object | None:
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

    def _pack_cryptid_copy_snapshot(
        self,
        method: str,
        params: Mapping[str, Any],
    ) -> tuple[frozenset[int], int] | None:
        """Capture permanent identities before a Cryptid is used from a pack."""

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
        cryptid = pack_cards[index]
        if getattr(cryptid, "center_key", None) != "c_cryptid":
            return None
        ability = getattr(cryptid, "ability", None)
        copy_count = ability.get("extra") if isinstance(ability, Mapping) else None
        if (
            not isinstance(copy_count, int)
            or isinstance(copy_count, bool)
            or copy_count < 1
        ):
            raise RuntimeError("Jackdaw Cryptid copy count is unavailable")
        identities: set[int] = set()
        for area_name in ("deck", "hand", "discard_pile", "play"):
            cards = game_state.get(area_name, [])
            if not isinstance(cards, list):
                raise RuntimeError(f"Jackdaw {area_name} state is unavailable")
            identities.update(id(card) for card in cards)
        return frozenset(identities), copy_count

    def _place_pack_cryptid_copies(
        self,
        snapshot: tuple[frozenset[int], int],
    ) -> bool:
        """Mirror pack-close hand-to-deck order for fresh Cryptid copies."""

        previous, expected_copies = snapshot
        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        deck = game_state.get("deck")
        if not isinstance(deck, list):
            raise RuntimeError("Jackdaw deck state is unavailable after Cryptid")
        copies = [card for card in deck if id(card) not in previous]
        if len(copies) != expected_copies:
            raise RuntimeError("Jackdaw did not create the expected Cryptid copies")
        deck[:] = [card for card in deck if id(card) in previous]
        deck[:0] = reversed(copies)

        identities: set[int] = set()
        for area_name in ("deck", "hand", "discard_pile", "play"):
            cards = game_state.get(area_name, [])
            if not isinstance(cards, list):
                raise RuntimeError(f"Jackdaw {area_name} state is unavailable")
            identities.update(id(card) for card in cards)
        game_state["playing_cards_count"] = len(identities)
        return True

    def _selected_shop_playing_card(
        self, method: str, params: Mapping[str, Any]
    ) -> object | None:
        """Capture a visible playing-card offer before the buy removes it."""

        if method != "buy":
            return None
        index = params.get("card")
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        shop_cards = game_state.get("shop_cards")
        if not isinstance(shop_cards, list) or not 0 <= index < len(shop_cards):
            return None
        card = shop_cards[index]
        ability = getattr(card, "ability", None)
        card_set = ability.get("set") if isinstance(ability, Mapping) else None
        return card if card_set in {"Default", "Enhanced"} else None

    def _selected_boss_disabling_sale(
        self,
        method: str,
        params: Mapping[str, Any],
    ) -> bool:
        """Capture a sale that disables the live boss before card removal.

        Jackdaw's generic sell path omits both Luchador's ``selling_self``
        mutation and Verdant Leaf's "sell one Joker" callback.  Resolve the
        sold Joker while its index is still valid, then apply the shared boss
        transition after the normal sale has completed.
        """

        if method != "sell":
            return False
        index = params.get("joker")
        if not isinstance(index, int) or isinstance(index, bool):
            return False
        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw game state is unavailable before Joker sale")
        jokers = game_state.get("jokers")
        if not isinstance(jokers, list) or not 0 <= index < len(jokers):
            raise RuntimeError("Jackdaw Joker state is invalid before Joker sale")
        if getattr(jokers[index], "center_key", None) == "j_luchador":
            return True
        blind = game_state.get("blind")
        return bool(
            blind is not None
            and getattr(blind, "boss", False)
            and not getattr(blind, "disabled", False)
            and getattr(blind, "name", None) == "Verdant Leaf"
        )

    def _apply_boss_disable_sale_compatibility(self) -> bool:
        """Apply a vanilla sale-triggered boss disable omitted by Jackdaw."""

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, dict):
            raise RuntimeError(
                "Jackdaw game state is unavailable after boss-disabling sale"
            )
        blind = game_state.get("blind")
        if blind is None:
            raise RuntimeError(
                "Jackdaw blind state is unavailable after boss-disabling sale"
            )
        if not getattr(blind, "boss", False) or getattr(blind, "disabled", False):
            return False

        area_names = ("deck", "hand", "discard_pile", "play")
        areas: list[list[Any]] = []
        for name in area_names:
            cards = game_state.get(name, [])
            if not isinstance(cards, list):
                raise RuntimeError(
                    f"Jackdaw {name} state is invalid after boss-disabling sale"
                )
            areas.append(cards)
        playing_cards: list[Any] = []
        for area in areas:
            for card in area:
                if not any(card is existing for existing in playing_cards):
                    playing_cards.append(card)
        jokers = game_state.get("jokers")
        current_round = game_state.get("current_round")
        if not isinstance(jokers, list) or not isinstance(current_round, dict):
            raise RuntimeError(
                "Jackdaw round state is invalid after boss-disabling sale"
            )
        disable = getattr(blind, "disable", None)
        if not callable(disable):
            raise RuntimeError(
                "Jackdaw boss cannot be disabled after boss-disabling sale"
            )
        result = disable(playing_cards=playing_cards, joker_cards=jokers)
        if not isinstance(result, Mapping):
            raise RuntimeError("Jackdaw boss disable result is invalid")

        for result_key, round_key in (
            ("restore_discards", "discards_left"),
            ("restore_hands", "hands_left"),
        ):
            amount = result.get(result_key, 0)
            current = current_round.get(round_key)
            if (
                not isinstance(amount, int)
                or isinstance(amount, bool)
                or not isinstance(current, int)
                or isinstance(current, bool)
            ):
                raise RuntimeError(f"Jackdaw {result_key} state is invalid")
            current_round[round_key] = current + amount

        hand_size_delta = result.get("restore_hand_size", 0)
        hand_size = game_state.get("hand_size")
        if (
            not isinstance(hand_size_delta, int)
            or isinstance(hand_size_delta, bool)
            or not isinstance(hand_size, int)
            or isinstance(hand_size, bool)
        ):
            raise RuntimeError(
                "Jackdaw hand-size state is invalid after boss-disabling sale"
            )
        game_state["hand_size"] = hand_size + hand_size_delta

        if result.get("clear_forced", False):
            for card in playing_cards:
                ability = getattr(card, "ability", None)
                if not isinstance(ability, dict):
                    raise RuntimeError("Jackdaw playing-card ability is invalid")
                ability.pop("forced_selection", None)

        if getattr(blind, "name", None) in {
            "The Wheel",
            "The House",
            "The Mark",
            "The Fish",
        }:
            for card in game_state["hand"]:
                card.facing = "front"
            for card in playing_cards:
                ability = getattr(card, "ability", None)
                if not isinstance(ability, dict):
                    raise RuntimeError("Jackdaw playing-card ability is invalid")
                ability.pop("wheel_flipped", None)

        for joker in jokers:
            joker.facing = "front"
            if getattr(blind, "name", None) == "Crimson Heart":
                ability = getattr(joker, "ability", None)
                if not isinstance(ability, dict):
                    raise RuntimeError("Jackdaw Joker ability is invalid")
                ability.pop("crimson_heart_chosen", None)
        return True

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
            raise RuntimeError(
                "Jackdaw current-round state is unavailable before voucher purchase"
            )
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
            raise RuntimeError(
                f"Jackdaw current-round {field} is unavailable before voucher purchase"
            )
        return field, before, delta

    def _apply_immediate_voucher_effect(self, effect: tuple[str, int, int]) -> bool:
        field, before, delta = effect
        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        current_round = game_state.get("current_round")
        if not isinstance(current_round, dict):
            raise RuntimeError(
                "Jackdaw current-round state is unavailable after voucher purchase"
            )
        actual = current_round.get(field)
        expected = before + delta
        if actual == expected:
            return False
        if actual != before:
            raise RuntimeError(
                f"Jackdaw {field} changed unexpectedly during voucher purchase"
            )
        current_round[field] = expected
        return True

    def _place_standard_pack_card(self, card: object) -> bool:
        """Match ``G.deck:emplace``: a picked playing card goes to the deck front."""

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        deck = game_state.get("deck")
        if not isinstance(deck, list):
            raise RuntimeError(
                "Jackdaw deck state is unavailable after Standard-pack pick"
            )
        indices = [index for index, candidate in enumerate(deck) if candidate is card]
        if len(indices) != 1:
            raise RuntimeError(
                "Jackdaw did not add the selected Standard-pack card exactly once"
            )
        playing_cards_count = game_state.get("playing_cards_count")
        if not isinstance(playing_cards_count, int):
            raise RuntimeError(
                "Jackdaw playing-card count is unavailable after Standard-pack pick"
            )
        piles = (deck, game_state.get("hand"), game_state.get("discard_pile"))
        if not all(isinstance(pile, list) for pile in piles):
            raise RuntimeError(
                "Jackdaw playing-card piles are unavailable after Standard-pack pick"
            )
        expected_count = sum(len(pile) for pile in piles)
        changed = playing_cards_count != expected_count
        game_state["playing_cards_count"] = expected_count
        index = indices[0]
        if index == 0:
            return changed
        deck.insert(0, deck.pop(index))
        return True

    def _sync_shop_playing_card_count(self, card: object) -> bool:
        """Include a bought shop card in the permanent public deck size."""

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        piles = (
            game_state.get("deck"),
            game_state.get("hand"),
            game_state.get("discard_pile"),
        )
        if not all(isinstance(pile, list) for pile in piles):
            raise RuntimeError(
                "Jackdaw playing-card piles are unavailable after shop purchase"
            )
        if sum(candidate is card for pile in piles for candidate in pile) != 1:
            raise RuntimeError(
                "Jackdaw did not add the bought shop playing card exactly once"
            )
        playing_cards_count = game_state.get("playing_cards_count")
        if not isinstance(playing_cards_count, int) or isinstance(
            playing_cards_count, bool
        ):
            raise RuntimeError(
                "Jackdaw playing-card count is unavailable after shop purchase"
            )
        expected_count = sum(len(pile) for pile in piles)
        changed = playing_cards_count != expected_count
        game_state["playing_cards_count"] = expected_count
        return changed

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
                    raise RuntimeError(
                        "Jackdaw Hook discarded a card absent from the pre-play hand"
                    )
                discarded = sorted(discarded, key=lambda card: hand_positions[id(card)])
            original_fire_discard_effects(state, discarded, hook=hook)

        with _JACKDAW_PATCH_LOCK:
            game._fire_discard_effects = vanilla_fire_discard_effects
            try:
                yield
            finally:
                game._fire_discard_effects = original_fire_discard_effects

    @contextmanager
    def _observatory_scoring_compatibility(self) -> Iterator[None]:
        """Apply held-Planet xMult after Jokers and before the deck back."""

        from jackdaw.engine import scoring
        from jackdaw.engine.back import Back
        from jackdaw.engine.consumables import _PLANET_HAND
        from jackdaw.engine.hand_eval import evaluate_hand

        game_state = getattr(self._backend, "_gs", None)
        if not isinstance(game_state, Mapping):
            raise RuntimeError("Jackdaw backend does not expose its active game state")
        original_score_hand = scoring.score_hand

        def score_with_observatory(*args: Any, **kwargs: Any) -> Any:
            played_cards = kwargs.get("played_cards", args[0] if args else None)
            jokers = kwargs.get("jokers", args[2] if len(args) > 2 else None)
            if not isinstance(played_cards, list) or not isinstance(jokers, list):
                raise RuntimeError("Jackdaw scoring inputs are unavailable")
            used_vouchers = game_state.get("used_vouchers")
            if not isinstance(used_vouchers, Mapping):
                raise RuntimeError("Jackdaw used-voucher state is unavailable")
            observatory = used_vouchers.get("v_observatory", False)
            if not isinstance(observatory, bool):
                raise RuntimeError("Jackdaw Observatory state is invalid")
            if not observatory:
                return original_score_hand(*args, **kwargs)

            consumables = game_state.get("consumables")
            if not isinstance(consumables, list):
                raise RuntimeError("Jackdaw consumable state is unavailable")
            hand_name = evaluate_hand(played_cards, jokers=jokers).detected_hand
            matching_planets = 0
            for consumable in consumables:
                key = getattr(consumable, "center_key", None)
                if key not in _PLANET_HAND:
                    continue
                debuffed = getattr(consumable, "debuff", None)
                if not isinstance(debuffed, bool):
                    raise RuntimeError("Jackdaw Planet debuff state is unavailable")
                if not debuffed and _PLANET_HAND[key] == hand_name:
                    matching_planets += 1
            if matching_planets == 0:
                return original_score_hand(*args, **kwargs)

            factor = 1.5**matching_planets
            original_trigger_effect = Back.trigger_effect

            def trigger_with_observatory(
                back: Any,
                context: str,
                **trigger_kwargs: Any,
            ) -> dict[str, Any] | None:
                if context != "final_scoring_step":
                    return original_trigger_effect(back, context, **trigger_kwargs)
                chips = trigger_kwargs.get("chips")
                mult = trigger_kwargs.get("mult")
                if not isinstance(chips, int | float) or isinstance(chips, bool):
                    raise RuntimeError("Jackdaw final scoring chips are invalid")
                if not isinstance(mult, int | float) or isinstance(mult, bool):
                    raise RuntimeError("Jackdaw final scoring Mult is invalid")
                multiplied = mult * factor
                effect = original_trigger_effect(
                    back,
                    context,
                    chips=chips,
                    mult=multiplied,
                )
                return effect or {"chips": chips, "mult": multiplied}

            Back.trigger_effect = trigger_with_observatory
            try:
                return original_score_hand(*args, **kwargs)
            finally:
                Back.trigger_effect = original_trigger_effect

        with _JACKDAW_PATCH_LOCK:
            scoring.score_hand = score_with_observatory
            try:
                yield
            finally:
                scoring.score_hand = original_score_hand

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
            raise RuntimeError(
                "Jackdaw hand-level state is unavailable at ante advance"
            )
        if not isinstance(round_resets, dict) or rng is None:
            raise RuntimeError("Jackdaw ante/RNG state is unavailable at ante advance")
        if self._pending_ante_setup is not None:
            raise RuntimeError(
                f"Jackdaw ante {self._pending_ante_setup} setup is already pending"
            )

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
            raise RuntimeError(
                f"pending ante {pending_ante} does not match active ante {ante}"
            )
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
            _mirror_duplicate_booster_emplacement(populate_state)
            populate_state["shop_voucher_limit"] = max(
                1,
                len(populate_state.get("shop_vouchers", [])),
            )
            self._pending_ante_setup = None

        with _JACKDAW_PATCH_LOCK:
            round_lifecycle.reset_round_targets = lambda *_args, **_kwargs: None
            game._populate_shop = vanilla_populate_shop
            try:
                yield
            finally:
                round_lifecycle.reset_round_targets = original_reset
                game._populate_shop = original_populate_shop


def _mirror_duplicate_booster_emplacement(game_state: dict[str, Any]) -> None:
    """Mirror vanilla CardArea order for two physically identical boosters."""

    boosters = game_state.get("shop_boosters")
    if not isinstance(boosters, list) or len(boosters) != 2:
        return
    first, second = boosters
    if (
        getattr(first, "center_key", None) == getattr(second, "center_key", None)
        and getattr(first, "center_key", None) is not None
        and getattr(first, "cost", None) == getattr(second, "cost", None)
    ):
        boosters.reverse()


def _normalize_jackdaw_bridge(
    raw: dict[str, Any],
    game_state: object,
    stale_shop_areas: Mapping[str, Mapping[str, Any]] | None = None,
    poker_hand_iteration_order: tuple[str, ...] | None = None,
    pack_card_limit: int | None = None,
    *,
    copy_raw: bool = True,
) -> dict[str, Any]:
    """Translate Jackdaw serializer defaults into BalatroBot's observed schema.

    This function may normalize representation only. Values come from
    Jackdaw's actual state; it must never invent a result to satisfy a trace.
    """

    result = deepcopy(raw) if copy_raw else raw
    private = game_state if isinstance(game_state, Mapping) else {}
    result["deck_composition"] = _jackdaw_deck_composition(private)
    pack_choices = private.get("pack_choices_remaining", 0)
    if (
        not isinstance(pack_choices, int)
        or isinstance(pack_choices, bool)
        or pack_choices < 0
    ):
        raise RuntimeError("Jackdaw pack choice count is unavailable")
    result["pack_choices_remaining"] = pack_choices
    last_tarot_planet = private.get("last_tarot_planet")
    if last_tarot_planet is not None and not isinstance(last_tarot_planet, str):
        raise RuntimeError("Jackdaw last Tarot/Planet state is invalid")
    result["last_tarot_planet"] = last_tarot_planet or ""
    if poker_hand_iteration_order is None:
        poker_hand_iteration_order = _DEFAULT_POKER_HAND_ITERATION_ORDER
    result["poker_hand_iteration_order"] = list(poker_hand_iteration_order)
    blinds = result.get("blinds")
    if not isinstance(blinds, Mapping):
        raise RuntimeError("Jackdaw blind observations are unavailable")
    current_blinds: list[dict[str, Any]] = []
    for blind in blinds.values():
        if not isinstance(blind, dict):
            raise RuntimeError("Jackdaw blind observation is invalid")
        blind["disabled"] = False
        if blind.get("status") == "CURRENT":
            current_blinds.append(blind)
    if len(current_blinds) > 1:
        raise RuntimeError("Jackdaw exposes multiple current blinds")
    if current_blinds:
        private_blind = private.get("blind")
        disabled = getattr(private_blind, "disabled", None)
        private_name = getattr(private_blind, "name", None)
        if not isinstance(disabled, bool):
            raise RuntimeError("Jackdaw current blind disabled state is unavailable")
        if private_name != current_blinds[0].get("name"):
            raise RuntimeError("Jackdaw current blind identity is out of sync")
        current_blinds[0]["disabled"] = disabled
    discard_pile = private.get("discard_pile")
    if not isinstance(discard_pile, list):
        raise RuntimeError("Jackdaw discard pile is unavailable")
    if discard_pile:
        from jackdaw.bridge.serializer import serialize_area

        result["discard"] = serialize_area(discard_pile, 500, 5)
    else:
        result["discard"] = {
            "cards": [],
            "count": 0,
            "highlighted_limit": 5,
            "limit": 500,
        }
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
        composition = result.get("deck_composition")
        if not isinstance(composition, list):
            raise RuntimeError("Jackdaw permanent deck composition is unavailable")
        permanent_deck_size = sum(
            entry.get("count", 0)
            for entry in composition
            if isinstance(entry, Mapping)
        )
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
        if not isinstance(private_cards, list) or len(private_cards) != len(
            area["cards"]
        ):
            raise RuntimeError(
                f"Jackdaw {area_name} serializer is out of sync with engine state"
            )
        if area_name == "shop":
            shop_config = private.get("shop")
            if not isinstance(shop_config, Mapping) or not isinstance(
                shop_config.get("joker_max"), int
            ):
                raise RuntimeError("Jackdaw shop capacity is unavailable")
            area["limit"] = shop_config["joker_max"]
        elif area_name == "vouchers":
            voucher_limit = private.get("shop_voucher_limit")
            if not isinstance(voucher_limit, int):
                raise RuntimeError("Jackdaw voucher capacity is unavailable")
            area["limit"] = voucher_limit
        elif area_name == "packs":
            area["limit"] = 2
        elif area_name == "pack":
            if private_cards:
                if not isinstance(pack_card_limit, int) or pack_card_limit < len(
                    private_cards
                ):
                    raise RuntimeError("Jackdaw opened-pack capacity is unavailable")
                area["limit"] = pack_card_limit
            else:
                area["limit"] = 0
        for card_index, (card, private_card) in enumerate(
            zip(area["cards"], private_cards, strict=True)
        ):
            if not isinstance(card, dict):
                continue
            modifier = card.get("modifier")
            if isinstance(modifier, Mapping):
                normalized_modifier = {
                    str(key): value
                    for key, value in modifier.items()
                    if value is not None and value is not False
                }
                _apply_balatrobot_card_modifiers(normalized_modifier, private_card)
                card["modifier"] = normalized_modifier or []
            state = card.get("state")
            if isinstance(state, Mapping):
                semantic_state = {
                    str(key): value
                    for key, value in state.items()
                    if value is not None and value is not False
                }
            elif (
                isinstance(state, Sequence) and not isinstance(state, str) and not state
            ):
                semantic_state = {}
            else:
                raise RuntimeError(f"Jackdaw {area_name} card state is invalid")
            ability = getattr(private_card, "ability", None)
            if (
                area_name == "hand"
                and isinstance(ability, Mapping)
                and ability.get("forced_selection") is True
            ):
                semantic_state["highlight"] = True
                semantic_state["forced_selection"] = True
            if area_name in {"cards", "discard"}:
                semantic_state["hidden"] = True
            if area_name == "jokers" and semantic_state.get("hidden") is True:
                # Amber Acorn shuffles face-down Jokers.  Their identities,
                # modifiers, costs, and runtime state are private; only the
                # occupied array position remains public.
                area["cards"][card_index] = {
                    "set": "JOKER",
                    "state": {"hidden": True},
                }
                continue
            card["state"] = semantic_state or []
            value = card.get("value")
            if isinstance(value, dict):
                _apply_balatrobot_card_values(value, private_card)
                if card.get("key") == "j_idol":
                    current_round = private.get("current_round")
                    idol_card = (
                        current_round.get("idol_card")
                        if isinstance(current_round, Mapping)
                        else None
                    )
                    if not isinstance(idol_card, Mapping):
                        raise RuntimeError("Jackdaw Idol target is unavailable")
                    rank = _RANK_LETTER.get(str(idol_card.get("rank")))
                    suit = _SUIT_LETTER.get(str(idol_card.get("suit")))
                    if rank is None or suit is None:
                        raise RuntimeError("Jackdaw Idol target is invalid")
                    ability = value.setdefault("ability", {})
                    if not isinstance(ability, dict):
                        raise RuntimeError("Jackdaw Idol ability is invalid")
                    ability["idol_rank"] = rank
                    ability["idol_suit"] = suit
                if card.get("key") == "j_castle":
                    current_round = private.get("current_round")
                    castle_card = (
                        current_round.get("castle_card")
                        if isinstance(current_round, Mapping)
                        else None
                    )
                    suit = (
                        _SUIT_LETTER.get(str(castle_card.get("suit")))
                        if isinstance(castle_card, Mapping)
                        else None
                    )
                    if suit is None:
                        raise RuntimeError("Jackdaw Castle target is unavailable")
                    ability = value.setdefault("ability", {})
                    if not isinstance(ability, dict):
                        raise RuntimeError("Jackdaw Castle ability is invalid")
                    ability["castle_suit"] = suit
                if card.get("key") == "j_mail":
                    current_round = private.get("current_round")
                    mail_card = (
                        current_round.get("mail_card")
                        if isinstance(current_round, Mapping)
                        else None
                    )
                    rank = (
                        _RANK_LETTER.get(str(mail_card.get("rank")))
                        if isinstance(mail_card, Mapping)
                        else None
                    )
                    if rank is None:
                        raise RuntimeError("Jackdaw Mail-In Rebate target is unavailable")
                    ability = value.setdefault("ability", {})
                    if not isinstance(ability, dict):
                        raise RuntimeError("Jackdaw Mail-In Rebate ability is invalid")
                    ability["mail_rank"] = rank
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
    current_round = (
        private.get("current_round") if isinstance(private, Mapping) else None
    )
    if isinstance(round_state, dict) and isinstance(current_round, Mapping):
        round_resets = private.get("round_resets")
        boss_rerolled = (
            round_resets.get("boss_rerolled")
            if isinstance(round_resets, Mapping)
            else None
        )
        if not isinstance(boss_rerolled, bool):
            raise RuntimeError("Jackdaw boss-rerolled state is unavailable")
        round_state["boss_rerolled"] = boss_rerolled
        before_first_blind = private.get("round", 0) == 0 and (
            phase == "BLIND_SELECT" or (in_pack and not pack_from_shop)
        )
        if before_first_blind:
            round_resets = private.get("round_resets")
            if not isinstance(round_resets, Mapping):
                raise RuntimeError("Jackdaw initial round-reset state is unavailable")
            round_state["hands_left"] = round_resets.get(
                "hands", round_state.get("hands_left", 0)
            )
            round_state["discards_left"] = round_resets.get(
                "discards", round_state.get("discards_left", 0)
            )
        ancient = current_round.get("ancient_card")
        if isinstance(ancient, Mapping) and ancient.get("suit") in _SUIT_LETTER:
            round_state["ancient_suit"] = _SUIT_LETTER[str(ancient["suit"])]
        most_played = current_round.get("most_played_poker_hand")
        if isinstance(most_played, str) and most_played:
            round_state["most_played_poker_hand"] = most_played

    if stale_shop_areas is not None and phase in {
        "BLIND_SELECT",
        "SELECTING_HAND",
        "ROUND_EVAL",
        "GAME_OVER",
    }:
        for name in ("shop", "vouchers", "packs"):
            if name not in result and name in stale_shop_areas:
                result[name] = deepcopy(stale_shop_areas[name])

    return result


def _jackdaw_deck_composition(
    game_state: Mapping[str, Any],
) -> list[dict[str, object]]:
    """Return the unordered permanent deck shown by vanilla's deck view."""

    from jackdaw.bridge.serializer import serialize_card

    cards: list[Any] = []
    seen_card_ids: set[int] = set()
    for area_name in ("deck", "hand", "discard_pile", "play"):
        area = game_state.get(area_name, [])
        if area is None:
            area = []
        if not isinstance(area, list):
            raise RuntimeError(f"Jackdaw {area_name} state is invalid")
        for card in area:
            card_id = id(card)
            if card_id not in seen_card_ids:
                seen_card_ids.add(card_id)
                cards.append(card)
    counts: Counter[tuple[str, str, str | None, str | None, str | None, int]] = Counter()
    for card in cards:
        serialized = serialize_card(card)
        value = serialized.get("value")
        modifier = serialized.get("modifier")
        if not isinstance(value, dict) or not isinstance(modifier, Mapping):
            raise RuntimeError("Jackdaw permanent deck card is invalid")
        _apply_balatrobot_card_values(value, card)
        enhancement = modifier.get("enhancement")
        rank = value.get("rank")
        suit = value.get("suit")
        if enhancement == "STONE":
            rank = suit = "?"
        if not isinstance(rank, str) or not isinstance(suit, str):
            raise RuntimeError("Jackdaw permanent deck identity is unavailable")
        permanent_bonus = value.get("perma_bonus", 0)
        if isinstance(permanent_bonus, bool) or not isinstance(permanent_bonus, int):
            raise RuntimeError("Jackdaw permanent card bonus is invalid")
        counts[
            (
                rank,
                suit,
                str(enhancement) if enhancement is not None else None,
                str(modifier.get("edition"))
                if modifier.get("edition") is not None
                else None,
                str(modifier.get("seal")) if modifier.get("seal") is not None else None,
                permanent_bonus,
            )
        ] += 1
    composition: list[dict[str, object]] = []
    for (rank, suit, enhancement, edition, seal, permanent_bonus), count in sorted(
        counts.items(),
        key=lambda pair: "|".join(
            (
                pair[0][0],
                pair[0][1],
                pair[0][2] or "",
                pair[0][3] or "",
                pair[0][4] or "",
                str(pair[0][5]),
            )
        ),
    ):
        entry: dict[str, object] = {
            "rank": rank,
            "suit": suit,
            "permanent_bonus": permanent_bonus,
            "count": count,
        }
        for modifier_field, value in (
            ("enhancement", enhancement),
            ("edition", edition),
            ("seal", seal),
        ):
            if value is not None:
                entry[modifier_field] = value
        composition.append(entry)
    return composition


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
    if (
        isinstance(perma_bonus, int | float)
        and not isinstance(perma_bonus, bool)
        and perma_bonus != 0
    ):
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
    center_key = getattr(card, "center_key", None)
    if center_key == "j_caino":
        caino_xmult = ability.get("caino_xmult")
        if isinstance(caino_xmult, int | float) and not isinstance(caino_xmult, bool):
            serialized["x_mult"] = caino_xmult
    if center_key == "j_invisible":
        invisible_rounds = ability.get("invis_rounds")
        if isinstance(invisible_rounds, int) and not isinstance(invisible_rounds, bool):
            serialized["invisible_rounds"] = invisible_rounds
    if center_key == "j_yorick":
        remaining_discards = ability.get("yorick_discards")
        if isinstance(remaining_discards, int) and not isinstance(remaining_discards, bool):
            serialized["remaining_discards"] = remaining_discards
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
            if (
                isinstance(item, int | float)
                and not isinstance(item, bool)
                and item != 0
            ):
                modifier[destination] = item
    if not isinstance(ability, Mapping):
        return
    center = _jackdaw_center(card)
    effect = ability.get("effect") if "effect" in center else None
    if isinstance(effect, str) and effect != "Base":
        modifier["enhancement"] = effect.replace(" Card", "").upper()
        x_mult = ability.get("x_mult")
        if (
            isinstance(x_mult, int | float)
            and not isinstance(x_mult, bool)
            and x_mult != 1
        ):
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
