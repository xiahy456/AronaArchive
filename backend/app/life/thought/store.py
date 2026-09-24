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

"""JSON ledger for a thought cycle. Separate from life.json."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ...safety import is_crisis_text
from ..state import format_life_dt, parse_life_dt

logger = logging.getLogger(__name__)

TRIGGER_KINDS: frozenset[str] = frozenset(
    {
        "aftertaste",
        "arrived",
        "left",
        "glance",
        "memory",
        "climate",
        "revisit",
        "spontaneous",
        "consolidate",
    }
)

# Higher keeps the item. Overflow drops the lowest, then the oldest.
TRIGGER_PRIORITY: dict[str, int] = {
    "aftertaste": 90,
    "arrived": 80,
    "left": 70,
    "glance": 60,
    "memory": 50,
    "climate": 40,
    "revisit": 30,
    "spontaneous": 20,
    "consolidate": 10,
}

MAX_TRIGGERS = 8


@dataclass
class PendingTrigger:
    kind: str
    not_before: datetime | None = None
    focus_id: str = ""
    memory_key: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "not_before": format_life_dt(self.not_before),
            "focus_id": self.focus_id,
            "memory_key": self.memory_key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PendingTrigger | None:
        if not isinstance(data, dict):
            return None
        kind = str(data.get("kind") or "").strip()
        if kind not in TRIGGER_KINDS:
            return None
        return cls(
            kind=kind,
            not_before=parse_life_dt(data.get("not_before")),
            focus_id=str(data.get("focus_id") or "").strip(),
            memory_key=str(data.get("memory_key") or "").strip(),
        )


@dataclass
class ThoughtFocus:
    id: str
    text: str
    since: datetime | None = None
    spoken: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "since": format_life_dt(self.since),
            "spoken": self.spoken,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ThoughtFocus | None:
        if not isinstance(data, dict):
            return None
        item_id = str(data.get("id") or "").strip()
        text = " ".join(str(data.get("text") or "").split())
        if not item_id or not text or is_crisis_text(text):
            return None
        return cls(
            id=item_id,
            text=text,
            since=parse_life_dt(data.get("since")),
            spoken=bool(data.get("spoken", False)),
        )


@dataclass
class ThoughtLedger:
    last_thought_at: datetime | None = None
    last_focus: str = ""
    last_thought_spoke_at: datetime | None = None
    speak_day: str = ""
    speak_count: int = 0
    thought_hour: str = ""
    thought_count: int = 0
    last_feeling: str = ""
    last_crisis_at: datetime | None = None
    last_glance_seen: str = ""
    seen_memory_keys: list[str] = field(default_factory=list)
    pending_triggers: list[PendingTrigger] = field(default_factory=list)
    focus: ThoughtFocus | None = None

    def enqueue(self, trigger: PendingTrigger) -> bool:
        """Append one trigger. Unknown kinds are ignored. Overflow drops the lowest."""
        if trigger.kind not in TRIGGER_KINDS:
            return False
        self.pending_triggers.append(trigger)
        self._trim_triggers()
        return True

    def _trim_triggers(self) -> None:
        while len(self.pending_triggers) > MAX_TRIGGERS:
            ranked = sorted(
                enumerate(self.pending_triggers),
                key=lambda pair: (
                    TRIGGER_PRIORITY.get(pair[1].kind, 0),
                    pair[1].not_before or datetime.min,
                    pair[0],
                ),
            )
            del self.pending_triggers[ranked[0][0]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_thought_at": format_life_dt(self.last_thought_at),
            "last_focus": self.last_focus,
            "last_thought_spoke_at": format_life_dt(self.last_thought_spoke_at),
            "speak_day": self.speak_day,
            "speak_count": self.speak_count,
            "thought_hour": self.thought_hour,
            "thought_count": self.thought_count,
            "last_feeling": self.last_feeling,
            "last_crisis_at": format_life_dt(self.last_crisis_at),
            "last_glance_seen": self.last_glance_seen,
            "seen_memory_keys": list(self.seen_memory_keys),
            "pending_triggers": [item.to_dict() for item in self.pending_triggers],
            "focus": self.focus.to_dict() if self.focus is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ThoughtLedger:
        if not isinstance(data, dict):
            return cls()
        triggers: list[PendingTrigger] = []
        raw_triggers = data.get("pending_triggers") or []
        if isinstance(raw_triggers, list):
            for raw in raw_triggers:
                item = PendingTrigger.from_dict(raw if isinstance(raw, dict) else None)
                if item is not None:
                    triggers.append(item)
        keys: list[str] = []
        raw_keys = data.get("seen_memory_keys") or []
        if isinstance(raw_keys, list):
            seen: set[str] = set()
            for raw in raw_keys:
                key = str(raw or "").strip()
                if key and key not in seen:
                    seen.add(key)
                    keys.append(key)
        last_focus = str(data.get("last_focus") or "").strip()
        if is_crisis_text(last_focus):
            last_focus = ""
        glance = str(data.get("last_glance_seen") or "").strip()
        if is_crisis_text(glance):
            glance = ""
        try:
            speak_count = int(data.get("speak_count") or 0)
        except (TypeError, ValueError):
            speak_count = 0
        if speak_count < 0:
            speak_count = 0
        try:
            thought_count = int(data.get("thought_count") or 0)
        except (TypeError, ValueError):
            thought_count = 0
        if thought_count < 0:
            thought_count = 0
        feeling = str(data.get("last_feeling") or "").strip()
        if feeling not in {"calm", "bright", "weary", "preoccupied", "sleepy"}:
            feeling = ""
        ledger = cls(
            last_thought_at=parse_life_dt(data.get("last_thought_at")),
            last_focus=last_focus,
            last_thought_spoke_at=parse_life_dt(data.get("last_thought_spoke_at")),
            speak_day=str(data.get("speak_day") or "").strip(),
            speak_count=speak_count,
            thought_hour=str(data.get("thought_hour") or "").strip(),
            thought_count=thought_count,
            last_feeling=feeling,
            last_crisis_at=parse_life_dt(data.get("last_crisis_at")),
            last_glance_seen=glance,
            seen_memory_keys=keys,
            pending_triggers=triggers,
            focus=ThoughtFocus.from_dict(
                data.get("focus") if isinstance(data.get("focus"), dict) else None
            ),
        )
        ledger._trim_triggers()
        return ledger


class ThoughtStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.ledger = ThoughtLedger()

    def load(self) -> ThoughtLedger:
        """Return an empty ledger when the file is missing or unreadable."""
        if not self.path.is_file():
            self.ledger = ThoughtLedger()
            return self.ledger
        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("thought load failed path=%s", self.path)
            self.ledger = ThoughtLedger()
            return self.ledger
        if not raw_text.strip():
            self.ledger = ThoughtLedger()
            return self.ledger
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.exception("thought load failed path=%s", self.path)
            self.ledger = ThoughtLedger()
            return self.ledger
        if not isinstance(raw, dict):
            logger.warning("thought load skipped non-object path=%s", self.path)
            self.ledger = ThoughtLedger()
            return self.ledger
        self.ledger = ThoughtLedger.from_dict(raw)
        return self.ledger

    def save(self, ledger: ThoughtLedger | None = None) -> None:
        if ledger is not None:
            self.ledger = ledger
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self.ledger.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)
