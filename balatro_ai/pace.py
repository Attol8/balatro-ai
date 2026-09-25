"""Public build pace and Tarot values for shop-side and consumable decisions.

Every number comes from the public observation: the full-deck composition, Jokers,
hand levels, round resources and visible offers. Draws come from a fixed set of
experiment-seeded shuffles of the public deck, never the game's seed or draw order,
so every variant of a build is compared on the same sampled hands.
"""

from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import combinations
from random import Random

from balatro_ai.game.actions import ConsumableSlot, HandSlot, UseConsumable, is_legal
from balatro_ai.game.boss_rules import boss_rule
from balatro_ai.game.consumable_rules import iter_public_targets
from balatro_ai.game.mechanics import planet_hand
from balatro_ai.game.scoring import (
    _HAND_LEVEL_GAINS,
    _PLAYED_INDIVIDUAL_ADDITIVE_JOKERS,
    _PLAYED_INDIVIDUAL_XMULT_JOKERS,
    _PLAYED_RETRIGGER_JOKERS,
    NO_SCORING_EFFECT_JOKERS,
    SCORING_RULE_JOKERS,
    MouthFamilyUnavailable,
    _card_joker_effect,
    _card_repetitions,
    _individual_joker_card_xmult,
    _prepare_score_context,
    _score_play_prepared,
    unmodelled_scoring_jokers,
)
from balatro_ai.game.state import (
    OBSCURED_CARD_ATTRIBUTE,
    DeckCardCount,
    HandStat,
    HiddenJokerSlot,
    Phase,
    PublicBlind,
    PublicItem,
    PublicObservation,
    VisiblePlayingCard,
)

_SEED = 5150  # An experiment constant, unrelated to any game seed.
_SAMPLES = 32
_BOOTSTRAP = 1000
# Each discard is assumed to replace about three cards, spread evenly over the hands.
_CARDS_PER_DISCARD = 3
_BUDGET_SECONDS = 2.5
_DECK_CANDIDATES = 6
_FACE_RANKS = frozenset({"J", "Q", "K"})
_NEXT_RANK = dict(zip("23456789TJQKA", "3456789TJQKA2", strict=True))
# Held cards matter to these Jokers, so fewer-card plays can beat five-card plays.
_HELD_EFFECT_JOKERS = frozenset(
    {"j_baron", "j_shoot_the_moon", "j_raised_fist", "j_mime", "j_blackboard"}
)
_SMALL_PLAY_JOKERS = frozenset({"j_half"})
# Boss effects the scorer applies itself when the boss is marked current.
_SCORER_BOSSES = frozenset({"The Flint", "The Psychic"})
_ENHANCEMENT_TAROTS = {
    "c_magician": "LUCKY",
    "c_empress": "MULT",
    "c_heirophant": "BONUS",
    "c_lovers": "WILD",
    "c_chariot": "STEEL",
    "c_justice": "GLASS",
    "c_devil": "GOLD",
    "c_tower": "STONE",
}
_SUIT_TAROTS = {"c_star": "D", "c_moon": "C", "c_sun": "H", "c_world": "S"}
# Deja Vu is a Spectral, valued the same way: its red seal retriggers the card.
_HAND_TAROTS = frozenset({*_ENHANCEMENT_TAROTS, *_SUIT_TAROTS, "c_strength", "c_deja_vu"})
# Destroying cards never raises a visible hand's best play; its value is deck thinning.
_DECK_TAROTS = _HAND_TAROTS | {"c_hanged_man"}
_TAROT_MAX_TARGETS = {
    **dict.fromkeys(("c_magician", "c_empress", "c_heirophant", "c_strength", "c_hanged_man"), 2),
    **dict.fromkeys(("c_lovers", "c_chariot", "c_justice", "c_devil", "c_tower"), 1),
    **dict.fromkeys(_SUIT_TAROTS, 3),
}
_HAND_VOUCHERS = {"v_grabber": 1, "v_nacho_tong": 1}
# Engine potential: an offer is also priced on decks with these many feeding edits,
# using the first samples only to bound the time.
_POTENTIAL_EDITS = (6, 12)
_POTENTIAL_SAMPLES = 16
_HELD_RANKS = {"j_baron": "K", "j_shoot_the_moon": "Q"}
# Mime retriggers and Steel Joker counts held Steel, so they feed on held Steel cards.
_HELD_STEEL_JOKERS = frozenset({"j_mime", "j_steel_joker"})
_COPIERS = frozenset({"j_blueprint", "j_brainstorm"})
# Engine pieces whose value multiplies together; a lone piece can look break-even.
_PARTNERS = {
    "j_baron": "j_mime",
    "j_shoot_the_moon": "j_mime",
    "j_mime": "j_baron",
    "j_photograph": "j_hanging_chad",
    "j_hanging_chad": "j_photograph",
}
_RANK_NAMES = dict(
    zip(
        "23456789TJQKA",
        ("2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s", "10s", "Jacks", "Queens", "Kings", "Aces"),
        strict=True,
    )
)
_SUIT_NAMES = {"S": "Spades", "H": "Hearts", "C": "Clubs", "D": "Diamonds"}
# Vanilla get_blind_amount: base chips per ante for each stake scaling level.
_ANTE_BASES = {
    1: (300, 800, 2000, 5000, 11000, 20000, 35000, 50000),
    2: (300, 900, 2600, 8000, 20000, 36000, 60000, 100000),
    3: (300, 1000, 3200, 9000, 25000, 60000, 110000, 200000),
}
_STAKE_SCALING = {"GREEN": 2, "BLACK": 2, "BLUE": 2, "PURPLE": 3, "ORANGE": 3, "GOLD": 3}
_DISCARD_VOUCHERS = {"v_wasteful": 1, "v_recyclomancy": 1}
_HAND_SIZE_VOUCHERS = {"v_paint_brush": 1, "v_palette": 1}


@dataclass(frozen=True, slots=True)
class _Round:
    hands: int
    discards: int
    hand_limit: int
    debuff_suits: tuple[str, ...] = ()
    debuff_ranks: tuple[str, ...] = ()
    debuff_faces: bool = False
    boss: PublicBlind | None = None
    # Held-card effects count only the cards actually in hand, so the sample is exactly
    # one hand; otherwise discards add a few replacement cards to choose plays from.
    hold: bool = False

    @property
    def pool(self) -> int:
        if self.hold:
            return self.hand_limit
        extra = int(_CARDS_PER_DISCARD * self.discards / max(1, self.hands) + 0.5)
        return self.hand_limit + min(5, extra)


@dataclass(frozen=True, slots=True)
class _Sample:
    """One sampled hand: its deck indices, best play, and best play per poker-hand family."""

    indices: tuple[int, ...]
    best: float
    best_selection: tuple[HandSlot, ...]
    by_family: tuple[tuple[HandSlot, ...], ...]


class _Budget:
    def __init__(self, seconds: float) -> None:
        self.started = time.monotonic()
        self.seconds = seconds
        self.skipped: list[str] = []

    def left(self) -> bool:
        return time.monotonic() - self.started < self.seconds

    def elapsed(self) -> float:
        return round(time.monotonic() - self.started, 3)


def build_pace(observation: PublicObservation) -> dict[str, object]:
    """Compare the build with the upcoming blinds, and price each visible upgrade."""

    if observation.phase not in {Phase.SHOP, Phase.BLIND_SELECT, Phase.PACK}:
        return {}
    blinds = [b for b in observation.blinds if b.status in {"SELECT", "UPCOMING"}]
    if not blinds or not observation.full_deck or _hidden_jokers(observation):
        return {}
    budget = _Budget(_BUDGET_SECONDS)
    base = _base(observation)
    deck = _deck(observation)
    hold = _holds(observation, deck)
    rounds = {blind.name: replace(_round_for(observation, blind), hold=hold) for blind in blinds}
    focus = next((b for b in blinds if b.kind == "BOSS"), blinds[-1])
    focus_round = rounds[focus.name]
    baselines = {rnd: _baseline(base, rnd, deck) for rnd in set(rounds.values())}
    samples = baselines[focus_round]
    result: dict[str, object] = {
        "blinds": [
            _blind_row(blind, rounds[blind.name], [s.best for s in baselines[rounds[blind.name]]])
            for blind in blinds
        ],
        "focus": focus.name,
    }
    view = _View(base, focus, focus_round, samples, deck)
    horizon = _next_ante(observation, blinds, view, rounds, baselines)
    if horizon:
        result["next_ante"] = horizon
    jokers = _joker_rows(observation, blinds, view)
    if jokers:
        result["jokers"] = jokers
    offers = _offer_rows(observation, view, jokers, budget)
    if offers:
        result["offers"] = offers
    tarots = _deck_tarot_rows(observation, view, budget)
    if tarots:
        result["tarots"] = tarots
    unmodelled = sorted({joker.key for joker in unmodelled_scoring_jokers(observation)})
    if unmodelled:
        result["not_modelled"] = unmodelled
    if budget.skipped:
        result["skipped_for_time"] = budget.skipped
    result["seconds"] = budget.elapsed()
    return result


def hand_tarot_values(observation: PublicObservation) -> list[dict[str, object]]:
    """Best targets among the visible hand for each held Tarot, scored on that hand."""

    if observation.phase != Phase.SELECTING_HAND or not observation.hand:
        return []
    if _hidden_jokers(observation) or not all(
        isinstance(card, VisiblePlayingCard) for card in observation.hand
    ):
        return []
    budget = _Budget(_BUDGET_SECONDS)
    try:
        before = _best_visible_play(observation, observation.hand)
    except MouthFamilyUnavailable:
        return []
    rows: list[dict[str, object]] = []
    for slot, item in enumerate(observation.consumables):
        if item.key not in _HAND_TAROTS:
            continue
        if not budget.left():
            break
        # The full action check also applies boss rules such as Cerulean Bell's forced card.
        legal = {
            targets
            for targets in iter_public_targets(observation, item, from_pack=False)
            if is_legal(
                observation,
                UseConsumable(ConsumableSlot(slot), tuple(HandSlot(t) for t in targets)),
            )
        }
        best = _greedy_hand_targets(observation, item.key, legal, budget)
        if best is None:
            continue
        rows.append(
            {
                "consumable": slot,
                "key": item.key,
                "best_targets": list(best[1]),
                "best_play_now": _number(before),
                "best_play_after": _number(best[0]),
            }
        )
    return rows


@dataclass(frozen=True, slots=True)
class _View:
    """The focus blind's round and baseline samples that every comparison shares."""

    base: PublicObservation
    focus: PublicBlind
    rnd: _Round
    samples: tuple[_Sample, ...]
    deck: tuple[VisiblePlayingCard | None, ...]

    @property
    def scores(self) -> list[float]:
        return [sample.best for sample in self.samples]

    def clear(self, scores: list[float], hands: int | None = None) -> float:
        return _clear_chance(scores, hands or self.rnd.hands, self.focus.score)

    def label(self) -> str:
        return f"{self.focus.kind.lower()}_clear_chance"


def _greedy_hand_targets(observation, key, legal, budget):
    """Add one legal target at a time, keeping the change that most raises the best play."""

    chosen: tuple[int, ...] = ()
    best = None
    while budget.left():
        step = None
        for index in range(len(observation.hand)):
            targets = tuple(sorted((*chosen, index)))
            if index in chosen or targets not in legal:
                continue
            hand = list(observation.hand)
            for target in targets:
                hand[target] = _apply_tarot(key, hand[target])
            score = _best_visible_play(observation, tuple(hand))
            if step is None or score > step[0]:
                step = (score, targets)
        if step is None or (best is not None and step[0] <= best[0]):
            break
        best, chosen = step, step[1]
    return best


_HELD_KEYS = _HELD_EFFECT_JOKERS | frozenset(_HELD_RANKS) | _HELD_STEEL_JOKERS


def _holds(observation: PublicObservation, deck) -> bool:
    """Whether held cards matter to this build or to a visible offer that would change it."""

    visible = (
        *observation.jokers,
        *observation.shop,
        *observation.opened_pack,
        *observation.consumables,
    )
    keys = {getattr(item, "key", None) for item in visible}
    return bool(keys & (_HELD_KEYS | {"c_chariot"})) or any(
        card.enhancement == "STEEL" for card in deck
    )


def _hidden_jokers(observation: PublicObservation) -> bool:
    return any(isinstance(joker, HiddenJokerSlot) for joker in observation.jokers)


def _deck(observation: PublicObservation) -> tuple[VisiblePlayingCard, ...]:
    return tuple(entry.card for entry in observation.full_deck for _ in range(entry.count))


def _round_for(observation: PublicObservation, blind: PublicBlind) -> _Round:
    # Outside a blind the round counters show the next round's full allowance.
    hands = max(1, observation.round.hands_left)
    discards = max(0, observation.round.discards_left)
    hand_limit = max(1, observation.hand_limit)
    rule = boss_rule(blind.name) if blind.kind == "BOSS" else None
    if rule is None:
        return _Round(hands, discards, hand_limit)
    return _Round(
        hands=rule.hands_forced or hands,
        discards=discards if rule.discards_forced is None else rule.discards_forced,
        hand_limit=max(1, hand_limit + rule.hand_size_delta),
        debuff_suits=rule.suit_debuff,
        debuff_ranks=rule.rank_debuff,
        debuff_faces=rule.face_debuff,
        boss=replace(blind, status="CURRENT", disabled=False)
        if blind.name in _SCORER_BOSSES
        else None,
    )


def _base(observation: PublicObservation) -> PublicObservation:
    """The build without offers or round state, so shop decisions share one cache entry."""

    money_matters = any(
        isinstance(joker, PublicItem) and joker.key in {"j_bull", "j_bootstraps"}
        for joker in observation.jokers
    )
    return replace(
        observation,
        phase=Phase.SHOP,
        money=observation.money if money_matters else 0,
        round=replace(
            observation.round,
            chips=0,
            hands_left=0,
            discards_left=0,
            hands_played=0,
            discards_used=0,
            reroll_cost=0,
            boss_rerolled=False,
            mouth_hand_family=None,
        ),
        last_tarot_planet=None,
        blinds=(),
        hand=(),
        required_hand_slots=(),
        remaining_deck=(),
        draw_count=0,
        shop=(),
        vouchers=(),
        packs=(),
        opened_pack=(),
        pack_kind=None,
        pack_choices_remaining=0,
    )


def _composition(deck: tuple[VisiblePlayingCard | None, ...]) -> tuple[DeckCardCount, ...]:
    counts = Counter(card for card in deck if card is not None)
    return tuple(
        DeckCardCount(card, count)
        for card, count in sorted(counts.items(), key=lambda pair: repr(pair[0]))
    )


@lru_cache(maxsize=8)
def _shuffles(size: int) -> tuple[tuple[int, ...], ...]:
    rng = Random(_SEED * 1009 + size)
    orders = []
    for _ in range(_SAMPLES):
        order = list(range(size))
        rng.shuffle(order)
        orders.append(tuple(order))
    return tuple(orders)


@lru_cache(maxsize=32)
def _selections(pool: int, sizes: tuple[int, ...]) -> tuple[tuple[HandSlot, ...], ...]:
    return tuple(
        tuple(HandSlot(index) for index in chosen)
        for size in sizes
        for chosen in combinations(range(pool), size)
    )


def _sizes(jokers, deck, pool: int) -> tuple[int, ...]:
    keys = {joker.key for joker in jokers if isinstance(joker, PublicItem) and not joker.debuffed}
    top = min(5, pool)
    if keys & _HELD_EFFECT_JOKERS or any(
        card is not None and card.enhancement == "STEEL" for card in deck
    ):
        return tuple(range(1, top + 1))
    if keys & _SMALL_PLAY_JOKERS:
        return tuple(sorted({*range(1, min(3, top) + 1), top}))
    return (top,)


def _debuffed(card: VisiblePlayingCard, rnd: _Round) -> VisiblePlayingCard:
    if card.enhancement == "STONE":
        return card
    if (
        card.suit in rnd.debuff_suits
        or card.rank in rnd.debuff_ranks
        or (rnd.debuff_faces and card.rank in _FACE_RANKS)
    ):
        return replace(card, debuffed=True)
    return card


def _scene(
    base: PublicObservation,
    rnd: _Round,
    cards: tuple[VisiblePlayingCard, ...],
    position: int,
    *,
    jokers=None,
    hand_stats: tuple[HandStat, ...] | None = None,
    full_deck: tuple[DeckCardCount, ...] | None = None,
) -> PublicObservation:
    """A round-start hand at ``position``: earlier hands played, one discard spent per hand."""

    position = position % rnd.hands
    discards_left = max(0, rnd.discards - position)
    round_state = replace(
        base.round,
        hands_left=rnd.hands - position,
        discards_left=discards_left,
        hands_played=position,
        discards_used=rnd.discards - discards_left,
    )
    composition = base.full_deck if full_deck is None else full_deck
    size = sum(entry.count for entry in composition)
    return replace(
        base,
        phase=Phase.SELECTING_HAND,
        round=round_state,
        blinds=(rnd.boss,) if rnd.boss is not None else (),
        hand=cards,
        jokers=base.jokers if jokers is None else jokers,
        hand_stats=base.hand_stats if hand_stats is None else hand_stats,
        full_deck=composition,
        deck_size=size,
        draw_count=max(0, size - len(cards)),
    )


def _score_pool(scene: PublicObservation, selections) -> tuple[float, tuple[HandSlot, ...], dict]:
    context = _prepare_score_context(scene)
    best, best_selection = 0.0, ()
    by_family: dict[str, tuple[float, tuple[HandSlot, ...]]] = {}
    for selection in selections:
        try:
            score, family = _score_play_prepared(scene, selection, None, context)
        except ValueError:
            continue
        value = float(score)
        if value > by_family.get(family, (-1.0, ()))[0]:
            by_family[family] = (value, selection)
        if value > best:
            best, best_selection = value, selection
    return best, best_selection, by_family


def _pool(order: tuple[int, ...], deck, size: int) -> tuple[int, ...]:
    return tuple(index for index in order if deck[index] is not None)[:size]


def _sample_pool(base, rnd, deck, indices, position, **changes) -> _Sample:
    cards = tuple(_debuffed(deck[index], rnd) for index in indices)
    scene = _scene(base, rnd, cards, position, **changes)
    jokers = changes.get("jokers", base.jokers)
    best, selection, by_family = _score_pool(
        scene, _selections(len(cards), _sizes(jokers, deck, len(cards)))
    )
    return _Sample(indices, best, selection, tuple(sel for _, sel in by_family.values()))


@lru_cache(maxsize=16)
def _baseline(base: PublicObservation, rnd: _Round, deck) -> tuple[_Sample, ...]:
    return tuple(
        _sample_pool(base, rnd, deck, _pool(order, deck, rnd.pool), position)
        for position, order in enumerate(_shuffles(len(deck)))
    )


def _variant_scores(view: _View, **changes) -> list[float]:
    """Rescore each sample's best play per poker-hand family under a changed build."""

    scores = []
    for position, sample in enumerate(view.samples):
        cards = tuple(_debuffed(view.deck[index], view.rnd) for index in sample.indices)
        scene = _scene(view.base, view.rnd, cards, position, **changes)
        context = _prepare_score_context(scene)
        best = 0.0
        for selection in sample.by_family:
            try:
                score, _ = _score_play_prepared(scene, selection, None, context)
            except ValueError:
                continue
            best = max(best, float(score))
        scores.append(best)
    return scores


def _deck_scores(view: _View, deck, changed: set[int], jokers=None, unchanged=None):
    """Rescore only the sampled hands whose pool contains a changed deck card.

    ``unchanged`` gives each sample's score when its pool is untouched (default: baseline).
    """

    jokers = view.base.jokers if jokers is None else jokers
    unchanged = view.scores if unchanged is None else unchanged
    composition = _composition(deck)
    scores = []
    orders = _shuffles(len(deck))[: len(view.samples)]
    for position, (order, sample) in enumerate(zip(orders, view.samples, strict=True)):
        indices = _pool(order, deck, view.rnd.pool)
        if changed.isdisjoint(indices) and indices == sample.indices:
            scores.append(unchanged[position])
            continue
        scores.append(
            _sample_pool(
                view.base, view.rnd, deck, indices, position, full_deck=composition, jokers=jokers
            ).best
        )
    return scores


def _clear_chance(scores: list[float], hands: int, target: int) -> float:
    if not scores or target <= 0:
        return 1.0
    rng = Random(_SEED + 7)
    wins = sum(sum(rng.choice(scores) for _ in range(hands)) >= target for _ in range(_BOOTSTRAP))
    return round(wins / _BOOTSTRAP, 2)


def _quantile(scores: list[float], fraction: float) -> float:
    ordered = sorted(scores)
    return ordered[min(len(ordered) - 1, int(fraction * (len(ordered) - 1) + 0.5))]


def _mean(scores: list[float]) -> float:
    return sum(scores) / len(scores) if scores else 0.0


def _change(before: list[float], after: list[float]) -> float:
    base = _mean(before)
    return round(_mean(after) / base - 1, 3) if base > 0 else 0.0


def _number(value: float) -> int:
    return int(round(value))


def _blind_row(blind: PublicBlind, rnd: _Round, scores: list[float]) -> dict[str, object]:
    row: dict[str, object] = {
        "blind": blind.name,
        "target": blind.score,
        "hands": rnd.hands,
        "discards": rnd.discards,
        "needed_per_hand": math.ceil(blind.score / rnd.hands),
        "per_hand_median": _number(_quantile(scores, 0.5)),
        "per_hand_p75": _number(_quantile(scores, 0.75)),
        "per_hand_best": _number(max(scores, default=0)),
        "clear_chance": _clear_chance(scores, rnd.hands, blind.score),
    }
    applied = []
    if rnd.debuff_suits or rnd.debuff_ranks or rnd.debuff_faces:
        applied.append("debuffs")
    if rnd.boss is not None:
        applied.append(rnd.boss.name)
    if applied:
        row["boss_effects_applied"] = applied
    return row


def ante_base(ante: int, stake: str) -> int | None:
    """Vanilla base chips for ``ante``; Big is 1.5x and most bosses 2x. None past float range."""

    amounts = _ANTE_BASES[_STAKE_SCALING.get(stake, 1)]
    if ante < 1:
        return 100
    if ante <= 8:
        return amounts[ante - 1]
    extra = ante - 8
    try:
        amount = math.floor(amounts[7] * (1.6 + (0.75 * extra) ** (1 + 0.2 * extra)) ** extra)
    except OverflowError:
        return None
    return amount - amount % (10 ** math.floor(math.log10(amount) - 1))


def _next_ante(observation, blinds, view: _View, rounds, baselines) -> dict[str, object]:
    """The next ante's targets against the build that will still be active by its boss."""

    if observation.ante >= 8 and not observation.won:
        return {}
    base_chips = ante_base(observation.ante + 1, observation.stake)
    if base_chips is None:
        return {}
    plain = next(
        (
            rnd
            for rnd in rounds.values()
            if rnd.boss is None
            and not rnd.debuff_suits
            and not rnd.debuff_ranks
            and not rnd.debuff_faces
        ),
        None,
    )
    if plain is None:
        plain = _Round(
            view.rnd.hands,
            max(0, observation.round.discards_left),
            view.rnd.hand_limit,
            hold=view.rnd.hold,
        )
    samples = baselines.get(plain) or _baseline(view.base, plain, view.deck)
    scores = [sample.best for sample in samples]
    boss = 2 * base_chips
    row: dict[str, object] = {
        "ante": observation.ante + 1,
        "big_target": base_chips * 3 // 2,
        "typical_boss_target": boss,
        "needed_per_hand": math.ceil(boss / plain.hands),
        "per_hand_median": _number(_quantile(scores, 0.5)),
        "boss_clear_chance": _clear_chance(scores, plain.hands, boss),
    }
    # Blinds left this ante, then the next ante's Small, Big and boss (skips ignored).
    rounds_to_boss = len(blinds) + 3
    expiring = [
        joker
        for joker in observation.jokers
        if isinstance(joker, PublicItem)
        and joker.perishable_rounds is not None
        and joker.perishable_rounds < rounds_to_boss
    ]
    if expiring:
        kept = tuple(joker for joker in observation.jokers if joker not in expiring)
        after = _variant_scores(replace(view, rnd=plain, samples=samples), jokers=kept)
        row["expiring_before_boss"] = [joker.key for joker in expiring]
        row["per_hand_median_without_expiring"] = _number(_quantile(after, 0.5))
        row["boss_clear_chance_without_expiring"] = _clear_chance(after, plain.hands, boss)
        scores = after
    median = _quantile(scores, 0.5)
    row["growth_needed"] = round(row["needed_per_hand"] / median, 2) if median > 0 else None
    # The last ante whose boss this build still clears at least half the time, starting
    # with this ante's own focus blind.
    last = observation.ante if view.clear(view.scores) >= 0.5 else observation.ante - 1
    for ante in range(last + 1, (observation.ante + 12) if observation.won else 9):
        if last < observation.ante:
            break
        target = ante_base(ante, observation.stake)
        if target is None or _clear_chance(scores, plain.hands, 2 * target) < 0.5:
            break
        last = ante
    row["build_holds_through_ante"] = last
    return row


def _rounds_until(blinds: list[PublicBlind], target: PublicBlind) -> int:
    """1 when ``target`` is the next blind to play, 2 when one blind comes first, and so on."""

    order = ("SMALL", "BIG", "BOSS")
    return 1 + sum(order.index(blind.kind) < order.index(target.kind) for blind in blinds)


def _joker_rows(observation, blinds, view: _View) -> list[dict[str, object]]:
    rows = []
    for slot, joker in enumerate(observation.jokers):
        if not isinstance(joker, PublicItem):
            continue
        without = observation.jokers[:slot] + observation.jokers[slot + 1 :]
        row: dict[str, object] = {
            "slot": slot,
            "key": joker.key,
            "share_of_score": round(
                -_change(view.scores, _variant_scores(view, jokers=without)), 3
            ),
        }
        if joker.eternal:
            row["eternal"] = True
        if joker.perishable_rounds is not None:
            row["perishable_rounds"] = joker.perishable_rounds
            active = joker.perishable_rounds >= _rounds_until(blinds, view.focus)
            row[f"active_at_{view.focus.kind.lower()}"] = active
        if joker.rental:
            row["rental"] = True
        if joker.edition:
            row["edition"] = joker.edition
        rows.append(row)
    return rows


def _offer_items(observation: PublicObservation):
    for slot, item in enumerate(observation.shop):
        if isinstance(item, PublicItem):
            yield "shop", slot, item
    for slot, item in enumerate(observation.vouchers):
        yield "vouchers", slot, item
    for slot, item in enumerate(observation.opened_pack):
        if isinstance(item, PublicItem):
            yield "opened_pack", slot, item
    for slot, item in enumerate(observation.consumables):
        if item.kind == "PLANET":
            yield "consumables", slot, item


def _offer_rows(observation, view: _View, jokers, budget) -> list[dict[str, object]]:
    before = view.scores
    clear_before = view.clear(before)
    sellable = sorted(
        (row for row in jokers if not row.get("eternal")), key=lambda row: row["share_of_score"]
    )
    rows = []
    for zone, slot, item in _offer_items(observation):
        if item.kind not in {"JOKER", "PLANET", "VOUCHER"}:
            continue
        if not budget.left():
            budget.skipped.append(f"{zone}:{item.key}")
            continue
        row: dict[str, object] = {"zone": zone, "slot": slot, "key": item.key}
        if item.buy_cost is not None and zone != "consumables":
            row["cost"] = item.buy_cost
        hands = view.rnd.hands
        if item.kind == "JOKER":
            current = observation.jokers
            if len(current) >= observation.joker_limit and item.edition != "NEGATIVE":
                if not sellable:
                    row["note"] = "Joker slots are full of eternal Jokers."
                    rows.append(row)
                    continue
                sold = sellable[0]
                row["replaces"] = sold["key"]
                current = current[: sold["slot"]] + current[sold["slot"] + 1 :]
            position, with_item, after = _best_position(view, current, item)
            if position != len(current):
                row["position"] = position
            potential = _engine_potential(
                view, current, with_item, position, item, after, budget, sellable
            )
            if potential:
                row["engine_potential"] = potential
            if item.key in NO_SCORING_EFFECT_JOKERS:
                row["no_direct_score"] = True
            elif item.key not in SCORING_RULE_JOKERS:
                row["not_modelled"] = True
        elif item.kind == "PLANET" and planet_hand(item.key):
            after = _variant_scores(
                view, hand_stats=_level_up(view.base.hand_stats, planet_hand(item.key))
            )
        elif item.key in _HAND_VOUCHERS:
            after, hands = before, view.rnd.hands + _HAND_VOUCHERS[item.key]
        elif item.key in _DISCARD_VOUCHERS or item.key in _HAND_SIZE_VOUCHERS:
            changed = replace(
                view.rnd,
                discards=view.rnd.discards + _DISCARD_VOUCHERS.get(item.key, 0),
                hand_limit=view.rnd.hand_limit + _HAND_SIZE_VOUCHERS.get(item.key, 0),
            )
            after = [sample.best for sample in _baseline(view.base, changed, view.deck)]
        else:
            continue
        row["per_hand_change"] = _change(before, after)
        row[view.label()] = [clear_before, view.clear(after, hands)]
        rows.append(row)
    return rows


def _best_position(view: _View, current, item):
    """Insert ``item`` where it scores best when a copier's target depends on order."""

    copier = item.key in _COPIERS or any(
        isinstance(joker, PublicItem) and joker.key in _COPIERS for joker in current
    )
    positions = range(len(current) + 1) if copier else (len(current),)
    best = None
    for position in positions:
        jokers = (*current[:position], item, *current[position:])
        scores = _variant_scores(view, jokers=jokers)
        if best is None or _mean(scores) > _mean(best[2]):
            best = (position, jokers, scores)
    return best


def _usage(view: _View) -> tuple[Counter, Counter]:
    """How often each deck card is played, and held, in the samples' best plays."""

    played, held = Counter(), Counter()
    for sample in view.samples:
        chosen = {sample.indices[slot.value] for slot in sample.best_selection}
        played.update(chosen)
        held.update(index for index in sample.indices if index not in chosen)
    return played, held


def _feed(view: _View, key: str, jokers) -> tuple[str, list[int]] | None:
    """The deck cards an engine Joker acts on, and whether it wants them held or played.

    Played-card rules come from the scorer itself, so every modelled per-card Joker
    is covered; an empty held list means any card kept in hand.
    """

    deck, base = view.deck, view.base
    cards = [(index, card) for index, card in enumerate(deck) if card is not None]
    if key in _HELD_RANKS:
        return "held", [index for index, card in cards if card.rank == _HELD_RANKS[key]]
    if key in _HELD_STEEL_JOKERS:
        ranks = {
            _HELD_RANKS[j.key] for j in jokers if isinstance(j, PublicItem) and j.key in _HELD_RANKS
        }
        return "held", [index for index, card in cards if card.rank in ranks]
    item = PublicItem(key, key, "JOKER")
    keys = frozenset({key})
    if key in _PLAYED_INDIVIDUAL_ADDITIVE_JOKERS:
        return "played", [i for i, c in cards if _card_joker_effect(key, (c,), keys) != (0, 0)]
    if key in _PLAYED_INDIVIDUAL_XMULT_JOKERS:
        return "played", [
            i
            for i, c in cards
            if _individual_joker_card_xmult(base, c, item, first_face=c.rank in _FACE_RANKS) != 1
        ]
    if key in _PLAYED_RETRIGGER_JOKERS:
        return "played", [i for i, c in cards if _card_repetitions(base, c, 0, (item,), keys) > 0]
    return None


def _fuel(deck, kind: str, feed: list[int], played: Counter, held: Counter, edits: int):
    """Apply the feeding edits: Chariot (Steel) for held engines, Justice (Glass) for played.

    Feed cards are edited first; the rest are Death or Strength copies of an edited feed
    card made from the cards the build uses least.
    """

    edit = "STEEL" if kind == "held" else "GLASS"
    use = held if kind == "held" else played
    if not feed:
        feed = sorted(
            (i for i, card in enumerate(deck) if card is not None and card.rank != "?"),
            key=lambda i: (-use[i], i),
        )[:edits]
    order = sorted(feed, key=lambda i: (-use[i], i))
    variant, changed = list(deck), set()
    for index in order:
        if len(changed) >= edits:
            break
        if deck[index].enhancement not in {edit, "STONE"}:
            variant[index] = replace(deck[index], enhancement=edit)
            changed.add(index)
    copies = 0
    if order and len(changed) < edits:
        model = replace(deck[order[0]], enhancement=edit)
        spare = sorted(
            (
                i
                for i, c in enumerate(deck)
                if c is not None and i not in feed and not c.enhancement
            ),
            key=lambda i: (played[i] + held[i], i),
        )
        for index in spare[: edits - len(changed)]:
            variant[index] = model
            changed.add(index)
            copies += 1
    return tuple(variant), changed, [deck[i] for i in order], copies


def _describe(cards: list[VisiblePlayingCard]) -> str:
    ranks = {card.rank for card in cards}
    suits = {card.suit for card in cards}
    if len(ranks) == 1 and next(iter(ranks)) in _RANK_NAMES:
        return _RANK_NAMES[next(iter(ranks))]
    if ranks and ranks <= _FACE_RANKS:
        return "face cards"
    if len(suits) == 1 and next(iter(suits)) in _SUIT_NAMES:
        return _SUIT_NAMES[next(iter(suits))]
    return "the cards it rewards" if cards else "cards kept in hand"


def _engine_potential(
    view: _View, current, with_item, position: int, item, after, budget, sellable=()
):
    """Price an engine Joker on decks fed for it, against the current build on those decks.

    An engine sits where an owned copier repeats it, since that is how engines compound.
    """

    key = item.key
    if key not in _COPIERS:
        for index, joker in enumerate(current):
            if isinstance(joker, PublicItem) and joker.key in _COPIERS:
                position = index + 1 if joker.key == "j_blueprint" else len(current)
                with_item = (*current[:position], item, *current[position:])
                after = _variant_scores(view, jokers=with_item)
                break
    if key in _COPIERS:
        # A copier's potential is the potential of the Joker it copies.
        targets = with_item[position + 1 : position + 2] if key == "j_blueprint" else with_item[:1]
        if not targets or not isinstance(targets[0], PublicItem):
            return None
        key = targets[0].key
    if not budget.left():
        budget.skipped.append(f"engine_potential:{item.key}")
        return None
    feed = _feed(view, key, with_item)
    if feed is None:
        return None
    kind, cards = feed
    played, held = _usage(view)
    small = replace(view, samples=view.samples[:_POTENTIAL_SAMPLES])
    after = after[:_POTENTIAL_SAMPLES]
    tarot = "Chariot (Steel)" if kind == "held" else "Justice (Glass)"
    result: dict[str, object] = {}
    for edits in _POTENTIAL_EDITS:
        if not budget.left():
            break
        deck, changed, fed, copies = _fuel(view.deck, kind, cards, played, held, edits)
        if not changed:
            break
        with_scores = _deck_scores(small, deck, changed, with_item, after)
        without = _deck_scores(small, deck, changed, None, view.scores[:_POTENTIAL_SAMPLES])
        result.setdefault("fuel", f"{tarot} on {_describe(fed if cards else [])}")
        result[f"after_{len(changed)}_edits"] = {
            "per_hand_median": _number(_quantile(with_scores, 0.5)),
            "per_hand_change": _change(without, with_scores),
            "copies_needed": copies,
        }
    partner = _PARTNERS.get(key)
    owned = {getattr(joker, "key", None) for joker in with_item}
    if result and partner and partner not in owned and budget.left():
        paired = _with_partner(view, with_item, item, partner, sellable)
        if paired is not None:
            unchanged = _variant_scores(small, jokers=paired)
            paired_scores = _deck_scores(small, deck, changed, paired, unchanged)
            result[f"with_{partner}_after_{len(changed)}_edits"] = {
                "per_hand_median": _number(_quantile(paired_scores, 0.5)),
                "per_hand_change": _change(without, paired_scores),
                "note": f"hypothetical: {partner} is not owned or offered here",
            }
    return result or None


def _with_partner(view: _View, with_item, item, partner: str, sellable):
    """The build with ``partner`` added, selling the weakest sellable Joker if slots are full."""

    jokers = list(with_item)
    if len(jokers) >= view.base.joker_limit:
        weakest = next(
            (
                row["key"]
                for row in sellable
                if row["key"] in {j.key for j in jokers} and row["key"] != item.key
            ),
            None,
        )
        if weakest is None:
            return None
        jokers.remove(next(j for j in jokers if j.key == weakest))
    return (*jokers, PublicItem(partner, partner, "JOKER"))


def _level_up(stats: tuple[HandStat, ...], family: str) -> tuple[HandStat, ...]:
    chips, mult = _HAND_LEVEL_GAINS[family]
    return tuple(
        replace(stat, level=stat.level + 1, chips=stat.chips + chips, mult=stat.mult + mult)
        if stat.name == family
        else stat
        for stat in stats
    )


def _apply_tarot(key: str, card: VisiblePlayingCard) -> VisiblePlayingCard | None:
    """The card after the Tarot, or None when the Tarot destroys it."""

    if key == "c_hanged_man":
        return None
    card = replace(card, effect_text="", debuffed=False)
    if key == "c_deja_vu":
        return replace(card, seal="RED")
    if key in _ENHANCEMENT_TAROTS:
        enhancement = _ENHANCEMENT_TAROTS[key]
        if enhancement == "STONE":
            return replace(
                card,
                rank=OBSCURED_CARD_ATTRIBUTE,
                suit=OBSCURED_CARD_ATTRIBUTE,
                enhancement="STONE",
            )
        if card.enhancement == "STONE":
            return card
        return replace(card, enhancement=enhancement)
    if card.enhancement == "STONE":
        return card
    if key in _SUIT_TAROTS:
        return replace(card, suit=_SUIT_TAROTS[key])
    if key == "c_strength":
        return replace(card, rank=_NEXT_RANK[card.rank])
    return card


def _hand_indices(observation: PublicObservation, deck) -> dict[int, int]:
    """Map visible hand slots to matching deck cards, for Tarots chosen from an open pack."""

    free = {}
    for index, card in enumerate(deck):
        free.setdefault(card, []).append(index)
    mapped = {}
    for slot, card in enumerate(observation.hand):
        if not isinstance(card, VisiblePlayingCard):
            continue
        key = replace(card, effect_text="", debuffed=False)
        if free.get(key):
            mapped[slot] = free[key].pop(0)
    return mapped


def _deck_tarot_rows(observation, view: _View, budget) -> list[dict[str, object]]:
    """Greedy deck targets for each visible Tarot, from the cards the build plays most.

    A pack Tarot is limited to the visible hand, which is where its targets must come from.
    """

    items = [
        (zone, slot, item)
        for zone, entries in (
            ("consumables", observation.consumables),
            ("shop", observation.shop),
            ("opened_pack", observation.opened_pack),
        )
        for slot, item in enumerate(entries)
        if isinstance(item, PublicItem) and item.key in _DECK_TAROTS
    ]
    if not items:
        return []
    deck = view.deck
    usage = Counter(
        sample.indices[slot.value] for sample in view.samples for slot in sample.best_selection
    )
    in_hand = _hand_indices(observation, deck) if observation.phase == Phase.PACK else {}
    rows = []
    for zone, slot, item in items:
        if not budget.left():
            budget.skipped.append(f"{zone}:{item.key}")
            continue
        pool = list(in_hand.values()) if zone == "opened_pack" else list(range(len(deck)))
        if not pool:
            continue
        if item.key == "c_hanged_man":
            # Thinning removes the cards the build plays least.
            pool.sort(key=lambda index: (usage[index], index))
        else:
            fed = _owned_feed(view, item.key)
            pool.sort(key=lambda index: (index not in fed, -usage[index], index))
        candidates, seen = [], set()
        for index in pool:
            if _apply_tarot(item.key, deck[index]) == deck[index] or deck[index] in seen:
                continue
            seen.add(deck[index])
            candidates.append(index)
            if len(candidates) >= _DECK_CANDIDATES:
                break
        gains = []
        for index in candidates:
            if not budget.left():
                break
            variant = list(deck)
            variant[index] = _apply_tarot(item.key, deck[index])
            gain = _mean(_deck_scores(view, tuple(variant), {index})) - _mean(view.scores)
            if gain > 0:
                gains.append((gain, index))
        row: dict[str, object] = {"zone": zone, "slot": slot, "key": item.key}
        gains.sort(reverse=True)
        chosen = [index for _, index in gains[: _TAROT_MAX_TARGETS.get(item.key, 1)]]
        if not chosen:
            row["note"] = "No tested target raised per-hand score for this build."
            rows.append(row)
            continue
        variant = list(deck)
        for index in chosen:
            variant[index] = _apply_tarot(item.key, deck[index])
        after = _deck_scores(view, tuple(variant), set(chosen))
        row["targets"] = [_card_code(deck[index]) for index in chosen]
        if zone == "opened_pack":
            row["hand_slots"] = sorted(
                hand_slot for hand_slot, index in in_hand.items() if index in chosen
            )
        row["per_hand_change"] = _change(view.scores, after)
        row[view.label()] = [view.clear(view.scores), view.clear(after)]
        rows.append(row)
    return rows


def _owned_feed(view: _View, tarot: str) -> set[int]:
    """Deck cards that owned engines feed on, for the Tarot that makes their fuel."""

    kind = {"c_chariot": "held", "c_justice": "played"}.get(tarot)
    if kind is None:
        return set()
    fed: set[int] = set()
    for joker in view.base.jokers:
        if isinstance(joker, PublicItem) and not joker.debuffed:
            feed = _feed(view, joker.key, view.base.jokers)
            if feed is not None and feed[0] == kind:
                fed.update(feed[1])
    return fed


def _card_code(card: VisiblePlayingCard) -> str:
    code = f"{card.rank}{card.suit}"
    if card.enhancement:
        code += f"+{card.enhancement.lower()}"
    if card.edition:
        code += f"/{card.edition.lower()}"
    if card.seal:
        code += f"*{card.seal.lower()}"
    return code


def _best_visible_play(observation: PublicObservation, hand: tuple) -> float:
    """Best legal play of ``hand``, which keeps the observation's slots (Cerulean Bell's forced card)."""

    scene = replace(observation, hand=hand)
    limit = min(5, observation.selection_limit or 5, len(hand))
    forced = {HandSlot(index) for index in observation.required_hand_slots}
    selections = tuple(
        selection
        for selection in _selections(len(hand), tuple(range(1, limit + 1)))
        if forced.issubset(selection)
    )
    best, _, _ = _score_pool(scene, selections)
    return best
