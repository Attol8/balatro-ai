"""A deliberately approximate, public-information baseline for real runs.

This is a benchmark opponent, not a parity scorer or a trained strategy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Protocol

from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.balatrobot.adapter import card_to_fast_id
from balatro_ai_v2.fast.cards import chips as card_chips
from balatro_ai_v2.fast.hand import BASE_CHIPS, BASE_MULT, HAND_KIND_NAMES, FastScore, score_cards_with_levels
from balatro_ai_v2.fast.jokers import Joker, ScoreContext, apply_additive_jokers


class LiveAction(Protocol):
    def to_balatrobot_rpc(self) -> tuple[str, dict]: ...


@dataclass(frozen=True)
class Decision:
    action: LiveAction
    reason: str
    predicted_score: float | None = None
    limitations: tuple[str, ...] = ()
    diagnostics: dict = field(default_factory=dict)


PLANETS = dict(zip(
    ('c_pluto', 'c_mercury', 'c_uranus', 'c_venus', 'c_saturn', 'c_jupiter',
     'c_earth', 'c_mars', 'c_neptune', 'c_planet_x', 'c_ceres', 'c_eris'), HAND_KIND_NAMES))
TARGETS = {'c_heirophant': 2, 'c_empress': 2, 'c_magician': 2,
           'c_chariot': 1, 'c_devil': 1, 'c_justice': 1, 'c_aura': 1}
# Rough acquisition utility. Unlisted jokers remain available at a low priority.
JOKER_VALUE = {'j_joker': 3, 'j_jolly': 5, 'j_sly': 4, 'j_half': 7,
               'j_abstract': 8, 'j_supernova': 8, 'j_green_joker': 7,
               'j_blue_joker': 7, 'j_banner': 7, 'j_mystic_summit': 6,
               'j_cavendish': 18, 'j_gros_michel': 10, 'j_stuntman': 12,
               'j_blueprint': 20, 'j_brainstorm': 20, 'j_baron': 10,
               'j_triboulet': 20, 'j_hanging_chad': 13, 'j_photograph': 11,
               'j_constellation': 12, 'j_hologram': 13, 'j_card_sharp': 14,
               'j_bull': 8, 'j_bootstraps': 7, 'j_egg': 2, 'j_credit_card': 1}
APPROX = ('Approximate scoring: unsupported joker interactions, boss effects, and random triggers are not simulated.',)


def _cards(state: dict, area: str) -> list[dict]:
    return (state.get(area) or {}).get('cards') or []


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _blind(state: dict) -> dict:
    return next((b for b in (state.get('blinds') or {}).values()
                 if isinstance(b, dict) and b.get('status') == 'CURRENT'), {})


def _utility(card: dict) -> float:
    modifier = card.get('modifier') or {}
    return (JOKER_VALUE.get(card.get('key'), 4)
            + {'FOIL': 3, 'HOLO': 4, 'HOLOGRAPHIC': 4, 'POLYCHROME': 6,
               'NEGATIVE': 8}.get(modifier.get('edition'), 0)
            - (3 if modifier.get('rental') else 0))


class BaselinePolicy:
    """Stateless deterministic decisions, with bounded shopping and discarding."""

    def choose(self, state: dict) -> Decision:
        phase = state.get('state')
        transitions = {'BLIND_SELECT': ActionKind.SELECT_BLIND,
                       'ROUND_EVAL': ActionKind.CASH_OUT}
        if phase in transitions:
            return Decision(GameAction(transitions[phase]), 'Advance the run.')
        if phase in {'SHOP', 'SELECTING_HAND'}:
            for index, card in enumerate(_cards(state, 'consumables')):
                targets = self._consumable_targets(card, state)
                if targets is not None:
                    return Decision(GameAction(ActionKind.USE_CONSUMABLE, targets, index),
                                    'Use an available supported consumable.')
        if phase == 'SELECTING_HAND':
            return self._hand(state)
        if phase == 'SHOP':
            return self._shop(state)
        if phase in {'SMODS_BOOSTER_OPENED', 'TAROT_PACK', 'PLANET_PACK',
                     'SPECTRAL_PACK', 'STANDARD_PACK', 'BUFFOON_PACK'}:
            return self._pack(state)
        raise ValueError(f'No decision for non-playable state {phase!r}')

    def _consumable_targets(self, card: dict, state: dict) -> tuple[int, ...] | None:
        key = card.get('key')
        if key in PLANETS or key == 'c_black_hole':
            return ()
        if key == 'c_temperance':
            return () if _cards(state, 'jokers') else None
        if key == 'c_hermit':
            return () if _number(state.get('money')) >= 8 else None
        if key in TARGETS:
            if state.get('state') == 'SHOP':
                return None
            forced = {i for i, target in enumerate(_cards(state, 'hand'))
                      if (target.get('state') or {}).get('forced_selection')}
            candidates = []
            for i, target in enumerate(_cards(state, 'hand')):
                if (target.get('state') or {}).get('hidden'):
                    continue
                modifier = target.get('modifier') or {}
                occupied = modifier.get('edition') if key == 'c_aura' else modifier.get('enhancement')
                if occupied:
                    continue
                try:
                    strength = card_chips(card_to_fast_id(target))
                except ValueError:
                    continue
                candidates.append((strength, i))
            if candidates:
                available = {i for _, i in candidates}
                if not forced.issubset(available) or len(forced) > TARGETS[key]:
                    return None
                chosen = sorted(forced)
                chosen.extend(i for _, i in sorted(candidates, reverse=True) if i not in forced)
                return tuple(chosen[:TARGETS[key]])
        return None

    def _hand(self, state: dict) -> Decision:
        hand = _cards(state, 'hand')
        if not hand:
            raise ValueError('SELECTING_HAND has no cards')
        round_state = state.get('round') or {}
        limit = min(5, int((state.get('hand') or {}).get('highlighted_limit', 5)), len(hand))
        forced = {i for i, c in enumerate(hand) if (c.get('state') or {}).get('forced_selection')}
        blind = _blind(state)
        boss = '' if blind.get('disabled') else blind.get('name', '').lower()
        levels = tuple(int((state.get('hands') or {}).get(name, {}).get('level', 1))
                       for name in HAND_KIND_NAMES)
        history = state.get('hands') or {}
        prior = {name for name, data in history.items() if data.get('played_this_round', 0) > 0}
        candidates = []
        for size in range(1, limit + 1):
            if 'psychic' in boss and size != 5:
                continue
            for indices in combinations(range(len(hand)), size):
                if not forced.issubset(indices):
                    continue
                estimate, name = self._estimate(state, indices, levels)
                if ('mouth' in boss and prior and name not in prior) or ('eye' in boss and name in prior):
                    estimate = 0
                if 'ox' in boss and name == round_state.get('most_played_poker_hand'):
                    estimate *= 0.75
                candidates.append((estimate, -size, indices, name))
        if not candidates:
            raise ValueError('No legal selection under visible forced-card/hand-limit constraints')
        score, _, indices, name = max(candidates)
        remaining = max(0, _number(blind.get('score'), 300) - _number(round_state.get('chips')))
        # One or more discards are worthwhile only when the present hand falls
        # short of its share of the blind. Retain the best scoring subset.
        if (round_state.get('discards_left', 0) > 0 and not forced
                and score < remaining / max(round_state.get('hands_left', 1), 1)):
            discard = tuple(i for i in range(len(hand)) if i not in indices)[:limit]
            if not discard and len(indices) > 1:
                discard = indices[-1:]
            if discard:
                return Decision(GameAction(ActionKind.DISCARD, discard),
                                f'Keep the best current {name}; draw toward the blind target.', score, APPROX)
        return Decision(GameAction(ActionKind.PLAY, indices),
                        f'Highest estimated legal hand: {name}.', score, APPROX)

    def _estimate(self, state: dict, indices: tuple[int, ...], levels: tuple[int, ...]) -> tuple[float, str]:
        hand = _cards(state, 'hand')
        try:
            ids = tuple(sorted(card_to_fast_id(hand[i]) for i in indices))
        except ValueError:
            return 0.0, 'Unknown'
        base = score_cards_with_levels(ids, levels)
        name = HAND_KIND_NAMES[base.kind]
        info = (state.get('hands') or {}).get(name, {})
        # Public chips/mult also account for changes beyond ordinary planets.
        chips = base.chips
        mult = base.mult
        if 'chips' in info:
            from balatro_ai_v2.fast.hand import LEVEL_CHIPS
            chips += _number(info['chips']) - BASE_CHIPS[base.kind] - (max(levels[base.kind], 1) - 1) * LEVEL_CHIPS[base.kind]
        if 'mult' in info:
            mult = _number(info['mult'])
        scored_ids = [ids[i] for i in range(len(ids)) if base.scoring_mask & (1 << i)]
        for i in indices:
            card = hand[i]
            card_id = card_to_fast_id(card)
            if card_id not in scored_ids:
                continue
            scored_ids.remove(card_id)
            if (card.get('state') or {}).get('debuff'):
                chips -= card_chips(card_id)
                continue
            mod = card.get('modifier') or {}
            enhancement = mod.get('enhancement')
            repeats = 2 if mod.get('seal') == 'RED' else 1
            chips += (repeats - 1) * card_chips(card_id)
            for _ in range(repeats):
                chips += _number((card.get('value') or {}).get('perma_bonus'))
                chips += 30 if enhancement == 'BONUS' else 0
                chips += _number(mod.get('edition_chips'), 50 if mod.get('edition') == 'FOIL' else 0)
                mult += 4 if enhancement == 'MULT' else 0
                mult += _number(mod.get('edition_mult'), 10 if mod.get('edition') in {'HOLO', 'HOLOGRAPHIC'} else 0)
                mult *= 2 if enhancement == 'GLASS' else 1
                mult *= _number(mod.get('edition_x_mult'), 1.5 if mod.get('edition') == 'POLYCHROME' else 1)
        for i, card in enumerate(hand):
            if i not in indices and not (card.get('state') or {}).get('debuff'):
                mod = card.get('modifier') or {}
                if mod.get('enhancement') == 'STEEL':
                    mult *= 1.5 ** (2 if mod.get('seal') == 'RED' else 1)
        round_state = state.get('round') or {}
        held_ids = []
        for i, card in enumerate(hand):
            if i not in indices:
                try:
                    held_ids.append(card_to_fast_id(card))
                except ValueError:
                    pass
        context = ScoreContext(money=int(_number(state.get('money'))),
                               held_cards=tuple(held_ids),
                               discards_left=round_state.get('discards_left', 0),
                               hands_left=max(0, round_state.get('hands_left', 1) - 1),
                               joker_slots=(state.get('jokers') or {}).get('limit', 5),
                               hand_times_played={k: int((state.get('hands') or {}).get(n, {}).get('played', 0)) + int(n == name)
                                                  for k, n in enumerate(HAND_KIND_NAMES)})
        jokers = _cards(state, 'jokers')
        for card in jokers:
            if (card.get('state') or {}).get('debuff'):
                continue
            key = card.get('key', '')
            ability = (card.get('value') or {}).get('ability') or {}
            scaling = _number(ability.get('mult', ability.get('t_chips', 0)))
            joker = Joker(key, int(scaling), _number(ability.get('x_mult'), 1),
                          int(_number((card.get('cost') or {}).get('sell'))))
            # Apply each joker sequentially so generic +Mult / XMult ordering
            # is retained, while explicitly leaving trigger interactions approximate.
            if key == 'j_abstract':
                mult += 3 * len(jokers)
            elif key == 'j_stencil':
                mult *= max(1, context.joker_slots - len(jokers) + sum(j.get('key') == 'j_stencil' for j in jokers))
            elif key == 'j_swashbuckler':
                mult += sum(_number((j.get('cost') or {}).get('sell')) for j in jokers if j is not card)
            else:
                result = apply_additive_jokers(FastScore(base.kind, chips, mult, 0, base.scoring_mask),
                                              ids, len(indices), (joker,), context)
                chips, mult = result.chips, result.total / max(result.chips, 1)
            mod = card.get('modifier') or {}
            chips += _number(mod.get('edition_chips'), 50 if mod.get('edition') == 'FOIL' else 0)
            mult += _number(mod.get('edition_mult'), 10 if mod.get('edition') in {'HOLO', 'HOLOGRAPHIC'} else 0)
            mult *= _number(mod.get('edition_x_mult'), 1.5 if mod.get('edition') == 'POLYCHROME' else 1)
        return max(0, chips * mult), name

    def _shop(self, state: dict) -> Decision:
        money = _number(state.get('money'))
        owned = _cards(state, 'jokers')
        room = len(owned) < (state.get('jokers') or {}).get('limit', 5)
        offers = sorted(enumerate(_cards(state, 'shop')), key=lambda pair: _utility(pair[1]), reverse=True)
        for index, card in offers:
            cost = _number((card.get('cost') or {}).get('buy'), float('inf'))
            if card.get('set') == 'JOKER' or str(card.get('key', '')).startswith('j_'):
                if room or (card.get('modifier') or {}).get('edition') == 'NEGATIVE':
                    if cost <= money and (len(owned) < 3 or money - cost >= 10 or cost == 0):
                        return Decision(GameAction(ActionKind.BUY_CARD, index=index), 'Buy an affordable joker to develop the scoring engine.')
                else:
                    sellable = [(i, j) for i, j in enumerate(owned)
                                if not (j.get('modifier') or {}).get('eternal')
                                and (j.get('modifier') or {}).get('edition') != 'NEGATIVE']
                    if sellable:
                        old_i, old = min(sellable, key=lambda pair: _utility(pair[1]))
                        if (_utility(card) >= _utility(old) + 5
                                and cost <= money + _number((old.get('cost') or {}).get('sell')) - 10):
                            return Decision(GameAction(ActionKind.SELL_JOKER, index=old_i), 'Make room for a substantially stronger affordable shop joker.')
            elif card.get('key') in PLANETS:
                capacity = (state.get('consumables') or {}).get('limit', 2)
                if cost <= money - 10 and len(_cards(state, 'consumables')) < capacity:
                    return Decision(GameAction(ActionKind.BUY_CARD, index=index), 'Buy a hand-level improvement while preserving cash.')
        for index, card in enumerate(_cards(state, 'packs')):
            key = card.get('key', '')
            if (('buffoon' in key and room) or 'celestial' in key) and _number((card.get('cost') or {}).get('buy'), float('inf')) <= money - 10:
                return Decision(GameAction(ActionKind.BUY_PACK, index=index), 'Open a supported pack while preserving cash.')
        return Decision(GameAction(ActionKind.NEXT_ROUND), 'Keep savings and advance to the next blind.')

    def _pack(self, state: dict) -> Decision:
        candidates = []
        for index, card in enumerate(_cards(state, 'pack')):
            key = card.get('key', '')
            if key.startswith('j_'):
                if len(_cards(state, 'jokers')) < (state.get('jokers') or {}).get('limit', 5) or (card.get('modifier') or {}).get('edition') == 'NEGATIVE':
                    candidates.append((_utility(card), index, ()))
            else:
                targets = self._consumable_targets(card, state)
                if targets is not None:
                    name = PLANETS.get(key)
                    value = 5 + _number(((state.get('hands') or {}).get(name) or {}).get('played'))
                    candidates.append((value, index, targets))
        if candidates:
            _, index, targets = max(candidates)
            return Decision(GameAction(ActionKind.PACK_SELECT, targets, index), 'Choose the best supported pack reward.')
        return Decision(GameAction(ActionKind.PACK_SKIP), 'Skip a pack without a supported useful selection.')
