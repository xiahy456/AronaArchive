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

"""Global dialogue log. Prompt windows still slice the last few turns."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .channel import method_label
from .life.thought.schema import is_thought_history_marker

logger = logging.getLogger(__name__)

MAX_DIALOGUE_ENTRIES = 2048
_DT_FMT = "%Y-%m-%dT%H:%M:%S"
_ROLES = frozenset({"user", "assistant", "event"})
_KINDS = frozenset({"speech", "touch", "arrive", "leave"})
_PROACTIVE_MARKERS = frozenset(
    {"【上线】", "【搭话】", "【提醒】", "【回访】", "【心情回访】", "【节日】"}
)
_PAT_HEAD = "【摸头】"
ARRIVE_TEXT = "老师接上"
LEAVE_TEXT = "老师离开"


def _format_transcript(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for msg in messages:
        role = "老师" if msg["role"] == "user" else "阿洛娜"
        label = method_label(msg.get("method"))
        lines.append(f"[{label}] {role}: {msg['content']}")
    return "\n".join(lines)


def _stamp(at: datetime | None) -> str:
    return (at or datetime.now()).strftime(_DT_FMT)


@dataclass
class DialogueEntry:
    role: str
    kind: str
    content: str
    action: str = ""
    time: str = ""
    session_id: str = ""
    method: str = ""

    def to_dict(self) -> dict[str, str]:
        payload = {
            "role": self.role,
            "kind": self.kind,
            "content": self.content,
            "action": self.action,
            "time": self.time,
            "session_id": self.session_id,
        }
        if self.method:
            payload["method"] = self.method
        return payload

    def history_line(self) -> dict[str, str]:
        return {
            "role": self.role,
            "content": self.content,
            "time": self.time,
            "method": self.method,
        }


def _entry_from_dict(raw: object) -> DialogueEntry | None:
    if not isinstance(raw, dict):
        return None
    role = str(raw.get("role") or "").strip()
    kind = str(raw.get("kind") or "").strip()
    content = str(raw.get("content") or "").strip()
    if role not in _ROLES or kind not in _KINDS or not content:
        return None
    if is_thought_history_marker(content) or content in _PROACTIVE_MARKERS:
        return None
    return DialogueEntry(
        role=role,
        kind=kind,
        content=content,
        action=str(raw.get("action") or "").strip(),
        time=str(raw.get("time") or "").strip(),
        session_id=str(raw.get("session_id") or "").strip(),
        method=str(raw.get("method") or "").strip(),
    )


class DialogueStore:
    def __init__(self, path: Path | None, *, max_entries: int = MAX_DIALOGUE_ENTRIES) -> None:
        self.path = path
        self.max_entries = max(1, int(max_entries or MAX_DIALOGUE_ENTRIES))
        self.entries: list[DialogueEntry] = []
        self.load()

    def load(self) -> list[DialogueEntry]:
        self.entries = []
        if self.path is None or not self.path.is_file():
            return self.entries
        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("dialogue load failed path=%s", self.path)
            return self.entries
        if not raw_text.strip():
            return self.entries
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.exception("dialogue load failed path=%s", self.path)
            return self.entries
        rows = raw.get("entries") if isinstance(raw, dict) else None
        if not isinstance(rows, list):
            logger.warning("dialogue load skipped non-list path=%s", self.path)
            return self.entries
        loaded = [item for item in (_entry_from_dict(row) for row in rows) if item is not None]
        self.entries = loaded[-self.max_entries :]
        return self.entries

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [item.to_dict() for item in self.entries]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def append(self, entry: DialogueEntry) -> None:
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries :]
        self.save()

    def clear(self) -> None:
        self.entries = []
        self.save()


@dataclass
class ConversationManager:
    max_history_turns: int = 6
    persist_path: Path | None = None
    max_entries: int = MAX_DIALOGUE_ENTRIES
    _store: DialogueStore | None = field(default=None, init=False, repr=False)
    _turn_counts: dict[str, int] = field(default_factory=dict)
    _extract_buffers: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._store = DialogueStore(self.persist_path, max_entries=self.max_entries)

    def entries(self) -> list[DialogueEntry]:
        assert self._store is not None
        return list(self._store.entries)

    def get_history(self, session_id: str = "") -> list[dict[str, str]]:
        del session_id
        assert self._store is not None
        spoken = [
            item.history_line()
            for item in self._store.entries
            if item.role in {"user", "assistant"}
        ]
        window = max(1, self.max_history_turns) * 2
        return spoken[-window:]

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        at: datetime | None = None,
        kind: str = "",
        action: str = "",
        method: str = "direct",
    ) -> None:
        text = (content or "").strip()
        if not text or is_thought_history_marker(text) or text in _PROACTIVE_MARKERS:
            return
        stored_role = role if role in _ROLES else "user"
        stored_kind = kind if kind in _KINDS else ""
        stored_action = (action or "").strip()
        if text == _PAT_HEAD or stored_action == "pat_head":
            stored_kind = "touch"
            stored_action = "pat_head"
            stored_role = "user"
        elif stored_kind in {"arrive", "leave"}:
            stored_role = "event"
        elif not stored_kind:
            stored_kind = "speech"
        stored_method = method if method in {"direct", "message"} else "direct"
        assert self._store is not None
        self._store.append(
            DialogueEntry(
                role=stored_role,
                kind=stored_kind,
                content=text,
                action=stored_action,
                time=_stamp(at),
                session_id=session_id or "",
                method=stored_method,
            )
        )
        if stored_role == "user":
            self._turn_counts[session_id] = self._turn_counts.get(session_id, 0) + 1

    def turn_count(self, session_id: str) -> int:
        return self._turn_counts.get(session_id, 0)

    def append_extract_buffer(
        self,
        session_id: str,
        role: str,
        content: str,
        method: str = "",
    ) -> None:
        buffer = self._extract_buffers.setdefault(session_id, [])
        buffer.append({"role": role, "content": content, "method": method})

    def extract_buffer_turn_count(self, session_id: str) -> int:
        buffer = self._extract_buffers.get(session_id) or []
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
        assert self._store is not None
        self._store.clear()
        self._turn_counts.pop(session_id, None)
        self._extract_buffers.pop(session_id, None)

    def drop(self, session_id: str) -> None:
        self._turn_counts.pop(session_id, None)
        self._extract_buffers.pop(session_id, None)

    def recent_transcript(self, session_id: str, turns: int = 3) -> str:
        history = self.get_history(session_id)
        slice_msgs = history[-(turns * 2) :]
        return _format_transcript(slice_msgs)
