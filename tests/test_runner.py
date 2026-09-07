import json
from copy import deepcopy

import pytest

from balatro_ai.runner import Limits, public_state, run_game, validate_response
from tests.game.state_factory import item_card, shop_area, state


class Game:
    def __init__(self, *, fail=False, victory=True, profile="all_unlocked", active=False):
        self.raw = state()
        self.raw.update(deck="RED", stake="WHITE")
        self.started = False
        self.fail, self.victory, self.profile, self.active = fail, victory, profile, active
        self.calls = []

    def rpc(self, method, params=None):
        self.calls.append(method)
        if method == "health":
            return {"profile_mode": self.profile}
        if method == "gamestate":
            return deepcopy(self.raw) if self.started or self.active else {"state": "MENU"}
        if method == "start":
            self.started = True
            return deepcopy(self.raw)
        if self.fail:
            raise RuntimeError("uncertain action")
        self.raw["ante_num"] = 9 if self.victory else 8
        self.raw["won"] = True
        self.raw["state"] = "ROUND_EVAL" if self.victory else "GAME_OVER"
        return deepcopy(self.raw)


class Coach:
    def __init__(self, *, stale=False, timeout=False):
        self.packets = []
        self.stale, self.timeout = stale, timeout

    def choose(self, packet, timeout):
        self.packets.append(packet)
        if self.timeout:
            raise TimeoutError("fake coach timeout")
        return {
            "request_id": "stale" if self.stale else packet["request_id"],
            "action_json": '{"type":"select_blind"}',
            "plan": "Grow safely.",
        }


class ShopGame:
    """Fake BalatroBot that applies shop mutations, so chains meet fresh state."""

    def __init__(self, *, money=20, shop=None, rerolls=(), reroll_cost=5):
        self.raw = state("SHOP")
        self.raw.update(deck="RED", stake="WHITE", money=money)
        self.raw["round"]["reroll_cost"] = reroll_cost
        self.raw["shop"] = shop_area(
            [item_card("c_pluto", card_id=40, kind="PLANET", buy=3)] if shop is None else shop
        )
        self.raw["vouchers"] = shop_area([])
        self.raw["packs"] = shop_area([])
        self.rerolls = [list(offer) for offer in rerolls]
        self.started = False
        self.calls = []

    def rpc(self, method, params=None):
        self.calls.append(method)
        if method == "health":
            return {"profile_mode": "all_unlocked"}
        if method == "gamestate":
            return deepcopy(self.raw) if self.started else {"state": "MENU"}
        if method == "start":
            self.started = True
            return deepcopy(self.raw)
        getattr(self, f"_{method}")(params or {})
        return deepcopy(self.raw)

    def _buy(self, params):
        card = self.raw["shop"]["cards"].pop(params["card"])
        self.raw["shop"]["count"] -= 1
        self.raw["money"] -= card["cost"]["buy"]
        if params.get("mode") != "use":
            area = "jokers" if card["set"] == "JOKER" else "consumables"
            self.raw[area]["cards"].append(card)
            self.raw[area]["count"] += 1

    def _use(self, params):
        self.raw["consumables"]["cards"].pop(params["consumable"])
        self.raw["consumables"]["count"] -= 1

    def _reroll(self, params):
        self.raw["money"] -= self.raw["round"]["reroll_cost"]
        offer = self.rerolls.pop(0) if self.rerolls else []
        self.raw["shop"] = shop_area(offer)

    def _next_round(self, params):
        self.raw["state"] = "GAME_OVER"


class ScriptedCoach:
    """Reply with the scripted response for each request; repeat the last one."""

    def __init__(self, *replies):
        self.replies, self.packets = list(replies), []

    def choose(self, packet, timeout):
        self.packets.append(packet)
        reply = self.replies[min(len(self.packets) - 1, len(self.replies) - 1)]
        return {"request_id": packet["request_id"], "plan": "Stay solvent.", **reply}


def transitions(run):
    rows = [json.loads(line) for line in (run / "trajectory.jsonl").read_text().splitlines()]
    return [row for row in rows if row["event"] == "transition"]


def buy(key, mode="store"):
    return json.dumps({"type": "buy_shop_card", "card": {"key": key}, "mode": mode})


LEAVE = '{"type":"leave_shop"}'
REROLL = '{"type":"reroll_shop"}'


@pytest.fixture(autouse=True)
def no_poll_delay(monkeypatch):
    monkeypatch.setattr("balatro_ai.runner.time.sleep", lambda _: None)
    # Fake games must not contend with a real player in another process.
    monkeypatch.setattr("balatro_ai.runner.fcntl.flock", lambda *_: None)


def test_complete_loop_and_public_boundary(tmp_path):
    game, coach = Game(), Coach()
    result = run_game(game, coach, tmp_path / "run")
    assert result["status"] == "won" and result["ante_reached"] == 9
    assert result["decisions"] == result["coach_requests"] == 1
    assert result["forced_actions"] == 0 and result["followup_actions"] == 0
    packet = json.dumps(coach.packets)
    assert "TEST-SEED" not in packet
    assert "seed" not in coach.packets[0]["observation"]
    assert json.loads((tmp_path / "run/result.json").read_text()) == result
    trace = [
        json.loads(line) for line in (tmp_path / "run/trajectory.jsonl").read_text().splitlines()
    ]
    assert [t["event"] for t in trace] == [
        "rpc_attempt",
        "coach_request",
        "coach_response",
        "rpc_attempt",
        "transition",
    ]


@pytest.mark.parametrize("stale,timeout", [(True, False), (False, True)])
def test_bad_coach_never_mutates(tmp_path, stale, timeout):
    game = Game()
    result = run_game(game, Coach(stale=stale, timeout=timeout), tmp_path / "run")
    assert result["status"] in {"error", "stopped"}
    assert "select" not in game.calls
    assert result["decisions"] == 0


def test_uncertain_mutation_not_retried(tmp_path):
    game = Game(fail=True)
    result = run_game(game, Coach(), tmp_path / "run")
    assert result["status"] == "error"
    assert game.calls.count("select") == 1


def test_premature_won_flag_is_loss(tmp_path):
    result = run_game(Game(victory=False), Coach(), tmp_path / "run")
    assert result["status"] == "lost" and not result["won"]


@pytest.mark.parametrize("kwargs", [{"profile": "normal"}, {"active": True}])
def test_preflight_does_not_start_existing_or_wrong_game(tmp_path, kwargs):
    game = Game(**kwargs)
    result = run_game(game, Coach(), tmp_path / "run")
    assert result["status"] == "error" and "start" not in game.calls


def test_limits_and_no_automatic_strategy(tmp_path):
    game = Game()

    def unchanged(method, params=None):
        if method == "select":
            game.calls.append(method)
            return deepcopy(game.raw)
        return Game.rpc(game, method, params)

    game.rpc = unchanged
    result = run_game(game, Coach(), tmp_path / "run", limits=Limits(max_calls=1))
    assert result["reason"] == "coach_call_limit"
    assert game.calls.count("select") == 1


def test_validation_rejects_extra_action_fields_and_illegal_action():
    obs = public_state(state())
    for action in ({"type": "select_blind", "extra": 1}, {"type": "play_cards", "cards": [0]}):
        with pytest.raises(ValueError):
            validate_response(
                {"request_id": "a", "action_json": json.dumps(action), "plan": ""}, "a", obs
            )


def test_output_not_overwritten(tmp_path):
    with pytest.raises(FileExistsError):
        run_game(Game(), Coach(), tmp_path)


def test_invalid_limits():
    for kwargs in ({"seconds": float("nan")}, {"call_seconds": 0}, {"max_calls": False}):
        with pytest.raises(ValueError):
            Limits(**kwargs)


def test_auth_failure_precedes_game_start(tmp_path):
    class Unauthenticated(Coach):
        def preflight(self, timeout):
            assert 0 < timeout <= 10
            raise RuntimeError("ChatGPT login required")

    game = Game()
    result = run_game(game, Unauthenticated(), tmp_path / "run")
    assert result["status"] == "error"
    assert "start" not in game.calls


def test_cashout_is_only_automatic_move(tmp_path):
    game = Game()
    game.raw["state"] = "ROUND_EVAL"
    coach = Coach()
    result = run_game(game, coach, tmp_path / "run")
    assert result["status"] == "won"
    assert not coach.packets and result["coach_requests"] == 0
    assert game.calls.count("cash_out") == 1


def test_expired_budget_never_starts_game(tmp_path, monkeypatch):
    ticks = iter([0, 2, 3, 4, 5, 6, 7])
    monkeypatch.setattr("balatro_ai.runner.time.monotonic", lambda: next(ticks))
    game = Game()
    result = run_game(game, Coach(), tmp_path / "run", limits=Limits(seconds=1))
    assert result["status"] == "stopped" and "start" not in game.calls


def test_rpc_timeout_uses_remaining_game_budget(monkeypatch):
    from balatro_ai.client import BalatroBotClient
    from balatro_ai.runner import game_rpc

    seen = []

    def post(self, payload):
        seen.append(self.timeout)
        return {"result": {}}

    monkeypatch.setattr(BalatroBotClient, "_http_post", post)
    monkeypatch.setattr("balatro_ai.runner.time.monotonic", lambda: 10)
    assert game_rpc(BalatroBotClient(), "gamestate", None, 10.25) == {}
    assert seen == [0.25]


def test_explicit_continuation_never_restarts_or_replays(tmp_path):
    from balatro_ai.runner import Continuation

    game = Game(active=True)
    current = public_state(game.raw)
    saved = Continuation(current, "Retained plan", (), 3, 4, 10, 20, "previous-run")
    result = run_game(
        game, Coach(), tmp_path / "continued", seed=game.raw["seed"], continuation=saved
    )
    assert result["status"] == "won"
    assert "start" not in game.calls
    assert game.calls.count("select") == 1
    assert result["decisions"] == 5 and result["coach_requests"] == 4
    assert result["seconds"] >= 10


def test_continuation_rejects_changed_game_before_mutation(tmp_path):
    from balatro_ai.runner import Continuation

    game = Game(active=True)
    saved = Continuation(public_state(game.raw), "", (), 0, 0, 0, 0, "previous-run")
    game.raw["money"] += 1
    result = run_game(
        game, Coach(), tmp_path / "continued", seed=game.raw["seed"], continuation=saved
    )
    assert result["status"] == "error"
    assert "start" not in game.calls and "select" not in game.calls


def test_invalid_action_is_corrected_before_any_game_mutation(tmp_path):
    class Correcting(Coach):
        def choose(self, packet, timeout):
            response = super().choose(packet, timeout)
            if len(self.packets) == 1:
                response["action_json"] = '{"type":"play_cards","cards":[0]}'
            else:
                assert packet["validation_feedback"]["error"] == "coach selected an illegal action"
            return response

    game = Game()
    result = run_game(game, Correcting(), tmp_path / "run")
    assert result["status"] == "won" and result["coach_requests"] == 2
    assert game.calls.count("select") == 1 and "play" not in game.calls


def test_unchanged_plan_preserves_full_strategy_and_recovery_log(tmp_path):
    class SamePlan(Coach):
        def choose(self, packet, timeout):
            response = super().choose(packet, timeout)
            if len(self.packets) == 1:
                response["plan"] = "Keep the whole strategy."
            else:
                assert packet["plan"] == "Keep the whole strategy."
                response["plan"] = "="
            return response

    game = Game()

    def rpc(method, params=None):
        if method == "select" and game.calls.count("select") == 0:
            game.calls.append(method)
            return deepcopy(game.raw)
        return Game.rpc(game, method, params)

    game.rpc = rpc
    result = run_game(game, SamePlan(), tmp_path / "run")
    assert result["status"] == "won"
    rows = [
        json.loads(line) for line in (tmp_path / "run/trajectory.jsonl").read_text().splitlines()
    ]
    replies = [r for r in rows if r["event"] == "coach_response"]
    assert replies[-1]["plan_unchanged"] is True
    assert replies[-1]["response"]["plan"] == "Keep the whole strategy."


def test_endless_continues_past_ante_eight_and_records_later_loss(tmp_path):
    game = Game(active=True)
    game.raw.update(ante_num=9, won=True, state="ROUND_EVAL")
    from balatro_ai.runner import Continuation

    saved = Continuation(public_state(game.raw), "Keep scaling.", (), 0, 0, 0, 0, "win")

    def rpc(method, params=None):
        if method == "cash_out":
            game.calls.append(method)
            game.raw["state"] = "GAME_OVER"
            return deepcopy(game.raw)
        return Game.rpc(game, method, params)

    game.rpc = rpc
    result = run_game(
        game, Coach(), tmp_path / "endless", seed=game.raw["seed"], continuation=saved, endless=True
    )
    assert game.calls.count("cash_out") == 1
    assert result["status"] == "lost" and result["reason"] == "endless_game_over"
    assert result["ante_8_cleared"] is True and result["won"] is True


def test_only_legal_move_is_forced_without_a_coach_call(tmp_path):
    game = Game()
    game.raw["blinds"]["small"]["status"] = "DEFEATED"
    game.raw["blinds"]["big"]["status"] = "DEFEATED"
    game.raw["blinds"]["boss"]["status"] = "SELECT"
    coach = Coach()
    result = run_game(game, coach, tmp_path / "run")
    assert result["status"] == "won"
    assert not coach.packets and result["coach_requests"] == 0
    assert result["forced_actions"] == 1 and result["decisions"] == 1
    assert game.calls.count("select") == 1
    assert [row["source"] for row in transitions(tmp_path / "run")] == ["forced"]


def test_selectable_small_blind_still_asks_the_coach(tmp_path):
    game, coach = Game(), Coach()
    result = run_game(game, coach, tmp_path / "run")
    assert len(coach.packets) == 1 and result["forced_actions"] == 0


def test_one_reply_buys_uses_and_leaves_the_shop(tmp_path):
    game = ShopGame()
    coach = ScriptedCoach(
        {
            "action_json": '{"type":"buy_shop_card","card":0,"mode":"store"}',
            "then": [
                {
                    "action_json": '{"type":"use_consumable","consumable":{"key":"c_pluto"}'
                    ',"targets":[]}'
                },
                {"action_json": LEAVE},
            ],
        }
    )
    result = run_game(game, coach, tmp_path / "run")
    assert len(coach.packets) == 1 and result["coach_requests"] == 1
    assert result["followup_actions"] == 2 and result["decisions"] == 3
    assert game.calls.count("buy") == game.calls.count("use") == 1
    assert [row["source"] for row in transitions(tmp_path / "run")] == [
        "coach",
        "coach_followup",
        "coach_followup",
    ]


def test_missing_key_stops_the_chain_and_is_reported(tmp_path):
    game = ShopGame()
    coach = ScriptedCoach(
        {
            "action_json": '{"type":"buy_shop_card","card":0,"mode":"store"}',
            "then": [
                {
                    "action_json": '{"type":"use_consumable","consumable":{"key":"c_pluto"}'
                    ',"targets":[]}'
                },
                {"action_json": buy("c_mars")},
                {"action_json": LEAVE},
            ],
        },
        {"action_json": LEAVE},
    )
    result = run_game(game, coach, tmp_path / "run")
    assert result["status"] == "lost" and result["followup_actions"] == 1
    assert len(coach.packets) == 2 and result["coach_requests"] == 2
    chain = coach.packets[1]["recent_outcomes"][-1]["chain"]
    assert "1 follow-up actions ran" in chain
    assert "chain stopped: buy_shop_card key c_mars not in shop" in chain
    assert coach.packets[1]["recent_outcomes"][-1]["source"] == "coach_followup"


def test_ambiguous_key_stops_the_chain(tmp_path):
    twins = [
        item_card("c_pluto", card_id=41, kind="PLANET", buy=3),
        item_card("c_pluto", card_id=42, kind="PLANET", buy=3),
    ]
    game = ShopGame(rerolls=[twins])
    coach = ScriptedCoach(
        {"action_json": REROLL, "then": [{"action_json": buy("c_pluto")}]},
        {"action_json": LEAVE},
    )
    result = run_game(game, coach, tmp_path / "run")
    assert result["followup_actions"] == 0 and "buy" not in game.calls
    assert "is ambiguous in shop" in coach.packets[1]["recent_outcomes"][-1]["chain"]


def test_reroll_chain_stops_on_a_wanted_key(tmp_path):
    game = ShopGame(
        money=40,
        rerolls=[
            [item_card("j_jolly", card_id=50, kind="JOKER", buy=4)],
            [item_card("j_blueprint", card_id=51, kind="JOKER", buy=10)],
        ],
    )
    coach = ScriptedCoach(
        {
            "action_json": REROLL,
            "then": [
                {
                    "action_json": REROLL,
                    "repeat": 4,
                    "until": {"shop_has_any": ["j_blueprint", "j_baron"], "money_at_least": None},
                }
            ],
        },
        {"action_json": LEAVE},
    )
    result = run_game(game, coach, tmp_path / "run")
    assert game.calls.count("reroll") == 2 and result["followup_actions"] == 1
    assert (
        "chain stopped: the shop offers j_blueprint"
        in (coach.packets[1]["recent_outcomes"][-1]["chain"])
    )


def test_reroll_chain_stops_on_the_money_floor(tmp_path):
    offers = [
        [item_card(key, card_id=60 + index, kind="JOKER", buy=4)]
        for index, key in enumerate(("j_jolly", "j_zany", "j_mad", "j_crazy", "j_droll"))
    ]
    game = ShopGame(money=30, rerolls=offers)
    coach = ScriptedCoach(
        {
            "action_json": REROLL,
            "then": [
                {
                    "action_json": REROLL,
                    "repeat": 4,
                    "until": {"shop_has_any": None, "money_at_least": 12},
                }
            ],
        },
        {"action_json": LEAVE},
    )
    result = run_game(game, coach, tmp_path / "run")
    assert game.calls.count("reroll") == 3 and result["followup_actions"] == 2
    assert "money below 12" in coach.packets[1]["recent_outcomes"][-1]["chain"]


def test_reroll_chain_stops_when_the_repeat_budget_ends(tmp_path):
    offers = [
        [item_card(key, card_id=70 + index, kind="JOKER", buy=4)]
        for index, key in enumerate(("j_jolly", "j_zany", "j_mad"))
    ]
    game = ShopGame(money=40, rerolls=offers)
    coach = ScriptedCoach(
        {"action_json": REROLL, "then": [{"action_json": REROLL, "repeat": 2}]},
        {"action_json": LEAVE},
    )
    result = run_game(game, coach, tmp_path / "run")
    assert game.calls.count("reroll") == 3 and result["followup_actions"] == 2
    assert coach.packets[1]["recent_outcomes"][-1]["chain"].endswith("chain complete")


def test_action_limit_stops_a_chain_midway(tmp_path):
    game = ShopGame()
    coach = ScriptedCoach(
        {
            "action_json": '{"type":"buy_shop_card","card":0,"mode":"store"}',
            "then": [
                {
                    "action_json": '{"type":"use_consumable","consumable":{"key":"c_pluto"}'
                    ',"targets":[]}'
                },
                {"action_json": LEAVE},
            ],
        }
    )
    result = run_game(game, coach, tmp_path / "run", limits=Limits(max_actions=2))
    assert result["reason"] == "action_limit"
    assert result["decisions"] == 2 and result["followup_actions"] == 1
    assert "next_round" not in game.calls


def test_hand_actions_are_rejected_inside_a_chain(tmp_path):
    game = ShopGame()
    coach = ScriptedCoach(
        {
            "action_json": REROLL,
            "then": [{"action_json": '{"type":"play_cards","cards":[0]}'}],
        },
        {"action_json": LEAVE},
    )
    result = run_game(game, coach, tmp_path / "run")
    assert result["status"] == "lost" and result["followup_actions"] == 0
    assert "reroll" not in game.calls and "play" not in game.calls
    feedback = coach.packets[1]["validation_feedback"]
    assert feedback["error"] == "follow-up actions cannot use hand slots"


def test_replies_without_then_and_repeated_instructions_are_unchanged(tmp_path):
    game = ShopGame(rerolls=[[item_card("j_jolly", card_id=80, kind="JOKER", buy=4)]])
    coach = ScriptedCoach({"action_json": REROLL}, {"action_json": LEAVE})
    result = run_game(game, coach, tmp_path / "run")
    assert result["decisions"] == result["coach_requests"] == 2
    assert result["followup_actions"] == 0 and result["forced_actions"] == 0
    assert coach.packets[0]["instructions"] == coach.packets[1]["instructions"]


def test_chain_contract_is_validated_before_any_mutation():
    obs = public_state(state("SHOP", money=10))
    rejected = [
        [{"action_json": '{"type":"reorder_hand","order":[1,0]}'}],
        [{"action_json": '{"type":"use_consumable","consumable":0,"targets":[0]}'}],
        [{"action_json": LEAVE, "repeat": 2}],
        [{"action_json": REROLL, "repeat": 7}],
        [{"action_json": REROLL, "until": {"unknown": 1}}],
        [{"action_json": buy("c_pluto"), "extra": 1}],
        [{"action_json": '{"type":"buy_pack","pack":{"key":1}}'}],
        [{"action_json": '{"type":"buy_shop_card","card":{"key":"c_pluto"}}'}],
        [{"action_json": REROLL}] * 7,
        "not-a-list",
    ]
    for then in rejected:
        with pytest.raises(ValueError):
            validate_response(
                {"request_id": "a", "action_json": REROLL, "plan": "", "then": then}, "a", obs
            )
    action, plan, followups = validate_response(
        {"request_id": "a", "action_json": REROLL, "plan": "", "then": None}, "a", obs
    )
    assert followups == () and plan == ""


class TimingOutCoach(Coach):
    """Time out on the first ``timeouts`` calls, then answer normally."""

    def __init__(self, timeouts=1):
        super().__init__()
        self.timeouts = timeouts

    def choose(self, packet, timeout):
        self.packets.append(packet)
        if len(self.packets) <= self.timeouts:
            raise TimeoutError("Codex CLI timed out")
        return {
            "request_id": packet["request_id"],
            "action_json": '{"type":"select_blind"}',
            "plan": "Grow safely.",
        }


def test_timed_out_model_call_is_re_asked_with_a_fresh_id(tmp_path):
    game, coach = Game(), TimingOutCoach()
    result = run_game(game, coach, tmp_path / "run")
    assert result["status"] == "won" and result["decisions"] == 1
    assert result["coach_timeouts"] == 1 and result["coach_requests"] == 2
    rows = [
        json.loads(line) for line in (tmp_path / "run/trajectory.jsonl").read_text().splitlines()
    ]
    timeouts = [row for row in rows if row["event"] == "coach_timeout"]
    assert [row["attempt"] for row in timeouts] == [1]
    sent = [row for row in rows if row["event"] == "coach_request"]
    assert len({row["request_id"] for row in sent}) == 2
    assert timeouts[0]["request_id"] == sent[0]["request_id"]
    # The retry re-asks the same decision; only the request id is new.
    assert {key: value for key, value in sent[0].items() if key != "request_id"} == {
        key: value for key, value in sent[1].items() if key != "request_id"
    }


def test_six_coach_timeouts_stop_the_run_without_mutating(tmp_path, monkeypatch):
    monkeypatch.setattr("balatro_ai.runner.COACH_RETRY_PAUSE_SECONDS", 0.0)
    game, coach = Game(), TimingOutCoach(timeouts=9)
    result = run_game(game, coach, tmp_path / "run")
    assert result["status"] == "stopped" and result["reason"] == "Codex CLI timed out"
    assert result["coach_timeouts"] == 6 and result["coach_requests"] == 6
    assert result["decisions"] == 0 and "select" not in game.calls


def test_coach_timeout_is_not_retried_without_run_budget(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("balatro_ai.runner.time.monotonic", lambda: clock[0])

    class Slow(Coach):
        def choose(self, packet, timeout):
            self.packets.append(packet)
            clock[0] += 95
            raise TimeoutError("Codex CLI timed out")

    game, coach = Game(), Slow()
    result = run_game(game, coach, tmp_path / "run", limits=Limits(seconds=100, call_seconds=180))
    assert result["status"] == "stopped" and result["reason"] == "Codex CLI timed out"
    assert result["coach_timeouts"] == 1 and result["coach_requests"] == 1
    assert len(coach.packets) == 1 and "select" not in game.calls
