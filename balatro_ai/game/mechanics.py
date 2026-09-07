"""Small, data-only public mechanics tables used by the game boundary."""

from __future__ import annotations


_PLANET_HANDS = {
    "c_pluto": "High Card",
    "c_mercury": "Pair",
    "c_uranus": "Two Pair",
    "c_venus": "Three of a Kind",
    "c_saturn": "Straight",
    "c_jupiter": "Flush",
    "c_earth": "Full House",
    "c_mars": "Four of a Kind",
    "c_neptune": "Straight Flush",
    "c_planet_x": "Five of a Kind",
    "c_ceres": "Flush House",
    "c_eris": "Flush Five",
}

_RARITY_2_KEYS = frozenset({
    "j_acrobat", "j_arrowhead", "j_astronomer", "j_blackboard", "j_bloodstone",
    "j_bootstraps", "j_bull", "j_burglar", "j_card_sharp", "j_cartomancer",
    "j_castle", "j_ceremonial", "j_certificate", "j_cloud_9", "j_constellation",
    "j_diet_cola", "j_dusk", "j_erosion", "j_fibonacci", "j_flash", "j_flower_pot",
    "j_four_fingers", "j_gift", "j_glass", "j_hack", "j_hiker", "j_hologram",
    "j_idol", "j_loyalty_card", "j_luchador", "j_lucky_cat", "j_madness",
    "j_marble", "j_matador", "j_merry_andy", "j_midas_mask", "j_mime", "j_mr_bones",
    "j_onyx_agate", "j_oops", "j_pareidolia", "j_ramen", "j_ring_master", "j_rocket",
    "j_rough_gem", "j_satellite", "j_seance", "j_seeing_double", "j_selzer",
    "j_shortcut", "j_sixth_sense", "j_smeared", "j_sock_and_buskin", "j_space",
    "j_steel_joker", "j_stencil", "j_stone", "j_throwback", "j_to_the_moon",
    "j_trading", "j_troubadour", "j_trousers", "j_turtle_bean", "j_vampire",
})
_RARITY_3_KEYS = frozenset({
    "j_ancient", "j_baron", "j_baseball", "j_blueprint", "j_brainstorm", "j_burnt",
    "j_campfire", "j_dna", "j_drivers_license", "j_duo", "j_family", "j_hit_the_road",
    "j_invisible", "j_obelisk", "j_order", "j_stuntman", "j_tribe", "j_trio",
    "j_vagabond", "j_wee",
})
_RARITY_4_KEYS = frozenset({"j_caino", "j_chicot", "j_perkeo", "j_triboulet", "j_yorick"})
_KNOWN_JOKER_KEYS = frozenset({
    "j_8_ball", "j_abstract", "j_acrobat", "j_ancient", "j_arrowhead", "j_astronomer", "j_banner", "j_baron",
    "j_baseball", "j_blackboard", "j_bloodstone", "j_blue_joker", "j_blueprint", "j_bootstraps", "j_brainstorm", "j_bull",
    "j_burglar", "j_burnt", "j_business", "j_caino", "j_campfire", "j_card_sharp", "j_cartomancer", "j_castle",
    "j_cavendish", "j_ceremonial", "j_certificate", "j_chaos", "j_chicot", "j_clever", "j_cloud_9", "j_constellation",
    "j_crafty", "j_crazy", "j_credit_card", "j_delayed_grat", "j_devious", "j_diet_cola", "j_dna", "j_drivers_license",
    "j_droll", "j_drunkard", "j_duo", "j_dusk", "j_egg", "j_erosion", "j_even_steven", "j_faceless",
    "j_family", "j_fibonacci", "j_flash", "j_flower_pot", "j_fortune_teller", "j_four_fingers", "j_gift", "j_glass",
    "j_gluttenous_joker", "j_golden", "j_greedy_joker", "j_green_joker", "j_gros_michel", "j_hack", "j_half", "j_hallucination",
    "j_hanging_chad", "j_hiker", "j_hit_the_road", "j_hologram", "j_ice_cream", "j_idol", "j_invisible", "j_joker",
    "j_jolly", "j_juggler", "j_loyalty_card", "j_luchador", "j_lucky_cat", "j_lusty_joker", "j_mad", "j_madness",
    "j_mail", "j_marble", "j_matador", "j_merry_andy", "j_midas_mask", "j_mime", "j_misprint", "j_mr_bones",
    "j_mystic_summit", "j_obelisk", "j_odd_todd", "j_onyx_agate", "j_oops", "j_order", "j_pareidolia", "j_perkeo",
    "j_photograph", "j_popcorn", "j_raised_fist", "j_ramen", "j_red_card", "j_reserved_parking", "j_ride_the_bus", "j_riff_raff",
    "j_ring_master", "j_rocket", "j_rough_gem", "j_runner", "j_satellite", "j_scary_face", "j_scholar", "j_seance",
    "j_seeing_double", "j_selzer", "j_shoot_the_moon", "j_shortcut", "j_sixth_sense", "j_sly", "j_smeared", "j_smiley",
    "j_sock_and_buskin", "j_space", "j_splash", "j_square", "j_steel_joker", "j_stencil", "j_stone", "j_stuntman",
    "j_supernova", "j_superposition", "j_swashbuckler", "j_throwback", "j_ticket", "j_to_the_moon", "j_todo_list", "j_trading",
    "j_tribe", "j_triboulet", "j_trio", "j_troubadour", "j_trousers", "j_turtle_bean", "j_vagabond", "j_vampire",
    "j_walkie_talkie", "j_wee", "j_wily", "j_wrathful_joker", "j_yorick", "j_zany",
})

_VANILLA_BOOSTER_VARIANT_COUNTS = {
    ("arcana", "normal"): 4, ("arcana", "jumbo"): 2, ("arcana", "mega"): 2,
    ("buffoon", "normal"): 2, ("buffoon", "jumbo"): 1, ("buffoon", "mega"): 1,
    ("celestial", "normal"): 4, ("celestial", "jumbo"): 2, ("celestial", "mega"): 2,
    ("spectral", "normal"): 2, ("spectral", "jumbo"): 1, ("spectral", "mega"): 1,
    ("standard", "normal"): 4, ("standard", "jumbo"): 2, ("standard", "mega"): 2,
}
_VANILLA_BOOSTER_ARTWORK_KEYS = frozenset(
    f"p_{kind}_{size}_{variant}"
    for (kind, size), count in _VANILLA_BOOSTER_VARIANT_COUNTS.items()
    for variant in range(1, count + 1)
)


def planet_hand(key: str) -> str | None:
    return _PLANET_HANDS.get(key)


def joker_rarity(key: str) -> int:
    """Return vanilla Joker rarity, or zero for an unknown key."""

    if key in _RARITY_2_KEYS:
        return 2
    if key in _RARITY_3_KEYS:
        return 3
    if key in _RARITY_4_KEYS:
        return 4
    return 1 if key in _KNOWN_JOKER_KEYS else 0


def semantic_card_key(kind: str, key: str) -> str:
    """Collapse numbered vanilla booster artwork variants with identical rules."""

    if kind.upper() == "BOOSTER" and key in _VANILLA_BOOSTER_ARTWORK_KEYS:
        return key.rpartition("_")[0]
    return key
