"""Source-audited Joker mechanics admitted to public blind rollouts.

The sets in this module are capability declarations, not a catalog of Jokers
that the policy can observe or buy.  Unknown mechanics remain baseline-only.
"""

from __future__ import annotations

from collections.abc import Iterable

from balatro_ai_v2.public_state import PublicItem, VisiblePlayingCard


TACTICAL_EXACT_JOKERS = frozenset(
    {
        "j_banner",
        "j_bull",
        "j_crafty",
        "j_credit_card",
        "j_droll",
        "j_drunkard",
        "j_faceless",
        "j_greedy_joker",
        "j_gluttenous_joker",
        "j_joker",
        "j_lusty_joker",
        "j_mystic_summit",
        "j_riff_raff",
        "j_scary_face",
        "j_sly",
        "j_wily",
    }
)

# Riff-Raff creates Jokers when a blind is selected.  A current-blind rollout
# may safely treat it as scoring-neutral, but a shop-to-next-blind rollout may
# not omit that setup transition.
PREBLIND_EXACT_JOKERS = TACTICAL_EXACT_JOKERS - {"j_riff_raff"}

# Exact for the immediate score of one fully visible sampled hand.  This is a
# narrower contract than PREBLIND_EXACT_JOKERS: membership does not claim that
# a whole blind's mutations or economy are modeled.
ONE_PLAY_CAPACITY_EXACT_JOKERS = PREBLIND_EXACT_JOKERS | {
    "j_blue_joker",
    "j_clever",
    "j_even_steven",
    "j_flash",
    "j_green_joker",
    "j_half",
    "j_hanging_chad",
    "j_ice_cream",
    "j_jolly",
    "j_juggler",
    "j_mad",
    "j_odd_todd",
    "j_photograph",
    "j_popcorn",
    "j_raised_fist",
    "j_red_card",
    "j_ride_the_bus",
    "j_scholar",
    "j_seeing_double",
    "j_shoot_the_moon",
    "j_stuntman",
    "j_supernova",
    "j_swashbuckler",
    "j_square",
    "j_trousers",
    "j_walkie_talkie",
    "j_wrathful_joker",
}

ONE_PLAY_CAPACITY_RUNTIME_FIELD = {
    "j_flash": "current_mult",
    "j_green_joker": "current_mult",
    "j_ice_cream": "current_chips",
    "j_popcorn": "current_mult",
    "j_red_card": "current_mult",
    "j_ride_the_bus": "current_mult",
    "j_square": "current_chips",
    "j_swashbuckler": "current_mult",
    "j_trousers": "current_mult",
}

_FACE_RANKS = frozenset({"J", "Q", "K"})


def faceless_discard_reward(
    jokers: Iterable[PublicItem],
    discarded: Iterable[VisiblePlayingCard],
) -> int:
    """Return the public money reward for one discard action."""

    if sum(card.rank in _FACE_RANKS and not card.debuffed for card in discarded) < 3:
        return 0
    active_copies = sum(
        joker.key == "j_faceless" and not joker.debuffed for joker in jokers
    )
    return 5 * active_copies


def purchased_discard_bonus(joker: PublicItem | None) -> int:
    """Return the next-round discard delta contributed by a new purchase."""

    return int(
        joker is not None
        and joker.key == "j_drunkard"
        and not joker.debuffed
        and joker.perishable_rounds != 0
    )


def exact_joker_multiplicity(jokers: Iterable[PublicItem]) -> bool:
    """Reject duplicate mechanics not yet covered by organic differentials."""

    return sum(joker.key == "j_credit_card" for joker in jokers) <= 1
