from __future__ import annotations

from dataclasses import dataclass, field, fields as dataclass_fields
from functools import lru_cache
import re
from random import Random

from balatro_ai_v2.fast.blinds import BLIND_RULES, BlindHandPolicy, BlindRule
from balatro_ai_v2.fast.boosters import BOOSTER_SPECS, BoosterKind, booster_spec
from balatro_ai_v2.fast.cards import NUM_RANKS, chips as card_chips, rank, suit
from balatro_ai_v2.fast.consumables import (
    DETERMINISTIC_CONSUMABLES,
    PLANET_HANDS,
    SPECTRAL_SEALS,
    TAROT_ENHANCEMENTS,
    TAROT_SUIT_CONVERSIONS,
    TAROT_TARGET_LIMITS,
)
from balatro_ai_v2.fast.env import ACTION_SPACE_SIZE, DISCARD_ACTION_OFFSET, MAX_SELECTED_CARDS
from balatro_ai_v2.fast.hand import (
    BASE_CHIPS,
    BASE_MULT,
    FLUSH,
    FULL_HOUSE,
    HAND_KIND_NAMES,
    HIGH_CARD,
    LEVEL_CHIPS,
    LEVEL_MULT,
    PAIR,
    STRAIGHT,
    THREE_OF_A_KIND,
    TWO_PAIR,
    FastScore,
    score_cards_with_joker_rules,
)
from balatro_ai_v2.fast.jokers import (
    IMPLEMENTED_JOKERS,
    PROBABILISTIC_SCORE_JOKERS,
    Joker,
    ScoreContext,
    apply_additive_jokers,
)
from balatro_ai_v2.fast.joker_money import (
    DOLLAR_BONUS_JOKERS,
    MONEY_EVENT_JOKERS,
    DollarBonusContext,
    total_joker_dollar_bonus,
)
from balatro_ai_v2.fast.joker_run_rules import RUN_EFFECT_JOKERS, apply_joker_run_effect
from balatro_ai_v2.fast.run import (
    BLIND_MULT,
    BlindKind,
    FastRunState,
    RunPhase,
    ShopState,
    _ante_base_chips,
    round_reward,
)
from balatro_ai_v2.fast.run_rules import RunModifiers, apply_deck, apply_voucher, starting_deck
from balatro_ai_v2.fast.tags import TAG_RULES, TagTrigger, tag_money_delta
from balatro_ai_v2.rules import RuleCatalog, load_rule_catalog


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

# Bosses whose effects are information/selection constraints the integer-card
# env cannot represent yet. They keep their score_mult but their special rule
# is a no-op in-sim; the planner applies a value penalty when one is upcoming.
UNMODELED_BOSS_EFFECTS = frozenset(
    {
        "bl_house",
        "bl_wheel",
        "bl_fish",
        "bl_mark",
        "bl_final_acorn",
        "bl_final_heart",
        "bl_final_bell",
    }
)

# Tags whose effect is a no-op in-sim; they can still be drawn so skip
# decisions stay honest, but the planner treats their value as zero.
UNMODELED_TAGS = frozenset({"tag_boss"})

_TAG_EDITION_IDS = {"foil": 1, "holo": 2, "polychrome": 3, "negative": 4}


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
    deck_cards: list[int] = field(init=False)
    planets_used: set[str] = field(init=False)
    consumable_hand_size_delta: int = field(default=0, init=False)
    boss_key: str | None = field(default=None, init=False)
    used_boss_keys: list[str] = field(init=False)
    round_hand_size: int = field(default=8, init=False)
    first_hand_kind_this_round: int | None = field(default=None, init=False)
    played_hand_kinds_this_round: set[int] = field(init=False)
    cards_played_this_ante: set[int] = field(init=False)
    ox_target_kind: int | None = field(default=None, init=False)
    tags: list[str] = field(init=False)
    blinds_skipped: int = field(default=0, init=False)
    unused_discards_total: int = field(default=0, init=False)
    pack_return_phase: RunPhase = field(default=RunPhase.SHOP, init=False)
    shop_item_editions: dict[int, int] = field(init=False)
    free_shop_item_indices: set[int] = field(init=False)
    coupon_active: bool = field(default=False, init=False)
    d6_active: bool = field(default=False, init=False)
    bought_pack_indices: set[int] = field(init=False)
    # Live-mirror overrides: exact visible prices/pack offers from the real
    # game take precedence over source costs for the current shop only.
    cost_overrides: dict[str, int] = field(init=False)
    pack_keys_override: tuple[str, ...] | None = field(default=None, init=False)

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
        self.deck_cards = sorted(card.card_id for card in starting_deck(self.deck_key, self.seed))
        self.planets_used = set()
        self.used_boss_keys = []
        self.played_hand_kinds_this_round = set()
        self.cards_played_this_ante = set()
        self.tags = []
        self.shop_item_editions = {}
        self.free_shop_item_indices = set()
        self.bought_pack_indices = set()
        self.cost_overrides = {}

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
        self.deck_cards = sorted(card.card_id for card in starting_deck(self.deck_key, self.seed))
        self.planets_used = set()
        self.consumable_hand_size_delta = 0
        self.boss_key = None
        self.used_boss_keys = []
        self.round_hand_size = self.run.hand_size
        self.first_hand_kind_this_round = None
        self.played_hand_kinds_this_round = set()
        self.cards_played_this_ante = set()
        self.ox_target_kind = None
        self.tags = []
        self.blinds_skipped = 0
        self.unused_discards_total = 0
        self.pack_return_phase = RunPhase.SHOP
        self.shop_item_editions = {}
        self.free_shop_item_indices = set()
        self.coupon_active = False
        self.d6_active = False
        self.bought_pack_indices = set()
        self.cost_overrides = {}
        self.pack_keys_override = None
        self._select_boss_for_ante()
        self._sync_required_score()
        return self.observation()

    def clone(self) -> "FastFullGameEnv":
        """Fast deep-enough copy for rollouts (replaces deepcopy).

        All mutable env state lives in shallow containers of immutable values
        (ints, strs, frozen Jokers), so copying one container level is enough.
        """
        new = object.__new__(FastFullGameEnv)
        for spec in dataclass_fields(self):
            value = getattr(self, spec.name)
            if spec.name == "run":
                value = _clone_run_state(value)
            elif isinstance(value, list):
                value = list(value)
            elif isinstance(value, set):
                value = set(value)
            elif isinstance(value, dict):
                value = dict(value)
            setattr(new, spec.name, value)
        return new

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
        boss_rule = self._boss_rule()
        if boss_rule is not None:
            if self._play_blocked(boss_rule, base.kind, len(selected)):
                return FastScore(kind=base.kind, chips=0, mult=0.0, total=0, scoring_mask=base.scoring_mask)
            base = self._boss_adjusted_score(boss_rule, base, sorted_cards)
        held = tuple(card for index, card in enumerate(hand) if not mask & (1 << index))
        context = ScoreContext(
            held_cards=held,
            money=self.run.money,
            discards_left=self.discards_remaining if discards_left is None else discards_left,
            hands_left=max(self.hands_remaining - 1, 0) if hands_left is None else hands_left,
            deck_count=max(len(self.run.deck) - self.run.deck_pos, 0),
            joker_slots=self.run.joker_slots,
            is_final_hand=self.hands_remaining <= 1,
            blinds_skipped=self.blinds_skipped,
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
            self.jokers = list(_jokers_after_discard(tuple(self.jokers), len(selected)))
            return FullGameStepResult(
                observation=self.observation(),
                reward=-0.01,
                terminated=False,
                info=self._info(selected, is_discard=True, hand_score=0, hand_kind=-1),
            )

        boss_rule = self._boss_rule()
        if boss_rule is not None and boss_rule.hand_policy == BlindHandPolicy.DOWNLEVEL_HAND:
            arm_kind = self.score_hand_mask(tuple(self.run.hand), mask).kind
            if self.hand_levels[arm_kind] > 1:
                self.hand_levels[arm_kind] -= 1
        score = self.score_action(mask)
        selected = self._replace_selected(mask)
        self.run.score += score.total
        self.hand_play_counts[score.kind] += 1
        self.hands_remaining -= 1
        self.jokers = list(_jokers_after_play(tuple(self.jokers), score, selected))
        self.cards_played_this_ante.update(selected)
        if boss_rule is not None:
            if score.total > 0:
                if self.first_hand_kind_this_round is None:
                    self.first_hand_kind_this_round = score.kind
                self.played_hand_kinds_this_round.add(score.kind)
            if (
                boss_rule.hand_policy == BlindHandPolicy.DRAIN_MONEY_ON_MOST_PLAYED
                and score.kind == self.ox_target_kind
            ):
                self.run.money = 0
            if boss_rule.dollar_loss_per_played_card:
                self.run.money -= boss_rule.dollar_loss_per_played_card * len(selected)

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
        self._sync_required_score()
        rule = self._boss_rule()
        hand_size = self.run.hand_size + (rule.hand_size_delta if rule is not None else 0)
        while "tag_juggle" in self.tags:
            self.tags.remove("tag_juggle")
            hand_size += 3
        self.round_hand_size = max(1, min(hand_size, MAX_HAND_OBS))
        self.run.deck = list(self.deck_cards)
        Random(self.seed + self.run.round_num).shuffle(self.run.deck)
        self.run.deck_pos = 0
        self.run.hand = self._draw(self.round_hand_size)
        self.run.hand = list(_sort_visible_hand(tuple(self.run.hand)))
        self.hands_remaining = self.run.hands
        self.discards_remaining = self.run.discards
        self.first_hand_kind_this_round = None
        self.played_hand_kinds_this_round = set()
        self.ox_target_kind = None
        if rule is not None:
            self.hands_remaining = max(1, self.run.hands + rule.hands_delta)
            self.discards_remaining = max(0, self.run.discards + rule.discard_delta)
            if rule.hand_policy == BlindHandPolicy.DRAIN_MONEY_ON_MOST_PLAYED and any(self.hand_play_counts):
                self.ox_target_kind = max(
                    range(len(self.hand_play_counts)),
                    key=lambda kind: (self.hand_play_counts[kind], -kind),
                )

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
        self.blinds_skipped += 1
        self._award_tag(self.skip_tag_key())
        self._advance_blind()
        if self.run.phase == RunPhase.BLIND_SELECT:
            self._open_pending_tag_pack()
        return FullGameStepResult(self.observation(), -0.05, self.run.phase == RunPhase.GAME_OVER, self._phase_info("skip_blind"))

    def skip_tag_key(self) -> str:
        """The tag the current small/big blind would award if skipped."""
        rng = Random(self.seed * 131 + self.run.round_num * 257 + self.run.ante * 31 + int(self.run.blind_kind))
        pool = [
            rule.key
            for rule in TAG_RULES.values()
            if rule.min_ante is None or self.run.ante >= rule.min_ante
        ]
        return rng.choice(pool)

    def _award_tag(self, key: str) -> None:
        copies = 1
        while "tag_double" in self.tags and key != "tag_double":
            self.tags.remove("tag_double")
            copies += 1
        for _ in range(copies):
            self._apply_or_queue_tag(key)

    def _apply_or_queue_tag(self, key: str) -> None:
        rule = TAG_RULES[key]
        if rule.trigger == TagTrigger.IMMEDIATE:
            if rule.spawn_jokers:
                pool = [
                    joker_key
                    for joker_key in self._available_joker_pool()
                    if _source_joker_rarities().get(joker_key, 1) == 1
                ]
                for joker_key in pool[: rule.spawn_jokers]:
                    if len(self.jokers) >= self.run.joker_slots:
                        break
                    self.jokers.append(_make_joker(joker_key))
                    if joker_key in RUN_EFFECT_JOKERS:
                        self._recompute_run_modifiers()
            elif rule.hand_levels:
                rng = Random(self.seed * 379 + self.run.round_num * 67 + len(self.tags))
                self.hand_levels[rng.randrange(len(self.hand_levels))] += rule.hand_levels
            else:
                self.run.money += tag_money_delta(
                    key,
                    hands_played=sum(self.hand_play_counts),
                    discards_unused=self.unused_discards_total,
                    money=self.run.money,
                    skips=self.blinds_skipped,
                )
            return
        self.tags.append(key)

    def _open_pending_tag_pack(self) -> None:
        if self.run.phase != RunPhase.BLIND_SELECT:
            return
        for key in self.tags:
            rule = TAG_RULES[key]
            if rule.free_pack_keys:
                self.tags.remove(key)
                rng = Random(self.seed * 977 + self.run.round_num * 41 + self.run.ante)
                pack_key = rng.choice(rule.free_pack_keys)
                self.pack_cards = self._generate_pack_cards(pack_key)
                self.pack_choices = booster_spec(pack_key).choices
                self.pack_return_phase = RunPhase.BLIND_SELECT
                self.run.phase = RunPhase.PACK
                return

    def _step_cash_out(self) -> FullGameStepResult:
        if self.run.phase != RunPhase.ROUND_EVAL:
            raise ValueError("can only cash out from round eval")
        self._finish_round()
        return FullGameStepResult(self.observation(), 0.25, False, self._phase_info("cash_out"))

    def _step_next_round(self) -> FullGameStepResult:
        if self.run.phase != RunPhase.SHOP:
            raise ValueError("can only leave shop from shop")
        prev_ante = self.run.ante
        self.run.next_round()
        if self.run.phase != RunPhase.GAME_OVER:
            if self.run.ante != prev_ante:
                self._select_boss_for_ante()
            self._sync_required_score()
        return FullGameStepResult(self.observation(), 0.0, self.run.phase == RunPhase.GAME_OVER, self._phase_info("next_round"))

    def _step_reroll(self) -> FullGameStepResult:
        if self.run.phase != RunPhase.SHOP:
            raise ValueError("can only reroll from shop")
        self.coupon_active = False
        self.run.reroll_shop()
        if self.d6_active:
            self.run.shop.reroll_cost = self.run.shop.reroll_cost_increase
        self._populate_shop(refresh_voucher=False)
        self.jokers = [
            _replace_joker(joker, scaling=joker.scaling + 2) if joker.key == "j_flash" else joker
            for joker in self.jokers
        ]
        return FullGameStepResult(self.observation(), -0.05, False, self._phase_info("reroll"))

    def _step_buy_card(self, index: int) -> FullGameStepResult:
        if self.run.phase != RunPhase.SHOP:
            raise ValueError("can only buy card from shop")
        if not 0 <= index < len(self.run.shop.item_keys):
            raise ValueError("shop card index out of range")
        key = self.run.shop.item_keys[index]
        cost = 0 if index in self.free_shop_item_indices else self._item_cost(key)
        if self.run.money < cost:
            raise ValueError("not enough money")
        if key.startswith("j_"):
            if any(joker.key == key for joker in self.jokers):
                raise ValueError("duplicate joker is not available in this gym")
            edition = self.shop_item_editions.get(index, 0)
            if edition == 4:
                self.run.joker_slots += 1
            if len(self.jokers) >= self.run.joker_slots:
                raise ValueError("no joker slots")
            joker = _make_joker(key)
            if edition:
                joker = Joker(
                    key=joker.key,
                    scaling=joker.scaling,
                    x_mult=joker.x_mult,
                    sell_value=joker.sell_value,
                    edition=edition,
                )
            self.jokers.append(joker)
            if key in RUN_EFFECT_JOKERS:
                self._recompute_run_modifiers()
        elif key.startswith("c_"):
            if len(self.consumables) >= self.run.consumable_slots:
                raise ValueError("no consumable slots")
            self.consumables.append(key)
        else:
            raise ValueError(f"unsupported shop card: {key}")
        self.run.money -= cost
        del self.run.shop.item_keys[index]
        self.shop_item_editions = {
            (i if i < index else i - 1): edition_id
            for i, edition_id in self.shop_item_editions.items()
            if i != index
        }
        self.free_shop_item_indices = {
            i if i < index else i - 1 for i in self.free_shop_item_indices if i != index
        }
        return FullGameStepResult(self.observation(), 0.05, False, self._phase_info(f"buy:{key}"))

    def _step_buy_pack(self, index: int) -> FullGameStepResult:
        if self.run.phase != RunPhase.SHOP:
            raise ValueError("can only buy pack from shop")
        pack_keys = self._pack_keys()
        if not 0 <= index < len(pack_keys):
            raise ValueError("pack index out of range")
        if index in self.bought_pack_indices:
            raise ValueError("pack already bought this shop")
        key = pack_keys[index]
        cost = 0 if self.coupon_active else self._item_cost(key)
        if self.run.money < cost:
            raise ValueError("not enough money")
        self.run.money -= cost
        self.bought_pack_indices.add(index)
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
        if joker.edition == 4:
            self.run.joker_slots = max(self.run.joker_slots - 1, 1)
        if joker.key in RUN_EFFECT_JOKERS:
            self._recompute_run_modifiers()
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
            if key in RUN_EFFECT_JOKERS:
                self._recompute_run_modifiers()
        elif key.startswith("c_"):
            self._apply_consumable(key)
        del self.pack_cards[index]
        self.pack_choices -= 1
        if self.pack_choices <= 0 or not self.pack_cards:
            self._close_pack()
        return FullGameStepResult(self.observation(), 0.05, False, self._phase_info(f"pack_select:{key}"))

    def _step_pack_skip(self) -> FullGameStepResult:
        if self.run.phase != RunPhase.PACK:
            raise ValueError("can only skip pack from pack")
        self.pack_cards = []
        self._close_pack()
        self.jokers = [
            _replace_joker(joker, scaling=joker.scaling + 3) if joker.key == "j_red_card" else joker
            for joker in self.jokers
        ]
        return FullGameStepResult(self.observation(), 0.0, False, self._phase_info("pack_skip"))

    def _close_pack(self) -> None:
        self.pack_cards = []
        self.pack_choices = 1
        self.run.phase = self.pack_return_phase
        self.pack_return_phase = RunPhase.SHOP
        if self.run.phase == RunPhase.BLIND_SELECT:
            self._open_pending_tag_pack()

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
        if self.run.blind_kind == BlindKind.BOSS:
            # Rocket's payout bump on boss defeat lands before the cash-out payout.
            self.jokers = [
                _replace_joker(joker, scaling=joker.scaling + 2) if joker.key == "j_rocket" else joker
                for joker in self.jokers
            ]
            while "tag_investment" in self.tags:
                self.tags.remove("tag_investment")
                reward += 25
        payout_jokers = tuple(joker for joker in self.jokers if joker.key in DOLLAR_BONUS_JOKERS)
        if payout_jokers:
            reward += total_joker_dollar_bonus(
                payout_jokers,
                DollarBonusContext(
                    deck_cards=tuple(self.deck_cards),
                    discards_used=max(self.run.discards - self.discards_remaining, 0),
                    discards_left=self.discards_remaining,
                    planets_used=frozenset(self.planets_used),
                ),
            )
        self.run.money += reward
        self.jokers = _jokers_after_round(self.jokers)
        self.unused_discards_total += max(self.discards_remaining, 0)
        self.rounds_cleared += 1
        self.run.phase = RunPhase.SHOP
        self.run.shop = ShopState(reroll_cost=self.run.base_reroll_cost)
        self.bought_pack_indices = set()
        self.cost_overrides = {}
        self.pack_keys_override = None
        self._populate_shop()

    def _populate_shop(self, *, refresh_voucher: bool = True) -> None:
        rng = Random(self.seed * 100_003 + self.run.round_num * 1009 + self.run.ante * 7919 + self.run.shop.reroll_cost_increase)
        self.run.shop.item_keys = [self._generate_shop_card(rng) for _ in range(min(self.run.shop_slots, MAX_SHOP_OBS))]
        self.shop_item_editions = {}
        self.free_shop_item_indices = set()
        self._consume_shop_tags(rng, new_shop=refresh_voucher)
        if refresh_voucher:
            self.available_voucher = self._generate_voucher(rng)
            if self.available_voucher is None and "tag_voucher" in self.tags:
                self.available_voucher = self._generate_voucher(rng)
            if self.available_voucher is not None and "tag_voucher" in self.tags:
                self.tags.remove("tag_voucher")

    def _consume_shop_tags(self, rng: Random, *, new_shop: bool) -> None:
        item_keys = self.run.shop.item_keys
        for key in list(self.tags):
            rule = TAG_RULES[key]
            if rule.joker_rarity is not None:
                pool = tuple(
                    joker_key
                    for joker_key in self._available_joker_pool()
                    if _source_joker_rarities().get(joker_key, 1) == rule.joker_rarity
                )
                if pool and item_keys:
                    target = next(
                        (index for index, item in enumerate(item_keys) if item.startswith("j_")),
                        0,
                    )
                    item_keys[target] = rng.choice(pool)
                    self.tags.remove(key)
            elif rule.joker_edition is not None:
                target = next(
                    (index for index, item in enumerate(item_keys) if item.startswith("j_")),
                    None,
                )
                if target is not None and target not in self.shop_item_editions:
                    self.shop_item_editions[target] = _TAG_EDITION_IDS[rule.joker_edition]
                    self.free_shop_item_indices.add(target)
                    self.tags.remove(key)
        if new_shop:
            self.coupon_active = False
            self.d6_active = False
            if "tag_coupon" in self.tags:
                self.tags.remove("tag_coupon")
                self.coupon_active = True
                self.free_shop_item_indices.update(range(len(item_keys)))
            if "tag_d_six" in self.tags:
                self.tags.remove("tag_d_six")
                self.d6_active = True
                self.run.shop.reroll_cost = 0

    def _pack_keys(self) -> tuple[str, ...]:
        if self.pack_keys_override is not None:
            return self.pack_keys_override
        rng = Random(self.seed * 65_537 + self.run.round_num * 1231 + self.run.ante * 4567)
        if self.run.ante == 1 and self.run.round_num == 0:
            first_buffoon = f"p_buffoon_normal_{rng.randrange(1, 3)}"
            return (first_buffoon, _weighted_choice(rng, _PACK_WEIGHTS))
        return tuple(_weighted_choice(rng, _PACK_WEIGHTS) for _ in range(2))

    def _generate_pack_cards(self, pack_key: str) -> list[str]:
        rng = Random(self.seed * 33_689 + self.run.round_num * 2713 + self.run.ante * 3623 + _ITEM_OBS_IDS.get(pack_key, 0))
        spec = booster_spec(pack_key)
        if spec.kind == BoosterKind.BUFFOON:
            return _sample_joker_offers(rng, self._available_joker_pool(), spec.size)
        if spec.kind == BoosterKind.ARCANA:
            return [rng.choice(_TAROT_KEYS) for _ in range(spec.size)]
        if spec.kind == BoosterKind.SPECTRAL and _SPECTRAL_KEYS:
            return [rng.choice(_SPECTRAL_KEYS) for _ in range(spec.size)]
        cards = [rng.choice(self._available_planet_pool()) for _ in range(spec.size)]
        if spec.kind == BoosterKind.CELESTIAL and self.run.telescope_guarantees_most_played_planet:
            target = self._planet_target_hand_kind()
            if target is not None:
                cards[0] = _HAND_KIND_TO_PLANET[target]
        return cards

    def _apply_consumable(self, key: str) -> None:
        hand_kind = _PLANET_TO_HAND_KIND.get(key)
        if hand_kind is not None:
            self.hand_levels[hand_kind] += 1
            self.planets_used.add(key)
            self.jokers = [
                _replace_joker(joker, x_mult=round(joker.x_mult + 0.1, 2))
                if joker.key == "j_constellation"
                else joker
                for joker in self.jokers
            ]
        elif key == "c_black_hole":
            self.hand_levels = [level + 1 for level in self.hand_levels]
        elif key == "c_hermit":
            self.run.money += min(self.run.money, 20)
        elif key == "c_temperance":
            self.run.money += min(sum(joker.sell_value for joker in self.jokers), 50)
        elif key == "c_high_priestess":
            target = self._planet_target_hand_kind()
            planet = _HAND_KIND_TO_PLANET.get(target, "c_mercury")
            if len(self.consumables) < self.run.consumable_slots:
                self.consumables.append(planet)
        elif key == "c_emperor":
            for tarot in ("c_hermit", "c_high_priestess"):
                if len(self.consumables) < self.run.consumable_slots:
                    self.consumables.append(tarot)
        elif key == "c_judgement" and len(self.jokers) < self.run.joker_slots:
            self.jokers.append(_make_joker(self._available_joker_pool()[0]))
            if self.jokers[-1].key in RUN_EFFECT_JOKERS:
                self._recompute_run_modifiers()
        elif key == "c_wraith" and len(self.jokers) < self.run.joker_slots:
            rare_pool = tuple(key for key in self._available_joker_pool() if _source_joker_rarities().get(key, 1) == 3)
            self.jokers.append(_make_joker((rare_pool or self._available_joker_pool())[0]))
            self.run.money = 0
            if self.jokers[-1].key in RUN_EFFECT_JOKERS:
                self._recompute_run_modifiers()
        elif key == "c_immolate":
            targets = self._target_cards_for_consumable(key)
            self._remove_hand_cards(targets)
            self.run.money += 20
        elif key == "c_hanged_man":
            self._remove_hand_cards(self._target_cards_for_consumable(key))
        elif key == "c_death":
            targets = self._target_cards_for_consumable(key)
            if len(targets) == 2:
                dest_index, source_index = targets
                self._replace_hand_card(dest_index, self.run.hand[source_index])
                self.run.hand = list(_sort_visible_hand(tuple(self.run.hand)))
        elif key == "c_strength":
            for index in self._target_cards_for_consumable(key):
                card = self.run.hand[index]
                self._replace_hand_card(index, suit(card) * NUM_RANKS + min(rank(card) + 1, NUM_RANKS - 1))
            self.run.hand = list(_sort_visible_hand(tuple(self.run.hand)))
        elif key in TAROT_SUIT_CONVERSIONS:
            target_suit = TAROT_SUIT_CONVERSIONS[key]
            for index in self._target_cards_for_consumable(key):
                card = self.run.hand[index]
                self._replace_hand_card(index, target_suit * NUM_RANKS + rank(card))
            self.run.hand = list(_sort_visible_hand(tuple(self.run.hand)))
        elif key == "c_sigil" and self.run.hand:
            target_suit = max(range(4), key=lambda suit_value: sum(1 for card in self.run.hand if suit(card) == suit_value))
            for index, card in enumerate(tuple(self.run.hand)):
                self._replace_hand_card(index, target_suit * NUM_RANKS + rank(card))
            self.run.hand = list(_sort_visible_hand(tuple(self.run.hand)))
        elif key == "c_ouija" and self.run.hand:
            target_rank = max(range(NUM_RANKS), key=lambda rank_value: sum(1 for card in self.run.hand if rank(card) == rank_value))
            for index, card in enumerate(tuple(self.run.hand)):
                self._replace_hand_card(index, suit(card) * NUM_RANKS + target_rank)
            self.consumable_hand_size_delta -= 1
            self.run.hand_size = max(1, self.run.hand_size - 1)
            self.run.hand = list(_sort_visible_hand(tuple(self.run.hand)))
        elif key == "c_cryptid" and self.run.hand:
            target = max(self.run.hand, key=lambda card: (rank(card), -suit(card)))
            self.deck_cards.extend([target, target])
        elif key in TAROT_ENHANCEMENTS or key in SPECTRAL_SEALS or key in {"c_aura", "c_wheel_of_fortune", "c_ankh", "c_hex", "c_ectoplasm"}:
            # The current full-game env stores int cards, so enhancement/seal
            # and joker-edition effects are intentionally left for the
            # FastCardState scoring migration.
            return

    def _target_cards_for_consumable(self, key: str) -> tuple[int, ...]:
        if not self.run.hand:
            return ()
        if key in {"c_hanged_man", "c_immolate"}:
            limit = 5 if key == "c_immolate" else TAROT_TARGET_LIMITS[key]
            ranked = sorted(range(len(self.run.hand)), key=lambda index: (rank(self.run.hand[index]), suit(self.run.hand[index])))
            return tuple(ranked[: min(limit, len(ranked))])
        if key == "c_death":
            if len(self.run.hand) < 2:
                return ()
            low = min(range(len(self.run.hand)), key=lambda index: (rank(self.run.hand[index]), suit(self.run.hand[index])))
            high = max(range(len(self.run.hand)), key=lambda index: (rank(self.run.hand[index]), -suit(self.run.hand[index])))
            return () if low == high else (low, high)
        if key == "c_strength":
            ranked = sorted(
                (index for index, card in enumerate(self.run.hand) if rank(card) < NUM_RANKS - 1),
                key=lambda index: (rank(self.run.hand[index]), suit(self.run.hand[index])),
            )
            return tuple(ranked[:TAROT_TARGET_LIMITS[key]])
        if key in TAROT_SUIT_CONVERSIONS:
            target_suit = TAROT_SUIT_CONVERSIONS[key]
            ranked = sorted(
                (index for index, card in enumerate(self.run.hand) if suit(card) != target_suit),
                key=lambda index: (-rank(self.run.hand[index]), suit(self.run.hand[index])),
            )
            return tuple(ranked[:TAROT_TARGET_LIMITS[key]])
        return ()

    def _remove_hand_cards(self, indices: tuple[int, ...]) -> None:
        if not indices:
            return
        removed = [self.run.hand[index] for index in indices]
        self.run.hand = [card for index, card in enumerate(self.run.hand) if index not in set(indices)]
        for card in removed:
            self._remove_deck_card(card)
        self.run.hand = list(_sort_visible_hand(tuple(self.run.hand)))

    def _replace_hand_card(self, index: int, new_card: int) -> None:
        old_card = self.run.hand[index]
        self.run.hand[index] = new_card
        self._replace_deck_card(old_card, new_card)

    def _remove_deck_card(self, card: int) -> None:
        try:
            self.deck_cards.remove(card)
        except ValueError:
            pass

    def _replace_deck_card(self, old_card: int, new_card: int) -> None:
        try:
            self.deck_cards[self.deck_cards.index(old_card)] = new_card
        except ValueError:
            self.deck_cards.append(new_card)

    def _apply_voucher(self, key: str) -> None:
        if key not in self.purchased_vouchers:
            self.purchased_vouchers.append(key)
        self._recompute_run_modifiers()

    def _recompute_run_modifiers(self) -> None:
        modifiers = apply_deck(RunModifiers(), self.deck_key)
        for key in self.purchased_vouchers:
            modifiers = apply_voucher(modifiers, key)
        for joker in self.jokers:
            if joker.key in RUN_EFFECT_JOKERS:
                modifiers = apply_joker_run_effect(modifiers, joker.key)
        money = self.run.money
        _copy_modifiers_to_run(self.run, modifiers)
        self.run.money = money
        if self.consumable_hand_size_delta:
            self.run.hand_size = max(1, min(self.run.hand_size + self.consumable_hand_size_delta, MAX_HAND_OBS))
        self.run.shop.reroll_cost = self.run.base_reroll_cost + self.run.shop.reroll_cost_increase

    def _generate_shop_card(self, rng: Random) -> str:
        joker_weight = 20.0
        planet_weight = max(0.0, self.run.planet_rate)
        tarot_weight = max(0.0, self.run.tarot_rate)
        spectral_weight = max(0.0, self.run.spectral_rate)
        category = _weighted_choice(
            rng,
            (
                ("joker", joker_weight),
                ("planet", planet_weight),
                ("tarot", tarot_weight),
                ("spectral", spectral_weight),
            ),
        )
        if category == "planet":
            return rng.choice(self._available_planet_pool())
        if category == "tarot":
            return rng.choice(_TAROT_KEYS)
        if category == "spectral" and _SPECTRAL_KEYS:
            return rng.choice(_SPECTRAL_KEYS)
        pool = self._available_shop_card_pool()
        return _weighted_joker_choice(rng, pool)

    def _generate_voucher(self, rng: Random) -> str | None:
        candidates = tuple(
            key for key in _VOUCHER_POOL
            if key not in self.purchased_vouchers and _voucher_requirements_met(key, tuple(self.purchased_vouchers))
        )
        if not candidates:
            return None
        return rng.choice(candidates)

    def _item_cost(self, key: str) -> int:
        if key in self.cost_overrides:
            return self.cost_overrides[key]
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
            self._select_boss_for_ante()
        self.run.phase = RunPhase.BLIND_SELECT
        self._sync_required_score()

    def _select_boss_for_ante(self) -> None:
        ante = self.run.ante
        rng = Random(self.seed * 7919 + ante * 104729)
        if ante >= 8:
            pool = [rule.key for rule in BLIND_RULES.values() if rule.showdown]
        else:
            pool = [
                rule.key
                for rule in BLIND_RULES.values()
                if rule.boss and not rule.showdown and (rule.boss_min_ante or 1) <= ante
            ]
        fresh = [key for key in pool if key not in self.used_boss_keys]
        self.boss_key = rng.choice(fresh or pool)
        self.used_boss_keys.append(self.boss_key)
        self.cards_played_this_ante = set()

    def _sync_required_score(self) -> None:
        if self.run.phase == RunPhase.GAME_OVER:
            return
        base = _ante_base_chips(self.run.ante)
        if self.run.blind_kind == BlindKind.BOSS and self.boss_key is not None:
            mult = BLIND_RULES[self.boss_key].score_mult
        else:
            mult = BLIND_MULT[self.run.blind_kind]
        self.run.required_score = int(base * mult * self.run.blind_requirement_multiplier)

    def _boss_rule(self) -> BlindRule | None:
        if self.run.blind_kind != BlindKind.BOSS or self.boss_key is None:
            return None
        return BLIND_RULES[self.boss_key]

    def _play_blocked(self, rule: BlindRule, kind: int, selected_count: int) -> bool:
        policy = rule.hand_policy
        if policy == BlindHandPolicy.MIN_FIVE_CARDS:
            return selected_count < 5
        if policy == BlindHandPolicy.REPEAT_HAND_FORBIDDEN:
            return kind in self.played_hand_kinds_this_round
        if policy == BlindHandPolicy.ONLY_FIRST_HAND_TYPE:
            return self.first_hand_kind_this_round is not None and kind != self.first_hand_kind_this_round
        return False

    def _card_debuffed(self, rule: BlindRule, card: int) -> bool:
        if rule.debuff_all_non_jokers:
            return True
        if rule.debuffed_suit is not None and suit(card) == rule.debuffed_suit:
            return True
        if rule.debuff_faces and rank(card) in {9, 10, 11}:
            return True
        if rule.debuff_played_this_ante and card in self.cards_played_this_ante:
            return True
        return False

    def _boss_adjusted_score(self, rule: BlindRule, score: FastScore, sorted_selected: tuple[int, ...]) -> FastScore:
        chips = score.chips
        mult = score.mult
        if (
            rule.debuffed_suit is not None
            or rule.debuff_faces
            or rule.debuff_played_this_ante
            or rule.debuff_all_non_jokers
        ):
            for index, card in enumerate(sorted_selected):
                if score.scoring_mask & (1 << index) and self._card_debuffed(rule, card):
                    chips -= card_chips(card)
        if rule.halves_base_score:
            level = max(self.hand_levels[score.kind], 1)
            base_part_chips = BASE_CHIPS[score.kind] + (level - 1) * LEVEL_CHIPS[score.kind]
            base_part_mult = BASE_MULT[score.kind] + (level - 1) * LEVEL_MULT[score.kind]
            chips -= base_part_chips - (base_part_chips + 1) // 2
            mult -= base_part_mult - (base_part_mult + 1) // 2
        chips = max(chips, 0)
        mult = max(mult, 0.0)
        return FastScore(
            kind=score.kind,
            chips=chips,
            mult=mult,
            total=int(chips * mult),
            scoring_mask=score.scoring_mask,
        )

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
            if index in self.bought_pack_indices:
                continue
            if self.run.money >= (0 if self.coupon_active else self._item_cost(key)):
                actions.append(BUY_PACK_ACTION_BASE + index)
        for index in range(len(self.jokers)):
            actions.append(SELL_JOKER_ACTION_BASE + index)
        if self.run.money >= self.run.shop.reroll_cost:
            actions.append(REROLL_ACTION)
        actions.append(NEXT_ROUND_ACTION)
        return tuple(actions)

    def _available_shop_card_pool(self) -> tuple[str, ...]:
        # The in-sim pool only offers jokers the simulator can actually score;
        # unimplemented source jokers would be dead purchases in rollouts. The
        # live mirror copies real shop contents, so this filter is sim-only.
        pool = tuple(
            key
            for key in _source_keys("jokers")
            if _source_joker_rarities().get(key, 1) < 4
            and key in IMPLEMENTED_JOKERS
            and key not in PROBABILISTIC_SCORE_JOKERS
        ) or (
            _SHOP_CARD_POOL_BY_ANTE[0] + tuple(key for ante, key in _SHOP_CARD_POOL_BY_ANTE[1] if self.run.ante >= ante)
        )
        owned_jokers = {joker.key for joker in self.jokers}
        filtered = tuple(key for key in pool if not key.startswith("j_") or key not in owned_jokers)
        return filtered or pool

    def _available_joker_pool(self) -> tuple[str, ...]:
        owned_jokers = {joker.key for joker in self.jokers}
        filtered = tuple(key for key in _PACK_JOKER_POOL if key not in owned_jokers)
        return filtered or _PACK_JOKER_POOL

    def _available_planet_pool(self) -> tuple[str, ...]:
        return tuple(
            key for key in _PLANET_KEYS
            if not _is_softlocked_planet(key) or self.hand_play_counts[_PLANET_TO_HAND_KIND[key]] > 0
        ) or ("c_pluto",)

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
        rule = self._boss_rule()
        if rule is not None and rule.key == "bl_serpent":
            draw_count = min(3, MAX_HAND_OBS - len(kept))
        else:
            draw_count = self.round_hand_size - len(kept)
        self.run.hand = list(_sort_visible_hand(tuple(kept + self._draw(max(draw_count, 0)))))
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
    shop_rollout_candidates: int = 0
    shop_rollout_steps: int = 0
    rollout_tactical_search: bool = False
    rollout_build_balance_weight: float = 0.0
    rollout_ranked_future_shop: bool = False

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
                        next_jokers = _jokers_after_discard(jokers, mask.bit_count())
                        candidate_first = first_action if first_action is not None else action
                        next_states.append((candidate_first, next_hand, next_deck, score, hands, discards - 1, next_jokers))

            if not next_states:
                break
            next_states.sort(key=lambda item: (item[3] >= env.run.required_score, item[3], item[4], item[5]), reverse=True)
            states = next_states[: self.beam_width]

        return best_action if best_action is not None else env.greedy_play_action()

    def _shop_action(self, env: FastFullGameEnv) -> int:
        if self.shop_rollout_candidates <= 0 or self.shop_rollout_steps <= 0:
            return self._heuristic_shop_action(env)
        return self._rollout_shop_action(env)

    def _rollout_shop_action(self, env: FastFullGameEnv) -> int:
        legal = set(env.legal_action_ids())
        candidates = [
            action
            for action in self._ranked_shop_candidates(env)
            if action in legal
        ][: self.shop_rollout_candidates]
        if NEXT_ROUND_ACTION in legal and NEXT_ROUND_ACTION not in candidates:
            candidates.append(NEXT_ROUND_ACTION)
        if not candidates:
            return NEXT_ROUND_ACTION

        best: tuple[float, int, int] | None = None
        for action in candidates:
            clone = env.clone()
            try:
                result = clone.step(action)
            except ValueError:
                continue
            score = self._rollout_score(clone, terminated=result.terminated)
            steps = 1
            while not result.terminated and steps < self.shop_rollout_steps:
                try:
                    next_action = self._rollout_policy_action(clone)
                    result = clone.step(next_action)
                except ValueError:
                    break
                score = self._rollout_score(clone, terminated=result.terminated)
                steps += 1
            candidate = (score, -_shop_action_tie_break(action), -action)
            if best is None or candidate > best:
                best = candidate
        if best is None:
            return self._heuristic_shop_action(env)
        return -best[2]

    def _rollout_policy_action(self, env: FastFullGameEnv) -> int:
        if env.run.phase == RunPhase.BLIND_SELECT:
            return SELECT_BLIND_ACTION
        if env.run.phase == RunPhase.ROUND_EVAL:
            return CASH_OUT_ACTION
        if env.run.phase == RunPhase.SHOP:
            if not self.rollout_ranked_future_shop:
                return self._heuristic_shop_action(env)
            ranked = self._ranked_shop_candidates(env)
            return ranked[0] if ranked else NEXT_ROUND_ACTION
        if env.run.phase == RunPhase.PACK:
            return self._pack_action(env)
        if env.run.phase == RunPhase.GAME_OVER:
            raise ValueError("cannot act after game over")
        if self.rollout_tactical_search:
            return SearchRunAgent.act(self, env)
        return env.greedy_play_action()

    def _rollout_score(self, env: FastFullGameEnv, *, terminated: bool) -> float:
        progress = (
            env.rounds_cleared * 10_000.0
            + env.run.ante * 1_000.0
            + int(env.run.blind_kind) * 250.0
        )
        if env.won:
            progress += 1_000_000.0
        elif terminated and env.run.phase == RunPhase.GAME_OVER:
            progress -= 25_000.0
        score_progress = env.run.score / max(env.run.required_score, 1)
        return (
            progress
            + min(score_progress, 1.5) * 300.0
            + env.run.money * 12.0
            + _joker_portfolio_value(env) * 18.0
            + self.rollout_build_balance_weight * _build_balance_value(env)
            + sum(max(level - 1, 0) for level in env.hand_levels) * 40.0
            + len(env.consumables) * 15.0
        )

    def _ranked_shop_candidates(self, env: FastFullGameEnv) -> tuple[int, ...]:
        scored = []
        legal = set(env.legal_action_ids())
        heuristic = self._heuristic_shop_action(env)
        for action in legal:
            value = _shop_candidate_value(env, action)
            if action == heuristic:
                value += 25.0
            scored.append((value, -_shop_action_tie_break(action), -action, action))
        scored.sort(reverse=True)
        return tuple(action for _, _, _, action in scored)

    def _heuristic_shop_action(self, env: FastFullGameEnv) -> int:
        for index, key in enumerate(env.consumables):
            if key.startswith("c_"):
                return USE_CONSUMABLE_ACTION_BASE + index
        if env.available_voucher is not None and BUY_VOUCHER_ACTION in env.legal_action_ids():
            value = _VOUCHER_PURCHASE_VALUES.get(env.available_voucher, 0.0) - env._item_cost(env.available_voucher)
            if value > 0:
                return BUY_VOUCHER_ACTION
        replacement_action = _best_replacement_sell_action(env)
        if replacement_action is not None:
            return replacement_action
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
                value = (
                    20.0 + 4.0 * env.hand_play_counts[target]
                    if target is not None
                    else _tarot_value(env, key)
                ) - env._item_cost(key)
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
                if any(joker.key == key for joker in env.jokers):
                    continue
                value = _JOKER_PURCHASE_VALUES.get(key, 0.0)
            elif key.startswith("c_"):
                target = _PLANET_TO_HAND_KIND.get(key)
                value = 10.0 + env.hand_play_counts[target] if target is not None else _tarot_value(env, key)
            else:
                value = 0.0
            candidate = (value, PACK_SELECT_ACTION_BASE + index)
            if best is None or candidate > best:
                best = candidate
        if best is not None and best[0] > 0:
            return best[1]
        return PACK_SKIP_ACTION


class RolloutSearchRunAgent(SearchRunAgent):
    """Shop rollout oracle used for stronger but slower training labels."""

    beam_width: int = 2
    action_beam: int = 1
    shop_rollout_candidates: int = 6
    shop_rollout_steps: int = 12


def evaluate_agent(
    seeds: range | tuple[int, ...] | list[int],
    *,
    deck_key: str = "b_red",
    max_steps: int = 600,
    agent: SearchRunAgent | None = None,
) -> dict[str, float | int]:
    agent = agent or SearchRunAgent()
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


@lru_cache(maxsize=1)
def _source_catalog() -> RuleCatalog | None:
    try:
        return load_rule_catalog()
    except FileNotFoundError:
        return None


@lru_cache(maxsize=1)
def _source_item_costs() -> dict[str, int]:
    catalog = _source_catalog()
    if catalog is None:
        return {}
    costs: dict[str, int] = {}
    for key, source in catalog.sources.items():
        match = re.search(r"\bcost\s*=\s*([0-9]+)", source.definition.snippet)
        if match:
            costs[key] = int(match.group(1))
    return costs


@lru_cache(maxsize=1)
def _source_joker_rarities() -> dict[str, int]:
    catalog = _source_catalog()
    if catalog is None:
        return {}
    rarities: dict[str, int] = {}
    for key in catalog.jokers:
        source = catalog.sources.get(key)
        if source is None:
            continue
        match = re.search(r"\brarity\s*=\s*([0-9]+)", source.definition.snippet)
        if match:
            rarities[key] = int(match.group(1))
    return rarities


@lru_cache(maxsize=1)
def _source_consumables_by_set() -> dict[str, tuple[str, ...]]:
    catalog = _source_catalog()
    if catalog is None:
        return {}
    out: dict[str, list[str]] = {"Tarot": [], "Planet": [], "Spectral": []}
    for key in catalog.consumables:
        source = catalog.sources.get(key)
        if source is not None and source.set_name in out:
            out[source.set_name].append(key)
    return {set_name: tuple(keys) for set_name, keys in out.items()}


def _source_keys(group: str) -> tuple[str, ...]:
    catalog = _source_catalog()
    if catalog is None:
        return ()
    return tuple(getattr(catalog, group))


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
    "j_half": 18.0,
    "j_even_steven": 16.0,
    "j_odd_todd": 18.0,
    "j_scholar": 18.0,
    "j_greedy_joker": 14.0,
    "j_lusty_joker": 14.0,
    "j_wrathful_joker": 14.0,
    "j_gluttenous_joker": 14.0,
    "j_jolly": 16.0,
    "j_zany": 15.0,
    "j_mad": 15.0,
    "j_crazy": 15.0,
    "j_droll": 17.0,
    "j_sly": 15.0,
    "j_wily": 15.0,
    "j_clever": 15.0,
    "j_devious": 15.0,
    "j_crafty": 17.0,
    "j_duo": 30.0,
    "j_trio": 24.0,
    "j_order": 24.0,
    "j_tribe": 32.0,
    "j_stencil": 24.0,
    "j_banner": 20.0,
    "j_abstract": 24.0,
    "j_supernova": 14.0,
    "j_blue_joker": 18.0,
    "j_bull": 22.0,
    "j_bootstraps": 18.0,
    "j_ice_cream": 22.0,
    "j_square": 20.0,
    "j_wee": 14.0,
    "j_castle": 14.0,
    "j_stone": 14.0,
    "j_ride_the_bus": 18.0,
    "j_green_joker": 22.0,
    "j_mystic_summit": 16.0,
    "j_runner": 14.0,
    "j_trousers": 16.0,
    "j_gros_michel": 18.0,
    "j_cavendish": 40.0,
    "j_acrobat": 22.0,
    "j_family": 18.0,
    "j_stuntman": 36.0,
    "j_popcorn": 18.0,
    "j_constellation": 18.0,
    "j_ramen": 28.0,
    "j_throwback": 12.0,
    "j_swashbuckler": 16.0,
    "j_baseball": 22.0,
    "j_blackboard": 26.0,
    "j_obelisk": 12.0,
    "j_steel_joker": 14.0,
    "j_vampire": 12.0,
    "j_glass": 12.0,
    "j_seeing_double": 22.0,
    "j_fibonacci": 20.0,
    "j_scary_face": 18.0,
    "j_smiley": 18.0,
    "j_walkie_talkie": 16.0,
    "j_photograph": 30.0,
    "j_bloodstone": 22.0,
    "j_triboulet": 30.0,
    "j_arrowhead": 20.0,
    "j_onyx_agate": 18.0,
    "j_baron": 18.0,
    "j_card_sharp": 30.0,
    "j_ceremonial": 14.0,
    "j_flash": 12.0,
    "j_shoot_the_moon": 18.0,
    "j_ancient": 22.0,
    "j_caino": 16.0,
    "j_campfire": 16.0,
    "j_drivers_license": 8.0,
    "j_erosion": 10.0,
    "j_flower_pot": 20.0,
    "j_fortune_teller": 12.0,
    "j_hit_the_road": 10.0,
    "j_hologram": 12.0,
    "j_idol": 12.0,
    "j_loyalty_card": 12.0,
    "j_lucky_cat": 10.0,
    "j_madness": 16.0,
    "j_pareidolia": 12.0,
    "j_raised_fist": 20.0,
    "j_red_card": 10.0,
    "j_yorick": 10.0,
    "j_credit_card": 10.0,
    "j_chaos": 14.0,
    "j_drunkard": 14.0,
    "j_juggler": 16.0,
    "j_oops": 8.0,
    "j_to_the_moon": 16.0,
    "j_astronomer": 22.0,
    "j_troubadour": 10.0,
    "j_merry_andy": 10.0,
    "j_cloud_9": 14.0,
    "j_delayed_grat": 12.0,
    "j_golden": 16.0,
    "j_rocket": 22.0,
    "j_satellite": 12.0,
    "j_business": 10.0,
    "j_faceless": 8.0,
    "j_mail": 10.0,
    "j_matador": 8.0,
    "j_reserved_parking": 8.0,
    "j_rough_gem": 10.0,
    "j_ticket": 8.0,
    "j_todo_list": 12.0,
    "j_trading": 12.0,
}
_PLANET_TO_HAND_KIND = dict(PLANET_HANDS)
_PLANET_KEYS = tuple(_PLANET_TO_HAND_KIND)
_HAND_KIND_TO_PLANET = {hand_kind: key for key, hand_kind in _PLANET_TO_HAND_KIND.items()}
_TAROT_KEYS = _source_consumables_by_set().get(
    "Tarot",
    (
        "c_hermit",
        "c_temperance",
        "c_emperor",
        "c_high_priestess",
        "c_judgement",
        "c_wheel_of_fortune",
    ),
)
_SPECTRAL_KEYS = _source_consumables_by_set().get("Spectral", ())
_PACK_WEIGHTS = tuple(
    (key, spec.weight)
    for key, spec in BOOSTER_SPECS.items()
    if spec.kind in {BoosterKind.BUFFOON, BoosterKind.CELESTIAL, BoosterKind.ARCANA, BoosterKind.SPECTRAL}
)
_PACK_JOKER_POOL = tuple(
    key
    for key in _source_keys("jokers")
    if _source_joker_rarities().get(key, 1) < 4
    and key in IMPLEMENTED_JOKERS
    and key not in PROBABILISTIC_SCORE_JOKERS
) or (
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


def _sample_joker_offers(rng: Random, pool: tuple[str, ...], size: int) -> list[str]:
    available = list(pool)
    out: list[str] = []
    for _ in range(size):
        if not available:
            available = list(pool)
        chosen = _weighted_joker_choice(rng, tuple(available))
        out.append(chosen)
        if chosen in available:
            available.remove(chosen)
    return out


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
    **_source_item_costs(),
    **{purchase.key: purchase.cost for purchase in _GENERAL_JOKER_PURCHASES},
    "j_jolly": 4,
    "j_sly": 4,
    "j_droll": 4,
    "j_crafty": 4,
    **{key: 3 for key in _PLANET_KEYS},
    **{key: 3 for key in _TAROT_KEYS},
    **{key: 4 for key in _SPECTRAL_KEYS},
    **{key: spec.cost for key, spec in BOOSTER_SPECS.items()},
    **_VOUCHER_COSTS,
}
_VOUCHER_POOL = _source_keys("vouchers") or (
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
        elif spec.kind == BoosterKind.ARCANA:
            value = _arcana_pack_purchase_value(env, cost, spec.choices)
        elif spec.kind == BoosterKind.SPECTRAL:
            value = 8.0 + spec.choices * 5.0
        else:
            value = 0.0
        candidate = (value - cost, BUY_PACK_ACTION_BASE + index)
        if best is None or candidate > best:
            best = candidate
    if best is not None and best[0] > 0:
        return best[1]
    return None


def _tarot_value(env: FastFullGameEnv, key: str) -> float:
    if key == "c_hermit":
        return float(min(env.run.money, 20))
    if key == "c_temperance":
        return float(min(sum(joker.sell_value for joker in env.jokers), 50))
    if key == "c_emperor":
        return 18.0 if len(env.consumables) < env.run.consumable_slots else 8.0
    if key == "c_high_priestess":
        return 16.0
    if key == "c_judgement":
        return 24.0 if len(env.jokers) < env.run.joker_slots else 0.0
    if key == "c_wheel_of_fortune":
        return 8.0 if env.jokers else 0.0
    if key == "c_black_hole":
        return 35.0
    if key == "c_immolate":
        return 22.0 if env.run.hand else 8.0
    if key == "c_wraith":
        return 18.0 if len(env.jokers) < env.run.joker_slots else 0.0
    if key == "c_cryptid":
        return 12.0 if env.run.hand else 0.0
    if key in {"c_hanged_man", "c_death", "c_strength", "c_sigil", "c_ouija"}:
        return 12.0 if env.run.hand else 0.0
    if key in TAROT_SUIT_CONVERSIONS:
        return 10.0 if env.run.hand else 0.0
    if key in TAROT_ENHANCEMENTS or key in SPECTRAL_SEALS or key in {"c_aura", "c_ankh", "c_hex", "c_ectoplasm"}:
        return 0.0
    return 0.0


def _arcana_pack_purchase_value(env: FastFullGameEnv, cost: int, choices: int) -> float:
    if cost > 0 and env.run.money - cost < 3:
        return 0.0
    if len(env.jokers) >= env.run.joker_slots and len(env.consumables) >= env.run.consumable_slots:
        return 0.0
    return 10.0 + choices * 5.0


def _shop_candidate_value(env: FastFullGameEnv, action: int) -> float:
    if action == NEXT_ROUND_ACTION:
        return 5.0 + env.run.money * 0.5
    if action == REROLL_ACTION:
        open_slots = max(env.run.joker_slots - len(env.jokers), 0)
        return 10.0 + open_slots * 8.0 - env.run.shop.reroll_cost * 1.5
    if action == BUY_VOUCHER_ACTION and env.available_voucher is not None:
        return _VOUCHER_PURCHASE_VALUES.get(env.available_voucher, 0.0) - env._item_cost(env.available_voucher)
    if BUY_CARD_ACTION_BASE <= action < BUY_CARD_ACTION_BASE + 8:
        index = action - BUY_CARD_ACTION_BASE
        if not 0 <= index < len(env.run.shop.item_keys):
            return -999.0
        key = env.run.shop.item_keys[index]
        cost = env._item_cost(key)
        if key.startswith("j_"):
            return _JOKER_PURCHASE_VALUES.get(key, 0.0) - cost
        target = _PLANET_TO_HAND_KIND.get(key)
        if target is not None:
            return 16.0 + 5.0 * env.hand_play_counts[target] + 4.0 * (env.hand_levels[target] - 1) - cost
        tarot_value = _tarot_value(env, key)
        return tarot_value - cost if tarot_value > 0 else -999.0
    if BUY_PACK_ACTION_BASE <= action < BUY_PACK_ACTION_BASE + 8:
        index = action - BUY_PACK_ACTION_BASE
        pack_keys = env._pack_keys()
        if not 0 <= index < len(pack_keys):
            return -999.0
        key = pack_keys[index]
        try:
            spec = booster_spec(key)
        except NotImplementedError:
            return -999.0
        cost = env._item_cost(key)
        if spec.kind == BoosterKind.BUFFOON:
            return 12.0 + max(env.run.joker_slots - len(env.jokers), 0) * 8.0 + spec.choices * 5.0 - cost
        if spec.kind == BoosterKind.CELESTIAL:
            target = env._planet_target_hand_kind()
            played = 0 if target is None else env.hand_play_counts[target]
            return 10.0 + played * 5.0 + spec.choices * 5.0 - cost
        if spec.kind == BoosterKind.ARCANA:
            value = _arcana_pack_purchase_value(env, cost, spec.choices)
            return value - cost if value > 0 else -999.0
        if spec.kind == BoosterKind.SPECTRAL:
            return 8.0 + spec.choices * 5.0 - cost
        return -999.0
    if SELL_JOKER_ACTION_BASE <= action < SELL_JOKER_ACTION_BASE + 8:
        index = action - SELL_JOKER_ACTION_BASE
        if not 0 <= index < len(env.jokers):
            return -999.0
        return _replacement_sell_value(env, index)
    if USE_CONSUMABLE_ACTION_BASE <= action < USE_CONSUMABLE_ACTION_BASE + 8:
        index = action - USE_CONSUMABLE_ACTION_BASE
        if not 0 <= index < len(env.consumables):
            return -999.0
        key = env.consumables[index]
        target = _PLANET_TO_HAND_KIND.get(key)
        if target is None:
            return _tarot_value(env, key)
        return 18.0 + env.hand_play_counts[target] * 5.0
    return -999.0


def _shop_action_tie_break(action: int) -> int:
    if action == NEXT_ROUND_ACTION:
        return 0
    if USE_CONSUMABLE_ACTION_BASE <= action < USE_CONSUMABLE_ACTION_BASE + 8:
        return 1
    if BUY_CARD_ACTION_BASE <= action < BUY_CARD_ACTION_BASE + 8:
        return 2
    if BUY_PACK_ACTION_BASE <= action < BUY_PACK_ACTION_BASE + 8:
        return 3
    if action == BUY_VOUCHER_ACTION:
        return 4
    if action == REROLL_ACTION:
        return 5
    if SELL_JOKER_ACTION_BASE <= action < SELL_JOKER_ACTION_BASE + 8:
        return 6
    return 7


def _joker_portfolio_value(env: FastFullGameEnv) -> float:
    return sum(_single_joker_value(joker) for joker in env.jokers)


def _build_balance_value(env: FastFullGameEnv) -> float:
    keys = {joker.key for joker in env.jokers}
    chip_sources = {
        "j_blue_joker",
        "j_bull",
        "j_ice_cream",
        "j_square",
        "j_runner",
        "j_stuntman",
        "j_banner",
        "j_odd_todd",
        "j_sly",
        "j_wily",
        "j_clever",
        "j_devious",
        "j_crafty",
        "j_arrowhead",
        "j_castle",
        "j_stone",
        "j_wee",
    }
    mult_sources = {
        "j_joker",
        "j_half",
        "j_abstract",
        "j_mystic_summit",
        "j_green_joker",
        "j_ride_the_bus",
        "j_trousers",
        "j_gros_michel",
        "j_popcorn",
        "j_bootstraps",
        "j_even_steven",
        "j_scholar",
        "j_fibonacci",
        "j_smiley",
        "j_raised_fist",
        "j_jolly",
        "j_zany",
        "j_mad",
        "j_crazy",
        "j_droll",
    }
    xmult_sources = {
        "j_cavendish",
        "j_duo",
        "j_trio",
        "j_order",
        "j_tribe",
        "j_blackboard",
        "j_card_sharp",
        "j_photograph",
        "j_bloodstone",
        "j_ramen",
        "j_acrobat",
        "j_baseball",
        "j_constellation",
        "j_hologram",
        "j_campfire",
        "j_madness",
        "j_seeing_double",
        "j_flower_pot",
        "j_baron",
    }
    economy_sources = {
        "j_rocket",
        "j_golden",
        "j_cloud_9",
        "j_to_the_moon",
        "j_delayed_grat",
        "j_business",
        "j_mail",
        "j_trading",
        "j_satellite",
    }
    scaling_sources = {
        "j_square",
        "j_runner",
        "j_green_joker",
        "j_ride_the_bus",
        "j_trousers",
        "j_constellation",
        "j_hologram",
        "j_campfire",
        "j_flash",
        "j_red_card",
        "j_castle",
        "j_wee",
        "j_lucky_cat",
    }
    has_chips = bool(keys & chip_sources)
    has_mult = bool(keys & mult_sources)
    has_xmult = bool(keys & xmult_sources)
    has_economy = bool(keys & economy_sources) or env.run.money >= 18
    has_scaling = bool(keys & scaling_sources) or any(level > 2 for level in env.hand_levels)
    ante = env.run.ante
    value = 0.0
    value += 180.0 if has_chips else (-120.0 if ante >= 3 else 0.0)
    value += 180.0 if has_mult else (-120.0 if ante >= 2 else 0.0)
    value += 320.0 if has_xmult else (-450.0 if ante >= 4 else 0.0)
    value += 120.0 if has_economy else (-120.0 if ante <= 3 and env.run.money < 6 else 0.0)
    value += 180.0 if has_scaling else (-220.0 if ante >= 3 else 0.0)
    if has_chips and has_mult:
        value += 160.0
    if has_chips and has_mult and has_xmult:
        value += 420.0
    open_slots = max(env.run.joker_slots - len(env.jokers), 0)
    if ante >= 3 and open_slots >= 2:
        value -= 150.0 * open_slots
    return value


def _best_replacement_sell_action(env: FastFullGameEnv) -> int | None:
    if len(env.jokers) < env.run.joker_slots:
        return None
    best: tuple[float, int] | None = None
    for index in range(len(env.jokers)):
        value = _replacement_sell_value(env, index)
        if value <= 0:
            continue
        candidate = (value, SELL_JOKER_ACTION_BASE + index)
        if best is None or candidate > best:
            best = candidate
    return None if best is None else best[1]


def _replacement_sell_value(env: FastFullGameEnv, sell_index: int) -> float:
    if not 0 <= sell_index < len(env.jokers):
        return -999.0
    joker = env.jokers[sell_index]
    sell_value = joker.sell_value
    owned_value = _single_joker_value(joker)
    replacement_values: list[float] = []
    for key in env.run.shop.item_keys:
        if not key.startswith("j_"):
            continue
        if any(other.key == key for own_index, other in enumerate(env.jokers) if own_index != sell_index):
            continue
        cost = env._item_cost(key)
        if env.run.money + sell_value < cost:
            continue
        replacement_values.append(_JOKER_PURCHASE_VALUES.get(key, 0.0) - owned_value - max(cost - sell_value, 0))
    if env.available_voucher is not None and env.run.money + sell_value >= env._item_cost(env.available_voucher):
        replacement_values.append(
            _VOUCHER_PURCHASE_VALUES.get(env.available_voucher, 0.0)
            - max(env._item_cost(env.available_voucher) - sell_value, 0)
            - owned_value * 0.4
        )
    if not replacement_values:
        return -999.0
    return max(replacement_values)


def _single_joker_value(joker: Joker) -> float:
    if joker.key not in IMPLEMENTED_JOKERS:
        # Mirrored unmodeled jokers score nothing in-sim; only their sell
        # value is real, so packs/replacements should not prize them.
        return float(joker.sell_value)
    base = _JOKER_PURCHASE_VALUES.get(joker.key, 8.0)
    if joker.key == "j_cavendish":
        base += 20.0
    if joker.key in {"j_square", "j_runner"}:
        base += joker.scaling / 8.0
    if joker.key in {"j_ride_the_bus", "j_green_joker", "j_trousers"}:
        base += joker.scaling * 1.5
    return base


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


def _clone_run_state(run: FastRunState) -> FastRunState:
    new = object.__new__(FastRunState)
    for spec in dataclass_fields(run):
        value = getattr(run, spec.name)
        if spec.name == "shop":
            value = ShopState(
                reroll_cost=value.reroll_cost,
                reroll_cost_increase=value.reroll_cost_increase,
                free_rerolls=value.free_rerolls,
                item_keys=list(value.item_keys),
            )
        elif isinstance(value, list):
            value = list(value)
        setattr(new, spec.name, value)
    return new


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


def _weighted_joker_choice(rng: Random, pool: tuple[str, ...]) -> str:
    rarity_weights = {1: 70.0, 2: 25.0, 3: 5.0}
    rarities = _source_joker_rarities()
    weighted = tuple((key, rarity_weights.get(rarities.get(key, 1), 0.0)) for key in pool)
    if any(weight > 0 for _, weight in weighted):
        return _weighted_choice(rng, weighted)
    return rng.choice(pool)


_VOUCHER_REQUIREMENTS = {
    "v_overstock_plus": ("v_overstock_norm",),
    "v_liquidation": ("v_clearance_sale",),
    "v_glow_up": ("v_hone",),
    "v_reroll_glut": ("v_reroll_surplus",),
    "v_omen_globe": ("v_crystal_ball",),
    "v_observatory": ("v_telescope",),
    "v_nacho_tong": ("v_grabber",),
    "v_recyclomancy": ("v_wasteful",),
    "v_tarot_tycoon": ("v_tarot_merchant",),
    "v_planet_tycoon": ("v_planet_merchant",),
    "v_money_tree": ("v_seed_money",),
    "v_antimatter": ("v_blank",),
    "v_illusion": ("v_magic_trick",),
    "v_petroglyph": ("v_hieroglyph",),
    "v_retcon": ("v_directors_cut",),
    "v_palette": ("v_paint_brush",),
}


def _voucher_requirements_met(key: str, purchased_vouchers: tuple[str, ...]) -> bool:
    required = _VOUCHER_REQUIREMENTS.get(key, ())
    return all(voucher in purchased_vouchers for voucher in required)


def _is_softlocked_planet(key: str) -> bool:
    return key in {"c_planet_x", "c_ceres", "c_eris"}


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
    boss_rule = env._boss_rule()
    if boss_rule is not None:
        # Blocking inside the beam uses the env's current round state; in-beam
        # first-hand locking (The Mouth) is tracked by the planner tactics.
        if env._play_blocked(boss_rule, base.kind, len(selected)):
            return FastScore(kind=base.kind, chips=0, mult=0.0, total=0, scoring_mask=base.scoring_mask)
        base = env._boss_adjusted_score(boss_rule, base, sorted_cards)
    context = ScoreContext(
        held_cards=tuple(card for index, card in enumerate(hand) if not mask & (1 << index)),
        money=env.run.money,
        discards_left=discards_left,
        hands_left=hands_left,
        deck_count=deck_count,
        joker_slots=env.run.joker_slots,
        is_final_hand=hands_left <= 0,
        blinds_skipped=env.blinds_skipped,
    )
    return apply_additive_jokers(base, sorted_cards, len(selected), jokers, context)


def _jokers_after_play(jokers: tuple[Joker, ...], score: FastScore, selected: tuple[int, ...]) -> tuple[Joker, ...]:
    from balatro_ai_v2.fast.hand import FULL_HOUSE, STRAIGHT, TWO_PAIR
    out: list[Joker] = []
    selected_count = len(selected)
    sorted_selected = tuple(sorted(selected))
    has_scored_face = any(
        score.scoring_mask & (1 << index) and rank(card) in {9, 10, 11}
        for index, card in enumerate(sorted_selected)
    )
    scored_two_count = sum(
        1
        for index, card in enumerate(sorted_selected)
        if score.scoring_mask & (1 << index) and rank(card) == 0
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
        elif joker.key == "j_ride_the_bus":
            out.append(_replace_joker(joker, scaling=0 if has_scored_face else joker.scaling + 1))
        elif joker.key == "j_wee" and scored_two_count:
            out.append(_replace_joker(joker, scaling=joker.scaling + 8 * scored_two_count))
        elif joker.key == "j_ice_cream":
            if joker.scaling > 5:
                out.append(_replace_joker(joker, scaling=joker.scaling - 5))
        else:
            out.append(joker)
    return tuple(out)


def _jokers_after_discard(jokers: tuple[Joker, ...], discarded_count: int = 0) -> tuple[Joker, ...]:
    out: list[Joker] = []
    for joker in jokers:
        if joker.key == "j_green_joker":
            out.append(_replace_joker(joker, scaling=max(joker.scaling - 1, 0)))
        elif joker.key == "j_ramen" and discarded_count:
            next_x_mult = round(joker.x_mult - 0.01 * discarded_count, 2)
            if next_x_mult > 1.0:
                out.append(_replace_joker(joker, x_mult=next_x_mult))
        else:
            out.append(joker)
    return tuple(out)


def _jokers_after_round(jokers: list[Joker]) -> list[Joker]:
    out: list[Joker] = []
    for joker in jokers:
        if joker.key == "j_popcorn":
            if joker.scaling > 4:
                out.append(_replace_joker(joker, scaling=joker.scaling - 4))
        else:
            out.append(joker)
    return out


def _replace_joker(joker: Joker, *, scaling: int | None = None, x_mult: float | None = None) -> Joker:
    return Joker(
        key=joker.key,
        scaling=joker.scaling if scaling is None else scaling,
        x_mult=joker.x_mult if x_mult is None else x_mult,
        sell_value=joker.sell_value,
        edition=joker.edition,
    )


def _selected_cards(hand: tuple[int, ...], mask: int) -> tuple[int, ...]:
    return tuple(card for index, card in enumerate(hand) if mask & (1 << index))


def _make_joker(key: str) -> Joker:
    if key == "j_cavendish":
        return Joker(key=key, x_mult=3.0, sell_value=2)
    if key == "j_rocket":
        return Joker(key=key, scaling=1, sell_value=2)
    if key == "j_ice_cream":
        return Joker(key=key, scaling=100, sell_value=2)
    if key == "j_popcorn":
        return Joker(key=key, scaling=20, sell_value=2)
    if key == "j_ramen":
        return Joker(key=key, x_mult=2.0, sell_value=2)
    if key in {
        "j_constellation",
        "j_caino",
        "j_campfire",
        "j_hit_the_road",
        "j_hologram",
        "j_lucky_cat",
        "j_madness",
        "j_yorick",
        "j_obelisk",
        "j_steel_joker",
        "j_vampire",
        "j_glass",
    }:
        return Joker(key=key, x_mult=1.0, sell_value=2)
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
