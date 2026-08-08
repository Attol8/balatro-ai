"""Optional recurrent policy/value model over the strict public contract only."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Sequence

try:
    import torch
    from torch import Tensor, nn
except ImportError as exc:  # pragma: no cover - exercised in base-only installations
    raise RuntimeError("install the 'model' extra to use the public policy model") from exc

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
    RerollShop,
    SelectBlind,
    SellConsumable,
    SellJoker,
    SkipBlind,
    SkipPack,
    UseConsumable,
    action_to_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai_v2.public_state import (
    HiddenHandCard,
    PublicItem,
    PublicObservation,
    VisiblePlayingCard,
)


MODEL_FORMAT_VERSION: Final = 1
PUBLIC_MODEL_ACTION_PROPOSAL_SCHEMA: Final = "no_reorder_enumerated_max2048_v1"
_REORDER_ACTIONS = (ReorderHand, ReorderJokers, ReorderConsumables)
_ACTION_FAMILIES = {
    SelectBlind: "select_blind",
    SkipBlind: "skip_blind",
    CashOut: "cash_out",
    LeaveShop: "leave_shop",
    RerollShop: "reroll_shop",
    PlayCards: "play_cards",
    DiscardCards: "discard_cards",
    BuyShopCard: "buy_shop_card",
    BuyVoucher: "buy_voucher",
    BuyPack: "buy_pack",
    SellJoker: "sell_joker",
    SellConsumable: "sell_consumable",
    UseConsumable: "use_consumable",
    ChoosePackCard: "choose_pack_card",
    SkipPack: "skip_pack",
}


class PublicModelError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PublicModelConfig:
    observation_features: int = 2048
    action_features: int = 512
    hidden_size: int = 128
    max_candidates: int = 2048

    def __post_init__(self) -> None:
        if min(
            self.observation_features,
            self.action_features,
            self.hidden_size,
            self.max_candidates,
        ) <= 0:
            raise ValueError("public model dimensions must be positive")


@dataclass(frozen=True, slots=True)
class DynamicPolicyOutput:
    logits: Tensor
    legal_mask: Tensor
    values: Tensor
    hidden: Tensor


@dataclass(frozen=True, slots=True)
class PublicModelDecision:
    action: PublicAction
    value: Tensor
    hidden: Tensor


class PublicRecurrentPolicyValue(nn.Module):
    """Single-step GRU with independent scoring of supplied public actions."""

    def __init__(self, config: PublicModelConfig = PublicModelConfig()) -> None:
        super().__init__()
        self.config = config
        hidden = config.hidden_size
        self.observation_encoder = nn.Sequential(
            nn.Linear(config.observation_features, hidden),
            nn.Tanh(),
        )
        self.action_encoder = nn.Sequential(
            nn.Linear(config.action_features, hidden),
            nn.Tanh(),
        )
        self.recurrent = nn.GRUCell(hidden * 2, hidden)
        self.policy_head = nn.Sequential(
            nn.Linear(hidden * 2, hidden),
            nn.Tanh(),
            nn.Linear(hidden, 1),
        )
        self.value_head = nn.Linear(hidden, 1)

    def initial_hidden(self, batch_size: int, *, device: torch.device | None = None) -> Tensor:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        actual_device = device or next(self.parameters()).device
        return torch.zeros(batch_size, self.config.hidden_size, device=actual_device)

    def step(
        self,
        observations: Sequence[PublicObservation],
        legal_actions: Sequence[Sequence[PublicAction]],
        previous_actions: Sequence[PublicAction | None],
        hidden: Tensor | None = None,
        reset_mask: Tensor | None = None,
    ) -> DynamicPolicyOutput:
        batch_size = len(observations)
        if batch_size == 0 or len(legal_actions) != batch_size or len(previous_actions) != batch_size:
            raise PublicModelError("model batch fields must have the same non-zero length")
        device = next(self.parameters()).device
        candidates = [self._validate_candidates(obs, tuple(actions)) for obs, actions in zip(observations, legal_actions)]
        observation_tensor = torch.tensor(
            [_observation_features(obs, self.config.observation_features) for obs in observations],
            dtype=torch.float32,
            device=device,
        )
        previous_tensor = torch.tensor(
            [
                _previous_action_features(action, self.config.action_features)
                for action in previous_actions
            ],
            dtype=torch.float32,
            device=device,
        )
        state_embedding = self.observation_encoder(observation_tensor)
        previous_embedding = self.action_encoder(previous_tensor)
        recurrent_input = torch.cat((state_embedding, previous_embedding), dim=-1)

        if hidden is None:
            hidden = self.initial_hidden(batch_size, device=device)
        elif hidden.shape != (batch_size, self.config.hidden_size):
            raise PublicModelError("hidden state has the wrong shape")
        else:
            hidden = hidden.to(device=device, dtype=torch.float32)
        if reset_mask is not None:
            if reset_mask.shape != (batch_size,):
                raise PublicModelError("reset mask has the wrong shape")
            hidden = hidden * (~reset_mask.to(device=device, dtype=torch.bool)).unsqueeze(1)
        next_hidden = self.recurrent(recurrent_input, hidden)

        width = max(len(actions) for actions in candidates)
        logits = torch.full((batch_size, width), -torch.inf, device=device)
        legal_mask = torch.zeros((batch_size, width), dtype=torch.bool, device=device)
        for row, (observation, actions) in enumerate(zip(observations, candidates)):
            action_tensor = torch.tensor(
                [
                    _action_features(observation, action, self.config.action_features)
                    for action in actions
                ],
                dtype=torch.float32,
                device=device,
            )
            encoded_actions = self.action_encoder(action_tensor)
            state_rows = next_hidden[row].unsqueeze(0).expand(len(actions), -1)
            logits[row, : len(actions)] = self.policy_head(
                torch.cat((state_rows, encoded_actions), dim=-1)
            ).squeeze(-1)
            legal_mask[row, : len(actions)] = True
        return DynamicPolicyOutput(
            logits=logits,
            legal_mask=legal_mask,
            values=self.value_head(next_hidden).squeeze(-1),
            hidden=next_hidden,
        )

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: Sequence[PublicAction],
        *,
        previous_action: PublicAction | None = None,
        hidden: Tensor | None = None,
        reset: bool = False,
    ) -> PublicModelDecision:
        ordered = tuple(sorted(legal_actions, key=_canonical_action_json))
        reset_mask = torch.tensor([reset], dtype=torch.bool) if reset else None
        output = self.step(
            (observation,),
            (ordered,),
            (previous_action,),
            hidden,
            reset_mask,
        )
        index = int(torch.argmax(output.logits[0]).item())
        return PublicModelDecision(ordered[index], output.values[0], output.hidden)

    def _validate_candidates(
        self,
        observation: PublicObservation,
        actions: tuple[PublicAction, ...],
    ) -> tuple[PublicAction, ...]:
        if not actions or len(actions) > self.config.max_candidates:
            raise PublicModelError("candidate count is outside the configured bound")
        encoded = [_canonical_action_json(action) for action in actions]
        if len(encoded) != len(set(encoded)):
            raise PublicModelError("candidate list contains duplicates")
        if any(isinstance(action, _REORDER_ACTIONS) for action in actions):
            raise PublicModelError("reorder actions require a future permutation head")
        if any(type(action) not in _ACTION_FAMILIES or not is_legal(observation, action) for action in actions):
            raise PublicModelError("candidate list contains an unsupported or illegal action")
        return actions


def public_model_candidates(observation: PublicObservation) -> tuple[PublicAction, ...]:
    """Return the explicit no-reorder-v1 proposal set without truncation."""

    actions: list[PublicAction] = []
    for action in iter_legal_actions(observation):
        if isinstance(action, _REORDER_ACTIONS):
            break
        actions.append(action)
    if not actions:
        raise PublicModelError("no supported public model action is available")
    if len(actions) > PublicModelConfig().max_candidates:
        raise PublicModelError(
            f"public model action proposal has {len(actions)} actions, exceeding its declared bound"
        )
    return tuple(actions)


def save_public_model(path: Path, model: PublicRecurrentPolicyValue) -> str:
    payload = {
        "format_version": MODEL_FORMAT_VERSION,
        "config": asdict(model.config),
        "state_dict": model.state_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        torch.save(payload, handle)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_public_model(path: Path, *, device: torch.device | str = "cpu") -> PublicRecurrentPolicyValue:
    try:
        payload = torch.load(path, map_location=device, weights_only=True)
    except (OSError, RuntimeError) as exc:
        raise PublicModelError(f"cannot load public model checkpoint: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != {"format_version", "config", "state_dict"}:
        raise PublicModelError("public model checkpoint fields are invalid")
    if payload["format_version"] != MODEL_FORMAT_VERSION or not isinstance(payload["config"], dict):
        raise PublicModelError("public model checkpoint version or config is invalid")
    try:
        config = PublicModelConfig(**payload["config"])
        model = PublicRecurrentPolicyValue(config).to(device)
        model.load_state_dict(payload["state_dict"], strict=True)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise PublicModelError(f"public model checkpoint is incompatible: {exc}") from exc
    return model


def _observation_features(observation: PublicObservation, size: int) -> list[float]:
    vector = _HashedVector(size)
    vector.category("phase", observation.phase.value)
    vector.category("deck", observation.deck)
    vector.category("stake", observation.stake)
    for name, value, scale in (
        ("ante", observation.ante, 8),
        ("round_no", observation.round_no, 24),
        ("money", observation.money, 50),
        ("round.chips", observation.round.chips, 10_000),
        ("round.hands_left", observation.round.hands_left, 8),
        ("round.discards_left", observation.round.discards_left, 8),
        ("round.hands_played", observation.round.hands_played, 8),
        ("round.discards_used", observation.round.discards_used, 8),
        ("round.reroll_cost", observation.round.reroll_cost, 20),
        ("hand_limit", observation.hand_limit, 12),
        ("selection_limit", observation.selection_limit, 5),
        ("draw_count", observation.draw_count, 52),
        ("deck_size", observation.deck_size, 80),
        ("joker_limit", observation.joker_limit, 10),
        ("consumable_limit", observation.consumable_limit, 6),
    ):
        vector.number(name, value, scale)
    vector.number("won", int(observation.won), 1)

    for index, card in enumerate(observation.hand):
        _add_card(vector, f"hand.{index}", card)
    for entry in observation.remaining_deck:
        _add_card(vector, "remaining", entry.card, weight=math.log1p(entry.count))
    for region in ("jokers", "consumables", "shop", "vouchers", "packs"):
        for index, item in enumerate(getattr(observation, region)):
            _add_item(vector, f"{region}.{index}", item)
    for index, offer in enumerate(observation.opened_pack):
        if isinstance(offer, PublicItem):
            _add_item(vector, f"opened_pack.{index}", offer)
        else:
            _add_card(vector, f"opened_pack.{index}", offer)
    for blind in observation.blinds:
        prefix = f"blind.{blind.kind}"
        vector.category(f"{prefix}.status", blind.status)
        vector.category(f"{prefix}.name", blind.name)
        vector.category(f"{prefix}.tag_name", blind.tag_name)
        vector.number(f"{prefix}.score", blind.score, 1_000_000)
    for hand in observation.hand_stats:
        prefix = f"hand_stat.{hand.name}"
        for name, value, scale in (
            ("level", hand.level, 20),
            ("chips", hand.chips, 1_000),
            ("mult", hand.mult, 100),
            ("played", hand.played, 50),
            ("played_this_round", hand.played_this_round, 10),
        ):
            vector.number(f"{prefix}.{name}", value, scale)
    for key in observation.used_vouchers:
        vector.category("used_voucher", key)
    return vector.values


def _action_features(
    observation: PublicObservation,
    action: PublicAction,
    size: int,
) -> list[float]:
    vector = _HashedVector(size)
    family = _ACTION_FAMILIES.get(type(action))
    if family is None or isinstance(action, _REORDER_ACTIONS):
        raise PublicModelError(f"unsupported model action {type(action).__name__}")
    vector.category("action.family", family)
    if isinstance(action, (PlayCards, DiscardCards)):
        for position, slot in enumerate(action.cards):
            vector.category(f"action.card.{position}.slot", str(slot.value))
            _add_card(vector, f"action.card.{position}", observation.hand[slot.value])
    elif isinstance(action, BuyShopCard):
        vector.category("action.buy_mode", action.mode.value)
        _add_item(vector, "action.item", observation.shop[action.card.value])
    elif isinstance(action, BuyVoucher):
        _add_item(vector, "action.item", observation.vouchers[action.voucher.value])
    elif isinstance(action, BuyPack):
        _add_item(vector, "action.item", observation.packs[action.pack.value])
    elif isinstance(action, SellJoker):
        _add_item(vector, "action.item", observation.jokers[action.joker.value])
    elif isinstance(action, SellConsumable):
        _add_item(vector, "action.item", observation.consumables[action.consumable.value])
    elif isinstance(action, UseConsumable):
        _add_item(vector, "action.item", observation.consumables[action.consumable.value])
        _add_target_cards(vector, observation, action.targets)
    elif isinstance(action, ChoosePackCard):
        offer = observation.opened_pack[action.card.value]
        if isinstance(offer, PublicItem):
            _add_item(vector, "action.item", offer)
        else:
            _add_card(vector, "action.item", offer)
        _add_target_cards(vector, observation, action.targets)
    return vector.values


def _previous_action_features(action: PublicAction | None, size: int) -> list[float]:
    vector = _HashedVector(size)
    if action is None:
        vector.category("previous.family", "<BOS>")
        return vector.values
    family = _ACTION_FAMILIES.get(type(action), "unsupported")
    vector.category("previous.family", family)
    data = action_to_data(action)
    for key, value in data.items():
        if key != "type":
            vector.category(f"previous.{key}", json.dumps(value, sort_keys=True))
    return vector.values


def _add_target_cards(vector: _HashedVector, observation: PublicObservation, targets: Sequence[object]) -> None:
    for position, target in enumerate(targets):
        slot = int(getattr(target, "value"))
        vector.category(f"action.target.{position}.slot", str(slot))
        _add_card(vector, f"action.target.{position}", observation.hand[slot])


def _add_card(
    vector: _HashedVector,
    prefix: str,
    card: VisiblePlayingCard | HiddenHandCard,
    *,
    weight: float = 1.0,
) -> None:
    if isinstance(card, HiddenHandCard):
        vector.add(f"{prefix}.hidden", weight)
        return
    for name, value in (
        ("rank", card.rank),
        ("suit", card.suit),
        ("enhancement", card.enhancement or "<NONE>"),
        ("edition", card.edition or "<NONE>"),
        ("seal", card.seal or "<NONE>"),
    ):
        vector.category(f"{prefix}.{name}", value, weight)
    vector.add(f"{prefix}.debuffed", weight if card.debuffed else 0.0)


def _add_item(vector: _HashedVector, prefix: str, item: PublicItem) -> None:
    vector.category(f"{prefix}.key", item.key)
    vector.category(f"{prefix}.kind", item.kind)
    vector.category(f"{prefix}.edition", item.edition or "<NONE>")
    vector.number(f"{prefix}.eternal", int(item.eternal), 1)
    vector.number(f"{prefix}.perishable", item.perishable_rounds or 0, 10)
    vector.number(f"{prefix}.rental", int(item.rental), 1)
    vector.number(f"{prefix}.buy_cost", item.buy_cost or 0, 50)
    vector.number(f"{prefix}.sell_cost", item.sell_cost or 0, 50)


class _HashedVector:
    def __init__(self, size: int) -> None:
        self.size = size
        self.values = [0.0] * size

    def category(self, name: str, value: str, weight: float = 1.0) -> None:
        self.add(f"{name}={value}", weight)

    def number(self, name: str, value: int | float, scale: int | float) -> None:
        self.add(name, math.tanh(float(value) / float(scale)))

    def add(self, key: str, value: float) -> None:
        if value == 0:
            return
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % self.size
        sign = 1.0 if digest[4] & 1 else -1.0
        self.values[index] += sign * value


def _canonical_action_json(action: PublicAction) -> str:
    return json.dumps(action_to_data(action), sort_keys=True, separators=(",", ":"))
