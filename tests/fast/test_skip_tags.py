from balatro_ai_v2.fast.full_game import (
    BUY_CARD_ACTION_BASE,
    CASH_OUT_ACTION,
    REROLL_ACTION,
    SELECT_BLIND_ACTION,
    SKIP_BLIND_ACTION,
    FastFullGameEnv,
    UNMODELED_TAGS,
)
from balatro_ai_v2.fast.run import BlindKind, RunPhase
from balatro_ai_v2.fast.tags import TAG_RULES


def _env(seed: int = 1) -> FastFullGameEnv:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=seed)
    return env


def test_skip_awards_deterministic_tag() -> None:
    env = _env(seed=3)
    expected = env.skip_tag_key()
    assert expected in TAG_RULES

    repeat = _env(seed=3)
    assert repeat.skip_tag_key() == expected


def test_skip_tag_respects_min_ante() -> None:
    for seed in range(1, 30):
        env = _env(seed=seed)
        rule = TAG_RULES[env.skip_tag_key()]
        assert rule.min_ante is None or rule.min_ante <= 1


def test_economy_tag_doubles_money_immediately() -> None:
    env = _env()
    env.run.money = 12
    env._award_tag("tag_economy")
    assert env.run.money == 24


def test_skip_tag_pays_per_skip() -> None:
    env = _env()
    env.blinds_skipped = 2
    start = env.run.money
    env._award_tag("tag_skip")
    assert env.run.money == start + 10


def test_double_tag_duplicates_next_tag() -> None:
    env = _env()
    env._award_tag("tag_double")
    start = env.run.money
    env.blinds_skipped = 1
    env._award_tag("tag_skip")
    assert env.run.money == start + 10


def test_investment_tag_pays_after_boss() -> None:
    env = _env()
    env._award_tag("tag_investment")
    env.run.phase = RunPhase.ROUND_EVAL
    env.run.blind_kind = BlindKind.BOSS
    baseline = _env()
    baseline.run.phase = RunPhase.ROUND_EVAL
    baseline.run.blind_kind = BlindKind.BOSS

    env.step(CASH_OUT_ACTION)
    baseline.step(CASH_OUT_ACTION)

    assert env.run.money - baseline.run.money == 25
    assert "tag_investment" not in env.tags


def test_charm_tag_opens_free_pack_and_returns_to_blind_select() -> None:
    env = _env()
    env.tags.append("tag_charm")
    env._open_pending_tag_pack()

    assert env.run.phase == RunPhase.PACK
    assert env.pack_cards
    assert all(key.startswith("c_") for key in env.pack_cards)

    while env.run.phase == RunPhase.PACK:
        env.step(env.legal_action_ids()[0])

    assert env.run.phase == RunPhase.BLIND_SELECT


def test_edition_tag_makes_next_shop_joker_free_with_edition() -> None:
    env = _env()
    env.tags.append("tag_foil")
    env.run.phase = RunPhase.ROUND_EVAL
    env.step(CASH_OUT_ACTION)

    joker_indices = [
        index for index, key in enumerate(env.run.shop.item_keys) if key.startswith("j_")
    ]
    if not joker_indices:
        env.run.money = 20
        env.step(REROLL_ACTION)
        joker_indices = [
            index for index, key in enumerate(env.run.shop.item_keys) if key.startswith("j_")
        ]
    assert joker_indices
    target = joker_indices[0]
    assert env.shop_item_editions[target] == 1
    assert target in env.free_shop_item_indices

    money_before = env.run.money
    env.step(BUY_CARD_ACTION_BASE + target)
    assert env.run.money == money_before
    assert env.jokers[-1].edition == 1


def test_negative_edition_joker_grants_extra_slot() -> None:
    env = _env()
    env.tags.append("tag_negative")
    env.run.phase = RunPhase.ROUND_EVAL
    env.step(CASH_OUT_ACTION)
    joker_indices = [
        index for index, key in enumerate(env.run.shop.item_keys) if key.startswith("j_")
    ]
    if not joker_indices:
        env.run.money = 20
        env.step(REROLL_ACTION)
        joker_indices = [
            index for index, key in enumerate(env.run.shop.item_keys) if key.startswith("j_")
        ]
    assert joker_indices
    slots_before = env.run.joker_slots

    env.step(BUY_CARD_ACTION_BASE + joker_indices[0])

    assert env.run.joker_slots == slots_before + 1
    assert env.jokers[-1].edition == 4


def test_d6_tag_makes_rerolls_start_free() -> None:
    env = _env()
    env.tags.append("tag_d_six")
    env.run.phase = RunPhase.ROUND_EVAL
    env.step(CASH_OUT_ACTION)

    assert env.run.shop.reroll_cost == 0
    money_before = env.run.money
    env.step(REROLL_ACTION)
    assert env.run.money == money_before
    assert env.run.shop.reroll_cost == 1


def test_coupon_tag_makes_shop_and_packs_free() -> None:
    env = _env()
    env.tags.append("tag_coupon")
    env.run.phase = RunPhase.ROUND_EVAL
    env.step(CASH_OUT_ACTION)

    assert env.coupon_active
    assert set(range(len(env.run.shop.item_keys))) <= env.free_shop_item_indices


def test_juggle_tag_raises_next_round_hand_size() -> None:
    env = _env()
    env.run.hand_size = 6
    env.tags.append("tag_juggle")
    env.step(SELECT_BLIND_ACTION)

    assert env.round_hand_size == 8  # 6 + 3 clamped to MAX_HAND_OBS
    assert "tag_juggle" not in env.tags


def test_unmodeled_tags_are_known_keys() -> None:
    for key in UNMODELED_TAGS:
        assert key in TAG_RULES


def test_skip_blind_increments_counter_and_advances() -> None:
    env = _env(seed=2)
    env.step(SKIP_BLIND_ACTION)
    assert env.blinds_skipped == 1
    assert env.run.phase in (RunPhase.BLIND_SELECT, RunPhase.PACK)
