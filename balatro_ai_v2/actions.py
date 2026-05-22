from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from balatro_ai_v2.fast.env import DISCARD_ACTION_OFFSET


class ActionKind(str, Enum):
    PLAY = "play"
    DISCARD = "discard"
    SELECT_BLIND = "select"
    SKIP_BLIND = "skip"
    CASH_OUT = "cash_out"
    NEXT_ROUND = "next_round"
    REROLL = "reroll"
    BUY_CARD = "buy_card"
    BUY_VOUCHER = "buy_voucher"
    BUY_PACK = "buy_pack"
    SELL_JOKER = "sell_joker"
    SELL_CONSUMABLE = "sell_consumable"
    USE_CONSUMABLE = "use_consumable"
    PACK_SELECT = "pack_select"
    PACK_SKIP = "pack_skip"


@dataclass(frozen=True, slots=True)
class GameAction:
    kind: ActionKind
    indices: tuple[int, ...] = ()
    index: int | None = None

    @staticmethod
    def from_fast_action_id(action_id: int) -> GameAction:
        if action_id >= DISCARD_ACTION_OFFSET:
            return GameAction(
                kind=ActionKind.DISCARD,
                indices=_indices_from_mask(action_id - DISCARD_ACTION_OFFSET),
            )
        return GameAction(kind=ActionKind.PLAY, indices=_indices_from_mask(action_id))

    def to_fast_action_id(self) -> int:
        mask = _mask_from_indices(self.indices)
        if self.kind == ActionKind.PLAY:
            return mask
        if self.kind == ActionKind.DISCARD:
            return DISCARD_ACTION_OFFSET + mask
        raise ValueError(f"{self.kind.value} cannot be encoded as a fast tactical action")

    def to_balatrobot_rpc(self) -> tuple[str, dict]:
        if self.kind == ActionKind.PLAY:
            return "play", {"cards": list(self.indices)}
        if self.kind == ActionKind.DISCARD:
            return "discard", {"cards": list(self.indices)}
        if self.kind == ActionKind.SELECT_BLIND:
            return "select", {}
        if self.kind == ActionKind.SKIP_BLIND:
            return "skip", {}
        if self.kind == ActionKind.CASH_OUT:
            return "cash_out", {}
        if self.kind == ActionKind.NEXT_ROUND:
            return "next_round", {}
        if self.kind == ActionKind.REROLL:
            return "reroll", {}
        if self.kind == ActionKind.BUY_CARD:
            return "buy", {"card": _required_index(self)}
        if self.kind == ActionKind.BUY_VOUCHER:
            return "buy", {"voucher": _required_index(self)}
        if self.kind == ActionKind.BUY_PACK:
            return "buy", {"pack": _required_index(self)}
        if self.kind == ActionKind.SELL_JOKER:
            return "sell", {"joker": _required_index(self)}
        if self.kind == ActionKind.SELL_CONSUMABLE:
            return "sell", {"consumable": _required_index(self)}
        if self.kind == ActionKind.USE_CONSUMABLE:
            params = {"consumable": _required_index(self)}
            if self.indices:
                params["cards"] = list(self.indices)
            return "use", params
        if self.kind == ActionKind.PACK_SELECT:
            params = {"card": _required_index(self)}
            if self.indices:
                params["targets"] = list(self.indices)
            return "pack", params
        if self.kind == ActionKind.PACK_SKIP:
            return "pack", {"skip": True}
        raise ValueError(f"unsupported action kind: {self.kind}")


def _mask_from_indices(indices: tuple[int, ...]) -> int:
    if not indices:
        raise ValueError("tactical action must contain at least one card index")
    mask = 0
    for index in indices:
        if not 0 <= index < 8:
            raise ValueError(f"card index out of tactical range: {index}")
        mask |= 1 << index
    return mask


def _indices_from_mask(mask: int) -> tuple[int, ...]:
    if mask <= 0:
        raise ValueError("mask must select at least one card")
    return tuple(index for index in range(8) if mask & (1 << index))


def _required_index(action: GameAction) -> int:
    if action.index is None:
        raise ValueError(f"{action.kind.value} requires index")
    return action.index

