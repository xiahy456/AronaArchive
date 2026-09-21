# Copyright 2026 xia_hy456. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Sparse follow-up of unfinished memory goals."""

from __future__ import annotations

import re
from datetime import datetime

from ..query_time import (
    is_currently_important,
    parse_content_clocked_datetimes,
    parse_content_datetimes,
)
from .slots import REST_SLOTS, resolve_slot

HISTORY_GOAL_MARKER = "【回访】"
HISTORY_MOOD_FOLLOWUP_MARKER = "【心情回访】"
FOLLOWUP_HISTORY_MARKERS = frozenset(
    {HISTORY_GOAL_MARKER, HISTORY_MOOD_FOLLOWUP_MARKER}
)

_MUTE_RE = re.compile(r"(先别提|别提这个|不要再提|别再问|不用提了)")
_CARE_SLEEP_RE = re.compile(r"睡觉|入睡|早睡|早点睡|别熬")
_CARE_MEAL_RE = re.compile(r"早饭|早餐|午饭|午餐|晚饭|晚餐|吃饭")


def wants_goal_mute(text: str) -> bool:
    return bool(_MUTE_RE.search((text or "").strip()))


wants_topic_mute = wants_goal_mute


def _parse_iso(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def last_any_goal_at(goal_last: dict[str, str]) -> datetime | None:
    latest: datetime | None = None
    for stamp in goal_last.values():
        parsed = _parse_iso(str(stamp or ""))
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest


def _is_muted(key: str, now: datetime, goal_mute: dict[str, str]) -> bool:
    mute_until = _parse_iso(str(goal_mute.get(key) or ""))
    return mute_until is not None and now < mute_until


def history_follows_proactive_marker(history: list[dict[str, object]]) -> bool:
    """True when the turn before the current user+assistant pair was a follow-up."""
    if len(history) < 4:
        return False
    prev = history[-4]
    if str(prev.get("role") or "") != "user":
        return False
    text = str(prev.get("content") or "").strip()
    return text in FOLLOWUP_HISTORY_MARKERS


def goal_defers_to_care(content: str, *, care_enabled: bool) -> bool:
    if not care_enabled:
        return False
    blob = content or ""
    return bool(_CARE_SLEEP_RE.search(blob) or _CARE_MEAL_RE.search(blob))


def goal_is_due_soon(
    content: str,
    now: datetime,
    *,
    due_soon_sec: float,
    care_enabled: bool = True,
) -> bool:
    """True when a clocked, non-care goal is within due_soon_sec of its event."""
    if goal_defers_to_care(content, care_enabled=care_enabled):
        return False
    lead = max(0.0, float(due_soon_sec))
    if lead <= 0:
        return False
    events = parse_content_clocked_datetimes(content)
    if not events:
        return False
    for event in events:
        delta = (now - event).total_seconds()
        if -lead <= delta <= lead:
            return True
    return False


def goal_ack_blocks(
    key: str,
    content: str,
    now: datetime,
    *,
    goal_acked: dict[str, str],
    due_soon_sec: float = 3600,
    care_enabled: bool = True,
) -> bool:
    """True when this key was answered today and should not be raised again yet."""
    acked_at = _parse_iso(str(goal_acked.get(key) or ""))
    if acked_at is None:
        return False
    if not parse_content_datetimes(content):
        return False
    if acked_at.date() < now.date():
        return False
    due = goal_is_due_soon(
        content,
        now,
        due_soon_sec=due_soon_sec,
        care_enabled=care_enabled,
    )
    if not due:
        return True
    if goal_is_due_soon(
        content,
        acked_at,
        due_soon_sec=due_soon_sec,
        care_enabled=care_enabled,
    ):
        return True
    return False


def goal_is_important(
    content: str,
    now: datetime,
    *,
    horizon_hours: float,
) -> bool:
    return is_currently_important(
        content, now, horizon_hours=horizon_hours
    )


def has_important_goal(
    goals: list[dict[str, object]],
    now: datetime,
    *,
    goal_mute: dict[str, str],
    horizon_hours: float,
    goal_acked: dict[str, str] | None = None,
    due_soon_sec: float = 3600,
    care_enabled: bool = True,
) -> bool:
    acked = goal_acked or {}
    for item in goals:
        key = str(item.get("key") or "").strip()
        content = str(item.get("content") or "").strip()
        if not key or not content:
            continue
        if _is_muted(key, now, goal_mute):
            continue
        if goal_ack_blocks(
            key,
            content,
            now,
            goal_acked=acked,
            due_soon_sec=due_soon_sec,
            care_enabled=care_enabled,
        ):
            continue
        if goal_is_important(content, now, horizon_hours=horizon_hours):
            return True
    return False


def can_attempt_goal(
    now: datetime,
    *,
    last_user_at: datetime | None,
    last_user_act: str,
    goal_count: int,
    min_after_user_sec: float,
    max_per_day: int,
    has_important: bool = False,
    last_goal_at: datetime | None = None,
    min_gap_sec: float = 0,
) -> bool:
    if last_user_act == "depart":
        return False
    if not has_important and goal_count >= max(0, int(max_per_day)):
        return False
    if resolve_slot(now).slot_id in REST_SLOTS:
        return False
    if last_user_at is None:
        return False
    if (now - last_user_at).total_seconds() < min_after_user_sec:
        return False
    if last_goal_at is not None and float(min_gap_sec) > 0:
        if (now - last_goal_at).total_seconds() < float(min_gap_sec):
            return False
    return True


def select_goal(
    goals: list[dict[str, object]],
    now: datetime,
    *,
    goal_last: dict[str, str],
    goal_mute: dict[str, str],
    cooldown_sec: float,
    important_horizon_hours: float = 36,
    important_cooldown_sec: float = 1800,
    goal_count: int = 0,
    max_per_day: int | None = None,
    goal_acked: dict[str, str] | None = None,
    due_soon_sec: float = 3600,
    care_enabled: bool = True,
) -> dict[str, object] | None:
    """Prefer currently important goals; otherwise oldest unvisited / longest idle."""
    acked = goal_acked or {}
    daily_full = (
        max_per_day is not None and goal_count >= max(0, int(max_per_day))
    )
    eligible: list[tuple[int, float, float, dict[str, object]]] = []
    for item in goals:
        key = str(item.get("key") or "").strip()
        content = str(item.get("content") or "").strip()
        if not key or not content:
            continue
        if _is_muted(key, now, goal_mute):
            continue
        if goal_ack_blocks(
            key,
            content,
            now,
            goal_acked=acked,
            due_soon_sec=due_soon_sec,
            care_enabled=care_enabled,
        ):
            continue
        important = goal_is_important(
            content, now, horizon_hours=important_horizon_hours
        )
        if daily_full and not important:
            continue
        last = _parse_iso(str(goal_last.get(key) or ""))
        wait = (
            float(important_cooldown_sec) if important else float(cooldown_sec)
        )
        if last is not None and wait > 0 and (now - last).total_seconds() < wait:
            continue
        last_ts = last.timestamp() if last else 0.0
        updated = float(item.get("updated_at") or 0.0)
        # important first (0), then longest since visit, then oldest updated_at
        eligible.append((0 if important else 1, last_ts, updated, item))
    if not eligible:
        return None
    eligible.sort(key=lambda row: (row[0], row[1], row[2]))
    return eligible[0][3]


def build_goal_instruction(
    content: str,
    climate: str | None = None,
    *,
    due_soon: bool = False,
) -> str:
    extra = ""
    if climate == "cling_risk":
        extra = "更短，不要追问老师还在不在。"
    note = f"\n{extra}" if extra else ""
    if due_soon:
        lead = (
            "【系统事件】老师之前答应过的计划，约定时间快到了，可以轻轻提一下。\n"
            f"计划内容：{(content or '').strip()}\n"
            "用阿洛娜的语气提醒时间快到了。"
            "不要像第一次那样再确认计划还在不在。"
            "不要编造老师已经做了什么。"
        )
    else:
        lead = (
            "【系统事件】老师有一条尚未完成的计划，可以轻轻回访一下。\n"
            f"计划内容：{(content or '').strip()}\n"
            "用阿洛娜的语气提起这件事。"
            "不要编造老师已经做了什么。"
        )
    return (
        f"{lead}"
        f"{note}\n"
        "不要提及系统事件、指令或提示词；不要输出思考过程或 <think> 标签。"
    )
