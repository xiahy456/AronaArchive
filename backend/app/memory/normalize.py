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

"""Normalize hot-slot memory keys (name / color / birthday)."""

from __future__ import annotations

import re
from typing import Any

from ..taxonomy import normalize_memory_category

# Shared color token fragment (no outer group).
COLOR_TOKEN = (
    r"粉(?:色|红)?|粉红|桃红|"
    r"黄(?:色)?|金黄|淡黄|橙黄|"
    r"蓝(?:色)?|天蓝|深蓝|浅蓝|蔚蓝|"
    r"红(?:色)?|朱红|大红|血红|"
    r"绿(?:色)?|草绿|墨绿|浅绿|"
    r"紫(?:色)?|淡紫|深紫|"
    r"白(?:色)?|米白|乳白|"
    r"黑(?:色)?|墨黑|"
    r"灰(?:色)?|银灰|"
    r"橙(?:色)?|橘(?:色)?|桔(?:色)?|"
    r"棕(?:色)?|咖啡(?:色)?|米色|青色"
)

_COLOR_RE = re.compile(COLOR_TOKEN)

_NAME_CONTENT_RE = re.compile(r"老师的名字是|老师叫")
_BIRTHDAY_CONTENT_RE = re.compile(r"老师的生日|生日是")
_COLOR_PREF_CONTENT_RE = re.compile(r"老师(?:比较|更|最)?喜欢|老师不喜欢")


def looks_like_color_preference(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    if not _COLOR_RE.search(text):
        return False
    return bool(_COLOR_PREF_CONTENT_RE.search(text) or "喜欢" in text or "不喜欢" in text)


def normalize_memory_item(item: dict[str, Any]) -> dict[str, Any]:
    """Force stable keys for hot slots; return a shallow-copied item."""
    out = dict(item)
    op = str(out.get("op") or "upsert").lower()
    key = str(out.get("key") or "").strip()
    content = str(out.get("content") or "").strip()
    category = str(out.get("category") or "").strip()

    if op == "delete":
        if key in {"preference_like", "preference_dislike", "favorite_color"} and (
            looks_like_color_preference(content) if content else key == "favorite_color"
        ):
            out["key"] = "preference_color"
        elif content and looks_like_color_preference(content):
            out["key"] = "preference_color"
        return out

    if not content:
        return out

    if _NAME_CONTENT_RE.search(content) or key in {"user_name", "name"}:
        out["key"] = "user_name"
        out["category"] = "profile"
        return out

    if _BIRTHDAY_CONTENT_RE.search(content) or key in {"user_birthday", "birthday"}:
        out["key"] = "user_birthday"
        out["category"] = "profile"
        return out

    if looks_like_color_preference(content) or key in {
        "preference_color",
        "favorite_color",
    }:
        out["key"] = "preference_color"
        out["category"] = "preference"
        return out

    if category:
        out["category"] = normalize_memory_category(category)
    return out
