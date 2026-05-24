from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from random import Random

from balatro_ai_v2.fast.cards import shuffled_deck
from balatro_ai_v2.fast.run_rules import RunModifiers, apply_deck


class RunPhase(IntEnum):
    BLIND_SELECT = 0
    SELECTING_HAND = 1
    ROUND_EVAL = 2
    SHOP = 3
    GAME_OVER = 4


class BlindKind(IntEnum):
    SMALL = 0
    BIG = 1
    BOSS = 2


BLIND_REWARD = {
    BlindKind.SMALL: 3,
    BlindKind.BIG: 4,
    BlindKind.BOSS: 5,
}

BLIND_MULT = {
    BlindKind.SMALL: 1.0,
    BlindKind.BIG: 1.5,
    BlindKind.BOSS: 2.0,
}

# Vanilla white-stake base blind amounts for ante 1-8. Higher antes keep growing
# exponentially enough for training pressure until exact source parity is added.
BASE_ANTE_CHIPS = (300, 800, 2000, 5000, 11000, 20000, 35000, 50000)


@dataclass(slots=True)
class ShopState:
    reroll_cost: int = 5
    reroll_cost_increase: int = 0
    free_rerolls: int = 0
    item_keys: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FastRunState:
    seed: int = 0
    deck_key: str = "b_red"
    ante: int = 1
    round_num: int = 0
    blind_kind: BlindKind = BlindKind.SMALL
    phase: RunPhase = RunPhase.BLIND_SELECT
    money: int = 4
    interest_cap: int = 25
    interest_amount: int = 1
    base_reroll_cost: int = 5
    bankrupt_at: int = 0
    score: int = 0
    required_score: int = 300
    hands: int = 4
    discards: int = 3
    hand_size: int = 8
    joker_slots: int = 5
    consumable_slots: int = 2
    shop_slots: int = 2
    shop_discount: float = 1.0
    blind_requirement_multiplier: float = 1.0
    tarot_rate: float = 4.0
    planet_rate: float = 4.0
    spectral_rate: float = 0.0
    playing_card_rate: float = 0.0
    edition_rate: float = 1.0
    arcana_pack_spectral_chance: float = 0.0
    telescope_guarantees_most_played_planet: bool = False
    observatory_xmult: float = 1.0
    boss_reroll_cost: int | None = None
    boss_reroll_once_per_ante: bool = False
    probability_multiplier: float = 1.0
    planets_are_free: bool = False
    celestial_packs_are_free: bool = False
    starting_consumables: tuple[str, ...] = ()
    earns_interest: bool = True
    earns_hand_money: bool = True
    earns_discard_money: bool = False
    deck: list[int] = field(default_factory=list)
    hand: list[int] = field(default_factory=list)
    deck_pos: int = 0
    shop: ShopState = field(default_factory=ShopState)
    won: bool = False

    def reset(self, seed: int | None = None) -> FastRunState:
        if seed is not None:
            self.seed = seed
        self.ante = 1
        self.round_num = 0
        self.blind_kind = BlindKind.SMALL
        self.phase = RunPhase.BLIND_SELECT
        modifiers = apply_deck(RunModifiers(), self.deck_key)
        self.money = modifiers.money
        self.hands = modifiers.hands
        self.discards = modifiers.discards
        self.hand_size = modifiers.hand_size
        self.joker_slots = modifiers.joker_slots
        self.consumable_slots = modifiers.consumable_slots
        self.shop_slots = modifiers.shop_slots
        self.interest_cap = modifiers.interest_cap
        self.interest_amount = modifiers.interest_amount
        self.base_reroll_cost = modifiers.base_reroll_cost
        self.bankrupt_at = modifiers.bankrupt_at
        self.shop_discount = modifiers.shop_discount
        self.blind_requirement_multiplier = modifiers.blind_requirement_multiplier
        self.tarot_rate = modifiers.tarot_rate
        self.planet_rate = modifiers.planet_rate
        self.spectral_rate = modifiers.spectral_rate
        self.playing_card_rate = modifiers.playing_card_rate
        self.edition_rate = modifiers.edition_rate
        self.arcana_pack_spectral_chance = modifiers.arcana_pack_spectral_chance
        self.telescope_guarantees_most_played_planet = modifiers.telescope_guarantees_most_played_planet
        self.observatory_xmult = modifiers.observatory_xmult
        self.boss_reroll_cost = modifiers.boss_reroll_cost
        self.boss_reroll_once_per_ante = modifiers.boss_reroll_once_per_ante
        self.probability_multiplier = modifiers.probability_multiplier
        self.planets_are_free = modifiers.planets_are_free
        self.celestial_packs_are_free = modifiers.celestial_packs_are_free
        self.starting_consumables = modifiers.starting_consumables
        self.earns_interest = modifiers.earns_interest
        self.earns_hand_money = modifiers.earns_hand_money
        self.earns_discard_money = modifiers.earns_discard_money
        self.score = 0
        self.required_score = blind_required_score(self.ante, self.blind_kind)
        self.deck = shuffled_deck(self.seed)
        self.hand = []
        self.deck_pos = 0
        self.shop = ShopState(reroll_cost=self.base_reroll_cost)
        self.won = False
        return self

    def select_blind(self) -> None:
        if self.phase != RunPhase.BLIND_SELECT:
            raise ValueError("can only select blind from BLIND_SELECT")
        self.phase = RunPhase.SELECTING_HAND
        self.score = 0
        self.required_score = blind_required_score(
            self.ante,
            self.blind_kind,
            blind_requirement_multiplier=self.blind_requirement_multiplier,
        )
        self.deck = shuffled_deck(self.seed + self.round_num)
        self.deck_pos = 0
        self.hand = self._draw(self.hand_size)

    def finish_round(self) -> int:
        if self.phase != RunPhase.ROUND_EVAL:
            raise ValueError("can only cash out from ROUND_EVAL")
        reward = round_reward(
            blind_kind=self.blind_kind,
            money=self.money,
            hands_remaining=self.hands,
            discards_remaining=self.discards,
            interest_cap=self.interest_cap,
            interest_amount=self.interest_amount,
            earns_interest=self.earns_interest,
            earns_hand_money=self.earns_hand_money,
            earns_discard_money=self.earns_discard_money,
        )
        self.money += reward
        self.phase = RunPhase.SHOP
        self.shop = ShopState(reroll_cost=self.base_reroll_cost)
        return reward

    def next_round(self) -> None:
        if self.phase != RunPhase.SHOP:
            raise ValueError("can only leave shop from SHOP")
        self.round_num += 1
        if self.blind_kind == BlindKind.SMALL:
            self.blind_kind = BlindKind.BIG
        elif self.blind_kind == BlindKind.BIG:
            self.blind_kind = BlindKind.BOSS
        else:
            self.ante += 1
            self.blind_kind = BlindKind.SMALL
            if self.ante > 8:
                self.won = True
                self.phase = RunPhase.GAME_OVER
                return
        self.phase = RunPhase.BLIND_SELECT
        self.required_score = blind_required_score(
            self.ante,
            self.blind_kind,
            blind_requirement_multiplier=self.blind_requirement_multiplier,
        )

    def reroll_shop(self) -> int:
        if self.phase != RunPhase.SHOP:
            raise ValueError("can only reroll from SHOP")
        cost = self.shop.reroll_cost
        if self.money < cost:
            raise ValueError("not enough money to reroll")
        self.money -= cost
        self.shop.reroll_cost_increase += 1
        self.shop.reroll_cost = self.base_reroll_cost + self.shop.reroll_cost_increase
        return cost

    def populate_shop(self) -> None:
        rng = Random(self.seed + self.round_num * 1009 + self.ante * 7919)
        self.shop.item_keys = [rng.choice(("j_joker", "j_jolly", "j_sly", "c_pluto")) for _ in range(2)]

    def _draw(self, count: int) -> list[int]:
        end = min(self.deck_pos + count, len(self.deck))
        drawn = self.deck[self.deck_pos : end]
        self.deck_pos = end
        return drawn


def blind_required_score(
    ante: int,
    blind_kind: BlindKind,
    blind_requirement_multiplier: float = 1.0,
) -> int:
    base = _ante_base_chips(ante)
    return int(base * BLIND_MULT[blind_kind] * blind_requirement_multiplier)


def round_reward(
    blind_kind: BlindKind,
    money: int,
    hands_remaining: int,
    discards_remaining: int = 0,
    interest_cap: int = 25,
    interest_amount: int = 1,
    earns_interest: bool = True,
    earns_hand_money: bool = True,
    earns_discard_money: bool = False,
) -> int:
    blind_money = BLIND_REWARD[blind_kind]
    interest = min(max(money, 0), interest_cap) // 5 * interest_amount if earns_interest else 0
    hand_money = max(hands_remaining, 0) if earns_hand_money else 0
    discard_money = max(discards_remaining, 0) if earns_discard_money else 0
    return blind_money + hand_money + discard_money + interest


def _ante_base_chips(ante: int) -> int:
    if ante <= len(BASE_ANTE_CHIPS):
        return BASE_ANTE_CHIPS[ante - 1]
    extra = ante - len(BASE_ANTE_CHIPS)
    return int(BASE_ANTE_CHIPS[-1] * (1.6**extra))
