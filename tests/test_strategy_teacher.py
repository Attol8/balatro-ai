from __future__ import annotations

from copy import deepcopy

import pytest

from balatro_ai_v2.actions import LeaveShop
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.strategy_engine import RunGoal
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTargetEndpoint,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
    read_teacher_records,
    teacher_record_from_data,
    teacher_record_to_data,
    write_teacher_records,
)
from state_factory import state


def _draft():
    observation = to_public_observation(state("SHOP"))
    return StrategyTeacherDraft(
        observation=observation,
        candidates=(
            StrategyTeacherCandidate(
                action=LeaveShop(),
                intent=None,
                samples=(StrategyRolloutTarget(1, 1, 0, 1, 2.5),),
            ),
        ),
        selected_index=0,
        baseline_index=0,
        goal=RunGoal.VICTORY,
        teacher_config_digest="1" * 64,
    )


def test_teacher_record_round_trips_without_seed_or_private_state(tmp_path) -> None:
    record = _draft().finalize(
        run_group="run-000000",
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=3,
        best_hand_score=12_345,
    )
    data = teacher_record_to_data(record)
    path = tmp_path / "teacher.jsonl"

    digest = write_teacher_records(path, (record,))

    assert read_teacher_records(path) == (record,)
    assert len(digest) == 64
    encoded = path.read_text(encoding="utf-8")
    assert "seed" not in encoded.casefold()
    assert "rng" not in encoded.casefold()
    assert "private" not in encoded.casefold()
    assert teacher_record_from_data(data) == record


def test_incomplete_run_cannot_finalize_teacher_record() -> None:
    with pytest.raises(ValueError, match="incomplete originating run"):
        _draft().finalize(
            run_group="run-000000",
            decision_index=0,
            run_complete=False,
            run_won=False,
            terminal_ante=0,
            best_hand_score=0,
        )


def test_teacher_reader_rejects_extra_or_unknown_fields() -> None:
    record = _draft().finalize(
        run_group="run-000000",
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=1,
        best_hand_score=100,
    )
    data = teacher_record_to_data(record)
    extra = deepcopy(data)
    extra["seed"] = "PRIVATE"
    bad_intent = deepcopy(data)
    bad_intent["candidates"][0]["intent"] = "future_strategy"

    with pytest.raises(ValueError, match="invalid fields"):
        teacher_record_from_data(extra)
    with pytest.raises(ValueError, match="intent is unsupported"):
        teacher_record_from_data(bad_intent)


def test_hidden_private_twins_produce_identical_teacher_data() -> None:
    left = state("SHOP", seed="PRIVATE-A")
    right = deepcopy(left)
    right["seed"] = "PRIVATE-B"
    right["cards"]["cards"].reverse()
    for card in right["cards"]["cards"]:
        card["id"] += 10_000

    left_record = StrategyTeacherDraft(
        to_public_observation(left),
        _draft().candidates,
        0,
        0,
        RunGoal.VICTORY,
        "1" * 64,
    ).finalize(
        run_group="run-000000",
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=2,
        best_hand_score=500,
    )
    right_record = StrategyTeacherDraft(
        to_public_observation(right),
        _draft().candidates,
        0,
        0,
        RunGoal.VICTORY,
        "1" * 64,
    ).finalize(
        run_group="run-000000",
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=2,
        best_hand_score=500,
    )

    assert teacher_record_to_data(left_record) == teacher_record_to_data(right_record)


def test_censored_target_cannot_masquerade_as_exact_long_horizon_label() -> None:
    with pytest.raises(ValueError, match="censored samples"):
        StrategyRolloutTarget(
            0,
            0,
            0,
            None,
            None,
            StrategyTargetEndpoint.CENSORED,
        )

    target = StrategyRolloutTarget(
        0,
        0,
        None,
        None,
        None,
        StrategyTargetEndpoint.CENSORED,
    )
    assert target.ante8_win is None
