"""Source-audited strategic metadata for the 150 base-game Jokers.

The keys and mechanics are derived from Jackdaw's pinned ``centers.json`` and
``engine/jokers.py`` at revision ``dbedc66255fe594cce7b7cccc188c8a11649d9ec``.
Build tags and the distinction between scaling/economy roles also preserve the
historical strategist groupings in :mod:`balatro_ai_v2.baselines`.

This module is deliberately data-only.  It neither imports a game engine nor
attempts to recover mechanics from display text or runtime ability payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Literal, TypeAlias


JokerRole: TypeAlias = Literal[
    "x_mult",
    "scaling",
    "retrigger",
    "flat_mult",
    "chips",
    "economy",
    "utility",
]
JokerRarity: TypeAlias = Literal[1, 2, 3, 4]
JokerRouteTag: TypeAlias = Literal[
    "held_anchor",
    "held_enabler",
    "played_anchor",
    "played_enabler",
    "consumable_anchor",
    "copy",
]

ArchetypeTag: TypeAlias = Literal[
    "high_card",
    "pair",
    "two_pair",
    "three_of_a_kind",
    "four_of_a_kind",
    "straight",
    "flush",
    "full_house",
    "straight_flush",
    "small_hand",
    "four_card_hand",
    "single_card",
    "repeat_hand",
    "hand_variety",
    "face_cards",
    "low_ranks",
    "even_ranks",
    "odd_ranks",
    "aces",
    "twos",
    "jacks",
    "queens",
    "kings",
    "nines",
    "diamonds",
    "hearts",
    "spades",
    "clubs",
    "mixed_suits",
    "held_cards",
    "discard",
    "no_discard",
    "deck_growth",
    "deck_thinning",
    "enhanced_cards",
    "stone_cards",
    "steel_cards",
    "glass_cards",
    "gold_cards",
    "lucky_cards",
    "hand_levels",
    "joker_heavy",
    "consumables",
    "tarot",
    "planets",
]


@dataclass(frozen=True, slots=True)
class JokerProfile:
    """Static public strategy metadata for one vanilla Joker."""

    key: str
    primary_role: JokerRole
    archetypes: frozenset[ArchetypeTag]
    order_sensitive: bool
    score_effect: bool
    rarity: JokerRarity = 1
    route_tags: frozenset[JokerRouteTag] = frozenset()

    @property
    def role(self) -> JokerRole:
        """Concise alias for callers grouping profiles by primary role."""

        return self.primary_role

    @property
    def tags(self) -> frozenset[ArchetypeTag]:
        """Concise alias for callers matching build archetypes."""

        return self.archetypes


def _j(
    key: str,
    primary_role: JokerRole,
    *archetypes: ArchetypeTag,
    order_sensitive: bool = False,
    score_effect: bool = False,
) -> JokerProfile:
    return JokerProfile(
        key=key,
        primary_role=primary_role,
        archetypes=frozenset(archetypes),
        order_sensitive=order_sensitive,
        score_effect=score_effect,
    )


# Ordered by the vanilla center order.  ``order_sensitive`` means that the
# realized effect depends on a meaningful card/Joker sequence, beyond the
# generic advice to put additive Mult before multiplicative Mult.
_PROFILES = (
    _j("j_joker", "flat_mult", score_effect=True),
    _j("j_greedy_joker", "flat_mult", "diamonds", score_effect=True),
    _j("j_lusty_joker", "flat_mult", "hearts", score_effect=True),
    _j("j_wrathful_joker", "flat_mult", "spades", score_effect=True),
    _j("j_gluttenous_joker", "flat_mult", "clubs", score_effect=True),
    _j("j_jolly", "flat_mult", "pair", score_effect=True),
    _j("j_zany", "flat_mult", "three_of_a_kind", score_effect=True),
    _j("j_mad", "flat_mult", "two_pair", score_effect=True),
    _j("j_crazy", "flat_mult", "straight", score_effect=True),
    _j("j_droll", "flat_mult", "flush", score_effect=True),
    _j("j_sly", "chips", "pair", score_effect=True),
    _j("j_wily", "chips", "three_of_a_kind", score_effect=True),
    _j("j_clever", "chips", "two_pair", score_effect=True),
    _j("j_devious", "chips", "straight", score_effect=True),
    _j("j_crafty", "chips", "flush", score_effect=True),
    _j("j_half", "flat_mult", "small_hand", score_effect=True),
    _j("j_stencil", "x_mult", score_effect=True),
    _j("j_four_fingers", "utility", "straight", "flush"),
    _j("j_mime", "retrigger", "held_cards", order_sensitive=True, score_effect=True),
    _j("j_credit_card", "economy"),
    _j(
        "j_ceremonial",
        "scaling",
        "joker_heavy",
        order_sensitive=True,
        score_effect=True,
    ),
    _j("j_banner", "chips", "discard", score_effect=True),
    _j("j_mystic_summit", "flat_mult", "no_discard", score_effect=True),
    _j("j_marble", "utility", "stone_cards", "deck_growth"),
    _j("j_loyalty_card", "x_mult", "repeat_hand", score_effect=True),
    _j("j_8_ball", "utility", "low_ranks", "tarot"),
    _j("j_misprint", "flat_mult", score_effect=True),
    _j("j_dusk", "retrigger", order_sensitive=True, score_effect=True),
    _j(
        "j_raised_fist",
        "flat_mult",
        "held_cards",
        "low_ranks",
        order_sensitive=True,
        score_effect=True,
    ),
    _j("j_chaos", "economy"),
    _j("j_fibonacci", "flat_mult", "low_ranks", "aces", score_effect=True),
    _j("j_steel_joker", "x_mult", "steel_cards", score_effect=True),
    _j("j_scary_face", "chips", "face_cards", score_effect=True),
    _j("j_abstract", "flat_mult", "joker_heavy", score_effect=True),
    _j("j_delayed_grat", "economy", "no_discard"),
    _j("j_hack", "retrigger", "low_ranks", order_sensitive=True, score_effect=True),
    _j("j_pareidolia", "utility", "face_cards"),
    _j("j_gros_michel", "flat_mult", score_effect=True),
    _j("j_even_steven", "flat_mult", "even_ranks", score_effect=True),
    _j("j_odd_todd", "chips", "odd_ranks", score_effect=True),
    _j("j_scholar", "chips", "aces", score_effect=True),
    _j("j_business", "economy", "face_cards"),
    _j("j_supernova", "scaling", "repeat_hand", score_effect=True),
    _j("j_ride_the_bus", "scaling", "face_cards", score_effect=True),
    _j("j_space", "utility", "hand_levels"),
    _j("j_egg", "economy", "joker_heavy"),
    _j("j_burglar", "utility", "no_discard"),
    _j(
        "j_blackboard",
        "x_mult",
        "held_cards",
        "clubs",
        "spades",
        order_sensitive=True,
        score_effect=True,
    ),
    _j("j_runner", "scaling", "straight", score_effect=True),
    _j("j_ice_cream", "chips", score_effect=True),
    _j("j_dna", "utility", "single_card", "deck_growth"),
    _j("j_splash", "utility"),
    _j("j_blue_joker", "chips", "deck_growth", score_effect=True),
    _j("j_sixth_sense", "utility", "single_card", "low_ranks"),
    _j("j_constellation", "scaling", "planets", "hand_levels", score_effect=True),
    _j("j_hiker", "scaling", score_effect=True),
    _j("j_faceless", "economy", "face_cards", "discard"),
    _j("j_green_joker", "scaling", "no_discard", score_effect=True),
    _j("j_superposition", "utility", "straight", "aces", "tarot"),
    _j("j_todo_list", "economy", "hand_variety"),
    _j("j_cavendish", "x_mult", score_effect=True),
    _j("j_card_sharp", "x_mult", "repeat_hand", score_effect=True),
    _j("j_red_card", "scaling", score_effect=True),
    _j("j_madness", "scaling", "joker_heavy", score_effect=True),
    _j("j_square", "scaling", "four_card_hand", score_effect=True),
    _j("j_seance", "utility", "straight_flush"),
    _j("j_riff_raff", "economy", "joker_heavy"),
    _j("j_vampire", "scaling", "enhanced_cards", score_effect=True),
    _j("j_shortcut", "utility", "straight"),
    _j("j_hologram", "scaling", "deck_growth", score_effect=True),
    _j("j_vagabond", "utility", "tarot"),
    _j(
        "j_baron",
        "x_mult",
        "held_cards",
        "kings",
        order_sensitive=True,
        score_effect=True,
    ),
    _j("j_cloud_9", "economy", "nines"),
    _j("j_rocket", "economy"),
    _j("j_obelisk", "scaling", "hand_variety", score_effect=True),
    _j("j_midas_mask", "utility", "face_cards", "gold_cards"),
    _j("j_luchador", "utility"),
    _j("j_photograph", "x_mult", "face_cards", order_sensitive=True, score_effect=True),
    _j("j_gift", "economy", "joker_heavy", "consumables"),
    _j("j_turtle_bean", "utility"),
    _j("j_erosion", "chips", "deck_thinning", score_effect=True),
    _j("j_reserved_parking", "economy", "held_cards", "face_cards"),
    _j("j_mail", "economy", "discard"),
    _j("j_to_the_moon", "economy"),
    _j("j_hallucination", "utility", "consumables"),
    _j("j_fortune_teller", "scaling", "tarot", score_effect=True),
    _j("j_juggler", "utility"),
    _j("j_drunkard", "utility", "discard"),
    _j("j_stone", "chips", "stone_cards", score_effect=True),
    _j("j_golden", "economy"),
    _j("j_lucky_cat", "scaling", "lucky_cards", score_effect=True),
    _j("j_baseball", "x_mult", "joker_heavy", order_sensitive=True, score_effect=True),
    _j("j_bull", "chips", score_effect=True),
    _j("j_diet_cola", "utility"),
    _j("j_trading", "economy", "single_card", "discard", "deck_thinning"),
    _j("j_flash", "scaling", score_effect=True),
    _j("j_popcorn", "flat_mult", score_effect=True),
    _j("j_trousers", "scaling", "two_pair", "full_house", score_effect=True),
    _j("j_ancient", "x_mult", "flush", order_sensitive=True, score_effect=True),
    _j("j_ramen", "x_mult", order_sensitive=True, score_effect=True),
    _j("j_walkie_talkie", "chips", "low_ranks", score_effect=True),
    _j("j_selzer", "retrigger", order_sensitive=True, score_effect=True),
    _j("j_castle", "scaling", "flush", "discard", score_effect=True),
    _j("j_smiley", "flat_mult", "face_cards", score_effect=True),
    _j("j_campfire", "scaling", score_effect=True),
    _j("j_ticket", "economy", "gold_cards"),
    _j("j_mr_bones", "utility"),
    _j("j_acrobat", "x_mult", order_sensitive=True, score_effect=True),
    _j(
        "j_sock_and_buskin",
        "retrigger",
        "face_cards",
        order_sensitive=True,
        score_effect=True,
    ),
    _j("j_swashbuckler", "flat_mult", "joker_heavy", score_effect=True),
    _j("j_troubadour", "utility"),
    _j("j_certificate", "utility", "deck_growth"),
    _j("j_smeared", "utility", "flush"),
    _j("j_throwback", "scaling", score_effect=True),
    _j("j_hanging_chad", "retrigger", order_sensitive=True, score_effect=True),
    _j("j_rough_gem", "economy", "diamonds"),
    _j("j_bloodstone", "x_mult", "hearts", order_sensitive=True, score_effect=True),
    _j("j_arrowhead", "chips", "spades", score_effect=True),
    _j("j_onyx_agate", "flat_mult", "clubs", score_effect=True),
    _j("j_glass", "scaling", "glass_cards", score_effect=True),
    _j("j_ring_master", "utility"),
    _j(
        "j_flower_pot", "x_mult", "mixed_suits", order_sensitive=True, score_effect=True
    ),
    _j(
        "j_blueprint", "utility", "joker_heavy", order_sensitive=True, score_effect=True
    ),
    _j("j_wee", "scaling", "twos", score_effect=True),
    _j("j_merry_andy", "utility", "discard"),
    _j("j_oops", "utility", "lucky_cards"),
    _j("j_idol", "x_mult", order_sensitive=True, score_effect=True),
    _j("j_seeing_double", "x_mult", "clubs", order_sensitive=True, score_effect=True),
    _j("j_matador", "economy"),
    _j("j_hit_the_road", "scaling", "jacks", "discard", score_effect=True),
    _j("j_duo", "x_mult", "pair", score_effect=True),
    _j("j_trio", "x_mult", "three_of_a_kind", score_effect=True),
    _j("j_family", "x_mult", "four_of_a_kind", score_effect=True),
    _j("j_order", "x_mult", "straight", score_effect=True),
    _j("j_tribe", "x_mult", "flush", score_effect=True),
    _j("j_stuntman", "chips", score_effect=True),
    _j("j_invisible", "utility"),
    _j(
        "j_brainstorm",
        "utility",
        "joker_heavy",
        order_sensitive=True,
        score_effect=True,
    ),
    _j("j_satellite", "economy", "planets"),
    _j(
        "j_shoot_the_moon",
        "flat_mult",
        "held_cards",
        "queens",
        order_sensitive=True,
        score_effect=True,
    ),
    _j("j_drivers_license", "x_mult", "enhanced_cards", score_effect=True),
    _j("j_cartomancer", "utility", "tarot"),
    _j("j_astronomer", "economy", "planets", "hand_levels"),
    _j("j_burnt", "utility", "discard", "hand_levels"),
    _j("j_bootstraps", "flat_mult", score_effect=True),
    _j("j_caino", "scaling", "face_cards", "deck_thinning", score_effect=True),
    _j(
        "j_triboulet",
        "x_mult",
        "kings",
        "queens",
        order_sensitive=True,
        score_effect=True,
    ),
    _j("j_yorick", "scaling", "discard", score_effect=True),
    _j("j_chicot", "utility"),
    _j("j_perkeo", "utility", "consumables"),
)

_RARITY_2_KEYS = frozenset(
    {
        "j_acrobat",
        "j_arrowhead",
        "j_astronomer",
        "j_blackboard",
        "j_bloodstone",
        "j_bootstraps",
        "j_bull",
        "j_burglar",
        "j_card_sharp",
        "j_cartomancer",
        "j_castle",
        "j_ceremonial",
        "j_certificate",
        "j_cloud_9",
        "j_constellation",
        "j_diet_cola",
        "j_dusk",
        "j_erosion",
        "j_fibonacci",
        "j_flash",
        "j_flower_pot",
        "j_four_fingers",
        "j_gift",
        "j_glass",
        "j_hack",
        "j_hiker",
        "j_hologram",
        "j_idol",
        "j_loyalty_card",
        "j_luchador",
        "j_lucky_cat",
        "j_madness",
        "j_marble",
        "j_matador",
        "j_merry_andy",
        "j_midas_mask",
        "j_mime",
        "j_mr_bones",
        "j_onyx_agate",
        "j_oops",
        "j_pareidolia",
        "j_ramen",
        "j_ring_master",
        "j_rocket",
        "j_rough_gem",
        "j_satellite",
        "j_seance",
        "j_seeing_double",
        "j_selzer",
        "j_shortcut",
        "j_sixth_sense",
        "j_smeared",
        "j_sock_and_buskin",
        "j_space",
        "j_steel_joker",
        "j_stencil",
        "j_stone",
        "j_throwback",
        "j_to_the_moon",
        "j_trading",
        "j_troubadour",
        "j_trousers",
        "j_turtle_bean",
        "j_vampire",
    }
)
_RARITY_3_KEYS = frozenset(
    {
        "j_ancient",
        "j_baron",
        "j_baseball",
        "j_blueprint",
        "j_brainstorm",
        "j_burnt",
        "j_campfire",
        "j_dna",
        "j_drivers_license",
        "j_duo",
        "j_family",
        "j_hit_the_road",
        "j_invisible",
        "j_obelisk",
        "j_order",
        "j_stuntman",
        "j_tribe",
        "j_trio",
        "j_vagabond",
        "j_wee",
    }
)
_RARITY_4_KEYS = frozenset(
    {"j_caino", "j_chicot", "j_perkeo", "j_triboulet", "j_yorick"}
)
_NON_COMMON_RARITIES = {
    **{key: 2 for key in _RARITY_2_KEYS},
    **{key: 3 for key in _RARITY_3_KEYS},
    **{key: 4 for key in _RARITY_4_KEYS},
}
_ROUTE_TAGS: dict[str, frozenset[JokerRouteTag]] = {
    "j_baron": frozenset({"held_anchor"}),
    "j_mime": frozenset({"held_enabler"}),
    "j_idol": frozenset({"played_anchor"}),
    "j_triboulet": frozenset({"played_anchor"}),
    "j_dusk": frozenset({"played_enabler"}),
    "j_hack": frozenset({"played_enabler"}),
    "j_selzer": frozenset({"played_enabler"}),
    "j_sock_and_buskin": frozenset({"played_enabler"}),
    "j_hanging_chad": frozenset({"played_enabler"}),
    "j_perkeo": frozenset({"consumable_anchor"}),
    "j_blueprint": frozenset({"copy"}),
    "j_brainstorm": frozenset({"copy"}),
}
_PROFILES = tuple(
    replace(
        profile,
        rarity=_NON_COMMON_RARITIES.get(profile.key, 1),
        route_tags=_ROUTE_TAGS.get(profile.key, frozenset()),
    )
    for profile in _PROFILES
)

if len(_PROFILES) != 150 or len({profile.key for profile in _PROFILES}) != 150:
    raise RuntimeError("base Joker catalog must contain exactly 150 unique entries")
if any(not profile.key.startswith("j_") for profile in _PROFILES):
    raise RuntimeError("base Joker catalog contains a non-Joker key")
if set(_NON_COMMON_RARITIES) - {profile.key for profile in _PROFILES}:
    raise RuntimeError("Joker rarity catalog contains an unknown key")
if set(_ROUTE_TAGS) - {profile.key for profile in _PROFILES}:
    raise RuntimeError("Joker route catalog contains an unknown key")
if len(_NON_COMMON_RARITIES) != sum(
    len(keys) for keys in (_RARITY_2_KEYS, _RARITY_3_KEYS, _RARITY_4_KEYS)
):
    raise RuntimeError("Joker rarity catalog contains overlapping keys")

JOKER_CATALOG = MappingProxyType({profile.key: profile for profile in _PROFILES})


def get_joker_profile(key: str) -> JokerProfile:
    """Return metadata for an exact base-Joker key, failing closed if unknown."""

    try:
        return JOKER_CATALOG[key]
    except KeyError:
        raise KeyError(f"unknown base Joker key: {key!r}") from None


lookup_joker = get_joker_profile


__all__ = [
    "ArchetypeTag",
    "JOKER_CATALOG",
    "JokerProfile",
    "JokerRarity",
    "JokerRole",
    "JokerRouteTag",
    "get_joker_profile",
    "lookup_joker",
]
