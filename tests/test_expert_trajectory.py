from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from expert_trace_factory import write_current_expert_trace
from state_factory import item_card, state

import balatro_ai_v2.expert_trajectory as expert_module
from balatro_ai_v2.actions import (
    ChoosePackCard,
    JokerSlot,
    OpenedPackSlot,
    SellJoker,
    iter_legal_actions,
)
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.balatrobot.tracing import _row_hash, read_verified_trace
from balatro_ai_v2.expert_trajectory import (
    ExpertTransition,
    expert_trajectories_bytes,
    expert_trajectories_digest,
    materialize_behavior_examples,
    read_expert_trajectories,
    split_expert_trajectories,
    trajectory_from_authority_trace,
)

_ROOT = Path(__file__).resolve().parents[1]
_ORGANIC_TRACE = (
    _ROOT
    / "runs/evidence/planet-buy-use-organic-v1-seeds2411-2430-attempt1"
    / "red-white-seed2411.jsonl"
)


@pytest.fixture
def current_trajectory(tmp_path: Path):
    return trajectory_from_authority_trace(
        write_current_expert_trace(tmp_path / "source.jsonl"),
        run_group="origin-11111111111111111111111111111111",
    )


def test_verified_current_authority_trace_round_trips_public_only(
    tmp_path: Path,
    current_trajectory,
) -> None:
    trajectories = (current_trajectory,)
    payload = expert_trajectories_bytes(trajectories)
    path = tmp_path / "expert.jsonl"
    path.write_bytes(payload)

    assert read_expert_trajectories(path) == trajectories
    assert expert_trajectories_digest(trajectories) == expert_trajectories_digest(
        read_expert_trajectories(path)
    )
    assert len(current_trajectory.transitions) == 3
    assert current_trajectory.best_hand_score == 0

    admitted = json.loads(payload)
    forbidden = {
        "seed",
        "authority",
        "raw",
        "canonical",
        "raw_digest",
        "canonical_digest",
        "rpc_method",
        "rpc_params",
        "rpc_observations",
        "command",
        "run_id",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert not forbidden.intersection(keys(admitted))


def test_behavior_examples_preserve_complete_public_prefix(current_trajectory) -> None:
    examples = materialize_behavior_examples((current_trajectory,))

    assert len(examples) == len(current_trajectory.transitions)
    for index, (example, transition) in enumerate(
        zip(examples, current_trajectory.transitions, strict=True)
    ):
        assert example.decision_index == index
        assert example.observation == transition.before
        assert example.candidates == tuple(iter_legal_actions(example.observation))
        assert example.candidates[example.demonstrated_index] == transition.action
        assert len(example.history) == index
        assert example.action_intents == (None,) * len(example.candidates)
        assert example.action_routes == (None,) * len(example.candidates)
        assert example.tensor_supported


def test_every_supported_example_tensorizes(current_trajectory) -> None:
    pytest.importorskip("torch")
    from balatro_ai_v2.strategy_model import PublicStrategyTensorizer

    examples = materialize_behavior_examples((current_trajectory,))
    supported = tuple(example for example in examples if example.tensor_supported)
    batch = PublicStrategyTensorizer().tensorize(
        tuple(example.observation for example in supported),
        tuple(example.candidates for example in supported),
        tuple(example.action_intents for example in supported),
        action_routes=tuple(example.action_routes for example in supported),
    )

    batch.validate()
    assert int(batch.action_mask.sum()) == sum(
        len(example.candidates) for example in supported
    )


def test_candidate_tampering_fails_closed(current_trajectory) -> None:
    transition = current_trajectory.transitions[0]
    with pytest.raises(ValueError, match="exact public action set"):
        replace(transition, candidates=transition.candidates[::-1])


def test_unknown_private_field_and_duplicate_json_keys_fail_closed(
    tmp_path: Path,
    current_trajectory,
) -> None:
    data = json.loads(expert_trajectories_bytes((current_trajectory,)))
    data["seed"] = "must-not-cross"
    unknown = tmp_path / "unknown.jsonl"
    unknown.write_text(json.dumps(data) + "\n")
    with pytest.raises(ValueError, match="invalid fields"):
        read_expert_trajectories(unknown)

    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text('{"schema_version":1,"schema_version":1}\n')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        read_expert_trajectories(duplicate)

    noncanonical = tmp_path / "noncanonical.jsonl"
    noncanonical.write_text(
        json.dumps(json.loads(expert_trajectories_bytes((current_trajectory,)))) + "\n"
    )
    with pytest.raises(ValueError, match="not canonical JSONL"):
        read_expert_trajectories(noncanonical)


@pytest.mark.parametrize("mutation", ["public_disagreement", "rpc_disagreement"])
def test_rehashed_source_inconsistencies_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    source = write_current_expert_trace(tmp_path / "source.jsonl")
    rows = [deepcopy(row) for row in read_verified_trace(source)]
    if mutation == "public_disagreement":
        rows[1]["public"]["money"] += 1
        expected = "stored public state disagrees"
    else:
        rows[2]["rpc_method"] = "injected_method"
        expected = "RPC does not match"

    path = tmp_path / f"{mutation}.jsonl"
    _write_rehashed(rows, path)

    with pytest.raises(ValueError, match=expected):
        trajectory_from_authority_trace(
            path,
            run_group="origin-22222222222222222222222222222222",
        )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("fake_backend", "not BalatroBot authority"),
        ("deck_mismatch", "deck or stake disagrees"),
        ("boolean_counter", "non-negative integer"),
    ],
)
def test_capture_provenance_and_integer_types_fail_closed(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    source = write_current_expert_trace(tmp_path / "source.jsonl")
    rows = [deepcopy(row) for row in read_verified_trace(source)]
    if mutation == "fake_backend":
        rows[0]["manifest"]["backend"]["backend_name"] = "Jackdaw"
    elif mutation == "deck_mismatch":
        rows[0]["manifest"]["run"]["deck"] = "BLUE"
    else:
        rows[-1]["accepted_decisions"] = True
    tampered = tmp_path / f"{mutation}.jsonl"
    _write_rehashed(rows, tampered)

    with pytest.raises((TypeError, ValueError), match=expected):
        trajectory_from_authority_trace(
            tampered,
            run_group="origin-44444444444444444444444444444444",
        )


def test_declared_decision_limit_is_enforced(tmp_path: Path) -> None:
    source = write_current_expert_trace(
        tmp_path / "over-limit.jsonl",
        max_decisions=2,
    )
    with pytest.raises(ValueError, match="declared decision limit"):
        trajectory_from_authority_trace(
            source,
            run_group="origin-55555555555555555555555555555555",
        )


def test_declared_settle_poll_limit_is_enforced(tmp_path: Path) -> None:
    source = write_current_expert_trace(tmp_path / "poll-over-limit.jsonl")
    rows = [deepcopy(row) for row in read_verified_trace(source)]
    rows[1]["authority"]["poll_count"] = 101
    _write_rehashed(rows, source)

    with pytest.raises(ValueError, match="settle-poll limit"):
        trajectory_from_authority_trace(
            source,
            run_group="origin-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaab",
        )


def test_exact_action_ceiling_rejects_whole_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = write_current_expert_trace(tmp_path / "too-wide.jsonl")
    monkeypatch.setattr(expert_module, "EXPERT_MAX_EXACT_ACTIONS", 1)

    with pytest.raises(ValueError, match="exact-action resource limit"):
        trajectory_from_authority_trace(
            source,
            run_group="origin-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaac",
        )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("complete", False, "incomplete source"),
        ("rejected_decisions", 1, "rejected decisions"),
    ],
)
def test_incomplete_or_rejected_source_run_fails_closed(
    tmp_path: Path,
    field: str,
    value: object,
    expected: str,
) -> None:
    source = write_current_expert_trace(tmp_path / "source.jsonl")
    rows = [deepcopy(row) for row in read_verified_trace(source)]
    rows[-1][field] = value
    tampered = tmp_path / f"{field}.jsonl"
    _write_rehashed(rows, tampered)

    with pytest.raises(ValueError, match=expected):
        trajectory_from_authority_trace(
            tampered,
            run_group="origin-99999999999999999999999999999999",
        )


def test_ante_cap_is_admitted_only_as_censored_behavior(tmp_path: Path) -> None:
    trajectory = trajectory_from_authority_trace(
        write_current_expert_trace(
            tmp_path / "censored.jsonl",
            ante_cap_endpoint=True,
        ),
        run_group="origin-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )

    assert trajectory.terminal_endpoint.value == "ante_cap"
    assert trajectory.long_horizon_censored
    assert not trajectory.transitions[-1].after.terminal
    assert trajectory.antes_cleared == 1


def test_hidden_seed_and_raw_ids_do_not_change_public_examples(tmp_path: Path) -> None:
    first = trajectory_from_authority_trace(
        write_current_expert_trace(
            tmp_path / "first.jsonl",
            run_id="hidden-twin-first",
            private_seed="PRIVATE-TWIN-A",
            id_offset=0,
            reverse_hidden_cards=False,
        ),
        run_group="origin-66666666666666666666666666666666",
    )
    second = trajectory_from_authority_trace(
        write_current_expert_trace(
            tmp_path / "second.jsonl",
            run_id="hidden-twin-second",
            private_seed="PRIVATE-TWIN-B",
            id_offset=900_000,
            reverse_hidden_cards=True,
        ),
        run_group="origin-77777777777777777777777777777777",
    )

    assert replace(first, run_group=second.run_group) == second
    assert materialize_behavior_examples(
        (replace(first, run_group=second.run_group),)
    ) == (materialize_behavior_examples((second,)))


def test_wide_tactical_candidates_are_preserved_but_not_tensor_supported(
    tmp_path: Path,
) -> None:
    trajectory = trajectory_from_authority_trace(
        write_current_expert_trace(tmp_path / "wide.jsonl", wide_hand=True),
        run_group="origin-88888888888888888888888888888888",
    )
    example = materialize_behavior_examples((trajectory,))[0]

    assert len(example.candidates) > 512
    assert not example.tensor_supported
    encoded = expert_trajectories_bytes((trajectory,))
    assert len(json.loads(encoded)["transitions"][0]["candidates"]) == len(
        example.candidates
    )


def test_whole_run_split_is_deterministic_and_disjoint(current_trajectory) -> None:
    trajectories = tuple(
        replace(
            current_trajectory,
            run_group=f"origin-{index:032x}",
        )
        for index in range(10)
    )

    first = split_expert_trajectories(trajectories, split_nonce="frozen-v1")
    second = split_expert_trajectories(trajectories[::-1], split_nonce="frozen-v1")

    assert first == second
    groups = {
        name: {trajectory.run_group for trajectory in split}
        for name, split in first.items()
    }
    assert len(groups["train"]) == 8
    assert len(groups["calibration"]) == 1
    assert len(groups["holdout"]) == 1
    assert groups["train"].isdisjoint(groups["calibration"])
    assert groups["train"].isdisjoint(groups["holdout"])
    assert groups["calibration"].isdisjoint(groups["holdout"])


def test_legacy_action_contract_cannot_be_relabelled_as_current() -> None:
    with pytest.raises(
        ValueError, match="invalid fields|current authority trace schema"
    ):
        trajectory_from_authority_trace(
            _ORGANIC_TRACE,
            run_group="origin-33333333333333333333333333333333",
        )


def test_pack_sale_to_choice_is_expressible_without_losing_pack_state() -> None:
    before_raw = state("BUFFOON_PACK")
    before_raw["jokers"]["cards"] = [item_card("j_joker", card_id=40, kind="JOKER")]
    before_raw["jokers"]["count"] = 1
    after_sale_raw = deepcopy(before_raw)
    after_sale_raw["money"] += 1
    after_sale_raw["jokers"]["cards"] = []
    after_sale_raw["jokers"]["count"] = 0
    before = to_public_observation(before_raw)
    after_sale = to_public_observation(after_sale_raw)
    after_choice = to_public_observation(state("SHOP", money=after_sale.money))

    sale = SellJoker(JokerSlot(0))
    sale_candidates = tuple(iter_legal_actions(before))
    sale_transition = ExpertTransition(
        before,
        sale,
        after_sale,
        sale_candidates,
        sale_candidates.index(sale),
    )
    choice = ChoosePackCard(OpenedPackSlot(0))
    choice_candidates = tuple(iter_legal_actions(after_sale))
    choice_transition = ExpertTransition(
        after_sale,
        choice,
        after_choice,
        choice_candidates,
        choice_candidates.index(choice),
    )

    assert sale_transition.after == choice_transition.before
    assert sale_transition.before.opened_pack == sale_transition.after.opened_pack
    assert (
        sale_transition.before.pack_choices_remaining
        == sale_transition.after.pack_choices_remaining
    )


def _write_rehashed(rows: list[dict[str, object]], path: Path) -> None:
    previous_hash = None
    lines: list[str] = []
    for row in rows:
        row["previous_hash"] = previous_hash
        row.pop("row_hash")
        row_hash = _row_hash(row)
        row["row_hash"] = row_hash
        previous_hash = row_hash
        lines.append(json.dumps(row, sort_keys=True, separators=(",", ":")))
    path.write_text("\n".join(lines) + "\n")
