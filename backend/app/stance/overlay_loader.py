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

"""Load handwritten stage overlay markdown files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .stance_schema import DEFAULT_STAGE, STAGE_FILES, normalize_stage

_OVERLAY_DIR = Path(__file__).resolve().parent / "overlays"
_REQUIRED = ("口吻", "性格", "语气锚定（仅供语气参考，不是对话模板，不要套用）")


@lru_cache(maxsize=8)
def load_overlay_sections(stage: str) -> dict[str, str]:
    """Return the three stage sections for a committed stage."""
    key = normalize_stage(stage)
    filename = STAGE_FILES[key]
    path = _OVERLAY_DIR / filename
    text = path.read_text(encoding="utf-8")
    sections = _parse_sections(text)
    missing = [name for name in _REQUIRED if name not in sections]
    if missing:
        raise ValueError(f"overlay {filename} missing sections: {', '.join(missing)}")
    return {name: sections[name] for name in _REQUIRED}


def format_overlay_block(stage: str, *, include_anchors: bool = True) -> str:
    sections = load_overlay_sections(stage)
    names = _REQUIRED if include_anchors else ("口吻", "性格")
    parts = [f"## {name}\n{sections[name].rstrip()}" for name in names]
    return "\n\n".join(parts).rstrip() + "\n"


def clear_overlay_cache() -> None:
    load_overlay_sections.cache_clear()


def _parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = ""
    lines: list[str] = []
    for raw in text.splitlines():
        if raw.startswith("## "):
            if current:
                sections[current] = "\n".join(lines).strip()
            current = raw[3:].strip()
            lines = []
            continue
        if current:
            lines.append(raw)
    if current:
        sections[current] = "\n".join(lines).strip()
    return sections


# Touch default stage so import fails early if steady.md is broken.
load_overlay_sections(DEFAULT_STAGE)
