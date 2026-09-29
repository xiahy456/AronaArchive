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

"""Calendar-based festival greetings (plus teacher birthday)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .slots import REST_SLOTS, resolve_slot

HISTORY_FESTIVAL_MARKER = "【节日】"

# Solar month-day -> (id, display name).
_SOLAR: dict[tuple[int, int], tuple[str, str]] = {
    (1, 1): ("new_year", "元旦"),
    (2, 14): ("valentine", "情人节"),
    (5, 1): ("labor", "劳动节"),
    (6, 1): ("children", "儿童节"),
    (9, 10): ("teacher", "教师节"),
    (10, 1): ("national", "国庆节"),
    (12, 25): ("christmas", "圣诞节"),
}

# Lunar festivals by Gregorian date (no extra dependency).
_LUNAR: dict[tuple[int, int, int], tuple[str, str]] = {
    (2025, 1, 29): ("spring_festival", "春节"),
    (2025, 2, 12): ("lantern", "元宵节"),
    (2025, 5, 31): ("dragon_boat", "端午节"),
    (2025, 10, 6): ("mid_autumn", "中秋节"),
    (2026, 2, 17): ("spring_festival", "春节"),
    (2026, 3, 3): ("lantern", "元宵节"),
    (2026, 6, 19): ("dragon_boat", "端午节"),
    (2026, 9, 25): ("mid_autumn", "中秋节"),
    (2027, 2, 6): ("spring_festival", "春节"),
    (2027, 2, 20): ("lantern", "元宵节"),
    (2027, 6, 9): ("dragon_boat", "端午节"),
    (2027, 9, 15): ("mid_autumn", "中秋节"),
    (2028, 1, 26): ("spring_festival", "春节"),
    (2028, 2, 9): ("lantern", "元宵节"),
    (2028, 5, 28): ("dragon_boat", "端午节"),
    (2028, 10, 3): ("mid_autumn", "中秋节"),
}

_ISO_MD = re.compile(r"(?:(?:\d{4})[-/年.])?(\d{1,2})[-/月.](\d{1,2})")
_CN_MD = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?")


@dataclass(frozen=True)
class FestivalHit:
    id: str
    name: str
    extra_memory: str = ""


def parse_birthday_md(text: str) -> tuple[int, int] | None:
    """Return (month, day) from common birthday strings, or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    cn = _CN_MD.search(raw)
    if cn:
        month, day = int(cn.group(1)), int(cn.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return month, day
    iso = _ISO_MD.search(raw)
    if iso:
        month, day = int(iso.group(1)), int(iso.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return month, day
    return None


def birthday_from_profiles(rows: list[dict[str, object]] | None) -> str:
    for item in rows or []:
        if str(item.get("key") or "").strip() == "user_birthday":
            return str(item.get("content") or "").strip()
    return ""


def match_festival(
    now: datetime,
    birthday_content: str = "",
) -> FestivalHit | None:
    """Pick at most one festival for the local date. Birthday wins."""
    md = parse_birthday_md(birthday_content)
    if md is not None and md == (now.month, now.day):
        return FestivalHit(
            id="birthday",
            name="老师的生日",
            extra_memory=(birthday_content or "").strip(),
        )
    lunar = _LUNAR.get((now.year, now.month, now.day))
    if lunar is not None:
        return FestivalHit(id=lunar[0], name=lunar[1])
    solar = _SOLAR.get((now.month, now.day))
    if solar is not None:
        return FestivalHit(id=solar[0], name=solar[1])
    return None


def needs_rest_followup(now: datetime) -> bool:
    return resolve_slot(now).slot_id in REST_SLOTS


def build_festival_instruction(
    hit: FestivalHit,
    climate: str | None = None,
) -> str:
    extra = ""
    if climate == "cling_risk":
        extra = "更短，不要追问老师还在不在，也不要索取确认。"
    elif climate in {"fragile", "rupture"}:
        extra = "语气放轻、简短，不要活泼催促或开玩笑。"
    note = f"\n{extra}" if extra else ""
    if hit.id == "birthday":
        intent = "今天是老师的生日。请轻轻祝老师生日快乐，温暖短句。"
    else:
        intent = f"今天是{hit.name}。请轻轻提起这个日子并送上祝福，温暖短句。"
    return (
        "【系统事件】今天有一个值得轻轻提起的日子。\n"
        f"{intent}\n"
        f"{note}\n"
        "用阿洛娜的语气主动开口。"
        "不要提及系统事件、指令或提示词；不要输出思考过程或 <think> 标签。"
    )
