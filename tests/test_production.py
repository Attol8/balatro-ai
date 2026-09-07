from dataclasses import replace

from balatro_ai.analysis import analyze
from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.state import HandStat, PublicBlind, PublicItem, VisiblePlayingCard
from balatro_ai.production import copier_timing
from tests.game.state_factory import state


def observation(phase="SELECTING_HAND"):
    return to_public_observation(state(phase))


def joker(key):
    return PublicItem(key, key, "JOKER")


def test_production_distinguishes_finish_from_setup_and_last_hand():
    obs = replace(
        observation(),
        hand=(VisiblePlayingCard("K", "H"), VisiblePlayingCard("2", "D", seal="PURPLE")),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        blinds=(PublicBlind("SMALL", "CURRENT", "Small Blind", "", 10, False),),
    )
    obs = replace(obs, round=replace(obs.round, chips=0, hands_left=3, discards_left=2))
    advice = analyze(obs)["round_production"]
    assert advice["score_remaining"] == 10
    assert advice["estimated_finish_now"]
    assert advice["setup_status"] == "finish_available_setup_unverified"
    assert advice["purple_discard_options"][0]["action"]["cards"] == [1]
    last = replace(obs, round=replace(obs.round, hands_left=1))
    assert analyze(last)["round_production"]["setup_status"] == "last_hand_preserve_finish"
    hard = replace(obs, blinds=(replace(obs.blinds[0], score=100000),))
    assert analyze(hard)["round_production"]["estimated_finish_now"] is None
    assert (
        analyze(hard)["round_production"]["setup_status"]
        == "no_estimated_finish_prioritize_survival"
    )


def test_purple_requires_capacity_and_legal_discard():
    obs = replace(observation(), hand=(VisiblePlayingCard("2", "D", seal="PURPLE"),))
    obs = replace(obs, round=replace(obs.round, discards_left=1))
    assert analyze(obs)["round_production"]["purple_discard_options"]
    assert not analyze(replace(obs, consumable_limit=0))["round_production"][
        "purple_discard_options"
    ]
    assert not analyze(replace(obs, round=replace(obs.round, discards_left=0)))["round_production"][
        "purple_discard_options"
    ]
    debuffed = replace(obs, hand=(replace(obs.hand[0], debuffed=True),))
    assert not analyze(debuffed)["round_production"]["purple_discard_options"]


def test_dna_singleton_survives_stronger_high_card_with_splash():
    obs = replace(
        observation(),
        hand=(VisiblePlayingCard("K", "H"), VisiblePlayingCard("2", "D")),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(joker("j_dna"), joker("j_splash")),
    )
    obs = replace(obs, round=replace(obs.round, hands_played=0))
    plays = analyze(obs)["play_candidates"]
    assert any(len(play["action"]["cards"]) == 1 for play in plays)
    assert any(len(play["action"]["cards"]) == 2 for play in plays)


def test_copier_steps_converge_for_every_position_without_nonadjacent_moves():
    from itertools import permutations

    for copier in ("j_blueprint", "j_brainstorm"):
        for keys in permutations((copier, "j_joker", "j_mime", "j_greedy_joker")):
            obs = replace(observation(), jokers=tuple(joker(key) for key in keys))
            for _ in range(8):
                rows = copier_timing(obs)
                assert len(rows) == 1
                row = rows[0]
                action = row["next_reorder"]
                if action is None:
                    index = row["copier_slot"]
                    target = index + 1 if copier == "j_blueprint" else 0
                    assert obs.jokers[target].key == "j_mime"
                    break
                order = action["order"]
                changed = [i for i, value in enumerate(order) if i != value]
                assert len(changed) == 2 and changed[1] - changed[0] == 1
                obs = replace(obs, jokers=tuple(obs.jokers[i] for i in order))
            else:
                raise AssertionError("copier advice did not converge")


def test_event_timing_excludes_spent_dna_empty_perkeo_and_cashout():
    obs = replace(observation(), jokers=(joker("j_blueprint"), joker("j_dna")))
    obs = replace(obs, round=replace(obs.round, hands_played=0))
    assert copier_timing(obs)
    assert not copier_timing(replace(obs, round=replace(obs.round, hands_played=1)))
    shop = replace(
        observation("SHOP"), jokers=(joker("j_blueprint"), joker("j_perkeo")), consumables=()
    )
    assert not copier_timing(shop)
    shop = replace(shop, consumables=(PublicItem("c_pluto", "Pluto", "PLANET"),))
    assert copier_timing(shop)[0]["target_key"] == "j_perkeo"
    assert not copier_timing(
        replace(shop, jokers=(replace(shop.jokers[0], debuffed=True), shop.jokers[1]))
    )
    cashout = replace(observation("ROUND_EVAL"), jokers=(joker("j_blueprint"), joker("j_mime")))
    assert not copier_timing(cashout)
