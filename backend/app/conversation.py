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

"""Per-session sliding conversation window."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


def _format_transcript(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for msg in messages:
        role = "老师" if msg["role"] == "user" else "阿洛娜"
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


@dataclass
class ConversationManager:
    max_history_turns: int = 6
    _sessions: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    _turn_counts: dict[str, int] = field(default_factory=dict)
    _extract_buffers: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        return list(self._sessions.get(session_id, []))

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        at: datetime | None = None,
    ) -> None:
        history = self._sessions.setdefault(session_id, [])
        stamp = (at or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S")
        history.append({"role": role, "content": content, "time": stamp})
        # Keep last N turns = 2N messages (user+assistant)
        max_messages = max(1, self.max_history_turns) * 2
        if len(history) > max_messages:
            self._sessions[session_id] = history[-max_messages:]
        if role == "user":
            self._turn_counts[session_id] = self._turn_counts.get(session_id, 0) + 1

    def turn_count(self, session_id: str) -> int:
        return self._turn_counts.get(session_id, 0)

    def append_extract_buffer(self, session_id: str, role: str, content: str) -> None:
        buffer = self._extract_buffers.setdefault(session_id, [])
        buffer.append({"role": role, "content": content})

    def extract_buffer_turn_count(self, session_id: str) -> int:
        buffer = self._extract_buffers.get(session_id) or []
        # Count complete user turns present in the buffer
        return sum(1 for msg in buffer if msg.get("role") == "user")

    def extract_buffer_transcript(self, session_id: str) -> str:
        buffer = self._extract_buffers.get(session_id) or []
        return _format_transcript(buffer)

    def extract_buffer_user_texts(self, session_id: str) -> list[str]:
        buffer = self._extract_buffers.get(session_id) or []
        return [
            str(msg.get("content") or "").strip()
            for msg in buffer
            if msg.get("role") == "user" and str(msg.get("content") or "").strip()
        ]

    def clear_extract_buffer(self, session_id: str) -> None:
        self._extract_buffers.pop(session_id, None)

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._turn_counts.pop(session_id, None)
        self._extract_buffers.pop(session_id, None)

    def drop(self, session_id: str) -> None:
        self.clear(session_id)

    def recent_transcript(self, session_id: str, turns: int = 3) -> str:
        history = self.get_history(session_id)
        # last `turns` user+assistant pairs
        slice_msgs = history[-(turns * 2) :]
        return _format_transcript(slice_msgs)
