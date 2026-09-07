"""Library integrity and retrieval against public recorded decisions."""

import gzip
import json
from dataclasses import replace
from pathlib import Path

from balatro_ai.analysis import analyze
from balatro_ai.game.codec import public_observation_from_data
from balatro_ai.game.state import HiddenJokerSlot, Phase, PublicBlind
from balatro_ai.strategy import load_examples, retrieve_examples

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence/astra-low-2K9H9HN/segments"


def recorded(segment, index):
    with gzip.open(EVIDENCE / segment / "trajectory.jsonl.gz", "rt") as stream:
        return json.loads(list(stream)[index])


def test_library_has_reviewable_unique_sourced_examples():
    examples = load_examples()
    assert 30 <= len(examples) <= 50
    assert len({row["id"] for row in examples}) == len(examples)
    assert len({row["lesson"] for row in examples}) == len(examples)
    assert len({row["family"] for row in examples}) >= 16
    for row in examples:
        assert set(row) == {
            "id",
            "family",
            "trigger_keys",
            "required_keys",
            "phases",
            "situation",
            "options",
            "lesson",
            "reversal",
            "provenance",
            "sources",
        }
        assert row["provenance"] in {"constructed", "recorded"}
        assert row["trigger_keys"] and row["sources"]
        for token in row["trigger_keys"] + row["required_keys"]:
            assert token.startswith(
                ("j_", "c_", "v_", "enhancement:", "seal:", "rank:", "suit:", "kind:", "boss:")
            )
        assert len(row["options"]) == 2
        assert set(row["phases"]) <= {"SHOP", "PACK", "SELECTING_HAND", "BLIND_SELECT"}
        for key in ("situation", "lesson", "reversal"):
            assert 0 < len(row[key]) <= 230
        for source in row["sources"]:
            if source.startswith("evidence:"):
                _, segment, index = source.split(":")
                event = recorded(segment, int(index))
                assert "observation" in event or "before" in event
            else:
                assert source.startswith(("game:card.lua:", "game:game.lua:", "https://"))


def test_recorded_mime_offer_retrieves_bounded_conditional_lessons():
    obs = public_observation_from_data(recorded("05", 95)["observation"])
    examples = retrieve_examples(obs)
    assert 1 <= len(examples) <= 3
    assert any("Mime" in row["lesson"] or "Mime" in row["situation"] for row in examples)
    assert analyze(obs)["strategy_examples"] == examples
    assert len(json.dumps(examples).encode()) <= 2600
    wire = json.dumps(examples)
    assert "2K9H9HN" not in wire and "evidence:" not in wire
    assert "sources" not in wire and "trigger_keys" not in wire


def test_hidden_and_unrelated_state_does_not_retrieve_build_lessons():
    obs = public_observation_from_data(recorded("05", 95)["observation"])
    obs = replace(
        obs,
        phase=Phase.SELECTING_HAND,
        blinds=(
            PublicBlind(
                kind="BOSS",
                status="CURRENT",
                name="Amber Acorn",
                effect="",
                score=1,
                disabled=False,
            ),
        ),
        jokers=(HiddenJokerSlot(),),
        consumables=(),
        shop=(),
        opened_pack=(),
        hand=(),
        full_deck=(),
        deck_size=0,
        vouchers=(),
        used_vouchers=(),
    )
    assert retrieve_examples(obs) == []


def test_no_lessons_at_game_over():
    from balatro_ai.game.state import Phase

    obs = public_observation_from_data(recorded("05", 95)["observation"])
    assert retrieve_examples(replace(obs, phase=Phase.GAME_OVER)) == []


def test_broad_unseen_engines_retrieve_without_recorded_inventory():
    from balatro_ai.game.adapter import to_public_observation
    from balatro_ai.game.state import Phase, PublicItem
    from tests.game.state_factory import state

    base = to_public_observation(state("SHOP"))
    for key, name in (
        ("j_shortcut", "Shortcut"),
        ("j_smeared", "Smeared"),
        ("j_bloodstone", "Bloodstone"),
        ("j_triboulet", "Triboulet"),
        ("j_yorick", "Yorick"),
        ("j_perkeo", "Perkeo"),
        ("j_obelisk", "Obelisk"),
        ("j_madness", "Madness"),
        ("j_wee", "Wee"),
        ("j_dna", "DNA"),
    ):
        obs = replace(
            base, jokers=(), shop=(PublicItem(key, key, "JOKER"),), consumables=(), opened_pack=()
        )
        if key == "j_yorick":
            obs = replace(obs, phase=Phase.SELECTING_HAND, jokers=obs.shop, shop=())
        examples = retrieve_examples(obs)
        assert any(name in row["lesson"] for row in examples), key
        assert all(row["situation"].startswith("Example: ") for row in examples)
        assert len(json.dumps(examples).encode()) <= 2600


def test_observatory_can_match_owned_voucher_without_joker():
    from balatro_ai.game.adapter import to_public_observation
    from balatro_ai.game.state import PublicItem
    from tests.game.state_factory import state

    obs = to_public_observation(state("SHOP"))
    obs = replace(
        obs,
        jokers=(),
        shop=(),
        used_vouchers=("v_observatory",),
        consumables=(PublicItem("c_pluto", "Pluto", "PLANET"),),
    )
    assert any("Observatory" in row["lesson"] for row in retrieve_examples(obs))
