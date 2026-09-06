from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from state_factory import item_card, playing_card, state

from balatro_ai_v2.actions import (
    ChoosePackCard,
    HandSlot,
    JokerSlot,
    LeaveShop,
    OpenedPackSlot,
    PlayCards,
    PublicAction,
    SellJoker,
    action_to_data,
)
from balatro_ai_v2.backend import BackendCapabilities, BackendMetadata, RunSpec
from balatro_ai_v2.balatrobot.adapter import action_to_rpc, to_public_observation
from balatro_ai_v2.balatrobot.tracing import AuthorityTraceWriter, TraceManifest
from balatro_ai_v2.canonical import BalatroBotCanonicalizer, CanonicalObservedState
from balatro_ai_v2.policy_wire import POLICY_ACTION_CONTRACT
from balatro_ai_v2.public_codec import public_observation_to_data


def write_current_expert_trace(
    path: Path,
    *,
    run_id: str = "expert-fixture-run",
    private_seed: str = "PRIVATE-SOURCE-SEED",
    id_offset: int = 0,
    max_decisions: int | None = None,
    wide_hand: bool = False,
    ante_cap_endpoint: bool = False,
    reverse_hidden_cards: bool = True,
) -> Path:
    if wide_hand:
        before_raw = state("SELECTING_HAND", seed=private_seed)
        hand = [
            playing_card(key, card_id=id_offset + 500 + index)
            for index, key in enumerate(
                ("S_A", "H_K", "D_Q", "C_J", "S_T", "H_9", "D_8", "C_7", "S_6")
            )
        ]
        before_raw["hand"] = {
            "cards": hand,
            "count": len(hand),
            "highlighted_limit": 5,
            "limit": 9,
        }
        raw_states = (before_raw, state("GAME_OVER", seed=private_seed))
        actions: tuple[PublicAction, ...] = (PlayCards((HandSlot(0),)),)
    else:
        raw_states, actions = _pack_sale_states(
            private_seed,
            id_offset,
            ante_cap_endpoint=ante_cap_endpoint,
            reverse_hidden_cards=reverse_hidden_cards,
        )

    declared_max_decisions = max_decisions or len(actions)
    canonicalizer = BalatroBotCanonicalizer()
    authority = tuple(
        _authority(raw, canonicalizer.canonicalize(raw)) for raw in raw_states
    )
    public = tuple(to_public_observation(raw) for raw in raw_states)
    manifest = TraceManifest(
        run_id=run_id,
        created_at="2026-09-06T00:00:00+00:00",
        repository_revision="a" * 40,
        repository_dirty=False,
        source_digest="b" * 64,
        command=("private-command", private_seed),
        config_digest="c" * 64,
        policy_name="TestExpertPolicy",
        model_digest=None,
        inference_budget=f"policy_action_contract={POLICY_ACTION_CONTRACT}",
        backend=BackendMetadata(
            backend_name="BalatroBot/LÖVE",
            backend_version="cli-test+mod-test+patch-sha256:" + "d" * 64,
            adapter_version="test-v1",
            game_version="1.0.1o-FULL",
            runtime_version="LOVE-11.5-test",
            capabilities=BackendCapabilities(True, False, False, False, False),
        ),
        run=RunSpec("RED", "WHITE", private_seed),
        sealed_seed_manifest_digest=None,
        max_decisions=declared_max_decisions,
        max_settle_polls=100,
        wall_clock_limit_seconds=30.0,
        launch_fast=False,
        launch_headless=True,
        profile_mode="all_unlocked",
        max_antes_cleared=(1 if ante_cap_endpoint else 20),
        mods=("balatrobot@test", "Steamodded@test", "Lovely@test"),
    )
    writer = AuthorityTraceWriter(path, manifest)
    writer.record(
        "run_start",
        authority=authority[0],
        public=public_observation_to_data(public[0]),
    )
    counts: dict[str, int] = {}
    for index, action in enumerate(actions):
        method, params = action_to_rpc(action, public[index])
        action_type = str(action_to_data(action)["type"])
        counts[action_type] = counts.get(action_type, 0) + 1
        writer.record(
            "transition",
            before_canonical_digest=authority[index]["canonical_digest"],
            action=action_to_data(action),
            rpc_method=method,
            rpc_params=params,
            status="accepted",
            rpc_observations=[],
            error=None,
            after=authority[index + 1],
            public_after=public_observation_to_data(public[index + 1]),
        )
    final = public[-1]
    writer.record(
        "run_end",
        complete=True,
        won=final.won,
        antes_cleared=final.antes_cleared,
        ante=final.ante,
        round_no=final.round_no,
        accepted_decisions=len(actions),
        rejected_decisions=0,
        terminal_reason=("ante_cap" if ante_cap_endpoint else "game_over"),
        final_public_digest=final.digest(),
        terminal_blind=None,
        action_counts=dict(sorted(counts.items())),
        semantic_action_counts=dict(sorted(counts.items())),
        cards_played=(1 if wide_hand else 0),
        cards_discarded=0,
        best_hand_score=0,
    )
    return path


def _pack_sale_states(
    private_seed: str,
    id_offset: int,
    *,
    ante_cap_endpoint: bool,
    reverse_hidden_cards: bool,
) -> tuple[tuple[dict[str, object], ...], tuple[PublicAction, ...]]:
    before_raw = state("BUFFOON_PACK", seed=private_seed)
    hidden_cards = before_raw["cards"]["cards"]
    assert isinstance(hidden_cards, list)
    if reverse_hidden_cards:
        hidden_cards.reverse()
    for index, card in enumerate(hidden_cards):
        assert isinstance(card, dict)
        card["id"] = id_offset + 800_000 + index
    before_raw["jokers"]["cards"] = [
        item_card("j_joker", card_id=id_offset + 401_337, kind="JOKER")
    ]
    before_raw["jokers"]["count"] = 1
    after_sale_raw = deepcopy(before_raw)
    after_sale_raw["money"] += 1
    after_sale_raw["jokers"]["cards"] = []
    after_sale_raw["jokers"]["count"] = 0
    shop_raw = state("SHOP", seed=private_seed, money=after_sale_raw["money"])
    if ante_cap_endpoint:
        terminal_raw = state(
            "BLIND_SELECT",
            seed=private_seed,
            money=after_sale_raw["money"],
        )
        terminal_raw["ante_num"] = 2
    else:
        terminal_raw = state(
            "GAME_OVER",
            seed=private_seed,
            money=after_sale_raw["money"],
        )
    return (
        (before_raw, after_sale_raw, shop_raw, terminal_raw),
        (
            SellJoker(JokerSlot(0)),
            ChoosePackCard(OpenedPackSlot(0)),
            LeaveShop(),
        ),
    )


def _authority(
    raw: dict[str, object],
    observed: CanonicalObservedState,
) -> dict[str, object]:
    return {
        "raw": raw,
        "canonical": observed.canonical,
        "raw_digest": observed.raw_digest,
        "canonical_digest": observed.canonical_digest,
        "settled": True,
        "poll_count": 0,
    }
