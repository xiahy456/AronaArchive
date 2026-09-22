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
