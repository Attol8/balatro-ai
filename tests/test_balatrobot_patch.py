from pathlib import Path


def test_authority_patch_admits_only_vanilla_pack_inventory_sales() -> None:
    patch = (
        Path(__file__).resolve().parents[1]
        / "patches"
        / "balatrobot-authority-readiness.patch"
    ).read_text(encoding="utf-8")
    sell = patch.split(
        "diff --git a/src/lua/endpoints/sell.lua b/src/lua/endpoints/sell.lua",
        maxsplit=1,
    )[1]

    for state in (
        "TAROT_PACK",
        "PLANET_PACK",
        "SPECTRAL_PACK",
        "STANDARD_PACK",
        "BUFFOON_PACK",
    ):
        assert f"+    G.STATES.{state}," in sell
    assert "+    local initial_state = G.STATE" in sell
    assert "+    local initial_pack_area = G.pack_cards" in sell
    assert "+    local initial_pack_choices = G.GAME.pack_choices" in sell
    assert "+        local valid_state = G.STATE == initial_state" in sell
    assert "+          G.pack_cards == initial_pack_area" in sell
    assert "+          and G.GAME.pack_choices == initial_pack_choices" in sell
    assert "SMODS_BOOSTER_OPENED" not in sell
