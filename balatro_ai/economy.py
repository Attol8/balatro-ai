"""Public money values: interest, cash-out, money sources, shop spend and skip rewards."""

from __future__ import annotations

from balatro_ai.game.actions import RerollShop
from balatro_ai.game.history import HistoryStep
from balatro_ai.game.state import Phase, PublicBlind, PublicItem, PublicObservation

# Vanilla blind rewards; Red Stake and above remove the Small Blind's.
_REWARDS = {"SMALL": 3, "BIG": 4, "BOSS": 5}
_STAKES = ("WHITE", "RED", "GREEN", "BLACK", "BLUE", "PURPLE", "ORANGE", "GOLD")
_INTEREST_CAP_MONEY = {"v_seed_money": 50, "v_money_tree": 100}
_BASE_INTEREST_CAP_MONEY = 25
_INTEREST_STEP = 5


def blind_reward(observation: PublicObservation, blind: PublicBlind) -> int:
    """Base cash for beating ``blind``; excludes $1 per unused hand and Joker income."""

    stake = _STAKES.index(observation.stake) if observation.stake in _STAKES else 0
    if blind.kind == "SMALL" and stake >= 1:
        return 0
    return _REWARDS.get(blind.kind, 0)


def interest(observation: PublicObservation, money: int | None = None) -> dict[str, int | None]:
    """Cash-out interest at ``money`` held (default: current money)."""

    money = observation.money if money is None else money
    cap_money = max(
        [_BASE_INTEREST_CAP_MONEY]
        + [
            amount
            for key, amount in _INTEREST_CAP_MONEY.items()
            if key in observation.used_vouchers
        ]
    )
    # Vanilla pays interest_amount per $5 held; each To the Moon adds one.
    per_step = 1 + sum(
        isinstance(joker, PublicItem) and joker.key == "j_to_the_moon" and not joker.debuffed
        for joker in observation.jokers
    )
    steps = max(0, money) // _INTEREST_STEP
    cap_steps = cap_money // _INTEREST_STEP
    return {
        "per_step": per_step,
        "at_cashout": per_step * min(steps, cap_steps),
        "cap": per_step * cap_steps,
        "next_threshold": None if steps >= cap_steps else (steps + 1) * _INTEREST_STEP,
        "spend_keeping_interest": max(0, money - min(steps, cap_steps) * _INTEREST_STEP),
    }


def next_blind(observation: PublicObservation) -> PublicBlind | None:
    return next(
        (b for b in observation.blinds if b.status in {"SELECT", "CURRENT", "UPCOMING"}), None
    )


def money_sources(observation: PublicObservation) -> list[dict[str, object]]:
    """Visible Tarots that pay money now, with their payout at current money."""

    rows = []
    sell_value = sum(
        joker.sell_cost or 0 for joker in observation.jokers if isinstance(joker, PublicItem)
    )
    for zone, items in (
        ("consumables", observation.consumables),
        ("shop", observation.shop),
        ("opened_pack", observation.opened_pack),
    ):
        for slot, item in enumerate(items):
            if not isinstance(item, PublicItem):
                continue
            if item.key == "c_hermit":
                gain = min(max(0, observation.money), 20)
            elif item.key == "c_temperance":
                gain = min(sell_value, 50)
            else:
                continue
            rows.append({"zone": zone, "slot": slot, "key": item.key, "pays_now": gain})
    return rows


def perkeo_plan(observation: PublicObservation) -> dict[str, object]:
    """What Perkeo will multiply: it copies one random held consumable as Negative per shop."""

    if not any(
        isinstance(joker, PublicItem) and joker.key == "j_perkeo" and not joker.debuffed
        for joker in observation.jokers
    ):
        return {}
    held: dict[str, int] = {}
    for item in observation.consumables:
        held[item.key] = held.get(item.key, 0) + 1
    return {
        "held": held,
        "negative": sum(item.edition == "NEGATIVE" for item in observation.consumables),
        "note": (
            "Leaving each shop adds a Negative copy of one random held consumable. Hold only "
            "the one you want multiplied (such as Cryptid) so every copy is that one."
        ),
    }


def shop_visit(history: tuple[HistoryStep, ...]) -> dict[str, int] | None:
    """Rerolls and money spent since this shop visit began."""

    if not history or history[-1].after.phase not in {Phase.SHOP, Phase.PACK}:
        return None
    round_no = history[-1].after.round_no
    rerolls = spent = 0
    for step in reversed(history):
        if step.before.phase not in {Phase.SHOP, Phase.PACK} or step.before.round_no != round_no:
            break
        rerolls += isinstance(step.action, RerollShop)
        spent += max(0, step.before.money - step.after.money)
    return {"rerolls": rerolls, "spent": spent}


def skip_value(observation: PublicObservation) -> dict[str, object]:
    """What skipping the next skippable blind gives and costs, from public values."""

    if observation.phase not in {Phase.BLIND_SELECT, Phase.SHOP}:
        return {}
    blind = next_blind(observation)
    if blind is None or blind.kind == "BOSS" or not blind.tag_name:
        return {}
    row: dict[str, object] = {
        "blind": blind.name,
        "reward_if_played": blind_reward(observation, blind),
        "tag": blind.tag_name,
        "tag_effect": blind.tag_effect,
    }
    money = _tag_money(observation, blind.tag_name)
    if money is not None:
        row["tag_money"] = money
    row["note"] = (
        "Skipping forfeits the reward, the $1 per unused hand, the round's scaling and the "
        "shop after it; the tag arrives at once and the next blind comes straight after."
    )
    return row


def _tag_money(observation: PublicObservation, tag: str) -> int | None:
    if tag == "Economy Tag":
        return min(max(0, observation.money), 40)
    if tag == "Investment Tag":
        return 25
    if tag == "Handy Tag":
        return sum(stat.played for stat in observation.hand_stats)
    return None
