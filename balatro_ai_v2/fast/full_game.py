from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from random import Random

from balatro_ai_v2.fast.boosters import BOOSTER_SPECS, BoosterKind, booster_spec
from balatro_ai_v2.fast.cards import rank, suit
from balatro_ai_v2.fast.env import ACTION_SPACE_SIZE, DISCARD_ACTION_OFFSET, MAX_SELECTED_CARDS
from balatro_ai_v2.fast.hand import (
    FLUSH,
    FULL_HOUSE,
    HAND_KIND_NAMES,
    HIGH_CARD,
    PAIR,
    STRAIGHT,
    THREE_OF_A_KIND,
    TWO_PAIR,
    FastScore,
    score_cards_with_joker_rules,
)
from balatro_ai_v2.fast.jokers import Joker, ScoreContext, apply_additive_jokers
from balatro_ai_v2.fast.run import FastRunState, RunPhase, ShopState, round_reward
from balatro_ai_v2.fast.run_rules import RunModifiers, apply_voucher


SELECT_BLIND_ACTION = 512
SKIP_BLIND_ACTION = 513
CASH_OUT_ACTION = 514
NEXT_ROUND_ACTION = 515
REROLL_ACTION = 516
BUY_VOUCHER_ACTION = 517
BUY_CARD_ACTION_BASE = 520
BUY_PACK_ACTION_BASE = 530
SELL_JOKER_ACTION_BASE = 540
USE_CONSUMABLE_ACTION_BASE = 550
PACK_SELECT_ACTION_BASE = 560
PACK_SKIP_ACTION = 570
FULL_ACTION_SPACE_SIZE = 576
MAX_JOKER_OBS = 8
MAX_CONSUMABLE_OBS = 4
MAX_SHOP_OBS = 4
MAX_PACK_OBS = 5
MAX_HAND_OBS = 8


@dataclass(frozen=True, slots=True)
class FullGameStepResult:
    observation: tuple[int, ...]
    reward: float
    terminated: bool
    info: dict[str, int | bool | str | tuple[int, ...]]


@dataclass(frozen=True, slots=True)
class ShopPurchase:
    key: str
    cost: int
    kind: str


@dataclass(slots=True)
class FastFullGameEnv:
    """Fast deterministic run-level Balatro gym for local agent training.

    The tactical action ids intentionally match ``FastBalatroEnv``:
    0..255 plays hand-position bitmasks and 256..511 discards them. Run-level
    actions start at 512 so the same env can train blind/shop/pack decisions.
    """

    deck_key: str = "b_red"
    seed: int = 0
    run: FastRunState = field(init=False)
    hand_levels: list[int] = field(init=False)
    hand_play_counts: list[int] = field(init=False)
    jokers: list[Joker] = field(init=False)
    consumables: list[str] = field(init=False)
    pack_cards: list[str] = field(init=False)
    available_voucher: str | None = field(default=None, init=False)
    purchased_vouchers: list[str] = field(init=False)
    pack_choices: int = field(default=1, init=False)
    hands_remaining: int = field(init=False)
    discards_remaining: int = field(init=False)
    rounds_cleared: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.run = FastRunState(deck_key=self.deck_key)
        self.hand_levels = [1] * len(HAND_KIND_NAMES)
        self.hand_play_counts = [0] * len(HAND_KIND_NAMES)
        self.jokers = []
        self.consumables = []
        self.pack_cards = []
        self.purchased_vouchers = []
        self.hands_remaining = 0
        self.discards_remaining = 0

    def reset(self, seed: int | None = None) -> tuple[int, ...]:
        if seed is not None:
            self.seed = seed
        self.run.deck_key = self.deck_key
        self.run.reset(self.seed)
        self.hand_levels = [1] * len(HAND_KIND_NAMES)
        self.hand_play_counts = [0] * len(HAND_KIND_NAMES)
        self.jokers = []
        self.consumables = list(self.run.starting_consumables)
        self.pack_cards = []
        self.available_voucher = None
        self.purchased_vouchers = []
        self.pack_choices = 1
        self.rounds_cleared = 0
        return self.observation()

    def legal_action_ids(self) -> tuple[int, ...]:
        if self.run.phase == RunPhase.BLIND_SELECT:
            actions = [SELECT_BLIND_ACTION]
            if self.run.blind_kind != 2:
                actions.append(SKIP_BLIND_ACTION)
            return tuple(actions)
        if self.run.phase == RunPhase.SELECTING_HAND:
            return _legal_actions(len(self.run.hand), self.discards_remaining > 0)
        if self.run.phase == RunPhase.ROUND_EVAL:
            return (CASH_OUT_ACTION,)
        if self.run.phase == RunPhase.SHOP:
            return self._legal_shop_actions()
        if self.run.phase == RunPhase.PACK:
            return tuple(PACK_SELECT_ACTION_BASE + index for index in range(len(self.pack_cards))) + (PACK_SKIP_ACTION,)
        return ()

    def action_mask(self) -> tuple[int, ...]:
        mask = [0] * FULL_ACTION_SPACE_SIZE
        for action_id in self.legal_action_ids():
            mask[action_id] = 1
        return tuple(mask)

    def greedy_play_action(self) -> int:
        self._require_selecting_hand()
        best_action = -1
        best_score = -1
        for action_id in _legal_masks(len(self.run.hand)):
            score = self.score_action(action_id)
            if score.total > best_score:
                best_action = action_id
                best_score = score.total
        return best_action

    def score_action(self, action_id: int) -> FastScore:
        self._require_selecting_hand()
        if action_id >= DISCARD_ACTION_OFFSET:
            raise ValueError("discard actions do not have a play score")
        self._validate_mask(action_id)
        return self.score_hand_mask(tuple(self.run.hand), action_id)

    def score_hand_mask(
        self,
        hand: tuple[int, ...],
        mask: int,
        *,
        hands_left: int | None = None,
        discards_left: int | None = None,
    ) -> FastScore:
        selected = tuple(card for index, card in enumerate(hand) if mask & (1 << index))
        sorted_cards = tuple(sorted(selected))
        base = score_cards_with_joker_rules(
            sorted_cards,
            tuple(self.hand_levels),
            tuple(joker.key for joker in self.jokers),
        )
        held = tuple(card for index, card in enumerate(hand) if not mask & (1 << index))
        context = ScoreContext(
            held_cards=held,
            money=self.run.money,
            discards_left=self.discards_remaining if discards_left is None else discards_left,
            hands_left=max(self.hands_remaining - 1, 0) if hands_left is None else hands_left,
            deck_count=max(len(self.run.deck) - self.run.deck_pos, 0),
            joker_slots=self.run.joker_slots,
            is_final_hand=self.hands_remaining <= 1,
        )
        return apply_additive_jokers(base, sorted_cards, len(selected), tuple(self.jokers), context)

    def step(self, action_id: int) -> FullGameStepResult:
        if not 0 <= action_id < FULL_ACTION_SPACE_SIZE:
            raise ValueError(f"invalid action id: {action_id}")
        if action_id == SELECT_BLIND_ACTION:
            return self._step_select_blind()
        if action_id == SKIP_BLIND_ACTION:
            return self._step_skip_blind()
        if action_id == CASH_OUT_ACTION:
            return self._step_cash_out()
        if action_id == NEXT_ROUND_ACTION:
            return self._step_next_round()
        if action_id == REROLL_ACTION:
            return self._step_reroll()
        if action_id == BUY_VOUCHER_ACTION:
            return self._step_buy_voucher()
        if BUY_CARD_ACTION_BASE <= action_id < BUY_CARD_ACTION_BASE + 8:
            return self._step_buy_card(action_id - BUY_CARD_ACTION_BASE)
        if BUY_PACK_ACTION_BASE <= action_id < BUY_PACK_ACTION_BASE + 8:
            return self._step_buy_pack(action_id - BUY_PACK_ACTION_BASE)
        if SELL_JOKER_ACTION_BASE <= action_id < SELL_JOKER_ACTION_BASE + 8:
            return self._step_sell_joker(action_id - SELL_JOKER_ACTION_BASE)
        if USE_CONSUMABLE_ACTION_BASE <= action_id < USE_CONSUMABLE_ACTION_BASE + 8:
            return self._step_use_consumable(action_id - USE_CONSUMABLE_ACTION_BASE)
        if PACK_SELECT_ACTION_BASE <= action_id < PACK_SELECT_ACTION_BASE + 8:
            return self._step_pack_select(action_id - PACK_SELECT_ACTION_BASE)
        if action_id == PACK_SKIP_ACTION:
            return self._step_pack_skip()

        self._require_selecting_hand()
        if not 0 <= action_id < ACTION_SPACE_SIZE:
            raise ValueError(f"invalid tactical action id: {action_id}")

        is_discard = action_id >= DISCARD_ACTION_OFFSET
        mask = action_id - DISCARD_ACTION_OFFSET if is_discard else action_id
        self._validate_mask(mask)

        if is_discard:
            if self.discards_remaining <= 0:
                raise ValueError("no discards remaining")
            self.discards_remaining -= 1
            selected = self._replace_selected(mask)
            return FullGameStepResult(
                observation=self.observation(),
                reward=-0.01,
                terminated=False,
                info=self._info(selected, is_discard=True, hand_score=0, hand_kind=-1),
            )

        score = self.score_action(mask)
        selected = self._replace_selected(mask)
        self.run.score += score.total
        self.hand_play_counts[score.kind] += 1
        self.hands_remaining -= 1

        if self.run.score >= self.run.required_score:
            reward = 1.0 + self.run.score / max(self.run.required_score, 1)
            self.run.phase = RunPhase.ROUND_EVAL
            return FullGameStepResult(
                observation=self.observation(),
                reward=reward,
                terminated=False,
                info=self._info(selected, is_discard=False, hand_score=score.total, hand_kind=score.kind),
            )

        if self.hands_remaining <= 0:
            self.run.phase = RunPhase.GAME_OVER
            return FullGameStepResult(
                observation=self.observation(),
                reward=-1.0,
                terminated=True,
                info=self._info(selected, is_discard=False, hand_score=score.total, hand_kind=score.kind),
            )

        return FullGameStepResult(
            observation=self.observation(),
            reward=score.total / max(self.run.required_score, 1),
            terminated=False,
            info=self._info(selected, is_discard=False, hand_score=score.total, hand_kind=score.kind),
        )

    def observation(self) -> tuple[int, ...]:
        hand = self.run.hand if self.run.phase == RunPhase.SELECTING_HAND else []
        padded_hand = tuple((hand + [-1] * MAX_HAND_OBS)[:MAX_HAND_OBS])
        joker_ids = tuple(_JOKER_OBS_IDS.get(joker.key, 0) for joker in self.jokers)
        padded_jokers = (joker_ids + (0,) * MAX_JOKER_OBS)[:MAX_JOKER_OBS]
        consumable_ids = tuple(_ITEM_OBS_IDS.get(key, 0) for key in self.consumables)
        padded_consumables = (consumable_ids + (0,) * MAX_CONSUMABLE_OBS)[:MAX_CONSUMABLE_OBS]
        shop_ids = tuple(_ITEM_OBS_IDS.get(key, 0) for key in self.run.shop.item_keys)
        padded_shop = (shop_ids + (0,) * MAX_SHOP_OBS)[:MAX_SHOP_OBS]
        voucher_id = 0 if self.available_voucher is None else _ITEM_OBS_IDS.get(self.available_voucher, 0)
        visible_pack_keys = self._pack_keys() if self.run.phase == RunPhase.SHOP else tuple(self.pack_cards)
        pack_ids = tuple(_ITEM_OBS_IDS.get(key, 0) for key in visible_pack_keys)
        padded_pack = (pack_ids + (0,) * MAX_PACK_OBS)[:MAX_PACK_OBS]
        return (
            int(self.run.phase),
            self.run.ante,
            int(self.run.blind_kind),
            self.rounds_cleared,
            self.run.money,
            self.run.score,
            self.run.required_score,
            self.hands_remaining,
            self.discards_remaining,
            self.run.deck_pos,
            *self.hand_levels,
            *self.hand_play_counts,
            *padded_jokers,
            *padded_consumables,
            *padded_shop,
            voucher_id,
            *padded_pack,
            *padded_hand,
        )

    @property
    def won(self) -> bool:
        return self.run.won

    def _start_selected_blind(self) -> None:
        if self.run.phase != RunPhase.BLIND_SELECT:
            raise ValueError("can only start a blind from BLIND_SELECT")
        self.run.select_blind()
        self.run.hand = list(_sort_visible_hand(tuple(self.run.hand)))
        self.hands_remaining = self.run.hands
        self.discards_remaining = self.run.discards

    def _step_select_blind(self) -> FullGameStepResult:
        if self.run.phase != RunPhase.BLIND_SELECT:
            raise ValueError("can only select blind from blind select")
        self._start_selected_blind()
        return FullGameStepResult(self.observation(), 0.0, False, self._phase_info("select_blind"))

    def _step_skip_blind(self) -> FullGameStepResult:
        if self.run.phase != RunPhase.BLIND_SELECT:
            raise ValueError("can only skip blind from blind select")
        if self.run.blind_kind == 2:
            raise ValueError("cannot skip boss blind")
        self._advance_blind()
        return FullGameStepResult(self.observation(), -0.05, self.run.phase == RunPhase.GAME_OVER, self._phase_info("skip_blind"))

    def _step_cash_out(self) -> FullGameStepResult:
        if self.run.phase != RunPhase.ROUND_EVAL:
            raise ValueError("can only cash out from round eval")
        self._finish_round()
        return FullGameStepResult(self.observation(), 0.25, False, self._phase_info("cash_out"))

    def _step_next_round(self) -> FullGameStepResult:
        if self.run.phase != RunPhase.SHOP:
            raise ValueError("can only leave shop from shop")
        self.run.next_round()
        return FullGameStepResult(self.observation(), 0.0, self.run.phase == RunPhase.GAME_OVER, self._phase_info("next_round"))

    def _step_reroll(self) -> FullGameStepResult:
        if self.run.phase != RunPhase.SHOP:
            raise ValueError("can only reroll from shop")
        self.run.reroll_shop()
        self._populate_shop(refresh_voucher=False)
        return FullGameStepResult(self.observation(), -0.05, False, self._phase_info("reroll"))

    def _step_buy_card(self, index: int) -> FullGameStepResult:
        if self.run.phase != RunPhase.SHOP:
            raise ValueError("can only buy card from shop")
        if not 0 <= index < len(self.run.shop.item_keys):
            raise ValueError("shop card index out of range")
        key = self.run.shop.item_keys[index]
        cost = self._item_cost(key)
        if self.run.money < cost:
            raise ValueError("not enough money")
        if key.startswith("j_"):
            if len(self.jokers) >= self.run.joker_slots:
                raise ValueError("no joker slots")
            if any(joker.key == key for joker in self.jokers):
                raise ValueError("duplicate joker is not available in this gym")
            self.jokers.append(_make_joker(key))
        elif key.startswith("c_"):
            if len(self.consumables) >= self.run.consumable_slots:
                raise ValueError("no consumable slots")
            self.consumables.append(key)
        else:
            raise ValueError(f"unsupported shop card: {key}")
        self.run.money -= cost
        del self.run.shop.item_keys[index]
        return FullGameStepResult(self.observation(), 0.05, False, self._phase_info(f"buy:{key}"))

    def _step_buy_pack(self, index: int) -> FullGameStepResult:
        if self.run.phase != RunPhase.SHOP:
            raise ValueError("can only buy pack from shop")
        pack_keys = self._pack_keys()
        if not 0 <= index < len(pack_keys):
            raise ValueError("pack index out of range")
        key = pack_keys[index]
        cost = self._item_cost(key)
        if self.run.money < cost:
            raise ValueError("not enough money")
        self.run.money -= cost
        self.pack_cards = self._generate_pack_cards(key)
        self.pack_choices = booster_spec(key).choices
        self.run.phase = RunPhase.PACK
        return FullGameStepResult(self.observation(), 0.02, False, self._phase_info(f"buy_pack:{key}"))

    def _step_buy_voucher(self) -> FullGameStepResult:
        if self.run.phase != RunPhase.SHOP:
            raise ValueError("can only buy voucher from shop")
        if self.available_voucher is None:
            raise ValueError("no voucher available")
        key = self.available_voucher
        if key in self.purchased_vouchers:
            raise ValueError("voucher already purchased")
        cost = self._item_cost(key)
        if self.run.money < cost:
            raise ValueError("not enough money")
        self.run.money -= cost
        self.purchased_vouchers.append(key)
        self.available_voucher = None
        self._apply_voucher(key)
        return FullGameStepResult(self.observation(), 0.08, False, self._phase_info(f"buy_voucher:{key}"))

    def _step_sell_joker(self, index: int) -> FullGameStepResult:
        if self.run.phase != RunPhase.SHOP:
            raise ValueError("can only sell joker from shop")
        if not 0 <= index < len(self.jokers):
            raise ValueError("joker index out of range")
        joker = self.jokers.pop(index)
        self.run.money += joker.sell_value
        return FullGameStepResult(self.observation(), 0.0, False, self._phase_info(f"sell:{joker.key}"))

    def _step_use_consumable(self, index: int) -> FullGameStepResult:
        if self.run.phase != RunPhase.SHOP:
            raise ValueError("can only use consumable from shop")
        if not 0 <= index < len(self.consumables):
            raise ValueError("consumable index out of range")
        key = self.consumables.pop(index)
        self._apply_consumable(key)
        return FullGameStepResult(self.observation(), 0.05, False, self._phase_info(f"use:{key}"))

    def _step_pack_select(self, index: int) -> FullGameStepResult:
        if self.run.phase != RunPhase.PACK:
            raise ValueError("can only select pack card from pack")
        if not 0 <= index < len(self.pack_cards):
            raise ValueError("pack card index out of range")
        key = self.pack_cards[index]
        if key.startswith("j_") and len(self.jokers) < self.run.joker_slots:
            self.jokers.append(_make_joker(key))
        elif key.startswith("c_"):
            if len(self.consumables) < self.run.consumable_slots:
                self.consumables.append(key)
            else:
                self._apply_consumable(key)
        del self.pack_cards[index]
        self.pack_choices -= 1
        if self.pack_choices <= 0 or not self.pack_cards:
            self.pack_cards = []
            self.run.phase = RunPhase.SHOP
        return FullGameStepResult(self.observation(), 0.05, False, self._phase_info(f"pack_select:{key}"))

    def _step_pack_skip(self) -> FullGameStepResult:
        if self.run.phase != RunPhase.PACK:
            raise ValueError("can only skip pack from pack")
        self.pack_cards = []
        self.run.phase = RunPhase.SHOP
        return FullGameStepResult(self.observation(), 0.0, False, self._phase_info("pack_skip"))

    def _finish_round(self) -> None:
        reward = round_reward(
            blind_kind=self.run.blind_kind,
            money=self.run.money,
            hands_remaining=self.hands_remaining,
            discards_remaining=self.discards_remaining,
            interest_cap=self.run.interest_cap,
            interest_amount=self.run.interest_amount,
            earns_interest=self.run.earns_interest,
            earns_hand_money=self.run.earns_hand_money,
            earns_discard_money=self.run.earns_discard_money,
        )
        self.run.money += reward
        self.rounds_cleared += 1
        self.run.phase = RunPhase.SHOP
        self.run.shop = ShopState(reroll_cost=self.run.base_reroll_cost)
        self._populate_shop()

    def _populate_shop(self, *, refresh_voucher: bool = True) -> None:
        rng = Random(self.seed * 100_003 + self.run.round_num * 1009 + self.run.ante * 7919 + self.run.shop.reroll_cost_increase)
        self.run.shop.item_keys = [self._generate_shop_card(rng) for _ in range(min(self.run.shop_slots, MAX_SHOP_OBS))]
        if refresh_voucher:
            self.available_voucher = self._generate_voucher(rng)

    def _pack_keys(self) -> tuple[str, ...]:
        rng = Random(self.seed * 65_537 + self.run.round_num * 1231 + self.run.ante * 4567)
        return tuple(_weighted_choice(rng, _PACK_WEIGHTS) for _ in range(2))

    def _generate_pack_cards(self, pack_key: str) -> list[str]:
        rng = Random(self.seed * 33_689 + self.run.round_num * 2713 + self.run.ante * 3623 + _ITEM_OBS_IDS.get(pack_key, 0))
        spec = booster_spec(pack_key)
        if spec.kind == BoosterKind.BUFFOON:
            return [rng.choice(_PACK_JOKER_POOL) for _ in range(spec.size)]
        cards = [rng.choice(_PLANET_KEYS) for _ in range(spec.size)]
        if self.run.telescope_guarantees_most_played_planet:
            target = self._planet_target_hand_kind()
            if target is not None:
                cards[0] = _HAND_KIND_TO_PLANET[target]
        return cards

    def _apply_consumable(self, key: str) -> None:
        hand_kind = _PLANET_TO_HAND_KIND.get(key)
        if hand_kind is not None:
            self.hand_levels[hand_kind] += 1

    def _apply_voucher(self, key: str) -> None:
        modifiers = apply_voucher(_run_modifiers(self.run), key)
        _copy_modifiers_to_run(self.run, modifiers)
        self.run.shop.reroll_cost = self.run.base_reroll_cost + self.run.shop.reroll_cost_increase

    def _generate_shop_card(self, rng: Random) -> str:
        joker_weight = max(1.0, 20.0 - self.run.planet_rate)
        planet_weight = max(0.0, self.run.planet_rate)
        category = _weighted_choice(
            rng,
            (
                ("joker", joker_weight),
                ("planet", planet_weight),
            ),
        )
        if category == "planet":
            return rng.choice(_PLANET_KEYS)
        pool = _SHOP_CARD_POOL_BY_ANTE[0] + tuple(key for ante, key in _SHOP_CARD_POOL_BY_ANTE[1] if self.run.ante >= ante)
        return rng.choice(pool)

    def _generate_voucher(self, rng: Random) -> str | None:
        candidates = tuple(key for key in _VOUCHER_POOL if key not in self.purchased_vouchers)
        if not candidates:
            return None
        return rng.choice(candidates)

    def _item_cost(self, key: str) -> int:
        if key.startswith("p_celestial") and self.run.celestial_packs_are_free:
            return 0
        if key.startswith("c_") and self.run.planets_are_free:
            return 0
        return int(_item_cost(key) * self.run.shop_discount)

    def _advance_blind(self) -> None:
        self.run.round_num += 1
        if self.run.blind_kind == 0:
            self.run.blind_kind = type(self.run.blind_kind).BIG
        elif self.run.blind_kind == 1:
            self.run.blind_kind = type(self.run.blind_kind).BOSS
        else:
            self.run.ante += 1
            self.run.blind_kind = type(self.run.blind_kind).SMALL
            if self.run.ante > 8:
                self.run.won = True
                self.run.phase = RunPhase.GAME_OVER
                return
        self.run.phase = RunPhase.BLIND_SELECT

    def _legal_shop_actions(self) -> tuple[int, ...]:
        actions: list[int] = []
        for index, key in enumerate(self.consumables):
            if key.startswith("c_"):
                actions.append(USE_CONSUMABLE_ACTION_BASE + index)
        for index, key in enumerate(self.run.shop.item_keys):
            if self.run.money < self._item_cost(key):
                continue
            if key.startswith("j_") and len(self.jokers) < self.run.joker_slots:
                if any(joker.key == key for joker in self.jokers):
                    continue
                actions.append(BUY_CARD_ACTION_BASE + index)
            elif key.startswith("c_") and len(self.consumables) < self.run.consumable_slots:
                actions.append(BUY_CARD_ACTION_BASE + index)
        if self.available_voucher is not None and self.run.money >= self._item_cost(self.available_voucher):
            actions.append(BUY_VOUCHER_ACTION)
        for index, key in enumerate(self._pack_keys()):
            if self.run.money >= self._item_cost(key):
                actions.append(BUY_PACK_ACTION_BASE + index)
        for index in range(len(self.jokers)):
            actions.append(SELL_JOKER_ACTION_BASE + index)
        if self.run.money >= self.run.shop.reroll_cost:
            actions.append(REROLL_ACTION)
        actions.append(NEXT_ROUND_ACTION)
        return tuple(actions)

    def _planet_target_hand_kind(self) -> int | None:
        best_kind = max(
            range(len(self.hand_play_counts)),
            key=lambda kind: (self.hand_play_counts[kind], self.hand_levels[kind], -kind),
            default=HIGH_CARD,
        )
        if self.hand_play_counts[best_kind] <= 0:
            return None
        return best_kind

    def _draw(self, count: int) -> list[int]:
        end = min(self.run.deck_pos + count, len(self.run.deck))
        drawn = self.run.deck[self.run.deck_pos : end]
        self.run.deck_pos = end
        return drawn

    def _replace_selected(self, mask: int) -> tuple[int, ...]:
        selected: list[int] = []
        kept: list[int] = []
        for index, card in enumerate(self.run.hand):
            if mask & (1 << index):
                selected.append(card)
            else:
                kept.append(card)
        self.run.hand = list(_sort_visible_hand(tuple(kept + self._draw(self.run.hand_size - len(kept)))))
        return tuple(selected)

    def _validate_mask(self, mask: int) -> None:
        if mask <= 0:
            raise ValueError("action must select at least one card")
        if mask >= (1 << len(self.run.hand)):
            raise ValueError("action references cards outside current hand")
        if mask.bit_count() > MAX_SELECTED_CARDS:
            raise ValueError("action cannot select more than five cards")

    def _require_selecting_hand(self) -> None:
        if self.run.phase != RunPhase.SELECTING_HAND:
            raise ValueError("environment is not selecting a hand")

    def _info(
        self,
        selected: tuple[int, ...],
        *,
        is_discard: bool,
        hand_score: int,
        hand_kind: int,
    ) -> dict[str, int | bool | str | tuple[int, ...]]:
        planet_target = self._planet_target_hand_kind()
        return {
            "ante": self.run.ante,
            "blind_kind": int(self.run.blind_kind),
            "rounds_cleared": self.rounds_cleared,
            "score": self.run.score,
            "required_score": self.run.required_score,
            "hands_remaining": self.hands_remaining,
            "discards_remaining": self.discards_remaining,
            "money": self.run.money,
            "selected": selected,
            "is_discard": is_discard,
            "hand_score": hand_score,
            "hand_kind": hand_kind,
            "won": self.run.won,
            "jokers": tuple(joker.key for joker in self.jokers),
            "planet_target_hand_kind": -1 if planet_target is None else planet_target,
        }

    def _phase_info(self, action: str) -> dict[str, int | bool | str | tuple[int, ...]]:
        info = self._info((), is_discard=False, hand_score=0, hand_kind=-1)
        info["phase_action"] = action
        return info


class SearchRunAgent:
    """General deterministic search baseline for the red-deck fast full-game gym."""

    beam_width: int = 4
    action_beam: int = 3

    def act(self, env: FastFullGameEnv) -> int:
        if env.run.phase == RunPhase.BLIND_SELECT:
            return SELECT_BLIND_ACTION
        if env.run.phase == RunPhase.ROUND_EVAL:
            return CASH_OUT_ACTION
        if env.run.phase == RunPhase.SHOP:
            return self._shop_action(env)
        if env.run.phase == RunPhase.PACK:
            return self._pack_action(env)
        if env.run.phase == RunPhase.GAME_OVER:
            raise ValueError("cannot act after game over")

        states: list[tuple[int | None, tuple[int, ...], tuple[int, ...], int, int, int, tuple[Joker, ...]]] = [
            (
                None,
                tuple(env.run.hand),
                tuple(env.run.deck[env.run.deck_pos :]),
                env.run.score,
                env.hands_remaining,
                env.discards_remaining,
                tuple(env.jokers),
            )
        ]
        best_action: int | None = None
        best_score = env.run.score
        max_depth = max(env.hands_remaining + env.discards_remaining, 1)

        for _ in range(max_depth):
            next_states: list[tuple[int, tuple[int, ...], tuple[int, ...], int, int, int, tuple[Joker, ...]]] = []
            for first_action, hand, deck, score, hands, discards, jokers in states:
                if score >= env.run.required_score:
                    if first_action is not None:
                        return first_action
                    continue
                if hands <= 0 or not hand:
                    continue

                for mask, scored in _ranked_play_masks(env, hand, jokers, hands, discards, len(deck), self.action_beam):
                    action = mask
                    selected = _selected_cards(hand, mask)
                    next_hand, next_deck = _replace_selected_from_front(hand, deck, mask)
                    next_score = score + scored.total
                    next_jokers = _jokers_after_play(jokers, scored, selected)
                    candidate_first = first_action if first_action is not None else action
                    if next_score > best_score:
                        best_score = next_score
                        best_action = candidate_first
                    if next_score >= env.run.required_score:
                        return candidate_first
                    next_states.append((candidate_first, next_hand, next_deck, next_score, hands - 1, discards, next_jokers))

                if discards > 0:
                    for mask in _ranked_discard_masks(env, hand, deck, jokers, hands, discards, self.action_beam):
                        action = DISCARD_ACTION_OFFSET + mask
                        next_hand, next_deck = _replace_selected_from_front(hand, deck, mask)
                        next_jokers = _jokers_after_discard(jokers)
                        candidate_first = first_action if first_action is not None else action
                        next_states.append((candidate_first, next_hand, next_deck, score, hands, discards - 1, next_jokers))

            if not next_states:
                break
            next_states.sort(key=lambda item: (item[3] >= env.run.required_score, item[3], item[4], item[5]), reverse=True)
            states = next_states[: self.beam_width]

        return best_action if best_action is not None else env.greedy_play_action()

    def _shop_action(self, env: FastFullGameEnv) -> int:
        for index, key in enumerate(env.consumables):
            if key.startswith("c_"):
                return USE_CONSUMABLE_ACTION_BASE + index
        if env.available_voucher is not None and BUY_VOUCHER_ACTION in env.legal_action_ids():
            value = _VOUCHER_PURCHASE_VALUES.get(env.available_voucher, 0.0) - env._item_cost(env.available_voucher)
            if value > 0:
                return BUY_VOUCHER_ACTION
        best: tuple[float, int] | None = None
        for index, key in enumerate(env.run.shop.item_keys):
            if env.run.money < env._item_cost(key):
                continue
            if key.startswith("j_") and len(env.jokers) < env.run.joker_slots:
                if any(joker.key == key for joker in env.jokers):
                    continue
                value = _JOKER_PURCHASE_VALUES.get(key, 0.0) - env._item_cost(key)
            elif key.startswith("c_") and len(env.consumables) < env.run.consumable_slots:
                target = _PLANET_TO_HAND_KIND.get(key)
                value = (20.0 + 4.0 * env.hand_play_counts[target] if target is not None else 0.0) - env._item_cost(key)
            else:
                continue
            candidate = (value, BUY_CARD_ACTION_BASE + index)
            if best is None or candidate > best:
                best = candidate
        if best is not None and best[0] > 0:
            return best[1]
        pack_action = _best_pack_action(env)
        if pack_action is not None:
            return pack_action
        if env.run.money >= env.run.shop.reroll_cost and len(env.jokers) < env.run.joker_slots and env.run.shop.reroll_cost <= 6:
            return REROLL_ACTION
        return NEXT_ROUND_ACTION

    def _pack_action(self, env: FastFullGameEnv) -> int:
        best: tuple[float, int] | None = None
        for index, key in enumerate(env.pack_cards):
            if key.startswith("j_") and len(env.jokers) < env.run.joker_slots:
                value = _JOKER_PURCHASE_VALUES.get(key, 0.0)
            elif key.startswith("c_"):
                target = _PLANET_TO_HAND_KIND.get(key)
                value = 10.0 + (env.hand_play_counts[target] if target is not None else 0)
            else:
                value = 0.0
            candidate = (value, PACK_SELECT_ACTION_BASE + index)
            if best is None or candidate > best:
                best = candidate
        if best is not None and best[0] > 0:
            return best[1]
        return PACK_SKIP_ACTION


def evaluate_agent(
    seeds: range | tuple[int, ...] | list[int],
    *,
    deck_key: str = "b_red",
    max_steps: int = 600,
) -> dict[str, float | int]:
    agent = SearchRunAgent()
    wins = 0
    rounds = 0
    steps_total = 0
    for seed in seeds:
        env = FastFullGameEnv(deck_key=deck_key)
        env.reset(seed=seed)
        terminated = False
        steps = 0
        while not terminated and steps < max_steps:
            result = env.step(agent.act(env))
            terminated = result.terminated
            steps += 1
        wins += int(env.won)
        rounds += env.rounds_cleared
        steps_total += steps
    seed_count = len(seeds)
    return {
        "seeds": seed_count,
        "wins": wins,
        "win_rate": wins / max(seed_count, 1),
        "avg_rounds_cleared": rounds / max(seed_count, 1),
        "avg_steps": steps_total / max(seed_count, 1),
    }


_GENERAL_JOKER_PURCHASES = (
    ShopPurchase("j_joker", 2, "joker"),
    ShopPurchase("j_abstract", 4, "joker"),
    ShopPurchase("j_bull", 6, "joker"),
    ShopPurchase("j_square", 4, "joker"),
    ShopPurchase("j_ride_the_bus", 6, "joker"),
    ShopPurchase("j_mystic_summit", 5, "joker"),
    ShopPurchase("j_runner", 5, "joker"),
    ShopPurchase("j_trousers", 6, "joker"),
    ShopPurchase("j_cavendish", 4, "joker"),
)
_JOKER_OBS_IDS = {purchase.key: index + 1 for index, purchase in enumerate(_GENERAL_JOKER_PURCHASES)}
_JOKER_PURCHASE_VALUES = {
    "j_joker": 18.0,
    "j_abstract": 24.0,
    "j_bull": 22.0,
    "j_square": 20.0,
    "j_ride_the_bus": 18.0,
    "j_mystic_summit": 16.0,
    "j_runner": 14.0,
    "j_trousers": 16.0,
    "j_cavendish": 40.0,
}
_PLANET_TO_HAND_KIND = {
    "c_pluto": HIGH_CARD,
    "c_mercury": PAIR,
    "c_uranus": TWO_PAIR,
    "c_venus": THREE_OF_A_KIND,
    "c_saturn": STRAIGHT,
    "c_jupiter": FLUSH,
    "c_earth": FULL_HOUSE,
}
_PLANET_KEYS = tuple(_PLANET_TO_HAND_KIND)
_HAND_KIND_TO_PLANET = {hand_kind: key for key, hand_kind in _PLANET_TO_HAND_KIND.items()}
_PACK_WEIGHTS = tuple(
    (key, spec.weight)
    for key, spec in BOOSTER_SPECS.items()
    if spec.kind in {BoosterKind.BUFFOON, BoosterKind.CELESTIAL}
)
_PACK_JOKER_POOL = (
    "j_joker",
    "j_abstract",
    "j_bull",
    "j_square",
    "j_ride_the_bus",
    "j_mystic_summit",
    "j_runner",
    "j_trousers",
    "j_cavendish",
)
_SHOP_CARD_POOL_BY_ANTE = (
    (
        "j_joker",
        "j_abstract",
        "j_bull",
        "j_square",
        "j_mystic_summit",
        "c_pluto",
        "c_mercury",
        "c_jupiter",
    ),
    (
        (2, "j_ride_the_bus"),
        (2, "j_runner"),
        (2, "j_trousers"),
        (3, "j_cavendish"),
        (3, "c_saturn"),
        (3, "c_earth"),
    ),
)
_VOUCHER_COSTS = {
    key: 10
    for key in (
        "v_overstock_norm",
        "v_clearance_sale",
        "v_reroll_surplus",
        "v_crystal_ball",
        "v_grabber",
        "v_wasteful",
        "v_planet_merchant",
        "v_seed_money",
        "v_telescope",
        "v_antimatter",
    )
}
_ITEM_COSTS = {
    **{purchase.key: purchase.cost for purchase in _GENERAL_JOKER_PURCHASES},
    "j_jolly": 4,
    "j_sly": 4,
    "j_droll": 4,
    "j_crafty": 4,
    **{key: 3 for key in _PLANET_KEYS},
    **{key: spec.cost for key, spec in BOOSTER_SPECS.items()},
    **_VOUCHER_COSTS,
}
_VOUCHER_POOL = (
    "v_overstock_norm",
    "v_clearance_sale",
    "v_reroll_surplus",
    "v_crystal_ball",
    "v_grabber",
    "v_wasteful",
    "v_planet_merchant",
    "v_seed_money",
    "v_telescope",
    "v_antimatter",
)
_VOUCHER_PURCHASE_VALUES = {
    "v_overstock_norm": 18.0,
    "v_clearance_sale": 24.0,
    "v_reroll_surplus": 12.0,
    "v_crystal_ball": 10.0,
    "v_grabber": 30.0,
    "v_wasteful": 14.0,
    "v_planet_merchant": 16.0,
    "v_seed_money": 12.0,
    "v_telescope": 16.0,
    "v_antimatter": 28.0,
}
_ITEM_OBS_IDS = {
    key: index + 1
    for index, key in enumerate(
        tuple(_ITEM_COSTS)
    )
}


def _item_cost(key: str) -> int:
    return _ITEM_COSTS.get(key, 99)


def _best_pack_action(env: FastFullGameEnv) -> int | None:
    best: tuple[float, int] | None = None
    for index, key in enumerate(env._pack_keys()):
        cost = env._item_cost(key)
        if env.run.money < cost:
            continue
        spec = booster_spec(key)
        if spec.kind == BoosterKind.BUFFOON and len(env.jokers) < env.run.joker_slots:
            value = 8.0 + 7.0 * (env.run.joker_slots - len(env.jokers))
        elif spec.kind == BoosterKind.CELESTIAL:
            target = env._planet_target_hand_kind()
            value = 8.0 + (5.0 * env.hand_play_counts[target] if target is not None else 0.0)
        else:
            value = 0.0
        candidate = (value - cost, BUY_PACK_ACTION_BASE + index)
        if best is None or candidate > best:
            best = candidate
    if best is not None and best[0] > 0:
        return best[1]
    return None


def _run_modifiers(run: FastRunState) -> RunModifiers:
    return RunModifiers(
        money=run.money,
        hands=run.hands,
        discards=run.discards,
        hand_size=run.hand_size,
        joker_slots=run.joker_slots,
        consumable_slots=run.consumable_slots,
        shop_slots=run.shop_slots,
        interest_cap=run.interest_cap,
        interest_amount=run.interest_amount,
        base_reroll_cost=run.base_reroll_cost,
        shop_discount=run.shop_discount,
        blind_requirement_multiplier=run.blind_requirement_multiplier,
        tarot_rate=run.tarot_rate,
        planet_rate=run.planet_rate,
        spectral_rate=run.spectral_rate,
        edition_rate=run.edition_rate,
        arcana_pack_spectral_chance=run.arcana_pack_spectral_chance,
        telescope_guarantees_most_played_planet=run.telescope_guarantees_most_played_planet,
        observatory_xmult=run.observatory_xmult,
        boss_reroll_cost=run.boss_reroll_cost,
        boss_reroll_once_per_ante=run.boss_reroll_once_per_ante,
        bankrupt_at=run.bankrupt_at,
        probability_multiplier=run.probability_multiplier,
        planets_are_free=run.planets_are_free,
        celestial_packs_are_free=run.celestial_packs_are_free,
        earns_interest=run.earns_interest,
        earns_hand_money=run.earns_hand_money,
        earns_discard_money=run.earns_discard_money,
        starting_consumables=run.starting_consumables,
    )


def _copy_modifiers_to_run(run: FastRunState, modifiers: RunModifiers) -> None:
    run.money = modifiers.money
    run.hands = modifiers.hands
    run.discards = modifiers.discards
    run.hand_size = min(modifiers.hand_size, MAX_HAND_OBS)
    run.joker_slots = modifiers.joker_slots
    run.consumable_slots = modifiers.consumable_slots
    run.shop_slots = min(modifiers.shop_slots, MAX_SHOP_OBS)
    run.interest_cap = modifiers.interest_cap
    run.interest_amount = modifiers.interest_amount
    run.base_reroll_cost = modifiers.base_reroll_cost
    run.shop_discount = modifiers.shop_discount
    run.blind_requirement_multiplier = modifiers.blind_requirement_multiplier
    run.tarot_rate = modifiers.tarot_rate
    run.planet_rate = modifiers.planet_rate
    run.spectral_rate = modifiers.spectral_rate
    run.edition_rate = modifiers.edition_rate
    run.arcana_pack_spectral_chance = modifiers.arcana_pack_spectral_chance
    run.telescope_guarantees_most_played_planet = modifiers.telescope_guarantees_most_played_planet
    run.observatory_xmult = modifiers.observatory_xmult
    run.boss_reroll_cost = modifiers.boss_reroll_cost
    run.boss_reroll_once_per_ante = modifiers.boss_reroll_once_per_ante
    run.bankrupt_at = modifiers.bankrupt_at
    run.probability_multiplier = modifiers.probability_multiplier
    run.planets_are_free = modifiers.planets_are_free
    run.celestial_packs_are_free = modifiers.celestial_packs_are_free
    run.earns_interest = modifiers.earns_interest
    run.earns_hand_money = modifiers.earns_hand_money
    run.earns_discard_money = modifiers.earns_discard_money


def _weighted_choice(rng: Random, items: tuple[tuple[str, float], ...]) -> str:
    total = sum(max(weight, 0.0) for _, weight in items)
    if total <= 0:
        return items[0][0]
    threshold = rng.random() * total
    running = 0.0
    for key, weight in items:
        running += max(weight, 0.0)
        if threshold <= running:
            return key
    return items[-1][0]


def _ranked_play_masks(
    env: FastFullGameEnv,
    hand: tuple[int, ...],
    jokers: tuple[Joker, ...],
    hands_left: int,
    discards_left: int,
    deck_count: int,
    action_beam: int,
) -> tuple[tuple[int, FastScore], ...]:
    scored = [
        (
            mask,
            _score_mask_with_jokers(
                env,
                hand,
                mask,
                jokers=jokers,
                hands_left=max(hands_left - 1, 0),
                discards_left=discards_left,
                deck_count=deck_count,
            ),
        )
        for mask in _legal_masks(len(hand))
    ]
    scored.sort(key=lambda item: item[1].total, reverse=True)
    return tuple(scored[:action_beam])


def _ranked_discard_masks(
    env: FastFullGameEnv,
    hand: tuple[int, ...],
    deck: tuple[int, ...],
    jokers: tuple[Joker, ...],
    hands_left: int,
    discards_left: int,
    action_beam: int,
) -> tuple[int, ...]:
    scored: list[tuple[int, int]] = []
    for mask in _legal_masks(len(hand)):
        next_hand, next_deck = _replace_selected_from_front(hand, deck, mask)
        if not next_hand:
            continue
        best_next_score = max(
            _score_mask_with_jokers(
                env,
                next_hand,
                play_mask,
                jokers=jokers,
                hands_left=max(hands_left - 1, 0),
                discards_left=max(discards_left - 1, 0),
                deck_count=len(next_deck),
            ).total
            for play_mask in _legal_masks(len(next_hand))
        )
        scored.append((best_next_score, mask))
    scored.sort(reverse=True)
    return tuple(mask for _, mask in scored[:action_beam])


def _score_mask_with_jokers(
    env: FastFullGameEnv,
    hand: tuple[int, ...],
    mask: int,
    *,
    jokers: tuple[Joker, ...],
    hands_left: int,
    discards_left: int,
    deck_count: int,
) -> FastScore:
    selected = _selected_cards(hand, mask)
    sorted_cards = tuple(sorted(selected))
    base = score_cards_with_joker_rules(
        sorted_cards,
        tuple(env.hand_levels),
        tuple(joker.key for joker in jokers),
    )
    context = ScoreContext(
        held_cards=tuple(card for index, card in enumerate(hand) if not mask & (1 << index)),
        money=env.run.money,
        discards_left=discards_left,
        hands_left=hands_left,
        deck_count=deck_count,
        joker_slots=env.run.joker_slots,
        is_final_hand=hands_left <= 0,
    )
    return apply_additive_jokers(base, sorted_cards, len(selected), jokers, context)


def _jokers_after_play(jokers: tuple[Joker, ...], score: FastScore, selected: tuple[int, ...]) -> tuple[Joker, ...]:
    from balatro_ai_v2.fast.hand import FULL_HOUSE, STRAIGHT, TWO_PAIR
    out: list[Joker] = []
    selected_count = len(selected)
    has_scored_face = any(
        score.scoring_mask & (1 << index) and rank(card) in {9, 10, 11}
        for index, card in enumerate(tuple(sorted(selected)))
    )
    for joker in jokers:
        if joker.key == "j_square" and selected_count == 4:
            out.append(_replace_joker(joker, scaling=joker.scaling + 4))
        elif joker.key == "j_runner" and score.kind == STRAIGHT:
            out.append(_replace_joker(joker, scaling=joker.scaling + 15))
        elif joker.key == "j_trousers" and score.kind in {TWO_PAIR, FULL_HOUSE}:
            out.append(_replace_joker(joker, scaling=joker.scaling + 2))
        elif joker.key == "j_green_joker":
            out.append(_replace_joker(joker, scaling=joker.scaling + 1))
        elif joker.key == "j_ride_the_bus" and not has_scored_face:
            out.append(_replace_joker(joker, scaling=joker.scaling + 1))
        else:
            out.append(joker)
    return tuple(out)


def _jokers_after_discard(jokers: tuple[Joker, ...]) -> tuple[Joker, ...]:
    out: list[Joker] = []
    for joker in jokers:
        if joker.key == "j_green_joker":
            out.append(_replace_joker(joker, scaling=max(joker.scaling - 1, 0)))
        else:
            out.append(joker)
    return tuple(out)


def _replace_joker(joker: Joker, *, scaling: int) -> Joker:
    return Joker(
        key=joker.key,
        scaling=scaling,
        x_mult=joker.x_mult,
        sell_value=joker.sell_value,
        edition=joker.edition,
    )


def _selected_cards(hand: tuple[int, ...], mask: int) -> tuple[int, ...]:
    return tuple(card for index, card in enumerate(hand) if mask & (1 << index))


def _make_joker(key: str) -> Joker:
    if key == "j_cavendish":
        return Joker(key=key, x_mult=3.0, sell_value=2)
    return Joker(key=key, sell_value=1)


def _replace_selected_from_front(
    hand: tuple[int, ...],
    deck: tuple[int, ...],
    mask: int,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    kept = tuple(card for index, card in enumerate(hand) if not mask & (1 << index))
    draw_count = min(len(hand) - len(kept), len(deck))
    drawn = deck[:draw_count]
    return _sort_visible_hand(kept + drawn), deck[draw_count:]


def _sort_visible_hand(cards: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(sorted(cards, key=lambda card: (-rank(card), suit(card))))


@lru_cache(maxsize=16)
def _legal_masks(hand_len: int) -> tuple[int, ...]:
    return tuple(
        mask
        for mask in range(1, 1 << hand_len)
        if mask.bit_count() <= MAX_SELECTED_CARDS
    )


@lru_cache(maxsize=32)
def _legal_actions(hand_len: int, can_discard: bool) -> tuple[int, ...]:
    masks = _legal_masks(hand_len)
    if not can_discard:
        return masks
    actions: list[int] = []
    for mask in masks:
        actions.append(mask)
        actions.append(DISCARD_ACTION_OFFSET + mask)
    return tuple(actions)


@lru_cache(maxsize=32)
def _action_mask(hand_len: int, can_discard: bool) -> tuple[int, ...]:
    mask = [0] * ACTION_SPACE_SIZE
    for action_id in _legal_actions(hand_len, can_discard):
        mask[action_id] = 1
    return tuple(mask)
