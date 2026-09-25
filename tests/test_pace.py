from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from balatro_ai.game.codec import public_observation_from_data
from balatro_ai.game.state import Phase, PublicItem, VisiblePlayingCard
from balatro_ai.pace import build_pace, hand_tarot_values

FIXTURES = Path(__file__).parent / "fixtures" / "pace"


def _recorded(name: str):
    return public_observation_from_data(
        json.loads((FIXTURES / f"{name}.json").read_text())["observation"]
    )


def _without_seconds(pace: dict) -> dict:
    return {key: value for key, value in pace.items() if key != "seconds"}


def test_recorded_ante5_builds_are_reported_short_before_they_lost() -> None:
    """JBG00001 scored 18,095 of 37,500 at the Big Blind; JBG00002 41,749 of 50,000."""

    first = build_pace(_recorded("jbg00001_ante5_big_shop"))
    big = next(row for row in first["blinds"] if row["blind"] == "Big Blind")
    assert big["per_hand_median"] < big["needed_per_hand"] and big["clear_chance"] < 0.1

    second = build_pace(_recorded("jbg00002_wheel_shop"))
    wheel = second["blinds"][0]
    assert wheel["blind"] == "The Wheel" and wheel["hands"] == 3
    assert wheel["per_hand_median"] < wheel["needed_per_hand"] and wheel["clear_chance"] < 0.1


def test_a_zero_score_eternal_shows_as_a_slot_that_adds_nothing() -> None:
    pace = build_pace(_recorded("jbg00002_wheel_shop"))
    chaos = next(row for row in pace["jokers"] if row["key"] == "j_chaos")
    assert chaos == {"slot": 2, "key": "j_chaos", "share_of_score": 0.0, "eternal": True}
    assert all(row["share_of_score"] > 0 for row in pace["jokers"] if row["key"] != "j_chaos")


def test_full_slots_price_a_joker_offer_as_a_swap_for_the_weakest_sellable_joker() -> None:
    """The Polychrome Delayed Gratification could only replace Ramen, and that loses score."""

    pace = build_pace(_recorded("jbg00002_wheel_shop"))
    offer = next(row for row in pace["offers"] if row["key"] == "j_delayed_grat")
    assert offer["replaces"] == "j_ramen" and offer["no_direct_score"] is True
    assert offer["per_hand_change"] < 0


def test_a_held_planet_for_the_played_hand_raises_the_boss_clear_chance() -> None:
    pace = build_pace(_recorded("jbg00002_wheel_shop"))
    mercury = next(row for row in pace["offers"] if row["zone"] == "consumables")
    assert mercury["key"] == "c_mercury" and mercury["per_hand_change"] > 0.05
    before, after = mercury["boss_clear_chance"]
    assert after >= before


def test_an_extra_hand_changes_the_clear_chance_not_the_per_hand_score() -> None:
    observation = _recorded("jbg00002_wheel_shop")
    grabber = PublicItem("v_grabber", "Grabber", "VOUCHER", buy_cost=10)
    pace = build_pace(replace(observation, vouchers=(grabber,)))
    row = next(row for row in pace["offers"] if row["key"] == "v_grabber")
    assert row["per_hand_change"] == 0
    assert row["boss_clear_chance"][1] > row["boss_clear_chance"][0]


def test_forecast_is_deterministic_and_bounded_in_time() -> None:
    observation = _recorded("jbg00001_ante5_big_shop")
    first, second = build_pace(observation), build_pace(observation)
    assert _without_seconds(first) == _without_seconds(second)
    assert first["seconds"] < 2.5


def test_a_shop_tarot_names_deck_targets_and_its_change() -> None:
    observation = _recorded("jbg00002_wheel_shop")
    justice = PublicItem("c_justice", "Justice", "TAROT", buy_cost=3)
    pace = build_pace(replace(observation, shop=(justice,)))
    row = pace["tarots"][0]
    assert row["key"] == "c_justice" and len(row["targets"]) == 1
    assert row["per_hand_change"] > 0


def test_a_pack_tarot_is_limited_to_the_visible_hand() -> None:
    observation = _recorded("jbg00002_arcana_pack")
    hand = tuple(entry.card for entry in observation.full_deck[:8])
    pace = build_pace(replace(observation, hand=hand))
    rows = [row for row in pace.get("tarots", []) if row["zone"] == "opened_pack"]
    assert rows, "the pack's targeted Tarots are valued once a hand is visible"
    for row in rows:
        assert set(row.get("hand_slots", [])) <= set(range(8))


def test_held_tarot_targets_are_scored_on_the_visible_hand() -> None:
    observation = _recorded("jbg00002_wheel_shop")
    hand = (
        VisiblePlayingCard("A", "S"),
        VisiblePlayingCard("A", "H"),
        VisiblePlayingCard("7", "D"),
        VisiblePlayingCard("4", "C"),
        VisiblePlayingCard("9", "C"),
    )
    blinds = tuple(
        replace(blind, status="CURRENT") if blind.kind == "BOSS" else blind
        for blind in observation.blinds
    )
    selecting = replace(
        observation,
        phase=Phase.SELECTING_HAND,
        hand=hand,
        shop=(),
        vouchers=(),
        packs=(),
        blinds=tuple(
            replace(b, name="Big Blind", kind="BIG") if b.kind == "BOSS" else b for b in blinds
        ),
        consumables=(PublicItem("c_justice", "Justice", "TAROT"),),
    )
    rows = hand_tarot_values(selecting)
    assert rows and rows[0]["key"] == "c_justice"
    assert rows[0]["best_play_after"] > rows[0]["best_play_now"]
    assert set(rows[0]["best_targets"]) <= {0, 1}


def test_ante_targets_follow_the_vanilla_table_into_endless() -> None:
    from balatro_ai.pace import ante_base

    assert [ante_base(ante, "WHITE") for ante in (1, 8, 9, 10, 13)] == [
        300,
        50000,
        110000,
        560000,
        47_000_000_000,
    ]
    assert [ante_base(ante, "GOLD") for ante in (5, 6, 8)] == [25000, 60000, 200000]
    assert ante_base(20, "WHITE") > 10**43
    assert ante_base(200, "WHITE") is None


def test_next_ante_prices_the_build_without_jokers_that_expire_first() -> None:
    observation = _recorded("jbg00001_ante5_big_shop")
    expiring = next(j for j in observation.jokers if j.perishable_rounds is not None)
    horizon = build_pace(observation)["next_ante"]
    assert horizon["ante"] == 6 and horizon["typical_boss_target"] == 120000
    assert expiring.key in horizon["expiring_before_boss"]
    assert horizon["growth_needed"] > 1
    ante8 = build_pace(replace(observation, ante=8))
    assert "next_ante" not in ante8


def test_joker_rows_name_editions_and_deja_vu_is_valued_as_a_red_seal() -> None:
    observation = _recorded("jbg00002_wheel_shop")
    deja_vu = PublicItem("c_deja_vu", "Deja Vu", "SPECTRAL", buy_cost=4)
    pace = build_pace(replace(observation, shop=(deja_vu,)))
    row = pace["tarots"][0]
    assert row["key"] == "c_deja_vu" and row["per_hand_change"] > 0
    assert all(
        ("edition" in j) == bool(o.edition) for j, o in zip(pace["jokers"], observation.jokers)
    )


def test_held_tarot_values_keep_cerulean_bells_forced_card() -> None:
    """A recorded 2W7A4ADG endless run crashed at an Ante 8 Cerulean Bell while a Tarot was held."""

    observation = _recorded("jbg00002_wheel_shop")
    hand = (
        VisiblePlayingCard("A", "S"),
        VisiblePlayingCard("A", "H"),
        VisiblePlayingCard("7", "D"),
        VisiblePlayingCard("4", "C"),
    )
    blinds = tuple(
        replace(blind, status="CURRENT", name="Cerulean Bell")
        if blind.kind == "BOSS"
        else replace(blind, status="DEFEATED")
        for blind in observation.blinds
    )
    selecting = replace(
        observation,
        phase=Phase.SELECTING_HAND,
        hand=hand,
        shop=(),
        vouchers=(),
        packs=(),
        blinds=blinds,
        required_hand_slots=(3,),
        consumables=(PublicItem("c_justice", "Justice", "TAROT"),),
    )
    rows = hand_tarot_values(selecting)
    assert rows and rows[0]["best_play_after"] >= rows[0]["best_play_now"] > 0
    assert 3 in rows[0]["best_targets"], "targets must include the forced card"


def test_a_build_short_of_this_antes_boss_does_not_hold_through_it() -> None:
    horizon = build_pace(_recorded("jbg00002_wheel_shop")).get("next_ante")
    wheel = build_pace(_recorded("jbg00002_wheel_shop"))["blinds"][0]
    assert wheel["clear_chance"] < 0.5
    assert horizon["build_holds_through_ante"] == 4


def _shop_offer(pace: dict, key: str) -> dict:
    return next(row for row in pace["offers"] if row["zone"] == "shop" and row["key"] == key)


def test_engine_potential_shows_what_todays_value_hides() -> None:
    """2W7A4ADG offered Baron (Ante 4) and Mime (Ante 5); both read negative today."""

    baron = _shop_offer(build_pace(_recorded("2w7a4adg_ante4_baron_shop")), "j_baron")
    assert baron["per_hand_change"] < 0
    potential = baron["engine_potential"]
    assert potential["fuel"].startswith("Chariot (Steel) on Kings")
    fed = potential["after_24_edits"]
    assert fed["with_j_mime"] > fed["build"] + 1 and fed["with_it"] > fed["build"]
    mime = _shop_offer(build_pace(_recorded("2w7a4adg_ante5_mime_shop")), "j_mime")
    grows = mime["engine_potential"]
    assert mime["per_hand_change"] < 0
    assert grows["after_24_edits"]["with_it"] > grows["today"]["with_it"]
    assert grows["after_24_edits"]["with_j_baron"] >= grows["after_24_edits"]["with_it"]


def test_a_copier_offer_is_placed_where_it_copies_something() -> None:
    blueprint = _shop_offer(build_pace(_recorded("2w7a4adg_ante4_blueprint_shop")), "j_blueprint")
    assert blueprint["position"] < 5 and blueprint["per_hand_change"] > 0.2


def test_played_card_engines_find_their_feed_from_the_scorer_rules() -> None:
    observation = _recorded("2w7a4adg_ante4_blueprint_shop")
    offers = (
        PublicItem("j_photograph", "Photograph", "JOKER", buy_cost=5),
        PublicItem("j_hack", "Hack", "JOKER", buy_cost=6),
    )
    pace = build_pace(replace(observation, shop=offers))
    assert _shop_offer(pace, "j_photograph")["engine_potential"]["fuel"] == (
        "Justice (Glass) on face cards"
    )
    assert "Justice (Glass)" in _shop_offer(pace, "j_hack")["engine_potential"]["fuel"]
    assert pace["seconds"] < 3.5
