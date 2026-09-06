"""Integrated public build-first policy. Values are heuristics, not probabilities."""
from dataclasses import replace
from math import log1p

from balatro_ai_v2.solver.actions import (
    BuyPack, BuyShopCard, BuyVoucher, ChoosePackCard, DiscardCards, JokerSlot,
    LeaveShop, PlayCards, RerollShop, SellJoker, ShopSlot, SkipBlind, SelectBlind,
    SkipPack, UseConsumable, is_legal, iter_legal_actions,
)
from balatro_ai_v2.solver.baselines import (
    _consumable_value, _play_score, _with_history_derived_joker_runtime,
)
from balatro_ai_v2.solver.build_intent import derive_intent, joker_value, planet_value
from balatro_ai_v2.solver.build_strategy import infer_build_plan
from balatro_ai_v2.solver.public_scoring import _scoring_cards
from balatro_ai_v2.solver.public_state import Phase, PublicItem, VisiblePlayingCard
from balatro_ai_v2.solver.shop_search import ShopSearch, _hand_size_delta, _owned_fingerprints
from .strategic import SearchPolicy, StrategicPolicy


class BuildFirstPolicy(SearchPolicy):
    def __init__(self):
        super().__init__(model_green_joker=True, project_next_boss=True,
                         optimize_order=True, model_hidden_jokers=True,
                         evaluate_blueprint_placement=True, prioritize_all_jokers=False,
                         model_static_debuffs=True, preserve_green_plays=True,
                         project_static_bosses=True)
        self.probe = ShopSearch(samples=3, project_next_boss=True, project_static_bosses=True)
        self.pending_purchase = None

    def select(self, observation):
        enriched = _with_history_derived_joker_runtime(observation, tuple(self.history))
        intent = derive_intent(enriched)
        actions = tuple(iter_legal_actions(enriched))
        # Numerical tactics remain a proposal, not a later override of intent.
        if observation.phase == Phase.SELECTING_HAND:
            action, reason, diagnostics = super().select(observation)
            action = self._growth_play(enriched, intent, actions, action)
        else:
            action, reason, diagnostics = StrategicPolicy.select(self, observation)
            if observation.phase == Phase.SHOP:
                action = self._shop(enriched, intent, actions, action)
            elif observation.phase == Phase.PACK:
                choices = [a for a in actions if isinstance(a, ChoosePackCard)]
                if choices:
                    action = max(choices, key=lambda a: self._item_value(
                        enriched.opened_pack[a.card.value], enriched, intent, a.targets))
                    if self._item_value(enriched.opened_pack[action.card.value], enriched,
                                        intent, action.targets) <= 0 and SkipPack() in actions:
                        action = SkipPack()
            elif isinstance(action, SkipBlind) and intent.growth_keys and SelectBlind() in actions:
                action = SelectBlind()
        if observation.phase != Phase.SHOP:
            self.pending_purchase = None
        if not is_legal(observation, action):
            raise ValueError('build-first selected an illegal action')
        return action, f'Build-first selected {type(action).__name__} for {intent.family}.', {
            **diagnostics, 'build_family': intent.family, 'primary_hand': intent.primary_hand,
            'growth_keys': ','.join(intent.growth_keys), 'valuation': 'ordinal_heuristic',
        }

    def _item_value(self, item, obs, intent, targets=()):
        if isinstance(item, VisiblePlayingCard):
            # Avoid random deck dilution; growth/enhancement gives a reason to add.
            return (12 if 'j_hologram' in intent.growth_keys else 0) + (
                8 if item.seal or item.enhancement or item.edition else 0)
        if not isinstance(item, PublicItem):
            return 0
        if item.kind == 'JOKER':
            return joker_value(item, obs, intent)
        if item.kind == 'PLANET':
            return planet_value(item.key, intent)
        build = replace(infer_build_plan(obs), primary_hand=intent.primary_hand)
        return _consumable_value(obs, item, tuple(t.value for t in targets), build)

    def _shop(self, obs, intent, actions, fallback):
        if self.pending_purchase is not None:
            round_no, fingerprint, offer = self.pending_purchase
            self.pending_purchase = None
            if round_no == obs.round_no and fingerprint == _owned_fingerprints(obs.jokers):
                for i, item in enumerate(obs.shop):
                    buy = BuyShopCard(ShopSlot(i))
                    if item == offer and buy in actions:
                        return buy
        # Use supported consumables with the same hand commitment as purchases.
        uses = [a for a in actions if isinstance(a, UseConsumable)
                and self._item_value(obs.consumables[a.consumable.value], obs, intent, a.targets) > 0]
        if uses:
            return max(uses, key=lambda a: self._item_value(
                obs.consumables[a.consumable.value], obs, intent, a.targets))
        if not obs.full_deck or any(not isinstance(j, PublicItem) for j in obs.jokers):
            return fallback
        if not 1 <= obs.hand_limit <= 12:
            return fallback
        hands = self.probe._hands(obs)
        blind, _ = self.probe._next_blind_projection(obs)
        def capacity(candidate):
            values = self.probe._capacity_components(candidate, hands, blind)
            return values[0] if blind and blind.name == 'The Needle' else min(values[0], sum(values) / 3)
        current = capacity(obs)
        upcoming = sorted((b for b in obs.blinds if b.status in {'SELECT', 'UPCOMING'}),
                          key=lambda b: {'SMALL': 0, 'BIG': 1, 'BOSS': 2}.get(b.kind, 3))
        target = upcoming[0].score if upcoming else 300
        budget = 1 if blind and blind.name == 'The Needle' else 3
        weak = current * budget < target
        # Early tempo takes priority; once stable, build toward full interest.
        reserve = 0 if weak else min(25, max(5, obs.money - 8))
        best = None
        for i, offer in enumerate(obs.shop):
            if not isinstance(offer, PublicItem) or offer.kind != 'JOKER' or offer.buy_cost is None:
                continue
            buy = BuyShopCard(ShopSlot(i))
            variants = [(None, obs, 0.0)] if buy in actions else []
            if len(obs.jokers) >= obs.joker_limit and offer.edition != 'NEGATIVE':
                for j, owned in enumerate(obs.jokers):
                    sale = SellJoker(JokerSlot(j))
                    delta = _hand_size_delta(owned)
                    if sale not in actions or owned.edition == 'NEGATIVE' or delta is None:
                        continue
                    remaining = obs.jokers[:j] + obs.jokers[j + 1:]
                    candidate = replace(obs, jokers=remaining, money=obs.money + (owned.sell_cost or 0),
                                        hand_limit=obs.hand_limit - delta)
                    if is_legal(candidate, buy):
                        variants.append((sale, candidate, joker_value(owned, candidate, derive_intent(candidate))))
            for sale, before, old_value in variants:
                cash = before.money - offer.buy_cost
                delta = _hand_size_delta(offer)
                if cash < reserve or delta is None or not 1 <= before.hand_limit + delta <= 12:
                    continue
                candidate = replace(before, jokers=before.jokers + (offer,), money=cash,
                                    hand_limit=before.hand_limit + delta,
                                    joker_limit=before.joker_limit + int(offer.edition == 'NEGATIVE'))
                future_capacity = capacity(candidate)
                # Do not exchange necessary present power for hypothetical growth.
                floor = current if weak else min(current * .75, target / budget * 1.2)
                if future_capacity < floor:
                    continue
                gain = (joker_value(offer, before, derive_intent(before)) - old_value
                        + 35 * (log1p(future_capacity) - log1p(current))
                        - 2 * (offer.buy_cost - (before.money - obs.money)))
                if gain > 12 and (best is None or gain > best[0]):
                    best = (gain, sale or buy, offer, before)
        if best:
            _, action, offer, before = best
            if isinstance(action, SellJoker):
                self.pending_purchase = (obs.round_no, _owned_fingerprints(before.jokers), offer)
            return action
        # Resource investment follows the same intent, not a separate hand vote.
        purchases = []
        for action in actions:
            if isinstance(action, BuyShopCard):
                item = obs.shop[action.card.value]
                if isinstance(item, PublicItem) and item.kind != 'JOKER':
                    value = self._item_value(item, obs, intent)
                    if value > 0 and obs.money - (item.buy_cost or 0) >= reserve:
                        purchases.append((value - 3 * (item.buy_cost or 0), action))
            elif isinstance(action, BuyVoucher):
                item = obs.vouchers[action.voucher.value]
                value = {'v_grabber': 65, 'v_nacho_tong': 65, 'v_paint_brush': 65,
                         'v_palette': 65, 'v_telescope': 55, 'v_seed_money': 45,
                         'v_money_tree': 45, 'v_clearance_sale': 40,
                         'v_liquidation': 45, 'v_reroll_surplus': 35}.get(item.key, 0)
                if obs.money - (item.buy_cost or 0) >= reserve:
                    purchases.append((value - 3 * (item.buy_cost or 0), action))
            elif isinstance(action, BuyPack):
                item = obs.packs[action.pack.value]
                key = item.key
                value = 0
                if 'buffoon' in key:
                    value = 65 if len(obs.jokers) < obs.joker_limit or not intent.growth_keys else 30
                elif 'celestial' in key:
                    value = 40 if intent.family == 'planet' or 'j_constellation' in intent.growth_keys else 20
                elif 'arcana' in key:
                    value = 35
                elif 'standard' in key and 'j_hologram' in intent.growth_keys:
                    value = 40
                elif 'spectral' in key and len(obs.jokers) < 3:
                    value = 25
                if value and obs.money - (item.buy_cost or 0) >= reserve:
                    purchases.append((value - 3 * (item.buy_cost or 0), action))
        if purchases:
            value, action = max(purchases, key=lambda pair: pair[0])
            if value > 0:
                return action
        rerolls = 0
        for step in reversed(self.history):
            if step.before.phase != Phase.SHOP or step.before.round_no != obs.round_no:
                break
            rerolls += isinstance(step.action, RerollShop)
        if RerollShop() in actions and rerolls < (4 if weak else 2):
            if obs.round.reroll_cost == 0 or obs.money - obs.round.reroll_cost >= reserve + 8:
                return RerollShop()
        return LeaveShop()

    def _growth_play(self, obs, intent, actions, fallback):
        if not intent.growth_keys or not isinstance(fallback, (PlayCards, DiscardCards)):
            return fallback
        if any(not isinstance(c, VisiblePlayingCard) for c in obs.hand):
            return fallback
        blind = next((b for b in obs.blinds if b.status == 'CURRENT'), None)
        # Do not substitute growth preferences into boss recovery or forced hands.
        if blind is None or (blind.kind == 'BOSS' and not blind.disabled) or obs.required_hand_slots:
            return fallback
        plays = [a for a in actions if isinstance(a, PlayCards)]
        if not plays:
            return fallback
        scored = [(a, *_play_score(obs, a.cards)) for a in plays]
        best_score = max(s for _, s, _ in scored)
        remaining = max(0, blind.score - obs.round.chips)
        if best_score >= remaining or obs.round.hands_left <= 1:
            return fallback
        floor = max(best_score * .75, remaining / max(1, obs.round.hands_left) * 1.2)
        eligible = []
        for action, score, hand in scored:
            if score < floor:
                continue
            cards = tuple(obs.hand[s.value] for s in action.cards)
            scoring = _scoring_cards(cards, hand)
            growth = 0
            for key in intent.growth_keys:
                if key == 'j_green_joker': growth += 1
                elif key == 'j_supernova': growth += hand == intent.primary_hand
                elif key == 'j_square': growth += len(cards) == 4
                elif key == 'j_trousers': growth += hand in {'Two Pair', 'Full House', 'Flush House'}
                elif key == 'j_runner': growth += hand in {'Straight', 'Straight Flush'}
                elif key == 'j_wee': growth += sum(c.rank == '2' and not c.debuffed for c in scoring)
                elif key == 'j_ride_the_bus':
                    growth += -10 if any(c.rank in {'J', 'Q', 'K'} and not c.debuffed for c in scoring) else 1
            eligible.append((growth, score, action))
        if eligible:
            growth, _, action = max(eligible, key=lambda row: (row[0], row[1]))
            if growth > 0:
                return action
        return fallback
