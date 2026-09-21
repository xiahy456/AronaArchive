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

"""In-process registry of live WebSocket sessions that can receive pushes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

SendFn = Callable[[dict[str, Any]], Awaitable[None]]


class ConnectionHub:
    """Track connected sessions and whether they are currently generating."""

    def __init__(self) -> None:
        self._sessions: dict[str, SendFn] = {}
        self._busy: set[str] = set()
        self._listening: set[str] = set()
        self._on_all_idle: Callable[[], None] | None = None

    def set_on_all_idle(self, fn: Callable[[], None] | None) -> None:
        self._on_all_idle = fn

    def _fire_all_idle_if_needed(self, was_busy: bool) -> None:
        if was_busy and not self._busy and self._on_all_idle is not None:
            self._on_all_idle()

    def register(self, session_id: str, send: SendFn) -> None:
        self._sessions[session_id] = send

    def unregister(self, session_id: str) -> None:
        was_busy = bool(self._busy)
        self._sessions.pop(session_id, None)
        self._busy.discard(session_id)
        self._listening.discard(session_id)
        self._fire_all_idle_if_needed(was_busy)

    def get(self, session_id: str) -> SendFn | None:
        return self._sessions.get(session_id)

    def set_listening(self, session_id: str, listening: bool) -> None:
        if listening:
            self._listening.add(session_id)
        else:
            self._listening.discard(session_id)

    def is_listening(self, session_id: str) -> bool:
        return session_id in self._listening

    def set_busy(self, session_id: str, busy: bool) -> None:
        was_busy = bool(self._busy)
        if busy:
            self._busy.add(session_id)
        else:
            self._busy.discard(session_id)
        self._fire_all_idle_if_needed(was_busy)

    def is_busy(self, session_id: str) -> bool:
        return session_id in self._busy

    def any_busy(self) -> bool:
        return bool(self._busy)

    def all_sessions(self) -> list[tuple[str, SendFn]]:
        return list(self._sessions.items())

    def idle_sessions(self) -> list[tuple[str, SendFn]]:
        """Sessions that can receive a line. Listening no longer freezes life."""
        return [
            (session_id, send)
            for session_id, send in self._sessions.items()
            if session_id not in self._busy
        ]
