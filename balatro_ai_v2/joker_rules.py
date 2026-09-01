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
