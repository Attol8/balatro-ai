"""Fresh Jackdaw roots constructed only from policy-visible information.

This is evaluator-parent code.  It must never receive an authority frame, run
seed, save payload, object identifier, or private simulator clone.  Unsupported
public states fail closed before a rollout can start.

The first certified slice is ``BLIND_SELECT``.  At that boundary every
permanent playing card is in the public Remaining view, so the complete deck
multiset can be rebuilt without inferring a hidden hand.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from typing import Any

from balatro_ai_v2.actions import SkipBlind, action_to_data
from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.determinize import DeterminizationUnavailable
from balatro_ai_v2.jackdaw import JackdawBackend
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.public_codec import public_observation_to_data
from balatro_ai_v2.public_state import (
    HiddenJokerSlot,
    Phase,
    PublicItem,
    PublicJokerRuntime,
    PublicObservation,
    PublicShopPlayingCard,
    VisiblePlayingCard,
)


_PRESENTATION_FIELDS = frozenset({"effect", "effect_text", "label", "tag_effect"})
_ENHANCEMENT_KEYS = {
    None: "c_base",
    "BONUS": "m_bonus",
    "MULT": "m_mult",
    "WILD": "m_wild",
    "GLASS": "m_glass",
    "STEEL": "m_steel",
    "STONE": "m_stone",
    "GOLD": "m_gold",
    "LUCKY": "m_lucky",
}
_EDITION_KEYS = {
    None: None,
    "FOIL": "foil",
    "HOLO": "holo",
    "HOLOGRAPHIC": "holo",
    "POLYCHROME": "polychrome",
    "NEGATIVE": "negative",
}
_SEAL_KEYS = {
    None: None,
    "RED": "Red",
    "BLUE": "Blue",
    "GOLD": "Gold",
    "GOLD SEAL": "Gold",
    "PURPLE": "Purple",
}
_BLIND_STATUS_FROM_PUBLIC = {
    "SELECT": "Select",
    "UPCOMING": "Upcoming",
    "CURRENT": "Current",
    "DEFEATED": "Defeated",
    "SKIPPED": "Skipped",
}
_RUNTIME_MULT = frozenset(
    {
        "j_ceremonial",
        "j_flash",
        "j_green_joker",
        "j_popcorn",
        "j_red_card",
        "j_ride_the_bus",
        "j_swashbuckler",
        "j_trousers",
    }
)
_RUNTIME_CHIPS = frozenset({"j_castle", "j_ice_cream", "j_runner", "j_square", "j_wee"})
_RUNTIME_XMULT = frozenset(
    {
        "j_campfire",
        "j_constellation",
        "j_glass",
        "j_hit_the_road",
        "j_hologram",
        "j_lucky_cat",
        "j_madness",
        "j_obelisk",
        "j_ramen",
        "j_stencil",
        "j_throwback",
        "j_vampire",
        "j_yorick",
    }
)
# These owned Jokers depend on visible tooltip state that the public contract
# does not yet carry completely.  Rejecting them is safer than silently using
# a fresh-run default in rollouts.
_MISSING_PUBLIC_RUNTIME = frozenset(
    {"j_caino", "j_castle", "j_invisible", "j_mail", "j_turtle_bean", "j_yorick"}
)
_UNSUPPORTED_BLIND_STATE = frozenset({"The Ox", "The Pillar"})
_PUBLIC_DERIVED_RUNTIME_FIELDS = {
    "j_flash": "current_mult",
    "j_green_joker": "current_mult",
    "j_red_card": "current_mult",
    "j_ride_the_bus": "current_mult",
    "j_stencil": "current_x_mult",
}


def public_root_seed(
    observation: PublicObservation,
    history: Sequence[PublicHistoryStep],
    nonce: str,
    index: int,
) -> str:
    """Derive one policy-owned particle seed from public values only."""

    if not isinstance(nonce, str) or not nonce:
        raise ValueError("public-root nonce must be a non-empty string")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("public-root particle index must be a non-negative integer")
    _validate_history(observation, history)
    material = {
        "history": [
            {
                "before": step.before.digest(),
                "action": action_to_data(step.action),
                "after": step.after.digest(),
            }
            for step in history
        ],
        "index": index,
        "nonce": nonce,
        "observation": observation.digest(),
        "stream": "public-root-v1",
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16].upper()


def construct_public_root(
    observation: PublicObservation,
    history: Sequence[PublicHistoryStep],
    nonce: str,
    index: int,
) -> JackdawBackend:
    """Build and verify a fresh strategic rollout root.

    The returned backend owns a complete private state, but every private value
    was initialized or sampled here from the policy seed.  No private authority
    state is copied into it.
    """

    _require_supported_root(observation, history)
    seed = public_root_seed(observation, history, nonce, index)
    backend = JackdawBackend(lightweight=True)
    try:
        backend.reset(RunSpec(observation.deck, observation.stake, seed))
        game_state = getattr(backend._backend, "_gs", None)
        if not isinstance(game_state, dict):
            raise DeterminizationUnavailable("fresh Jackdaw root has no game state")
        _rebuild_state(game_state, observation, history, seed)
        backend._poker_hand_iteration_order = _sample_poker_hand_order(
            observation,
            seed,
        )
        game_state["orbital_choices"] = {}
        _set_most_played_hand(game_state, backend._poker_hand_iteration_order)
        if observation.phase == Phase.BLIND_SELECT:
            backend._initialize_orbital_choices()
        backend._stale_shop_areas = None
        backend._round_targets_rolled = False
        backend._pending_ante_setup = None
        backend._active_pack_cards = None
        backend._pack_card_limit = None
        backend._won = observation.won
        backend._pending_skip_dollars = 0
        backend._lightweight_normalized = None
        backend._current = backend.observe()
        projected = backend.current_public
        if projected is None:
            raise DeterminizationUnavailable("fresh public root has no public projection")
        difference = _decision_difference(projected, observation)
        if difference is not None:
            path, actual, expected = difference
            raise DeterminizationUnavailable(
                f"fresh public root does not round-trip at {path}: "
                f"candidate={actual!r}, public={expected!r}"
            )
        return backend
    except Exception:
        backend.close()
        raise


def _require_supported_root(
    observation: PublicObservation,
    history: Sequence[PublicHistoryStep],
) -> None:
    if observation.phase not in {Phase.BLIND_SELECT, Phase.SHOP}:
        raise DeterminizationUnavailable(
            f"phase {observation.phase.value} has no fresh public constructor"
        )
    _validate_history(observation, history)
    if observation.hand:
        raise DeterminizationUnavailable("BLIND_SELECT root unexpectedly has a hand")
    if observation.required_hand_slots:
        raise DeterminizationUnavailable("BLIND_SELECT root has required hand slots")
    if observation.phase == Phase.BLIND_SELECT and (
        observation.shop
        or observation.vouchers
        or observation.packs
        or observation.opened_pack
    ):
        raise DeterminizationUnavailable("BLIND_SELECT root exposes a transient card area")
    if observation.phase == Phase.SHOP and observation.opened_pack:
        raise DeterminizationUnavailable("SHOP root exposes an opened pack")
    if observation.pack_kind is not None or observation.pack_choices_remaining:
        raise DeterminizationUnavailable("BLIND_SELECT root exposes pack metadata")
    if observation.draw_count != observation.deck_size:
        raise DeterminizationUnavailable("BLIND_SELECT draw count differs from deck size")
    if _deck_multiset(observation.remaining_deck) != _deck_multiset(
        observation.full_deck
    ):
        raise DeterminizationUnavailable(
            "BLIND_SELECT Remaining view differs from permanent deck"
        )
    if any(isinstance(joker, HiddenJokerSlot) for joker in observation.jokers):
        raise DeterminizationUnavailable("face-down Jokers cannot seed a public root")
    if any(isinstance(step.action, SkipBlind) for step in history):
        raise DeterminizationUnavailable(
            "historical skip-tag state is not yet reconstructible"
        )
    selecting = [blind for blind in observation.blinds if blind.status == "SELECT"]
    if observation.phase == Phase.BLIND_SELECT and len(selecting) != 1:
        raise DeterminizationUnavailable("BLIND_SELECT requires exactly one selectable blind")
    if observation.phase == Phase.SHOP and selecting:
        raise DeterminizationUnavailable("SHOP root unexpectedly has a selectable blind")
    for blind in observation.blinds:
        if blind.kind not in {"SMALL", "BIG", "BOSS"}:
            raise DeterminizationUnavailable(f"unknown blind kind {blind.kind!r}")
        if blind.status not in _BLIND_STATUS_FROM_PUBLIC:
            raise DeterminizationUnavailable(f"unknown blind status {blind.status!r}")
        if blind.name in _UNSUPPORTED_BLIND_STATE:
            raise DeterminizationUnavailable(
                f"blind {blind.name!r} needs state absent from the public contract"
            )


def _validate_history(
    observation: PublicObservation,
    history: Sequence[PublicHistoryStep],
) -> None:
    if history and (
        history[0].before.round_no != 0 or history[0].before.antes_cleared != 0
    ):
        raise DeterminizationUnavailable("public history is not contiguous from run start")
    previous = None
    for offset, step in enumerate(history):
        if previous is not None and step.before != previous:
            raise DeterminizationUnavailable(
                f"public history is not contiguous at step {offset}"
            )
        if step.before.deck != observation.deck or step.before.stake != observation.stake:
            raise DeterminizationUnavailable("public history changes deck or stake")
        previous = step.after
    if history and history[-1].after != observation:
        raise DeterminizationUnavailable("public history does not end at the root")
    if not history and (observation.round_no != 0 or observation.antes_cleared != 0):
        raise DeterminizationUnavailable("non-initial public root requires complete history")


def _rebuild_state(
    game_state: dict[str, Any],
    observation: PublicObservation,
    history: Sequence[PublicHistoryStep],
    seed: str,
) -> None:
    from jackdaw.bridge.backend import DECK_FROM_BOT, STAKE_FROM_BOT
    from jackdaw.engine.actions import GamePhase
    from jackdaw.engine.blind import Blind
    from jackdaw.engine.data.prototypes import BLINDS, TAGS
    from jackdaw.engine.rng import PseudoRandom
    from jackdaw.engine.vouchers import VOUCHERS, apply_voucher

    if observation.deck not in DECK_FROM_BOT or observation.stake not in STAKE_FROM_BOT:
        raise DeterminizationUnavailable("unknown deck or stake")

    game_state["phase"] = (
        GamePhase.BLIND_SELECT
        if observation.phase == Phase.BLIND_SELECT
        else GamePhase.SHOP
    )
    game_state["selected_back_key"] = DECK_FROM_BOT[observation.deck]
    game_state["stake"] = STAKE_FROM_BOT[observation.stake]
    game_state["rng"] = PseudoRandom(seed)
    game_state["seed"] = seed
    game_state["seeded"] = True
    game_state["dollars"] = observation.money
    game_state["won"] = observation.won
    game_state["round"] = observation.round_no
    game_state["chips"] = observation.round.chips
    game_state["last_tarot_planet"] = observation.last_tarot_planet
    game_state["hand_size"] = observation.hand_limit
    game_state["joker_slots"] = observation.joker_limit
    game_state["consumable_slots"] = observation.consumable_limit
    game_state["hand"] = []
    game_state["discard_pile"] = []
    game_state["play"] = []
    game_state["played_cards_area"] = []
    game_state.pop("pack_cards", None)
    game_state["shop_cards"] = []
    game_state["shop_vouchers"] = []
    game_state["shop_boosters"] = []

    round_resets = game_state.setdefault("round_resets", {})
    round_resets["ante"] = observation.ante
    round_resets["blind_ante"] = observation.ante
    round_resets["hands"] = observation.round.hands_left
    round_resets["discards"] = observation.round.discards_left
    round_resets["temp_reroll_cost"] = None
    round_resets["temp_handsize"] = None
    round_resets["boss_rerolled"] = observation.round.boss_rerolled

    blind_by_name = {prototype.name: key for key, prototype in BLINDS.items()}
    tag_by_name = {prototype.name: key for key, prototype in TAGS.items()}
    choices: dict[str, str] = {}
    states: dict[str, str] = {}
    tags: dict[str, str] = {}
    selected_kind = None
    for public_blind in observation.blinds:
        title = public_blind.kind.title()
        blind_key = blind_by_name.get(public_blind.name)
        if blind_key is None:
            raise DeterminizationUnavailable(
                f"unknown public blind {public_blind.name!r}"
            )
        choices[title] = blind_key
        states[title] = _BLIND_STATUS_FROM_PUBLIC[public_blind.status]
        if public_blind.status == "SELECT":
            selected_kind = title
        if public_blind.tag_name:
            tag_key = tag_by_name.get(public_blind.tag_name)
            if tag_key is None:
                raise DeterminizationUnavailable(
                    f"unknown public tag {public_blind.tag_name!r}"
                )
            tags[title] = tag_key
    if observation.phase == Phase.SHOP:
        selected_kind = _next_shop_blind_kind(states)
    if selected_kind is None:
        raise DeterminizationUnavailable("public root has no next blind boundary")
    round_resets["blind_choices"] = choices
    round_resets["blind_states"] = states
    round_resets["blind_tags"] = tags
    game_state["blind_on_deck"] = selected_kind
    game_state["blind"] = None

    current_round = game_state.setdefault("current_round", {})
    current_round.update(
        {
            "hands_left": observation.round.hands_left,
            "discards_left": observation.round.discards_left,
            "hands_played": observation.round.hands_played,
            "discards_used": observation.round.discards_used,
            "reroll_cost": observation.round.reroll_cost,
        }
    )
    if observation.round.ancient_suit is not None:
        suits = {"S": "Spades", "H": "Hearts", "D": "Diamonds", "C": "Clubs"}
        if observation.round.ancient_suit not in suits:
            raise DeterminizationUnavailable("unknown Ancient Joker target suit")
        current_round["ancient_card"] = {"suit": suits[observation.round.ancient_suit]}

    _rebuild_hand_levels(game_state, observation)
    game_state["deck"] = _rebuild_deck(observation, seed)
    game_state["playing_card_count"] = observation.deck_size
    game_state["playing_cards_count"] = observation.deck_size
    game_state["starting_deck_size"] = _starting_deck_size(observation, history)

    # Start with deck-defined vouchers already applied by initialize_run, then
    # add every publicly owned voucher in the observed chronological order.
    existing = game_state.get("used_vouchers")
    if not isinstance(existing, dict):
        raise DeterminizationUnavailable("fresh voucher state is invalid")
    for key in observation.used_vouchers:
        if key not in VOUCHERS:
            raise DeterminizationUnavailable(f"unknown used voucher {key!r}")
        if existing.get(key):
            continue
        existing[key] = True
        apply_voucher(key, game_state)
    # Public limits and counters are authoritative after durable effects.
    game_state["hand_size"] = observation.hand_limit
    game_state["joker_slots"] = observation.joker_limit
    game_state["consumable_slots"] = observation.consumable_limit
    round_resets["ante"] = observation.ante
    round_resets["blind_ante"] = observation.ante
    round_resets["hands"] = observation.round.hands_left
    round_resets["discards"] = observation.round.discards_left
    current_round["reroll_cost"] = observation.round.reroll_cost

    jokers = [_rebuild_joker(item, current_round) for item in observation.jokers]
    game_state["jokers"] = jokers
    game_state["consumables"] = [
        _rebuild_consumable(item) for item in observation.consumables
    ]
    for card in [*game_state["jokers"], *game_state["consumables"]]:
        card.add_to_deck(game_state)
    # Passive application reconstructs hidden durable mechanics, while these
    # visible values remain authoritative at the exact decision boundary.
    game_state["hand_size"] = observation.hand_limit
    game_state["joker_slots"] = observation.joker_limit
    game_state["consumable_slots"] = observation.consumable_limit
    round_resets["hands"] = observation.round.hands_left
    round_resets["discards"] = observation.round.discards_left
    current_round["hands_left"] = observation.round.hands_left
    current_round["discards_left"] = observation.round.discards_left
    _restore_shop_reroll_state(game_state, observation, history)

    _rebuild_shop(game_state, observation)
    _assign_public_root_sort_ids(game_state)
    game_state["used_jokers"] = {
        key: True for key in _active_center_keys(observation)
    }
    game_state["has_showman"] = any(card.center_key == "j_ring_master" for card in jokers)
    game_state["first_shop_buffoon"] = observation.phase == Phase.SHOP or any(
        step.before.phase == Phase.SHOP or step.after.phase == Phase.SHOP
        for step in history
    )
    game_state["pool_flags"] = (
        {"gros_michel_extinct": True}
        if _gros_michel_went_extinct(history)
        else {}
    )

    hand_plays = sum(stat.played for stat in observation.hand_stats)
    game_state["hands_played"] = hand_plays
    game_state["round_scores"] = _public_round_scores(history)
    shop_purchases, joker_purchases = (
        _current_shop_purchases(history)
        if observation.phase == Phase.SHOP
        else (0, 0)
    )
    game_state["cards_purchased"] = shop_purchases
    current_round["jokers_purchased"] = joker_purchases
    game_state["skips"] = 0
    game_state["bosses_used"] = _public_bosses_used(observation, history, BLINDS)

    # Validate the current blind objects are constructible at the declared
    # scaling.  The serializer will recompute their public scores from these
    # fields during the final round trip.
    for key in choices.values():
        Blind.create(
            key,
            observation.ante,
            int(game_state.get("modifiers", {}).get("scaling", 1)),
            float(game_state.get("starting_params", {}).get("ante_scaling", 1.0)),
        )


def _next_shop_blind_kind(states: Mapping[str, str]) -> str:
    pattern = tuple(states.get(kind) for kind in ("Small", "Big", "Boss"))
    next_by_pattern = {
        ("Upcoming", "Upcoming", "Upcoming"): "Small",
        ("Defeated", "Upcoming", "Upcoming"): "Big",
        ("Defeated", "Defeated", "Upcoming"): "Boss",
    }
    try:
        return next_by_pattern[pattern]
    except KeyError as exc:
        raise DeterminizationUnavailable(
            f"SHOP blind progression is not reconstructible: {pattern!r}"
        ) from exc


def _restore_shop_reroll_state(
    game_state: dict[str, Any],
    observation: PublicObservation,
    history: Sequence[PublicHistoryStep],
) -> None:
    if observation.phase != Phase.SHOP:
        game_state["current_round"]["reroll_cost"] = observation.round.reroll_cost
        return

    from balatro_ai_v2.actions import RerollShop
    from jackdaw.engine.shop import calculate_reroll_cost

    entrance, steps = _current_shop_visit(history)
    free_rerolls = _visible_joker_count(entrance, "j_chaos")
    paid_rerolls = 0
    for step in steps:
        if isinstance(step.action, RerollShop):
            if step.before.round.reroll_cost == 0:
                free_rerolls = max(0, free_rerolls - 1)
            else:
                paid_rerolls += 1
        free_rerolls = max(
            0,
            free_rerolls
            + _visible_joker_count(step.after, "j_chaos")
            - _visible_joker_count(step.before, "j_chaos"),
        )
    if _visible_joker_count(observation, "j_chaos") != _visible_joker_count(
        steps[-1].after if steps else entrance,
        "j_chaos",
    ):
        raise DeterminizationUnavailable("SHOP Joker history does not reach the root")

    current_round = game_state["current_round"]
    current_round["free_rerolls"] = free_rerolls
    current_round["reroll_cost_increase"] = paid_rerolls
    rebuilt_cost = calculate_reroll_cost(game_state)
    if rebuilt_cost != observation.round.reroll_cost:
        raise DeterminizationUnavailable(
            "SHOP reroll state does not match the public price: "
            f"candidate={rebuilt_cost}, public={observation.round.reroll_cost}"
        )


def _visible_joker_count(observation: PublicObservation, key: str) -> int:
    return sum(
        isinstance(joker, PublicItem) and joker.key == key
        for joker in observation.jokers
    )


def _rebuild_hand_levels(game_state: dict[str, Any], observation: PublicObservation) -> None:
    from jackdaw.engine.data.hands import HandType
    from jackdaw.engine.hand_levels import HandLevels

    if len(observation.hand_stats) != len(HandType):
        raise DeterminizationUnavailable("public root does not expose all poker hands")
    levels = HandLevels()
    seen: set[str] = set()
    for public in observation.hand_stats:
        try:
            state = levels.get_state(HandType(public.name))
        except ValueError as exc:
            raise DeterminizationUnavailable(
                f"unknown poker hand {public.name!r}"
            ) from exc
        if public.name in seen:
            raise DeterminizationUnavailable("duplicate poker-hand state")
        seen.add(public.name)
        state.level = public.level
        state.chips = public.chips
        state.mult = public.mult
        state.played = public.played
        state.played_this_round = public.played_this_round
        state.visible = True
    game_state["hand_levels"] = levels


def _sample_poker_hand_order(
    observation: PublicObservation,
    seed: str,
) -> tuple[str, ...]:
    names = [stat.name for stat in observation.hand_stats]
    random.Random(
        int(hashlib.sha256(f"{seed}|lua-hand-order".encode()).hexdigest(), 16)
    ).shuffle(names)
    return tuple(names)


def _set_most_played_hand(
    game_state: dict[str, Any],
    order: tuple[str, ...],
) -> None:
    levels = game_state["hand_levels"]
    best = order[0]
    best_count = -1
    for name in order:
        count = levels.get_state(name).played
        if count >= best_count:
            best = name
            best_count = count
    game_state["current_round"]["most_played_poker_hand"] = best


def _rebuild_deck(observation: PublicObservation, seed: str) -> list[Any]:
    from jackdaw.engine.card_factory import RANK_LETTER, SUIT_LETTER, create_playing_card

    chooser = random.Random(int(hashlib.sha256(f"{seed}|stone-base".encode()).hexdigest(), 16))
    rank_letters = tuple(RANK_LETTER)
    suit_letters = tuple(SUIT_LETTER)
    cards: list[Any] = []
    for entry in observation.full_deck:
        public = entry.card
        enhancement = _ENHANCEMENT_KEYS.get(public.enhancement)
        edition_key = _EDITION_KEYS.get(public.edition)
        seal = _SEAL_KEYS.get(public.seal)
        if enhancement is None or public.edition not in _EDITION_KEYS or public.seal not in _SEAL_KEYS:
            raise DeterminizationUnavailable("unsupported playing-card modifier")
        for _ in range(entry.count):
            if public.enhancement == "STONE":
                rank = RANK_LETTER[chooser.choice(rank_letters)]
                suit = SUIT_LETTER[chooser.choice(suit_letters)]
            else:
                if public.rank not in RANK_LETTER or public.suit not in SUIT_LETTER:
                    raise DeterminizationUnavailable("unsupported playing-card identity")
                rank = RANK_LETTER[public.rank]
                suit = SUIT_LETTER[public.suit]
            card = create_playing_card(
                suit,
                rank,
                enhancement,
                {edition_key: True} if edition_key else None,
                seal,
                playing_card_index=len(cards) + 1,
            )
            card.ability["perma_bonus"] = public.permanent_bonus
            card.debuff = public.debuffed
            cards.append(card)
    random.Random(int(hashlib.sha256(f"{seed}|deck-order".encode()).hexdigest(), 16)).shuffle(cards)
    return cards


def _assign_public_root_sort_ids(game_state: dict[str, Any]) -> None:
    """Give every rebuilt card a root-local ID and reset Jackdaw's counter."""

    import jackdaw.engine.card as card_module

    next_id = 0
    for area_name in (
        "deck",
        "jokers",
        "consumables",
        "shop_cards",
        "shop_vouchers",
        "shop_boosters",
    ):
        area = game_state.get(area_name)
        if not isinstance(area, list):
            raise DeterminizationUnavailable(f"fresh {area_name} area is invalid")
        for card in area:
            next_id += 1
            card.sort_id = next_id
            if getattr(card, "base", None) is not None:
                card.playing_card = next_id
    card_module._sort_id_counter = next_id


def _deck_multiset(entries: Sequence[Any]) -> tuple[tuple[object, ...], ...]:
    """Compare the two public deck views without presentation-only text."""

    values = (
        (
                entry.card.rank,
                entry.card.suit,
                entry.card.enhancement,
                entry.card.edition,
                entry.card.seal,
                entry.card.debuffed,
                entry.card.permanent_bonus,
                entry.count,
        )
        for entry in entries
    )
    return tuple(sorted(values, key=repr))


def _rebuild_joker(item: PublicItem, current_round: dict[str, Any]) -> Any:
    from jackdaw.engine.card_factory import create_joker
    from jackdaw.engine.data.prototypes import JOKERS

    if item.kind != "JOKER" or item.key not in JOKERS:
        raise DeterminizationUnavailable(f"unknown owned Joker {item.key!r}")
    if item.key in _MISSING_PUBLIC_RUNTIME:
        raise DeterminizationUnavailable(
            f"owned Joker {item.key!r} lacks complete public runtime"
        )
    edition_key = _EDITION_KEYS.get(item.edition)
    if item.edition not in _EDITION_KEYS:
        raise DeterminizationUnavailable("unsupported Joker edition")
    card = create_joker(
        item.key,
        {edition_key: True} if edition_key else None,
        eternal=item.eternal,
        perishable=item.perishable_rounds is not None,
        rental=item.rental,
    )
    card.debuff = item.debuffed
    if item.perishable_rounds is not None:
        card.perish_tally = item.perishable_rounds
    _set_costs(card, item)
    _apply_joker_runtime(card, item.runtime, current_round)
    return card


def _apply_joker_runtime(
    card: Any,
    runtime: PublicJokerRuntime | None,
    current_round: dict[str, Any],
) -> None:
    key = card.center_key
    required = key in _RUNTIME_MULT | _RUNTIME_CHIPS | _RUNTIME_XMULT | {
        "j_rocket",
        "j_selzer",
        "j_loyalty_card",
        "j_drivers_license",
        "j_todo_list",
        "j_idol",
    }
    if (
        required
        and runtime is None
        and key not in _PUBLIC_DERIVED_RUNTIME_FIELDS
    ):
        raise DeterminizationUnavailable(f"owned Joker {key!r} has no public runtime")
    if runtime is None:
        return
    if key in _RUNTIME_MULT:
        if runtime.current_mult is None:
            raise DeterminizationUnavailable(f"owned Joker {key!r} has no current mult")
        card.ability["mult"] = runtime.current_mult
    if key in _RUNTIME_CHIPS:
        if runtime.current_chips is None:
            raise DeterminizationUnavailable(f"owned Joker {key!r} has no current chips")
        extra = card.ability.get("extra")
        if not isinstance(extra, dict):
            raise DeterminizationUnavailable(f"owned Joker {key!r} has invalid chip state")
        extra["chips"] = runtime.current_chips
    if key in _RUNTIME_XMULT:
        if runtime.current_x_mult is None:
            raise DeterminizationUnavailable(f"owned Joker {key!r} has no current xMult")
        card.ability["x_mult"] = runtime.current_x_mult
    if key == "j_rocket":
        if runtime.current_dollars is None or not isinstance(card.ability.get("extra"), dict):
            raise DeterminizationUnavailable("Rocket has invalid public dollars")
        card.ability["extra"]["dollars"] = runtime.current_dollars
    elif key == "j_selzer":
        if runtime.remaining_hands is None:
            raise DeterminizationUnavailable("Seltzer has no public remaining hands")
        card.ability["extra"] = runtime.remaining_hands
    elif key == "j_loyalty_card":
        if runtime.loyalty_remaining is None:
            raise DeterminizationUnavailable("Loyalty Card has no public countdown")
        card.ability["loyalty_remaining"] = runtime.loyalty_remaining
    elif key == "j_drivers_license":
        if runtime.driver_tally is None:
            raise DeterminizationUnavailable("Driver's License has no public tally")
        card.ability["driver_tally"] = runtime.driver_tally
    elif key == "j_todo_list":
        if runtime.target_hand is None:
            raise DeterminizationUnavailable("To Do List has no public target")
        card.ability["to_do_poker_hand"] = runtime.target_hand
    elif key == "j_idol":
        if runtime.target_rank is None or runtime.target_suit is None:
            raise DeterminizationUnavailable("The Idol has no public card target")
        rank_names = {
            **{str(value): str(value) for value in range(2, 10)},
            "T": "10",
            "J": "Jack",
            "Q": "Queen",
            "K": "King",
            "A": "Ace",
        }
        suit_names = {"S": "Spades", "H": "Hearts", "D": "Diamonds", "C": "Clubs"}
        current_round["idol_card"] = {
            "rank": rank_names[runtime.target_rank],
            "suit": suit_names[runtime.target_suit],
            "id": tuple(rank_names).index(runtime.target_rank) + 2,
        }


def _rebuild_consumable(item: PublicItem) -> Any:
    from jackdaw.engine.card_factory import create_consumable
    from jackdaw.engine.data.prototypes import PLANETS, SPECTRALS, TAROTS

    known = set(TAROTS) | set(PLANETS) | set(SPECTRALS)
    if item.kind not in {"TAROT", "PLANET", "SPECTRAL"} or item.key not in known:
        raise DeterminizationUnavailable(f"unknown owned consumable {item.key!r}")
    if item.runtime is not None or item.eternal or item.perishable_rounds is not None or item.rental:
        raise DeterminizationUnavailable("owned consumable has unsupported modifiers")
    card = create_consumable(item.key)
    edition_key = _EDITION_KEYS.get(item.edition)
    if item.edition not in _EDITION_KEYS:
        raise DeterminizationUnavailable("unsupported consumable edition")
    if edition_key is not None:
        card.set_edition({edition_key: True})
    card.debuff = item.debuffed
    _set_costs(card, item)
    return card


def _rebuild_shop(game_state: dict[str, Any], observation: PublicObservation) -> None:
    if observation.phase != Phase.SHOP:
        game_state["shop_cards"] = []
        game_state["shop_vouchers"] = []
        game_state["shop_boosters"] = []
        return

    current_round = game_state["current_round"]
    chooser = random.Random(
        int(
            hashlib.sha256(
                f"{game_state['seed']}|shop-stone-base".encode()
            ).hexdigest(),
            16,
        )
    )
    game_state["shop_cards"] = [
        _rebuild_shop_offer(offer, current_round, chooser)
        for offer in observation.shop
    ]
    game_state["shop_vouchers"] = [
        _rebuild_voucher(item) for item in observation.vouchers
    ]
    game_state["shop_boosters"] = [
        _rebuild_booster(item) for item in observation.packs
    ]
    game_state["shop_voucher_limit"] = max(1, len(game_state["shop_vouchers"]))
    shop = game_state.setdefault("shop", {})
    if not isinstance(shop, dict):
        raise DeterminizationUnavailable("fresh shop capacity state is invalid")
    shop["joker_max"] = max(int(shop.get("joker_max", 2)), len(observation.shop))
    current_round["voucher"] = (
        game_state["shop_vouchers"][0].center_key
        if game_state["shop_vouchers"]
        else None
    )
    game_state["shop_return_phase"] = "shop"


def _rebuild_shop_offer(
    offer: PublicItem | PublicShopPlayingCard,
    current_round: dict[str, Any],
    chooser: random.Random,
) -> Any:
    if isinstance(offer, PublicShopPlayingCard):
        card = _rebuild_visible_playing_card(offer.card, chooser)
        card.cost = offer.buy_cost
        return card
    if offer.kind == "JOKER":
        return _rebuild_joker(offer, current_round)
    if offer.kind in {"TAROT", "PLANET", "SPECTRAL"}:
        return _rebuild_consumable(offer)
    raise DeterminizationUnavailable(f"unsupported shop offer kind {offer.kind!r}")


def _rebuild_visible_playing_card(
    public: VisiblePlayingCard,
    chooser: random.Random,
) -> Any:
    from jackdaw.engine.card_factory import RANK_LETTER, SUIT_LETTER, create_playing_card

    enhancement = _ENHANCEMENT_KEYS.get(public.enhancement)
    edition_key = _EDITION_KEYS.get(public.edition)
    seal = _SEAL_KEYS.get(public.seal)
    if (
        enhancement is None
        or public.edition not in _EDITION_KEYS
        or public.seal not in _SEAL_KEYS
        or (
            public.enhancement != "STONE"
            and (public.rank not in RANK_LETTER or public.suit not in SUIT_LETTER)
        )
    ):
        raise DeterminizationUnavailable("unsupported shop playing-card identity")
    card = create_playing_card(
        (
            SUIT_LETTER[chooser.choice(tuple(SUIT_LETTER))]
            if public.enhancement == "STONE"
            else SUIT_LETTER[public.suit]
        ),
        (
            RANK_LETTER[chooser.choice(tuple(RANK_LETTER))]
            if public.enhancement == "STONE"
            else RANK_LETTER[public.rank]
        ),
        enhancement,
        {edition_key: True} if edition_key else None,
        seal,
    )
    card.ability["perma_bonus"] = public.permanent_bonus
    card.debuff = public.debuffed
    return card


def _rebuild_voucher(item: PublicItem) -> Any:
    from jackdaw.engine.card_factory import create_voucher
    from jackdaw.engine.data.prototypes import VOUCHERS

    if item.kind != "VOUCHER" or item.key not in VOUCHERS:
        raise DeterminizationUnavailable(f"unknown shop voucher {item.key!r}")
    if (
        item.runtime is not None
        or item.edition is not None
        or item.eternal
        or item.perishable_rounds is not None
        or item.rental
        or item.debuffed
    ):
        raise DeterminizationUnavailable("shop voucher has unsupported modifiers")
    card = create_voucher(item.key)
    _set_costs(card, item)
    return card


def _rebuild_booster(item: PublicItem) -> Any:
    from jackdaw.engine.card import Card
    from jackdaw.engine.data.prototypes import BOOSTERS
    from balatro_ai_v2.canonical import semantic_card_key

    matching_keys = [
        key
        for key in BOOSTERS
        if semantic_card_key("BOOSTER", key) == item.key
    ]
    if item.kind != "BOOSTER" or not matching_keys:
        raise DeterminizationUnavailable(f"unknown shop booster {item.key!r}")
    if (
        item.runtime is not None
        or item.edition is not None
        or item.eternal
        or item.perishable_rounds is not None
        or item.rental
        or item.debuffed
    ):
        raise DeterminizationUnavailable("shop booster has unsupported modifiers")
    card = Card()
    card.set_ability(sorted(matching_keys)[0])
    _set_costs(card, item)
    return card


def _set_costs(card: Any, item: PublicItem) -> None:
    if item.buy_cost is not None:
        card.cost = item.buy_cost
    if item.sell_cost is not None:
        card.sell_cost = item.sell_cost


def _starting_deck_size(
    observation: PublicObservation,
    history: Sequence[PublicHistoryStep],
) -> int:
    if history:
        return history[0].before.deck_size
    return observation.deck_size


def _public_round_scores(
    history: Sequence[PublicHistoryStep],
) -> dict[str, Any]:
    from balatro_ai_v2.actions import (
        BuyPack,
        BuyShopCard,
        BuyVoucher,
        DiscardCards,
        PlayCards,
        RerollShop,
    )

    cards_played = cards_discarded = times_rerolled = cards_purchased = 0
    for step in history:
        action = step.action
        if isinstance(action, PlayCards):
            cards_played += len(action.cards)
        elif isinstance(action, DiscardCards):
            cards_discarded += len(action.cards)
        elif isinstance(action, RerollShop):
            times_rerolled += 1
        elif isinstance(action, (BuyShopCard, BuyVoucher, BuyPack)):
            cards_purchased += 1
    return {
        "furthest_ante": max((step.after.ante for step in history), default=0),
        "furthest_round": max((step.after.round_no for step in history), default=0),
        "hand": 0,
        "poker_hand": "",
        "new_collection": 0,
        "cards_played": cards_played,
        "cards_discarded": cards_discarded,
        "times_rerolled": times_rerolled,
        "cards_purchased": cards_purchased,
    }


def _current_shop_purchases(
    history: Sequence[PublicHistoryStep],
) -> tuple[int, int]:
    from balatro_ai_v2.actions import BuyPack, BuyShopCard, BuyVoucher

    purchases = jokers = 0
    _, steps = _current_shop_visit(history)
    for step in steps:
        if isinstance(step.action, BuyShopCard):
            purchases += 1
            index = step.action.card.value
            if 0 <= index < len(step.before.shop):
                offer = step.before.shop[index]
                jokers += int(isinstance(offer, PublicItem) and offer.kind == "JOKER")
        elif isinstance(step.action, (BuyPack, BuyVoucher)):
            purchases += 1
    return purchases, jokers


def _current_shop_visit(
    history: Sequence[PublicHistoryStep],
) -> tuple[PublicObservation, tuple[PublicHistoryStep, ...]]:
    visit_phases = {Phase.SHOP, Phase.PACK}
    boundary = next(
        (
            index
            for index in range(len(history) - 1, -1, -1)
            if history[index].after.phase == Phase.SHOP
            and history[index].before.phase not in visit_phases
        ),
        None,
    )
    if boundary is None:
        raise DeterminizationUnavailable("SHOP history has no public entrance boundary")
    steps = tuple(history[boundary + 1 :])
    if any(
        step.before.phase not in visit_phases or step.after.phase not in visit_phases
        for step in steps
    ):
        raise DeterminizationUnavailable("SHOP visit history crosses another phase")
    return history[boundary].after, steps


def _active_center_keys(observation: PublicObservation) -> frozenset[str]:
    keys: set[str] = set()
    for item in [
        *observation.jokers,
        *observation.consumables,
        *observation.shop,
        *observation.opened_pack,
    ]:
        if isinstance(item, PublicItem):
            keys.add(item.key)
        elif isinstance(item, PublicShopPlayingCard):
            keys.add(_ENHANCEMENT_KEYS[item.card.enhancement])
        elif isinstance(item, VisiblePlayingCard):
            keys.add(_ENHANCEMENT_KEYS[item.enhancement])
    return frozenset(keys)


def _gros_michel_went_extinct(
    history: Sequence[PublicHistoryStep],
) -> bool:
    from balatro_ai_v2.actions import PlayCards

    return any(
        isinstance(step.action, PlayCards)
        and _visible_joker_count(step.after, "j_gros_michel")
        < _visible_joker_count(step.before, "j_gros_michel")
        for step in history
    )


def _public_bosses_used(
    observation: PublicObservation,
    history: Sequence[PublicHistoryStep],
    blind_prototypes: Mapping[str, Any],
) -> dict[str, int]:
    from balatro_ai_v2.actions import RerollBoss

    by_name = {prototype.name: key for key, prototype in blind_prototypes.items()}
    used = {key: 0 for key, prototype in blind_prototypes.items() if prototype.boss is not None}

    def record(public: PublicObservation) -> None:
        boss = next((blind for blind in public.blinds if blind.kind == "BOSS"), None)
        if boss is None:
            raise DeterminizationUnavailable("public state has no boss blind")
        key = by_name.get(boss.name)
        if key is None:
            raise DeterminizationUnavailable(f"unknown historical boss {boss.name!r}")
        used[key] = used.get(key, 0) + 1

    initial = history[0].before if history else observation
    record(initial)
    for step in history:
        before_boss = next(
            blind for blind in step.before.blinds if blind.kind == "BOSS"
        )
        after_boss = next(
            blind for blind in step.after.blinds if blind.kind == "BOSS"
        )
        new_assignment = (
            isinstance(step.action, RerollBoss)
            or before_boss.name != after_boss.name
            or (
                before_boss.status == "DEFEATED"
                and after_boss.status == "UPCOMING"
            )
        )
        if new_assignment:
            record(step.after)
    return used


def _decision_difference(
    left: PublicObservation,
    right: PublicObservation,
) -> tuple[str, object, object] | None:
    return _first_difference(
        _without_presentation(public_observation_to_data(left)),
        _without_presentation(public_observation_to_data(right)),
    )


def _without_presentation(value: object) -> object:
    if isinstance(value, dict):
        normalized = value
        runtime_field = _PUBLIC_DERIVED_RUNTIME_FIELDS.get(value.get("key"))
        runtime = value.get("runtime")
        if runtime_field is not None and isinstance(runtime, dict):
            normalized = dict(value)
            normalized_runtime = dict(runtime)
            normalized_runtime[runtime_field] = None
            normalized["runtime"] = (
                None
                if all(item is None for item in normalized_runtime.values())
                else normalized_runtime
            )
        return {
            key: _without_presentation(item)
            for key, item in normalized.items()
            if key not in _PRESENTATION_FIELDS
        }
    if isinstance(value, list):
        return [_without_presentation(item) for item in value]
    return value


def _first_difference(
    left: object,
    right: object,
    path: str = "",
) -> tuple[str, object, object] | None:
    if type(left) is not type(right):
        return path or "/", left, right
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            child = f"{path}/{key}"
            if key not in left or key not in right:
                return child, left.get(key), right.get(key)
            difference = _first_difference(left[key], right[key], child)
            if difference is not None:
                return difference
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return path or "/", left, right
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            difference = _first_difference(left_item, right_item, f"{path}/{index}")
            if difference is not None:
                return difference
    elif left != right:
        return path or "/", left, right
    return None
