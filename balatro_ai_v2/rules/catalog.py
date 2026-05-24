from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Mapping

DEFAULT_DUMP_DIR = Path.home() / "Library/Application Support/Balatro/Mods/lovely/dump"

_CENTER_PATTERN = re.compile(r"^\s*([a-z]_[a-z0-9_]+)\s*=", re.MULTILINE)
_BLIND_PATTERN = re.compile(r"^\s*(bl_[a-z0-9_]+)\s*=", re.MULTILINE)
_TAG_PATTERN = re.compile(r"^\s*(tag_[a-z0-9_]+)\s*=", re.MULTILINE)
_STAKE_PATTERN = re.compile(r"^\s*(stake_[a-z0-9_]+)\s*=", re.MULTILINE)
_STRING_FIELD_TEMPLATE = r"\b{field}\s*=\s*(['\"])(.*?)\1"


@dataclass(frozen=True, slots=True)
class SourceRef:
    path: str
    line: int
    reason: str
    snippet: str


@dataclass(frozen=True, slots=True)
class RuleSource:
    key: str
    category: str
    definition: SourceRef
    name: str | None
    set_name: str | None
    effect: str | None
    config_hash: str | None
    behavior_refs: tuple[SourceRef, ...] = ()

    @property
    def source_location(self) -> str:
        return f"{self.definition.path}:{self.definition.line}"


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
    sources: Mapping[str, RuleSource] = field(default_factory=dict)

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
    center_text, center_offset = _named_table_or_full_text(text, "self.P_CENTERS")
    blind_text, blind_offset = _named_table_or_full_text(text, "self.P_BLINDS")
    tag_text, tag_offset = _named_table_or_full_text(text, "self.P_TAGS")
    stake_text, stake_offset = _named_table_or_full_text(text, "self.P_STAKES")
    center_blocks = _find_rule_blocks(
        center_text, _CENTER_PATTERN, source_path="game.lua", source_offset=center_offset, full_text=text
    )
    blind_blocks = _find_rule_blocks(
        blind_text, _BLIND_PATTERN, source_path="game.lua", source_offset=blind_offset, full_text=text
    )
    tag_blocks = _find_rule_blocks(
        tag_text, _TAG_PATTERN, source_path="game.lua", source_offset=tag_offset, full_text=text
    )
    stake_blocks = _find_rule_blocks(
        stake_text, _STAKE_PATTERN, source_path="game.lua", source_offset=stake_offset, full_text=text
    )

    behavior_sources = _load_behavior_sources(dump_dir)
    sources = _build_sources(
        center_blocks | blind_blocks | tag_blocks | stake_blocks,
        behavior_sources=behavior_sources,
    )

    center_keys = tuple(sorted(center_blocks))
    return RuleCatalog(
        jokers=_center_keys(center_keys, sources, fallback_prefix="j_", set_names={"Joker"}),
        consumables=_center_keys(
            center_keys, sources, fallback_prefix="c_", set_names={"Tarot", "Planet", "Spectral"}
        ),
        vouchers=_center_keys(center_keys, sources, fallback_prefix="v_", set_names={"Voucher"}),
        enhancements=_center_keys(center_keys, sources, fallback_prefix="m_", set_names={"Enhanced"}),
        editions=_center_keys(center_keys, sources, fallback_prefix="e_", set_names={"Edition"}),
        boosters=_center_keys(center_keys, sources, fallback_prefix="p_", set_names={"Booster"}),
        decks=_center_keys(center_keys, sources, fallback_prefix="b_", set_names={"Back"}),
        blinds=tuple(sorted(blind_blocks)),
        tags=tuple(sorted(tag_blocks)),
        stakes=tuple(sorted(stake_blocks)),
        sources=sources,
    )


def _by_prefix(keys: tuple[str, ...], prefix: str) -> tuple[str, ...]:
    return tuple(key for key in keys if key.startswith(prefix))


def _center_keys(
    keys: tuple[str, ...],
    sources: Mapping[str, RuleSource],
    *,
    fallback_prefix: str,
    set_names: set[str],
) -> tuple[str, ...]:
    return tuple(
        key
        for key in keys
        if sources[key].set_name in set_names
        or (sources[key].set_name is None and key.startswith(fallback_prefix))
    )


@dataclass(frozen=True, slots=True)
class _RuleBlock:
    key: str
    path: str
    line: int
    text: str


def _named_table_or_full_text(text: str, table_name: str) -> tuple[str, int]:
    match = re.search(rf"\b{re.escape(table_name)}\s*=", text)
    if not match:
        return text, 0
    start = text.find("{", match.end())
    if start == -1:
        return text, 0
    end = _balanced_table_end(text, start)
    if end is None:
        return text, 0
    return text[start:end], start


def _find_rule_blocks(
    text: str,
    pattern: re.Pattern[str],
    *,
    source_path: str,
    source_offset: int,
    full_text: str,
) -> dict[str, _RuleBlock]:
    blocks: dict[str, _RuleBlock] = {}
    for match in pattern.finditer(text):
        key = match.group(1)
        start = text.find("{", match.end())
        if start == -1:
            continue
        end = _balanced_table_end(text, start)
        if end is None:
            continue
        blocks[key] = _RuleBlock(
            key=key,
            path=source_path,
            line=full_text.count("\n", 0, source_offset + match.start(1)) + 1,
            text=text[start:end],
        )
    return blocks


def _balanced_table_end(text: str, start: int) -> int | None:
    depth = 0
    quote: str | None = None
    line_comment = False
    index = start
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char == "-" and next_char == "-":
            line_comment = True
            index += 2
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _load_behavior_sources(dump_dir: Path) -> dict[str, str]:
    paths = [
        "card.lua",
        "blind.lua",
        "tag.lua",
        "back.lua",
        "functions/common_events.lua",
        "functions/state_events.lua",
    ]
    sources: dict[str, str] = {}
    for relative_path in paths:
        path = dump_dir / relative_path
        if path.exists():
            sources[relative_path] = path.read_text(encoding="utf-8")
    return sources


def _build_sources(
    blocks: Mapping[str, _RuleBlock], *, behavior_sources: Mapping[str, str]
) -> dict[str, RuleSource]:
    return {
        key: _source_from_block(block, behavior_sources=behavior_sources)
        for key, block in blocks.items()
    }


def _source_from_block(block: _RuleBlock, *, behavior_sources: Mapping[str, str]) -> RuleSource:
    name = _string_field(block.text, "name")
    set_name = _string_field(block.text, "set")
    return RuleSource(
        key=block.key,
        category=_category_for_key(block.key, set_name=set_name),
        definition=SourceRef(
            path=block.path,
            line=block.line,
            reason="definition",
            snippet=_single_line(block.text),
        ),
        name=name,
        set_name=set_name,
        effect=_string_field(block.text, "effect"),
        config_hash=_config_hash(block.text),
        behavior_refs=_behavior_refs_for_name(name, behavior_sources=behavior_sources),
    )


def _string_field(text: str, field_name: str) -> str | None:
    pattern = re.compile(_STRING_FIELD_TEMPLATE.format(field=re.escape(field_name)))
    match = pattern.search(text)
    return match.group(2) if match else None


def _config_hash(text: str) -> str | None:
    match = re.search(r"\bconfig\s*=", text)
    if not match:
        return None
    start = text.find("{", match.end())
    if start == -1:
        return None
    end = _balanced_table_end(text, start)
    if end is None:
        return None
    config_text = re.sub(r"\s+", " ", text[start:end]).strip()
    return hashlib.sha256(config_text.encode("utf-8")).hexdigest()[:12]


def _behavior_refs_for_name(
    name: str | None, *, behavior_sources: Mapping[str, str]
) -> tuple[SourceRef, ...]:
    if not name:
        return ()
    refs: list[SourceRef] = []
    quoted_name = re.escape(name)
    pattern = re.compile(
        rf"(ability\.name\s*(?:==|~=)\s*['\"]{quoted_name}['\"]|_c\.name\s*==\s*['\"]{quoted_name}['\"])"
    )
    for path, text in behavior_sources.items():
        for line_number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                refs.append(
                    SourceRef(
                        path=path,
                        line=line_number,
                        reason="ability.name branch",
                        snippet=line.strip(),
                    )
                )
    return tuple(refs)


def _category_for_key(key: str, *, set_name: str | None = None) -> str:
    if set_name == "Joker":
        return "jokers"
    if set_name in {"Tarot", "Planet", "Spectral"}:
        return "consumables"
    if set_name == "Voucher":
        return "vouchers"
    if set_name == "Enhanced":
        return "enhancements"
    if set_name == "Edition":
        return "editions"
    if set_name == "Booster":
        return "boosters"
    if set_name == "Back":
        return "decks"
    if key.startswith("j_"):
        return "jokers"
    if key.startswith("c_"):
        return "consumables"
    if key.startswith("v_"):
        return "vouchers"
    if key.startswith("m_"):
        return "enhancements"
    if key.startswith("e_"):
        return "editions"
    if key.startswith("p_"):
        return "boosters"
    if key.startswith("b_"):
        return "decks"
    if key.startswith("bl_"):
        return "blinds"
    if key.startswith("tag_"):
        return "tags"
    if key.startswith("stake_"):
        return "stakes"
    return "unknown"


def _single_line(text: str, *, max_len: int = 160) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."
