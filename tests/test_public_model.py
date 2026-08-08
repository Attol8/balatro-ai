from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from balatro_ai_v2.actions import (  # noqa: E402
    BuyPack,
    BuyShopCard,
    BuyVoucher,
    CashOut,
    ChoosePackCard,
    DiscardCards,
    HandSlot,
    LeaveShop,
    PlayCards,
    ReorderHand,
    RerollShop,
    SelectBlind,
    SellConsumable,
    SellJoker,
    SkipBlind,
    SkipPack,
    UseConsumable,
    action_to_data,
    iter_legal_actions,
)
from balatro_ai_v2.balatrobot.adapter import to_public_observation  # noqa: E402
from balatro_ai_v2.public_model import (  # noqa: E402
    PublicModelConfig,
    PublicModelError,
    PublicRecurrentPolicyValue,
    TacticalCandidate,
    TacticalFamily,
    load_public_model,
    public_model_candidates,
    save_public_model,
)
from state_factory import item_card, state  # noqa: E402


def _model() -> PublicRecurrentPolicyValue:
    torch.manual_seed(7)
    model = PublicRecurrentPolicyValue(PublicModelConfig(hidden_size=32))
    model.eval()
    return model


def _step(model: PublicRecurrentPolicyValue, observation):
    actions = public_model_candidates(observation)
    return model.step((observation,), (actions,), (None,))


def test_hidden_twins_have_identical_model_outputs() -> None:
    first = state("SELECTING_HAND", seed="FIRST")
    second = state("SELECTING_HAND", seed="SECOND")
    for raw, rank, suit in ((first, "A", "S"), (second, "2", "D")):
        card = raw["hand"]["cards"][0]
        card["key"] = f"{suit}_{rank}"
        card["value"]["rank"] = rank
        card["value"]["suit"] = suit
        card["state"] = {"hidden": True}
    first["cards"]["cards"].reverse()
    observation_a = to_public_observation(first)
    observation_b = to_public_observation(second)
    model = _model()

    output_a = _step(model, observation_a)
    output_b = _step(model, observation_b)

    assert observation_a == observation_b
    assert torch.equal(output_a.logits, output_b.logits)
    assert torch.equal(output_a.values, output_b.values)


def test_model_ignores_item_label_and_effect_prose_but_uses_public_money() -> None:
    observation = to_public_observation(state("SHOP"))
    changed_item = replace(observation.shop[0], label="Private prose", effect_text="Anything")
    prose_twin = replace(observation, shop=(changed_item,))
    richer = replace(observation, money=observation.money + 7)
    model = _model()

    original = _step(model, observation)
    prose = _step(model, prose_twin)
    money = _step(model, richer)

    assert torch.equal(original.logits, prose.logits)
    assert torch.equal(original.values, prose.values)
    assert not torch.equal(original.values, money.values)


def test_remaining_deck_encoding_is_order_invariant_and_count_sensitive() -> None:
    observation = to_public_observation(state())
    reversed_deck = replace(observation, remaining_deck=tuple(reversed(observation.remaining_deck)))
    first = observation.remaining_deck[0]
    changed_count = replace(
        observation,
        remaining_deck=(replace(first, count=first.count + 1), *observation.remaining_deck[1:]),
    )
    model = _model()

    original = _step(model, observation)
    reordered = _step(model, reversed_deck)
    changed = _step(model, changed_count)

    assert torch.equal(original.values, reordered.values)
    assert not torch.equal(original.values, changed.values)


def test_model_encodes_visible_permanent_card_bonus() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    card = observation.hand[0]
    assert hasattr(card, "permanent_bonus")
    changed = replace(
        observation,
        hand=(replace(card, permanent_bonus=15), *observation.hand[1:]),
    )
    model = _model()

    assert not torch.equal(_step(model, observation).values, _step(model, changed).values)


def test_dynamic_head_supports_every_non_reorder_action_family() -> None:
    selecting = state("SELECTING_HAND")
    selecting["jokers"] = {
        "cards": [item_card("j_joker", card_id=40, kind="JOKER")],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 5,
    }
    selecting["consumables"] = {
        "cards": [item_card("c_pluto", card_id=41, kind="PLANET")],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    observations = (
        to_public_observation(state()),
        to_public_observation(selecting),
        to_public_observation(state("ROUND_EVAL")),
        to_public_observation(state("SHOP", money=10)),
        to_public_observation(state("BUFFOON_PACK")),
    )
    expected = {
        SelectBlind,
        SkipBlind,
        SellJoker,
        SellConsumable,
        UseConsumable,
        CashOut,
        RerollShop,
        BuyShopCard,
        BuyVoucher,
        BuyPack,
        LeaveShop,
        SkipPack,
        ChoosePackCard,
        TacticalCandidate,
    }
    actions = [public_model_candidates(observation) for observation in observations]
    actual = {type(action) for group in actions for action in group}
    model = _model()

    output = model.step(observations, actions, (None,) * len(observations))

    assert actual == expected
    tactical_families = {
        action.family
        for group in actions
        for action in group
        if isinstance(action, TacticalCandidate)
    }
    assert tactical_families == {TacticalFamily.PLAY, TacticalFamily.DISCARD}
    assert output.logits.shape[0] == len(observations)
    assert torch.isfinite(output.logits[output.legal_mask]).all()


def test_factorized_tactical_sampling_and_replay_have_identical_log_probability() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    candidates = public_model_candidates(observation)
    model = _model()
    hidden = model.initial_hidden(1)
    torch.manual_seed(11)

    with torch.no_grad():
        sample = model.sample_actions((observation,), (candidates,), (None,), hidden)
        replay = model.evaluate_actions(
            (observation,),
            (candidates,),
            (None,),
            sample.actions,
            hidden,
        )

    assert isinstance(sample.actions[0], (PlayCards, DiscardCards))
    assert 1 <= len(sample.actions[0].cards) <= 5
    assert tuple(slot.value for slot in sample.actions[0].cards) == tuple(
        sorted(slot.value for slot in sample.actions[0].cards)
    )
    assert torch.allclose(sample.log_probabilities, replay.log_probabilities)


def test_reorder_actions_fail_closed_and_are_not_silently_proposed() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    candidates = public_model_candidates(observation)
    legal_reorder = next(
        action
        for action in iter_legal_actions(observation)
        if isinstance(action, ReorderHand)
    )
    model = _model()

    assert not any(isinstance(action, ReorderHand) for action in candidates)
    with pytest.raises(PublicModelError, match="reorder"):
        model.step((observation,), ((legal_reorder,),), (None,))


def test_candidate_order_does_not_change_logits_or_tie_breaking() -> None:
    observation = to_public_observation(state())
    actions = public_model_candidates(observation)
    model = _model()

    forward = model.step((observation,), (actions,), (None,)).logits[0]
    reverse = model.step((observation,), (tuple(reversed(actions)),), (None,)).logits[0]
    forward_by_action = {str(action_to_data(action)): value for action, value in zip(actions, forward)}
    reverse_by_action = {
        str(action_to_data(action)): value for action, value in zip(reversed(actions), reverse)
    }

    assert forward_by_action.keys() == reverse_by_action.keys()
    assert all(torch.equal(forward_by_action[key], reverse_by_action[key]) for key in forward_by_action)

    for parameter in model.parameters():
        parameter.data.zero_()
    decision_a = model.choose_action(observation, actions)
    decision_b = model.choose_action(observation, tuple(reversed(actions)))
    expected = min(
        actions,
        key=lambda action: json.dumps(action_to_data(action), sort_keys=True, separators=(",", ":")),
    )
    assert action_to_data(decision_a.action) == action_to_data(expected)
    assert action_to_data(decision_b.action) == action_to_data(expected)


def test_padding_and_candidate_validation_fail_closed() -> None:
    blind = to_public_observation(state())
    round_eval = to_public_observation(state("ROUND_EVAL"))
    blind_actions = public_model_candidates(blind)
    cash_actions = public_model_candidates(round_eval)
    model = _model()

    output = model.step((blind, round_eval), (blind_actions, cash_actions), (None, None))

    assert output.legal_mask.tolist() == [[True, True], [True, False]]
    assert output.logits[1, 1].item() == -torch.inf
    with pytest.raises(PublicModelError, match="candidate count"):
        model.step((blind,), ((),), (None,))
    with pytest.raises(PublicModelError, match="duplicates"):
        model.step((blind,), ((blind_actions[0], blind_actions[0]),), (None,))
    tiny = PublicRecurrentPolicyValue(PublicModelConfig(hidden_size=16, max_candidates=1))
    with pytest.raises(PublicModelError, match="candidate count"):
        tiny.step((blind,), (blind_actions,), (None,))


def test_recurrent_reset_matches_fresh_hidden_state() -> None:
    observation = to_public_observation(state())
    actions = public_model_candidates(observation)
    model = _model()
    dirty_hidden = torch.randn(1, model.config.hidden_size)

    reset = model.step(
        (observation,),
        (actions,),
        (None,),
        dirty_hidden,
        torch.tensor([True]),
    )
    fresh = model.step((observation,), (actions,), (None,))

    assert torch.equal(reset.hidden, fresh.hidden)
    assert torch.equal(reset.logits, fresh.logits)


def test_checkpoint_round_trip_preserves_outputs(tmp_path: Path) -> None:
    observation = to_public_observation(state())
    actions = public_model_candidates(observation)
    model = _model()
    path = tmp_path / "model.pt"

    digest = save_public_model(path, model)
    restored = load_public_model(path)
    restored.eval()

    assert len(digest) == 64
    assert torch.equal(
        model.step((observation,), (actions,), (None,)).logits,
        restored.step((observation,), (actions,), (None,)).logits,
    )
    with pytest.raises(FileExistsError):
        save_public_model(path, model)


def test_tiny_public_batch_has_finite_gradients() -> None:
    blind = to_public_observation(state())
    round_eval = to_public_observation(state("ROUND_EVAL"))
    actions = (public_model_candidates(blind), public_model_candidates(round_eval))
    model = PublicRecurrentPolicyValue(PublicModelConfig(hidden_size=16))
    model.train()

    output = model.step((blind, round_eval), actions, (None, None))
    policy_loss = torch.nn.functional.cross_entropy(output.logits, torch.tensor([0, 0]))
    value_loss = torch.nn.functional.mse_loss(output.values, torch.tensor([0.0, -1.0]))
    loss = policy_loss + value_loss
    loss.backward()

    assert torch.isfinite(loss)
    gradients = [parameter.grad for parameter in model.parameters() if parameter.grad is not None]
    assert gradients
    assert all(torch.isfinite(gradient).all() for gradient in gradients)


def test_factorized_tactical_log_probability_has_finite_gradients() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    candidates = public_model_candidates(observation)
    model = PublicRecurrentPolicyValue(PublicModelConfig(hidden_size=16))
    model.train()

    output = model.evaluate_actions(
        (observation,),
        (candidates,),
        (None,),
        (PlayCards((HandSlot(0),)),),
    )
    loss = -output.log_probabilities.mean() + output.values.square().mean()
    loss.backward()

    assert torch.isfinite(loss)
    gradients = [parameter.grad for parameter in model.parameters() if parameter.grad is not None]
    assert gradients
    assert all(torch.isfinite(gradient).all() for gradient in gradients)


def test_public_model_source_has_no_private_engine_imports() -> None:
    import balatro_ai_v2.public_model as public_model

    source = Path(public_model.__file__).read_text(encoding="utf-8")

    assert "balatro_ai_v2.jackdaw" not in source
    assert "balatro_ai_v2.balatrobot" not in source
    assert "balatro_ai_v2.backend" not in source
    assert "public_env_process" not in source
