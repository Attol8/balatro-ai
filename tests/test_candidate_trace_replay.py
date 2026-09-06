from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from state_factory import state

from balatro_ai_v2.actions import (
    LeaveShop,
    PublicAction,
    SelectBlind,
    action_to_data,
    iter_legal_actions,
)
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.candidate_trace_replay import (
    CANDIDATE_TRACE_FORMAT,
    CANDIDATE_TRACE_SCHEMA_VERSION,
    CandidateTraceManifest,
    CandidateTraceReplayError,
    CandidateTraceReplayPolicy,
    CandidateTraceWriter,
)
from balatro_ai_v2.policy_wire import POLICY_ACTION_CONTRACT
from balatro_ai_v2.public_codec import public_observation_to_data


def _write_candidate_trace(
    path: Path,
    *,
    action: PublicAction = LeaveShop(),
    candidate_only: bool = True,
    complete: bool = True,
    action_contract: str = POLICY_ACTION_CONTRACT,
    extra_transition_field: bool = False,
) -> Path:
    before = to_public_observation(state("SHOP"))
    after = to_public_observation(state("GAME_OVER"))
    manifest = CandidateTraceManifest(
        format=CANDIDATE_TRACE_FORMAT,
        run_id="candidate-trace-test",
        created_at="2026-09-06T00:00:00+00:00",
        repository_revision="a" * 40,
        repository_dirty=False,
        source_digest="b" * 64,
        config_digest="c" * 64,
        policy_name="DeterminizedSearchPolicy[test]:parent-v1",
        model_digest=None,
        inference_budget=f"policy_action_contract={POLICY_ACTION_CONTRACT}",
        backend_name="Jackdaw",
        backend_version="test",
        adapter_version="test",
        game_version="test",
        runtime_version="Python",
        candidate_only=candidate_only,
        deck="RED",
        stake="WHITE",
        max_decisions=10,
        max_antes_cleared=20,
        action_contract=action_contract,
        schema_version=CANDIDATE_TRACE_SCHEMA_VERSION,
    )
    manifest_data = asdict(manifest)
    config = {
        name: manifest_data[name]
        for name in (
            "format",
            "policy_name",
            "model_digest",
            "inference_budget",
            "backend_name",
            "backend_version",
            "adapter_version",
            "game_version",
            "runtime_version",
            "candidate_only",
            "deck",
            "stake",
            "max_decisions",
            "max_antes_cleared",
            "action_contract",
            "schema_version",
        )
    }
    manifest = replace(
        manifest,
        config_digest=hashlib.sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )
    writer = CandidateTraceWriter(path, manifest)
    writer.record(
        "run_start",
        authority={"seed": "PRIVATE-SOURCE-SEED"},
        public=public_observation_to_data(before),
    )
    transition = {
        "action": action_to_data(action),
        "status": "accepted",
        "error": None,
        "public_after": public_observation_to_data(after),
    }
    if extra_transition_field:
        transition["unexpected"] = True
        writer._write("transition", **transition)
    else:
        writer.record(
            "transition",
            **transition,
            rpc_method="private-rpc",
            rpc_params={"seed": "PRIVATE-SOURCE-SEED"},
            rpc_observations=["PRIVATE-SOURCE-SEED"],
            after={"seed": "PRIVATE-SOURCE-SEED"},
        )
    action_type = str(action_to_data(action)["type"])
    writer.record(
        "run_end",
        complete=complete,
        won=after.won,
        antes_cleared=after.antes_cleared,
        ante=after.ante,
        round_no=after.round_no,
        accepted_decisions=1,
        rejected_decisions=0,
        terminal_reason="game_over",
        final_public_digest=after.digest(),
        action_counts={action_type: 1},
        cards_played=0,
        cards_discarded=0,
        best_hand_score=0,
    )
    return path


def test_candidate_trace_replay_requires_exact_public_path(tmp_path: Path) -> None:
    policy = CandidateTraceReplayPolicy.from_path(
        _write_candidate_trace(tmp_path / "candidate.jsonl")
    )
    before = policy.steps[0].before
    action = policy.choose_action(before, lambda: iter_legal_actions(before), ())

    assert action == LeaveShop()
    assert policy.consumed_actions == 1
    policy.assert_complete(policy.steps[0].after)


def test_candidate_trace_replay_fails_on_public_divergence(tmp_path: Path) -> None:
    policy = CandidateTraceReplayPolicy.from_path(
        _write_candidate_trace(tmp_path / "candidate.jsonl")
    )
    wrong = to_public_observation(state("BLIND_SELECT"))

    with pytest.raises(CandidateTraceReplayError, match="observation diverged"):
        policy.choose_action(wrong, lambda: iter_legal_actions(wrong), ())


def test_candidate_trace_replay_rejects_source_action_that_is_not_publicly_legal(
    tmp_path: Path,
) -> None:
    path = _write_candidate_trace(
        tmp_path / "candidate.jsonl", action=SelectBlind()
    )

    with pytest.raises(CandidateTraceReplayError, match="not uniquely legal"):
        CandidateTraceReplayPolicy.from_path(path)


def test_candidate_trace_replay_fails_when_action_is_not_live_legal(
    tmp_path: Path,
) -> None:
    policy = CandidateTraceReplayPolicy.from_path(
        _write_candidate_trace(tmp_path / "candidate.jsonl")
    )

    with pytest.raises(CandidateTraceReplayError, match="not uniquely legal"):
        policy.choose_action(policy.steps[0].before, lambda: iter(()), ())


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"candidate_only": False}, "candidate-only"),
        ({"complete": False}, "incomplete"),
        ({"action_contract": "old"}, "action contract"),
        ({"extra_transition_field": True}, "invalid fields"),
    ],
)
def test_candidate_trace_replay_rejects_inadmissible_sources(
    tmp_path: Path,
    kwargs: dict[str, object],
    message: str,
) -> None:
    path = _write_candidate_trace(tmp_path / "candidate.jsonl", **kwargs)

    with pytest.raises(CandidateTraceReplayError, match=message):
        CandidateTraceReplayPolicy.from_path(path)


def test_candidate_trace_replay_rejects_unconsumed_actions(tmp_path: Path) -> None:
    policy = CandidateTraceReplayPolicy.from_path(
        _write_candidate_trace(tmp_path / "candidate.jsonl")
    )

    with pytest.raises(CandidateTraceReplayError, match="consumed 0 of 1"):
        policy.assert_complete(policy.final_observation)


def test_candidate_transcript_contains_no_seed_or_private_authority_fields(
    tmp_path: Path,
) -> None:
    path = _write_candidate_trace(tmp_path / "opaque-run.jsonl")
    raw = path.read_text(encoding="utf-8")

    assert "2491" not in raw
    assert '"seed"' not in raw
    assert '"authority"' not in raw
    assert '"rpc_method"' not in raw
    assert "PRIVATE-SOURCE-SEED" not in raw
