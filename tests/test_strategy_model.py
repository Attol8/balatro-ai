from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, fields, replace

import pytest

torch = pytest.importorskip("torch")

from balatro_ai_v2.actions import (  # noqa: E402
    BuyShopCard,
    ShopSlot,
    HandSlot,
    PlayCards,
    SelectBlind,
    UseConsumable,
    ConsumableSlot,
    iter_legal_actions,
)
from balatro_ai_v2.balatrobot.adapter import to_public_observation  # noqa: E402
from balatro_ai_v2.public_state import PublicItem, PublicJokerRuntime  # noqa: E402
from balatro_ai_v2.strategy_context import PublicStrategyContext  # noqa: E402
from balatro_ai_v2.strategy_model import (  # noqa: E402
    EntityKind,
    PublicStrategyTensorizer,
    RELATION_BRAINSTORM,
    RELATION_BLUEPRINT,
    RELATION_PRESENT,
    RELATION_PUBLICLY_ENABLED,
    STRATEGY_MODEL_FORMAT_VERSION,
    STRATEGY_MODEL_SCHEMA_DIGEST,
    RelationalStrategyPolicyValue,
    StrategyCalibration,
    StrategyModelConfig,
    StrategyModelError,
    load_strategy_model,
    save_strategy_model,
)
from balatro_ai_v2.strategy_options import StrategyIntent  # noqa: E402
from state_factory import item_card, playing_card, state  # noqa: E402


def _config() -> StrategyModelConfig:
    return StrategyModelConfig(
        hidden_size=32,
        attention_heads=4,
        attention_layers=1,
        feedforward_size=64,
        max_entities=128,
        max_actions=128,
    )


def _model() -> RelationalStrategyPolicyValue:
    torch.manual_seed(17)
    model = RelationalStrategyPolicyValue(_config())
    model.eval()
    return model


def _trained_provenance(calibration: StrategyCalibration) -> dict[str, object]:
    train_groups = ["origin-00000000000000000000000000000000"]
    calibration_groups = ["origin-00000000000000000000000000000001"]
    holdout_groups = ["origin-00000000000000000000000000000002"]

    def digest(groups: list[str]) -> str:
        return hashlib.sha256("\n".join(sorted(groups)).encode()).hexdigest()

    def metrics(*, calibration_split: bool) -> dict[str, object]:
        result: dict[str, object] = {
            "records": 1,
            "groups": 1,
            "weighting": "inverse_eligible_targets_per_run_and_head",
            "policy": {
                "agreement": 0.75,
                "recommendations": 1,
                "recommendation_groups": 1,
                "recommendation_errors": 0,
                "false_tie_overrides": 0,
                "mean_recommended_utility_gain": 0.1,
                "mean_recommendation_regret": 0.0,
                "override_margin": calibration.policy_override_margin,
            },
            "current_blind": {"count": 0.0, "brier": 0.0, "log_loss": 0.0},
            "next_boss": {"count": 0.0, "brier": 0.0, "log_loss": 0.0},
            "ante8": {"count": 0.0, "brier": 0.0, "log_loss": 0.0},
            "endless_ante": {"count": 0.0, "mae": 0.0, "rmse": 0.0},
            "log_score": {"count": 0.0, "mae": 0.0, "rmse": 0.0},
            "strata": {},
        }
        if calibration_split:
            result["error_radii"] = {
                "current_blind": 0.0,
                "next_boss": 0.0,
                "ante8": 0.0,
                "endless_ante": 0.0,
                "log_score": 0.0,
            }
        return result

    baseline_metrics = {
        "weighting": "inverse_eligible_targets_per_run_and_head",
        "policy": {"agreement": 0.5},
        "current_blind": {"count": 0.0, "brier": 0.0, "log_loss": 0.0},
        "next_boss": {"count": 0.0, "brier": 0.0, "log_loss": 0.0},
        "ante8": {"count": 0.0, "brier": 0.0, "log_loss": 0.0},
        "endless_ante": {"count": 0.0, "mae": 0.0, "rmse": 0.0},
        "log_score": {"count": 0.0, "mae": 0.0, "rmse": 0.0},
    }

    return {
        "training_status": "trained",
        "influence_mode": "shadow",
        "dataset_sha256": "1" * 64,
        "collection_report_sha256": "2" * 64,
        "teacher_config_digest": "3" * 64,
        "strategy_model_schema_digest": STRATEGY_MODEL_SCHEMA_DIGEST,
        "split": {
            "train_groups": train_groups,
            "calibration_groups": calibration_groups,
            "holdout_groups": holdout_groups,
            "train_digest": digest(train_groups),
            "calibration_digest": digest(calibration_groups),
            "holdout_digest": digest(holdout_groups),
        },
        "trainer": {
            "training_seed": 1,
            "split_nonce": "test",
            "epochs": 1,
            "learning_rate": 0.001,
            "weight_decay": 0.0,
            "max_gradient_norm": 1.0,
            "device": "cpu",
            "python_version": "3.test",
            "torch_version": "test",
            "source_digest": "4" * 64,
            "loss_weights": {
                "policy": 1.0,
                "paired_utility": 1.0,
                "ordering": 0.25,
                "current_blind": 1.0,
                "next_boss": 1.0,
                "ante8": 1.0,
                "endless_ante": 0.5,
                "log_score": 0.5,
            },
            "objective": {
                "name": "paired_baseline_relative_search_utility_v1",
                "regression": "smooth_l1",
                "ordering": "signed_softplus;exact_ties=squared_delta",
                "weighting": "run_then_decision_then_alternative_equal",
            },
        },
        "calibration": {
            "parameters": asdict(calibration),
            "metrics": metrics(calibration_split=True),
            "holdout_metrics": metrics(calibration_split=False),
            "empirical_baseline_metrics": baseline_metrics,
            "gate": {
                "safe_policy_recommendations": True,
                "positive_recommendation_coverage": True,
                "policy_agreement_beats_baseline": True,
                "zero_recommendation_errors": True,
                "zero_false_tie_overrides": True,
                "non_positive_recommendation_regret": True,
                "positive_recommended_utility_gain": True,
                "head_improvements": {
                    "current_blind": False,
                    "next_boss": False,
                    "ante8": False,
                    "endless_ante": False,
                    "log_score": False,
                },
                "all_heads_beat_train_only_baselines": False,
                "offline_gate_passed": True,
                "authorizes_action_influence": False,
            },
        },
    }


def _observation(phase: str = "BLIND_SELECT"):
    raw = state(phase)
    # The shared legacy fixture uses a non-vanilla shorthand pack key. This
    # model's contract intentionally admits only exact pinned center keys.
    if phase == "SHOP":
        raw["packs"]["cards"][0]["key"] = "p_buffoon_normal_1"
    return to_public_observation(raw)


def test_relational_model_outputs_policy_and_all_distinct_finite_value_heads() -> None:
    observations = (_observation(), _observation("SELECTING_HAND"))
    actions = tuple(
        tuple(iter_legal_actions(observation)) for observation in observations
    )
    batch = PublicStrategyTensorizer(_config()).tensorize(observations, actions)

    with torch.no_grad():
        output = _model()(batch)

    assert output.policy_logits.shape == output.legal_mask.shape == (2, len(actions[1]))
    assert output.legal_mask[0].sum().item() == len(actions[0])
    assert output.legal_mask[1].sum().item() == len(actions[1])
    for values in (
        output.policy_logits,
        output.current_blind_survival,
        output.next_boss_survival,
        output.ante8_win,
        output.endless_ante,
        output.log_score,
    ):
        assert torch.isfinite(values).all()
    for probabilities in (
        output.current_blind_survival,
        output.next_boss_survival,
        output.ante8_win,
    ):
        assert probabilities.shape == output.legal_mask.shape
        assert ((0.0 <= probabilities) & (probabilities <= 1.0)).all()
    assert (
        output.endless_ante.shape == output.log_score.shape == output.legal_mask.shape
    )
    assert (output.endless_ante >= 0).all()
    assert (output.log_score >= 0).all()


def test_target_relations_and_logits_distinguish_consumable_targets() -> None:
    raw = state("SELECTING_HAND")
    raw["consumables"] = {
        "cards": [item_card("c_death", card_id=50, kind="TAROT")],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    observation = to_public_observation(raw)
    actions = (
        UseConsumable(ConsumableSlot(0), (HandSlot(0), HandSlot(1))),
        UseConsumable(ConsumableSlot(0), (HandSlot(1), HandSlot(2))),
    )
    batch = PublicStrategyTensorizer(_config()).tensorize((observation,), (actions,))

    assert not torch.equal(batch.action_relations[0, 0], batch.action_relations[0, 1])
    with torch.no_grad():
        logits = _model()(batch).policy_logits[0]
    assert logits[0] != logits[1]


def test_shop_playing_card_tensor_preserves_card_price_and_action_relation() -> None:
    first_raw = state("SHOP", money=10)
    first_card = playing_card("H_K", card_id=90)
    first_card["cost"]["buy"] = 1
    first_raw["shop"] = {
        "cards": [first_card],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    second_raw = state("SHOP", money=10)
    second_card = playing_card("D_6", card_id=91, modifier=["BONUS", "FOIL", "RED"])
    second_card["set"] = "ENHANCED"
    second_card["cost"]["buy"] = 2
    second_raw["shop"] = {
        "cards": [second_card],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    observations = (
        to_public_observation(first_raw),
        to_public_observation(second_raw),
    )
    action = BuyShopCard(ShopSlot(0))
    batch = PublicStrategyTensorizer(_config()).tensorize(
        observations, ((action,), (action,))
    )
    shop_rows = [
        torch.nonzero(row == int(EntityKind.SHOP_ITEM), as_tuple=False).item()
        for row in batch.entity_kinds
    ]

    assert not torch.equal(
        batch.entity_features[0, shop_rows[0]],
        batch.entity_features[1, shop_rows[1]],
    )
    assert batch.action_relations[0, 0, shop_rows[0]].any()
    assert batch.action_relations[1, 0, shop_rows[1]].any()


def test_intent_conditioning_admits_same_action_with_distinct_intents() -> None:
    observation = _observation()
    action = SelectBlind()
    actions = (action, action)
    intents = (StrategyIntent.STABILIZE, StrategyIntent.ECONOMY)
    tensorizer = PublicStrategyTensorizer(_config())

    batch = tensorizer.tensorize((observation,), (actions,), (intents,))

    assert not torch.equal(batch.action_features[0, 0], batch.action_features[0, 1])
    with torch.no_grad():
        logits = _model()(batch).policy_logits[0]
    assert logits[0] != logits[1]
    with pytest.raises(StrategyModelError, match="legal actions must be unique"):
        tensorizer.tensorize((observation,), (actions,))


def test_intent_conditioning_rejects_missing_mismatched_and_unknown_values() -> None:
    observation = _observation()
    action = SelectBlind()
    tensorizer = PublicStrategyTensorizer(_config())

    with pytest.raises(StrategyModelError, match="wrong batch size"):
        tensorizer.tensorize((observation,), ((action,),), ())
    with pytest.raises(StrategyModelError, match="exactly one"):
        tensorizer.tensorize((observation,), ((action,),), ((),))
    with pytest.raises(StrategyModelError, match="StrategyIntent"):
        tensorizer.tensorize((observation,), ((action,),), (("stabilize",),))  # type: ignore[arg-type]


def test_calibration_identity_and_frozen_transforms_are_applied() -> None:
    observation = _observation()
    actions = tuple(iter_legal_actions(observation))
    batch = PublicStrategyTensorizer(_config()).tensorize((observation,), (actions,))
    identity = _model()
    calibration = StrategyCalibration(
        policy_temperature=2.0,
        current_blind_bias=1.0,
        current_blind_temperature=2.0,
        next_boss_bias=-0.5,
        next_boss_temperature=1.5,
        ante8_bias=0.25,
        ante8_temperature=3.0,
        endless_ante_bias=2.0,
        log_score_bias=-1.0,
        policy_override_margin=0.75,
        calibrated=True,
    )
    transformed = RelationalStrategyPolicyValue(
        _config(), calibration, _trained_provenance(calibration)
    ).eval()
    transformed.load_state_dict(identity.state_dict(), strict=True)

    with torch.no_grad():
        before = identity(batch)
        after = transformed(batch)

    mask = before.legal_mask
    assert torch.allclose(after.policy_logits[mask], before.policy_logits[mask] / 2.0)
    current_logit = torch.logit(before.current_blind_survival)
    assert torch.allclose(
        after.current_blind_survival,
        torch.sigmoid((current_logit + 1.0) / 2.0),
    )
    assert torch.allclose(after.endless_ante, before.endless_ante + 2.0)
    assert torch.allclose(after.log_score, (before.log_score - 1.0).clamp_min(0.0))


@pytest.mark.parametrize(
    "values",
    (
        {"policy_temperature": 0.0},
        {"next_boss_temperature": float("nan")},
        {"policy_override_margin": -0.01},
        {"calibrated": 1},
    ),
)
def test_calibration_rejects_invalid_values(values: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        StrategyCalibration(**values)  # type: ignore[arg-type]


def test_joker_order_changes_relational_state_and_value() -> None:
    raw = state("SELECTING_HAND")
    raw["jokers"] = {
        "cards": [
            item_card("j_blueprint", card_id=40, kind="JOKER"),
            item_card("j_joker", card_id=41, kind="JOKER"),
        ],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 5,
    }
    observation = to_public_observation(raw)
    swapped = replace(observation, jokers=tuple(reversed(observation.jokers)))
    action = PlayCards((HandSlot(0),))
    tensorizer = PublicStrategyTensorizer(_config())
    original_batch = tensorizer.tensorize((observation,), ((action,),))
    swapped_batch = tensorizer.tensorize((swapped,), ((action,),))

    assert not torch.equal(
        original_batch.entity_features, swapped_batch.entity_features
    )
    assert not torch.equal(
        original_batch.entity_identities, swapped_batch.entity_identities
    )
    model = _model()
    with torch.no_grad():
        original = model(original_batch)
        changed = model(swapped_batch)
    assert original.ante8_win.item() != changed.ante8_win.item()


def test_copy_topology_records_blueprint_brainstorm_and_disabled_self_cycle() -> None:
    raw = state("SELECTING_HAND")
    raw["jokers"] = {
        "cards": [
            item_card("j_blueprint", card_id=40, kind="JOKER"),
            item_card("j_joker", card_id=41, kind="JOKER"),
            item_card("j_brainstorm", card_id=42, kind="JOKER"),
        ],
        "count": 3,
        "highlighted_limit": 1,
        "limit": 5,
    }
    observation = to_public_observation(raw)
    batch = PublicStrategyTensorizer(_config()).tensorize(
        (observation,), ((PlayCards((HandSlot(0),)),),)
    )
    joker_rows = (
        torch.nonzero(batch.entity_kinds[0] == int(EntityKind.JOKER), as_tuple=False)
        .flatten()
        .tolist()
    )
    blueprint, target, brainstorm = joker_rows

    blueprint_edge = batch.entity_relations[0, blueprint, target]
    assert blueprint_edge[RELATION_PRESENT] == 1
    assert blueprint_edge[RELATION_BLUEPRINT] == 1
    assert blueprint_edge[RELATION_BRAINSTORM] == 0
    assert blueprint_edge[RELATION_PUBLICLY_ENABLED] == 1
    brainstorm_edge = batch.entity_relations[0, brainstorm, blueprint]
    assert brainstorm_edge[RELATION_PRESENT] == 1
    assert brainstorm_edge[RELATION_BLUEPRINT] == 0
    assert brainstorm_edge[RELATION_BRAINSTORM] == 1
    assert brainstorm_edge[RELATION_PUBLICLY_ENABLED] == 1
    without_topology = replace(
        batch,
        entity_relations=torch.zeros_like(batch.entity_relations),
    )
    model = _model()
    with torch.no_grad():
        with_topology_value = model(batch).ante8_win
        without_topology_value = model(without_topology).ante8_win
    assert not torch.equal(with_topology_value, without_topology_value)

    self_cycle_observation = replace(
        observation,
        jokers=(observation.jokers[2], observation.jokers[1], observation.jokers[0]),
    )
    self_cycle_batch = PublicStrategyTensorizer(_config()).tensorize(
        (self_cycle_observation,), ((PlayCards((HandSlot(0),)),),)
    )
    first_joker = torch.nonzero(
        self_cycle_batch.entity_kinds[0] == int(EntityKind.JOKER), as_tuple=False
    ).flatten()[0]
    self_edge = self_cycle_batch.entity_relations[0, first_joker, first_joker]
    assert self_edge[RELATION_PRESENT] == 1
    assert self_edge[RELATION_BRAINSTORM] == 1
    assert self_edge[RELATION_PUBLICLY_ENABLED] == 0


def test_copy_topology_uses_shared_debuffed_target_gate() -> None:
    raw = state("SELECTING_HAND")
    target = item_card("j_joker", card_id=41, kind="JOKER")
    target["state"] = {"debuff": True}
    raw["jokers"] = {
        "cards": [item_card("j_blueprint", card_id=40, kind="JOKER"), target],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 5,
    }
    observation = to_public_observation(raw)
    batch = PublicStrategyTensorizer(_config()).tensorize(
        (observation,), ((PlayCards((HandSlot(0),)),),)
    )
    joker_rows = torch.nonzero(
        batch.entity_kinds[0] == int(EntityKind.JOKER), as_tuple=False
    ).flatten()
    edge = batch.entity_relations[0, joker_rows[0], joker_rows[1]]

    assert edge[RELATION_PRESENT] == 1
    assert edge[RELATION_BLUEPRINT] == 1
    assert edge[RELATION_PUBLICLY_ENABLED] == 0


def test_tensorization_is_deterministic_and_batch_padding_is_masked() -> None:
    observations = (_observation(), _observation("SHOP"))
    actions = tuple(
        tuple(iter_legal_actions(observation)) for observation in observations
    )
    tensorizer = PublicStrategyTensorizer(_config())

    first = tensorizer.tensorize(observations, actions)
    second = tensorizer.tensorize(observations, actions)

    for field in fields(first):
        assert torch.equal(getattr(first, field.name), getattr(second, field.name))
    assert first.entity_mask[0].sum() != first.entity_mask[1].sum()
    assert first.action_mask[0].sum() != first.action_mask[1].sum()
    assert not first.action_relations[~first.action_mask].any()
    first.validate()


def test_public_history_context_changes_only_public_tensor_features() -> None:
    observation = to_public_observation(state("SHOP"))
    actions = tuple(iter_legal_actions(observation))
    tensorizer = PublicStrategyTensorizer(_config())

    plain = tensorizer.tensorize((observation,), (actions,))
    contextual = tensorizer.tensorize(
        (observation,),
        (actions,),
        contexts=(
            PublicStrategyContext(
                current_shop_actions=2,
                current_shop_has_joker_sale=True,
                prior_shop_has_joker_sale=True,
                best_hand_log_score=5.0,
                incoming_intent=StrategyIntent.ECONOMY,
            ),
        ),
    )

    assert not torch.equal(plain.entity_features, contextual.entity_features)
    assert torch.equal(plain.action_kinds, contextual.action_kinds)
    assert torch.equal(plain.action_relations, contextual.action_relations)


def test_hidden_twins_and_display_prose_do_not_change_tensors() -> None:
    first_raw = state("SELECTING_HAND", seed="FIRST")
    second_raw = state("SELECTING_HAND", seed="SECOND")
    for raw, rank, suit in ((first_raw, "A", "S"), (second_raw, "2", "D")):
        card = raw["hand"]["cards"][0]
        card["key"] = f"{suit}_{rank}"
        card["value"]["rank"] = rank
        card["value"]["suit"] = suit
        card["state"] = {"hidden": True}
    first_raw["cards"]["cards"][0], second_raw["cards"]["cards"][0] = (
        deepcopy(second_raw["hand"]["cards"][0]),
        deepcopy(first_raw["hand"]["cards"][0]),
    )
    first = to_public_observation(first_raw)
    second = to_public_observation(second_raw)
    assert first == second
    action = PlayCards((HandSlot(0),))
    tensorizer = PublicStrategyTensorizer(_config())

    a = tensorizer.tensorize((first,), ((action,),))
    b = tensorizer.tensorize((second,), ((action,),))
    assert torch.equal(a.entity_features, b.entity_features)
    assert torch.equal(a.entity_identities, b.entity_identities)
    intent_a = tensorizer.tensorize(
        (first,), ((action,),), ((StrategyIntent.RELIABLE_HAND,),)
    )
    intent_b = tensorizer.tensorize(
        (second,), ((action,),), ((StrategyIntent.RELIABLE_HAND,),)
    )
    for field in fields(intent_a):
        assert torch.equal(getattr(intent_a, field.name), getattr(intent_b, field.name))

    shop = _observation("SHOP")
    prose_item = replace(
        shop.shop[0], label="Invented label", effect_text="Private prose"
    )
    prose = replace(shop, shop=(prose_item,))
    shop_actions = tuple(iter_legal_actions(shop))
    prose_actions = tuple(iter_legal_actions(prose))
    original_tensor = tensorizer.tensorize((shop,), (shop_actions,))
    prose_tensor = tensorizer.tensorize((prose,), (prose_actions,))
    assert torch.equal(original_tensor.entity_features, prose_tensor.entity_features)
    assert torch.equal(
        original_tensor.entity_identities, prose_tensor.entity_identities
    )


def test_stone_shop_private_base_identity_does_not_change_strategy_tensors() -> None:
    left_raw = state("SHOP")
    left_card = playing_card("H_K", card_id=92, modifier=["STONE"])
    left_card["set"] = "ENHANCED"
    left_raw["shop"] = {
        "cards": [left_card], "count": 1, "highlighted_limit": 1, "limit": 2
    }
    right_raw = json.loads(json.dumps(left_raw))
    right_card = right_raw["shop"]["cards"][0]
    right_card["key"] = "C_2"
    right_card["value"]["rank"] = "2"
    right_card["value"]["suit"] = "C"
    left = to_public_observation(left_raw)
    right = to_public_observation(right_raw)
    left_actions = tuple(iter_legal_actions(left))
    right_actions = tuple(iter_legal_actions(right))
    tensorizer = PublicStrategyTensorizer(_config())

    a = tensorizer.tensorize((left,), (left_actions,))
    b = tensorizer.tensorize((right,), (right_actions,))

    for field in fields(a):
        assert torch.equal(getattr(a, field.name), getattr(b, field.name))


def test_unknown_public_semantics_and_illegal_actions_fail_closed() -> None:
    observation = _observation("SELECTING_HAND")
    unknown = replace(
        observation,
        jokers=(PublicItem("j_future_mod", "Future", "JOKER"),),
    )
    tensorizer = PublicStrategyTensorizer(_config())

    with pytest.raises(StrategyModelError, match="unsupported public Joker"):
        tensorizer.tensorize((unknown,), ((PlayCards((HandSlot(0),)),),))
    with pytest.raises(StrategyModelError, match="not legal"):
        tensorizer.tensorize((observation,), ((UseConsumable(ConsumableSlot(0)),),))


@pytest.mark.parametrize(
    "key",
    (
        "p_buffoon_normal_1",
        "p_buffoon_normal_2",
        "p_buffoon_jumbo_1",
        "p_buffoon_mega_1",
    ),
)
def test_exact_vanilla_buffoon_boosters_are_covered(key: str) -> None:
    raw = state("SHOP")
    raw["packs"]["cards"][0]["key"] = key
    changed = to_public_observation(raw)
    assert changed.packs[0].key in {
        "p_buffoon_normal",
        "p_buffoon_jumbo",
        "p_buffoon_mega",
    }

    PublicStrategyTensorizer(_config()).tensorize(
        (changed,), (tuple(iter_legal_actions(changed)),)
    ).validate()


@pytest.mark.parametrize(
    "key",
    ("p_arcana_future", "p_buffoon_jumbo_2", "p_buffoon_normal_3"),
)
def test_lookalike_or_nonexistent_booster_fails_closed(key: str) -> None:
    observation = _observation("SHOP")
    lookalike = replace(observation.packs[0], key=key)
    unknown = replace(observation, packs=(lookalike,))

    with pytest.raises(StrategyModelError, match="unsupported public booster"):
        PublicStrategyTensorizer(_config()).tensorize(
            (unknown,), (tuple(iter_legal_actions(unknown)),)
        )


def test_non_finite_runtime_fails_closed() -> None:
    observation = _observation("SELECTING_HAND")
    joker = PublicItem("j_joker", "Joker", "JOKER")
    # Public value objects are intentionally permissive enough to preserve a
    # malformed upstream value; the model boundary is where it must be rejected.
    joker = replace(joker, runtime=PublicJokerRuntime(current_x_mult=float("inf")))
    malformed = replace(observation, jokers=(joker,))

    with pytest.raises(StrategyModelError, match="not a finite number"):
        PublicStrategyTensorizer(_config()).tensorize(
            (malformed,), ((PlayCards((HandSlot(0),)),),)
        )


def test_scientific_scale_public_scores_tensorize_without_float_overflow() -> None:
    observation = _observation("SELECTING_HAND")
    enormous = 10**1000
    huge = replace(
        observation,
        round=replace(observation.round, chips=enormous),
        blinds=tuple(replace(blind, score=enormous) for blind in observation.blinds),
        hand_stats=tuple(
            replace(stat, chips=enormous, mult=enormous)
            for stat in observation.hand_stats
        ),
    )
    action = PlayCards((HandSlot(0),))
    tensorizer = PublicStrategyTensorizer(_config())

    ordinary = tensorizer.tensorize((observation,), ((action,),))
    scaled = tensorizer.tensorize((huge,), ((action,),))

    assert torch.isfinite(scaled.entity_features).all()
    assert not torch.equal(ordinary.entity_features, scaled.entity_features)


def test_strategy_tensor_distinguishes_disabled_current_boss() -> None:
    observation = _observation("SELECTING_HAND")
    enabled = replace(
        observation,
        blinds=tuple(
            replace(blind, status="DEFEATED")
            if blind.kind == "SMALL"
            else replace(blind, status="CURRENT")
            if blind.kind == "BOSS"
            else blind
            for blind in observation.blinds
        ),
    )
    disabled = replace(
        enabled,
        blinds=tuple(
            replace(blind, disabled=True) if blind.kind == "BOSS" else blind
            for blind in enabled.blinds
        ),
    )
    action = PlayCards((HandSlot(0),))
    tensorizer = PublicStrategyTensorizer(_config())

    enabled_tensor = tensorizer.tensorize((enabled,), ((action,),))
    disabled_tensor = tensorizer.tensorize((disabled,), ((action,),))

    assert not torch.equal(
        enabled_tensor.entity_features, disabled_tensor.entity_features
    )


def test_exact_vanilla_skip_tag_is_admitted() -> None:
    observation = _observation()
    tagged = replace(
        observation,
        blinds=tuple(
            replace(blind, tag_name="Skip Tag") if blind.status == "SELECT" else blind
            for blind in observation.blinds
        ),
    )

    PublicStrategyTensorizer(_config()).tensorize(
        (tagged,), (tuple(iter_legal_actions(tagged)),)
    ).validate()


def test_strategy_checkpoint_round_trip_and_digest(tmp_path) -> None:
    model = _model()
    path = tmp_path / "strategy.pt"

    digest = save_strategy_model(path, model)
    loaded = load_strategy_model(path)

    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(digest) == 64
    assert loaded.config == model.config
    assert loaded.calibration == StrategyCalibration()
    assert loaded.provenance == {"training_status": "untrained"}
    payload = torch.load(path, weights_only=True)
    assert payload["format_version"] == STRATEGY_MODEL_FORMAT_VERSION == 6
    assert set(payload) == {
        "format_version",
        "schema_digest",
        "config",
        "calibration",
        "provenance",
        "state_dict",
    }
    for name, parameter in model.state_dict().items():
        assert torch.equal(parameter, loaded.state_dict()[name])


def test_strategy_checkpoint_rejects_extra_fields(tmp_path) -> None:
    valid = tmp_path / "valid.pt"
    path = tmp_path / "extra.pt"
    save_strategy_model(valid, _model())
    payload = torch.load(valid, weights_only=True)
    payload["private_payload"] = {}
    torch.save(payload, path)

    with pytest.raises(StrategyModelError, match="fields are invalid"):
        load_strategy_model(path)


def test_strategy_checkpoint_rejects_missing_fields(tmp_path) -> None:
    valid = tmp_path / "valid.pt"
    path = tmp_path / "missing.pt"
    save_strategy_model(valid, _model())
    payload = torch.load(valid, weights_only=True)
    del payload["calibration"]
    torch.save(payload, path)

    with pytest.raises(StrategyModelError, match="fields are invalid"):
        load_strategy_model(path)


def test_strategy_checkpoint_rejects_semantic_schema_drift(tmp_path) -> None:
    valid = tmp_path / "valid.pt"
    changed = tmp_path / "changed.pt"
    save_strategy_model(valid, _model())
    payload = torch.load(valid, weights_only=True)
    assert payload["schema_digest"] == STRATEGY_MODEL_SCHEMA_DIGEST
    payload["schema_digest"] = "0" * 64
    torch.save(payload, changed)

    with pytest.raises(StrategyModelError, match="version or payload is invalid"):
        load_strategy_model(changed)


@pytest.mark.parametrize("field", ("calibration", "provenance", "state_dict"))
def test_strategy_checkpoint_rejects_nonfinite_metadata(tmp_path, field: str) -> None:
    valid = tmp_path / "valid.pt"
    changed = tmp_path / f"nonfinite-{field}.pt"
    save_strategy_model(valid, _model())
    payload = torch.load(valid, weights_only=True)
    if field == "calibration":
        payload[field]["policy_temperature"] = float("nan")
    elif field == "provenance":
        payload[field] = {"training_status": "trained", "metric": float("inf")}
    else:
        parameter = next(iter(payload[field]))
        payload[field][parameter].view(-1)[0] = float("nan")
    torch.save(payload, changed)

    with pytest.raises(StrategyModelError, match="checkpoint is incompatible"):
        load_strategy_model(changed)


def test_strategy_checkpoint_round_trips_calibration_and_training_provenance(
    tmp_path,
) -> None:
    calibration = StrategyCalibration(
        policy_temperature=1.25,
        current_blind_bias=0.1,
        policy_override_margin=0.4,
        calibrated=True,
    )
    provenance = _trained_provenance(calibration)
    model = RelationalStrategyPolicyValue(_config(), calibration, provenance)
    path = tmp_path / "trained.pt"

    save_strategy_model(path, model)
    loaded = load_strategy_model(path)

    assert loaded.calibration == calibration
    assert loaded.provenance == provenance


def test_trained_provenance_requires_complete_contract_and_matching_calibration() -> (
    None
):
    calibration = StrategyCalibration(calibrated=True)
    incomplete = {"training_status": "trained"}
    mismatch = _trained_provenance(calibration)
    mismatch["calibration"]["parameters"]["policy_temperature"] = 2.0

    with pytest.raises(ValueError, match="fields are invalid"):
        RelationalStrategyPolicyValue(_config(), calibration, incomplete)
    with pytest.raises(ValueError, match="disagrees with model calibration"):
        RelationalStrategyPolicyValue(_config(), calibration, mismatch)


def test_trained_provenance_recomputes_split_digest_and_gate_logic() -> None:
    calibration = StrategyCalibration(calibrated=True)
    bad_digest = _trained_provenance(calibration)
    bad_digest["split"]["train_digest"] = "0" * 64
    bad_gate = _trained_provenance(calibration)
    bad_gate["calibration"]["gate"]["offline_gate_passed"] = False

    with pytest.raises(ValueError, match="digest disagrees"):
        RelationalStrategyPolicyValue(_config(), calibration, bad_digest)
    with pytest.raises(ValueError, match="gate is inconsistent"):
        RelationalStrategyPolicyValue(_config(), calibration, bad_gate)


@pytest.mark.parametrize(
    "provenance",
    (
        {"training_status": "untrained", "dataset_digest": "forbidden"},
        {"training_status": "trained", "metric": float("inf")},
        {"training_status": "unknown"},
        {"training_status": "trained", "tuple": (1, 2)},
    ),
)
def test_strategy_provenance_rejects_non_exact_or_nonfinite_values(provenance) -> None:
    with pytest.raises(ValueError):
        RelationalStrategyPolicyValue(_config(), provenance=provenance)
