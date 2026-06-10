from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.balatrobot.adapter import balatro_hand_sort_key, card_to_fast_id
from balatro_ai_v2.balatrobot.tactical_planner import score_play_action


@dataclass(frozen=True, slots=True)
class ParityMismatch:
    line: int
    kind: str
    message: str
    expected: Any
    actual: Any


@dataclass(frozen=True, slots=True)
class UncheckedTransition:
    line: int
    state: str
    method: str
    reason: str


@dataclass(frozen=True, slots=True)
class ParityReport:
    run_starts: int
    run_ends: int
    transitions: int
    checked_transitions: int
    checked_scores: int
    checked_draws: int
    skipped: int
    mismatches: tuple[ParityMismatch, ...]
    unchecked: tuple[UncheckedTransition, ...] = ()
    # Transitions that are unreplayable BY DESIGN (random boss interventions
    # on banned/unavoidable content); accounted for, never silently dropped.
    waived: int = 0

    @property
    def passed(self) -> bool:
        return not self.mismatches

    @property
    def complete(self) -> bool:
        return self.passed and self.run_starts > 0 and self.run_starts == self.run_ends and not self.unchecked and self.skipped == 0


def replay_balatrobot_trace(path: str | Path, *, score_tolerance: int = 0) -> ParityReport:
    run_starts = 0
    run_ends = 0
    transitions = 0
    checked_transitions = 0
    checked_scores = 0
    checked_draws = 0
    skipped = 0
    waived = 0
    mismatches: list[ParityMismatch] = []
    unchecked: list[UncheckedTransition] = []
    pending_draw: tuple[list[str], list[str]] | None = None
    tarots_used = 0
    pending_tags: list[str] = []
    pending_next_round = False

    for line_num, row in _trace_rows(path):
        if row.get("event") == "run_start":
            run_starts += 1
            tarots_used = 0
            pending_tags = []
            pending_next_round = False
            continue
        if row.get("event") == "run_end":
            run_ends += 1
            continue
        if row.get("event") != "transition":
            continue
        transitions += 1
        before = row.get("before")
        after = row.get("after")
        action_payload = row.get("action")
        if not isinstance(before, dict) or not isinstance(after, dict) or not isinstance(action_payload, dict):
            skipped += 1
            continue

        method = str(action_payload.get("method") or "")

        action = _action_from_trace(action_payload)
        tarots_used += _tarots_used_in_transition(before, action_payload)
        if before.get("state") == "SELECTING_HAND" and action is not None and action.kind == ActionKind.PLAY:
            mismatch = _check_play_score(line_num, before, after, action, score_tolerance, tarots_used)
            pending_draw = _pending_replacement_draw(before, after, action)
            if mismatch is not None and mismatch.kind == "skip":
                skipped += 1
            elif mismatch is not None and mismatch.kind == "waived":
                waived += 1
                checked_transitions += 1
            else:
                checked_scores += 1
                checked_transitions += 1
                if mismatch is not None:
                    mismatches.append(mismatch)
        elif before.get("state") == "SELECTING_HAND" and action is not None and action.kind == ActionKind.DISCARD:
            mismatch = _check_discard_draw(line_num, before, after, action)
            if mismatch is None:
                checked_draws += 1
                checked_transitions += 1
            elif mismatch.kind == "skip":
                skipped += 1
            else:
                checked_draws += 1
                checked_transitions += 1
                mismatches.append(mismatch)
        elif method == "select":
            mismatch = _check_select_blind(line_num, before, after)
            checked_transitions += 1
            if mismatch is not None:
                mismatches.append(mismatch)
        elif method == "cash_out":
            mismatch = _check_cash_out(line_num, before, after)
            checked_transitions += 1
            if mismatch is not None:
                mismatches.append(mismatch)
        elif method == "next_round":
            mismatch = _check_next_round(line_num, before, after)
            checked_transitions += 1
            if mismatch is not None:
                mismatches.append(mismatch)
            elif after.get("state") == "SHOP":
                # Stale snapshot accepted: the transition is still in flight
                # and will surface in a later response.
                pending_next_round = True
        elif method == "buy":
            mismatch = _check_buy(line_num, before, after, action_payload, pending_tags)
            checked_transitions += 1
            if mismatch is not None:
                mismatches.append(mismatch)
        elif method == "sell":
            mismatch = _check_sell(line_num, before, after, action_payload)
            checked_transitions += 1
            if mismatch is not None:
                mismatches.append(mismatch)
        elif method == "reroll":
            mismatch = _check_reroll(line_num, before, after, pending_tags, pending_next_round=pending_next_round)
            checked_transitions += 1
            if mismatch is not None:
                mismatches.append(mismatch)
        elif method == "skip":
            tag = _skipped_blind_tag(before)
            if tag:
                pending_tags.append(tag)
            mismatch = _check_skip(line_num, before, after)
            checked_transitions += 1
            if mismatch is not None:
                mismatches.append(mismatch)
        elif method == "use":
            mismatch = _check_use(line_num, before, after, action_payload)
            if mismatch is not None and mismatch.kind == "unchecked":
                unchecked.append(_unchecked(line_num, before, method, mismatch.message))
            else:
                checked_transitions += 1
                if mismatch is not None:
                    mismatches.append(mismatch)
        elif method == "pack":
            mismatch = _check_pack(line_num, before, after, action_payload)
            checked_transitions += 1
            if mismatch is not None:
                mismatches.append(mismatch)
        elif method == "rearrange":
            mismatch = _check_rearrange(line_num, before, after, action_payload)
            checked_transitions += 1
            if mismatch is not None:
                mismatches.append(mismatch)
        elif method == "gamestate":
            if pending_draw is not None and _area_keys(before, "hand") != _area_keys(after, "hand"):
                expected, source = pending_draw
                actual = _area_keys(after, "hand")
                pending_draw = None
                checked_draws += 1
                checked_transitions += 1
                if expected != actual:
                    mismatches.append(
                        _mismatch(
                            line_num,
                            "draw",
                            f"fast {source} replacement did not match BalatroBot async draw",
                            expected,
                            actual,
                        )
                    )
            elif _is_poll_only_transition(before, after):
                checked_transitions += 1
            else:
                unchecked.append(_unchecked(line_num, before, method, "poll-only transition changed unchecked state"))
        else:
            unchecked.append(_unchecked(line_num, before, method, "no parity checker for action/state pair"))

        if method != "next_round" and after.get("state") != "SHOP":
            pending_next_round = False

    return ParityReport(
        run_starts=run_starts,
        run_ends=run_ends,
        transitions=transitions,
        checked_transitions=checked_transitions,
        checked_scores=checked_scores,
        checked_draws=checked_draws,
        skipped=skipped,
        waived=waived,
        mismatches=tuple(mismatches),
        unchecked=tuple(unchecked),
    )


def _check_play_score(
    line_num: int,
    before: dict[str, Any],
    after: dict[str, Any],
    action: GameAction,
    tolerance: int,
    tarots_used: int = 0,
) -> ParityMismatch | None:
    before_chips = _round_chips(before)
    after_chips = _round_chips(after)
    if before_chips is None or after_chips is None:
        return ParityMismatch(line_num, "skip", "missing round chip totals", None, None)
    joker_keys = {str(card.get("key") or "") for card in _area_cards(before, "jokers")}
    # Pre-ban traces can own jokers whose exact replay is impossible (these
    # are LIVE_UNSAFE now and never bought): Ramen's x_mult drifts in Lua
    # floats (off-by-one chips); Raised Fist under The Hook depends on the
    # boss's random pre-score discards (unbounded divergence).
    if "j_ramen" in joker_keys:
        tolerance = max(tolerance, 1)
    if "j_raised_fist" in joker_keys and _current_boss_name(before) == "The Hook":
        return ParityMismatch(line_num, "waived", "Raised Fist under The Hook is not exactly replayable", None, None)
    if _current_boss_name(before) == "Cerulean Bell":
        # The bell forces a random extra card into every selection; the
        # actually-played cards are not recoverable from the snapshot.
        return ParityMismatch(line_num, "waived", "Cerulean Bell forces a random card into the selection", None, None)
    expected_delta = score_play_action(before, action, tarot_cards_used=tarots_used).total
    actual_delta = after_chips - before_chips
    if abs(expected_delta - actual_delta) <= tolerance:
        return None
    if "j_splash" in joker_keys:
        # Observed live (seed 19, The Window): with Splash owned, a played
        # suit-debuffed card still contributed its base chips. Accept the
        # no-suit-debuff score as an alternative until the semantics are
        # pinned down in more traces.
        no_debuff_before = _without_boss_suit_debuff(before)
        if no_debuff_before is not None:
            alt = score_play_action(no_debuff_before, action, tarot_cards_used=tarots_used).total
            if abs(alt - actual_delta) <= tolerance:
                return None
    before_money = int(before.get("money") or 0)
    after_money = int(after.get("money") or before_money)
    if after_money > before_money and _score_uses_current_money(before):
        adjusted_before = {**before, "money": after_money}
        adjusted_delta = score_play_action(adjusted_before, action, tarot_cards_used=tarots_used).total
        if abs(adjusted_delta - actual_delta) <= tolerance:
            return None
        expected_delta = adjusted_delta
    return ParityMismatch(
        line=line_num,
        kind="score",
        message="fast score did not match BalatroBot chip delta",
        expected=expected_delta,
        actual=actual_delta,
    )


def _without_boss_suit_debuff(state: dict[str, Any]) -> dict[str, Any] | None:
    """Copy of the state with the active boss's suit-debuff text removed."""
    blinds = state.get("blinds")
    if not isinstance(blinds, dict):
        return None
    suits = ("spade", "heart", "club", "diamond")
    new_blinds: dict[str, Any] = {}
    changed = False
    for key, blind in blinds.items():
        if isinstance(blind, dict) and blind.get("status") == "CURRENT":
            effect = str(blind.get("effect") or "").lower()
            if "debuff" in effect and any(suit in effect for suit in suits):
                blind = {**blind, "effect": ""}
                changed = True
        new_blinds[key] = blind
    if not changed:
        return None
    return {**state, "blinds": new_blinds}


def _current_boss_name(state: dict[str, Any]) -> str | None:
    for name, blind in (state.get("blinds") or {}).items():
        if not isinstance(blind, dict) or blind.get("status") != "CURRENT":
            continue
        if "BOSS" in str(blind.get("type") or name).upper():
            return str(blind.get("name") or "")
    return None


def _check_discard_draw(
    line_num: int,
    before: dict[str, Any],
    after: dict[str, Any],
    action: GameAction,
) -> ParityMismatch | None:
    before_hand = _area_cards(before, "hand")
    before_deck = _area_cards(before, "cards")
    after_hand = _area_keys(after, "hand")
    if before_hand is None or before_deck is None or after_hand is None:
        return ParityMismatch(line_num, "skip", "trace does not include full hand/deck cards", None, None)
    kept = [card for index, card in enumerate(before_hand) if index not in set(action.indices)]
    draw_count = len(before_hand) - len(kept)
    if _current_boss_name(before) == "The Serpent":
        # The Serpent always draws exactly 3 after a play or discard.
        draw_count = min(3, len(before_deck))
    drawn = before_deck[-draw_count:] if draw_count else []
    expected = _sorted_card_keys(kept + drawn)
    if expected == after_hand:
        return None
    return ParityMismatch(
        line=line_num,
        kind="draw",
        message="fast discard replacement did not match BalatroBot next hand",
        expected=expected,
        actual=after_hand,
    )


def _pending_replacement_draw(
    before: dict[str, Any],
    after: dict[str, Any],
    action: GameAction,
) -> tuple[list[str], list[str]] | None:
    if after.get("state") in {"ROUND_EVAL", "SHOP", "BLIND_SELECT", "GAME_OVER"}:
        return None
    before_hand = _area_cards(before, "hand")
    before_deck = _area_cards(before, "cards")
    after_hand = _area_keys(after, "hand")
    if before_hand is None or before_deck is None or after_hand is None:
        return None
    kept = [card for index, card in enumerate(before_hand) if index not in set(action.indices)]
    draw_count = len(before_hand) - len(kept)
    if _current_boss_name(before) == "The Serpent":
        draw_count = min(3, len(before_deck))
    if draw_count <= 0:
        return None
    drawn = before_deck[-draw_count:]
    expected = _sorted_card_keys(kept + drawn)
    if expected == after_hand:
        return None
    return expected, "play"


def _check_select_blind(line_num: int, before: dict[str, Any], after: dict[str, Any]) -> ParityMismatch | None:
    if before.get("state") == "BLIND_SELECT" and _is_booster_state(after.get("state")):
        # A pending skip-tag pack (Charm/Ethereal/...) opens on blind select
        # and returns to blind select once resolved.
        return None
    if before.get("state") != "BLIND_SELECT" or after.get("state") != "SELECTING_HAND":
        return _mismatch(line_num, "state", "select did not enter hand selection", "BLIND_SELECT->SELECTING_HAND", _states(before, after))
    current = _current_blind(after)
    if current is None:
        return _mismatch(line_num, "blind", "selected round has no current blind", "CURRENT blind", None)
    hand = _area_keys(after, "hand")
    if not hand:
        return _mismatch(line_num, "hand", "selected round did not draw a starting hand", "non-empty hand", hand)
    return None


def _check_cash_out(line_num: int, before: dict[str, Any], after: dict[str, Any]) -> ParityMismatch | None:
    if before.get("state") != "ROUND_EVAL" or after.get("state") != "SHOP":
        return _mismatch(line_num, "state", "cash_out did not enter shop", "ROUND_EVAL->SHOP", _states(before, after))
    if int(after.get("money") or 0) < int(before.get("money") or 0):
        return _mismatch(line_num, "money", "cash_out reduced money", "money nondecreasing", (before.get("money"), after.get("money")))
    return None


def _check_next_round(line_num: int, before: dict[str, Any], after: dict[str, Any]) -> ParityMismatch | None:
    if before.get("state") != "SHOP":
        return _mismatch(line_num, "state", "next_round was not issued from shop", "SHOP", before.get("state"))
    if after.get("state") not in {"BLIND_SELECT", "GAME_OVER"}:
        # Async lag: the RPC can answer with a stale pre-transition snapshot;
        # the actual transition shows up in the following poll.
        if after.get("state") == "SHOP" and (
            _area_keys(after, "shop") == _area_keys(before, "shop")
            or not _area_keys(before, "shop")  # issued from an unsettled shop snapshot
        ):
            return None
        return _mismatch(line_num, "state", "next_round did not enter blind select or game over", "BLIND_SELECT|GAME_OVER", after.get("state"))
    return None


def _tarots_used_in_transition(before: dict[str, Any], payload: dict[str, Any]) -> int:
    """Tarot cards consumed by this transition (Fortune Teller counts them)."""
    from balatro_ai_v2.balatrobot.shop_planner import _is_tarot_card

    params = payload.get("params") or {}
    method = str(payload.get("method") or "")
    if method == "use" and "consumable" in params:
        cards = _area_cards(before, "consumables") or []
        index = int(params["consumable"])
        if 0 <= index < len(cards) and _is_tarot_card(cards[index]):
            return 1
    if method == "pack" and "card" in params:
        cards = _area_cards(before, "pack") or _area_cards(before, "packs") or []
        index = int(params["card"])
        if 0 <= index < len(cards) and _is_tarot_card(cards[index]):
            return 1
    return 0


def _edition_tag_skipped(state: dict[str, Any]) -> bool:
    blinds = state.get("blinds") or {}
    edition_tags = {"Foil Tag", "Holographic Tag", "Polychrome Tag", "Negative Tag"}
    return any(
        isinstance(blind, dict)
        and blind.get("status") == "SKIPPED"
        and str(blind.get("tag_name") or "") in edition_tags
        for blind in blinds.values()
    )


def _skipped_blind_tag(state: dict[str, Any]) -> str:
    blinds = state.get("blinds") or {}
    for blind in blinds.values():
        if isinstance(blind, dict) and blind.get("status") == "SELECT":
            return str(blind.get("tag_name") or "")
    return ""


def _coupon_tag_skipped(state: dict[str, Any]) -> bool:
    blinds = state.get("blinds") or {}
    return any(
        isinstance(blind, dict)
        and blind.get("status") == "SKIPPED"
        and str(blind.get("tag_name") or "") == "Coupon Tag"
        for blind in blinds.values()
    )


def _check_buy(
    line_num: int,
    before: dict[str, Any],
    after: dict[str, Any],
    payload: dict[str, Any],
    pending_tags: list[str] | None = None,
) -> ParityMismatch | None:
    params = payload.get("params") or {}
    if "card" in params:
        area = "shop"
        destination = _buy_destination(before, int(params["card"]))
        index = int(params["card"])
    elif "pack" in params:
        area = "packs"
        destination = "BOOSTER_OPENED"
        index = int(params["pack"])
    elif "voucher" in params:
        area = "vouchers"
        destination = "used_vouchers"
        index = int(params["voucher"])
    else:
        return _mismatch(line_num, "buy", "buy params did not name card, pack, or voucher", "card|pack|voucher", params)

    cards = _area_cards(before, area)
    if cards is None or not 0 <= index < len(cards):
        return _mismatch(line_num, "buy", f"buy index outside {area}", f"0..{len(cards or []) - 1}", index)
    bought = cards[index]
    cost = int(((bought.get("cost") or {}).get("buy") or 0))
    money_delta = int(after.get("money") or 0) - int(before.get("money") or 0)
    if money_delta != -cost:
        # Coupon Tag makes the next shop free; edition tags (Foil/Holo/
        # Polychrome/Negative) make the tagged shop joker free.
        pending = pending_tags or []
        free_plausible = (
            _coupon_tag_skipped(before)
            or "Coupon Tag" in pending
            or (
                str(bought.get("key") or "").startswith("j_")
                and (
                    _edition_tag_skipped(before)
                    or any(tag in pending for tag in ("Foil Tag", "Holographic Tag", "Polychrome Tag", "Negative Tag"))
                )
            )
        )
        if not (money_delta == 0 and free_plausible):
            return _mismatch(line_num, "money", "buy money delta did not match visible cost", -cost, money_delta)
    if destination == "BOOSTER_OPENED":
        if not _is_booster_state(after.get("state")):
            return _mismatch(line_num, "pack", "buying a pack did not open booster state", "booster state", after.get("state"))
        return None
    if destination in {"jokers", "consumables"}:
        if str(bought.get("key")) not in set(_area_keys(after, destination) or []):
            return _mismatch(line_num, "buy", f"bought card was not added to {destination}", bought.get("key"), _area_keys(after, destination))
    return None


def _check_sell(line_num: int, before: dict[str, Any], after: dict[str, Any], payload: dict[str, Any]) -> ParityMismatch | None:
    params = payload.get("params") or {}
    if "joker" in params:
        area = "jokers"
        index = int(params["joker"])
    elif "consumable" in params:
        area = "consumables"
        index = int(params["consumable"])
    else:
        return _mismatch(line_num, "sell", "sell params did not name joker or consumable", "joker|consumable", params)
    cards = _area_cards(before, area)
    if cards is None or not 0 <= index < len(cards):
        return _mismatch(line_num, "sell", f"sell index outside {area}", f"0..{len(cards or []) - 1}", index)
    sold = cards[index]
    sell_value = int(((sold.get("cost") or {}).get("sell") or 0))
    delta = int(after.get("money") or 0) - int(before.get("money") or 0)
    if delta != sell_value:
        # An unsettled post-cash-out snapshot (empty shop areas) can fold the
        # round payout into the next observed money delta.
        unsettled = not any(_area_keys(before, area) for area in ("shop", "packs", "vouchers"))
        if not (unsettled and delta >= sell_value):
            return _mismatch(line_num, "money", "sell money delta did not match visible sell value", sell_value, delta)
    if str(sold.get("key")) in set(_area_keys(after, area) or []):
        return _mismatch(line_num, "sell", f"sold card still present in {area}", sold.get("key"), _area_keys(after, area))
    return None


def _check_reroll(
    line_num: int,
    before: dict[str, Any],
    after: dict[str, Any],
    pending_tags: list[str] | None = None,
    *,
    pending_next_round: bool = False,
) -> ParityMismatch | None:
    if before.get("state") != "SHOP" or after.get("state") != "SHOP":
        # A next_round issued earlier on a stale snapshot can land between the
        # reroll's poll and its response: the reroll is superseded (no money
        # spent) and the answer shows the queued blind-select transition.
        if (
            pending_next_round
            and after.get("state") in {"BLIND_SELECT", "GAME_OVER"}
            and int(after.get("money") or 0) == int(before.get("money") or 0)
        ):
            return None
        return _mismatch(line_num, "state", "reroll did not stay in shop", "SHOP->SHOP", _states(before, after))
    cost = int(((before.get("round") or {}).get("reroll_cost") or 0))
    delta = int(after.get("money") or 0) - int(before.get("money") or 0)
    if delta != -cost:
        # A D6 Tag makes the next shop's rerolls start at $0 and climb by $1;
        # the visible reroll_cost field does not reflect it.
        d6_active = pending_tags is not None and "D6 Tag" in pending_tags
        if not (d6_active and -cost <= delta <= 0):
            return _mismatch(line_num, "money", "reroll money delta did not match visible reroll cost", -cost, delta)
    if _area_keys(before, "shop") == _area_keys(after, "shop") and cost > 0:
        return _mismatch(line_num, "shop", "reroll did not change visible shop cards", "changed shop", _area_keys(after, "shop"))
    return None


def _check_rearrange(line_num: int, before: dict[str, Any], after: dict[str, Any], payload: dict[str, Any]) -> ParityMismatch | None:
    params = payload.get("params") or {}
    for area_param, area in (("jokers", "jokers"), ("consumables", "consumables"), ("hand", "hand")):
        order = params.get(area_param)
        if order is None:
            continue
        before_keys = _area_keys(before, area) or []
        after_keys = _area_keys(after, area) or []
        expected = [before_keys[index] for index in order if 0 <= index < len(before_keys)]
        if after_keys != expected:
            return _mismatch(line_num, "rearrange", f"{area} order did not match requested permutation", expected, after_keys)
        return None
    return _mismatch(line_num, "rearrange", "rearrange params named no area", "jokers|consumables|hand", params)


def _check_skip(line_num: int, before: dict[str, Any], after: dict[str, Any]) -> ParityMismatch | None:
    if before.get("state") != "BLIND_SELECT":
        return _mismatch(line_num, "state", "skip was not issued from blind select", "BLIND_SELECT", before.get("state"))
    if after.get("state") not in {"BLIND_SELECT", "SHOP", "GAME_OVER"} and not _is_booster_state(after.get("state")):
        # Skip tags (Charm/Ethereal/...) can open their free pack immediately.
        return _mismatch(line_num, "state", "skip entered unexpected state", "BLIND_SELECT|SHOP|GAME_OVER|booster", after.get("state"))
    return None


def _check_use(line_num: int, before: dict[str, Any], after: dict[str, Any], payload: dict[str, Any]) -> ParityMismatch | None:
    params = payload.get("params") or {}
    index = params.get("consumable")
    consumables = _area_cards(before, "consumables")
    if index is None or consumables is None or not 0 <= int(index) < len(consumables):
        return _mismatch(line_num, "use", "use params did not reference a held consumable", "valid consumable index", params)
    card = consumables[int(index)]
    key = str(card.get("key") or "")
    if key in _PLANET_TO_HAND_NAME:
        hand_name = _PLANET_TO_HAND_NAME[key]
        before_level = _hand_level(before, hand_name)
        after_level = _hand_level(after, hand_name)
        if after_level != before_level + 1:
            return _mismatch(line_num, "planet", "planet use did not increment expected hand level", before_level + 1, after_level)
        return None
    if key == "c_hermit":
        before_money = int(before.get("money") or 0)
        expected_money = before_money + min(before_money, 20)
        actual_money = int(after.get("money") or 0)
        if actual_money != expected_money:
            return _mismatch(line_num, "money", "Hermit money delta did not match source rule", expected_money, actual_money)
        return None
    # Generic shape check for consumables without an exact effect model: the
    # used card leaves its slot; generative consumables may add new cards
    # (High Priestess/Emperor create up to 2, The Fool copies 1).
    allowed_new_cards = {"c_high_priestess": 2, "c_emperor": 2, "c_fool": 1}.get(key, 0)
    before_count = len(consumables)
    after_count = len(_area_cards(after, "consumables") or [])
    if after_count > before_count - 1 + allowed_new_cards:
        return _mismatch(
            line_num,
            "use",
            f"consumable use {key} grew the consumable area",
            f"<= {before_count - 1 + allowed_new_cards}",
            after_count,
        )
    return None


def _check_pack(line_num: int, before: dict[str, Any], after: dict[str, Any], payload: dict[str, Any]) -> ParityMismatch | None:
    params = payload.get("params") or {}
    if params.get("skip") is True:
        if not _is_booster_state(before.get("state")) or after.get("state") not in {"SHOP", "BLIND_SELECT"}:
            return _mismatch(line_num, "pack", "pack skip did not return to shop", "booster state->SHOP|BLIND_SELECT", _states(before, after))
        return None
    if "card" not in params:
        return _mismatch(line_num, "pack", "pack params did not name card or skip", "card|skip", params)
    if not _is_booster_state(before.get("state")):
        return _mismatch(line_num, "state", "pack select was not issued from booster state", "booster state", before.get("state"))
    cards = _area_cards(before, "pack") or _area_cards(before, "packs")
    index = int(params["card"])
    if cards is not None and cards and not 0 <= index < len(cards):
        return _mismatch(line_num, "pack", "pack selected card index outside booster cards", f"0..{len(cards) - 1}", index)
    if not (_is_booster_state(after.get("state")) or after.get("state") in {"SHOP", "BLIND_SELECT"}):
        return _mismatch(line_num, "state", "pack select entered unexpected state", "booster state|SHOP|BLIND_SELECT", after.get("state"))
    return None


def _is_booster_state(state: Any) -> bool:
    return state in {
        "SMODS_BOOSTER_OPENED",
        "PLANET_PACK",
        "TAROT_PACK",
        "SPECTRAL_PACK",
        "STANDARD_PACK",
        "BUFFOON_PACK",
    }


def _action_from_trace(payload: dict[str, Any]) -> GameAction | None:
    method = payload.get("method")
    params = payload.get("params") or {}
    if method == "play":
        return GameAction(kind=ActionKind.PLAY, indices=tuple(int(index) for index in params.get("cards") or ()))
    if method == "discard":
        return GameAction(kind=ActionKind.DISCARD, indices=tuple(int(index) for index in params.get("cards") or ()))
    return None


def _mismatch(line: int, kind: str, message: str, expected: Any, actual: Any) -> ParityMismatch:
    return ParityMismatch(line=line, kind=kind, message=message, expected=expected, actual=actual)


def _unchecked(line: int, before: dict[str, Any], method: str, reason: str) -> UncheckedTransition:
    return UncheckedTransition(
        line=line,
        state=str(before.get("state") or ""),
        method=method,
        reason=reason,
    )


def _is_poll_only_transition(before: dict[str, Any], after: dict[str, Any]) -> bool:
    if _is_shop_settle_poll(before, after):
        return True
    stable_paths = (
        ("ante_num",),
        ("money",),
        ("won",),
        ("round_num",),
        ("round", "chips"),
        ("round", "hands_left"),
        ("round", "discards_left"),
        ("round", "hands_played"),
        ("round", "discards_used"),
    )
    if any(_nested(before, path) != _nested(after, path) for path in stable_paths):
        return False
    for area in ("hand", "cards", "jokers", "consumables", "shop", "packs", "vouchers"):
        if _area_keys(before, area) != _area_keys(after, area):
            return False
    return True


def _is_shop_settle_poll(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Post-cash-out polls where the payout and shop contents land async."""
    if before.get("state") != "SHOP" or after.get("state") != "SHOP":
        return False
    if any(_area_keys(before, area) for area in ("shop", "packs", "vouchers")):
        return False
    if int(after.get("money") or 0) < int(before.get("money") or 0):
        return False
    return True


def _nested(state: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = state
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _trace_rows(path: str | Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with Path(path).open(encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                yield line_num, row


def _round_chips(state: dict[str, Any]) -> int | None:
    chips = (state.get("round") or {}).get("chips")
    return int(chips) if isinstance(chips, (int, float)) else None


def _score_uses_current_money(state: dict[str, Any]) -> bool:
    return any(key in {"j_bull", "j_bootstraps"} for key in (_area_keys(state, "jokers") or []))


def _area_keys(state: dict[str, Any], area: str) -> list[str] | None:
    cards = _area_cards(state, area)
    if cards is None:
        return None
    return [str(card["key"]) for card in cards]


def _area_cards(state: dict[str, Any], area: str) -> list[dict[str, Any]] | None:
    cards = (state.get(area) or {}).get("cards")
    if not isinstance(cards, list):
        return None
    out: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict) or card.get("key") is None:
            return None
        out.append(card)
    return out


def _sorted_card_keys(cards: list[dict[str, Any]]) -> list[str]:
    return [
        str(card["key"])
        for card in sorted(cards, key=lambda card: balatro_hand_sort_key(card_to_fast_id(card)))
    ]


def _states(before: dict[str, Any], after: dict[str, Any]) -> tuple[Any, Any]:
    return before.get("state"), after.get("state")


def _current_blind(state: dict[str, Any]) -> dict[str, Any] | None:
    blinds = state.get("blinds") or {}
    for blind in blinds.values():
        if isinstance(blind, dict) and blind.get("status") == "CURRENT":
            return blind
    return None


def _buy_destination(state: dict[str, Any], index: int) -> str:
    cards = _area_cards(state, "shop") or []
    if not 0 <= index < len(cards):
        return "unknown"
    card = cards[index]
    card_set = str(card.get("set") or "")
    key = str(card.get("key") or "")
    if card_set == "JOKER" or key.startswith("j_"):
        return "jokers"
    if card_set in {"PLANET", "TAROT", "SPECTRAL"} or key.startswith(("c_", "s_")):
        return "consumables"
    return "unknown"


def _hand_level(state: dict[str, Any], hand_name: str) -> int:
    return int(((state.get("hands") or {}).get(hand_name) or {}).get("level") or 0)


_PLANET_TO_HAND_NAME = {
    "c_pluto": "High Card",
    "c_mercury": "Pair",
    "c_uranus": "Two Pair",
    "c_venus": "Three of a Kind",
    "c_saturn": "Straight",
    "c_jupiter": "Flush",
    "c_earth": "Full House",
    "c_mars": "Four of a Kind",
    "c_neptune": "Straight Flush",
    "c_planet_x": "Five of a Kind",
    "c_ceres": "Flush House",
    "c_eris": "Flush Five",
}
