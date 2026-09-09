"""Offline public-state arithmetic witnesses. No game/model calls.
Run from repository root: python -m scripts.audit_production_proof
Event references printed below are ZERO-BASED JSONL indices.
"""

import gzip
import json
from dataclasses import replace
from fractions import Fraction
from math import comb
from pathlib import Path

from balatro_ai.game.actions import DiscardCards, HandSlot, PlayCards, is_legal
from balatro_ai.game.codec import public_observation_from_data
from balatro_ai.game.scoring import score_play

ROOT = Path(__file__).resolve().parents[1]


def events(relative):
    with gzip.open(ROOT / relative, "rt") as stream:
        return [json.loads(line) for line in stream]


def play(*slots):
    return PlayCards(tuple(HandSlot(slot) for slot in slots))


xv_path = "evidence/astra-round-production-XV2MP8L5/segments/00/trajectory.jsonl.gz"
xv = events(xv_path)
request, response, recorded = xv[451], xv[452], xv[454]
assert request["event"] == "coach_request"
assert response["event"] == "coach_response"
assert recorded["event"] == "transition"
assert recorded["action"] == {"type": "play_cards", "cards": [6]}
obs = public_observation_from_data(recorded["before"])
assert request["observation"] == recorded["before"]
assert [card.rank for card in obs.hand] == ["A", "K", "K", "J", "T", "6", "5"]
assert obs.money == 40
assert obs.round.chips == 0
assert (obs.round.hands_left, obs.round.discards_left) == (4, 2)
blind = next(blind for blind in obs.blinds if blind.status == "CURRENT")
assert (blind.name, blind.score) == ("The Flint", 10000)
assert next(j.runtime.mail_rank for j in obs.jokers if j.key == "j_mail") == "3"
assert sum(row.count for row in obs.remaining_deck) == obs.draw_count == 32
assert sum(row.count for row in obs.remaining_deck if row.card.rank == "3") == 3
assert all(
    row.card.enhancement is None and row.card.edition is None and row.card.seal is None
    for row in obs.remaining_deck
)
assert {j.key for j in obs.jokers} == {"j_fibonacci", "j_stuntman", "j_mail", "j_baron", "j_hack"}
assert all(not j.debuffed for j in obs.jokers)
actual = play(6)
assert is_legal(obs, actual)
actual_score = score_play(obs, actual.cards)[0]
assert actual_score == Fraction(50759, 4)
actual_delta = recorded["after"]["round"]["chips"] - recorded["before"]["round"]["chips"]
assert actual_delta == int(actual_score) == 12689
setup = play(1, 2, 3, 4, 5)
assert is_legal(obs, setup)
setup_score = score_play(obs, setup.cards)[0]
assert setup_score == 3965 < blind.score
# This is a conservative scoring observation, not a simulated hidden draw:
# keep only the preserved A and 5, credit setup chips, and consume one hand.
# Remaining cards are all plain, and Baron is the only held-card effect;
# therefore adding any drawn cards cannot lower the singleton-5 score.
floor_obs = replace(
    obs,
    hand=(obs.hand[0], obs.hand[6]),
    round=replace(obs.round, chips=3965, hands_left=3, hands_played=1),
)
finish = play(1)
assert is_legal(floor_obs, finish)
finish_floor = score_play(floor_obs, finish.cards)[0]
assert finish_floor == 7101
assert setup_score + finish_floor == 11066 > blind.score
# At most three target cards can arrive. Every positive target count fits in
# a single legal discard; retained A/5 are never selected.
three = next(row.card for row in obs.remaining_deck if row.card.rank == "3")
for k in range(1, 4):
    after_setup = replace(floor_obs, hand=floor_obs.hand + (three,) * k)
    discard = DiscardCards(tuple(HandSlot(slot) for slot in range(2, 2 + k)))
    assert is_legal(after_setup, discard)
probs = {k: Fraction(comb(3, k) * comb(29, 5 - k), comb(32, 5)) for k in range(4)}
assert sum(probs.values()) == 1
expected_targets = sum(k * probability for k, probability in probs.items())
assert expected_targets == Fraction(15, 32)
expected_net = 5 * expected_targets - 1
assert expected_net == Fraction(43, 32)
# Actual cashout: $40->$53. Same blind reward and capped interest; one fewer
# unplayed hand costs exactly $1. Mail payouts occur before terminal play.
assert xv[456]["action"] == {"type": "cash_out"}
assert (xv[456]["before"]["money"], xv[456]["after"]["money"]) == (40, 53)

print(
    json.dumps(
        {
            "xv": {
                "path": xv_path,
                "request_index": 451,
                "response_index": 452,
                "transition_index": 454,
                "actual_score": actual_delta,
                "setup_score": int(setup_score),
                "finish_floor": int(finish_floor),
                "total_floor": 11066,
                "expected_mail_dollars": float(5 * expected_targets),
                "lost_hand_cashout_dollars": 1,
                "expected_net_dollars": float(expected_net),
                "probability_at_least_one_target": float(1 - probs[0]),
                "net_cash_distribution": [
                    {
                        "drawn_threes": k,
                        "net_dollars": 5 * k - 1,
                        "probability": float(p),
                        "exact_probability": str(p),
                    }
                    for k, p in probs.items()
                ],
                "limitation": "Public uniform-draw expectation and conservative score bound, not an executed alternate game or proof of downstream score gain.",
            }
        },
        indent=2,
    )
)

taf_path = "evidence/astra-low-TAF7DNTX/segments/04/trajectory.jsonl.gz"
taf = events(taf_path)
summary = []
for request_index, transition_index, expected_actual, expected_prediction, expected_candidate in [
    (945, 948, 770347, 764127, 1192568832),
    (953, 956, 951042624, 951035904, 5275984896),
]:
    req, row = taf[request_index], taf[transition_index]
    assert req["event"] == "coach_request"
    assert row["event"] == "transition"
    observation = public_observation_from_data(row["before"])
    assert req["observation"] == row["before"]
    chosen = play(*row["action"]["cards"])
    candidate = req["analysis"]["play_candidates"][0]
    advised = play(*candidate["action"]["cards"])
    assert is_legal(observation, chosen) and is_legal(observation, advised)
    prediction = score_play(observation, chosen.cards)[0]
    actual_delta = row["after"]["round"]["chips"] - row["before"]["round"]["chips"]
    assert actual_delta == expected_actual
    assert prediction == expected_prediction
    assert candidate["estimated_score"] == expected_candidate
    assert score_play(observation, advised.cards)[0] == expected_candidate
    assert chosen != advised
    summary.append(
        {
            "request_index": request_index,
            "transition_index": transition_index,
            "historical_candidate_field": "analysis.play_candidates[0]",
            "chosen": row["action"],
            "actual_score": actual_delta,
            "chosen_scorer_prediction": int(prediction),
            "historical_advised_action": candidate["action"],
            "historical_advised_score": expected_candidate,
            "interpretation": "Historical model did not apply already available higher-scoring advice; candidate score remains an offline approximation.",
        }
    )
print(json.dumps({"taf": {"path": taf_path, "evidence": summary}}, indent=2))
print("All assertions passed.")
