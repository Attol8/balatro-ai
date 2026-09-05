"""Small public-information baselines for coverage and later comparison.

These policies are deliberately not learning agents.  They exist to drive
organic public actions through both kernels and expose the first divergence.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import combinations, islice
from typing import Literal

from balatro_ai_v2.actions import (
    BuyPack,
    BuyShopCard,
    BuyVoucher,
    CashOut,
    ChoosePackCard,
    ConsumableSlot,
    DiscardCards,
    HandSlot,
    JokerSlot,
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
)
from balatro_ai_v2.belief import PublicDrawBelief
from balatro_ai_v2.boss_rules import BossRule, FaceDownMode, boss_rule
from balatro_ai_v2.build_strategy import BuildPlan, infer_build_plan, planet_hand
from balatro_ai_v2.joker_catalog import get_joker_profile
from balatro_ai_v2.policy import (
    ActionSource,
    NoPublicProgressAction,
    PublicHistoryStep,
    PublicPolicy,
)
from balatro_ai_v2.public_state import (
    HandStat,
    HiddenHandCard,
    HiddenJokerSlot,
    Phase,
    PublicItem,
    PublicJokerRuntime,
    PublicObservation,
    VisiblePlayingCard,
)
from balatro_ai_v2.public_scoring import (
    _PreparedScoreContext,
    _COPY_HELD_INDIVIDUAL_JOKERS,
    _COPY_HELD_RETRIGGER_JOKERS,
    _COPY_JOKERS,
    _COPY_MAIN_JOKERS,
    _COPY_PLAYED_INDIVIDUAL_JOKERS,
    _COPY_PLAYED_RETRIGGER_JOKERS,
    _RANK_ORDER,
    _SUIT_MULT_JOKERS,
    _TYPE_CHIP_JOKERS,
    _TYPE_MULT_JOKERS,
    _TYPE_XMULT_JOKERS,
    _card_chips,
    _classify,
    _current_boss_rule,
    _effective_joker_for_pass,
    _hand_matches,
    _prepare_score_context,
    _score_play_prepared,
)
from balatro_ai_v2.strategy_tuning import StrategyTuning
from balatro_ai_v2.strategy_engine import RunRoute
from balatro_ai_v2.strategy_options import (
    StrategyIntent,
    options_for_intent,
    options_for_route,
)


_REORDER_TYPES = (ReorderHand, ReorderJokers, ReorderConsumables)
_MAX_PUBLIC_ACTIONS = 256
_MAX_PUBLIC_DRAW_BRANCHES = 512
PUBLIC_BASELINE_NAMES = (
    "random",
    "greedy",
    "tactical",
    "strategic",
    "preboss_search",
    "red_gold_search",
)

_HANDS_CONTAINING_FAMILY = {
    "Pair": frozenset(
        {
            "Pair",
            "Two Pair",
            "Three of a Kind",
            "Full House",
            "Four of a Kind",
            "Five of a Kind",
            "Flush House",
            "Flush Five",
        }
    ),
    "Three of a Kind": frozenset(
        {
            "Three of a Kind",
            "Full House",
            "Four of a Kind",
            "Five of a Kind",
            "Flush House",
            "Flush Five",
        }
    ),
    "Four of a Kind": frozenset({"Four of a Kind", "Five of a Kind", "Flush Five"}),
    "Straight": frozenset({"Straight", "Straight Flush"}),
    "Flush": frozenset({"Flush", "Straight Flush", "Flush House", "Flush Five"}),
}
_HAND_BUILD_ARCHETYPES = frozenset(
    {
        "high_card",
        "pair",
        "two_pair",
        "three_of_a_kind",
        "four_of_a_kind",
        "straight",
        "flush",
        "full_house",
        "straight_flush",
    }
)
_UNCONDITIONAL_XMULT_JOKERS = frozenset({"j_cavendish", "j_ramen"})
_COPY_SCORING_JOKERS = frozenset(
    _COPY_MAIN_JOKERS
    | _COPY_PLAYED_INDIVIDUAL_JOKERS
    | _COPY_PLAYED_RETRIGGER_JOKERS
    | _COPY_HELD_INDIVIDUAL_JOKERS
    | _COPY_HELD_RETRIGGER_JOKERS
)
_STATIC_PHASE1_JOKERS = frozenset(
    {
        "j_abstract",
        "j_acrobat",
        "j_ancient",
        "j_arrowhead",
        "j_banner",
        "j_baron",
        "j_baseball",
        "j_blackboard",
        "j_bloodstone",
        "j_blue_joker",
        "j_blueprint",
        "j_bootstraps",
        "j_brainstorm",
        "j_bull",
        "j_card_sharp",
        "j_cavendish",
        "j_dusk",
        "j_erosion",
        "j_even_steven",
        "j_fibonacci",
        "j_flash",
        "j_flower_pot",
        "j_four_fingers",
        "j_gros_michel",
        "j_green_joker",
        "j_hack",
        "j_half",
        "j_hanging_chad",
        "j_hiker",
        "j_joker",
        "j_mime",
        "j_misprint",
        "j_mystic_summit",
        "j_odd_todd",
        "j_onyx_agate",
        "j_pareidolia",
        "j_photograph",
        "j_raised_fist",
        "j_ramen",
        "j_red_card",
        "j_ride_the_bus",
        "j_runner",
        "j_scholar",
        "j_scary_face",
        "j_seeing_double",
        "j_shortcut",
        "j_shoot_the_moon",
        "j_sly",
        "j_smeared",
        "j_smiley",
        "j_sock_and_buskin",
        "j_splash",
        "j_square",
        "j_stencil",
        "j_stuntman",
        "j_supernova",
        "j_swashbuckler",
        "j_triboulet",
        "j_trousers",
        "j_walkie_talkie",
        "j_wee",
    }
    | frozenset(_TYPE_MULT_JOKERS)
    | frozenset(_TYPE_CHIP_JOKERS)
    | frozenset(_TYPE_XMULT_JOKERS)
    | frozenset(_SUIT_MULT_JOKERS)
)
_PHASE1_CONTEXT_JOKER_VALUES = {
    "j_burglar": 60,
    "j_chaos": 55,
    "j_drunkard": 55,
    "j_golden": 55,
    "j_juggler": 55,
    "j_merry_andy": 50,
    "j_rough_gem": 45,
    "j_troubadour": 45,
}

_JOKER_ROLE_VALUES = {
    "x_mult": 85,
    "scaling": 70,
    "retrigger": 65,
    "flat_mult": 55,
    "chips": 55,
    "economy": 35,
    "utility": 20,
}
_VOUCHER_VALUES = {
    "v_overstock_norm": 85,
    "v_overstock_plus": 90,
    "v_reroll_surplus": 80,
    "v_reroll_glut": 82,
    "v_clearance_sale": 78,
    "v_liquidation": 82,
    "v_telescope": 85,
    "v_observatory": 90,
    "v_hieroglyph": 88,
    "v_petroglyph": 90,
    "v_grabber": 80,
    "v_nacho_tong": 85,
    "v_wasteful": 55,
    "v_recyclomancy": 60,
    "v_crystal_ball": 62,
    # These voucher effects feed action families the current public policy does
    # not use. Keep them at zero until Arcana purchases or boss rerolls exist.
    "v_omen_globe": 0,
    "v_tarot_merchant": 0,
    "v_tarot_tycoon": 0,
    "v_planet_merchant": 65,
    "v_planet_tycoon": 72,
    "v_seed_money": 72,
    "v_money_tree": 78,
    "v_hone": 55,
    "v_glow_up": 62,
    "v_magic_trick": 30,
    "v_illusion": 45,
    "v_directors_cut": 50,
    "v_retcon": 0,
    "v_paint_brush": 40,
    "v_palette": 48,
    "v_blank": 0,
    "v_antimatter": 100,
}
_UNTARGETED_CONSUMABLE_VALUES = {
    "c_black_hole": 120,
    "c_soul": 115,
    "c_immolate": 105,
    "c_hermit": 95,
    "c_temperance": 90,
    "c_high_priestess": 80,
    "c_emperor": 78,
    "c_fool": 75,
    "c_judgement": 72,
    "c_wheel_of_fortune": 65,
    "c_familiar": 58,
    "c_grim": 58,
    "c_incantation": 55,
    "c_sigil": 55,
    "c_ouija": 50,
    "c_ectoplasm": 45,
    "c_hex": 40,
    "c_wraith": 35,
}
_TARGETED_CONSUMABLE_VALUES = {
    "c_hanged_man": 85,
    "c_death": 82,
    "c_empress": 72,
    "c_heirophant": 72,
    "c_strength": 65,
    "c_chariot": 62,
    "c_justice": 60,
    "c_devil": 58,
    "c_magician": 56,
    "c_lovers": 54,
    "c_star": 52,
    "c_moon": 52,
    "c_sun": 52,
    "c_world": 52,
    "c_tower": 35,
    "c_talisman": 64,
    "c_aura": 70,
    "c_deja_vu": 64,
    "c_trance": 60,
    "c_medium": 60,
    "c_cryptid": 75,
}
_REPLACEMENT_MARGIN = 20


def build_public_baseline(
    name: str,
    policy_seed: str,
    tuning: StrategyTuning = StrategyTuning(),
) -> tuple[PublicPolicy, str]:
    if name == "random":
        return DeterministicRandomPolicy(
            policy_seed
        ), f"DeterministicRandomPolicy:{policy_seed}"
    if name == "greedy":
        return GreedyImmediatePolicy(), "GreedyImmediatePolicy"
    if name == "tactical":
        return PublicBeliefTacticalPolicy(), "PublicBeliefTacticalPolicy"
    if name == "strategic":
        return PublicStrategicPolicy(tuning=tuning), "PublicStrategicPolicy"
    if name == "preboss_search":
        from balatro_ai_v2.preboss_search import PublicPreBossSearchPolicy

        return (
            PublicPreBossSearchPolicy(
                search_nonce=policy_seed,
                baseline=PublicStrategicPolicy(tuning=tuning),
            ),
            f"PublicPreBossSearchPolicy:{policy_seed}",
        )
    if name == "red_gold_search":
        from balatro_ai_v2.solver_policy import PublicRedGoldSearchPolicy

        return (
            PublicRedGoldSearchPolicy(search_nonce=policy_seed, tuning=tuning),
            f"PublicRedGoldSearchPolicy:{policy_seed}",
        )
    raise ValueError(f"unknown public baseline {name!r}")


@dataclass(frozen=True, slots=True)
class DeterministicRandomPolicy:
    """Bounded random legal-action control using public state only."""

    policy_seed: str = "random-v1"

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        actions = _bounded_actions(legal_actions())
        if not actions:
            raise RuntimeError(
                f"no bounded public action for {observation.phase.value}"
            )
        payload = f"{self.policy_seed}\0{len(history)}\0{observation.digest()}"
        number = int.from_bytes(
            hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big"
        )
        return actions[number % len(actions)]


@dataclass(frozen=True, slots=True)
class GreedyImmediatePolicy:
    """Immediate visible-score baseline with no strategic shop model."""

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        del history
        if observation.phase == Phase.SELECTING_HAND:
            return _best_play(observation, 0)[0]
        return _passive_control_action(observation, legal_actions)


@dataclass(frozen=True, slots=True)
class PublicBeliefTacticalPolicy:
    """One-ply public expectimax over a bounded visible-score surrogate."""

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        del history
        if observation.phase == Phase.SELECTING_HAND:
            return _belief_tactical_action(observation)
        return _passive_control_action(observation, legal_actions)


@dataclass(frozen=True, slots=True)
class PublicStrategicPolicy:
    """Bounded strategic baseline using only explicit public state."""

    max_shop_actions: int = 6
    tuning: StrategyTuning = StrategyTuning()

    def fork_for_rollout(
        self,
        intent: StrategyIntent | None = None,
        route: RunRoute | None = None,
    ) -> PublicStrategicPolicy:
        """Return a distinct stateless continuation for one rollout root."""

        del intent, route
        return replace(self)

    def choose_action_for_strategy(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
        intent: StrategyIntent | None,
        route: RunRoute,
    ) -> PublicAction:
        """Choose within actions that still express a public route and intent."""

        supplied = tuple(legal_actions())
        supplied_set = set(supplied)
        intended = tuple(
            dict.fromkeys(
                option.first_action
                for option in options_for_route(observation, route)
                if (intent is None or option.intent == intent)
                and option.first_action in supplied_set
            )
        )
        if not intended:
            if intent is not None:
                return self.choose_action_for_intent(
                    observation, lambda: iter(supplied), history, intent
                )
            return self.choose_action(observation, lambda: iter(supplied), history)
        try:
            selected = self.choose_action(observation, lambda: iter(intended), history)
        except Exception:
            return self.choose_action(observation, lambda: iter(supplied), history)
        return selected if selected in intended else intended[0]

    def choose_action_for_intent(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
        intent: StrategyIntent,
    ) -> PublicAction:
        """Revalidate an intent and choose within its current public actions."""

        supplied = tuple(legal_actions())
        supplied_set = set(supplied)
        intended = tuple(
            dict.fromkeys(
                option.first_action
                for option in options_for_intent(observation, intent)
                if option.first_action in supplied_set
            )
        )
        if not intended:
            return self.choose_action(observation, lambda: iter(supplied), history)
        try:
            selected = self.choose_action(observation, lambda: iter(intended), history)
        except Exception:
            # Existing phase heuristics may require a progress action that an
            # intent-specific subset intentionally omits. Fall back to the
            # ordinary public continuation rather than inventing a preference.
            return self.choose_action(observation, lambda: iter(supplied), history)
        # Some phases have a mandatory progress rule that does not consult the
        # supplied action source. In that case retain the declared intent with
        # the first canonical, revalidated action rather than returning an
        # action outside the intent-filtered set.
        return selected if selected in intended else intended[0]

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        observation = _with_history_derived_joker_runtime(observation, history)
        build = infer_build_plan(observation)
        if observation.phase == Phase.BLIND_SELECT:
            selected_blind = next(
                (blind for blind in observation.blinds if blind.status == "SELECT"),
                None,
            )
            if selected_blind is None:
                raise RuntimeError("blind selection has no selected public blind")
            if (
                selected_blind.kind == "SMALL"
                and selected_blind.tag_name == "Economy Tag"
                and observation.money >= 20
            ):
                return SkipBlind()
            return SelectBlind()
        if observation.phase == Phase.SELECTING_HAND:
            current_boss = _current_boss_rule(observation)
            all_actions = list(legal_actions())
            if current_boss is not None:
                boss_sale = _boss_disable_sale(
                    observation,
                    all_actions,
                    current_boss,
                    build,
                )
                if boss_sale is not None:
                    return boss_sale
            consumable = _strategic_consumable_action(observation, all_actions, build)
            if consumable is not None:
                return consumable
            actions = [
                action
                for action in all_actions
                if isinstance(action, (PlayCards, DiscardCards))
                and is_legal(observation, action)
            ]
            if not any(isinstance(action, PlayCards) for action in actions):
                discard = next(
                    (action for action in actions if isinstance(action, DiscardCards)),
                    None,
                )
                if discard is not None:
                    return discard
                raise NoPublicProgressAction(
                    "selecting-hand state has no public play or discard action"
                )
            if current_boss is not None and not _boss_eligible_plays(
                observation,
                actions,
                current_boss,
            ):
                recovery = _boss_recovery_discard(observation, actions, current_boss)
                if recovery is not None:
                    return recovery
                # Mouth/Eye can leave no admissible scoring family after all
                # discards are spent. The public action contract still
                # permits a play; emit the best one so the blind can resolve
                # the blocked hand instead of crashing the policy process.
                return _best_available_play(observation, actions)[0]
            best, hand_name = _best_available_play(observation, actions, current_boss)
            stats = {hand.name: hand for hand in observation.hand_stats}
            best_score, _ = _play_score(observation, best.cards, stats)
            current_blind = next(
                (blind for blind in observation.blinds if blind.status == "CURRENT"),
                None,
            )
            clears = (
                current_blind is not None
                and observation.round.chips + best_score >= current_blind.score
            )
            if clears:
                todo_play = _todo_list_clear_play(
                    observation,
                    actions,
                    current_boss,
                    current_blind.score if current_blind is not None else 0,
                )
                if todo_play is not None:
                    return todo_play
                return best
            if current_boss is not None:
                hidden_discard = _boss_hidden_discard(
                    observation,
                    actions,
                    current_boss,
                )
                if hidden_discard is not None:
                    return hidden_discard
                if (
                    current_boss.repeat_hand_restriction
                    and current_blind is not None
                    and observation.round.hands_left > 0
                    and best_score
                    >= Fraction(
                        current_blind.score - observation.round.chips,
                        observation.round.hands_left,
                    )
                ):
                    return best
            build_play = _build_pace_play(
                observation,
                actions,
                current_boss,
                build,
                current_blind.score if current_blind is not None else 0,
            )
            if build_play is not None:
                return build_play
            joker_reorder = _score_improving_joker_reorder(
                observation,
                all_actions,
                best,
                best_score,
            )
            if joker_reorder is not None:
                return joker_reorder
            discard = _coverage_discard(
                observation,
                best,
                hand_name,
                fish_strong_hand=observation.round.hands_left == 1,
                target_hand=build.primary_hand,
                draw_count_override=(
                    current_boss.draw_count_override
                    if current_boss is not None
                    else None
                ),
            )
            return discard if discard in actions else best
        if observation.phase == Phase.ROUND_EVAL:
            return CashOut()
        actions = _bounded_actions(legal_actions())
        if observation.phase == Phase.SHOP:
            consumable = _strategic_consumable_action(observation, actions, build)
            if consumable is not None:
                return consumable
            return _strategic_shop_action(
                observation,
                actions,
                history,
                self.max_shop_actions,
                build,
                self.tuning,
            )
        if observation.phase == Phase.PACK:
            return _strategic_pack_action(observation, actions, build)
        raise RuntimeError(f"no strategic action for {observation.phase.value}")


def _with_history_derived_joker_runtime(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
) -> PublicObservation:
    """Replace stale Loyalty Card state with a public-history countdown."""

    loyalty_indexes = [
        index
        for index, joker in enumerate(observation.jokers)
        if isinstance(joker, PublicItem) and joker.key == "j_loyalty_card"
    ]
    if not loyalty_indexes:
        return observation
    remaining = _loyalty_remaining_from_history(observation, history)
    jokers = list(observation.jokers)
    for index in loyalty_indexes:
        joker = jokers[index]
        runtime = joker.runtime
        if remaining is None:
            if runtime is not None and runtime.loyalty_remaining is not None:
                jokers[index] = replace(
                    joker,
                    runtime=replace(runtime, loyalty_remaining=None),
                )
            continue
        jokers[index] = replace(
            joker,
            runtime=(
                PublicJokerRuntime(loyalty_remaining=remaining)
                if runtime is None
                else replace(runtime, loyalty_remaining=remaining)
            ),
        )
    return replace(observation, jokers=tuple(jokers))


def _loyalty_remaining_from_history(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
) -> int | None:
    """Derive whether the next public play is Loyalty Card's sixth hand."""

    if any(isinstance(joker, HiddenJokerSlot) for joker in observation.jokers):
        return None
    if any(
        isinstance(joker, HiddenJokerSlot)
        for step in history
        for seen in (step.before, step.after)
        for joker in seen.jokers
    ):
        return None
    if sum(
        joker.key == "j_loyalty_card"
        for joker in observation.jokers
        if isinstance(joker, PublicItem)
    ) != 1:
        return None
    if not history or history[-1].after != observation:
        return None
    if any(
        previous.after != following.before
        for previous, following in zip(history, history[1:], strict=False)
    ):
        return None

    for index in range(len(history) - 1, -1, -1):
        step = history[index]
        before_count = sum(
            joker.key == "j_loyalty_card"
            for joker in step.before.jokers
            if isinstance(joker, PublicItem)
        )
        after_count = sum(
            joker.key == "j_loyalty_card"
            for joker in step.after.jokers
            if isinstance(joker, PublicItem)
        )
        if after_count != 1:
            return None
        if before_count == 0:
            if isinstance(step.action, PlayCards):
                return None
            plays_since_creation = sum(
                isinstance(later.action, PlayCards) for later in history[index + 1 :]
            )
            return (5 - plays_since_creation) % 6
        if before_count != 1:
            return None
    return None


def _without_loyalty_remaining(observation: PublicObservation) -> PublicObservation:
    """Normalize only the history-derived Loyalty field for equality checks."""

    jokers = tuple(
        replace(
            joker,
            runtime=replace(joker.runtime, loyalty_remaining=None),
        )
        if isinstance(joker, PublicItem)
        and joker.key == "j_loyalty_card"
        and joker.runtime is not None
        and joker.runtime.loyalty_remaining is not None
        else joker
        for joker in observation.jokers
    )
    return replace(observation, jokers=jokers)


@dataclass(frozen=True, slots=True)
class DeterministicCoveragePolicy:
    """Exercise public action families without consulting privileged state."""

    policy_seed: str = "coverage-v1"
    max_shop_actions: int = 3
    pack_strategy: Literal["mixed", "skip", "pick"] = "mixed"
    coverage_mode: Literal["default", "extended"] = "default"

    def __post_init__(self) -> None:
        if self.max_shop_actions < 0:
            raise ValueError("max_shop_actions must be non-negative")
        if self.coverage_mode not in {"default", "extended"}:
            raise ValueError(f"unsupported coverage mode {self.coverage_mode!r}")

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        if observation.phase == Phase.BLIND_SELECT:
            actions = _bounded_actions(legal_actions())
            skips = [action for action in actions if isinstance(action, SkipBlind)]
            if skips and self._number(observation, history, "blind") % 5 == 0:
                return skips[0]
            return next(action for action in actions if isinstance(action, SelectBlind))

        if observation.phase == Phase.SELECTING_HAND:
            planet = _held_planet_action(observation)
            if self.coverage_mode == "extended" and planet is not None:
                return planet
            best, hand_name = _best_play(
                observation, self._number(observation, history, "tactical")
            )
            discard = _coverage_discard(observation, best, hand_name)
            if discard is not None:
                return discard
            return best

        if observation.phase == Phase.ROUND_EVAL:
            return CashOut()

        if observation.phase == Phase.SHOP:
            actions = _bounded_actions(legal_actions())
            shop_steps = _current_shop_action_count(history)
            if shop_steps >= self.max_shop_actions:
                return next(
                    action for action in actions if isinstance(action, LeaveShop)
                )
            rerolls = [action for action in actions if isinstance(action, RerollShop)]
            if self.coverage_mode == "extended" and rerolls and shop_steps == 0:
                return rerolls[0]
            planet = _held_planet_action(observation)
            if self.coverage_mode == "extended" and planet is not None:
                return planet
            pack_purchases = [
                action for action in actions if isinstance(action, BuyPack)
            ]
            if pack_purchases and self.pack_strategy != "mixed" and shop_steps == 0:
                return self._pick(pack_purchases, observation, history, "pack-buy")
            purchases = [
                action
                for action in actions
                if isinstance(action, (BuyShopCard, BuyPack, BuyVoucher))
            ]
            if purchases and (
                shop_steps == 0 or self._number(observation, history, "buy") % 3
            ):
                return self._pick(purchases, observation, history, "buy-choice")
            if rerolls and shop_steps == 0:
                return rerolls[0]
            return next(action for action in actions if isinstance(action, LeaveShop))

        if observation.phase == Phase.PACK:
            actions = _bounded_actions(legal_actions())
            if self.pack_strategy == "skip":
                return next(
                    action for action in actions if isinstance(action, SkipPack)
                )
            choices = [
                action for action in actions if isinstance(action, ChoosePackCard)
            ]
            if choices and (
                self.pack_strategy == "pick"
                or self._number(observation, history, "pack") % 4
            ):
                return self._pick(choices, observation, history, "pack-choice")
            return next(action for action in actions if isinstance(action, SkipPack))

        raise RuntimeError(f"no coverage action for {observation.phase.value}")

    def _pick(
        self,
        actions: list[PublicAction],
        observation: PublicObservation,
        history: tuple[PublicHistoryStep, ...],
        label: str,
    ) -> PublicAction:
        ordered = sorted(
            actions,
            key=lambda action: json.dumps(action_to_data(action), sort_keys=True),
        )
        return ordered[self._number(observation, history, label) % len(ordered)]

    def _number(
        self,
        observation: PublicObservation,
        history: tuple[PublicHistoryStep, ...],
        label: str,
    ) -> int:
        payload = f"{self.policy_seed}\0{label}\0{len(history)}\0{observation.digest()}"
        return int.from_bytes(
            hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big"
        )


def _best_play(observation: PublicObservation, tie_seed: int) -> tuple[PlayCards, str]:
    action, hand_name, _ = _best_play_with_score(observation, tie_seed)
    return action, hand_name


def _best_play_with_score(
    observation: PublicObservation,
    tie_seed: int,
    hand_stats: Mapping[str, HandStat] | None = None,
) -> tuple[PlayCards, str, int | Fraction]:
    slots = tuple(HandSlot(index) for index in range(len(observation.hand)))
    maximum = min(5, observation.selection_limit, len(slots))
    candidate_slots = (
        selected
        for size in range(maximum, 0, -1)
        for selected in combinations(slots, size)
        if set(observation.required_hand_slots).issubset(
            slot.value for slot in selected
        )
    )
    stats = (
        hand_stats
        if hand_stats is not None
        else {hand.name: hand for hand in observation.hand_stats}
    )
    best: tuple[int | Fraction, int, tuple[HandSlot, ...], str] | None = None
    for selected in candidate_slots:
        score, hand_name = _play_score(observation, selected, stats)
        tie = (
            tie_seed ^ sum((slot.value + 1) * 0x9E3779B1 for slot in selected)
        ) & 0xFFFFFFFF
        candidate = (score, tie, selected, hand_name)
        if best is None or (candidate[0], candidate[1]) > (best[0], best[1]):
            best = candidate
    if best is None:
        raise RuntimeError("selecting-hand state has no legal cards")
    score, _, selected, hand_name = best
    return PlayCards(selected), hand_name, score


def _best_available_play(
    observation: PublicObservation,
    actions: list[PublicAction],
    current_boss: BossRule | None = None,
) -> tuple[PlayCards, str]:
    stats = {hand.name: hand for hand in observation.hand_stats}
    plays = _boss_eligible_plays(observation, actions, current_boss)
    if not plays:
        boss_name = current_boss.name if current_boss is not None else "ordinary blind"
        raise RuntimeError(
            f"strategic proposal contains no playable hand for {boss_name}"
        )
    scored = [
        (*_play_score(observation, action.cards, stats), action) for action in plays
    ]
    _, hand_name, best = max(
        scored,
        key=lambda row: (row[0], tuple(-slot.value for slot in row[2].cards)),
    )
    return best, hand_name


def _boss_eligible_plays(
    observation: PublicObservation,
    actions: list[PublicAction],
    current_boss: BossRule | None,
) -> list[PlayCards]:
    stats = {hand.name: hand for hand in observation.hand_stats}
    plays = [action for action in actions if isinstance(action, PlayCards)]
    if current_boss is None:
        return plays
    if current_boss.min_selected_cards is not None:
        plays = [
            action
            for action in plays
            if len(action.cards) >= current_boss.min_selected_cards
        ]
    classified = [
        (
            action,
            _classify(
                tuple(observation.hand[slot.value] for slot in action.cards),
                frozenset(
                    joker.key
                    for joker in observation.jokers
                    if isinstance(joker, PublicItem) and not joker.debuffed
                ),
            ),
        )
        for action in plays
    ]
    if current_boss.repeat_hand_restriction:
        classified = [
            (action, hand_name)
            for action, hand_name in classified
            if stats.get(hand_name) is None or stats[hand_name].played_this_round == 0
        ]
    if current_boss.single_hand_family:
        played_families = {
            stat.name: stat.played_this_round
            for stat in stats.values()
            if stat.played_this_round > 0
        }
        if played_families:
            # A blocked off-family play can still appear in the public round
            # counters. The established Mouth family is the one with the most
            # recorded plays; ties are deterministic by semantic name.
            required_family = max(
                played_families,
                key=lambda name: (played_families[name], name),
            )
            classified = [
                (action, hand_name)
                for action, hand_name in classified
                if hand_name == required_family
            ]
    return [action for action, _ in classified]


def _todo_list_clear_play(
    observation: PublicObservation,
    actions: list[PublicAction],
    current_boss: BossRule | None,
    target_score: int,
) -> PlayCards | None:
    """Collect visible To Do List income only when the target hand also clears."""

    targets = {
        joker.runtime.target_hand
        for joker in observation.jokers
        if isinstance(joker, PublicItem)
        and not joker.debuffed
        and joker.key == "j_todo_list"
        and joker.runtime is not None
        and joker.runtime.target_hand is not None
    }
    if not targets:
        return None
    stats = {stat.name: stat for stat in observation.hand_stats}
    candidates: list[tuple[int | Fraction, tuple[int, ...], PlayCards]] = []
    for action in _boss_eligible_plays(observation, actions, current_boss):
        score, hand_name = _play_score(observation, action.cards, stats)
        if hand_name in targets and observation.round.chips + score >= target_score:
            candidates.append(
                (score, tuple(-slot.value for slot in action.cards), action)
            )
    return max(candidates, default=(0, (), None), key=lambda row: row[:2])[2]


def _build_pace_play(
    observation: PublicObservation,
    actions: list[PublicAction],
    current_boss: BossRule | None,
    build: BuildPlan,
    target_score: int,
) -> PlayCards | None:
    """Keep building the committed hand only when it meets blind-clear pace."""

    if observation.round.hands_left <= 0 or target_score <= observation.round.chips:
        return None
    required_per_hand = Fraction(
        target_score - observation.round.chips,
        observation.round.hands_left,
    )
    stats = {stat.name: stat for stat in observation.hand_stats}
    exact_candidates: list[tuple[int | Fraction, tuple[int, ...], PlayCards]] = []
    containing_candidates: list[tuple[int | Fraction, tuple[int, ...], PlayCards]] = []
    for action in _boss_eligible_plays(observation, actions, current_boss):
        score, hand_name = _play_score(observation, action.cards, stats)
        if score < required_per_hand:
            continue
        candidate = (score, tuple(-slot.value for slot in action.cards), action)
        if hand_name == build.primary_hand:
            exact_candidates.append(candidate)
            continue
        cards = tuple(observation.hand[slot.value] for slot in action.cards)
        if _hand_matches(cards, hand_name, build.primary_hand):
            containing_candidates.append(candidate)
    candidates = exact_candidates or containing_candidates
    return max(candidates, default=(0, (), None), key=lambda row: row[:2])[2]


def _score_improving_joker_reorder(
    observation: PublicObservation,
    all_actions: list[PublicAction],
    best_play: PlayCards,
    current_score: int | Fraction,
) -> ReorderJokers | None:
    """Take one adjacent public Joker swap only when it improves this hand."""

    candidates: list[tuple[int | Fraction, tuple[int, ...], ReorderJokers]] = []
    for action in all_actions:
        if not isinstance(action, ReorderJokers):
            continue
        reordered = replace(
            observation,
            jokers=tuple(observation.jokers[slot.value] for slot in action.order),
        )
        score, _ = _play_score(
            reordered,
            best_play.cards,
            {hand.name: hand for hand in reordered.hand_stats},
        )
        if score > current_score:
            candidates.append(
                (score, tuple(-slot.value for slot in action.order), action)
            )
    return max(candidates, default=(0, (), None), key=lambda candidate: candidate[:2])[
        2
    ]


def _boss_recovery_discard(
    observation: PublicObservation,
    actions: list[PublicAction],
    current_boss: BossRule,
) -> DiscardCards | None:
    discards = [action for action in actions if isinstance(action, DiscardCards)]
    if not discards:
        return None
    target_hand: str | None = None
    if current_boss.single_hand_family:
        played_families = {
            stat.name: stat.played_this_round
            for stat in observation.hand_stats
            if stat.played_this_round > 0
        }
        if played_families:
            target_hand = max(
                played_families,
                key=lambda name: (played_families[name], name),
            )
    kept = (
        _keep_slots_for_hand(observation, target_hand)
        if target_hand is not None
        else set()
    )
    candidates = [
        index
        for index, card in sorted(
            enumerate(observation.hand),
            key=lambda pair: (_card_chips(pair[1]), pair[0]),
        )
        if isinstance(card, VisiblePlayingCard) and index not in kept
    ]
    selected = tuple(HandSlot(index) for index in sorted(candidates[:5]))
    recovery = DiscardCards(selected) if selected else None
    return recovery if recovery in discards else None


def _boss_hidden_discard(
    observation: PublicObservation,
    actions: list[PublicAction],
    current_boss: BossRule,
) -> DiscardCards | None:
    """Cycle only explicitly hidden slots for a typed face-down boss."""

    if (
        current_boss.face_down_mode
        not in {
            FaceDownMode.FIRST_HAND,
            FaceDownMode.AFTER_PLAY,
            FaceDownMode.FACE_RANKS,
            FaceDownMode.RANDOM_DRAW,
        }
        or observation.round.discards_left <= 0
    ):
        return None
    hidden = [
        HandSlot(index)
        for index, card in enumerate(observation.hand)
        if isinstance(card, HiddenHandCard)
    ]
    selected = tuple(hidden[: min(5, observation.selection_limit)])
    discard = DiscardCards(selected) if selected else None
    return discard if discard in actions else None


def _boss_disable_sale(
    observation: PublicObservation,
    actions: list[PublicAction],
    current_boss: BossRule,
    build: BuildPlan,
) -> SellJoker | None:
    sales = {
        action.joker.value: action
        for action in actions
        if isinstance(action, SellJoker)
    }
    luchador = next(
        (
            sales[index]
            for index, joker in enumerate(observation.jokers)
            if isinstance(joker, PublicItem)
            and joker.key == "j_luchador"
            and index in sales
        ),
        None,
    )
    if luchador is not None:
        return luchador
    if not current_boss.sell_to_disable:
        return None
    if not any(
        isinstance(card, VisiblePlayingCard) and card.debuffed
        for card in observation.hand
    ):
        return None
    candidates = [
        (index, observation.jokers[index], action)
        for index, action in sales.items()
        if observation.jokers[index].edition != "NEGATIVE"
    ]
    if not candidates:
        return None
    reenabled = replace(
        observation,
        hand=tuple(
            replace(card, debuffed=False)
            if isinstance(card, VisiblePlayingCard)
            else card
            for card in observation.hand
        ),
    )
    play_actions = [action for action in actions if isinstance(action, PlayCards)]
    stats = {stat.name: stat for stat in observation.hand_stats}
    scored_sales: list[tuple[int | Fraction, int, int, int, SellJoker]] = []
    for index, joker, action in candidates:
        after_sale = replace(
            reenabled,
            jokers=(observation.jokers[:index] + observation.jokers[index + 1 :]),
        )
        score: int | Fraction = 0
        for hands_left in range(observation.round.hands_left, 0, -1):
            capacity_probe = replace(
                after_sale,
                round=replace(after_sale.round, hands_left=hands_left),
            )
            best_play, _ = _best_available_play(
                capacity_probe,
                play_actions,
                current_boss,
            )
            hand_score, _ = _play_score(
                capacity_probe,
                best_play.cards,
                stats,
            )
            score += hand_score
        scored_sales.append(
            (
                score,
                -_owned_joker_context_value(observation, index, build),
                joker.sell_cost or 0,
                -index,
                action,
            )
        )
    if scored_sales:
        return max(scored_sales, key=lambda candidate: candidate[:4])[4]
    return min(
        candidates,
        key=lambda candidate: (
            _owned_joker_context_value(observation, candidate[0], build),
            -(candidate[1].sell_cost or 0),
            candidate[0],
        ),
    )[2]


_PLAY_SCORE_CACHE: dict[
    int,
    tuple[
        PublicObservation,
        _PreparedScoreContext,
        dict[object, tuple[int | Fraction, str]],
    ],
] = {}
_PLAY_SCORE_CACHE_OBSERVATIONS = 16


def _play_score(
    observation: PublicObservation,
    selected: tuple[HandSlot, ...],
    stats: Mapping[str, HandStat] | None = None,
) -> tuple[int | Fraction, str]:
    """``score_play`` memoized per observation object; scores are pure in their inputs."""

    if any(isinstance(joker, HiddenJokerSlot) for joker in observation.jokers):
        # Amber Acorn hides the identity-to-position association.  A legal
        # public fallback can still rank hands by card-only score, but must not
        # pretend to know any Joker effect or copied position.
        observation = replace(observation, jokers=())

    entry = _PLAY_SCORE_CACHE.get(id(observation))
    if entry is None or entry[0] is not observation:
        if len(_PLAY_SCORE_CACHE) >= _PLAY_SCORE_CACHE_OBSERVATIONS:
            _PLAY_SCORE_CACHE.clear()
        entry = (observation, _prepare_score_context(observation), {})
        _PLAY_SCORE_CACHE[id(observation)] = entry
    key = (selected, None if stats is None else tuple(sorted(stats.items())))
    cached = entry[2].get(key)
    if cached is None:
        cached = _score_play_prepared(observation, selected, stats, entry[1])
        entry[2][key] = cached
    return cached


def _belief_tactical_action(observation: PublicObservation) -> PublicAction:
    hand_stats = {hand.name: hand for hand in observation.hand_stats}
    play, _, current_score = _best_play_with_score(observation, 0, hand_stats)
    if (
        observation.round.discards_left <= 0
        or any(isinstance(card, HiddenHandCard) for card in observation.hand)
        or not observation.hand
    ):
        return play
    try:
        belief = PublicDrawBelief.from_observation(observation)
    except ValueError:
        return play
    if belief.draw_count == 0:
        return play

    candidates = tuple(HandSlot(index) for index in range(len(observation.hand)))
    if len(candidates) * len(belief.remaining_deck) > _MAX_PUBLIC_DRAW_BRANCHES:
        return play

    ranked: list[tuple[Fraction, int, DiscardCards]] = []
    for slot in candidates:
        discard = DiscardCards((slot,))
        if not is_legal(observation, discard):
            continue
        weighted_score = Fraction(0)
        for entry in belief.remaining_deck:
            hand = list(observation.hand)
            hand[slot.value] = entry.card
            hypothetical = replace(observation, hand=tuple(hand))
            _, _, score = _best_play_with_score(hypothetical, 0, hand_stats)
            weighted_score += entry.count * score
        expected_score = weighted_score / belief.draw_count
        ranked.append((expected_score, -slot.value, discard))
    if not ranked:
        return play
    expected_score, _, discard = max(ranked, key=lambda item: (item[0], item[1]))
    return discard if expected_score > current_score else play


def _passive_control_action(
    observation: PublicObservation,
    legal_actions: ActionSource,
) -> PublicAction:
    actions = _bounded_actions(legal_actions())
    expected = {
        Phase.BLIND_SELECT: SelectBlind,
        Phase.ROUND_EVAL: CashOut,
        Phase.SHOP: LeaveShop,
        Phase.PACK: SkipPack,
    }.get(observation.phase)
    if expected is None:
        raise RuntimeError(f"no passive action for {observation.phase.value}")
    return next(action for action in actions if isinstance(action, expected))


def _held_planet_action(
    observation: PublicObservation,
    build: BuildPlan | None = None,
) -> UseConsumable | None:
    if "v_observatory" in observation.used_vouchers:
        return None
    candidates = [
        (
            _committed_planet_value(item.key, build),
            -index,
            UseConsumable(ConsumableSlot(index)),
        )
        for index, item in enumerate(observation.consumables)
        if item.kind.upper() == "PLANET"
        and _committed_planet_value(item.key, build) > 0
    ]
    legal = [
        candidate for candidate in candidates if is_legal(observation, candidate[2])
    ]
    return max(legal, default=(0, 0, None), key=lambda candidate: candidate[:2])[2]


def _strategic_consumable_action(
    observation: PublicObservation,
    actions: list[PublicAction],
    build: BuildPlan,
) -> PublicAction | None:
    uses = [action for action in actions if isinstance(action, UseConsumable)]
    ranked: list[tuple[int, int, UseConsumable]] = []
    for action in uses:
        item = observation.consumables[action.consumable.value]
        value = _consumable_value(
            observation,
            item,
            tuple(slot.value for slot in action.targets),
            build,
        )
        if value > 0:
            ranked.append((value, -action.consumable.value, action))
    if ranked:
        return max(ranked, key=lambda candidate: candidate[:2])[2]

    if len(observation.consumables) < observation.consumable_limit:
        return None
    useful_planet = any(
        isinstance(item, PublicItem)
        and item.kind.upper() == "PLANET"
        and _committed_planet_value(item.key, build) > 0
        and (item.buy_cost or 0) <= observation.money
        for item in observation.shop
    )
    if not useful_planet:
        return None
    sell_actions = [action for action in actions if isinstance(action, SellConsumable)]
    if not sell_actions:
        return None
    return min(
        sell_actions,
        key=lambda action: (
            _consumable_value(
                observation,
                observation.consumables[action.consumable.value],
                (),
                build,
            ),
            action.consumable.value,
        ),
    )


def _consumable_value(
    observation: PublicObservation,
    item: PublicItem,
    targets: tuple[int, ...],
    build: BuildPlan,
) -> int:
    if item.kind.upper() == "PLANET":
        if "v_observatory" in observation.used_vouchers:
            return 0
        return _committed_planet_value(item.key, build)
    if item.key == "c_hermit" and observation.money <= 0:
        return 0
    if item.key == "c_temperance" and not observation.jokers:
        return 0
    if item.key == "c_wraith" and observation.money > 4:
        return 0
    if item.key == "c_hex" and len(observation.jokers) > 1:
        return 0
    if not targets:
        return _UNTARGETED_CONSUMABLE_VALUES.get(item.key, 0)

    selected: list[VisiblePlayingCard] = []
    for target in targets:
        if target >= len(observation.hand):
            return 0
        card = observation.hand[target]
        if not isinstance(card, VisiblePlayingCard):
            return 0
        selected.append(card)
    value = _TARGETED_CONSUMABLE_VALUES.get(item.key, 0)
    if value <= 0:
        return 0
    if item.key == "c_hanged_man":
        value += sum(max(0, 15 - _card_chips(card)) for card in selected)
    elif item.key in {
        "c_empress",
        "c_heirophant",
        "c_chariot",
        "c_justice",
        "c_magician",
    }:
        value += sum(_card_chips(card) for card in selected)
    elif item.key in {"c_star", "c_moon", "c_sun", "c_world"}:
        target_suit = {
            "c_star": "D",
            "c_moon": "C",
            "c_sun": "H",
            "c_world": "S",
        }[item.key]
        hand_suits = Counter(
            card.suit
            for card in observation.hand
            if isinstance(card, VisiblePlayingCard)
        )
        value += 10 * hand_suits[target_suit]
        value += 5 * sum(card.suit != target_suit for card in selected)
    elif item.key == "c_tower":
        value += sum(max(0, 12 - _card_chips(card)) for card in selected)
    return value


def _strategic_shop_action(
    observation: PublicObservation,
    actions: list[PublicAction],
    history: tuple[PublicHistoryStep, ...],
    max_shop_actions: int,
    build: BuildPlan,
    tuning: StrategyTuning = StrategyTuning(),
) -> PublicAction:
    planet = _held_planet_action(observation, build)
    if planet is not None and planet in actions:
        return planet
    shop_steps = _current_shop_action_count(history)
    if shop_steps >= max_shop_actions:
        return _action_of_type(actions, LeaveShop)

    scoring_jokers = sum(
        _joker_context_is_scorer(observation, index)
        for index in range(len(observation.jokers))
    )
    building = scoring_jokers < 2
    interest_floor = _economy_reserve(observation, tuning)
    spendable = observation.money - interest_floor

    replacement = _replacement_sale(
        observation,
        actions,
        shop_steps=shop_steps,
        max_shop_actions=max_shop_actions,
        interest_floor=interest_floor,
        tuning=tuning,
        replaced_this_shop=_current_shop_has_sale(history),
        require_score_gain=_has_prior_shop_sale(history),
        history=history,
        build=build,
    )
    if replacement is not None:
        return replacement

    joker_buys = [
        action
        for action in actions
        if isinstance(action, BuyShopCard)
        and isinstance(observation.shop[action.card.value], PublicItem)
        and observation.shop[action.card.value].kind.upper() == "JOKER"
    ]
    buyable_jokers = [
        action
        for action in joker_buys
        if _joker_value(observation.shop[action.card.value], build) >= 45
        and (observation.shop[action.card.value].buy_cost or 0)
        <= observation.money
        - (
            3
            if building
            or _joker_value(observation.shop[action.card.value], build) >= 80
            else interest_floor
        )
    ]
    if buyable_jokers:
        return max(
            buyable_jokers,
            key=lambda action: (
                _shop_joker_survival_rank(
                    observation,
                    history,
                    observation.shop[action.card.value],
                ),
                _shop_joker_score_rank(
                    observation,
                    history,
                    observation.shop[action.card.value],
                ),
                _joker_value(observation.shop[action.card.value], build),
                -(observation.shop[action.card.value].buy_cost or 0),
                -action.card.value,
            ),
        )

    rerolls = [action for action in actions if isinstance(action, RerollShop)]
    has_xmult = any(
        _joker_context_supplies_usable_xmult(observation, index, build)
        for index in range(len(observation.jokers))
    )
    weakest_value = min(
        (
            _owned_joker_context_value(observation, index, build)
            for index in range(len(observation.jokers))
        ),
        default=0,
    )
    needs_upgrade = len(observation.jokers) >= observation.joker_limit and (
        not has_xmult or weakest_value < tuning.sell_threshold
    )

    vouchers = [
        action
        for action in actions
        if isinstance(action, BuyVoucher)
        and _voucher_value(observation.vouchers[action.voucher.value]) >= 55
        and (observation.vouchers[action.voucher.value].buy_cost or 0) <= spendable
    ]
    if vouchers and (scoring_jokers >= 2 or observation.money >= interest_floor + 20):
        return max(
            vouchers,
            key=lambda action: (
                _voucher_value(observation.vouchers[action.voucher.value]),
                -(observation.vouchers[action.voucher.value].buy_cost or 0),
                -action.voucher.value,
            ),
        )

    if len(observation.consumables) < observation.consumable_limit:
        planet_buys = [
            action
            for action in actions
            if isinstance(action, BuyShopCard)
            and isinstance(observation.shop[action.card.value], PublicItem)
            and observation.shop[action.card.value].kind.upper() == "PLANET"
            and (observation.shop[action.card.value].buy_cost or 0)
            <= observation.money
            - (
                3
                if _committed_planet_value(
                    observation.shop[action.card.value].key,
                    build,
                )
                >= 100
                else interest_floor
            )
            and _committed_planet_value(
                observation.shop[action.card.value].key,
                build,
            )
            > 0
        ]
        if planet_buys:
            return max(
                planet_buys,
                key=lambda action: (
                    _committed_planet_value(
                        observation.shop[action.card.value].key,
                        build,
                    ),
                    -action.card.value,
                ),
            )

    if (
        needs_upgrade
        and rerolls
        and shop_steps < 3
        and observation.round.reroll_cost <= spendable
    ):
        return rerolls[0]

    pack_buys = []
    for action in actions:
        if not isinstance(action, BuyPack):
            continue
        pack = observation.packs[action.pack.value]
        is_buffoon = pack.key.startswith("p_buffoon")
        is_celestial = pack.key.startswith("p_celestial")
        if not (
            (
                is_buffoon
                and building
                and len(observation.jokers) < observation.joker_limit
            )
            or (is_celestial and "v_observatory" not in observation.used_vouchers)
        ):
            continue
        pack_floor = (
            3
            if building and is_buffoon
            else min(12, interest_floor)
            if is_celestial
            else interest_floor
        )
        if (pack.buy_cost or 0) <= observation.money - pack_floor:
            pack_buys.append(action)
    if pack_buys:
        return max(
            pack_buys,
            key=lambda action: (
                int(
                    building
                    and observation.packs[action.pack.value].key.startswith("p_buffoon")
                ),
                -(observation.packs[action.pack.value].buy_cost or 0),
                -action.pack.value,
            ),
        )

    if rerolls and shop_steps < 3 and observation.round.reroll_cost <= spendable:
        if building and not buyable_jokers:
            return rerolls[0]

    if rerolls and observation.round.reroll_cost == 0:
        return rerolls[0]
    return _action_of_type(actions, LeaveShop)


def _shop_joker_survival_rank(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
    offer: PublicItem,
) -> tuple[int, int | Fraction, int | Fraction]:
    """Rank an offer by a public representative hand's boss survival margin.

    The projection deliberately reuses only the most recent fully visible play.
    It does not guess a draw or retain the prior blind's debuffs. Unsupported or
    ambiguous history returns the neutral rank, preserving typed category value
    as the shop fallback.
    """

    if observation.round_no % 3 != 2:
        return 0, 0, 0
    probe = _shop_joker_score_probe(observation, history, offer)
    if probe is None:
        return 0, 0, 0
    recent, hands_per_blind, current_score, offer_score = probe
    previous_blind = next(
        (blind for blind in recent.before.blinds if blind.status == "CURRENT"),
        None,
    )
    if previous_blind is None or previous_blind.kind != "BIG":
        return 0, 0, 0
    boss = next(
        (
            blind
            for blind in observation.blinds
            if blind.kind == "BOSS" and blind.status in {"UPCOMING", "SELECT"}
        ),
        None,
    )
    rule = boss_rule(boss.name) if boss is not None else None
    if boss is None or boss.score <= 0 or rule is None or not rule.high_target:
        return 0, 0, 0
    current_capacity = hands_per_blind * current_score
    offer_capacity = hands_per_blind * offer_score
    current_gap = max(0, boss.score - current_capacity)
    offer_gap = max(0, boss.score - offer_capacity)
    if current_gap <= 0 or offer_gap > 0:
        return 0, 0, 0
    return (
        1,
        offer_capacity - boss.score,
        offer_capacity - current_capacity,
    )


def _shop_joker_score_rank(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
    offer: PublicItem,
) -> tuple[int, int | Fraction, int | Fraction]:
    """Rank a modeled offer by its delta on an exactly observed public play."""

    probe = _shop_joker_score_probe(observation, history, offer)
    if probe is None:
        return 0, 0, 0
    _, _, current_score, offer_score = probe
    if offer_score <= current_score:
        return 0, 0, 0
    return 1, offer_score - current_score, offer_score


def _shop_joker_score_probe(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
    offer: PublicItem,
) -> tuple[PublicHistoryStep, int, int | Fraction, int | Fraction] | None:
    """Project one offer only after reproducing a deterministic public score."""

    if offer.key in {"j_bloodstone", "j_misprint"}:
        return None
    context = _shop_score_context(observation, history)
    if context is None:
        return None
    recent, hands_per_blind, projection, selected, stats, current_score = context
    with_offer = replace(
        projection,
        money=observation.money - (offer.buy_cost or 0),
        jokers=(*observation.jokers, offer),
    )
    offer_score, _ = _play_score(with_offer, selected, stats)
    return recent, hands_per_blind, current_score, offer_score


_ShopScoreContext = tuple[
    PublicHistoryStep,
    int,
    PublicObservation,
    tuple[HandSlot, ...],
    Mapping[str, HandStat],
    int | Fraction,
]


def _shop_score_context(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
) -> _ShopScoreContext | None:
    """Return a score probe only immediately after the current cash-out."""

    if len(history) < 2:
        return None
    cashout = history[-1]
    recent = history[-2]
    if not (
        isinstance(cashout.action, CashOut)
        and cashout.before.phase == Phase.ROUND_EVAL
        and _without_loyalty_remaining(cashout.after)
        == _without_loyalty_remaining(observation)
        and isinstance(recent.action, PlayCards)
        and recent.before.phase == Phase.SELECTING_HAND
        and recent.after == cashout.before
    ):
        return None
    return _persisted_shop_score_context(observation, history)


def _persisted_shop_score_context(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
) -> _ShopScoreContext | None:
    """Return a neutral shop scoring probe after exact public reproduction."""

    if len(history) < 2 or observation.phase != Phase.SHOP:
        return None
    cashout_index = next(
        (
            index
            for index in range(len(history) - 1, 0, -1)
            if isinstance(history[index].action, CashOut)
            and history[index].before.phase == Phase.ROUND_EVAL
            and history[index].after.phase == Phase.SHOP
        ),
        None,
    )
    if cashout_index is None:
        return None
    cashout = history[cashout_index]
    recent = history[cashout_index - 1]
    if not (
        cashout.after.ante == observation.ante
        and cashout.after.round_no == observation.round_no
        and all(
            step.before.phase in {Phase.SHOP, Phase.PACK}
            and step.after.phase in {Phase.SHOP, Phase.PACK}
            for step in history[cashout_index + 1 :]
        )
        and isinstance(recent.action, PlayCards)
        and recent.before.phase == Phase.SELECTING_HAND
        and recent.after == cashout.before
    ):
        return None
    recent_before = _with_history_derived_joker_runtime(
        recent.before,
        history[: cashout_index - 1],
    )
    selected = recent.action.cards
    if (
        not selected
        or any(slot.value >= len(recent_before.hand) for slot in selected)
        or not is_legal(recent_before, recent.action)
        or any(
            not isinstance(card, VisiblePlayingCard) or card.debuffed
            for card in recent_before.hand
        )
    ):
        return None
    hands_per_blind = recent_before.round.hands_left + recent_before.round.hands_played
    if hands_per_blind <= 0:
        return None
    stochastic_keys = {"j_bloodstone", "j_misprint"}
    if any(
        joker.key in stochastic_keys
        for joker in recent_before.jokers
        if isinstance(joker, PublicItem) and not joker.debuffed
    ):
        return None
    historical_stats = {stat.name: stat for stat in recent_before.hand_stats}
    historical_score, _ = _play_score(recent_before, selected, historical_stats)
    observed_score = recent.after.round.chips - recent_before.round.chips
    if historical_score.denominator != 1 or int(historical_score) != observed_score:
        return None

    discards_per_blind = (
        recent_before.round.discards_left + recent_before.round.discards_used
    )
    reset_stats = tuple(
        replace(stat, played_this_round=0) for stat in observation.hand_stats
    )
    projection = replace(
        recent_before,
        ante=observation.ante,
        money=observation.money,
        round=replace(
            recent_before.round,
            chips=0,
            hands_left=hands_per_blind,
            discards_left=discards_per_blind,
            hands_played=0,
            discards_used=0,
            ancient_suit=observation.round.ancient_suit,
        ),
        blinds=observation.blinds,
        hand_stats=reset_stats,
        jokers=observation.jokers,
        required_hand_slots=(),
    )
    stats = {stat.name: stat for stat in reset_stats}
    current_score, _ = _play_score(projection, selected, stats)
    return recent, hands_per_blind, projection, selected, stats, current_score


def _strategic_pack_action(
    observation: PublicObservation,
    actions: list[PublicAction],
    build: BuildPlan,
) -> PublicAction:
    choices = [action for action in actions if isinstance(action, ChoosePackCard)]
    if not choices:
        return _action_of_type(actions, SkipPack)

    def value(action: ChoosePackCard) -> tuple[int, int]:
        offer = observation.opened_pack[action.card.value]
        if isinstance(offer, VisiblePlayingCard):
            return 5, -action.card.value
        if offer.kind.upper() == "PLANET":
            return _committed_planet_value(offer.key, build), -action.card.value
        if offer.kind.upper() == "JOKER":
            return _joker_value(offer, build), -action.card.value
        return (
            _consumable_value(
                observation,
                offer,
                tuple(slot.value for slot in action.targets),
                build,
            ),
            -action.card.value,
        )

    best = max(choices, key=value)
    # Unknown effects preserve the explicit skip baseline until a typed public
    # rule assigns positive value.
    return best if value(best)[0] > 0 else _action_of_type(actions, SkipPack)


def _committed_planet_value(key: str, build: BuildPlan | None) -> int:
    """Value only Planets for the two explicitly selected build lanes.

    Coverage mode has no strategic build and should continue exercising any
    legal Planet.  The strategic policy must not let a merely related or
    unrelated Planet create the evidence that changes its own commitment.
    """

    if build is None:
        return 1
    hand = planet_hand(key)
    if hand == build.primary_hand:
        return 100
    if hand == build.secondary_hand:
        return 80
    return 0


def _phase1_joker_supported(item: PublicItem) -> bool:
    """Return whether Phase 1 can model this Joker from typed public state."""

    if item.key in _STATIC_PHASE1_JOKERS or item.key in _PHASE1_CONTEXT_JOKER_VALUES:
        return True
    runtime = item.runtime
    if runtime is None:
        return False
    if any(
        value is not None
        for value in (
            runtime.current_mult,
            runtime.current_chips,
            runtime.current_x_mult,
        )
    ):
        return True
    if item.key == "j_drivers_license":
        return runtime.driver_tally is not None
    if item.key == "j_loyalty_card":
        return runtime.loyalty_remaining is not None
    if item.key == "j_selzer":
        return runtime.remaining_hands is not None
    return False


def _joker_value(item: PublicItem, build: BuildPlan | None = None) -> int:
    try:
        profile = get_joker_profile(item.key)
    except KeyError:
        return 0
    if not _phase1_joker_supported(item):
        return 0
    if (
        build is not None
        and item.key in _TYPE_XMULT_JOKERS
        and not _build_supports_hand_xmult(item.key, build)
    ):
        return 0
    if (
        build is not None
        and profile.archetypes & _HAND_BUILD_ARCHETYPES
        and not profile.archetypes & build.favored_tags
    ):
        return 0
    value = _JOKER_ROLE_VALUES[profile.primary_role]
    value = max(value, _PHASE1_CONTEXT_JOKER_VALUES.get(item.key, 0))
    if item.runtime is not None and item.runtime.current_x_mult is not None:
        runtime_xmult = item.runtime.current_x_mult
        realized_value = (
            20 if runtime_xmult <= 1 else min(110, 55 + int(30 * (runtime_xmult - 1)))
        )
        if profile.primary_role == "x_mult":
            value = realized_value
        elif profile.primary_role == "scaling":
            value = max(45, realized_value)
    # Blueprint and Brainstorm are catalogued as utility because their effect
    # is compositional, but they are still first-class scoring cards.
    if profile.primary_role == "utility" and profile.score_effect:
        value += 65
    if build is not None:
        value += 18 * min(2, len(profile.archetypes & build.favored_tags))
    if item.edition == "POLYCHROME":
        value += 25
    elif item.edition in {"FOIL", "HOLO", "HOLOGRAPHIC"}:
        value += 10
    if item.rental:
        value -= 25
    if item.perishable_rounds is not None:
        value -= 10
    return value


def _joker_context_target(
    observation: PublicObservation,
    index: int,
) -> PublicItem | None:
    return _effective_joker_for_pass(
        observation.jokers,
        index,
        _COPY_SCORING_JOKERS,
    )


def _joker_context_is_scorer(
    observation: PublicObservation,
    index: int,
) -> bool:
    item = _joker_context_target(observation, index)
    return item is not None and _joker_is_scorer(item)


def _owned_joker_context_value(
    observation: PublicObservation,
    index: int,
    build: BuildPlan | None = None,
) -> int:
    item = observation.jokers[index]
    if isinstance(item, HiddenJokerSlot):
        return 0
    if item.key not in _COPY_JOKERS:
        return _owned_joker_value(item, observation.ante, build)
    target = _joker_context_target(observation, index)
    if target is None:
        return 0
    return _owned_joker_value(target, observation.ante, build)


def _joker_context_supplies_additive_mult(
    observation: PublicObservation,
    index: int,
) -> bool:
    item = _joker_context_target(observation, index)
    return item is not None and _joker_supplies_additive_mult(item)


def _joker_context_supplies_usable_xmult(
    observation: PublicObservation,
    index: int,
    build: BuildPlan,
) -> bool:
    item = _joker_context_target(observation, index)
    return item is not None and _joker_supplies_usable_xmult(item, build)


def _joker_is_scorer(item: PublicItem) -> bool:
    if item.debuffed:
        return False
    try:
        return (
            _phase1_joker_supported(item) and get_joker_profile(item.key).score_effect
        )
    except KeyError:
        return False


def _joker_supplies_additive_mult(item: PublicItem) -> bool:
    if item.debuffed:
        return False
    if item.runtime is not None and (item.runtime.current_mult or 0) > 0:
        return True
    try:
        return get_joker_profile(item.key).primary_role == "flat_mult"
    except KeyError:
        return False


def _joker_supplies_usable_xmult(item: PublicItem, build: BuildPlan) -> bool:
    if item.debuffed:
        return False
    if item.runtime is not None and item.runtime.current_x_mult is not None:
        return item.runtime.current_x_mult > 1
    if item.key in _UNCONDITIONAL_XMULT_JOKERS:
        return True
    if not _phase1_joker_supported(item):
        return False
    if item.key in _TYPE_XMULT_JOKERS:
        return _build_supports_hand_xmult(item.key, build)
    try:
        profile = get_joker_profile(item.key)
    except KeyError:
        return False
    if profile.primary_role != "x_mult":
        return False
    hand_archetypes = profile.archetypes & _HAND_BUILD_ARCHETYPES
    return not hand_archetypes or bool(hand_archetypes & build.favored_tags)


def _build_supports_hand_xmult(key: str, build: BuildPlan) -> bool:
    family = _TYPE_XMULT_JOKERS[key][0]
    triggering_hands = _HANDS_CONTAINING_FAMILY[family]
    return build.primary_hand in triggering_hands or (
        build.secondary_hand is not None and build.secondary_hand in triggering_hands
    )


def _known_joker(item: PublicItem) -> bool:
    try:
        get_joker_profile(item.key)
    except KeyError:
        return False
    return True


def _economy_reserve(
    observation: PublicObservation,
    tuning: StrategyTuning = StrategyTuning(),
) -> int:
    interest_cap = 25
    if "v_seed_money" in observation.used_vouchers:
        interest_cap = 50
    if "v_money_tree" in observation.used_vouchers:
        interest_cap = 100
    if observation.ante <= 1:
        reserve = tuning.reserve_ante_1
    elif observation.ante == 2:
        reserve = tuning.reserve_ante_2
    elif observation.ante == 3:
        reserve = tuning.reserve_ante_3
    else:
        reserve = interest_cap
    if any(
        joker.key in {"j_bull", "j_bootstraps"}
        for joker in observation.jokers
        if isinstance(joker, PublicItem)
    ):
        reserve = max(reserve, interest_cap)
    return reserve


def _voucher_value(item: PublicItem) -> int:
    return _VOUCHER_VALUES.get(item.key, 0)


def _owned_joker_value(
    item: PublicItem,
    ante: int,
    build: BuildPlan | None = None,
) -> int:
    value = _joker_value(item, build)
    try:
        profile = get_joker_profile(item.key)
    except KeyError:
        return value
    if profile.primary_role == "scaling" and not (
        item.runtime is not None
        and item.runtime.current_x_mult is not None
        and item.runtime.current_x_mult <= 1
    ):
        value += 20
    if ante >= 4 and profile.primary_role == "economy":
        value -= 50
    return value


def _replacement_sale(
    observation: PublicObservation,
    actions: list[PublicAction],
    *,
    shop_steps: int,
    max_shop_actions: int,
    interest_floor: int,
    replaced_this_shop: bool,
    require_score_gain: bool,
    history: tuple[PublicHistoryStep, ...],
    build: BuildPlan,
    tuning: StrategyTuning = StrategyTuning(),
) -> SellJoker | None:
    if observation.ante < 4 or replaced_this_shop:
        return None
    if (
        observation.joker_limit <= 0
        or len(observation.jokers) != observation.joker_limit
    ):
        return None
    if shop_steps + 1 >= max_shop_actions:
        return None

    sellable = [
        (index, item)
        for index, item in enumerate(observation.jokers)
        if isinstance(item, PublicItem)
        and not item.eternal
        and item.edition != "NEGATIVE"
        and item.sell_cost is not None
        and item.sell_cost >= 0
        and _known_joker(item)
    ]
    if not sellable:
        return None
    score_context = (
        _persisted_shop_score_context(observation, history)
        if require_score_gain
        else None
    )
    if require_score_gain and score_context is None:
        return None
    owned_keys = {
        item.key for item in observation.jokers if isinstance(item, PublicItem)
    }
    building_after_sale = len(observation.jokers) - 1 < min(4, observation.joker_limit)
    additive_mult_count = sum(
        _joker_context_supplies_additive_mult(observation, index)
        for index in range(len(observation.jokers))
    )
    replacements: list[tuple[int | Fraction, int, int, int, PublicItem]] = []
    for index, weakest in sellable:
        offers = [
            item
            for item in observation.shop
            if isinstance(item, PublicItem)
            and item.kind.upper() == "JOKER"
            and item.key not in owned_keys
            and (
                not require_score_gain or item.key not in {"j_bloodstone", "j_misprint"}
            )
            and item.buy_cost is not None
            and item.buy_cost >= 0
            and (building_after_sale or _joker_value(item, build) >= 25)
            and observation.money + weakest.sell_cost - item.buy_cost
            >= (3 if _joker_value(item, build) >= 80 else interest_floor)
            and (
                additive_mult_count != 1
                or not _joker_context_supplies_additive_mult(observation, index)
                or _joker_supplies_additive_mult(item)
            )
        ]
        if not offers:
            continue
        owned_value = _owned_joker_context_value(observation, index, build)
        ranked_offers: list[tuple[int | Fraction, int, int, str, PublicItem]] = []
        for offer in offers:
            offer_value = _joker_value(offer, build)
            if offer_value < owned_value + tuning.replacement_margin:
                continue
            primary_gain: int | Fraction = offer_value - owned_value
            if score_context is not None:
                _, _, projection, selected, stats, current_score = score_context
                with_replacement = replace(
                    projection,
                    money=(
                        observation.money + weakest.sell_cost - (offer.buy_cost or 0)
                    ),
                    jokers=(
                        observation.jokers[:index]
                        + observation.jokers[index + 1 :]
                        + (offer,)
                    ),
                )
                replacement_score, _ = _play_score(
                    with_replacement,
                    selected,
                    stats,
                )
                if replacement_score <= current_score:
                    continue
                primary_gain = replacement_score - current_score
            ranked_offers.append(
                (
                    primary_gain,
                    offer_value,
                    -(offer.buy_cost or 0),
                    offer.key,
                    offer,
                )
            )
        if not ranked_offers:
            continue
        primary_gain, offer_value, _, _, _ = max(
            ranked_offers,
            key=lambda candidate: candidate[:4],
        )
        replacements.append(
            (
                primary_gain,
                offer_value,
                weakest.sell_cost,
                -index,
                weakest,
            )
        )
    if not replacements:
        return None
    _, _, _, negative_index, _ = max(replacements, key=lambda candidate: candidate[:4])
    action = SellJoker(JokerSlot(-negative_index))
    return action if action in actions else None


def _action_of_type(
    actions: list[PublicAction],
    action_type: type[object],
) -> PublicAction:
    return next(action for action in actions if isinstance(action, action_type))


def _coverage_discard(
    observation: PublicObservation,
    best: PlayCards,
    hand_name: str,
    *,
    fish_strong_hand: bool = False,
    target_hand: str | None = None,
    draw_count_override: int | None = None,
) -> DiscardCards | None:
    if observation.round.discards_left <= 0:
        return None
    if not fish_strong_hand and any(
        joker.key in {"j_green_joker", "j_ramen"}
        for joker in observation.jokers
        if isinstance(joker, PublicItem)
    ):
        return None
    weak_hand = hand_name in {"High Card", "Pair", "Two Pair", "Three of a Kind"}
    if not weak_hand and not fish_strong_hand:
        return None

    visible = {
        index: card
        for index, card in enumerate(observation.hand)
        if isinstance(card, VisiblePlayingCard)
    }
    if not visible and fish_strong_hand:
        limit = min(5, observation.selection_limit, len(observation.hand))
        selected = tuple(HandSlot(index) for index in range(limit))
        return DiscardCards(selected) if selected else None
    if weak_hand:
        if target_hand is not None:
            kept = _keep_slots_for_hand(observation, target_hand)
            visible_cards = tuple(visible.values())
            active_keys = frozenset(
                joker.key
                for joker in observation.jokers
                if isinstance(joker, PublicItem) and not joker.debuffed
            )
            target_made = _hand_matches(
                visible_cards,
                _classify(visible_cards, active_keys),
                target_hand,
            )
            if not target_made:
                rank_counts = Counter(card.rank for card in visible.values())
                paired = {
                    index
                    for index, card in visible.items()
                    if rank_counts[card.rank] >= 2
                }
                if len(paired) > len(kept):
                    kept = paired
                suit_counts = Counter(card.suit for card in visible.values())
                if suit_counts:
                    suit, count = suit_counts.most_common(1)[0]
                    if count >= 3 and count > len(kept):
                        kept = {
                            index
                            for index, card in visible.items()
                            if card.suit == suit
                        }
                straight_kept = _keep_slots_for_hand(observation, "Straight")
                if len(straight_kept) >= 4 and len(straight_kept) > len(kept):
                    kept = straight_kept
        else:
            rank_counts = Counter(card.rank for card in visible.values())
            suit_counts = Counter(card.suit for card in visible.values())
            kept = {
                index for index, card in visible.items() if rank_counts[card.rank] >= 2
            }
            if suit_counts:
                suit, count = suit_counts.most_common(1)[0]
                if count >= 3 and count > len(kept):
                    kept = {
                        index for index, card in visible.items() if card.suit == suit
                    }
    else:
        # On the last hand, a made hand that still cannot clear may improve by
        # cycling its kickers. Preserve every card in the current best play.
        kept = {slot.value for slot in best.cards}

    candidates = [
        index
        for index, card in sorted(
            visible.items(), key=lambda pair: (_card_chips(pair[1]), pair[0])
        )
        if index not in kept
    ]
    if fish_strong_hand:
        candidates.extend(
            index
            for index in range(len(observation.hand))
            if index not in visible and index not in kept
        )
    if not candidates:
        best_slots = {slot.value for slot in best.cards}
        candidates = [index for index in visible if index not in best_slots]
    limit = min(
        5,
        observation.selection_limit,
        len(candidates),
        draw_count_override if draw_count_override is not None else 5,
    )
    selected = sorted(candidates[:limit])
    return (
        DiscardCards(tuple(HandSlot(index) for index in selected)) if selected else None
    )


def _keep_slots_for_hand(
    observation: PublicObservation,
    hand_name: str,
) -> set[int]:
    visible = {
        index: card
        for index, card in enumerate(observation.hand)
        if isinstance(card, VisiblePlayingCard) and card.enhancement != "STONE"
    }
    if not visible:
        return set()
    rank_slots: dict[str, list[int]] = {}
    suit_slots: dict[str, list[int]] = {}
    for index, card in visible.items():
        rank_slots.setdefault(card.rank, []).append(index)
        suit_slots.setdefault(card.suit, []).append(index)

    if hand_name == "Pair":
        paired = {
            index for slots in rank_slots.values() if len(slots) >= 2 for index in slots
        }
        if paired:
            return paired
        best_rank = max(
            rank_slots,
            key=lambda rank: (
                len(rank_slots[rank]),
                _RANK_ORDER.get(rank, 0),
                -min(rank_slots[rank]),
            ),
        )
        return set(rank_slots[best_rank])
    if hand_name in {"Three of a Kind", "Four of a Kind", "Five of a Kind"}:
        best_rank = max(
            rank_slots,
            key=lambda rank: (
                len(rank_slots[rank]),
                _RANK_ORDER.get(rank, 0),
                -min(rank_slots[rank]),
            ),
        )
        return set(rank_slots[best_rank])
    if hand_name in {"Two Pair", "Full House", "Flush House", "Flush Five"}:
        ranked = sorted(
            rank_slots,
            key=lambda rank: (
                len(rank_slots[rank]),
                _RANK_ORDER.get(rank, 0),
                -min(rank_slots[rank]),
            ),
            reverse=True,
        )
        return {index for rank in ranked[:2] for index in rank_slots[rank]}
    if hand_name in {"Flush", "Straight Flush"}:
        best_suit = max(
            suit_slots,
            key=lambda suit: (len(suit_slots[suit]), -min(suit_slots[suit])),
        )
        return set(suit_slots[best_suit])
    if hand_name == "Straight":
        windows = [set(range(start, start + 5)) for start in range(2, 11)]
        windows.append({14, 2, 3, 4, 5})
        best_window = max(
            windows,
            key=lambda window: (
                sum(
                    _RANK_ORDER.get(card.rank, 0) in window for card in visible.values()
                ),
                sum(window),
            ),
        )
        kept: set[int] = set()
        seen_ranks: set[str] = set()
        for index, card in visible.items():
            if (
                _RANK_ORDER.get(card.rank, 0) in best_window
                and card.rank not in seen_ranks
            ):
                kept.add(index)
                seen_ranks.add(card.rank)
        return kept
    highest = max(
        visible,
        key=lambda index: (_card_chips(visible[index]), -index),
    )
    return {highest}


def _bounded_actions(
    actions: Iterator[PublicAction],
    limit: int = _MAX_PUBLIC_ACTIONS,
) -> list[PublicAction]:
    return [
        action
        for action in islice(actions, limit)
        if not isinstance(action, _REORDER_TYPES)
    ]


def _current_shop_action_count(history: tuple[PublicHistoryStep, ...]) -> int:
    count = 0
    for step in reversed(history):
        if step.before.phase == Phase.ROUND_EVAL and step.after.phase == Phase.SHOP:
            break
        if step.before.phase == Phase.SHOP:
            count += 1
    return count


def _current_shop_has_sale(history: tuple[PublicHistoryStep, ...]) -> bool:
    for step in reversed(history):
        if step.before.phase == Phase.ROUND_EVAL and step.after.phase == Phase.SHOP:
            break
        if step.before.phase == Phase.SHOP and isinstance(step.action, SellJoker):
            return True
    return False


def _has_prior_shop_sale(history: tuple[PublicHistoryStep, ...]) -> bool:
    return any(
        step.before.phase == Phase.SHOP and isinstance(step.action, SellJoker)
        for step in history
    )
