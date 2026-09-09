"""Offline only. Run with python -m scripts.audit_build_proof."""

import copy
import gzip
import json
import math
from dataclasses import replace
from pathlib import Path

from balatro_ai.game.actions import action_from_data, is_legal
from balatro_ai.game.adapter import _fortune_teller_mult
from balatro_ai.game.codec import public_observation_from_data
from balatro_ai.game.scoring import score_play
from balatro_ai.game.state import PublicJokerRuntime

ROOT = Path(__file__).resolve().parents[1]


def rows(seed, segment):
    with gzip.open(
        ROOT / f"evidence/astra-low-{seed}/segments/{segment}/trajectory.jsonl.gz", "rt"
    ) as f:
        return [json.loads(line) for line in f]


def card_id(card):
    return tuple(
        card[k]
        for k in ("rank", "suit", "enhancement", "seal", "edition", "permanent_bonus", "debuffed")
    )


def probability(n, k, draws):
    return 1 - math.comb(n - k, draws) / math.comb(n, draws)


taf = rows("TAF7DNTX", "04")
before = taf[837]["before"]
alternative_action = action_from_data(
    {"type": "use_consumable", "consumable": 0, "targets": [1, 3]}
)
assert before["consumables"][0]["key"] == "c_death"
assert is_legal(public_observation_from_data(before), alternative_action)
alt = copy.deepcopy(before)
source, target = alt["hand"][1], alt["hand"][3]
assert (source["rank"], source["suit"], source["enhancement"]) == ("Q", "H", None)
assert (target["rank"], target["suit"], target["enhancement"]) == ("J", "S", "GLASS")
for entry in alt["full_deck"]:
    if card_id(entry["card"]) == card_id(source):
        entry["count"] -= 1
    if card_id(entry["card"]) == card_id(target):
        entry["count"] += 1
alt["full_deck"] = [e for e in alt["full_deck"] if e["count"]]
alt["hand"][1] = copy.deepcopy(target)
alt["consumables"].pop(0)
alt["last_tarot_planet"] = "c_death"
# Death transforms an existing card; deck size and Hologram do not increase.
# Both cards are already in hand, so remaining_deck is unchanged.
play = action_from_data(taf[841]["action"])
assert is_legal(public_observation_from_data(alt), play)
baseline = int(score_play(public_observation_from_data(taf[841]["before"]), play.cards)[0])
observed = taf[841]["after"]["round"]["chips"] - taf[841]["before"]["round"]["chips"]
assert baseline == observed == 2853107712
alternative = int(score_play(public_observation_from_data(alt), play.cards)[0])
assert alternative == 1766209536
assert alternative > 600000000
print(
    "Death: legal [1,3] instead of [1,6]; exact baseline parity",
    baseline,
    "alternative",
    alternative,
    "survival margin",
    alternative / 600000000,
)
print(
    "Held copied Glass J is not scored, so no break roll; played Glass J has normal 25% break chance."
)
for i in (837, 924, 928, 948, 960):
    o = taf[i]["before"]

    def counts(zone):
        arr = o[zone]
        return sum(e.get("count", 1) for e in arr), sum(
            e.get("count", 1)
            for e in arr
            if e.get("card", e)["enhancement"] == "GLASS"
            and e.get("card", e)["rank"] in ("J", "Q", "K")
        )

    print(
        "TAF 04:" + str(i),
        "full N,K",
        counts("full_deck"),
        "remaining N,K",
        counts("remaining_deck"),
        "hand N,K",
        counts("hand"),
    )
print(
    "Hypothetical fresh-shuffle access holding the pre-play deck counts fixed: N60, K3 versus K4. Subsequent Glass breaks are not simulated."
)
for d in (8, 28, 33):
    print(d, [probability(60, k, d) for k in (3, 4)])
print("Tooth actual: predeal 1/57; after opening miss 1/49; after all discards miss 1/29.")
print("Next 25-card discard capacity conditional opening miss:", probability(49, 1, 25))
print(
    "Next 15 cards across first three 5-card plays conditional discard miss:",
    probability(29, 1, 15),
)
print("Illustrative future-deck resilience only; NOT an actual counterfactual replay:")
for d in (8, 28, 33, 43):
    print("N57 draws", d, "K1 vs K2", [probability(57, k, d) for k in (1, 2)])

mime = next(x for x in rows("2K9H9HN", "05")[95]["observation"]["shop"] if x["key"] == "j_mime")


def hydrated(data):
    o = public_observation_from_data(data)
    return replace(
        o,
        jokers=tuple(
            replace(
                j,
                runtime=PublicJokerRuntime(
                    current_mult=_fortune_teller_mult({"effect": j.effect_text})
                ),
            )
            if getattr(j, "key", None) == "j_fortune_teller"
            else j
            for j in o.jokers
        ),
    )


for segment in ("05", "06"):
    for i, r in enumerate(rows("2K9H9HN", segment)):
        if (
            r["event"] != "transition"
            or r["action"]["type"] != "play_cards"
            or (segment == "05" and i < 95)
        ):
            continue
        if not any(j.get("key") == "j_cloud_9" for j in r["before"]["jokers"]):
            continue
        a = action_from_data(r["action"])
        base = int(score_play(hydrated(r["before"]), a.cards)[0])
        data = copy.deepcopy(r["before"])
        data["jokers"] = [mime if j["key"] == "j_cloud_9" else j for j in data["jokers"]]
        changed = int(score_play(hydrated(data), a.cards)[0])
        print(
            "Mime static swap",
            segment,
            i,
            "base",
            base,
            "alternative",
            changed,
            "ratio",
            changed / base,
        )
