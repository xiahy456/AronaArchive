# AronaArchive - 自循环 AI
# Copyright (C) 2026 xia_hy456
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""QQ stickers loaded from data/knowledge/emoji/*.json."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import BACKEND_DIR

logger = logging.getLogger(__name__)

_FIELDS = ("emoji_package_id", "emoji_id", "key", "summary", "description")
EMOJI_DIR = BACKEND_DIR / "data" / "knowledge" / "emoji"


@dataclass(frozen=True)
class EmojiSticker:
    emoji_package_id: str
    emoji_id: str
    key: str
    summary: str
    description: str

    def package_id_value(self) -> int | str:
        raw = self.emoji_package_id.strip()
        try:
            return int(raw)
        except ValueError:
            return raw


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def sticker_from_row(row: object) -> EmojiSticker | None:
    """Skip non-objects and any row with a blank required field."""
    if not isinstance(row, dict):
        return None
    values = {name: _text(row.get(name)) for name in _FIELDS}
    if any(not values[name] for name in _FIELDS):
        return None
    return EmojiSticker(
        emoji_package_id=values["emoji_package_id"],
        emoji_id=values["emoji_id"],
        key=values["key"],
        summary=values["summary"],
        description=values["description"],
    )


def load_emoji_catalog(directory: Path | None = None) -> tuple[EmojiSticker, ...]:
    """Read every JSON array in the directory. The first emoji_id wins."""
    root = directory if directory is not None else EMOJI_DIR
    if not root.is_dir():
        return ()
    found: dict[str, EmojiSticker] = {}
    for path in sorted(root.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("emoji catalog skipped path=%s", path)
            continue
        if not isinstance(raw, list):
            logger.info("emoji catalog skipped non-array path=%s", path)
            continue
        for row in raw:
            sticker = sticker_from_row(row)
            if sticker is None or sticker.emoji_id in found:
                continue
            found[sticker.emoji_id] = sticker
    return tuple(found.values())


_CATALOG: tuple[EmojiSticker, ...] | None = None
_BY_ID: dict[str, EmojiSticker] | None = None


def emoji_catalog() -> tuple[EmojiSticker, ...]:
    global _CATALOG, _BY_ID
    if _CATALOG is None:
        _CATALOG = load_emoji_catalog()
        _BY_ID = {item.emoji_id: item for item in _CATALOG}
    return _CATALOG


def lookup_emoji(emoji_id: str) -> EmojiSticker | None:
    key = (emoji_id or "").strip()
    if not key:
        return None
    emoji_catalog()
    assert _BY_ID is not None
    return _BY_ID.get(key)


def format_emoji_prompt() -> str:
    """description and emoji_id pairs for the planner system prompt."""
    rows = [f"- {item.description}：{item.emoji_id}" for item in emoji_catalog()]
    return "\n".join(rows) if rows else "（无）"
