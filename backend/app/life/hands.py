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

"""Computer use is an interruptible activity. Teacher barge-in aborts the hands first."""

from __future__ import annotations

import logging
from typing import Any

from .events import world_event
from .presence import schedule_presence

logger = logging.getLogger(__name__)


def teacher_turn_aborts_hands(inflight_kind: str | None) -> bool:
    return inflight_kind == "computer_use"


def begin_hands(state: Any) -> None:
    engine = getattr(state, "life", None)
    if engine is None:
        return
    engine.apply(world_event("hands_on"))
    journal = getattr(state, "journal", None)
    if journal is not None:
        journal.note_inner(
            engine.state,
            arona=getattr(state, "arona_memory", None),
        )
        journal.append("hands", "开始通过什亭之匣操作电脑")
    schedule_presence(state)
    logger.info("life hands on activity=%s", engine.state.activity)


def end_hands(state: Any, *, stopped: bool) -> None:
    engine = getattr(state, "life", None)
    if engine is None or engine.state.activity != "using_computer":
        return
    engine.apply(world_event("hands_off"))
    journal = getattr(state, "journal", None)
    if journal is not None:
        summary = "停下操作电脑" if stopped else "操作电脑结束"
        journal.append("hands", summary)
        journal.note_inner(
            engine.state,
            arona=getattr(state, "arona_memory", None),
        )
    schedule_presence(state)
    logger.info("life hands off stopped=%s activity=%s", stopped, engine.state.activity)
