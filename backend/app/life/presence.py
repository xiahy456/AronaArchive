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

"""Map inner state to a visible face and push `presence` (never chat)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal

from ..planner.emotions import normalize_emotion
from ..protocol import msg_presence
from .state import InnerState

logger = logging.getLogger(__name__)

PresenceVerdict = Literal["send", "defer", "skip"]

_IDLE_MOOD_FACE = {
    "bright": "smile",
    "weary": "frustration",
    "preoccupied": "curious",
    "sleepy": "sleep",
}


def presence_emotion(state: InnerState) -> str:
    """Deterministic inner-state → arona_emotion whitelist value."""
    activity = state.activity
    mood = state.private_mood
    if activity == "using_computer":
        raw = "curious"
    elif mood == "sleepy":
        raw = "sleep"
    elif activity == "resting":
        raw = "sleep_very_content" if mood == "bright" else "sleep"
    elif activity == "looking_at_teacher":
        raw = "normal"
    elif activity == "thinking":
        raw = "frustration" if mood == "weary" else "curious"
    else:
        raw = _IDLE_MOOD_FACE.get(mood, "normal")
    return normalize_emotion(raw)


@dataclass
class PresenceGate:
    """Process-level last-sent face. Not persisted."""

    last_sent: str | None = None
    pending: bool = False
    sticky_emotion: str | None = None
    sticky_mapped: str | None = None

    def desired(self, mapped: str) -> str:
        if self.sticky_emotion and mapped == self.sticky_mapped:
            return self.sticky_emotion
        self.sticky_emotion = None
        self.sticky_mapped = None
        return mapped

    def set_sticky(self, emotion: str, mapped: str) -> None:
        self.sticky_emotion = emotion
        self.sticky_mapped = mapped

    def decide(self, desired: str, *, any_busy: bool) -> PresenceVerdict:
        if desired == self.last_sent:
            self.pending = False
            return "skip"
        if any_busy:
            self.pending = True
            return "defer"
        return "send"

    def mark_sent(self, emotion: str) -> None:
        self.last_sent = emotion
        self.pending = False


async def publish_presence(
    state: Any,
    *,
    force_session: str | None = None,
    emotion_override: str | None = None,
    ignore_busy: bool = False,
) -> None:
    """Send `presence` to connected sessions when the mapped face changes.

    `force_session` always delivers the current face to that session (connect).
    Generation (`hub.any_busy`) defers the broadcast; callers flush when idle.
    `emotion_override` is a one-activity sticky face (emotion_only).
    """
    engine = getattr(state, "life", None)
    hub = getattr(state, "hub", None)
    gate: PresenceGate | None = getattr(state, "presence", None)
    if engine is None or hub is None:
        return
    if gate is None:
        gate = PresenceGate()
        state.presence = gate

    inner: InnerState = engine.state
    mapped = presence_emotion(inner)
    override = (emotion_override or "").strip()
    if override:
        face = normalize_emotion(override)
        gate.set_sticky(face, mapped)
    emotion = gate.desired(mapped)
    payload = msg_presence(emotion, activity=inner.activity)

    if force_session:
        send = hub.get(force_session)
        if send is not None:
            try:
                await send(payload)
            except Exception:
                logger.exception("presence send failed session=%s", force_session)

    any_busy = bool(hub.any_busy()) and not ignore_busy
    verdict = gate.decide(emotion, any_busy=any_busy)
    if verdict == "skip":
        return
    if verdict == "defer":
        logger.debug("presence deferred emotion=%s", emotion)
        return

    for session_id, send in hub.all_sessions():
        if session_id == force_session:
            continue
        try:
            await send(payload)
        except Exception:
            logger.exception("presence send failed session=%s", session_id)
    gate.mark_sent(emotion)
    logger.info(
        "life presence emotion=%s activity=%s",
        emotion,
        payload.get("activity"),
    )


async def _publish_safe(
    state: Any,
    *,
    force_session: str | None = None,
    emotion_override: str | None = None,
    ignore_busy: bool = False,
) -> None:
    try:
        await publish_presence(
            state,
            force_session=force_session,
            emotion_override=emotion_override,
            ignore_busy=ignore_busy,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("presence publish failed")


def schedule_presence(
    state: Any,
    *,
    force_session: str | None = None,
    emotion_override: str | None = None,
    ignore_busy: bool = False,
) -> None:
    """Queue a presence push; no-op without a running event loop (unit tests)."""
    if getattr(state, "life", None) is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        _publish_safe(
            state,
            force_session=force_session,
            emotion_override=emotion_override,
            ignore_busy=ignore_busy,
        ),
        name="life-presence",
    )
