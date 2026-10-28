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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .channel import method_label
from .life.thought.schema import is_thought_history_marker
from .safety import is_crisis_text

logger = logging.getLogger(__name__)

MAX_DIALOGUE_ENTRIES = 2048
EXTRACT_WINDOW_MAX_ROWS = 40
EXTRACT_CARRY_MAX_ROWS = 20
_DT_FMT = "%Y-%m-%dT%H:%M:%S"
_ROLES = frozenset({"user", "assistant", "event"})
_KINDS = frozenset({"speech", "touch", "arrive", "leave"})
_PROACTIVE_MARKERS = frozenset(
    {"【上线】", "【搭话】", "【提醒】", "【回访】", "【心情回访】", "【节日】"}
)
_PAT_HEAD = "【摸头】"
_IMAGE_PLACEHOLDER = "（图片）"
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


def _parse_entry_time(raw: str | None) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.strptime(text, _DT_FMT)
        except ValueError:
            return None


@dataclass
class DialogueEntry:
    role: str
    kind: str
    content: str
    action: str = ""
    time: str = ""
    session_id: str = ""
    method: str = ""
    qq_parts: list[dict[str, str]] = field(default_factory=list)
    seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": self.role,
            "kind": self.kind,
            "content": self.content,
            "action": self.action,
            "time": self.time,
            "session_id": self.session_id,
            "seq": self.seq,
        }
        if self.method:
            payload["method"] = self.method
        if self.qq_parts:
            payload["qq_parts"] = list(self.qq_parts)
        return payload

    def history_line(self) -> dict[str, str]:
        return {
            "role": self.role,
            "content": self.content,
            "time": self.time,
            "method": self.method,
        }


def _qq_parts_from_raw(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    parts: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        message_id = str(item.get("message_id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not message_id and not text:
            continue
        parts.append({"message_id": message_id, "text": text})
    return parts


def _content_from_qq_parts(parts: list[dict[str, str]]) -> str:
    texts = [str(part.get("text") or "").strip() for part in parts]
    joined = "\n".join(text for text in texts if text)
    if joined:
        return joined
    return _IMAGE_PLACEHOLDER if parts else ""


def _entry_from_dict(raw: object) -> DialogueEntry | None:
    if not isinstance(raw, dict):
        return None
    role = str(raw.get("role") or "").strip()
    kind = str(raw.get("kind") or "").strip()
    content = str(raw.get("content") or "").strip()
    qq_parts = _qq_parts_from_raw(raw.get("qq_parts"))
    if role not in _ROLES or kind not in _KINDS:
        return None
    if not content and not qq_parts:
        return None
    if content and (is_thought_history_marker(content) or content in _PROACTIVE_MARKERS):
        return None
    try:
        seq = int(raw.get("seq") or 0)
    except (TypeError, ValueError):
        seq = 0
    return DialogueEntry(
        role=role,
        kind=kind,
        content=content or _content_from_qq_parts(qq_parts),
        action=str(raw.get("action") or "").strip(),
        time=str(raw.get("time") or "").strip(),
        session_id=str(raw.get("session_id") or "").strip(),
        method=str(raw.get("method") or "").strip(),
        qq_parts=qq_parts,
        seq=max(0, seq),
    )


class DialogueStore:
    def __init__(self, path: Path | None, *, max_entries: int = MAX_DIALOGUE_ENTRIES) -> None:
        self.path = path
        self.max_entries = max(1, int(max_entries or MAX_DIALOGUE_ENTRIES))
        self.entries: list[DialogueEntry] = []
        self._next_seq = 1
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
        self._assign_missing_seq()
        return self.entries

    def _assign_missing_seq(self) -> None:
        """Keep seq monotonic. Older files have no seq; number them by order."""
        highest = 0
        for entry in self.entries:
            if entry.seq > highest:
                highest = entry.seq
        if highest <= 0:
            for index, entry in enumerate(self.entries, start=1):
                entry.seq = index
            highest = len(self.entries)
        else:
            for entry in self.entries:
                if entry.seq <= 0:
                    highest += 1
                    entry.seq = highest
        self._next_seq = highest + 1

    @property
    def next_seq(self) -> int:
        return self._next_seq

    def max_seq(self) -> int:
        return max((entry.seq for entry in self.entries), default=0)

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [item.to_dict() for item in self.entries]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def append(self, entry: DialogueEntry) -> None:
        if entry.seq <= 0:
            entry.seq = self._next_seq
        self._next_seq = max(self._next_seq, entry.seq + 1)
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries :]
        self.save()

    def remove_qq_message(self, message_id: str) -> bool:
        """Drop one QQ piece from the newest matching user row. True if changed."""
        target = str(message_id or "").strip()
        if not target:
            return False
        for index in range(len(self.entries) - 1, -1, -1):
            entry = self.entries[index]
            if entry.role != "user" or not entry.qq_parts:
                continue
            kept = [
                part
                for part in entry.qq_parts
                if str(part.get("message_id") or "").strip() != target
            ]
            if len(kept) == len(entry.qq_parts):
                continue
            if not kept:
                del self.entries[index]
            else:
                entry.qq_parts = kept
                entry.content = _content_from_qq_parts(kept)
            self.save()
            return True
        return False

    def clear(self) -> None:
        self.entries = []
        self.save()


@dataclass
class ConversationManager:
    max_history_turns: int = 6
    planner_history_hours: float = 6.0
    persist_path: Path | None = None
    max_entries: int = MAX_DIALOGUE_ENTRIES
    _store: DialogueStore | None = field(default=None, init=False, repr=False)
    _turn_counts: dict[str, int] = field(default_factory=dict)
    _extract_cursor: int = field(default=0, init=False, repr=False)
    _extract_carry: list[dict[str, str]] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._store = DialogueStore(self.persist_path, max_entries=self.max_entries)
        self.planner_history_hours = max(0.0, float(self.planner_history_hours or 0.0))
        self._extract_cursor = self._store.max_seq()
        self._turn_counts.clear()

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

    def get_planner_history(
        self,
        session_id: str = "",
        *,
        now: datetime | None = None,
    ) -> list[dict[str, str]]:
        """Recent window for Planner: all turns in the last N hours, pad back to 2N."""
        del session_id
        assert self._store is not None
        spoken = [
            item.history_line()
            for item in self._store.entries
            if item.role in {"user", "assistant"}
        ]
        if not spoken:
            return []
        target = max(1, self.max_history_turns) * 2
        anchor = now or datetime.now()
        hours = self.planner_history_hours
        cutoff = anchor - timedelta(hours=hours) if hours > 0 else anchor
        recent: list[dict[str, str]] = []
        older: list[dict[str, str]] = []
        for msg in spoken:
            stamped = _parse_entry_time(msg.get("time"))
            if stamped is not None and stamped >= cutoff:
                recent.append(msg)
            else:
                older.append(msg)
        if len(recent) >= target:
            return recent
        need = target - len(recent)
        return older[-need:] + recent

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
        qq_parts: list[dict[str, str]] | None = None,
    ) -> None:
        parts = _qq_parts_from_raw(qq_parts or [])
        text = (content or "").strip()
        if not text and parts:
            text = _content_from_qq_parts(parts)
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
                qq_parts=parts if stored_method == "message" else [],
            )
        )
        if stored_role == "user":
            self._turn_counts[session_id] = self._turn_counts.get(session_id, 0) + 1

    def remove_qq_message(self, message_id: str) -> bool:
        assert self._store is not None
        return self._store.remove_qq_message(message_id)

    def turn_count(self, session_id: str) -> int:
        return self._turn_counts.get(session_id, 0)

    def _max_seq(self) -> int:
        assert self._store is not None
        return self._store.max_seq()

    def _window_rows(self) -> list[dict[str, str]]:
        """Every logged line the extractor has not consumed yet, in order."""
        assert self._store is not None
        rows = [
            {
                "role": item.role,
                "content": item.content,
                "method": item.method,
                "seq": item.seq,
            }
            for item in self._store.entries
            if item.role in {"user", "assistant"} and item.seq > self._extract_cursor
        ]
        return rows

    def pending_extract_entries(self) -> list[dict[str, str]]:
        rows = list(self._extract_carry) + self._window_rows()
        if len(rows) > EXTRACT_WINDOW_MAX_ROWS:
            rows = rows[-EXTRACT_WINDOW_MAX_ROWS:]
        return rows

    def pending_extract_high_water(self) -> int:
        """Highest seq covered by the current window, ignoring the carry."""
        rows = self._window_rows()
        return max((int(row.get("seq") or 0) for row in rows), default=self._extract_cursor)

    def extract_window_turn_count(self) -> int:
        rows = self.pending_extract_entries()
        return sum(1 for msg in rows if msg.get("role") == "user")

    def extract_window_transcript(self) -> str:
        return _format_transcript(self.pending_extract_entries())

    def extract_window_user_texts(self) -> list[str]:
        return [
            str(msg.get("content") or "").strip()
            for msg in self.pending_extract_entries()
            if msg.get("role") == "user" and str(msg.get("content") or "").strip()
        ]

    def advance_extract_cursor(
        self,
        *,
        keep_pending: bool = False,
        through_seq: int | None = None,
    ) -> None:
        """Consume the window. keep_pending stashes it for the next extract.

        through_seq pins the high-water mark that was actually enqueued, so lines
        appended while the gate call was in flight stay for the next round.
        """
        if keep_pending:
            kept = [
                row
                for row in self.pending_extract_entries()
                if not is_crisis_text(str(row.get("content") or ""))
            ]
            self._extract_carry = kept[-EXTRACT_CARRY_MAX_ROWS:]
        else:
            self._extract_carry.clear()
        mark = self._max_seq() if through_seq is None else int(through_seq)
        self._extract_cursor = max(self._extract_cursor, mark)

    def clear(self, session_id: str) -> None:
        assert self._store is not None
        self._store.clear()
        self._turn_counts.pop(session_id, None)
        self._extract_carry.clear()
        self._extract_cursor = 0

    def drop(self, session_id: str) -> None:
        self._turn_counts.pop(session_id, None)

    def recent_transcript(self, session_id: str, turns: int = 3) -> str:
        history = self.get_history(session_id)
        slice_msgs = history[-(turns * 2) :]
        return _format_transcript(slice_msgs)
