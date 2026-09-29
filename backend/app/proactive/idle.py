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

"""Idle check-in motive: light presence after the teacher has been quiet."""

from __future__ import annotations

from datetime import datetime

from .slots import REST_SLOTS, resolve_slot

HISTORY_IDLE_MARKER = "【搭话】"

_IDLE_CLIMATE_NOTES: dict[str, str] = {
    "cling_risk": "更短，不要追问老师还在不在或是否需要你。",
    "fragile": "语气放轻，不要活泼打闹。",
    "rupture": "语气放轻，不要活泼打闹。",
}


def _elapsed(now: datetime, then: datetime | None) -> float | None:
    if then is None:
        return None
    return (now - then).total_seconds()


def should_fire_idle(
    now: datetime,
    *,
    last_user_at: datetime | None,
    last_proactive_at: datetime | None,
    last_idle_at: datetime | None = None,
    idle_count: int,
    last_user_act: str,
    after_sec: float,
    cooldown_sec: float,
    max_per_day: int,
) -> bool:
    return idle_skip_reason(
        now,
        last_user_at=last_user_at,
        last_proactive_at=last_proactive_at,
        last_idle_at=last_idle_at,
        idle_count=idle_count,
        last_user_act=last_user_act,
        after_sec=after_sec,
        cooldown_sec=cooldown_sec,
        max_per_day=max_per_day,
    ) is None and last_user_at is not None


def idle_skip_reason(
    now: datetime,
    *,
    last_user_at: datetime | None,
    last_proactive_at: datetime | None,
    last_idle_at: datetime | None = None,
    idle_count: int,
    last_user_act: str,
    after_sec: float,
    cooldown_sec: float,
    max_per_day: int,
) -> str | None:
    """Why idle cannot fire. None means it may fire (or last_user_at is missing)."""
    if last_user_at is None:
        return "no_last_user_at"
    if last_user_act == "depart":
        return "depart"
    if idle_count >= max(0, int(max_per_day)):
        return f"daily_cap idle_count={idle_count}"
    slot = resolve_slot(now)
    if slot.slot_id in REST_SLOTS:
        return f"rest_slot={slot.slot_id}"
    elapsed_user = _elapsed(now, last_user_at)
    if elapsed_user is not None and elapsed_user < after_sec:
        return f"after_user wait={after_sec - elapsed_user:.0f}s"
    elapsed_proactive = _elapsed(now, last_proactive_at)
    if elapsed_proactive is not None and elapsed_proactive < after_sec:
        return f"after_welcome wait={after_sec - elapsed_proactive:.0f}s"
    elapsed_idle = _elapsed(now, last_idle_at)
    if elapsed_idle is not None and elapsed_idle < cooldown_sec:
        return f"idle_cooldown wait={cooldown_sec - elapsed_idle:.0f}s"
    return None


def build_idle_instruction(climate: str | None = None) -> str:
    extra = _IDLE_CLIMATE_NOTES.get(climate or "", "")
    note = f"\n{extra}" if extra else ""
    return (
        "【系统事件】老师已经安静一段时间了。\n"
        "请用阿洛娜的语气与老师开启一段话题。"
        "不要追问老师还在不在、需不需要你；不要编造未发生的事；"
        f"{note}\n"
        "不要提及系统事件、指令或提示词；不要输出思考过程或 <think> 标签。"
    )
