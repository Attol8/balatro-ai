"""Preparation from public boss information, with a deliberately narrow score ceiling."""

from collections import Counter
from dataclasses import fields, replace
from functools import lru_cache
from itertools import combinations_with_replacement

from balatro_ai.game.actions import HandSlot
from balatro_ai.game.scoring import score_play
from balatro_ai.game.state import Phase, PublicItem, PublicObservation, VisiblePlayingCard

_RANKS = tuple("23456789TJQKA")
_SUITS = tuple("SHCD")
_FAMILIES = {
    "High Card",
    "Pair",
    "Two Pair",
    "Three of a Kind",
    "Straight",
    "Flush",
    "Full House",
    "Four of a Kind",
    "Straight Flush",
}
_JOKERS = {
    "j_joker",
    "j_green_joker",
    "j_blue_joker",
    "j_trousers",
    "j_supernova",
    "j_sock_and_buskin",
    "j_walkie_talkie",
}
_HINTS = {
    "The Needle": "Exactly one hand: prepare one-hand scoring and reliable access to it; extra normal hands do not help.",
    "The Wall": "Larger target: prepare enough total scoring across the available hands.",
    "Violet Vessel": "Much larger target: prepare scalable scoring and enough total output across the available hands.",
    "The Plant": "Face cards are debuffed: prepare scoring that does not depend on their chips or effects.",
    "The Psychic": "Every play must select five cards; retain enough filler alongside the scoring cards.",
    "The Eye": "Do not repeat a poker-hand family this round; prepare several scoring families.",
    "The Mouth": "Only one poker-hand family this round; choose a repeatable family before the first play.",
    "The Flint": "Base poker-hand chips and Mult are halved; assess scoring after that reduction.",
    "The Water": "Start with zero discards; prepare consistency without relying on discard draws.",
    "The Manacle": "Hand size is reduced by one; prepare combinations reachable with fewer held cards.",
}


def _unsupported(obs: PublicObservation, current: bool) -> str | None:
    if obs.deck not in {"RED", "BLUE", "YELLOW", "GREEN", "BLACK"}:
        return "deck scoring rules outside the supported scope"
    if obs.consumables:
        return "owned consumables could change scoring or the build"
    if (
        len(obs.full_deck) != 52
        or obs.deck_size != 52
        or {(e.card.rank, e.card.suit) for e in obs.full_deck}
        != {(rank, suit) for rank in _RANKS for suit in _SUITS}
        or any(
            e.count != 1
            or e.card.enhancement
            or e.card.edition
            or e.card.seal
            or e.card.debuffed
            or e.card.permanent_bonus
            for e in obs.full_deck
        )
    ):
        return "requires an unmodified standard 52-card deck"
    if any(
        (
            isinstance(card, VisiblePlayingCard)
            and (
                card.enhancement
                or card.edition
                or card.seal
                or card.debuffed
                or card.permanent_bonus
            )
        )
        or (current and not isinstance(card, VisiblePlayingCard))
        for card in obs.hand
    ):
        return "modified or hidden held cards are outside the supported scope"
    stats = obs.hand_stats
    if (
        not _FAMILIES.issubset({s.name for s in stats})
        or len({s.name for s in stats}) != len(stats)
        or any(
            not all(type(v) is int and v >= 0 for v in (s.chips, s.mult, s.played)) for s in stats
        )
    ):
        return "complete nonnegative public hand scoring values are required"
    for joker in obs.jokers:
        if (
            not isinstance(joker, PublicItem)
            or joker.key not in _JOKERS
            or joker.debuffed
            or joker.edition not in {None, "FOIL", "HOLO", "HOLOGRAPHIC", "NEGATIVE"}
        ):
            return "unsupported or debuffed Joker or edition"
        runtime = joker.runtime
        if joker.key in {"j_green_joker", "j_trousers"}:
            if runtime is None or type(runtime.current_mult) is not int or runtime.current_mult < 0:
                return "scaling Joker runtime is unavailable"
            if any(
                getattr(runtime, f.name) is not None
                for f in fields(runtime)
                if f.name != "current_mult"
            ):
                return "unsupported additional Joker runtime"
        elif runtime is not None:
            return "unsupported Joker runtime"
    if current and (
        obs.round.hands_left != 1
        or obs.round.hands_played != 0
        or obs.round.chips != 0
        or not 0 <= obs.draw_count <= 52
    ):
        return "requires the current Needle before its only play"
    return None


@lru_cache(maxsize=16)
def _ceiling(obs: PublicObservation) -> tuple[int, str]:
    """Exhaust rank multisets and flush/nonflush classes; no draw-order input.

    Allowlisted effects ignore suit identity, held cards and selection order.
    Duplicate ranks cannot flush in this deck. Free choice from the entire deck
    and a frozen optimistic draw pile only enlarge the attainable set.
    """
    best, family = -1, ""
    for count in range(1, 6):
        slots = tuple(HandSlot(i) for i in range(count))
        for ranks in combinations_with_replacement(_RANKS, count):
            if max(Counter(ranks).values()) > 4:
                continue
            used = Counter()
            cards = []
            for rank in ranks:
                cards.append(VisiblePlayingCard(rank, _SUITS[used[rank]]))
                used[rank] += 1
            representatives = [tuple(cards)]
            if count == 5 and len(used) == 5:
                representatives.append((replace(cards[0], suit="H"), *cards[1:]))
            for hand in representatives:
                score, name = score_play(replace(obs, hand=hand), slots)
                if score > best:
                    best, family = int(score), name
    return best, family


def boss_readiness(observation: PublicObservation) -> dict:
    """Return public preparation advice; unavailable numerical analysis stays explicit."""
    if observation.phase not in {Phase.SHOP, Phase.PACK, Phase.BLIND_SELECT, Phase.SELECTING_HAND}:
        return {}
    bosses = [
        b
        for b in observation.blinds
        if b.kind == "BOSS" and b.status in {"UPCOMING", "SELECT", "CURRENT"}
    ]
    if len(bosses) != 1:
        return {}
    boss = bosses[0]
    current = boss.status == "CURRENT"
    if observation.phase == Phase.SELECTING_HAND and not current:
        return {}
    result = {
        "boss": boss.name,
        "effect": boss.effect,
        "target": boss.score,
        "status": "current" if current else "upcoming",
        "disabled": boss.disabled,
        "preparation": _HINTS.get(
            boss.name, "Prepare for the publicly visible boss effect and target."
        ),
        "ceiling_available": False,
    }
    if boss.disabled:
        result["preparation"] = (
            "The current boss effect is disabled; the visible score target still applies."
        )
        return result
    if boss.name != "The Needle":
        return result
    reason = _unsupported(observation, current)
    if reason:
        result["ceiling_unavailable_reason"] = reason
        return result
    # A future round's draw count is not yet known. 52 overstates Blue Joker,
    # safely avoiding accidental reuse of the just-completed round's draw pile.
    snapshot = replace(observation, blinds=(), draw_count=observation.draw_count if current else 52)
    ceiling, family = _ceiling(snapshot)
    result.update(
        {
            "ceiling_available": True,
            "current_build_optimistic_one_hand_ceiling": ceiling,
            "best_family": family,
            "snapshot_ceiling_below_target": ceiling < boss.score,
            "scope": "Snapshot-only ceiling within the public scorer for the current build, hand levels and played counts. "
            "Allows any cards from the whole deck and optimistic Blue Joker chips; includes same-play growth. "
            "Not a future win probability or a bound on future build growth. Reaching the ceiling is not guaranteed.",
            "preparation_note": "Further shops, packs and intervening hands can change this snapshot; "
            "Green Joker, Spare Trousers and Supernova can still grow before the boss."
            if not current
            else "Frozen current counters and draw count are optimistic: discards can reduce Green Joker and Blue Joker.",
        }
    )
    return result
