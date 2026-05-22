from pathlib import Path

from balatro_ai_v2.rules.catalog import load_rule_catalog


def test_load_rule_catalog_from_lua_dump_sample(tmp_path: Path) -> None:
    dump = tmp_path / "dump"
    dump.mkdir()
    (dump / "game.lua").write_text(
        """
        j_joker = {name = "Joker"},
        c_fool = {name = "The Fool"},
        v_blank = {name = "Blank"},
        m_mult = {name = "Mult Card"},
        e_foil = {name = "Foil"},
        p_buffoon_normal_1 = {name = "Buffoon Pack"},
        b_red = {name = "Red Deck"},
        bl_small = {name = "Small Blind"},
        tag_uncommon = {name = "Uncommon Tag"},
        stake_white = {name = "White Stake"},
        """,
        encoding="utf-8",
    )

    catalog = load_rule_catalog(dump)

    assert catalog.jokers == ("j_joker",)
    assert catalog.consumables == ("c_fool",)
    assert catalog.vouchers == ("v_blank",)
    assert catalog.enhancements == ("m_mult",)
    assert catalog.editions == ("e_foil",)
    assert catalog.boosters == ("p_buffoon_normal_1",)
    assert catalog.decks == ("b_red",)
    assert catalog.blinds == ("bl_small",)
    assert catalog.tags == ("tag_uncommon",)
    assert catalog.stakes == ("stake_white",)

