"""Small, deterministic retrieval from reviewed offline decision examples."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

from balatro_ai.game.state import PublicItem, PublicObservation, VisiblePlayingCard


@lru_cache(maxsize=1)
def load_examples() -> tuple[dict, ...]:
    return tuple(json.loads(files("balatro_ai").joinpath("knowledge/decisions.json").read_text()))


def retrieve_examples(observation: PublicObservation) -> list[dict[str, str]]:
    """Match public facts only; sources stay offline, never sent as seed routes."""
    owned = {
        item.key
        for item in (*observation.jokers, *observation.consumables)
        if isinstance(item, PublicItem) and not item.debuffed
    }
    owned.update(observation.used_vouchers)
    offered = {
        item.key
        for item in (*observation.shop, *observation.opened_pack, *observation.vouchers)
        if isinstance(item, PublicItem)
    }
    facts = owned | offered
    for item in (*observation.consumables, *observation.shop, *observation.opened_pack):
        if isinstance(item, PublicItem):
            facts.add(f"kind:{item.kind}")
    for blind in observation.blinds:
        if (
            blind.kind == "BOSS"
            and not blind.disabled
            and blind.status in {"CURRENT", "UPCOMING", "SELECT"}
        ):
            facts.add(f"boss:{blind.name}")
    cards = [card for card in observation.hand if isinstance(card, VisiblePlayingCard)]
    cards.extend(entry.card for entry in observation.full_deck)
    for card in cards:
        for field in ("enhancement", "seal", "rank", "suit"):
            value = getattr(card, field)
            if value is not None and value != "?":
                facts.add(f"{field}:{value}")
    matches = []
    for example in load_examples():
        triggers = set(example["trigger_keys"])
        required = set(example["required_keys"])
        if (
            observation.phase.value not in example["phases"]
            or not triggers.intersection(facts)
            or not required.issubset(facts)
        ):
            continue
        # Prefer decisions about an actual offer, then more specific contexts.
        priority = (
            len(triggers.intersection(offered)),
            len(required),
            len(triggers.intersection(owned)),
        )
        matches.append((priority, example))
    matches.sort(key=lambda pair: (tuple(-n for n in pair[0]), pair[1]["id"]))
    result = []
    families = set()
    for _, example in matches:
        if example["family"] in families:
            continue
        families.add(example["family"])
        result.append({key: example[key] for key in ("id", "situation", "lesson", "reversal")})
        result[-1]["situation"] = "Example: " + result[-1]["situation"]
        if len(result) == 3:
            break
    return result
