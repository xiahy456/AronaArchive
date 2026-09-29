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
