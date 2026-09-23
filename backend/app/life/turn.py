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

"""Teacher-turn adapter: snapshot inner state, then apply the world event."""

from __future__ import annotations

import logging
from typing import Any

from .events import WorldKind, world_event
from .presence import schedule_presence
from .state import InnerState

logger = logging.getLogger(__name__)

ACTIVITY_LABELS = {
    "idle_in_classroom": "正在教室发呆",
    "looking_at_teacher": "正在看老师",
    "thinking": "正在想事情",
    "resting": "正在休息",
    "using_computer": "正在通过什亭之匣操作电脑",
}

def format_interrupt_block(state: InnerState | None) -> str:
    """Planner-facing interrupt context. Empty when there is no inner state."""
    if state is None:
        return ""
    label = ACTIVITY_LABELS.get(state.activity, ACTIVITY_LABELS["idle_in_classroom"])
    lines = [f"【阿洛娜此刻】{label}"]
    if state.rumination:
        content = (state.rumination[-1].content or "").strip()
        if content:
            lines.append(f"【未出口的心事】{content}")
    return "\n".join(lines)


def note_teacher_turn(
    app_state: Any,
    kind: WorldKind,
    *,
    session_id: str = "",
) -> InnerState | None:
    """Clone inner state, apply the world event, push presence. Returns the snapshot."""
    engine = getattr(app_state, "life", None)
    if engine is None:
        return None
    from .impulse import expire_stale_care

    expire_stale_care(app_state)
    snapshot = engine.state.clone()
    engine.apply(world_event(kind, session_id=session_id))
    schedule_presence(app_state)
    if kind == "teacher_interrupt":
        journal = getattr(app_state, "journal", None)
        if journal is not None:
            journal.note_teacher_opened()
    return snapshot


def apply_turn_action(
    app_state: Any,
    action: str,
    emotion: str = "normal",
) -> None:
    """Commit the loop-recognized action after Planner / relationship choice."""
    engine = getattr(app_state, "life", None)
    activity = engine.state.activity if engine is not None else "-"
    logger.info("life turn_action=%s activity=%s emotion=%s", action, activity, emotion)
    if action == "emotion_only":
        schedule_presence(
            app_state,
            emotion_override=emotion,
            ignore_busy=True,
        )
        return
    if action == "continue_activity":
        schedule_presence(app_state)
