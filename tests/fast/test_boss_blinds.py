from balatro_ai_v2.fast.blinds import BLIND_RULES
from balatro_ai_v2.fast.cards import NUM_RANKS
from balatro_ai_v2.fast.full_game import (
    SELECT_BLIND_ACTION,
    FastFullGameEnv,
    UNMODELED_BOSS_EFFECTS,
)
from balatro_ai_v2.fast.hand import HIGH_CARD, PAIR
from balatro_ai_v2.fast.run import BlindKind, RunPhase


def _card(suit: int, rank: int) -> int:
    return suit * NUM_RANKS + rank


def _boss_env(boss_key: str, seed: int = 1) -> FastFullGameEnv:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=seed)
    env.run.blind_kind = BlindKind.BOSS
    env.boss_key = boss_key
    env.step(SELECT_BLIND_ACTION)
    return env


def test_boss_required_score_uses_rule_score_mult() -> None:
    wall = _boss_env("bl_wall")
    assert wall.run.required_score == 300 * 4

    needle = _boss_env("bl_needle")
    assert needle.run.required_score == 300 * 1

    vessel = _boss_env("bl_final_vessel")
    assert vessel.run.required_score == 300 * 6


def test_needle_and_water_limit_hands_and_discards() -> None:
    needle = _boss_env("bl_needle")
    assert needle.hands_remaining == 1

    water = _boss_env("bl_water")
    assert water.discards_remaining == 0

    hook = _boss_env("bl_hook")
    assert hook.discards_remaining == max(0, hook.run.discards - 2)


def test_manacle_shrinks_round_hand_size() -> None:
    env = _boss_env("bl_manacle")
    assert env.round_hand_size == env.run.hand_size - 1
    assert len(env.run.hand) == env.round_hand_size


def test_psychic_blocks_small_plays() -> None:
    env = _boss_env("bl_psychic")
    hand = tuple(env.run.hand)

    assert env.score_hand_mask(hand, 0b1).total == 0
    assert env.score_hand_mask(hand, 0b11111).total > 0


def test_mouth_locks_first_hand_kind() -> None:
    env = _boss_env("bl_mouth")
    env.run.hand = [
        _card(0, 3),
        _card(1, 3),
        _card(0, 5),
        _card(1, 7),
        _card(2, 9),
        _card(3, 10),
        _card(0, 11),
        _card(2, 2),
    ]
    pair_score = env.score_hand_mask(tuple(env.run.hand), 0b11)
    assert pair_score.kind == PAIR
    assert pair_score.total > 0

    env.step(0b11)

    assert env.first_hand_kind_this_round == PAIR
    high_card = env.score_hand_mask(tuple(env.run.hand), 0b1)
    if high_card.kind == HIGH_CARD:
        assert high_card.total == 0


def test_club_debuffs_club_card_chips() -> None:
    env = _boss_env("bl_club")
    club_ace = _card(2, 12)
    spade_ace = _card(0, 12)
    env.run.hand = [club_ace, spade_ace] + env.run.hand[2:]

    club_score = env.score_hand_mask(tuple(env.run.hand), 0b1)
    spade_score = env.score_hand_mask(tuple(env.run.hand), 0b10)

    assert spade_score.total - club_score.total > 0


def test_flint_halves_base_chips_and_mult() -> None:
    env = _boss_env("bl_flint")
    plain = FastFullGameEnv(deck_key="b_red")
    plain.reset(seed=1)
    plain.step(SELECT_BLIND_ACTION)
    hand = tuple(plain.run.hand)
    env.run.hand = list(hand)

    flint_score = env.score_hand_mask(hand, 0b11111)
    plain_score = plain.score_hand_mask(hand, 0b11111)

    assert flint_score.total < plain_score.total


def test_tooth_charges_per_played_card() -> None:
    env = _boss_env("bl_tooth")
    env.run.money = 10

    env.step(0b11111)

    assert env.run.money == 5


def test_arm_downlevels_played_hand() -> None:
    env = _boss_env("bl_arm")
    env.hand_levels[PAIR] = 3
    env.run.hand = [
        _card(0, 3),
        _card(1, 3),
        _card(0, 5),
        _card(1, 7),
        _card(2, 9),
        _card(3, 10),
        _card(0, 11),
        _card(2, 2),
    ]

    env.step(0b11)

    assert env.hand_levels[PAIR] == 2


def test_boss_selection_is_deterministic_and_ante_aware() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=5)
    first = env.boss_key
    env.reset(seed=5)
    assert env.boss_key == first
    rule = BLIND_RULES[first]
    assert rule.boss and not rule.showdown
    assert (rule.boss_min_ante or 1) <= 1

    env.run.ante = 8
    env._select_boss_for_ante()
    assert BLIND_RULES[env.boss_key].showdown


def test_unmodeled_boss_effects_is_explicit() -> None:
    assert "bl_house" in UNMODELED_BOSS_EFFECTS
    for key in UNMODELED_BOSS_EFFECTS:
        assert key in BLIND_RULES
