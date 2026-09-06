"""Bounded, public-only discard lookahead over the frozen scoring model.

This is a sampled next-play estimate, not a complete blind simulator. Unsupported
hidden information and discard-triggered state changes retain the strategic
baseline. The only randomness comes from a digest of the public observation.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from functools import lru_cache
from hashlib import sha256
from itertools import combinations
from random import Random

from balatro_ai_v2.solver.actions import DiscardCards, HandSlot, PlayCards, PublicAction, is_legal
from balatro_ai_v2.solver.belief import canonical_remaining_deck
from balatro_ai_v2.solver.public_scoring import (
    _prepare_score_context,
    _score_play_prepared,
    _scoring_cards,
)
from balatro_ai_v2.solver.public_state import (
    DeckCardCount, HiddenHandCard, HiddenJokerSlot, Phase, PublicObservation, VisiblePlayingCard,
)


_NONCE = "public-discard-lookahead-v1"
_RANK = {rank: index for index, rank in enumerate("23456789TJQKA", 2)}
_SUIT = {suit: index for index, suit in enumerate("SHCD")}
_ORDER_SENSITIVE_JOKERS = frozenset({
    "j_photograph", "j_hanging_chad", "j_raised_fist", "j_baron", "j_shoot_the_moon",
    "j_bloodstone", "j_ancient", "j_triboulet", "j_blueprint", "j_brainstorm",
})
_SUPPORTED_BLINDS = frozenset({
    "Small Blind", "Big Blind", "The Psychic", "The Eye", "The Mouth",
    "The Flint", "The Wall", "The Needle", "The Water", "Violet Vessel",
})
_DISCARD_STATE_JOKERS = frozenset({
    "j_burnt", "j_trading", "j_castle", "j_yorick", "j_mail", "j_faceless",
    "j_hit_the_road", "j_green_joker", "j_ramen",
})


@dataclass(frozen=True, slots=True)
class TacticalChoice:
    action: PublicAction
    expected_score: float | None
    baseline_score: float | None
    samples: int
    reason: str


def choose_tactical(
    observation: PublicObservation, baseline: PublicAction, *, samples: int = 8,
    model_green_joker: bool = False,
) -> TacticalChoice:
    """Prefer a clear now, or a materially better sampled discard/refill."""
    if isinstance(samples, bool) or not isinstance(samples, int) or not 1 <= samples <= 64:
        raise ValueError("samples must be an integer in 1..64")

    def unchanged(reason: str) -> TacticalChoice:
        return TacticalChoice(baseline, None, None, 0, reason)

    if observation.phase != Phase.SELECTING_HAND or not isinstance(baseline, (PlayCards, DiscardCards)):
        return unchanged("preserve strategic action")
    if not is_legal(observation, baseline):
        raise ValueError("tactical baseline is not legal")
    if any(isinstance(card, HiddenHandCard) for card in observation.hand) or any(
        isinstance(joker, HiddenJokerSlot) for joker in observation.jokers
    ):
        return unchanged("hidden state: preserve baseline")
    if observation.required_hand_slots:
        return unchanged("forced selection: preserve boss recovery")
    if len(observation.hand) > 10:
        return unchanged("hand exceeds bounded lookahead budget")
    blind = next((blind for blind in observation.blinds if blind.status == "CURRENT"), None)
    if blind is None or (not blind.disabled and blind.name not in _SUPPORTED_BLINDS):
        return unchanged("unsupported blind transition: preserve baseline")
    best = _best_play(observation, preferred=baseline if isinstance(baseline, PlayCards) else None)
    if best is None:
        return unchanged("no scoring play: preserve boss recovery")
    play, score, hand_name = best
    target = max(0, blind.score - observation.round.chips)
    baseline_score = _action_score(observation, baseline) if isinstance(baseline, PlayCards) else score
    stochastic = _stochastic_scoring(observation)
    if isinstance(baseline, PlayCards) and baseline_score >= target and _is_scoring_family_eligible(observation, baseline):
        reason = "preserve strategic estimated clear" if stochastic else "preserve strategic clearing play"
        return TacticalChoice(baseline, baseline_score, baseline_score, 0, reason)
    if score >= target:
        return TacticalChoice(play, score, baseline_score, 0, "estimated clear now" if stochastic else "clear blind now")
    if observation.round.discards_left <= 0 or observation.draw_count <= 0:
        return TacticalChoice(play, score, baseline_score, 0, "best immediate legal play")
    unsupported = _DISCARD_STATE_JOKERS - {"j_green_joker"} if model_green_joker else _DISCARD_STATE_JOKERS
    if any(joker.key in unsupported and not joker.debuffed for joker in observation.jokers):
        return unchanged("discard changes joker state: preserve baseline")
    if model_green_joker and any(
        joker.key == "j_green_joker" and not joker.debuffed
        and (joker.runtime is None or joker.runtime.current_mult is None)
        for joker in observation.jokers
    ):
        return unchanged("unknown Green Joker runtime: preserve baseline")
    if any(card.seal == "PURPLE" for card in observation.hand):
        return unchanged("discard generates consumables: preserve baseline")
    if sum(entry.count for entry in observation.remaining_deck) != observation.draw_count:
        return unchanged("incomplete public draw belief")
    sort_mode = _observed_sort(observation.hand)
    if any(entry.card.rank not in _RANK or entry.card.suit not in _SUIT for entry in observation.remaining_deck):
        sort_mode = None
    if _order_sensitive(observation) and (sort_mode is None or _ambiguous_card_ties(observation)):
        return unchanged("unknown refill ordering affects score: preserve baseline")

    candidates = _discard_candidates(observation, baseline, play, hand_name)
    if not candidates:
        return TacticalChoice(play, score, baseline_score, 0, "no useful discard proposal")
    # Canonicalize before shuffling: caller-provided multiset ordering is not RNG.
    deck = tuple(card for entry in canonical_remaining_deck(observation.remaining_deck)
                 for card in (entry.card,) * entry.count)
    if not deck:
        return TacticalChoice(play, score, baseline_score, 0, "draw pile exhausted")
    rng = Random(int.from_bytes(sha256((_NONCE + observation.canonical_json()).encode()).digest(), "big"))
    max_draw = max(0, min(len(deck), max(observation.hand_limit - len(observation.hand) + len(c.cards) for c in candidates)))
    shared_draws = [tuple(rng.sample(deck, max_draw)) for _ in range(samples)]
    scored = []
    cache: dict[PublicObservation, float] = {}
    for discard in candidates:
        outcomes = []
        for drawn in shared_draws:
            after = _after_discard(observation, discard, drawn, sort_mode=sort_mode,
                                   model_green_joker=model_green_joker)
            if after not in cache:
                next_play = _best_play(after)
                cache[after] = next_play[1] if next_play is not None else 0.0
            outcomes.append(cache[after])
        # Cap at the blind requirement: enormous rare scores must not dominate
        # the choice over reliable survival. Keep raw expectation for diagnostics.
        utility = sum(min(target, value) for value in outcomes) / samples
        clear_probability = sum(value >= target for value in outcomes) / samples
        scored.append((utility, clear_probability, sum(outcomes) / samples, discard))
    last_hand = observation.round.hands_left == 1
    winner = max(scored, key=lambda row: ((row[1], row[0]) if last_hand else (row[0], row[1]), -len(row[3].cards),
                                         tuple(-slot.value for slot in row[3].cards)))
    utility, clear_probability, expected, discard = winner
    # A discard consumes a run resource. On the last hand a modest gain is
    # worthwhile; earlier, require a larger improvement before spending it.
    threshold = max(5.0, score * (0.05 if last_hand else 0.15))
    if (last_hand and score < target and clear_probability > 0) or utility > min(target, score) + threshold:
        ordering = f"inferred {sort_mode} refill order" if sort_mode else "refill order does not affect modeled scoring"
        return TacticalChoice(discard, expected, baseline_score, samples,
                              f"sampled next-play estimate; modeled draw-clear fraction {clear_probability:.3f}; {ordering}")
    return TacticalChoice(play, score, baseline_score, samples, "sampled refill does not justify discard")


@lru_cache(maxsize=24)
def _selections(size: int, limit: int) -> tuple[tuple[HandSlot, ...], ...]:
    return tuple(tuple(HandSlot(index) for index in indices)
                 for count in range(1, min(size, limit, 5) + 1)
                 for indices in combinations(range(size), count))


def _best_play(observation: PublicObservation, preferred: PlayCards | None = None) -> tuple[PlayCards, float, str] | None:
    context = _prepare_score_context(observation)
    stats = {stat.name: stat for stat in observation.hand_stats}
    boss = context.current_boss
    result = None
    best_key = None
    for selected in _selections(len(observation.hand), observation.selection_limit):
        action = PlayCards(selected)
        if not is_legal(observation, action):
            continue
        if boss is not None and boss.min_selected_cards is not None and len(selected) < boss.min_selected_cards:
            continue
        value, family = _score_play_prepared(observation, selected, stats, context)
        if boss is not None:
            if boss.repeat_hand_restriction and stats.get(family) is not None and stats[family].played_this_round:
                continue
            if boss.single_hand_family and any(stat.played_this_round and stat.name != family for stat in stats.values()):
                continue
        score = float(value)
        key = (score, action == preferred, -len(selected), tuple(-slot.value for slot in selected))
        if best_key is None or key > best_key:
            result, best_key = (action, score, family), key
    return result


def _action_score(observation: PublicObservation, action: PlayCards) -> float:
    return float(_score_play_prepared(observation, action.cards, None, _prepare_score_context(observation))[0])


def _is_scoring_family_eligible(observation: PublicObservation, action: PlayCards) -> bool:
    context = _prepare_score_context(observation)
    boss = context.current_boss
    if boss is None:
        return True
    if boss.min_selected_cards is not None and len(action.cards) < boss.min_selected_cards:
        return False
    _, family = _score_play_prepared(observation, action.cards, None, context)
    if boss.repeat_hand_restriction and any(stat.name == family and stat.played_this_round for stat in observation.hand_stats):
        return False
    return not (boss.single_hand_family and any(stat.name != family and stat.played_this_round for stat in observation.hand_stats))


def _discard_candidates(observation: PublicObservation, baseline: PublicAction,
                        play: PlayCards, family: str) -> tuple[DiscardCards, ...]:
    hand = observation.hand
    proposals: list[DiscardCards] = []

    def add(indices: tuple[int, ...]) -> None:
        indices = tuple(sorted(indices))
        if not indices or len(indices) > 5:
            return
        action = DiscardCards(tuple(HandSlot(index) for index in indices))
        if action not in proposals and is_legal(observation, action) and len(proposals) < 8:
            proposals.append(action)

    def keep(indices: set[int]) -> None:
        outside = [index for index in range(len(hand)) if index not in indices]
        outside.sort(key=lambda i: (_RANK.get(hand[i].rank, 0), i))
        add(tuple(outside[:5]))

    if isinstance(baseline, DiscardCards):
        add(tuple(slot.value for slot in baseline.cards))
    scoring = Counter(_scoring_cards(tuple(hand[slot.value] for slot in play.cards), family))
    core = set()
    for slot in play.cards:
        if scoring[hand[slot.value]]:
            core.add(slot.value)
            scoring[hand[slot.value]] -= 1
    keep(core)
    # Flush and straight draws compete with keeping an already-made pair.
    for suit in "SHCD":
        suited = {index for index, card in enumerate(hand) if card.suit == suit}
        if len(suited) >= 4:
            keep(suited)
    ranks = {_RANK.get(card.rank, 0) for card in hand}
    if 14 in ranks:
        ranks.add(1)
    for low in range(1, 11):
        wanted = ranks.intersection(range(low, low + 5))
        if len(wanted) >= 4:
            indices = {next(index for index, card in enumerate(hand)
                            if _RANK.get(card.rank, 0) == (14 if rank == 1 else rank))
                       for rank in wanted}
            keep(indices)
    counts = Counter(card.rank for card in hand)
    pairs = {index for index, card in enumerate(hand) if counts[card.rank] >= 2}
    if pairs:
        keep(pairs)
    for rank, count in counts.most_common():
        if count >= 2:
            keep({index for index, card in enumerate(hand) if card.rank == rank})
    for index in sorted(set(range(len(hand))) - core, key=lambda i: (_RANK.get(hand[i].rank, 0), i)):
        add((index,))
    return tuple(proposals)


def _after_discard(observation: PublicObservation, discard: DiscardCards,
                   shared_draw: tuple[VisiblePlayingCard, ...], *, sort_mode: str | None = None,
                   model_green_joker: bool = False) -> PublicObservation:
    selected = {slot.value for slot in discard.cards}
    kept = tuple(card for index, card in enumerate(observation.hand) if index not in selected)
    draw = shared_draw[:max(0, observation.hand_limit - len(kept))]
    remaining = Counter({entry.card: entry.count for entry in canonical_remaining_deck(observation.remaining_deck)})
    remaining.subtract(draw)
    deck = tuple(DeckCardCount(card, count) for card, count in remaining.items() if count > 0)
    hand = _sort_hand(kept + draw, sort_mode) if sort_mode else kept + draw
    jokers = observation.jokers
    if model_green_joker:
        # Installed card.lua: one decrement on the last discarded card, excluding
        # Blueprint contexts. Copies subsequently score the updated target runtime.
        updated = []
        for joker in jokers:
            if joker.key == "j_green_joker" and not joker.debuffed:
                if joker.runtime is None or joker.runtime.current_mult is None:
                    raise ValueError("Green Joker discard requires known current_mult")
                joker = replace(joker, runtime=replace(
                    joker.runtime, current_mult=max(0, joker.runtime.current_mult - 1)))
            updated.append(joker)
        jokers = tuple(updated)
    return replace(observation, hand=hand, jokers=jokers, draw_count=observation.draw_count - len(draw),
                   remaining_deck=deck, round=replace(observation.round,
                       discards_left=observation.round.discards_left - 1,
                       discards_used=observation.round.discards_used + 1))


def _sort_hand(hand: tuple[VisiblePlayingCard, ...], mode: str) -> tuple[VisiblePlayingCard, ...]:
    def key(card: VisiblePlayingCard) -> tuple[int, int]:
        rank, suit = _RANK[card.rank], _SUIT[card.suit]
        return (-rank, suit) if mode.startswith("rank") else (suit, -rank)
    return tuple(sorted(hand, key=key, reverse=mode.endswith("ascending")))


def _observed_sort(hand: tuple[VisiblePlayingCard, ...]) -> str | None:
    # Neither the sort mode nor private tie-break values are exported. Only
    # infer a mode when exactly one ordinary sort explains the public hand.
    if any(card.rank not in _RANK or card.suit not in _SUIT for card in hand):
        return None
    matches = [mode for mode in ("rank descending", "rank ascending", "suit descending", "suit ascending")
               if _sort_hand(hand, mode) == hand]
    return matches[0] if len(matches) == 1 else None


def _order_sensitive(observation: PublicObservation) -> bool:
    if any(joker.key in _ORDER_SENSITIVE_JOKERS and not joker.debuffed for joker in observation.jokers):
        return True
    return any(card.enhancement in {"GLASS", "STEEL"} or card.edition == "POLYCHROME"
               for card in (*observation.hand, *(entry.card for entry in observation.remaining_deck)))


def _ambiguous_card_ties(observation: PublicObservation) -> bool:
    seen: dict[tuple[str, str], VisiblePlayingCard] = {}
    for card in (*observation.hand, *(entry.card for entry in observation.remaining_deck)):
        # Equal rank/suit cards with different scoring properties can be
        # ordered by private vanilla tie-breaks. Presentation text is irrelevant.
        canonical = replace(card, effect_text="")
        key = (card.rank, card.suit)
        if key in seen and seen[key] != canonical:
            return True
        seen[key] = canonical
    return False


def _stochastic_scoring(observation: PublicObservation) -> bool:
    return any(joker.key in {"j_misprint", "j_bloodstone", "j_space"} and not joker.debuffed
               for joker in observation.jokers) or any(
        card.enhancement == "LUCKY" and not card.debuffed for card in observation.hand
    )
