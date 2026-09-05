from __future__ import annotations

from dataclasses import replace

import pytest
import torch

from balatro_ai_v2.actions import LeaveShop, iter_legal_actions
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.route_learning import (
    RouteLearningDataError,
    reconstruct_route_split,
    route_pair_coverage,
    route_paired_examples,
    route_training_loss,
)
from balatro_ai_v2.strategy_engine import RunGoal, RunRoute
from balatro_ai_v2.strategy_model import RelationalStrategyPolicyValue
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
)
from state_factory import state


def _record(seed: int, *, null_ante8: bool = False):
    observation = to_public_observation(state("SHOP", money=10))
    actions = tuple(iter_legal_actions(observation))
    first = actions.index(LeaveShop())
    second = next(index for index, action in enumerate(actions) if index != first)

    def samples(utility: float, route: bool = False):
        return tuple(
            StrategyRolloutTarget(
                1,
                1,
                None if null_ante8 and route else 1,
                2,
                2,
                search_utility=utility,
            )
            for _ in range(2)
        )

    candidates = [
        StrategyTeacherCandidate(actions[first], None, samples(1)),
        StrategyTeacherCandidate(actions[second], None, samples(1)),
        StrategyTeacherCandidate(
            actions[first], None, samples(2, route=True), RunRoute.PLAYED_RETRIGGER
        ),
    ]
    return StrategyTeacherDraft(
        observation=observation,
        candidates=tuple(candidates),
        selected_index=2,
        baseline_index=1,
        ordinary_index=1,
        behavior_index=2,
        goal=RunGoal.VICTORY,
        teacher_config_digest="a" * 64,
        candidate_space_size=3,
    ).finalize(
        run_group=f"origin-{seed:032x}",
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=4,
        best_hand_score=100,
    )


def test_route_pair_uses_same_action_comparator_not_global_ordinary():
    record = _record(1)
    example = route_paired_examples((record,))[0]
    assert record.ordinary_index == 1
    assert example.ordinary_index == 0
    assert example.specialist_index == 2
    assert example.targets.scalar == (1.0, 1.0)


def test_victory_route_is_never_a_specialist_and_null_masks_are_head_local():
    record = _record(1, null_ante8=True)
    example = route_paired_examples((record,))[0]
    assert example.targets.masks["ante8_win"] == (False, False)
    assert example.targets.masks["current_blind_clear"] == (True, True)
    victory = replace(record.candidates[2], route=RunRoute.VICTORY)
    victory_record = replace(
        record, candidates=(record.candidates[0], record.candidates[1], victory)
    )
    assert route_paired_examples((victory_record,)) == ()


def test_loss_ignores_selected_behavior_and_factual_outcome_fields():
    torch.manual_seed(4)
    record = _record(1)
    model_a = RelationalStrategyPolicyValue()
    model_b = RelationalStrategyPolicyValue()
    model_b.load_state_dict(model_a.state_dict())
    loss_a, metrics_a = route_training_loss(model_a, (record,))
    mutated = replace(
        record,
        selected_index=0,
        behavior_index=0,
        run_won=True,
        terminal_ante=99,
        run_log_score=99.0,
    )
    loss_b, metrics_b = route_training_loss(model_b, (mutated,))
    assert torch.equal(loss_a, loss_b)
    assert metrics_a == metrics_b


def test_null_mismatch_masks_only_the_affected_head():
    torch.manual_seed(9)
    record = _record(1, null_ante8=True)
    model = RelationalStrategyPolicyValue()
    _, masked = route_training_loss(model, (record,))
    specialist = record.candidates[2]
    complete_samples = tuple(
        replace(sample, ante8_win=1.0) for sample in specialist.samples
    )
    complete = replace(
        record,
        candidates=(
            *record.candidates[:2],
            replace(specialist, samples=complete_samples),
        ),
    )
    _, complete_metrics = route_training_loss(model, (complete,))
    assert (
        masked["current_blind_clear_loss"]
        == complete_metrics["current_blind_clear_loss"]
    )
    assert masked["ante8_win_loss"] != complete_metrics["ante8_win_loss"]


def test_split_reconstructs_opaque_groups_and_rejects_tampering():
    records = tuple(_record(seed) for seed in range(20))
    groups = [record.run_group for record in records]
    components = []
    for index in range(1, 6):
        selected = sorted(groups[(index - 1) * 4 : index * 4])
        import hashlib

        components.append(
            {
                "batch_id": f"batch-{index:02d}",
                "opaque_groups": selected,
                "opaque_group_sha256": hashlib.sha256(
                    "\n".join(selected).encode()
                ).hexdigest(),
            }
        )
    split = reconstruct_route_split(records, {"merged_components": components})
    assert len(split.train_groups) == 12
    assert len(split.calibration_groups) == 4
    assert len(split.holdout_groups) == 4
    components[4]["opaque_groups"][0] = components[0]["opaque_groups"][0]
    with pytest.raises(RouteLearningDataError):
        reconstruct_route_split(records, {"merged_components": components})


def test_pair_coverage_is_deterministic():
    records = (_record(1), _record(2))
    assert route_pair_coverage(records) == route_pair_coverage(tuple(records))
