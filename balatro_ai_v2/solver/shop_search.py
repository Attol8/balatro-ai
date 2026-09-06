"""Bounded shop comparisons on shared, synthetic public-deck hands.

Capacity estimates omit future boss effects and stochastic trigger outcomes;
they are a purchasing heuristic, not predictions of the next actual draw.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections import Counter
from itertools import combinations
from math import log1p
from random import Random

from balatro_ai_v2.solver.actions import (
    BuyMode, BuyShopCard, HandSlot, JokerSlot, LeaveShop, PublicAction, RerollShop,
    SellJoker, ShopSlot, BuyPack, BuyVoucher, ReorderJokers, is_legal,
)
from balatro_ai_v2.solver.joker_catalog import get_joker_profile
from balatro_ai_v2.solver.build_strategy import planet_hand
from balatro_ai_v2.solver.policy import PublicHistoryStep
from balatro_ai_v2.solver.public_scoring import _HAND_LEVEL_GAINS, _prepare_score_context, _score_play_prepared
from balatro_ai_v2.solver.public_state import DeckCardCount, Phase, PublicBlind, PublicItem, PublicJokerRuntime, PublicObservation

_SUIT_BOSSES = {'The Club': 'C', 'The Goad': 'S', 'The Head': 'H', 'The Window': 'D'}
_STATIC_BOSSES = {*_SUIT_BOSSES, 'The Plant'}


def _project_static_card(card, observation, blind):
    """Installed Card:is_suit(..., true)/is_face(true), for vanilla cards."""
    if blind is None or blind.name not in _STATIC_BOSSES:
        return card
    active = {j.key for j in observation.jokers if isinstance(j, PublicItem) and not j.debuffed}
    if blind.name == 'The Plant':
        debuffed = 'j_pareidolia' in active or (card.enhancement != 'STONE' and card.rank in {'J', 'Q', 'K'})
    else:
        suit = _SUIT_BOSSES[blind.name]
        debuffed = card.enhancement != 'STONE' and (
            card.enhancement == 'WILD' or card.suit == suit
            or ('j_smeared' in active and (card.suit in {'H', 'D'}) == (suit in {'H', 'D'})))
    return replace(card, debuffed=debuffed)


@dataclass(frozen=True, slots=True)
class ShopChoice:
    action: PublicAction
    reason: str
    diagnostics: dict[str, float | int | str]


def _hand_size_delta(item: PublicItem) -> int | None:
    if item.key == 'j_turtle_bean':
        return item.runtime.current_hand_size_bonus if item.runtime is not None else None
    return {'j_stuntman': -2, 'j_juggler': 1, 'j_merry_andy': -1}.get(item.key, 0)


def _owned_fingerprints(jokers: tuple) -> tuple:
    # Owned costs and runtime can change on purchase. Preserve occurrence order;
    # never infer which identical-key Joker moved from an unordered multiset.
    return tuple((j.key, j.edition, j.eternal, j.perishable_rounds, j.rental)
                 if isinstance(j, PublicItem) else None for j in jokers)


class ShopSearch:
    def __init__(self, samples: int = 6, max_rerolls: int = 2, evaluate_planets: bool = False, project_next_boss: bool = False,
                 evaluate_blueprint_placement: bool = False, prioritize_all_jokers: bool = True,
                 survival_rerolls: int | None = None, project_static_bosses: bool = False):
        if not 1 <= samples <= 12 or not 0 <= max_rerolls <= 5:
            raise ValueError('shop search budgets must be bounded')
        self.samples = samples
        self.max_rerolls = max_rerolls
        if survival_rerolls is not None and (isinstance(survival_rerolls, bool)
                or not isinstance(survival_rerolls, int) or not max_rerolls <= survival_rerolls <= 5):
            raise ValueError('survival_rerolls must be an integer between max_rerolls and five')
        self.survival_rerolls = survival_rerolls
        if not isinstance(evaluate_planets, bool):
            raise ValueError('evaluate_planets must be boolean')
        self.evaluate_planets = evaluate_planets
        if not isinstance(project_next_boss, bool):
            raise ValueError('project_next_boss must be boolean')
        self.project_next_boss = project_next_boss
        if not isinstance(project_static_bosses, bool) or (project_static_bosses and not project_next_boss):
            raise ValueError('static boss projection requires project_next_boss')
        self.project_static_bosses = project_static_bosses
        self._pending: tuple[int, PublicItem] | None = None
        if not isinstance(evaluate_blueprint_placement, bool):
            raise ValueError('evaluate_blueprint_placement must be boolean')
        self.evaluate_blueprint_placement = evaluate_blueprint_placement
        if not isinstance(prioritize_all_jokers, bool):
            raise ValueError('prioritize_all_jokers must be boolean')
        self.prioritize_all_jokers = prioritize_all_jokers
        self._blueprint_purchase = None
        self._blueprint_order = None

    def choose(self, observation: PublicObservation, baseline_action: PublicAction,
               history: tuple[PublicHistoryStep, ...] = ()) -> ShopChoice | None:
        if observation.phase != Phase.SHOP:
            self._pending = None
            self._blueprint_purchase = None
            self._blueprint_order = None
            return None
        if self._blueprint_order is not None:
            round_no, expected, index, destination, budget = self._blueprint_order
            self._blueprint_order = None
            if round_no != observation.round_no or _owned_fingerprints(observation.jokers) != expected:
                return None
            if index > destination and budget > 0:
                order = list(range(len(expected)))
                order[index - 1], order[index] = order[index], order[index - 1]
                action = ReorderJokers(tuple(JokerSlot(i) for i in order))
                if not is_legal(observation, action):
                    return None
                self._blueprint_order = (round_no, tuple(expected[i] for i in order), index - 1, destination, budget - 1)
                return ShopChoice(action, 'Move purchased Blueprint to its evaluated position.',
                                  {'blueprint_destination': destination, 'placement_swaps_remaining': budget - 1})
        if self._blueprint_purchase is not None:
            round_no, expected, desired, destination = self._blueprint_purchase
            self._blueprint_purchase = None
            if round_no != observation.round_no or _owned_fingerprints(observation.jokers) != expected:
                return None
            for i, offer in enumerate(observation.shop):
                action = BuyShopCard(ShopSlot(i))
                if offer == desired and is_legal(observation, action):
                    self._arm_blueprint_order(observation, offer, destination)
                    return ShopChoice(action, 'Complete the revalidated Blueprint upgrade.', {'planned_purchase': 1})
            return None
        if self._pending is not None:
            round_no, desired = self._pending
            self._pending = None
            if round_no == observation.round_no:
                for i, offer in enumerate(observation.shop):
                    action = BuyShopCard(ShopSlot(i))
                    if offer == desired and is_legal(observation, action):
                        return ShopChoice(action, 'Complete the revalidated joker upgrade.', {'planned_purchase': 1})
        permitted = (LeaveShop, BuyShopCard, RerollShop, SellJoker)
        if self.evaluate_blueprint_placement:
            permitted += (BuyPack, BuyVoucher)
        if not isinstance(baseline_action, permitted):
            return None
        priority_screen = self.evaluate_blueprint_placement and isinstance(baseline_action, (BuyPack, BuyVoucher))
        if isinstance(baseline_action, BuyShopCard):
            offer = observation.shop[baseline_action.card.value]
            if not isinstance(offer, PublicItem) or offer.kind != 'JOKER':
                if not self.evaluate_blueprint_placement:
                    return None
                priority_screen = True
        if not observation.full_deck or not 1 <= observation.hand_limit <= 12 or any(not isinstance(j, PublicItem) for j in observation.jokers):
            return None
        hands = self._hands(observation)
        projected_blind, projection_reason = self._next_blind_projection(observation)
        needle = projected_blind is not None and projected_blind.name == 'The Needle'

        def components(candidate):
            if projected_blind is None:
                return self._capacity_components(candidate, hands)
            return self._capacity_components(candidate, hands, projected_blind)

        def aggregate(first, repeated, final):
            return first if needle else .5 * first + .35 * repeated + .15 * final

        current_first, current_repeat, current_final = components(observation)
        current = aggregate(current_first, current_repeat, current_final)
        upcoming = [b.score for b in sorted(observation.blinds, key=lambda b: {'SMALL': 0, 'BIG': 1, 'BOSS': 2}.get(b.kind, 3))
                    if b.status in {'SELECT', 'UPCOMING'}]
        target = float(upcoming[0] if upcoming else max((b.score for b in observation.blinds), default=300) * 1.5)
        # Optimistic continuation bonuses must not lock up survival cash when
        # ordinary first-hand capacity is below the next blind's pace.
        weak = min(current_first, current) * (1 if needle else 3) < target
        reroll_limit = self.survival_rerolls if weak and self.survival_rerolls is not None else self.max_rerolls
        reserve = 2 if weak else min(25, 8 + 3 * max(0, observation.ante - 1))
        diagnostics = {'current_capacity': current, 'next_blind_target': target,
                       'reserve': reserve, 'samples': self.samples,
                       'current_first_hand': current_first, 'current_repeat_hand': current_repeat,
                       'current_final_hand': current_final,
                       'continuation_assumption': '50% first / 35% same-family repeat / 15% final; no intervening discards; Green Joker +1 per prior play'}
        if self.survival_rerolls is not None:
            diagnostics.update(reroll_limit=reroll_limit, below_forecast_pace=weak)
        if self.project_next_boss:
            diagnostics.update(boss_projection=projection_reason,
                               projected_hand_budget=1 if needle else 4,
                               survival_capacity_multiplier=1 if needle else 3)
            if needle:
                diagnostics['continuation_assumption'] = 'Needle: first and only hand; no continuation bonus'
        best = None
        for i, offer in enumerate(observation.shop):
            if not isinstance(offer, PublicItem) or offer.kind != 'JOKER' or offer.buy_cost is None:
                continue
            if priority_screen and not self.prioritize_all_jokers and offer.key != 'j_blueprint':
                continue
            try:
                profile = get_joker_profile(offer.key)
            except KeyError:
                continue
            offered_size_delta = _hand_size_delta(offer)
            if offered_size_delta is None:
                continue
            buy = BuyShopCard(ShopSlot(i))
            options = [(None, observation)] if is_legal(observation, buy) else []
            # Only consider removing an owned card when capacity is full. A
            # Negative joker takes its extra slot with it when sold.
            if len(observation.jokers) >= observation.joker_limit and offer.edition != 'NEGATIVE':
                for old_i, old in enumerate(observation.jokers):
                    sale = SellJoker(JokerSlot(old_i))
                    if old.eternal or old.edition == 'NEGATIVE' or not is_legal(observation, sale):
                        continue
                    removed_size_delta = _hand_size_delta(old)
                    if removed_size_delta is None:
                        continue
                    after_sale = replace(observation, money=observation.money + (old.sell_cost or 0),
                                         hand_limit=observation.hand_limit - removed_size_delta,
                                         jokers=observation.jokers[:old_i] + observation.jokers[old_i + 1:])
                    if is_legal(after_sale, buy):
                        options.append((sale, after_sale))
            for sale, before_buy in options:
                cash_left = before_buy.money - offer.buy_cost
                if cash_left < reserve and offer.buy_cost > 0:
                    continue
                candidate_hand_limit = before_buy.hand_limit + offered_size_delta
                if not 1 <= candidate_hand_limit <= 12:
                    continue
                candidate = replace(before_buy, money=cash_left,
                                    hand_limit=candidate_hand_limit,
                                    jokers=before_buy.jokers + (offer,),
                                    joker_limit=before_buy.joker_limit + int(offer.edition == 'NEGATIVE'))
                first, repeated, final = components(candidate)
                destination = None
                if self.evaluate_blueprint_placement and offer.key == 'j_blueprint':
                    destination = len(before_buy.jokers)
                    for position in range(len(before_buy.jokers)):
                        placed = replace(candidate, jokers=before_buy.jokers[:position] + (offer,) + before_buy.jokers[position:])
                        alternate = components(placed)
                        if aggregate(*alternate) > aggregate(first, repeated, final):
                            first, repeated, final = alternate
                            destination = position
                capacity = aggregate(first, repeated, final)
                gain = log1p(capacity) - log1p(current)
                # Small explicit future utility; unknown/non-scoring cards
                # cannot win merely through rarity or a generic tier score.
                future = 0.08 if profile.role == 'scaling' and observation.ante <= 4 else 0.0
                if profile.role == 'economy' and not weak and observation.ante <= 4:
                    future = 0.06
                if sale is not None:
                    old = observation.jokers[sale.joker.value]
                    try:
                        old_role = get_joker_profile(old.key).role
                    except KeyError:
                        old_role = 'utility'
                    if old_role in {'scaling', 'economy'}:
                        future -= 0.08
                opportunity = 0.025 if offer.edition == 'NEGATIVE' else 0.055
                cash_penalty = (offer.buy_cost - ((observation.jokers[sale.joker.value].sell_cost or 0) if sale else 0)) * (0.004 if weak else 0.008)
                utility = gain + future - opportunity - cash_penalty
                if utility > 0.025 and (best is None or utility > best[0]):
                    best = (utility, sale or buy, offer, capacity, first, repeated, final, destination)
        planet_screen = self.evaluate_planets and isinstance(baseline_action, (LeaveShop, RerollShop))
        if planet_screen:
            evaluated = 0
            reasons = []
            best_planet_gain = None
            for i, offer in enumerate(observation.shop):
                if not isinstance(offer, PublicItem) or offer.kind != 'PLANET':
                    continue
                family = planet_hand(offer.key)
                buy = BuyShopCard(ShopSlot(i), BuyMode.USE)
                if 'v_observatory' in observation.used_vouchers:
                    reasons.append(f'{offer.key}: Observatory hold/use tradeoff excluded')
                    continue
                if family not in _HAND_LEVEL_GAINS or not any(s.name == family for s in observation.hand_stats):
                    reasons.append(f'{offer.key}: unsupported hand family')
                    continue
                if not is_legal(observation, buy) or offer.buy_cost is None:
                    reasons.append(f'{offer.key}: buy-and-use is not legal or affordable')
                    continue
                if observation.money - offer.buy_cost < reserve and offer.buy_cost > 0:
                    reasons.append(f'{offer.key}: protected cash reserve')
                    continue
                chip_gain, mult_gain = _HAND_LEVEL_GAINS[family]
                candidate = replace(observation, money=observation.money - offer.buy_cost,
                                    hand_stats=tuple(replace(stat, level=stat.level + 1,
                                                             chips=stat.chips + chip_gain,
                                                             mult=stat.mult + mult_gain)
                                                     if stat.name == family else stat for stat in observation.hand_stats))
                first, repeated, final = components(candidate)
                capacity = aggregate(first, repeated, final)
                utility = log1p(capacity) - log1p(current) - offer.buy_cost * (0.004 if weak else 0.008)
                evaluated += 1
                best_planet_gain = max(best_planet_gain if best_planet_gain is not None else utility, utility)
                reasons.append(f'{offer.key}: utility {utility:.6f}')
                if utility > 0.025 and (best is None or utility > best[0]):
                    best = (utility, buy, offer, capacity, first, repeated, final, None)
            diagnostics.update(planet_candidates_evaluated=evaluated,
                               planet_screen='; '.join(reasons) or 'no planet offers')
            if best_planet_gain is not None:
                diagnostics['best_planet_utility'] = best_planet_gain
        if best is not None:
            utility, action, offer, capacity, first, repeated, final, destination = best
            if destination is not None:
                diagnostics['blueprint_destination'] = destination
                if isinstance(action, SellJoker):
                    after_sale = observation.jokers[:action.joker.value] + observation.jokers[action.joker.value + 1:]
                    self._blueprint_purchase = (observation.round_no, _owned_fingerprints(after_sale), offer, destination)
                else:
                    self._arm_blueprint_order(observation, offer, destination)
            elif isinstance(action, SellJoker):
                self._pending = (observation.round_no, offer)
            return ShopChoice(action, f'Improve sampled scoring capacity with {offer.label or offer.key}.',
                              {**diagnostics, 'candidate_capacity': capacity, 'utility_gain': utility,
                               'candidate_first_hand': first, 'candidate_repeat_hand': repeated,
                               'candidate_final_hand': final,
                               ('desired_planet' if offer.kind == 'PLANET' else 'desired_joker'): offer.key})
        if priority_screen:
            return None
        rerolls = sum(isinstance(step.action, RerollShop) for step in history
                      if step.before.round_no == observation.round_no)
        # Cost growth also bounds rerolls when callers provide no history.
        cost = observation.round.reroll_cost
        if (weak and rerolls < reroll_limit and cost < 5 + reroll_limit
                and observation.money - cost >= reserve + 6
                and is_legal(observation, RerollShop())):
            return ShopChoice(RerollShop(), 'Search for a scoring upgrade while the build is below next-blind pace.', diagnostics)
        if isinstance(baseline_action, RerollShop) and (rerolls >= reroll_limit or cost >= 5 + reroll_limit):
            return ShopChoice(LeaveShop(), 'Stop after the bounded shop reroll budget.', diagnostics)
        if planet_screen:
            return ShopChoice(baseline_action, 'Preserve baseline after scoring available planets.', diagnostics)
        if self.project_next_boss:
            return ShopChoice(baseline_action, 'Preserve baseline after checking the next-blind projection.', diagnostics)
        # Respect an existing conservative fallback instead of suppressing
        # strategy purchases that the immediate scorer cannot value.
        return None

    def _arm_blueprint_order(self, observation: PublicObservation, offer: PublicItem, destination: int) -> None:
        index = len(observation.jokers)
        self._blueprint_order = (observation.round_no, _owned_fingerprints(observation.jokers + (offer,)),
                                 index, destination, index)

    def _next_blind_projection(self, observation: PublicObservation) -> tuple[PublicBlind | None, str]:
        if not self.project_next_boss:
            return None, 'disabled'
        upcoming = sorted((b for b in observation.blinds if b.status in {'SELECT', 'UPCOMING'}),
                          key=lambda b: {'SMALL': 0, 'BIG': 1, 'BOSS': 2}.get(b.kind, 3))
        if not upcoming:
            return None, 'control fallback: no public next blind'
        blind = upcoming[0]
        if blind.kind == 'BOSS':
            supported = {'The Needle', 'The Flint'} | (_STATIC_BOSSES if self.project_static_bosses else set())
            if blind.name not in supported:
                return None, f'control fallback: unsupported {blind.name}'
            interactions = [j.key for j in (*observation.jokers, *observation.shop)
                            if isinstance(j, PublicItem) and j.key in
                            ({'j_chicot', 'j_burglar', 'j_luchador', 'j_ceremonial'} if blind.name in _STATIC_BOSSES else {'j_chicot', 'j_burglar'})]
            if interactions:
                return None, 'control fallback: activation interaction ' + ','.join(sorted(set(interactions)))
        elif blind.kind not in {'SMALL', 'BIG'}:
            return None, f'control fallback: unsupported blind kind {blind.kind}'
        return replace(blind, status='CURRENT', disabled=False), f'projected {blind.name}'

    def _hands(self, observation: PublicObservation) -> tuple[tuple, ...]:
        deck = [entry.card for entry in observation.full_deck for _ in range(entry.count)]
        # Fixed nonce intentionally independent of game seed, private order,
        # candidate identity, and offered loadout: common random numbers.
        rng = Random(730241)
        size = min(len(deck), 12)
        return tuple(tuple(rng.sample(deck, size)) for _ in range(self.samples))

    @staticmethod
    def _capacity_components(observation: PublicObservation, hands: tuple[tuple, ...], projected_blind: PublicBlind | None = None) -> tuple[float, float, float]:
        results = []
        for stream in hands:
            hand = tuple(_project_static_card(card, observation, projected_blind)
                         for card in stream[:observation.hand_limit])
            remaining = Counter()
            for entry in observation.full_deck:
                remaining[_project_static_card(entry.card, observation, projected_blind)] += entry.count
            remaining.subtract(hand)
            remaining_deck = tuple(DeckCardCount(card, count) for card, count in remaining.items() if count > 0)
            synthetic = replace(observation, phase=Phase.SELECTING_HAND, hand=hand,
                                remaining_deck=remaining_deck, draw_count=sum(entry.count for entry in remaining_deck),
                                required_hand_slots=(), selection_limit=min(5, len(hand)),
                                blinds=((projected_blind,) if projected_blind is not None else
                                        tuple(replace(b, status='UPCOMING', disabled=False) for b in observation.blinds)),
                                round=replace(observation.round, chips=0, hands_left=1 if projected_blind is not None and projected_blind.name == 'The Needle' else 4, hands_played=0,
                                              discards_left=3, discards_used=0),
                                hand_stats=tuple(replace(h, played_this_round=0) for h in observation.hand_stats))
            best = 0.0
            best_selection = ()
            best_family = None
            context = _prepare_score_context(synthetic)
            stats = {stat.name: stat for stat in synthetic.hand_stats}
            for count in range(1, min(5, len(hand)) + 1):
                for chosen in combinations(range(len(hand)), count):
                    selection = tuple(HandSlot(i) for i in chosen)
                    try:
                        score, family = _score_play_prepared(synthetic, selection, stats, context)
                    except (ValueError, KeyError, NotImplementedError):
                        continue
                    if float(score) > best:
                        best, best_selection, best_family = float(score), selection, family
            if projected_blind is not None and projected_blind.name == 'The Needle':
                results.append((best, best, best))
                continue
            continuation = []
            for prior_plays in (1, 3):
                # A transparent counterfactual: repeat the first best family
                # with the same synthetic cards, without any intervening
                # discard. This is capacity, not a simulated draw trajectory.
                projected_jokers = []
                for joker in synthetic.jokers:
                    if joker.key == 'j_green_joker':
                        runtime = joker.runtime or PublicJokerRuntime()
                        joker = replace(joker, runtime=replace(runtime, current_mult=(runtime.current_mult or 0) + prior_plays))
                    projected_jokers.append(joker)
                followup = replace(synthetic, jokers=tuple(projected_jokers),
                                   round=replace(synthetic.round, hands_played=prior_plays, hands_left=4-prior_plays),
                                   hand_stats=tuple(replace(stat, played=stat.played + prior_plays,
                                                           played_this_round=prior_plays)
                                                    if stat.name == best_family else stat for stat in synthetic.hand_stats))
                try:
                    projected, _ = _score_play_prepared(followup, best_selection,
                                                       {stat.name: stat for stat in followup.hand_stats},
                                                       _prepare_score_context(followup)) if best_selection else (0, '')
                except (ValueError, KeyError, NotImplementedError):
                    projected = best
                continuation.append(float(projected))
            results.append((best, *continuation))
        return tuple(sum(row[i] for row in results) / max(len(results), 1) for i in range(3))
