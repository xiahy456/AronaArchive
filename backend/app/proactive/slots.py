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

"""Local-time slots for proactive welcome greetings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

SlotId = Literal[
    "late_night",
    "morning",
    "forenoon",
    "noon",
    "afternoon",
    "evening",
    "night",
]

SLOT_LABELS: dict[SlotId, str] = {
    "late_night": "凌晨",
    "morning": "早上",
    "forenoon": "上午",
    "noon": "中午",
    "afternoon": "下午",
    "evening": "晚上",
    "night": "深夜",
}

# Slots where first greeting should remind the teacher to rest.
REST_SLOTS: frozenset[SlotId] = frozenset({"late_night", "night"})


@dataclass(frozen=True)
class ResolvedSlot:
    slot_id: SlotId
    label: str
    date_key: str  # YYYY-MM-DD in local time


def resolve_slot(now: datetime | None = None) -> ResolvedSlot:
    """Map local datetime to a welcome time slot."""
    dt = now or datetime.now()
    hour = dt.hour
    if 0 <= hour < 5:
        slot_id: SlotId = "late_night"
    elif hour < 9:
        slot_id = "morning"
    elif hour < 12:
        slot_id = "forenoon"
    elif hour < 14:
        slot_id = "noon"
    elif hour < 18:
        slot_id = "afternoon"
    elif hour < 23:
        slot_id = "evening"
    else:
        slot_id = "night"
    return ResolvedSlot(
        slot_id=slot_id,
        label=SLOT_LABELS[slot_id],
        date_key=dt.strftime("%Y-%m-%d"),
    )
