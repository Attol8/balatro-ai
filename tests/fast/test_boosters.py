from balatro_ai_v2.fast.boosters import BOOSTER_SPECS, BoosterKind, booster_spec


def test_all_source_boosters_have_specs() -> None:
    assert len(BOOSTER_SPECS) == 32
    assert booster_spec("p_arcana_normal_1").kind == BoosterKind.ARCANA
    assert booster_spec("p_celestial_mega_2").choices == 2
    assert booster_spec("p_spectral_normal_1").size == 2
    assert booster_spec("p_standard_jumbo_2").cost == 6
    assert booster_spec("p_buffoon_mega_1").weight == 0.15


def test_booster_orders_match_source() -> None:
    assert booster_spec("p_arcana_normal_1").order == 1
    assert booster_spec("p_celestial_normal_1").order == 9
    assert booster_spec("p_standard_normal_1").order == 17
    assert booster_spec("p_buffoon_normal_1").order == 25
    assert booster_spec("p_spectral_normal_1").order == 29
