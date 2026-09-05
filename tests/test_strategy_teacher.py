from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from balatro_ai_v2.actions import LeaveShop, RerollShop
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.strategy_context import PublicStrategyContext
from balatro_ai_v2.strategy_engine import RunGoal, RunRoute
from balatro_ai_v2.strategy_options import StrategyIntent
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
                route=None,
                samples=(StrategyRolloutTarget(1, 1, 0, 1, 2.5),),
            ),
            StrategyTeacherCandidate(
                action=LeaveShop(),
                intent=StrategyIntent.STABILIZE,
                route=RunRoute.HELD_RETRIGGER,
                samples=(StrategyRolloutTarget(1, 1, 0, 1, 2.5),),
            ),
        ),
        selected_index=1,
        baseline_index=0,
        ordinary_index=0,
        behavior_index=1,
        goal=RunGoal.VICTORY,
        teacher_config_digest="1" * 64,
        context=PublicStrategyContext(
            incoming_intent=StrategyIntent.STABILIZE,
            incoming_route=RunRoute.HELD_RETRIGGER,
        ),
    )


def test_teacher_record_round_trips_without_seed_or_private_state(tmp_path) -> None:
    record = _draft().finalize(
        run_group="origin-00000000000000000000000000000000",
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
    assert data["schema_version"] == 11
    assert data["ordinary_index"] == record.baseline_index
    assert data["behavior_index"] == record.selected_index
    assert teacher_record_from_data(data) == record


def test_incomplete_run_cannot_finalize_teacher_record() -> None:
    with pytest.raises(ValueError, match="incomplete originating run"):
        _draft().finalize(
            run_group="origin-00000000000000000000000000000000",
            decision_index=0,
            run_complete=False,
            run_won=False,
            terminal_ante=0,
            best_hand_score=0,
        )


def test_teacher_reader_rejects_extra_or_unknown_fields() -> None:
    record = _draft().finalize(
        run_group="origin-00000000000000000000000000000000",
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
    missing_ordinary = deepcopy(data)
    missing_ordinary.pop("ordinary_index")
    old_schema = deepcopy(data)
    old_schema["schema_version"] = 10

    with pytest.raises(ValueError, match="invalid fields"):
        teacher_record_from_data(extra)
    with pytest.raises(ValueError, match="intent is unsupported"):
        teacher_record_from_data(bad_intent)
    with pytest.raises(ValueError, match="invalid fields"):
        teacher_record_from_data(missing_ordinary)
    with pytest.raises(ValueError, match="schema version is unsupported"):
        teacher_record_from_data(old_schema)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ordinary_index", True, "must be an integer"),
        ("behavior_index", 2, "record is invalid"),
    ],
)
def test_teacher_reader_rejects_invalid_route_identity_indexes(
    field: str,
    value: object,
    message: str,
) -> None:
    record = _draft().finalize(
        run_group="origin-00000000000000000000000000000000",
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=1,
        best_hand_score=100,
    )
    data = teacher_record_to_data(record)
    data[field] = value

    with pytest.raises(ValueError, match=message):
        teacher_record_from_data(data)


def test_teacher_requires_baseline_to_equal_ordinary_comparator() -> None:
    observation = to_public_observation(state("SHOP", money=10))
    samples = (StrategyRolloutTarget(1, 1, 0, 1, 2.5),)

    with pytest.raises(ValueError, match="baseline must be the ordinary"):
        StrategyTeacherDraft(
            observation=observation,
            candidates=(
                StrategyTeacherCandidate(LeaveShop(), None, samples),
                StrategyTeacherCandidate(RerollShop(), None, samples),
            ),
            selected_index=1,
            baseline_index=0,
            ordinary_index=1,
            behavior_index=1,
            goal=RunGoal.VICTORY,
            teacher_config_digest="1" * 64,
        )


def test_hidden_private_twins_produce_identical_teacher_data() -> None:
    left = state("SHOP", seed="PRIVATE-A")
    right = deepcopy(left)
    right["seed"] = "PRIVATE-B"
    right["cards"]["cards"].reverse()
    for card in right["cards"]["cards"]:
        card["id"] += 10_000

    left_record = StrategyTeacherDraft(
        observation=to_public_observation(left),
        candidates=_draft().candidates,
        selected_index=1,
        baseline_index=0,
        ordinary_index=0,
        behavior_index=1,
        goal=RunGoal.VICTORY,
        teacher_config_digest="1" * 64,
    ).finalize(
        run_group="origin-00000000000000000000000000000000",
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=2,
        best_hand_score=500,
    )
    right_record = StrategyTeacherDraft(
        observation=to_public_observation(right),
        candidates=_draft().candidates,
        selected_index=1,
        baseline_index=0,
        ordinary_index=0,
        behavior_index=1,
        goal=RunGoal.VICTORY,
        teacher_config_digest="1" * 64,
    ).finalize(
        run_group="origin-00000000000000000000000000000000",
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


def test_reader_rejects_inconsistent_outcomes_within_origin(tmp_path) -> None:
    first = _draft().finalize(
        run_group="origin-00000000000000000000000000000000",
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=3,
        best_hand_score=100,
    )
    second = replace(first, decision_index=1, terminal_ante=4)
    path = tmp_path / "teacher.jsonl"
    write_teacher_records(path, (first, second))

    with pytest.raises(ValueError, match="inconsistent run outcome"):
        read_teacher_records(path)
