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

"""World events that enter the life loop. Teacher text is not stored here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

WorldKind = Literal[
    "teacher_spoke",
    "teacher_transcript",
    "teacher_touched",
    "teacher_interrupt",
    "teacher_arrived",
    "teacher_left",
    "listen_on",
    "listen_off",
    "clock_tick",
    "impulse_due",
    "hands_on",
    "hands_off",
]

# 老师出现在场：说话、听写、触摸、上线。听写开关不算。
TEACHER_PRESENCE_KINDS: frozenset[str] = frozenset(
    {
        "teacher_spoke",
        "teacher_transcript",
        "teacher_touched",
        "teacher_arrived",
    }
)

WORLD_KINDS: frozenset[str] = frozenset(
    {
        "teacher_spoke",
        "teacher_transcript",
        "teacher_touched",
        "teacher_interrupt",
        "teacher_arrived",
        "teacher_left",
        "listen_on",
        "listen_off",
        "clock_tick",
        "impulse_due",
        "hands_on",
        "hands_off",
    }
)


@dataclass(frozen=True)
class WorldEvent:
    """Input to the life loop. session_id is log-only."""

    kind: WorldKind
    at: datetime
    session_id: str = ""


def world_event(
    kind: WorldKind,
    *,
    at: datetime | None = None,
    session_id: str = "",
) -> WorldEvent:
    return WorldEvent(kind=kind, at=at or datetime.now(), session_id=session_id)
