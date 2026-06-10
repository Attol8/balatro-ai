"""Event/economy jokers wired into FastFullGameEnv."""

from balatro_ai_v2.fast.cards import NUM_RANKS
from balatro_ai_v2.fast.full_game import (
    SELECT_BLIND_ACTION,
    SELL_JOKER_ACTION_BASE,
    FastFullGameEnv,
    _make_joker,
)
from balatro_ai_v2.fast.jokers import Joker
from balatro_ai_v2.fast.run import BlindKind, RunPhase


def card(rank: int, suit: int) -> int:
    return suit * NUM_RANKS + rank


def env_at_blind_select(jokers: list[Joker]) -> FastFullGameEnv:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=11)
    env.jokers = list(jokers)
    return env


def test_burglar_grants_hands_and_drops_discards() -> None:
    env = env_at_blind_select([Joker("j_burglar")])
    base_hands = env.run.hands

    env.step(SELECT_BLIND_ACTION)

    assert env.hands_remaining == base_hands + 3
    assert env.discards_remaining == 0


def test_chicot_disables_boss_blind() -> None:
    env = env_at_blind_select([Joker("j_chicot")])
    env.run.blind_kind = BlindKind.BOSS
    env.boss_key = "bl_wall"  # x4 requirement when active
    env._sync_required_score()
    boss_required = env.run.required_score

    env.step(SELECT_BLIND_ACTION)

    assert env.boss_blind_disabled
    assert env._boss_rule() is None
    assert env.run.required_score < boss_required


def test_riff_raff_creates_common_jokers_on_blind_select() -> None:
    env = env_at_blind_select([Joker("j_riff_raff")])

    env.step(SELECT_BLIND_ACTION)

    assert len(env.jokers) == 3


def test_cartomancer_creates_tarot_on_blind_select() -> None:
    env = env_at_blind_select([Joker("j_cartomancer")])
    env.consumables = []

    env.step(SELECT_BLIND_ACTION)

    assert len(env.consumables) == 1
    assert env.consumables[0].startswith("c_")


def test_turtle_bean_extends_hand_size_and_decays() -> None:
    env = env_at_blind_select([_make_joker("j_turtle_bean")])
    env.step(SELECT_BLIND_ACTION)
    assert env.round_hand_size == min(env.run.hand_size + 5, 8)

    env.jokers = list(env.jokers)
    from balatro_ai_v2.fast.full_game import _jokers_after_round

    decayed = _jokers_after_round(env.jokers)
    bean = next(j for j in decayed if j.key == "j_turtle_bean")
    assert bean.scaling == 4


def test_rough_gem_pays_per_scored_diamond() -> None:
    env = env_at_blind_select([Joker("j_rough_gem")])
    env.step(SELECT_BLIND_ACTION)
    env.run.hand = [card(5, 3), card(7, 3), card(9, 3), card(2, 3), card(3, 3)]
    money = env.run.money

    env.step(0b11111)  # diamond flush: all five score

    assert env.run.money == money + 5


def test_dna_copies_single_first_hand_card_into_deck() -> None:
    env = env_at_blind_select([Joker("j_dna")])
    env.step(SELECT_BLIND_ACTION)
    target = env.run.hand[0]
    deck_size = len(env.deck_cards)

    env.step(0b00001)

    assert len(env.deck_cards) == deck_size + 1
    assert env.deck_cards.count(target) >= 2


def test_trading_destroys_first_single_discard_and_pays() -> None:
    env = env_at_blind_select([Joker("j_trading")])
    env.step(SELECT_BLIND_ACTION)
    target = env.run.hand[0]
    deck_size = len(env.deck_cards)
    money = env.run.money

    env.step(256 + 0b00001)  # discard one card

    assert env.run.money == money + 3
    assert len(env.deck_cards) == deck_size - 1


def test_burnt_levels_first_discarded_hand_kind() -> None:
    env = env_at_blind_select([Joker("j_burnt")])
    env.step(SELECT_BLIND_ACTION)
    kind = env.score_hand_mask(tuple(env.run.hand), 0b11111).kind
    level = env.hand_levels[kind]

    env.step(256 + 0b11111)

    assert env.hand_levels[kind] == level + 1


def test_egg_and_gift_grow_sell_values_at_round_end() -> None:
    from balatro_ai_v2.fast.full_game import _jokers_after_round

    jokers = [Joker("j_egg", sell_value=2), Joker("j_gift", sell_value=3)]
    grown = _jokers_after_round(jokers)

    assert grown[0].sell_value == 2 + 3 + 1
    assert grown[1].sell_value == 3 + 1


def test_diet_cola_awards_double_tag_on_sell() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=11)
    env.jokers = [Joker("j_diet_cola", sell_value=1)]
    env.run.phase = RunPhase.SHOP

    env.step(SELL_JOKER_ACTION_BASE)

    assert "tag_double" in env.tags


def test_mr_bones_saves_run_at_quarter_score() -> None:
    env = env_at_blind_select([Joker("j_mr_bones")])
    env.step(SELECT_BLIND_ACTION)
    env.run.required_score = 1_000_000
    env.run.score = 250_000
    env.hands_remaining = 1

    result = env.step(0b00001)

    assert not result.terminated
    assert env.run.phase == RunPhase.ROUND_EVAL
    assert all(joker.key != "j_mr_bones" for joker in env.jokers)


def test_mr_bones_does_not_save_below_quarter() -> None:
    env = env_at_blind_select([Joker("j_mr_bones")])
    env.step(SELECT_BLIND_ACTION)
    env.run.required_score = 10_000_000
    env.run.score = 0
    env.hands_remaining = 1

    result = env.step(0b00001)

    assert result.terminated
    assert env.run.phase == RunPhase.GAME_OVER
