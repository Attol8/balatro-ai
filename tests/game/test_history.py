import gzip
import json
from dataclasses import replace
from pathlib import Path

import pytest
from state_factory import state

from balatro_ai.analysis import analyze
from balatro_ai.game.actions import (
    BuyShopCard,
    HandSlot,
    PlayCards,
    ShopSlot,
    canonical_action_from_data,
)
from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.codec import public_observation_from_data, public_observation_to_data
from balatro_ai.game.history import HistoryStep, enrich_runtime
from balatro_ai.game.scoring import MouthFamilyUnavailable, score_play
from balatro_ai.game.state import PublicItem, PublicJokerRuntime


def _mouth_archive():
    path = (
        Path(__file__).parents[2]
        / "evidence/terra-low-QD3F4XVW-attempt1/segments/01/trajectory.jsonl.gz"
    )
    steps = []
    with gzip.open(path, "rt") as source:
        for line_number, line in enumerate(source, 1):
            row = json.loads(line)
            if line_number == 68:
                return public_observation_from_data(row["before"]), tuple(steps)
            if row.get("event") == "transition":
                steps.append(
                    HistoryStep(
                        public_observation_from_data(row["before"]),
                        canonical_action_from_data(row["action"]),
                        public_observation_from_data(row["after"]),
                    )
                )
    raise AssertionError("missing archived Mouth state")


def test_mouth_failed_other_families_do_not_erase_first_family():
    observation, history = _mouth_archive()
    enriched = enrich_runtime(observation, history)
    assert enriched.round.mouth_hand_family == "Two Pair"
    assert {h.name for h in observation.hand_stats if h.played_this_round} == {
        "Two Pair",
        "High Card",
    }
    first = next(
        s
        for s in history
        if s.before.round_no == observation.round_no and isinstance(s.action, PlayCards)
    )
    # Reuse the actual first hand after later failed High Cards: it still scores
    # the 496 chips observed live, rather than every family becoming suppressed.
    replay = replace(enriched, hand=first.before.hand)
    assert score_play(replay, first.action.cards)[0] == first.after.round.chips == 496
    assert score_play(replay, (HandSlot(0),))[0] == 0
    assert public_observation_from_data(public_observation_to_data(enriched)) == enriched


def test_mouth_ambiguous_legacy_snapshot_reports_unavailable_without_crashing_analysis():
    observation, _ = _mouth_archive()
    with pytest.raises(MouthFamilyUnavailable):
        score_play(observation, (HandSlot(0),))
    result = analyze(observation)
    assert result["play_candidates"] == []
    assert "first hand family is unavailable" in result["numerical_play_status"]


def test_mouth_first_family_cannot_leak_between_rounds():
    observation, history = _mouth_archive()
    later = replace(observation, round_no=observation.round_no + 1)
    assert enrich_runtime(later, history).round.mouth_hand_family is None


def test_mouth_rejects_missing_or_disconnected_history():
    observation, history = _mouth_archive()
    assert enrich_runtime(observation, ()).round.mouth_hand_family is None
    assert enrich_runtime(observation, history[:-1]).round.mouth_hand_family is None
    broken = (*history[:-1], replace(history[-1], before=replace(history[-1].before, money=999)))
    assert enrich_runtime(observation, broken).round.mouth_hand_family is None


def _history(plays: int):
    loyalty = PublicItem(
        "j_loyalty_card",
        "Loyalty Card",
        "JOKER",
        runtime=PublicJokerRuntime(loyalty_remaining=5),
    )
    owned = replace(to_public_observation(state("SELECTING_HAND")), jokers=(loyalty,))
    empty = replace(owned, jokers=())
    steps = [HistoryStep(empty, BuyShopCard(ShopSlot(0)), owned)]
    steps.extend(HistoryStep(owned, PlayCards((HandSlot(0),)), owned) for _ in range(plays))
    return owned, tuple(steps)


@pytest.mark.parametrize("plays", range(6))
def test_loyalty_countdown_from_contiguous_public_history(plays: int) -> None:
    observation, history = _history(plays)
    enriched = enrich_runtime(observation, history)
    assert enriched.jokers[0].runtime.loyalty_remaining == (5 - plays) % 6


def test_loyalty_runtime_fails_closed_without_provenance() -> None:
    observation, _ = _history(0)
    stale = replace(
        observation,
        jokers=(replace(observation.jokers[0], runtime=PublicJokerRuntime(loyalty_remaining=0)),),
    )
    assert enrich_runtime(stale, ()).jokers[0].runtime.loyalty_remaining is None


def test_loyalty_sixth_play_scores_x4() -> None:
    observation, history = _history(5)
    selected = (HandSlot(0),)
    scored, _ = score_play(enrich_runtime(observation, history), selected)
    without, _ = score_play(replace(observation, jokers=()), selected)
    assert scored == 4 * without
