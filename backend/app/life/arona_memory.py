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

"""Arona's own short memory. Written by the life loop, never by the teacher extractor."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..safety import is_crisis_text
from .state import format_life_dt, parse_life_dt

logger = logging.getLogger(__name__)

MAX_LINES = 3
DEFAULT_NOTES_MAX = 8
CONSOLIDATE_NOTE_LIMIT = 3
DEFAULT_NOTES_MAX_AGE_HOURS = 24.0
SLOT_ORDER = ("classroom", "open_worry", "worry")

_ACTIVITY_LINE = {
    "idle_in_classroom": "在教室待过",
    "looking_at_teacher": "看过老师",
    "thinking": "在教室想过事情",
    "resting": "在教室休息过",
    "using_computer": "通过什亭之匣操作过电脑",
}


def _clean_line(text: str) -> str:
    line = " ".join((text or "").split())
    if not line or is_crisis_text(line):
        return ""
    return line


def _clean_note(text: str) -> str:
    """Reject crisis wording whole, before the note is stored."""
    line = " ".join((text or "").split())
    if not line or is_crisis_text(line):
        return ""
    return line


@dataclass
class AronaNote:
    at: datetime
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"at": format_life_dt(self.at), "text": self.text}


class AronaMemory:
    def __init__(
        self,
        path: Path,
        *,
        notes_max: int = DEFAULT_NOTES_MAX,
        notes_max_age_hours: float = DEFAULT_NOTES_MAX_AGE_HOURS,
    ) -> None:
        self.path = path
        self.notes_max = max(0, int(notes_max))
        self.notes_max_age = timedelta(hours=max(0.0, float(notes_max_age_hours)))
        self.slots: dict[str, str] = {key: "" for key in SLOT_ORDER}
        self.notes: list[AronaNote] = []
        self.worry_stopped_at: datetime | None = None
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("arona memory load failed path=%s", self.path)
            return
        if not isinstance(raw, dict):
            return
        slots = raw.get("slots")
        if not isinstance(slots, dict):
            return
        for key in SLOT_ORDER:
            self.slots[key] = _clean_line(str(slots.get(key) or ""))
        notes: list[AronaNote] = []
        raw_notes = raw.get("notes")
        if isinstance(raw_notes, list):
            for item in raw_notes:
                note = self._note_from_raw(item)
                if note is not None:
                    notes.append(note)
        self.notes = notes
        self._trim_notes(datetime.now())
        self.worry_stopped_at = parse_life_dt(raw.get("worry_stopped_at"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "slots": {key: self.slots.get(key, "") for key in SLOT_ORDER},
            "notes": [note.to_dict() for note in self.notes],
            "worry_stopped_at": format_life_dt(self.worry_stopped_at),
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def set_slot(self, slot: str, text: str) -> None:
        if slot not in SLOT_ORDER:
            return
        line = _clean_line(text)
        if not line or self.slots.get(slot) == line:
            return
        self.slots[slot] = line
        if slot == "worry":
            self.worry_stopped_at = None
        try:
            self.save()
        except OSError:
            logger.exception("arona memory save failed path=%s", self.path)

    def clear_slot(self, slot: str) -> None:
        if slot not in SLOT_ORDER or not self.slots.get(slot):
            return
        self.slots[slot] = ""
        if slot == "worry":
            self.worry_stopped_at = None
        try:
            self.save()
        except OSError:
            logger.exception("arona memory save failed path=%s", self.path)

    def append_note(self, text: str, now: datetime | None = None) -> bool:
        """Store one observation. Crisis text is refused whole."""
        line = _clean_note(text)
        if not line:
            return False
        at = (now or datetime.now()).replace(microsecond=0)
        self.notes.append(AronaNote(at=at, text=line))
        self._trim_notes(at)
        try:
            self.save()
        except OSError:
            logger.exception("arona memory save failed path=%s", self.path)
            return False
        return True

    def replace_notes(self, lines: list[str], now: datetime | None = None) -> None:
        """Replace her notes with a short rest rewrite. Crisis lines are dropped."""
        at = (now or datetime.now()).replace(microsecond=0)
        kept: list[AronaNote] = []
        for raw in lines[:CONSOLIDATE_NOTE_LIMIT]:
            text = _clean_note(raw)
            if text:
                kept.append(AronaNote(at=at, text=text))
        self.notes = kept
        self._trim_notes(at)
        try:
            self.save()
        except OSError:
            logger.exception("arona memory save failed path=%s", self.path)

    def set_worry(self, content: str, stopped_at: datetime) -> None:
        """Record a worry that has ended, including when it stopped."""
        body = " ".join(f"担心过：{content}".split())
        if not body or is_crisis_text(body):
            return
        when = stopped_at.replace(microsecond=0)
        suffix = f"（{when.strftime('%Y-%m-%d %H:%M')}放下）"
        line = body + suffix
        if self.slots.get("worry") == line and self.worry_stopped_at == when:
            return
        self.slots["worry"] = line
        self.worry_stopped_at = when
        try:
            self.save()
        except OSError:
            logger.exception("arona memory save failed path=%s", self.path)

    def note_activity(self, activity: str) -> None:
        line = _ACTIVITY_LINE.get(activity, "")
        if line:
            self.set_slot("classroom", line)

    def lines(self) -> list[str]:
        out: list[str] = []
        for key in SLOT_ORDER:
            line = (self.slots.get(key) or "").strip()
            if line:
                out.append(line)
        return out[:MAX_LINES]

    def block(self) -> str:
        """Teacher-turn block. Notes stay out so the planner context is unchanged."""
        rows = self.lines()
        if not rows:
            return ""
        return "【阿洛娜的记忆】\n" + "\n".join(f"- {line}" for line in rows)

    def _note_from_raw(self, raw: object) -> AronaNote | None:
        if not isinstance(raw, dict):
            return None
        text = _clean_note(str(raw.get("text") or ""))
        at = parse_life_dt(raw.get("at"))
        if not text or at is None:
            return None
        return AronaNote(at=at, text=text)

    def _trim_notes(self, now: datetime) -> None:
        cutoff = now - self.notes_max_age
        self.notes = [note for note in self.notes if note.at >= cutoff]
        self.notes.sort(key=lambda note: note.at)
        if len(self.notes) > self.notes_max:
            self.notes = self.notes[-self.notes_max :]
