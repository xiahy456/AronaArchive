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

"""Arona's own short memory. Written by the life loop, never by the teacher extractor."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..safety import is_crisis_text

logger = logging.getLogger(__name__)

MAX_LINES = 3
LINE_MAX = 60
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
    if len(line) > LINE_MAX:
        line = line[:LINE_MAX] + "…"
    return line


class AronaMemory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.slots: dict[str, str] = {key: "" for key in SLOT_ORDER}
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

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"slots": {key: self.slots.get(key, "") for key in SLOT_ORDER}}
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
        try:
            self.save()
        except OSError:
            logger.exception("arona memory save failed path=%s", self.path)

    def clear_slot(self, slot: str) -> None:
        if slot not in SLOT_ORDER or not self.slots.get(slot):
            return
        self.slots[slot] = ""
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
        rows = self.lines()
        if not rows:
            return ""
        return "【阿洛娜的记忆】\n" + "\n".join(f"- {line}" for line in rows)
