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

"""Deterministic life policy: update inner state, never speak. No I/O, no LLM."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from ..proactive.slots import REST_SLOTS, resolve_slot
from .events import TEACHER_PRESENCE_KINDS, WorldEvent
from .state import (
    DEFAULT_ACTIVITY,
    DEFAULT_ATTENTION,
    DEFAULT_MOOD,
    Activity,
    Attention,
    InnerState,
    PrivateMood,
)

LifeAction = Literal[
    "continue_activity",
    "shift_activity",
    "speak",
    "glance",
    "emotion_only",
]

# Layer 1 may only return these two.
_LAYER1_ACTIONS: frozenset[str] = frozenset(
    {"continue_activity", "shift_activity"}
)


@dataclass(frozen=True)
class LifeDecision:
    state: InnerState
    action: LifeAction
    next_activity: Activity


@dataclass(frozen=True)
class LifeSettings:
    look_hold_sec: float = 180
    think_hold_sec: float = 120


def _elapsed_sec(start: datetime | None, now: datetime) -> float:
    if start is None:
        return 1e18
    return max(0.0, (now - start).total_seconds())


def _teacher_hold_active(
    state: InnerState, now: datetime, look_hold_sec: float
) -> bool:
    if state.activity != "looking_at_teacher":
        return False
    return _elapsed_sec(state.last_event_at, now) < look_hold_sec


def _in_rest_slot(now: datetime) -> bool:
    return resolve_slot(now).slot_id in REST_SLOTS


def _shift(
    state: InnerState,
    now: datetime,
    *,
    activity: Activity,
    attention: Attention,
    mood: PrivateMood,
    last_event_at: datetime | None | object = None,
    can_hear: bool | None = None,
) -> InnerState:
    """last_event_at None means keep; pass now explicitly to stamp."""
    next_state = state.clone()
    changed_activity = next_state.activity != activity
    next_state.activity = activity
    next_state.attention = attention
    next_state.private_mood = mood
    if changed_activity:
        next_state.activity_since = now
    elif next_state.activity_since is None:
        next_state.activity_since = now
    if last_event_at is not None:
        next_state.last_event_at = last_event_at  # type: ignore[assignment]
    if can_hear is not None:
        next_state.can_hear = can_hear
    return next_state


def _decision(state: InnerState, action: LifeAction) -> LifeDecision:
    if action not in _LAYER1_ACTIONS:
        action = "continue_activity"
    return LifeDecision(
        state=state, action=action, next_activity=state.activity
    )


def _after_teacher_gone(state: InnerState, now: datetime) -> InnerState:
    if _in_rest_slot(now):
        return _shift(
            state,
            now,
            activity="resting",
            attention="diffuse",
            mood="sleepy",
            last_event_at=now,
        )
    if state.has_rumination():
        return _shift(
            state,
            now,
            activity="thinking",
            attention="rumination",
            mood="preoccupied",
            last_event_at=now,
        )
    return _shift(
        state,
        now,
        activity=DEFAULT_ACTIVITY,
        attention=DEFAULT_ATTENTION,
        mood=DEFAULT_MOOD,
        last_event_at=now,
    )


def _release_look(state: InnerState, now: datetime) -> InnerState:
    if state.has_rumination():
        return _shift(
            state,
            now,
            activity="thinking",
            attention="rumination",
            mood="preoccupied",
        )
    return _shift(
        state,
        now,
        activity=DEFAULT_ACTIVITY,
        attention=DEFAULT_ATTENTION,
        mood=DEFAULT_MOOD,
    )


def decide(
    state: InnerState,
    event: WorldEvent,
    *,
    settings: LifeSettings,
    climate: str | None = None,
) -> LifeDecision:
    """Apply one world event. climate is read-only and unused for actions."""
    del climate  # reserved for later layers / logging at the engine
    now = event.at
    kind = event.kind

    if kind in TEACHER_PRESENCE_KINDS:
        mood: PrivateMood = (
            state.private_mood if state.private_mood == "sleepy" else "bright"
        )
        nxt = _shift(
            state,
            now,
            activity="looking_at_teacher",
            attention="teacher",
            mood=mood,
            last_event_at=now,
        )
        return _decision(nxt, "shift_activity")

    if kind == "listen_on":
        nxt = replace(state.clone(), can_hear=True)
        return _decision(nxt, "continue_activity")

    if kind == "listen_off":
        nxt = replace(state.clone(), can_hear=False)
        return _decision(nxt, "continue_activity")

    if kind == "teacher_left":
        nxt = _after_teacher_gone(state, now)
        return _decision(nxt, "shift_activity")

    if kind == "impulse_due":
        return _decision(state.clone(), "continue_activity")

    # clock_tick and any unknown kind: wall-clock decay only
    look_hold = max(0.0, float(settings.look_hold_sec))
    think_hold = max(0.0, float(settings.think_hold_sec))
    hold_active = _teacher_hold_active(state, now, look_hold)
    in_rest = _in_rest_slot(now)

    if hold_active:
        return _decision(state.clone(), "continue_activity")

    if in_rest:
        if state.activity == "resting":
            return _decision(state.clone(), "continue_activity")
        nxt = _shift(
            state,
            now,
            activity="resting",
            attention="diffuse",
            mood="sleepy",
        )
        return _decision(nxt, "shift_activity")

    if state.activity == "resting":
        nxt = _release_look(state, now)
        return _decision(nxt, "shift_activity")

    if state.activity == "looking_at_teacher":
        nxt = _release_look(state, now)
        return _decision(nxt, "shift_activity")

    if state.activity == "thinking":
        if _elapsed_sec(state.activity_since, now) >= think_hold:
            nxt = _shift(
                state,
                now,
                activity=DEFAULT_ACTIVITY,
                attention=DEFAULT_ATTENTION,
                mood=DEFAULT_MOOD,
            )
            return _decision(nxt, "shift_activity")
        return _decision(state.clone(), "continue_activity")

    return _decision(state.clone(), "continue_activity")
