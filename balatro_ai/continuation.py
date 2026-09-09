"""Bounded public one-draw score estimates, using common Monte Carlo draws."""

from collections import Counter
from dataclasses import replace
from fractions import Fraction
from functools import lru_cache
from itertools import combinations
from math import fsum, sqrt
from random import Random

from balatro_ai.game.actions import (
    DiscardCards,
    HandSlot,
    PlayCards,
    action_from_data,
    action_to_data,
    is_legal,
)
from balatro_ai.game.scoring import (
    _prepare_score_context,
    _score_play_prepared,
    _scoring_cards,
    score_play,
)
from balatro_ai.game.state import (
    DeckCardCount,
    Phase,
    PublicItem,
    PublicObservation,
    VisiblePlayingCard,
)

_FIXED_JOKERS = frozenset(
    {
        "j_joker",
        "j_odd_todd",
        "j_hack",
        "j_drunkard",
        "j_gros_michel",
        "j_walkie_talkie",
        "j_shoot_the_moon",
        "j_jolly",
        "j_droll",
    }
)
_EDITIONS = {None, "FOIL", "HOLO", "HOLOGRAPHIC", "POLYCHROME", "NEGATIVE"}
_SEED = 739291  # An experiment constant, unrelated to any game seed.
_PLAY_CAP = 4
_DISCARD_CAP = 4


def _plain(card: object) -> bool:
    return (
        isinstance(card, VisiblePlayingCard)
        and card.rank in {"2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"}
        and card.suit in {"S", "H", "C", "D"}
        and card.enhancement is None
        and card.seal is None
        and card.edition is None
        and not card.debuffed
        and card.permanent_bonus == 0
    )


@lru_cache(maxsize=9)
def _selections(count: int) -> tuple[tuple[HandSlot, ...], ...]:
    return tuple(
        tuple(HandSlot(index) for index in indices)
        for size in range(1, min(count, 5) + 1)
        for indices in combinations(range(count), size)
    )


def _number(value: int | Fraction) -> int | float:
    return int(value) if value == int(value) else float(value)


def _wilson(successes: int, samples: int) -> list[float]:
    z = 1.959963984540054
    probability = successes / samples
    denominator = 1 + z * z / samples
    center = (probability + z * z / (2 * samples)) / denominator
    half = (
        z
        * sqrt(probability * (1 - probability) / samples + z * z / (4 * samples * samples))
        / denominator
    )
    return [max(0.0, center - half), min(1.0, center + half)]


def _candidates(observation: PublicObservation, play_candidates: list[dict]) -> list:
    supplied = []
    for row in play_candidates:
        try:
            action = action_from_data(row["action"])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(action, PlayCards) and is_legal(observation, action):
            score, family = score_play(observation, action.cards)
            supplied.append((action, score, family))
    if not supplied:
        context = _prepare_score_context(observation)
        supplied = [
            (PlayCards(selection), *_score_play_prepared(observation, selection, None, context))
            for selection in _selections(len(observation.hand))
        ]
    top, score, family = min(supplied, key=lambda row: (-row[1], len(row[0].cards), row[0].cards))
    scoring = Counter(
        _scoring_cards(tuple(observation.hand[slot.value] for slot in top.cards), family)
    )
    core = []
    for slot in top.cards:
        card = observation.hand[slot.value]
        if scoring[card]:
            core.append(slot)
            scoring[card] -= 1
    core = tuple(core)
    candidates = []
    if observation.round.hands_left >= 2:
        # Include the no-kicker core, the supplied top play, and individual
        # harmless kickers. The score/family check excludes costly held Queens.
        variants = [core, top.cards]
        variants.extend(
            tuple(sorted((*core, HandSlot(index))))
            for index in range(len(observation.hand))
            if HandSlot(index) not in core and len(core) < 5
        )
        for slots in variants:
            action = PlayCards(slots)
            if action in [row[0] for row in candidates] or not is_legal(observation, action):
                continue
            immediate, actual_family = score_play(observation, action.cards)
            if immediate == score and actual_family == family:
                candidates.append((action, immediate, actual_family))
            if len(candidates) == _PLAY_CAP:
                break
    if observation.round.discards_left > 0:
        keep_queens = any(joker.key == "j_shoot_the_moon" for joker in observation.jokers)
        protected = {
            index for index, card in enumerate(observation.hand) if keep_queens and card.rank == "Q"
        }
        proposed = [
            tuple(
                HandSlot(index)
                for index in range(len(observation.hand))
                if HandSlot(index) not in top.cards and index not in protected
            )
        ]
        ranks = Counter(card.rank for card in observation.hand)
        unseen_ranks = Counter()
        for entry in observation.remaining_deck:
            unseen_ranks[entry.card.rank] += entry.count
        # Preserve literal rank outs even when the best immediate play is an
        # unrelated high card. This is candidate construction, not draw search.
        for rank in sorted(ranks, key=lambda rank: (-ranks[rank] * unseen_ranks[rank], rank)):
            if unseen_ranks[rank]:
                proposed.append(
                    tuple(
                        HandSlot(index)
                        for index, card in enumerate(observation.hand)
                        if card.rank != rank and index not in protected
                    )
                )
        for suit in ("S", "H", "C", "D"):
            if sum(card.suit == suit for card in observation.hand) in (3, 4):
                proposed.append(
                    tuple(
                        HandSlot(index)
                        for index, card in enumerate(observation.hand)
                        if card.suit != suit and index not in protected
                    )
                )
        singles = tuple(
            HandSlot(index)
            for index, card in enumerate(observation.hand)
            if ranks[card.rank] == 1 and card.rank != "Q"
        )
        proposed.append(singles)
        proposed.extend((slot,) for slot in singles)
        discards = []
        for slots in proposed:
            if not 1 <= len(slots) <= 5:
                continue
            action = DiscardCards(slots)
            if action not in discards and is_legal(observation, action):
                discards.append(action)
            if len(discards) == _DISCARD_CAP:
                break
        candidates.extend((action, 0, None) for action in discards)
    return candidates


def continuation_advice(
    observation: PublicObservation, play_candidates: list[dict], *, samples: int = 48
) -> dict[str, object]:
    """Estimate one refill followed by the best scoring subset, without acting."""
    current = [blind for blind in observation.blinds if blind.status == "CURRENT"]
    if (
        isinstance(samples, bool)
        or not isinstance(samples, int)
        or not 1 <= samples <= 128
        or observation.phase != Phase.SELECTING_HAND
        or observation.deck not in {"RED", "BLACK"}
        or not 1 <= len(observation.hand) <= 8
        or observation.hand_limit != len(observation.hand)
        or observation.selection_limit != 5
        or observation.required_hand_slots
        or observation.round.hands_left < 1
        or len(current) != 1
        or current[0].kind not in {"SMALL", "BIG"}
        or not 0 < observation.draw_count <= 52
        or sum(entry.count for entry in observation.remaining_deck) != observation.draw_count
        or any(not _plain(card) for card in observation.hand)
        or any(not _plain(entry.card) for entry in observation.remaining_deck)
        or any(
            not isinstance(joker, PublicItem)
            or joker.key not in _FIXED_JOKERS
            or joker.runtime is not None
            or joker.debuffed
            or joker.edition not in _EDITIONS
            for joker in observation.jokers
        )
    ):
        return {}
    target = current[0].score
    # Independently verify the terminal guard instead of trusting cached advice.
    context = _prepare_score_context(observation)
    best_current = max(
        _score_play_prepared(observation, slots, None, context)[0]
        for slots in _selections(len(observation.hand))
    )
    if observation.round.chips + best_current >= target:
        return {}
    candidates = _candidates(observation, play_candidates)
    if not candidates:
        return {}
    population = sorted(
        (entry.card for entry in observation.remaining_deck for _ in range(entry.count)),
        key=lambda card: (card.suit, card.rank, card.effect_text),
    )
    rng = Random(_SEED)
    outcomes = [[] for _ in candidates]
    successes = [0 for _ in candidates]
    for _ in range(samples):
        unseen = population.copy()
        rng.shuffle(unseen)
        for index, (action, immediate, family) in enumerate(candidates):
            selected = {slot.value for slot in action.cards}
            held = tuple(card for slot, card in enumerate(observation.hand) if slot not in selected)
            draws = min(observation.hand_limit - len(held), len(unseen))
            playing = isinstance(action, PlayCards)
            following = replace(
                observation,
                hand=held + tuple(unseen[:draws]),
                remaining_deck=tuple(
                    DeckCardCount(card, count) for card, count in Counter(unseen[draws:]).items()
                ),
                draw_count=observation.draw_count - draws,
                round=replace(
                    observation.round,
                    chips=observation.round.chips + immediate,
                    hands_left=observation.round.hands_left - int(playing),
                    hands_played=observation.round.hands_played + int(playing),
                    discards_left=observation.round.discards_left - int(not playing),
                    discards_used=observation.round.discards_used + int(not playing),
                ),
                hand_stats=tuple(
                    replace(
                        stat, played=stat.played + 1, played_this_round=stat.played_this_round + 1
                    )
                    if playing and stat.name == family
                    else stat
                    for stat in observation.hand_stats
                ),
            )
            prepared = _prepare_score_context(following)
            best = max(
                _score_play_prepared(following, slots, None, prepared)[0]
                for slots in _selections(len(following.hand))
            )
            outcomes[index].append(float(best))
            successes[index] += observation.round.chips + immediate + best >= target
    return {
        "samples": samples,
        "candidate_cap": _PLAY_CAP + _DISCARD_CAP,
        "play_candidate_cap": _PLAY_CAP,
        "discard_candidate_cap": _DISCARD_CAP,
        "candidates": [
            {
                "action": action_to_data(action),
                "horizon": "play_then_best_play"
                if isinstance(action, PlayCards)
                else "discard_then_best_play",
                "immediate_score": _number(immediate),
                "mean_best_next_score": fsum(outcomes[index]) / samples,
                "finish_probability": successes[index] / samples,
                "wilson_95_interval": _wilson(successes[index], samples),
                "samples": samples,
            }
            for index, (action, immediate, _) in enumerate(candidates)
        ],
        "note": (
            "One-draw Monte Carlo score estimates from public unordered deck composition, "
            "using common uniform permutations and an experiment seed unrelated to the game seed. "
            "The next play maximizes the local score estimate; this is not real-engine validation. "
            "Wilson 95% intervals express Monte Carlo uncertainty. Candidates are incomplete, "
            "ignore later discards and plays, and are not ranked across different resource horizons. "
            "Finish probability concerns this blind within the stated horizon, not full-run wins."
        ),
    }
