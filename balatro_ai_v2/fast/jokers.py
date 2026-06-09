from __future__ import annotations

from dataclasses import dataclass, field

from balatro_ai_v2.fast.cards import chips as card_chips, rank, suit
from balatro_ai_v2.fast.hand import (
    FLUSH,
    FLUSH_FIVE,
    FLUSH_HOUSE,
    FOUR_OF_A_KIND,
    FULL_HOUSE,
    FIVE_OF_A_KIND,
    HIGH_CARD,
    PAIR,
    STRAIGHT,
    STRAIGHT_FLUSH,
    THREE_OF_A_KIND,
    TWO_PAIR,
    FastScore,
)
from balatro_ai_v2.fast.modifiers import Edition, edition_chip_bonus, edition_mult_bonus, edition_xmult


@dataclass(frozen=True, slots=True)
class Joker:
    key: str
    scaling: int = 0
    x_mult: float = 1.0
    sell_value: int = 0
    edition: int = 0


@dataclass(frozen=True, slots=True)
class ScoreContext:
    held_cards: tuple[int, ...] = ()
    money: int = 0
    discards_left: int = 0
    hands_left: int = 0
    deck_count: int = 52
    deck_cards: tuple[int, ...] = ()
    starting_deck_size: int = 52
    playing_card_count: int = 52
    joker_count: int | None = None
    joker_slots: int = 5
    is_final_hand: bool = False
    hands_played_this_round: int = 0
    blinds_skipped: int = 0
    current_ancient_suit: int | None = None
    current_idol_rank: int | None = None
    current_idol_suit: int | None = None
    debuffed_held_suits: frozenset[int] = frozenset()
    debuffed_held_cards: frozenset[int] = frozenset()
    enhanced_card_count: int = 0
    tarot_cards_used: int = 0
    loyalty_remaining: int | None = None
    all_cards_are_face: bool = False
    hand_times_played: dict[int, int] = field(default_factory=dict)
    hand_times_played_round: dict[int, int] = field(default_factory=dict)


SUIT_MULT_JOKERS = {
    "j_greedy_joker": (3, 3),
    "j_lusty_joker": (1, 3),
    "j_wrathful_joker": (0, 3),
    "j_gluttenous_joker": (2, 3),
}

TYPE_MULT_JOKERS = {
    "j_jolly": (PAIR, 8),
    "j_zany": (THREE_OF_A_KIND, 12),
    "j_mad": (TWO_PAIR, 10),
    "j_crazy": (STRAIGHT, 12),
    "j_droll": (FLUSH, 10),
}

TYPE_CHIP_JOKERS = {
    "j_sly": (PAIR, 50),
    "j_wily": (THREE_OF_A_KIND, 100),
    "j_clever": (TWO_PAIR, 80),
    "j_devious": (STRAIGHT, 100),
    "j_crafty": (FLUSH, 80),
}

CONTAINED_TYPE_MULT_JOKERS = {
    "j_jolly": (PAIR, 8),
    "j_zany": (THREE_OF_A_KIND, 12),
    "j_mad": (TWO_PAIR, 10),
    "j_crazy": (STRAIGHT, 12),
    "j_droll": (FLUSH, 10),
}

CONTAINED_TYPE_CHIP_JOKERS = {
    "j_sly": (PAIR, 50),
    "j_wily": (THREE_OF_A_KIND, 100),
    "j_clever": (TWO_PAIR, 80),
    "j_devious": (STRAIGHT, 100),
    "j_crafty": (FLUSH, 80),
}

CONTAINED_TYPE_XMULT_JOKERS = {
    "j_duo": (PAIR, 2.0),
    "j_trio": (THREE_OF_A_KIND, 3.0),
    "j_order": (STRAIGHT, 3.0),
    "j_tribe": (FLUSH, 2.0),
}

# Jokers whose score contribution is a random roll in the live game. The sim
# scores them at expected value, which is fine for valuation but breaks exact
# score parity — so the planner never buys them.
PROBABILISTIC_SCORE_JOKERS = frozenset({"j_bloodstone"})

IMPLEMENTED_JOKERS = frozenset(
    {
        # Hand-rule jokers are applied inside score_cards_with_joker_rules.
        "j_four_fingers",
        "j_shortcut",
        "j_smeared",
        "j_splash",
        "j_joker",
        "j_half",
        "j_even_steven",
        "j_odd_todd",
        "j_scholar",
        *SUIT_MULT_JOKERS.keys(),
        *TYPE_MULT_JOKERS.keys(),
        *TYPE_CHIP_JOKERS.keys(),
        *CONTAINED_TYPE_XMULT_JOKERS.keys(),
        "j_stencil",
        "j_banner",
        "j_mystic_summit",
        "j_misprint",
        "j_abstract",
        "j_supernova",
        "j_blue_joker",
        "j_bull",
        "j_bootstraps",
        "j_ice_cream",
        "j_runner",
        "j_green_joker",
        "j_ride_the_bus",
        "j_cavendish",
        "j_acrobat",
        "j_family",
        "j_stuntman",
        "j_popcorn",
        "j_constellation",
        "j_ramen",
        "j_throwback",
        "j_swashbuckler",
        "j_baseball",
        "j_blackboard",
        "j_obelisk",
        "j_steel_joker",
        "j_gros_michel",
        "j_vampire",
        "j_glass",
        "j_seeing_double",
        "j_fibonacci",
        "j_scary_face",
        "j_smiley",
        "j_walkie_talkie",
        "j_photograph",
        "j_bloodstone",
        "j_triboulet",
        "j_arrowhead",
        "j_onyx_agate",
        "j_baron",
        "j_card_sharp",
        "j_ceremonial",
        "j_flash",
        "j_shoot_the_moon",
        "j_square",
        "j_stone",
        "j_trousers",
        "j_ancient",
        "j_caino",
        "j_campfire",
        "j_castle",
        "j_drivers_license",
        "j_erosion",
        "j_flower_pot",
        "j_fortune_teller",
        "j_hit_the_road",
        "j_hologram",
        "j_idol",
        "j_loyalty_card",
        "j_lucky_cat",
        "j_madness",
        "j_pareidolia",
        "j_raised_fist",
        "j_red_card",
        "j_wee",
        "j_yorick",
    }
)


def apply_additive_jokers(
    score: FastScore,
    sorted_cards: tuple[int, ...],
    selected_count: int,
    jokers: tuple[Joker, ...],
    context: ScoreContext | None = None,
) -> FastScore:
    context = context or ScoreContext()
    joker_count = len(jokers) if context.joker_count is None else context.joker_count
    chips = score.chips
    mult = float(score.mult)
    x_mult = 1.0

    # Card-phase x-mults trigger while the cards score, before any joker adds
    # its mult (verified against live traces: Photograph doubles the base
    # mult, not the post-joker total).
    if any(joker.key == "j_photograph" for joker in jokers) and _scored_face_count(
        sorted_cards,
        score.scoring_mask,
        context.all_cards_are_face or _has_joker(jokers, "j_pareidolia"),
    ) > 0:
        mult *= 2.0

    for joker in jokers:
        if joker.key == "j_joker":
            mult += 4
        elif joker.key == "j_half" and selected_count <= 3:
            mult += 20
        elif joker.key == "j_stencil":
            x_mult *= 1.0 + max(context.joker_slots - joker_count, 0)
        elif joker.key == "j_banner":
            chips += 30 * context.discards_left
        elif joker.key == "j_mystic_summit" and context.discards_left == 0:
            mult += 15
        elif joker.key == "j_misprint":
            mult += joker.scaling if joker.scaling > 0 else 12
        elif joker.key == "j_abstract":
            mult += 3 * joker_count
        elif joker.key == "j_supernova":
            mult += context.hand_times_played.get(score.kind, 0)
        elif joker.key == "j_blue_joker":
            chips += 2 * context.deck_count
        elif joker.key == "j_bull":
            chips += 2 * context.money
        elif joker.key == "j_bootstraps":
            mult += 2 * (context.money // 5)
        elif joker.key == "j_ice_cream":
            chips += joker.scaling
        elif joker.key == "j_square":
            chips += joker.scaling + (4 if selected_count == 4 else 0)
        elif joker.key == "j_wee":
            chips += joker.scaling
        elif joker.key == "j_castle":
            chips += joker.scaling
        elif joker.key == "j_stone":
            chips += 25 * joker.scaling
        elif joker.key == "j_runner":
            chips += joker.scaling + (15 if _hand_contains(score.kind, STRAIGHT) else 0)
        elif joker.key == "j_green_joker":
            mult += joker.scaling + 1
        elif joker.key == "j_erosion":
            mult += max(context.starting_deck_size - context.playing_card_count, 0) * 4
        elif joker.key == "j_fortune_teller":
            mult += context.tarot_cards_used
        elif joker.key == "j_ride_the_bus" and _scored_face_count(
            sorted_cards,
            score.scoring_mask,
            context.all_cards_are_face or _has_joker(jokers, "j_pareidolia"),
        ) == 0:
            mult += joker.scaling + 1
        elif joker.key == "j_cavendish":
            x_mult *= 3.0
        elif joker.key == "j_acrobat" and context.hands_left == 0:
            x_mult *= 3.0
        elif joker.key == "j_family" and score.kind == FOUR_OF_A_KIND:
            x_mult *= 4.0
        elif joker.key == "j_stuntman":
            chips += 250
        elif joker.key == "j_popcorn":
            mult += joker.scaling
        elif joker.key == "j_constellation":
            x_mult *= joker.x_mult
        elif joker.key in {
            "j_caino",
            "j_campfire",
            "j_hit_the_road",
            "j_hologram",
            "j_lucky_cat",
            "j_madness",
            "j_yorick",
        }:
            x_mult *= joker.x_mult
        elif joker.key == "j_ramen":
            x_mult *= joker.x_mult if joker.x_mult > 0 else 2.0
        elif joker.key == "j_throwback":
            x_mult *= 1.0 + 0.25 * context.blinds_skipped
        elif joker.key == "j_swashbuckler":
            mult += sum(other.sell_value for other in jokers if other is not joker)
        elif joker.key == "j_ceremonial":
            mult += joker.scaling
        elif joker.key == "j_flash":
            mult += joker.scaling
        elif joker.key == "j_trousers":
            mult += joker.scaling + (2 if _hand_contains(score.kind, TWO_PAIR) else 0)
        elif joker.key == "j_red_card":
            mult += joker.scaling
        elif joker.key == "j_shoot_the_moon":
            mult += _held_rank_count(context.held_cards, 10) * 13
        elif joker.key == "j_raised_fist":
            lowest_nominal = _lowest_held_nominal(
                context.held_cards,
                context.debuffed_held_suits,
                context.debuffed_held_cards,
            )
            if lowest_nominal is not None:
                mult += 2 * lowest_nominal
        elif joker.key == "j_blackboard" and context.held_cards:
            if all(suit(card) in (0, 2) for card in context.held_cards):
                x_mult *= 3.0
        elif joker.key == "j_baron":
            x_mult *= 1.5 ** _held_rank_count(context.held_cards, 11)
        elif joker.key == "j_loyalty_card" and context.loyalty_remaining == 0:
            x_mult *= 4.0
        elif joker.key == "j_obelisk":
            x_mult *= joker.x_mult
        elif joker.key == "j_steel_joker":
            x_mult *= 1.0 + 0.2 * joker.scaling
        elif joker.key == "j_gros_michel":
            mult += 15
        elif joker.key == "j_vampire":
            x_mult *= joker.x_mult
        elif joker.key == "j_glass":
            x_mult *= joker.x_mult
        elif joker.key == "j_seeing_double" and _has_club_and_other_suit(sorted_cards, score.scoring_mask):
            x_mult *= 2.0
        elif joker.key == "j_card_sharp" and context.hand_times_played_round.get(score.kind, 0) > 1:
            x_mult *= 3.0
        elif joker.key == "j_drivers_license" and context.enhanced_card_count >= 16:
            x_mult *= 3.0
        elif joker.key == "j_even_steven":
            mult += _scored_rank_count(sorted_cards, score.scoring_mask, {0, 2, 4, 6, 8}) * 4
        elif joker.key == "j_odd_todd":
            chips += _scored_rank_count(sorted_cards, score.scoring_mask, {1, 3, 5, 7, 12}) * 31
        elif joker.key == "j_scholar":
            aces = _scored_rank_count(sorted_cards, score.scoring_mask, {12})
            chips += aces * 20
            mult += aces * 4
        elif joker.key == "j_fibonacci":
            mult += _scored_rank_count(sorted_cards, score.scoring_mask, {0, 1, 3, 6, 12}) * 8
        elif joker.key == "j_scary_face":
            chips += _scored_face_count(
                sorted_cards,
                score.scoring_mask,
                context.all_cards_are_face or _has_joker(jokers, "j_pareidolia"),
            ) * 30
        elif joker.key == "j_smiley":
            mult += _scored_face_count(
                sorted_cards,
                score.scoring_mask,
                context.all_cards_are_face or _has_joker(jokers, "j_pareidolia"),
            ) * 5
        elif joker.key == "j_walkie_talkie":
            count = _scored_rank_count(sorted_cards, score.scoring_mask, {2, 8})
            chips += count * 10
            mult += count * 4
        elif joker.key == "j_photograph":
            pass  # applied in the card phase above
        elif joker.key == "j_bloodstone":
            x_mult *= 1.25 ** _scored_suit_count(sorted_cards, score.scoring_mask, 1)
        elif joker.key == "j_ancient" and context.current_ancient_suit is not None:
            x_mult *= 1.5 ** _scored_suit_count(
                sorted_cards,
                score.scoring_mask,
                context.current_ancient_suit,
            )
        elif (
            joker.key == "j_idol"
            and context.current_idol_rank is not None
            and context.current_idol_suit is not None
        ):
            x_mult *= 2.0 ** _scored_rank_suit_count(
                sorted_cards,
                score.scoring_mask,
                context.current_idol_rank,
                context.current_idol_suit,
            )
        elif joker.key == "j_triboulet":
            x_mult *= 2.0 ** _scored_rank_count(sorted_cards, score.scoring_mask, {10, 11})
        elif joker.key in SUIT_MULT_JOKERS:
            target_suit, add_mult = SUIT_MULT_JOKERS[joker.key]
            mult += _scored_suit_count(sorted_cards, score.scoring_mask, target_suit) * add_mult
        elif joker.key == "j_arrowhead":
            chips += _scored_suit_count(sorted_cards, score.scoring_mask, 0) * 50
        elif joker.key == "j_onyx_agate":
            mult += _scored_suit_count(sorted_cards, score.scoring_mask, 2) * 7
        elif joker.key == "j_flower_pot" and _has_all_four_suits(sorted_cards, score.scoring_mask):
            x_mult *= 3.0
        elif joker.key in CONTAINED_TYPE_MULT_JOKERS:
            target_kind, add_mult = CONTAINED_TYPE_MULT_JOKERS[joker.key]
            if _hand_contains(score.kind, target_kind):
                mult += add_mult
        elif joker.key in CONTAINED_TYPE_CHIP_JOKERS:
            target_kind, add_chips = CONTAINED_TYPE_CHIP_JOKERS[joker.key]
            if _hand_contains(score.kind, target_kind):
                chips += add_chips
        elif joker.key in CONTAINED_TYPE_XMULT_JOKERS:
            target_kind, add_xmult = CONTAINED_TYPE_XMULT_JOKERS[joker.key]
            if _hand_contains(score.kind, target_kind):
                x_mult *= add_xmult
        elif joker.key in TYPE_MULT_JOKERS:
            target_kind, add_mult = TYPE_MULT_JOKERS[joker.key]
            if score.kind == target_kind:
                mult += add_mult
        elif joker.key in TYPE_CHIP_JOKERS:
            target_kind, add_chips = TYPE_CHIP_JOKERS[joker.key]
            if score.kind == target_kind:
                chips += add_chips

        edition = Edition(joker.edition)
        chips += edition_chip_bonus(edition)
        mult += edition_mult_bonus(edition)
        x_mult *= edition_xmult(edition)

    return FastScore(
        kind=score.kind,
        chips=chips,
        mult=mult,
        total=int(chips * mult * x_mult),
        scoring_mask=score.scoring_mask,
    )


def _scored_suit_count(cards: tuple[int, ...], scoring_mask: int, target_suit: int) -> int:
    return sum(
        1
        for index, card in enumerate(cards)
        if scoring_mask & (1 << index) and suit(card) == target_suit
    )


def _scored_rank_suit_count(
    cards: tuple[int, ...],
    scoring_mask: int,
    target_rank: int,
    target_suit: int,
) -> int:
    return sum(
        1
        for index, card in enumerate(cards)
        if scoring_mask & (1 << index) and rank(card) == target_rank and suit(card) == target_suit
    )


def _scored_rank_count(cards: tuple[int, ...], scoring_mask: int, target_ranks: set[int]) -> int:
    return sum(
        1
        for index, card in enumerate(cards)
        if scoring_mask & (1 << index) and rank(card) in target_ranks
    )


def _scored_face_count(cards: tuple[int, ...], scoring_mask: int, all_cards_are_face: bool = False) -> int:
    if all_cards_are_face:
        return scoring_mask.bit_count()
    return _scored_rank_count(cards, scoring_mask, {9, 10, 11})


def _has_face_card(cards: tuple[int, ...]) -> bool:
    return any(rank(card) in {9, 10, 11} for card in cards)


def _has_joker(jokers: tuple[Joker, ...], key: str) -> bool:
    return any(joker.key == key for joker in jokers)


def _held_rank_count(cards: tuple[int, ...], target_rank: int) -> int:
    return sum(1 for card in cards if rank(card) == target_rank)


def _lowest_held_nominal(
    cards: tuple[int, ...],
    debuffed_suits: frozenset[int] = frozenset(),
    debuffed_cards: frozenset[int] = frozenset(),
) -> int | None:
    if not cards:
        return None
    lowest_card = cards[0]
    lowest_rank = rank(lowest_card)
    for card in cards:
        card_rank = rank(card)
        if card_rank <= lowest_rank:
            lowest_card = card
            lowest_rank = card_rank
    if suit(lowest_card) in debuffed_suits or lowest_card in debuffed_cards:
        return None
    return card_chips(lowest_card)


def _has_club_and_other_suit(cards: tuple[int, ...], scoring_mask: int) -> bool:
    scored_suits = {
        suit(card)
        for index, card in enumerate(cards)
        if scoring_mask & (1 << index)
    }
    return 2 in scored_suits and len(scored_suits) > 1


def _has_all_four_suits(cards: tuple[int, ...], scoring_mask: int) -> bool:
    scored_suits = {
        suit(card)
        for index, card in enumerate(cards)
        if scoring_mask & (1 << index)
    }
    return len(scored_suits) == 4


def _hand_contains(hand_kind: int, contained_kind: int) -> bool:
    if contained_kind == PAIR:
        return hand_kind in {
            PAIR,
            TWO_PAIR,
            THREE_OF_A_KIND,
            FULL_HOUSE,
            FOUR_OF_A_KIND,
            FIVE_OF_A_KIND,
            FLUSH_HOUSE,
            FLUSH_FIVE,
        }
    if contained_kind == TWO_PAIR:
        return hand_kind in {TWO_PAIR, FULL_HOUSE, FLUSH_HOUSE}
    if contained_kind == THREE_OF_A_KIND:
        return hand_kind in {
            THREE_OF_A_KIND,
            FULL_HOUSE,
            FOUR_OF_A_KIND,
            FIVE_OF_A_KIND,
            FLUSH_HOUSE,
            FLUSH_FIVE,
        }
    if contained_kind == STRAIGHT:
        return hand_kind in {STRAIGHT, STRAIGHT_FLUSH}
    if contained_kind == FLUSH:
        return hand_kind in {FLUSH, STRAIGHT_FLUSH, FLUSH_HOUSE, FLUSH_FIVE}
    return hand_kind == contained_kind
