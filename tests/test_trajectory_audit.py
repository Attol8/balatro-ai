"""Offline mechanical parity against the saved Astra-low endless run."""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from pathlib import Path

from balatro_ai.game.actions import PlayCards, action_from_data
from balatro_ai.game.adapter import _fortune_teller_mult
from balatro_ai.game.codec import public_observation_from_data
from balatro_ai.game.scoring import score_play
from balatro_ai.game.state import HiddenJokerSlot, PublicItem, PublicJokerRuntime


EVIDENCE = Path(__file__).resolve().parents[1] / "evidence" / "astra-low-2K9H9HN"
def _legacy_fortune_runtime(observation):
    """Hydrate evidence recorded before the adapter admitted this public value."""

    jokers = []
    for joker in observation.jokers:
        if isinstance(joker, PublicItem) and joker.key == "j_fortune_teller":
            current_mult = _fortune_teller_mult({"effect": joker.effect_text})
            assert current_mult is not None
            joker = replace(
                joker,
                runtime=PublicJokerRuntime(current_mult=current_mult),
            )
        jokers.append(joker)
    return replace(observation, jokers=tuple(jokers))


def test_saved_endless_trace_has_exact_deterministic_score_parity() -> None:
    play_count = 0
    hidden: list[int] = []
    stochastic: list[tuple[int, float, int]] = []
    exact = 0
    final: tuple[int, float, int] | None = None
    transition_index = 0

    paths = sorted((EVIDENCE / "segments").glob("0[0-6]/trajectory.jsonl.gz"))
    assert len(paths) == 7
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["event"] != "transition":
                    continue
                transition_index += 1
                action = action_from_data(row["action"])
                if not isinstance(action, PlayCards):
                    continue
                play_count += 1
                before = public_observation_from_data(row["before"])
                if any(isinstance(joker, HiddenJokerSlot) for joker in before.jokers):
                    hidden.append(transition_index)
                    continue
                before = _legacy_fortune_runtime(before)
                predicted, _ = score_play(before, action.cards)
                actual = row["after"]["round"]["chips"] - row["before"]["round"]["chips"]
                # Balatro floors the completed hand score before adding it.
                if int(predicted) == actual:
                    exact += 1
                else:
                    stochastic.append((transition_index, float(predicted), actual))
                final = transition_index, int(predicted), actual

    assert play_count == 49
    assert hidden == [301, 302]  # Amber Acorn intentionally obscures Jokers.
    assert exact == 46
    assert stochastic == [(98, 14640.0, 32940)]  # Lucky Card RNG, retriggered.
    assert final == (383, 1239454, 1239454)
