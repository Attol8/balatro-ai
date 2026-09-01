"""Optional recurrent policy/value model over the strict public contract only."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Final, Sequence, TypeAlias

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
    HandSlot,
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


MODEL_FORMAT_VERSION: Final = 3
PUBLIC_MODEL_ACTION_PROPOSAL_SCHEMA: Final = "factorized_tactical_targeted_adjacent_reorder_v3"
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
    ReorderHand: "reorder_hand",
    ReorderJokers: "reorder_jokers",
    ReorderConsumables: "reorder_consumables",
}


class PublicModelError(RuntimeError):
    pass


class TacticalFamily(str, Enum):
    PLAY = "play_cards"
    DISCARD = "discard_cards"


@dataclass(frozen=True, slots=True)
class TacticalCandidate:
    family: TacticalFamily


ModelCandidate: TypeAlias = PublicAction | TacticalCandidate


@dataclass(frozen=True, slots=True)
class PublicModelConfig:
    observation_features: int = 2048
    action_features: int = 512
    hidden_size: int = 128
    max_candidates: int = 512

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


@dataclass(frozen=True, slots=True)
class PublicModelSample:
    actions: tuple[PublicAction, ...]
    log_probabilities: Tensor
    entropies: Tensor
    values: Tensor
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
        legal_actions: Sequence[Sequence[ModelCandidate]],
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
                    _candidate_features(observation, action, self.config.action_features)
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
        legal_actions: Sequence[ModelCandidate],
        *,
        previous_action: PublicAction | None = None,
        hidden: Tensor | None = None,
        reset: bool = False,
    ) -> PublicModelDecision:
        ordered = tuple(sorted(legal_actions, key=_canonical_candidate_json))
        reset_mask = torch.tensor([reset], dtype=torch.bool) if reset else None
        output = self.step(
            (observation,),
            (ordered,),
            (previous_action,),
            hidden,
            reset_mask,
        )
        candidate = ordered[int(torch.argmax(output.logits[0]).item())]
        action = (
            self._tactical_action(observation, candidate, output.hidden[0], sample=False)[0]
            if isinstance(candidate, TacticalCandidate)
            else candidate
        )
        return PublicModelDecision(action, output.values[0], output.hidden)

    def sample_actions(
        self,
        observations: Sequence[PublicObservation],
        candidates: Sequence[Sequence[ModelCandidate]],
        previous_actions: Sequence[PublicAction | None],
        hidden: Tensor | None = None,
        reset_mask: Tensor | None = None,
    ) -> PublicModelSample:
        candidate_sets = tuple(tuple(values) for values in candidates)
        output = self.step(observations, candidate_sets, previous_actions, hidden, reset_mask)
        distribution = torch.distributions.Categorical(logits=output.logits)
        indexes = distribution.sample()
        log_probabilities = distribution.log_prob(indexes)
        entropies = distribution.entropy()
        actions: list[PublicAction] = []
        for row, (observation, values) in enumerate(zip(observations, candidate_sets)):
            candidate = values[int(indexes[row])]
            if isinstance(candidate, TacticalCandidate):
                action, extra_log_probability, extra_entropy = self._tactical_action(
                    observation,
                    candidate,
                    output.hidden[row],
                    sample=True,
                )
                log_probabilities[row] = log_probabilities[row] + extra_log_probability
                entropies[row] = entropies[row] + extra_entropy
                actions.append(action)
            else:
                actions.append(candidate)
        return PublicModelSample(
            tuple(actions),
            log_probabilities,
            entropies,
            output.values,
            output.hidden,
        )

    def evaluate_actions(
        self,
        observations: Sequence[PublicObservation],
        candidates: Sequence[Sequence[ModelCandidate]],
        previous_actions: Sequence[PublicAction | None],
        actions: Sequence[PublicAction],
        hidden: Tensor | None = None,
        reset_mask: Tensor | None = None,
    ) -> PublicModelSample:
        if len(actions) != len(observations):
            raise PublicModelError("evaluated action count differs from the model batch")
        candidate_sets = tuple(tuple(values) for values in candidates)
        output = self.step(observations, candidate_sets, previous_actions, hidden, reset_mask)
        distribution = torch.distributions.Categorical(logits=output.logits)
        indexes: list[int] = []
        tactical: list[TacticalCandidate | None] = []
        for values, action in zip(candidate_sets, actions):
            wanted = _candidate_for_action(action)
            try:
                indexes.append(values.index(wanted))
            except ValueError as exc:
                raise PublicModelError("evaluated action is absent from the proposal") from exc
            tactical.append(wanted if isinstance(wanted, TacticalCandidate) else None)
        index_tensor = torch.tensor(indexes, dtype=torch.long, device=output.logits.device)
        log_probabilities = distribution.log_prob(index_tensor)
        entropies = distribution.entropy()
        for row, (observation, candidate, action) in enumerate(
            zip(observations, tactical, actions)
        ):
            if candidate is None:
                continue
            extra_log_probability, extra_entropy = self._evaluate_tactical_action(
                observation,
                candidate,
                action,
                output.hidden[row],
            )
            log_probabilities[row] = log_probabilities[row] + extra_log_probability
            entropies[row] = entropies[row] + extra_entropy
        return PublicModelSample(
            tuple(actions),
            log_probabilities,
            entropies,
            output.values,
            output.hidden,
        )

    def _validate_candidates(
        self,
        observation: PublicObservation,
        actions: tuple[ModelCandidate, ...],
    ) -> tuple[ModelCandidate, ...]:
        if not actions or len(actions) > self.config.max_candidates:
            raise PublicModelError("candidate count is outside the configured bound")
        encoded = [_canonical_candidate_json(action) for action in actions]
        if len(encoded) != len(set(encoded)):
            raise PublicModelError("candidate list contains duplicates")
        if any(not _candidate_is_legal(observation, action) for action in actions):
            raise PublicModelError("candidate list contains an unsupported or illegal action")
        return actions

    def _tactical_action(
        self,
        observation: PublicObservation,
        candidate: TacticalCandidate,
        hidden: Tensor,
        *,
        sample: bool,
    ) -> tuple[PublicAction, Tensor, Tensor]:
        selected: list[int] = []
        log_probability = hidden.new_zeros(())
        entropy = hidden.new_zeros(())
        while True:
            choices, logits = self._tactical_logits(observation, candidate, selected, hidden)
            if len(choices) == 1:
                choice_index = 0
            else:
                distribution = torch.distributions.Categorical(logits=logits)
                choice_index = (
                    int(distribution.sample().item())
                    if sample
                    else int(torch.argmax(logits).item())
                )
                index_tensor = torch.tensor(choice_index, device=hidden.device)
                log_probability = log_probability + distribution.log_prob(index_tensor)
                entropy = entropy + distribution.entropy()
            choice = choices[choice_index]
            if choice is None:
                break
            selected.append(choice)
            if len(selected) == _tactical_limit(observation) or choice == len(observation.hand) - 1:
                break
        slots = tuple(HandSlot(index) for index in selected)
        action: PublicAction = (
            PlayCards(slots) if candidate.family == TacticalFamily.PLAY else DiscardCards(slots)
        )
        return action, log_probability, entropy

    def _evaluate_tactical_action(
        self,
        observation: PublicObservation,
        candidate: TacticalCandidate,
        action: PublicAction,
        hidden: Tensor,
    ) -> tuple[Tensor, Tensor]:
        if candidate.family == TacticalFamily.PLAY and not isinstance(action, PlayCards):
            raise PublicModelError("play-family proposal received a different action")
        if candidate.family == TacticalFamily.DISCARD and not isinstance(action, DiscardCards):
            raise PublicModelError("discard-family proposal received a different action")
        wanted = [slot.value for slot in action.cards]
        if (
            not wanted
            or wanted != sorted(wanted)
            or len(wanted) > _tactical_limit(observation)
        ):
            raise PublicModelError("tactical action is not a canonical increasing selection")
        selected: list[int] = []
        log_probability = hidden.new_zeros(())
        entropy = hidden.new_zeros(())
        for wanted_choice in wanted:
            choices, logits = self._tactical_logits(observation, candidate, selected, hidden)
            if wanted_choice not in choices:
                raise PublicModelError("tactical action selection is unavailable")
            if len(choices) > 1:
                distribution = torch.distributions.Categorical(logits=logits)
                index = choices.index(wanted_choice)
                log_probability = log_probability + distribution.log_prob(
                    torch.tensor(index, device=hidden.device)
                )
                entropy = entropy + distribution.entropy()
            selected.append(wanted_choice)
        if (
            len(selected) < _tactical_limit(observation)
            and selected[-1] < len(observation.hand) - 1
        ):
            choices, logits = self._tactical_logits(observation, candidate, selected, hidden)
            if None not in choices:
                raise PublicModelError("tactical action cannot stop at its declared selection")
            if len(choices) > 1:
                distribution = torch.distributions.Categorical(logits=logits)
                index = choices.index(None)
                log_probability = log_probability + distribution.log_prob(
                    torch.tensor(index, device=hidden.device)
                )
                entropy = entropy + distribution.entropy()
        return log_probability, entropy

    def _tactical_logits(
        self,
        observation: PublicObservation,
        candidate: TacticalCandidate,
        selected: list[int],
        hidden: Tensor,
    ) -> tuple[list[int | None], Tensor]:
        start = selected[-1] + 1 if selected else 0
        choices: list[int | None] = list(range(start, len(observation.hand)))
        missing_required = [
            slot for slot in observation.required_hand_slots if slot not in selected
        ]
        if missing_required:
            first_required = missing_required[0]
            choices = [choice for choice in choices if choice <= first_required]
            remaining = _tactical_limit(observation) - len(selected)
            if remaining <= len(missing_required):
                choices = [choice for choice in choices if choice == first_required]
        elif selected:
            choices.append(None)
        if not choices:
            raise PublicModelError("tactical proposal has no selectable card")
        feature_tensor = torch.tensor(
            [
                _tactical_choice_features(
                    observation,
                    candidate,
                    selected,
                    choice,
                    self.config.action_features,
                )
                for choice in choices
            ],
            dtype=torch.float32,
            device=hidden.device,
        )
        encoded = self.action_encoder(feature_tensor)
        state_rows = hidden.unsqueeze(0).expand(len(choices), -1)
        logits = self.policy_head(torch.cat((state_rows, encoded), dim=-1)).squeeze(-1)
        return choices, logits


def public_model_candidates(observation: PublicObservation) -> tuple[ModelCandidate, ...]:
    """Return factorized tactical families plus exact non-tactical actions."""

    if observation.phase.value == "SELECTING_HAND":
        actions: list[ModelCandidate] = [TacticalCandidate(TacticalFamily.PLAY)]
        if observation.round.discards_left > 0:
            actions.append(TacticalCandidate(TacticalFamily.DISCARD))
        actions.extend(
            action
            for action in iter_legal_actions(observation)
            if not isinstance(action, (PlayCards, DiscardCards))
        )
        if len(actions) > PublicModelConfig().max_candidates:
            raise PublicModelError("public model action proposal exceeds its declared bound")
        return tuple(actions)

    actions = []
    for action in iter_legal_actions(observation):
        actions.append(action)
    if not actions:
        raise PublicModelError("no supported public model action is available")
    if len(actions) > PublicModelConfig().max_candidates:
        raise PublicModelError("public model action proposal exceeds its declared bound")
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
        ("required_hand_slots", len(observation.required_hand_slots), 5),
        ("draw_count", observation.draw_count, 52),
        ("deck_size", observation.deck_size, 80),
        ("joker_limit", observation.joker_limit, 10),
        ("consumable_limit", observation.consumable_limit, 6),
    ):
        vector.number(name, value, scale)
    vector.number("won", int(observation.won), 1)
    vector.category("pack_kind", observation.pack_kind or "<NONE>")
    vector.number("pack_choices_remaining", observation.pack_choices_remaining, 4)
    vector.category("last_tarot_planet", observation.last_tarot_planet or "<NONE>")
    for slot in observation.required_hand_slots:
        vector.category("required_hand_slot", str(slot))

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
    if family is None:
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
    elif isinstance(action, _REORDER_ACTIONS):
        for position, slot in enumerate(action.order):
            vector.category(f"action.order.{position}", str(slot.value))
    return vector.values


def _candidate_features(
    observation: PublicObservation,
    candidate: ModelCandidate,
    size: int,
) -> list[float]:
    if isinstance(candidate, TacticalCandidate):
        vector = _HashedVector(size)
        vector.category("action.family", candidate.family.value)
        vector.category("action.factorization", "tactical")
        return vector.values
    return _action_features(observation, candidate, size)


def _tactical_choice_features(
    observation: PublicObservation,
    candidate: TacticalCandidate,
    selected: Sequence[int],
    choice: int | None,
    size: int,
) -> list[float]:
    vector = _HashedVector(size)
    vector.category("tactical.family", candidate.family.value)
    vector.number("tactical.position", len(selected), 5)
    for position, slot in enumerate(selected):
        vector.category(f"tactical.selected.{position}.slot", str(slot))
        _add_card(vector, f"tactical.selected.{position}", observation.hand[slot])
    if choice is None:
        vector.category("tactical.choice", "<STOP>")
    else:
        vector.category("tactical.choice.slot", str(choice))
        _add_card(vector, "tactical.choice.card", observation.hand[choice])
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
    vector.add(
        f"{prefix}.permanent_bonus",
        math.tanh(card.permanent_bonus / 100) * weight,
    )


def _add_item(vector: _HashedVector, prefix: str, item: PublicItem) -> None:
    vector.category(f"{prefix}.key", item.key)
    vector.category(f"{prefix}.kind", item.kind)
    vector.category(f"{prefix}.edition", item.edition or "<NONE>")
    vector.number(f"{prefix}.eternal", int(item.eternal), 1)
    vector.number(f"{prefix}.perishable_present", int(item.perishable_rounds is not None), 1)
    vector.number(f"{prefix}.perishable", item.perishable_rounds or 0, 10)
    vector.number(f"{prefix}.rental", int(item.rental), 1)
    vector.number(f"{prefix}.debuffed", int(item.debuffed), 1)
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


def _canonical_candidate_json(candidate: ModelCandidate) -> str:
    if isinstance(candidate, TacticalCandidate):
        return json.dumps(
            {"type": "tactical_family", "family": candidate.family.value},
            sort_keys=True,
            separators=(",", ":"),
        )
    return _canonical_action_json(candidate)


def _candidate_for_action(action: PublicAction) -> ModelCandidate:
    if isinstance(action, PlayCards):
        return TacticalCandidate(TacticalFamily.PLAY)
    if isinstance(action, DiscardCards):
        return TacticalCandidate(TacticalFamily.DISCARD)
    return action


def _candidate_is_legal(observation: PublicObservation, candidate: ModelCandidate) -> bool:
    if isinstance(candidate, TacticalCandidate):
        if (
            observation.phase.value != "SELECTING_HAND"
            or not observation.hand
            or _tactical_limit(observation) < 1
            or observation.round.hands_left < 1
        ):
            return False
        if candidate.family == TacticalFamily.DISCARD:
            return observation.round.discards_left > 0
        return candidate.family == TacticalFamily.PLAY
    if isinstance(candidate, (PlayCards, DiscardCards)):
        return False
    return type(candidate) in _ACTION_FAMILIES and is_legal(observation, candidate)


def _tactical_limit(observation: PublicObservation) -> int:
    return min(5, observation.selection_limit, len(observation.hand))
