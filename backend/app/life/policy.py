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

"""Deterministic life policy: update inner state. Speak only from a pending impulse."""

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
ImpulseFollowup = Literal["keep", "drop", "mark_fired", "mark_care"]

# Empty wall-clock ticks may only continue or shift.
_LAYER1_ACTIONS: frozenset[str] = frozenset(
    {"continue_activity", "shift_activity"}
)
_IMPULSE_ACTIONS: frozenset[str] = frozenset(
    {"continue_activity", "shift_activity", "speak", "emotion_only", "glance"}
)
_CARE_KINDS: frozenset[str] = frozenset(
    {"breakfast", "lunch", "dinner", "sleep"}
)
SIMMER_SEC = 30.0


@dataclass(frozen=True)
class LifeDecision:
    state: InnerState
    action: LifeAction
    next_activity: Activity
    impulse_followup: ImpulseFollowup = "keep"
    impulse_kind: str = ""
    impulse_source_id: str = ""
    impulse_due_soon: bool = False


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


def _impulse_meta(state: InnerState) -> tuple[str, str, bool]:
    impulse = state.pending_impulse
    if impulse is None:
        return "", "", False
    return impulse.kind, impulse.source_id, impulse.due_soon


def _decision(
    state: InnerState,
    action: LifeAction,
    *,
    allow_impulse: bool = False,
    followup: ImpulseFollowup = "keep",
    impulse_kind: str = "",
    impulse_source_id: str = "",
    impulse_due_soon: bool = False,
) -> LifeDecision:
    if action == "glance":
        action = "emotion_only"
    allowed = _IMPULSE_ACTIONS if allow_impulse else _LAYER1_ACTIONS
    if action not in allowed:
        action = "continue_activity"
        followup = "keep"
    return LifeDecision(
        state=state,
        action=action,
        next_activity=state.activity,
        impulse_followup=followup,
        impulse_kind=impulse_kind,
        impulse_source_id=impulse_source_id,
        impulse_due_soon=impulse_due_soon,
    )


def _clear_impulse(state: InnerState) -> InnerState:
    nxt = state.clone()
    nxt.pending_impulse = None
    return nxt


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


def _resolve_pending(
    state: InnerState,
    now: datetime,
) -> LifeDecision | None:
    """Pick an effector for a pending impulse. None means leave the base tick."""
    impulse = state.pending_impulse
    if impulse is None:
        return None
    kind = impulse.kind
    allow = impulse.allow_speak
    age = _elapsed_sec(impulse.created_at, now)
    meta_kind, meta_source, meta_due = _impulse_meta(state)

    def _pick(
        nxt: InnerState,
        action: LifeAction,
        followup: ImpulseFollowup,
    ) -> LifeDecision:
        return _decision(
            nxt,
            action,
            allow_impulse=True,
            followup=followup,
            impulse_kind=meta_kind,
            impulse_source_id=meta_source,
            impulse_due_soon=meta_due,
        )

    if kind in {"welcome", "festival"}:
        if allow:
            return _pick(state.clone(), "speak", "keep")
        return _pick(_clear_impulse(state), "emotion_only", "drop")

    if kind in _CARE_KINDS:
        if not allow:
            return _pick(_clear_impulse(state), "emotion_only", "mark_care")
        if age < SIMMER_SEC:
            nxt = _shift(
                state,
                now,
                activity="thinking",
                attention="rumination",
                mood="preoccupied",
                last_event_at=now,
            )
            nxt.pending_impulse = state.pending_impulse
            return _pick(nxt, "emotion_only", "keep")
        return _pick(state.clone(), "speak", "keep")

    if kind == "idle":
        if not allow:
            return _pick(_clear_impulse(state), "emotion_only", "drop")
        if state.activity == "thinking" and state.has_rumination():
            return _pick(_clear_impulse(state), "emotion_only", "mark_fired")
        return _pick(state.clone(), "speak", "keep")

    # goal / mood_followup
    if not allow:
        return _pick(_clear_impulse(state), "emotion_only", "drop")
    return _pick(state.clone(), "speak", "keep")


def _with_impulse(base: LifeDecision, now: datetime) -> LifeDecision:
    resolved = _resolve_pending(base.state, now)
    return resolved if resolved is not None else base


def decide(
    state: InnerState,
    event: WorldEvent,
    *,
    settings: LifeSettings,
    climate: str | None = None,
) -> LifeDecision:
    """Apply one world event. climate is read-only (logged at the engine)."""
    del climate
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

    if kind == "hands_on":
        nxt = _shift(
            state,
            now,
            activity="using_computer",
            attention="self",
            mood=state.private_mood,
        )
        return _decision(nxt, "shift_activity")

    if kind == "hands_off":
        if state.activity != "using_computer":
            return _decision(state.clone(), "continue_activity")
        nxt = _release_look(state, now)
        return _decision(nxt, "shift_activity")

    if kind == "teacher_interrupt":
        nxt = state.clone()
        nxt.last_event_at = now
        return _decision(nxt, "continue_activity")

    if kind == "teacher_left":
        nxt = _after_teacher_gone(state, now)
        return _decision(nxt, "shift_activity")

    if kind == "impulse_due":
        resolved = _resolve_pending(state, now)
        if resolved is not None:
            return resolved
        return _decision(state.clone(), "continue_activity")

    # clock_tick and any unknown kind: wall-clock decay, then pending impulse
    look_hold = max(0.0, float(settings.look_hold_sec))
    think_hold = max(0.0, float(settings.think_hold_sec))
    hold_active = _teacher_hold_active(state, now, look_hold)
    in_rest = _in_rest_slot(now)

    if hold_active:
        base = _decision(state.clone(), "continue_activity")
        return _with_impulse(base, now)

    if state.activity == "using_computer":
        base = _decision(state.clone(), "continue_activity")
        return _with_impulse(base, now)

    if in_rest:
        if state.activity == "resting":
            base = _decision(state.clone(), "continue_activity")
            return _with_impulse(base, now)
        nxt = _shift(
            state,
            now,
            activity="resting",
            attention="diffuse",
            mood="sleepy",
        )
        return _with_impulse(_decision(nxt, "shift_activity"), now)

    if state.activity == "resting":
        nxt = _release_look(state, now)
        return _with_impulse(_decision(nxt, "shift_activity"), now)

    if state.activity == "looking_at_teacher":
        nxt = _release_look(state, now)
        return _with_impulse(_decision(nxt, "shift_activity"), now)

    if state.activity == "thinking":
        if _elapsed_sec(state.activity_since, now) >= think_hold:
            nxt = _shift(
                state,
                now,
                activity=DEFAULT_ACTIVITY,
                attention=DEFAULT_ATTENTION,
                mood=DEFAULT_MOOD,
            )
            return _with_impulse(_decision(nxt, "shift_activity"), now)
        return _with_impulse(_decision(state.clone(), "continue_activity"), now)

    return _with_impulse(_decision(state.clone(), "continue_activity"), now)
