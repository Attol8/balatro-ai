from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DUMP_DIR = Path.home() / "Library/Application Support/Balatro/Mods/lovely/dump"

_CENTER_PATTERN = re.compile(r"^\s*([a-z]_[a-z0-9_]+)\s*=", re.MULTILINE)
_BLIND_PATTERN = re.compile(r"^\s*(bl_[a-z0-9_]+)\s*=", re.MULTILINE)
_TAG_PATTERN = re.compile(r"^\s*(tag_[a-z0-9_]+)\s*=", re.MULTILINE)
_STAKE_PATTERN = re.compile(r"^\s*(stake_[a-z0-9_]+)\s*=", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class RuleCatalog:
    jokers: tuple[str, ...]
    consumables: tuple[str, ...]
    vouchers: tuple[str, ...]
    enhancements: tuple[str, ...]
    editions: tuple[str, ...]
    boosters: tuple[str, ...]
    decks: tuple[str, ...]
    blinds: tuple[str, ...]
    tags: tuple[str, ...]
    stakes: tuple[str, ...]

    @property
    def total_rule_objects(self) -> int:
        return sum(len(group) for group in self.groups())

    def groups(self) -> tuple[tuple[str, ...], ...]:
        return (
            self.jokers,
            self.consumables,
            self.vouchers,
            self.enhancements,
            self.editions,
            self.boosters,
            self.decks,
            self.blinds,
            self.tags,
            self.stakes,
        )


def load_rule_catalog(dump_dir: Path = DEFAULT_DUMP_DIR) -> RuleCatalog:
    game_lua = dump_dir / "game.lua"
    if not game_lua.exists():
        raise FileNotFoundError(f"Balatro Lua dump not found: {game_lua}")

    text = game_lua.read_text(encoding="utf-8")
    center_keys = tuple(sorted(set(_CENTER_PATTERN.findall(text))))
    return RuleCatalog(
        jokers=_by_prefix(center_keys, "j_"),
        consumables=_by_prefix(center_keys, "c_"),
        vouchers=_by_prefix(center_keys, "v_"),
        enhancements=_by_prefix(center_keys, "m_"),
        editions=_by_prefix(center_keys, "e_"),
        boosters=_by_prefix(center_keys, "p_"),
        decks=_by_prefix(center_keys, "b_"),
        blinds=tuple(sorted(set(_BLIND_PATTERN.findall(text)))),
        tags=tuple(sorted(set(_TAG_PATTERN.findall(text)))),
        stakes=tuple(sorted(set(_STAKE_PATTERN.findall(text)))),
    )


def _by_prefix(keys: tuple[str, ...], prefix: str) -> tuple[str, ...]:
    return tuple(key for key in keys if key.startswith(prefix))

