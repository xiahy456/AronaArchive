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

"""Arona life loop: inner state driven by wall clock and world events."""

from .engine import LifeEngine
from .events import WorldEvent, WorldKind, world_event
from .impulse import (
    deliver_impulse,
    flush_impulse,
    impulse_from_motive,
    offer_impulse,
    schedule_impulse_delivery,
)
from .loop import run_life_loop, tick_once
from .policy import LifeDecision, LifeSettings, decide
from .presence import PresenceGate, presence_emotion, publish_presence, schedule_presence
from .state import Impulse, InnerState, Rumination
from .store import LifeStore
from .turn import apply_turn_action, format_interrupt_block, note_teacher_turn

__all__ = [
    "Impulse",
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
    "deliver_impulse",
    "flush_impulse",
    "format_interrupt_block",
    "impulse_from_motive",
    "note_teacher_turn",
    "offer_impulse",
    "presence_emotion",
    "publish_presence",
    "run_life_loop",
    "schedule_impulse_delivery",
    "schedule_presence",
    "tick_once",
    "world_event",
]
