"""Pinned Jackdaw candidate backend.

Jackdaw is a fast candidate, never an authority.  The import is lazy so the
authority-only project remains dependency-free on Python 3.11; candidate work
uses Python 3.12 and the pinned optional dependency.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
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


class JackdawUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class JackdawBackend:
    canonicalizer: BalatroBotCanonicalizer = field(default_factory=BalatroBotCanonicalizer)
    metadata: BackendMetadata = field(init=False)
    _backend: Any = field(init=False, repr=False)
    _rpc_error: type[Exception] = field(init=False, repr=False)
    _current: AuthorityObservation | None = field(default=None, init=False, repr=False)

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
        try:
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

    def _observation(self, raw: dict[str, Any]) -> AuthorityObservation:
        # Both adapters must pass independently.  The public conversion catches
        # leaks/unsupported shapes; canonicalization catches semantic drift.
        normalized = _normalize_jackdaw_bridge(raw, getattr(self._backend, "_gs", None))
        to_public_observation(normalized)
        observed = self.canonicalizer.canonicalize(normalized)
        return AuthorityObservation(observed=observed, settled=True, polls=(observed.raw_json,))


def _normalize_jackdaw_bridge(raw: dict[str, Any], game_state: object) -> dict[str, Any]:
    """Translate Jackdaw serializer defaults into BalatroBot's observed schema.

    This function may normalize representation only. Values come from
    Jackdaw's actual state; it must never invent a result to satisfy a trace.
    """

    result = deepcopy(raw)
    private = game_state if isinstance(game_state, Mapping) else {}
    phase = result.get("state")

    for name in _OPTIONAL_AREAS:
        area = result.get(name)
        relevant = (phase == "SHOP" and name in {"shop", "vouchers", "packs"}) or (
            phase in {"SMODS_BOOSTER_OPENED", "PLANET_PACK", "TAROT_PACK", "SPECTRAL_PACK", "STANDARD_PACK", "BUFFOON_PACK"}
            and name == "pack"
        )
        if isinstance(area, Mapping) and not area.get("cards") and not relevant:
            result.pop(name, None)

    limits = {"cards": 5, "hand": 5, "jokers": 1, "consumables": 1}
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
        for card in area["cards"]:
            if not isinstance(card, dict):
                continue
            modifier = card.get("modifier")
            if isinstance(modifier, Mapping):
                card["modifier"] = {
                    str(key): value for key, value in modifier.items() if value is not None and value is not False
                } or []
            state = card.get("state")
            if isinstance(state, Mapping):
                semantic_state = {
                    str(key): value for key, value in state.items() if value is not None and value is not False
                }
                if area_name == "cards":
                    semantic_state["hidden"] = True
                card["state"] = semantic_state or []
            if str(card.get("set") or "").upper() == "DEFAULT":
                card["cost"] = {"buy": 1, "sell": 1}
                value = card.get("value")
                if isinstance(value, dict):
                    value["ability"] = {"x_mult": 1}

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

    return result
