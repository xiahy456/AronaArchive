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

"""Arona life loop: inner state driven by wall clock and world events."""

from .engine import LifeEngine
from .events import WorldEvent, WorldKind, world_event
from .loop import run_life_loop, tick_once
from .policy import LifeDecision, LifeSettings, decide
from .presence import PresenceGate, presence_emotion, publish_presence, schedule_presence
from .state import InnerState, Rumination
from .store import LifeStore
from .turn import apply_turn_action, format_interrupt_block, note_teacher_turn

__all__ = [
    "InnerState",
    "LifeDecision",
    "LifeEngine",
    "LifeSettings",
    "LifeStore",
    "PresenceGate",
    "Rumination",
    "WorldEvent",
    "WorldKind",
    "apply_turn_action",
    "decide",
    "format_interrupt_block",
    "note_teacher_turn",
    "presence_emotion",
    "publish_presence",
    "run_life_loop",
    "schedule_presence",
    "tick_once",
    "world_event",
]
