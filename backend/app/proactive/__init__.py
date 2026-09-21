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

"""Proactive companion actions (welcome, idle, care, goal follow-up)."""

from .care import (
    CARE_KINDS,
    CARE_MEMORY_QUERY,
    HISTORY_CARE_MARKER,
    build_care_instruction,
    care_planner_declined,
    care_window_specs,
    in_window,
    should_fire_care,
)
from .festival import (
    HISTORY_FESTIVAL_MARKER,
    FestivalHit,
    build_festival_instruction,
    match_festival,
    needs_rest_followup,
    parse_birthday_md,
)
from .followup import HISTORY_CONTINUE_MARKER, build_continue_instruction
from .mood import (
    HISTORY_MOOD_MARKER,
    build_mood_instruction,
    can_attempt_mood,
    select_mood_entry,
    wants_topic_mute,
)
from .goal import (
    HISTORY_GOAL_MARKER,
    build_goal_instruction,
    can_attempt_goal,
    has_important_goal,
    history_follows_proactive_marker,
    last_any_goal_at,
    select_goal,
    wants_goal_mute,
)
from .hub import ConnectionHub
from .idle import HISTORY_IDLE_MARKER, build_idle_instruction, should_fire_idle
from .loop import (
    TICK_SEC,
    load_birthday_content,
    run_proactive_loop,
    tick_once,
)
from .scheduler import Motive, ProactiveScheduler, ProactiveState
from .slots import REST_SLOTS, SLOT_LABELS, ResolvedSlot, SlotId, resolve_slot
from .welcome import (
    HISTORY_USER_MARKER,
    WELCOME_CLOSING_HINTS,
    WELCOME_CLOSING_QUESTION,
    WELCOME_CLOSING_STATEMENT,
    WELCOME_MEMORY_QUERY,
    WelcomeState,
    build_welcome_instruction,
    pick_welcome_closing_hint,
    resolve_welcome_context,
)

__all__ = [
    "CARE_KINDS",
    "CARE_MEMORY_QUERY",
    "ConnectionHub",
    "HISTORY_CARE_MARKER",
    "HISTORY_CONTINUE_MARKER",
    "HISTORY_FESTIVAL_MARKER",
    "HISTORY_GOAL_MARKER",
    "HISTORY_IDLE_MARKER",
    "HISTORY_MOOD_MARKER",
    "HISTORY_USER_MARKER",
    "FestivalHit",
    "Motive",
    "ProactiveScheduler",
    "ProactiveState",
    "REST_SLOTS",
    "ResolvedSlot",
    "SLOT_LABELS",
    "SlotId",
    "TICK_SEC",
    "WELCOME_CLOSING_HINTS",
    "WELCOME_CLOSING_QUESTION",
    "WELCOME_CLOSING_STATEMENT",
    "WELCOME_MEMORY_QUERY",
    "WelcomeState",
    "build_care_instruction",
    "care_planner_declined",
    "care_window_specs",
    "build_continue_instruction",
    "build_festival_instruction",
    "build_goal_instruction",
    "build_idle_instruction",
    "build_mood_instruction",
    "build_welcome_instruction",
    "can_attempt_goal",
    "can_attempt_mood",
    "has_important_goal",
    "history_follows_proactive_marker",
    "last_any_goal_at",
    "match_festival",
    "needs_rest_followup",
    "parse_birthday_md",
    "pick_welcome_closing_hint",
    "in_window",
    "resolve_slot",
    "resolve_welcome_context",
    "load_birthday_content",
    "run_proactive_loop",
    "select_goal",
    "select_mood_entry",
    "should_fire_care",
    "should_fire_idle",
    "tick_once",
    "wants_goal_mute",
    "wants_topic_mute",
]
