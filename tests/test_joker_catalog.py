from __future__ import annotations

import pytest

from balatro_ai_v2.joker_catalog import JOKER_CATALOG, get_joker_profile


def test_catalog_is_the_complete_unique_base_joker_set() -> None:
    assert len(JOKER_CATALOG) == 150
    assert len(set(JOKER_CATALOG)) == 150
    assert all(key.startswith("j_") for key in JOKER_CATALOG)
    assert all(profile.key == key for key, profile in JOKER_CATALOG.items())


def test_every_primary_role_is_represented() -> None:
    assert {profile.primary_role for profile in JOKER_CATALOG.values()} == {
        "x_mult",
        "scaling",
        "retrigger",
        "flat_mult",
        "chips",
        "economy",
        "utility",
    }


def test_catalog_has_source_audited_rarity_partition() -> None:
    counts = {
        rarity: sum(profile.rarity == rarity for profile in JOKER_CATALOG.values())
        for rarity in (1, 2, 3, 4)
    }

    assert counts == {1: 61, 2: 64, 3: 20, 4: 5}
    assert get_joker_profile("j_luchador").rarity == 2
    assert get_joker_profile("j_baseball").rarity == 3
    assert get_joker_profile("j_triboulet").rarity == 4


@pytest.mark.parametrize(
    ("key", "role", "tags", "order_sensitive", "score_effect"),
    [
        ("j_blueprint", "utility", {"joker_heavy"}, True, True),
        ("j_brainstorm", "utility", {"joker_heavy"}, True, True),
        ("j_baron", "x_mult", {"held_cards", "kings"}, True, True),
        ("j_mime", "retrigger", {"held_cards"}, True, True),
        ("j_runner", "scaling", {"straight"}, False, True),
        ("j_trousers", "scaling", {"two_pair", "full_house"}, False, True),
        ("j_credit_card", "economy", set(), False, False),
        ("j_invisible", "utility", set(), False, False),
    ],
)
def test_representative_difficult_classifications(
    key: str,
    role: str,
    tags: set[str],
    order_sensitive: bool,
    score_effect: bool,
) -> None:
    profile = get_joker_profile(key)
    assert profile.primary_role == role
    assert profile.archetypes == tags
    assert profile.order_sensitive is order_sensitive
    assert profile.score_effect is score_effect


def test_unknown_lookup_fails_closed() -> None:
    with pytest.raises(KeyError, match="unknown base Joker key"):
        get_joker_profile("j_future_modded_joker")
