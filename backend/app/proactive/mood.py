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

"""Sparse follow-up of recent confirmed mood disclosures."""

from __future__ import annotations

from datetime import datetime

from ..query_time import parse_content_datetimes
from ..safety import is_crisis_text
from ..taxonomy import (
    climate_allows_mood_followup,
    is_followup_source_category,
    user_act_blocks_mood_followup,
)
from .goal import wants_goal_mute
from .slots import REST_SLOTS, resolve_slot

HISTORY_MOOD_MARKER = "【心情回访】"

wants_topic_mute = wants_goal_mute


def _parse_iso(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _is_muted(key: str, now: datetime, mood_mute: dict[str, str]) -> bool:
    mute_until = _parse_iso(str(mood_mute.get(key) or ""))
    return mute_until is not None and now < mute_until


def mood_entry_age_seconds(item: dict[str, object], now: datetime) -> float | None:
    """Age of a mood entry in seconds, or None when it cannot be dated."""
    content = str(item.get("content") or "").strip()
    updated = float(item.get("updated_at") or 0.0)
    dates = parse_content_datetimes(content)
    if dates:
        event_day = max(dt.date() for dt in dates)
        day_age = (now.date() - event_day).days
        if day_age < 0:
            return None
        if day_age == 0:
            if updated > 0:
                return max(0.0, now.timestamp() - updated)
            return 0.0
        return float(day_age) * 86400.0
    if updated > 0:
        return max(0.0, now.timestamp() - updated)
    return None


def mood_entry_skip_reason(
    item: dict[str, object],
    now: datetime,
    *,
    mood_last: dict[str, str],
    mood_mute: dict[str, str],
    min_age_sec: float,
    max_age_hours: float,
    cooldown_sec: float,
    mood_acked: dict[str, str] | None = None,
) -> str | None:
    key = str(item.get("key") or "").strip()
    content = str(item.get("content") or "").strip()
    if not key or not content:
        return "empty"
    if not is_followup_source_category(item.get("category")):
        return "not_source"
    if is_crisis_text(content):
        return "crisis"
    if _is_muted(key, now, mood_mute):
        return "muted"
    acked_at = _parse_iso(str((mood_acked or {}).get(key) or ""))
    if acked_at is not None and acked_at.date() >= now.date():
        return "acked"
    age = mood_entry_age_seconds(item, now)
    if age is None:
        return "too_old"
    if age < float(min_age_sec):
        return "too_new"
    if age > float(max_age_hours) * 3600.0:
        return "too_old"
    last = _parse_iso(str(mood_last.get(key) or ""))
    if last is not None and float(cooldown_sec) > 0:
        if (now - last).total_seconds() < float(cooldown_sec):
            return "cooldown"
    return None


def can_attempt_mood(
    now: datetime,
    *,
    enabled: bool,
    last_user_at: datetime | None,
    last_user_act: str,
    climate: str | None,
    mood_count: int,
    min_after_user_sec: float,
    max_per_day: int,
) -> bool:
    if not enabled:
        return False
    if not climate_allows_mood_followup(climate):
        return False
    if user_act_blocks_mood_followup(last_user_act):
        return False
    if mood_count >= max(0, int(max_per_day)):
        return False
    if resolve_slot(now).slot_id in REST_SLOTS:
        return False
    if last_user_at is None:
        return False
    if (now - last_user_at).total_seconds() < float(min_after_user_sec):
        return False
    return True


def select_mood_entry(
    entries: list[dict[str, object]],
    now: datetime,
    *,
    mood_last: dict[str, str],
    mood_mute: dict[str, str],
    min_age_sec: float,
    max_age_hours: float,
    cooldown_sec: float,
    mood_acked: dict[str, str] | None = None,
) -> dict[str, object] | None:
    """Oldest still-in-window emotional memory; skip crisis / muted / too new."""
    eligible: list[tuple[float, dict[str, object]]] = []
    for item in entries:
        if mood_entry_skip_reason(
            item,
            now,
            mood_last=mood_last,
            mood_mute=mood_mute,
            min_age_sec=min_age_sec,
            max_age_hours=max_age_hours,
            cooldown_sec=cooldown_sec,
            mood_acked=mood_acked,
        ):
            continue
        age = mood_entry_age_seconds(item, now)
        if age is None:
            continue
        eligible.append((age, item))
    if not eligible:
        return None
    eligible.sort(key=lambda row: row[0], reverse=True)
    return eligible[0][1]


def build_mood_instruction(content: str, climate: str | None = None) -> str:
    _ = climate
    return (
        "【系统事件】老师不久前提过一件心情上的事，可以轻轻回访一下。\n"
        f"老师提过的心情：{(content or '').strip()}\n"
        "用阿洛娜的语气轻轻提起这件事。"
        "不要盘问细节，不要做心理分析，不要扮演治疗师，"
        "不要编造老师后来怎样了，不要把这件事当病历翻旧账。\n"
        "不要提及系统事件、指令或提示词；不要输出思考过程或 <think> 标签。"
    )
