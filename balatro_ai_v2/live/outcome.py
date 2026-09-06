"""Confirm run victories without trusting Balatro's premature won flag."""

from balatro_ai_v2.live.observation import numeric


def normalize_outcome(raw: dict, *, previously_won: bool = False) -> dict:
    """Return a copy with an earned victory flag and retain the reported flag.

    The installed state_events.lua sets G.GAME.won before checking game_over
    at the final boss. Thus an Ante-8 boss loss can report won=true. Successful
    boss completion advances the displayed ante before the settled ROUND_EVAL.
    Persist an already witnessed victory through subsequent endless states.
    """
    result = dict(raw)
    reported = raw.get("won") is True
    confirmed = previously_won or (reported and numeric(raw.get("ante_num")) > 8)
    result["reported_won"] = reported
    result["won"] = confirmed
    return result
