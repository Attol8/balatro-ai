"""Bounded resource and copier advice from the current public observation."""

from balatro_ai.game.actions import (
    DiscardCards,
    HandSlot,
    JokerSlot,
    ReorderJokers,
    action_to_data,
    is_legal,
)
from balatro_ai.game.state import (
    HiddenJokerSlot,
    Phase,
    PublicItem,
    PublicObservation,
    VisiblePlayingCard,
)


def round_production(observation: PublicObservation, plays: list[dict]) -> dict:
    """Expose opportunities, not a claim that an unknown subsequent draw is safe."""
    if observation.phase != Phase.SELECTING_HAND:
        return {}
    current = next((blind for blind in observation.blinds if blind.status == "CURRENT"), None)
    needed = max(0, current.score - observation.round.chips) if current else None
    finish = next(
        (play for play in plays if needed is not None and play["estimated_score"] >= needed),
        None,
    )
    visible = [
        (index, card)
        for index, card in enumerate(observation.hand)
        if isinstance(card, VisiblePlayingCard) and not card.debuffed
    ]
    purple = [index for index, card in visible if card.seal == "PURPLE"]
    free_slots = max(0, observation.consumable_limit - len(observation.consumables))
    discards = []
    for index in purple:
        action = DiscardCards((HandSlot(index),))
        if free_slots and is_legal(observation, action):
            discards.append(
                {
                    "action": action_to_data(action),
                    "potential_tarots": 1,
                    "removes_finish_play_card": finish is not None
                    and index in finish["action"]["cards"],
                }
            )
    return {
        "score_remaining": needed,
        "estimated_finish_now": finish["action"] if finish else None,
        "hands_left": observation.round.hands_left,
        "discards_left": observation.round.discards_left,
        "setup_status": (
            "last_hand_preserve_finish"
            if observation.round.hands_left <= 1
            else "finish_available_setup_unverified"
            if finish
            else "no_estimated_finish_prioritize_survival"
        ),
        "purple_discard_options": discards,
        "held_gold_slots": [index for index, card in visible if card.enhancement == "GOLD"],
        "held_blue_slots": [index for index, card in visible if card.seal == "BLUE"],
        "consumable_slots_free": free_slots,
        "remaining_draw_cards": observation.draw_count,
        "note": (
            "Finish is an approximate current-hand score, not guaranteed safety after setup. "
            "Value money, Tarots and copies against lost hand cashout, discards and scoring cards. "
            "Purple options change the hand: reassess scoring, held effects and boss restrictions. "
            "Gold/Blue pay only if held through the terminal hand; reserve consumable capacity. "
            "Do not spend the last hand on non-winning setup."
        ),
    }


_EVENTS = {
    "j_dna": "first hand: exactly one played card; preserve a later scoring finish",
    "j_reserved_parking": "during setup hands: held faces can generate money",
    "j_business": "scoring face cards: probabilistic income",
    "j_faceless": "discard at least three face cards together for income",
    "j_mail": "discard the currently specified rank for income",
    "j_mime": "before terminal play: held Gold/Blue effects at round end; also assess held scoring",
    "j_perkeo": "before leave_shop: retain the intended consumable; multiple targets are random",
}


def copier_timing(observation: PublicObservation) -> list[dict]:
    """Give one legal adjacent step toward each direct event target; reobserve after it."""
    if observation.phase not in {Phase.SELECTING_HAND, Phase.SHOP}:
        return []
    if any(isinstance(joker, HiddenJokerSlot) for joker in observation.jokers):
        return []
    rows = []
    for copier_index, copier in enumerate(observation.jokers):
        if copier.debuffed or copier.key not in {"j_blueprint", "j_brainstorm"}:
            continue
        for target_index, target in enumerate(observation.jokers):
            if not isinstance(target, PublicItem) or target.debuffed or target.key not in _EVENTS:
                continue
            if (target.key == "j_perkeo") != (observation.phase == Phase.SHOP):
                continue
            if target.key == "j_perkeo" and not observation.consumables:
                continue
            if target.key == "j_dna" and observation.round.hands_played != 0:
                continue
            if target.key in {"j_faceless", "j_mail"} and observation.round.discards_left <= 0:
                continue
            order = list(range(len(observation.jokers)))
            order.remove(target_index)
            destination = 0 if copier.key == "j_brainstorm" else order.index(copier_index) + 1
            order.insert(destination, target_index)
            original = list(range(len(order)))
            action = None
            if order != original:
                # Bubble the desired first differing item left by exactly one slot.
                first = next(index for index in original if order[index] != index)
                position = original.index(order[first])
                original[position - 1], original[position] = (
                    original[position],
                    original[position - 1],
                )
                step = ReorderJokers(tuple(JokerSlot(index) for index in original))
                if not is_legal(observation, step):
                    continue
                action = action_to_data(step)
            rows.append(
                {
                    "copier_slot": copier_index,
                    "target_slot": target_index,
                    "target_key": target.key,
                    "event": _EVENTS[target.key],
                    "next_reorder": action,
                    "already_direct_target": action is None,
                    "note": "Optional production target, not a scoring recommendation. Reobserve after each swap. Keep this target through its named event; after setup, reassess the scoring arrangement for the finish. Round-end targets must remain set through the terminal play, not be changed at cashout.",
                }
            )
    return rows[:8]
