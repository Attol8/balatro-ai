"""Bounded, public-only numerical advice for one Balatro decision."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from balatro_ai.game.actions import (
    DiscardCards,
    HandSlot,
    JokerSlot,
    PlayCards,
    PublicAction,
    ReorderHand,
    ReorderJokers,
    action_to_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai.game.scoring import (
    _prepare_score_context,
    _score_play_prepared,
    _scoring_cards,
)
from balatro_ai.game.state import (
    HiddenHandCard,
    HiddenJokerSlot,
    Phase,
    PublicItem,
    PublicObservation,
    VisiblePlayingCard,
)

_MAX_PLAY_CANDIDATES = 16  # Thirteen hand families plus three preservation views.
_MAX_STRATEGIC_ACTIONS = 24
_MAX_REORDER_SUGGESTIONS = 4
_FACE_RANKS = frozenset({"J", "Q", "K"})
_BLACK_SUITS = frozenset({"S", "C"})
_COPY_ENGINE_KEYS = frozenset({
    "j_card_sharp", "j_hologram", "j_constellation", "j_ramen",
    "j_blackboard", "j_photograph", "j_hanging_chad", "j_stuntman",
    "j_mime", "j_baron",
})


def analyze(observation: PublicObservation) -> dict[str, object]:
    """Describe bounded legal choices without choosing an action.

    The caller may submit any separately validated raw action; the shortlist is
    context for the model, not an action allow-list.
    """

    plays, reorder = _play_advice(observation)
    strategic, omitted = _strategic_actions(observation)
    result: dict[str, object] = {
        "play_candidates": plays,
        "reorder_suggestions": reorder,
        "strategic_actions": strategic,
        "strategic_actions_omitted": omitted,
        "shortlist_is_not_allowlist": True,
        "mechanism_reminders": _mechanism_reminders(observation),
    }
    opportunities = _engine_opportunities(observation)
    if opportunities:
        result["engine_opportunities"] = opportunities
    if observation.phase == Phase.SELECTING_HAND and not plays:
        if any(isinstance(card, HiddenHandCard) for card in observation.hand):
            result["numerical_play_status"] = "unavailable: hand contains hidden cards"
        elif any(isinstance(joker, HiddenJokerSlot) for joker in observation.jokers):
            result["numerical_play_status"] = "unavailable: Joker identities/order are hidden"
    if observation.phase == Phase.SELECTING_HAND:
        result["discard_note"] = (
            "Discards require model choice; no discard outcome search is available."
        )
    return result


def _play_advice(
    observation: PublicObservation,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if observation.phase != Phase.SELECTING_HAND:
        return [], []
    if any(isinstance(card, HiddenHandCard) for card in observation.hand):
        return [], []
    if any(isinstance(joker, HiddenJokerSlot) for joker in observation.jokers):
        return [], []

    context = _prepare_score_context(observation)
    scored: list[tuple[PlayCards, int | Fraction, str]] = []
    for action in iter_legal_actions(observation):
        if isinstance(action, PlayCards):
            score, family = _score_play_prepared(
                observation, action.cards, None, context
            )
            scored.append((action, score, family))

    by_family: dict[str, tuple[PlayCards, int | Fraction, str]] = {}
    for row in scored:
        previous = by_family.get(row[2])
        if previous is None or (row[1], _play_tiebreak(row[0])) > (
            previous[1], _play_tiebreak(previous[0])
        ):
            by_family[row[2]] = row

    chosen = sorted(by_family.values(), key=_scored_sort_key, reverse=True)
    # Preserve alternatives relevant to growth and held-card engines even when
    # their immediate family score loses to the same family's strongest play.
    for predicate in (_bus_safe, _holds_valuable_cards, _holds_black_hand):
        alternatives = [row for row in scored if predicate(observation, row)]
        if alternatives:
            candidate = max(alternatives, key=_scored_sort_key)
            if candidate not in chosen:
                chosen.append(candidate)
    chosen = sorted(chosen, key=_scored_sort_key, reverse=True)[:_MAX_PLAY_CANDIDATES]
    candidates = [_play_entry(observation, *row) for row in chosen]
    reorder = _reorder_advice(observation, chosen[:3])
    return candidates, reorder


def _play_entry(
    observation: PublicObservation,
    action: PlayCards,
    score: int | Fraction,
    family: str,
) -> dict[str, object]:
    selected = tuple(observation.hand[slot.value] for slot in action.cards)
    assert all(isinstance(card, VisiblePlayingCard) for card in selected)
    visible = tuple(card for card in selected if isinstance(card, VisiblePlayingCard))
    splash = _active_joker(observation, "j_splash")
    scoring = visible if splash else _scoring_cards(visible, family)
    scoring_slots = _matching_slots(action.cards, visible, scoring)
    scoring_set = set(scoring_slots)
    pareidolia = _active_joker(observation, "j_pareidolia")
    held = [
        (index, card)
        for index, card in enumerate(observation.hand)
        if index not in {slot.value for slot in action.cards}
        and isinstance(card, VisiblePlayingCard)
    ]
    scoring_faces = [
        slot
        for slot in scoring_slots
        if not observation.hand[slot].debuffed
        and (pareidolia or observation.hand[slot].rank in _FACE_RANKS)
    ]
    bus_reset = [
        slot
        for slot in scoring_slots
        if not observation.hand[slot].debuffed
        and observation.hand[slot].rank in _FACE_RANKS
    ]
    return {
        "action": action_to_data(action),
        "estimated_score": _json_score(score),
        "family": family,
        "approximation": _score_approximation(observation),
        "facts": {
            "scoring_slots": scoring_slots,
            "scoring_faces": scoring_faces,
            "harmless_kickers": [
                slot.value for slot in action.cards if slot.value not in scoring_set
            ],
            "ride_the_bus_reset_slots": bus_reset,
            "ride_the_bus_interaction_uncertain": _active_joker(
                observation, "j_ride_the_bus"
            ) and (pareidolia or splash),
            "pareidolia_active": pareidolia,
            "splash_active": splash,
            "held_blue_seal_slots": [i for i, card in held if card.seal == "BLUE"],
            "held_steel_slots": [i for i, card in held if card.enhancement == "STEEL"],
            "held_cards_all_black": all(
                card.suit in _BLACK_SUITS for _, card in held
            ),
            "boss_scoring_restriction": _boss_scoring_restriction(
                observation, score
            ),
        },
    }


def _matching_slots(
    slots: tuple[HandSlot, ...],
    selected: tuple[VisiblePlayingCard, ...],
    wanted: tuple[VisiblePlayingCard, ...],
) -> list[int]:
    remaining = list(wanted)
    result: list[int] = []
    for slot, card in zip(slots, selected, strict=True):
        try:
            index = remaining.index(card)
        except ValueError:
            continue
        result.append(slot.value)
        remaining.pop(index)
    return result


def _reorder_advice(
    observation: PublicObservation,
    plays: list[tuple[PlayCards, int | Fraction, str]],
) -> list[dict[str, object]]:
    suggestions: list[dict[str, object]] = []
    for play, baseline, _ in plays:
        physical = tuple(sorted(play.cards, key=lambda slot: slot.value))
        for area, slot_type, action_type in (
            ("jokers", JokerSlot, ReorderJokers),
            ("hand", HandSlot, ReorderHand),
        ):
            items = getattr(observation, area)
            for index in range(len(items) - 1):
                order = list(range(len(items)))
                order[index], order[index + 1] = order[index + 1], order[index]
                action = action_type(tuple(slot_type(value) for value in order))
                if not is_legal(observation, action):
                    continue
                after = replace(observation, **{area: tuple(items[value] for value in order)})
                mapped = physical if area == "jokers" else tuple(
                    HandSlot(value)
                    for value in sorted(order.index(slot.value) for slot in physical)
                )
                try:
                    score, family = _score_play_prepared(
                        after, mapped, None, _prepare_score_context(after)
                    )
                except ValueError:
                    continue
                if score > baseline:
                    suggestions.append({
                        "action": action_to_data(action),
                        "then_play": action_to_data(PlayCards(mapped)),
                        "family": family,
                        "baseline_score": _json_score(baseline),
                        "reordered_score": _json_score(score),
                        "approximation": _score_approximation(observation),
                        "selected_before": [slot.value for slot in physical],
                        "selected_after": [slot.value for slot in mapped],
                        "note": "Optional adjacent reorder; reassess after it settles.",
                    })
    suggestions.sort(key=lambda row: float(row["reordered_score"]), reverse=True)
    return suggestions[:_MAX_REORDER_SUGGESTIONS]


def _strategic_actions(
    observation: PublicObservation,
) -> tuple[list[dict[str, object]], int]:
    actions: list[PublicAction] = []
    for action in iter_legal_actions(observation):
        if isinstance(action, (PlayCards, DiscardCards)):
            continue
        actions.append(action)
    shown = actions[:_MAX_STRATEGIC_ACTIONS]
    return [action_to_data(action) for action in shown], len(actions) - len(shown)


def _mechanism_reminders(observation: PublicObservation) -> list[str]:
    reminders: list[str] = []
    keys = {
        joker.key
        for joker in observation.jokers
        if isinstance(joker, PublicItem) and not joker.debuffed
    }
    if "j_ride_the_bus" in keys:
        reminders.append("Ride the Bus resets only when a non-debuffed J/Q/K scores.")
    if "j_blueprint" in keys:
        reminders.append("Blueprint copies the compatible Joker immediately to its right; recheck its target.")
    if "j_hologram" in keys:
        reminders.append("Hologram's displayed public runtime is included in numerical scores.")
    if "j_blackboard" in keys:
        reminders.append("Blackboard requires every held card to be Spades or Clubs.")
    if any(isinstance(card, VisiblePlayingCard) and card.seal == "BLUE" for card in observation.hand):
        reminders.append("A Blue Seal held at round end can create the planet for the played hand.")
    if any(isinstance(card, VisiblePlayingCard) and card.enhancement == "STEEL" for card in observation.hand):
        reminders.append("A non-debuffed Steel card scores x1.5 Mult while held.")
    boss = next((blind for blind in observation.blinds if blind.kind == "BOSS" and blind.status in {"UPCOMING", "SELECT"}), None)
    if boss is not None:
        reminders.append(f"Next visible boss: {boss.name}: {boss.effect}")
    return reminders


def _active_joker(observation: PublicObservation, key: str) -> bool:
    return any(
        isinstance(joker, PublicItem) and joker.key == key and not joker.debuffed
        for joker in observation.jokers
    )


def _score_approximation(observation: PublicObservation) -> str:
    stochastic = {
        joker.key
        for joker in observation.jokers
        if isinstance(joker, PublicItem) and not joker.debuffed
        and joker.key in {"j_misprint", "j_bloodstone"}
    }
    notes = [
        "Retained public scorer estimate; integer rounding, random outcomes, and unsupported effects may differ in game."
    ]
    if stochastic:
        names = ", ".join(
            sorted(
                key.removeprefix("j_").replace("_", " ").title()
                for key in stochastic
            )
        )
        notes.append(f"Uses expected values for stochastic {names} effects.")
    if any(
        isinstance(card, VisiblePlayingCard) and card.enhancement == "LUCKY"
        for card in observation.hand
    ):
        notes.append("Lucky Card random Mult and money triggers are omitted.")
    if _active_joker(observation, "j_ride_the_bus") and (
        _active_joker(observation, "j_pareidolia")
        or _active_joker(observation, "j_splash")
    ):
        notes.append(
            "Ride the Bus with Pareidolia or Splash follows the retained scorer; treat reset safety as uncertain."
        )
    return " ".join(notes)


def _bus_safe(observation: PublicObservation, row: tuple[PlayCards, int | Fraction, str]) -> bool:
    if not _active_joker(observation, "j_ride_the_bus"):
        return False
    if _active_joker(observation, "j_pareidolia") or _active_joker(
        observation, "j_splash"
    ):
        return False
    entry = _play_entry(observation, *row)
    return not entry["facts"]["ride_the_bus_reset_slots"]


def _holds_valuable_cards(observation: PublicObservation, row: tuple[PlayCards, int | Fraction, str]) -> bool:
    selected = {slot.value for slot in row[0].cards}
    return any(
        index not in selected
        and isinstance(card, VisiblePlayingCard)
        and (card.seal == "BLUE" or card.enhancement == "STEEL")
        for index, card in enumerate(observation.hand)
    )


def _holds_black_hand(observation: PublicObservation, row: tuple[PlayCards, int | Fraction, str]) -> bool:
    if not _active_joker(observation, "j_blackboard"):
        return False
    selected = {slot.value for slot in row[0].cards}
    held = [card for index, card in enumerate(observation.hand) if index not in selected]
    return all(
        isinstance(card, VisiblePlayingCard) and card.suit in _BLACK_SUITS for card in held
    )


def _play_tiebreak(action: PlayCards) -> tuple[int, tuple[int, ...]]:
    return (-len(action.cards), tuple(-slot.value for slot in action.cards))


def _scored_sort_key(row: tuple[PlayCards, int | Fraction, str]) -> tuple[object, ...]:
    return (row[1], _play_tiebreak(row[0]), row[2])


def _json_score(score: int | Fraction) -> int | float:
    return score.numerator if isinstance(score, Fraction) and score.denominator == 1 else float(score)


def _boss_scoring_restriction(
    observation: PublicObservation, score: int | Fraction
) -> str | None:
    if score != 0:
        return None
    boss = next(
        (
            blind
            for blind in observation.blinds
            if blind.kind == "BOSS"
            and blind.status == "CURRENT"
            and not blind.disabled
            and blind.name in {"The Psychic", "The Eye", "The Mouth"}
        ),
        None,
    )
    if boss is None:
        return None
    return f"{boss.name} suppresses this play's score under its active restriction; the legal action can intentionally waste a hand."


def _engine_opportunities(observation: PublicObservation) -> list[dict[str, object]]:
    deck_known = bool(observation.full_deck) and observation.deck_size > 0
    steel = kings = faces = enhanced = 0
    if deck_known:
        for entry in observation.full_deck:
            card, count = entry.card, entry.count
            steel += count if card.enhancement == "STEEL" else 0
            kings += count if card.rank == "K" else 0
            faces += count if card.rank in _FACE_RANKS else 0
            enhanced += count if (
                card.enhancement in {"BONUS", "MULT", "GLASS", "LUCKY"}
                or card.edition is not None
                or card.seal == "RED"
            ) else 0
    copy_targets = [
        joker.key for joker in observation.jokers
        if isinstance(joker, PublicItem)
        and not joker.debuffed
        and joker.key in _COPY_ENGINE_KEYS
    ]
    full = len(observation.jokers) >= observation.joker_limit
    offers = (
        [("shop", slot, item) for slot, item in enumerate(observation.shop)]
        + [("opened_pack", slot, item) for slot, item in enumerate(observation.opened_pack)]
    )
    result: list[dict[str, object]] = []
    for zone, slot, item in offers:
        if not isinstance(item, PublicItem) or item.kind != "JOKER":
            continue
        support: dict[str, object]
        mechanism: str
        tradeoff: str
        if item.key == "j_mime" and deck_known and steel:
            support = {"steel_cards_in_public_deck": steel}
            mechanism = "Mime retriggers held-card abilities; drawn Steel cards can apply held XMult again."
            tradeoff = "Value depends on drawing and holding Steel instead of scoring it."
        elif item.key == "j_baron" and deck_known and kings:
            support = {"kings_in_public_deck": kings}
            mechanism = "Baron gives X1.5 Mult for each King held in hand."
            tradeoff = "Value depends on drawing and holding Kings."
        elif item.key == "j_hanging_chad" and deck_known and enhanced:
            support = {"enhanced_scoring_cards_in_public_deck": enhanced}
            mechanism = "Hanging Chad retriggers the first scoring card twice."
            tradeoff = "Gain depends on making a supported enhanced card score first."
        elif item.key == "j_photograph" and deck_known and faces:
            support = {"face_cards_in_public_deck": faces}
            mechanism = "Photograph gives X2 Mult when the first played face card scores."
            tradeoff = "Gain requires a non-debuffed face card to score."
        elif item.key in {"j_hologram", "j_constellation"}:
            runtime = item.runtime.current_x_mult if item.runtime is not None else None
            support = {"displayed_current_x_mult": runtime}
            mechanism = (
                "Hologram grows when playing cards are added to the deck."
                if item.key == "j_hologram"
                else "Constellation grows when Planet cards are used."
            )
            tradeoff = "This is a scaling route, not a guaranteed immediate gain; compare its displayed runtime."
        elif item.key in {"j_blueprint", "j_brainstorm"} and copy_targets:
            support = {"visible_compatible_engine_keys": copy_targets}
            mechanism = "This copier can repeat a visible compatible scoring engine when positioned correctly."
            tradeoff = "Compatibility and target position must be rechecked after acquisition."
        else:
            continue
        row: dict[str, object] = {
            "zone": zone, "slot": slot, "key": item.key,
            "support": support, "mechanism": mechanism, "tradeoff": tradeoff,
        }
        if full and item.edition != "NEGATIVE":
            row["capacity"] = (
                "Joker slots are full: selling is a separate action; observe the fresh state before buying or choosing this offer."
            )
        result.append(row)
        if len(result) == 6:
            break
    return result
