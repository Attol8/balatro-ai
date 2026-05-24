import json

from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.balatrobot.parity import replay_balatrobot_trace
from balatro_ai_v2.balatrobot.tactical_planner import score_play_action


def test_replay_trace_passes_when_fast_score_matches_balatrobot_delta(tmp_path) -> None:
    before = _selecting_hand_state(
        [
            _card("S", "A"),
            _card("S", "K"),
            _card("S", "Q"),
            _card("S", "J"),
            _card("S", "T"),
        ],
        chips=0,
    )
    action = GameAction(kind=ActionKind.PLAY, indices=(0, 1, 2, 3, 4))
    after = {**before, "state": "ROUND_EVAL", "round": {**before["round"]}}
    after["round"]["chips"] = score_play_action(before, action).total
    trace_path = tmp_path / "trace.jsonl"
    _write_rows(
        trace_path,
        [
            {
                "event": "transition",
                "before": before,
                "action": {"method": "play", "params": {"cards": [0, 1, 2, 3, 4]}},
                "after": after,
            }
        ],
    )

    report = replay_balatrobot_trace(trace_path)

    assert report.passed
    assert not report.unchecked
    assert report.checked_scores == 1
    assert report.mismatches == ()


def test_replay_trace_reports_score_mismatch(tmp_path) -> None:
    before = _selecting_hand_state([_card("S", "A")], chips=10)
    trace_path = tmp_path / "trace.jsonl"
    _write_rows(
        trace_path,
        [
            {
                "event": "transition",
                "before": before,
                "action": {"method": "play", "params": {"cards": [0]}},
                "after": {**before, "round": {"chips": 11}},
            }
        ],
    )

    report = replay_balatrobot_trace(trace_path)

    assert not report.passed
    assert report.mismatches[0].kind == "score"


def test_score_play_honors_explicit_debuffed_scoring_cards() -> None:
    state = _selecting_hand_state(
        [
            _card("S", "9"),
            _card("C", "9"),
            _card("D", "9"),
            _card("C", "3", debuffed=True),
            _card("D", "3"),
        ],
        chips=0,
    )
    state["money"] = 53
    state["jokers"] = {
        "count": 2,
        "limit": 5,
        "cards": [
            {"key": "j_bull", "set": "JOKER", "value": {"ability": {"extra": 2}}},
            {"key": "j_ride_the_bus", "set": "JOKER", "value": {"ability": {"extra": 1}}},
        ],
    }

    score = score_play_action(state, GameAction(kind=ActionKind.PLAY, indices=(0, 1, 2, 3, 4)))

    assert score.total == 880


def test_score_play_ride_the_bus_uses_current_mult_not_extra() -> None:
    state = _selecting_hand_state([_card("S", "A")], chips=0)
    state["money"] = 33
    state["jokers"] = {
        "count": 3,
        "limit": 5,
        "cards": [
            {"key": "j_bull", "set": "JOKER", "value": {"ability": {"extra": 2}}},
            {"key": "j_scholar", "set": "JOKER", "value": {"ability": {"chips": 20, "mult": 4}}},
            {"key": "j_ride_the_bus", "set": "JOKER", "value": {"ability": {"extra": 1}}},
        ],
    }

    score = score_play_action(state, GameAction(kind=ActionKind.PLAY, indices=(0,)))

    assert score.total == 612


def test_replay_trace_checks_discard_draw_order(tmp_path) -> None:
    before = _selecting_hand_state(
        [_card("S", "A"), _card("H", "2"), _card("D", "3")],
        chips=0,
        deck_cards=[_card("C", "4"), _card("S", "5")],
    )
    after = _selecting_hand_state(
        [_card("S", "A"), _card("S", "5"), _card("D", "3")],
        chips=0,
        deck_cards=[_card("C", "4")],
    )
    trace_path = tmp_path / "trace.jsonl"
    _write_rows(
        trace_path,
        [
            {
                "event": "transition",
                "before": before,
                "action": {"method": "discard", "params": {"cards": [1]}},
                "after": after,
            }
        ],
    )

    report = replay_balatrobot_trace(trace_path)

    assert report.passed
    assert report.checked_draws == 1


def test_replay_trace_reports_unchecked_transitions(tmp_path) -> None:
    before = _selecting_hand_state([_card("S", "A")], chips=0)
    trace_path = tmp_path / "trace.jsonl"
    _write_rows(
        trace_path,
        [
            {
                "event": "transition",
                "before": before,
                "action": {"method": "unknown", "params": {}},
                "after": before,
            }
        ],
    )

    report = replay_balatrobot_trace(trace_path)

    assert report.passed
    assert not report.complete
    assert report.unchecked[0].method == "unknown"


def test_replay_trace_checks_visible_shop_buy(tmp_path) -> None:
    before = _shop_state(
        money=8,
        shop_cards=[
            {"key": "j_joker", "set": "JOKER", "cost": {"buy": 2, "sell": 1}},
        ],
        jokers=[],
    )
    after = _shop_state(
        money=6,
        shop_cards=[],
        jokers=[
            {"key": "j_joker", "set": "JOKER", "cost": {"buy": 2, "sell": 1}},
        ],
    )
    trace_path = tmp_path / "trace.jsonl"
    _write_rows(
        trace_path,
        [
            {
                "event": "transition",
                "before": before,
                "action": {"method": "buy", "params": {"card": 0}},
                "after": after,
            }
        ],
    )

    report = replay_balatrobot_trace(trace_path)

    assert report.passed
    assert report.checked_transitions == 1
    assert not report.unchecked


def test_complete_requires_finished_run(tmp_path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_rows(
        trace_path,
        [
            {"event": "run_start", "state": {"state": "BLIND_SELECT"}},
        ],
    )

    report = replay_balatrobot_trace(trace_path)

    assert report.passed
    assert not report.complete
    assert report.run_starts == 1
    assert report.run_ends == 0


def test_replay_trace_checks_sell_joker(tmp_path) -> None:
    before = _shop_state(
        money=3,
        shop_cards=[],
        jokers=[
            {"key": "j_joker", "set": "JOKER", "cost": {"buy": 2, "sell": 1}},
        ],
    )
    after = _shop_state(money=4, shop_cards=[], jokers=[])
    trace_path = tmp_path / "trace.jsonl"
    _write_rows(
        trace_path,
        [
            {
                "event": "transition",
                "before": before,
                "action": {"method": "sell", "params": {"joker": 0}},
                "after": after,
            }
        ],
    )

    report = replay_balatrobot_trace(trace_path)

    assert report.passed
    assert report.checked_transitions == 1


def test_replay_trace_checks_reroll_money_delta(tmp_path) -> None:
    before = _shop_state(
        money=8,
        shop_cards=[
            {"key": "j_joker", "set": "JOKER", "cost": {"buy": 2, "sell": 1}},
        ],
        jokers=[],
    )
    before["round"] = {"reroll_cost": 5}
    after = _shop_state(
        money=3,
        shop_cards=[
            {"key": "j_half", "set": "JOKER", "cost": {"buy": 5, "sell": 2}},
        ],
        jokers=[],
    )
    after["round"] = {"reroll_cost": 6}
    trace_path = tmp_path / "trace.jsonl"
    _write_rows(
        trace_path,
        [
            {
                "event": "transition",
                "before": before,
                "action": {"method": "reroll", "params": {}},
                "after": after,
            }
        ],
    )

    report = replay_balatrobot_trace(trace_path)

    assert report.passed
    assert report.checked_transitions == 1


def test_replay_trace_checks_skip_state(tmp_path) -> None:
    before = _selecting_hand_state([], chips=0)
    before["state"] = "BLIND_SELECT"
    after = {**before, "state": "BLIND_SELECT"}
    trace_path = tmp_path / "trace.jsonl"
    _write_rows(
        trace_path,
        [
            {
                "event": "transition",
                "before": before,
                "action": {"method": "skip", "params": {}},
                "after": after,
            }
        ],
    )

    report = replay_balatrobot_trace(trace_path)

    assert report.passed
    assert report.checked_transitions == 1


def _write_rows(path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def _selecting_hand_state(
    cards: list[dict],
    *,
    chips: int,
    deck_cards: list[dict] | None = None,
) -> dict:
    return {
        "state": "SELECTING_HAND",
        "round_num": 1,
        "ante_num": 1,
        "money": 4,
        "seed": "1",
        "round": {"hands_left": 4, "discards_left": 3, "chips": chips},
        "hands": {name: {"level": 1} for name in _HAND_NAMES},
        "blinds": {
            "small": {"type": "SMALL", "status": "CURRENT", "score": 300},
            "big": {"type": "BIG", "status": "UPCOMING", "score": 450},
            "boss": {"type": "BOSS", "status": "UPCOMING", "score": 600},
        },
        "jokers": {"count": 0, "limit": 5, "cards": []},
        "cards": {"count": len(deck_cards or []), "limit": 52, "cards": deck_cards or []},
        "hand": {"count": len(cards), "limit": 8, "highlighted_limit": 5, "cards": cards},
    }


def _shop_state(
    *,
    money: int,
    shop_cards: list[dict],
    jokers: list[dict],
) -> dict:
    state = _selecting_hand_state([], chips=0)
    state["state"] = "SHOP"
    state["money"] = money
    state["shop"] = {"count": len(shop_cards), "limit": 2, "cards": shop_cards}
    state["jokers"] = {"count": len(jokers), "limit": 5, "cards": jokers}
    return state


def _card(suit: str, rank: str, *, debuffed: bool = False) -> dict:
    return {
        "key": f"{suit}_{rank}",
        "value": {"suit": suit, "rank": rank},
        "state": {"debuff": True} if debuffed else {},
        "cost": {"buy": 0, "sell": 0},
    }


_HAND_NAMES = (
    "High Card",
    "Pair",
    "Two Pair",
    "Three of a Kind",
    "Straight",
    "Flush",
    "Full House",
    "Four of a Kind",
    "Straight Flush",
    "Five of a Kind",
    "Flush House",
    "Flush Five",
)
