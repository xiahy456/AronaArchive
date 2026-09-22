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

"""Arona's private inner state — not relationship climate, not arona_emotion."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal

Activity = Literal[
    "idle_in_classroom",
    "looking_at_teacher",
    "thinking",
    "resting",
    "using_computer",
]

Attention = Literal["teacher", "self", "rumination", "diffuse"]

PrivateMood = Literal["calm", "bright", "weary", "preoccupied", "sleepy"]

DEFAULT_ACTIVITY: Activity = "idle_in_classroom"
DEFAULT_ATTENTION: Attention = "diffuse"
DEFAULT_MOOD: PrivateMood = "calm"
MAX_RUMINATION = 2

ImpulseKind = Literal[
    "welcome",
    "festival",
    "breakfast",
    "lunch",
    "dinner",
    "sleep",
    "idle",
    "goal",
    "mood_followup",
]
IMPULSE_KINDS: frozenset[str] = frozenset(
    {
        "welcome",
        "festival",
        "breakfast",
        "lunch",
        "dinner",
        "sleep",
        "idle",
        "goal",
        "mood_followup",
    }
)

ACTIVITIES: frozenset[str] = frozenset(
    {
        "idle_in_classroom",
        "looking_at_teacher",
        "thinking",
        "resting",
        "using_computer",
    }
)
ATTENTIONS: frozenset[str] = frozenset(
    {"teacher", "self", "rumination", "diffuse"}
)
PRIVATE_MOODS: frozenset[str] = frozenset(
    {"calm", "bright", "weary", "preoccupied", "sleepy"}
)

_DT_FMT = "%Y-%m-%dT%H:%M:%S"


def format_life_dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime(_DT_FMT)


def parse_life_dt(raw: object) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, _DT_FMT)
    except ValueError:
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None


def _one_of(value: object, allowed: frozenset[str], default: str) -> str:
    text = str(value or "").strip()
    if text in allowed:
        return text
    return default


@dataclass
class Impulse:
    """One pending urge. Not relationship climate; the loop may ignore it."""

    kind: ImpulseKind
    created_at: datetime | None = None
    source_id: str = ""
    hint: str = ""
    instruction: str = ""
    history_marker: str = ""
    retrieve_memory: bool = False
    memory_query: str = ""
    extra_memories: tuple[str, ...] = ()
    due_soon: bool = False
    allow_speak: bool = True
    first_in_slot: bool = False
    slot_id: str = ""
    date_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "created_at": format_life_dt(self.created_at),
            "source_id": self.source_id,
            "hint": self.hint,
            "instruction": self.instruction,
            "history_marker": self.history_marker,
            "retrieve_memory": self.retrieve_memory,
            "memory_query": self.memory_query,
            "extra_memories": list(self.extra_memories),
            "due_soon": self.due_soon,
            "allow_speak": self.allow_speak,
            "first_in_slot": self.first_in_slot,
            "slot_id": self.slot_id,
            "date_key": self.date_key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Impulse | None:
        if not isinstance(data, dict):
            return None
        kind = str(data.get("kind") or "").strip()
        if kind not in IMPULSE_KINDS:
            return None
        extras_raw = data.get("extra_memories") or []
        extras: list[str] = []
        if isinstance(extras_raw, list):
            extras = [str(item).strip() for item in extras_raw if str(item).strip()]
        return cls(
            kind=kind,  # type: ignore[arg-type]
            created_at=parse_life_dt(data.get("created_at")),
            source_id=str(data.get("source_id") or "").strip(),
            hint=str(data.get("hint") or "").strip(),
            instruction=str(data.get("instruction") or "").strip(),
            history_marker=str(data.get("history_marker") or "").strip(),
            retrieve_memory=bool(data.get("retrieve_memory", False)),
            memory_query=str(data.get("memory_query") or "").strip(),
            extra_memories=tuple(extras),
            due_soon=bool(data.get("due_soon", False)),
            allow_speak=bool(data.get("allow_speak", True)),
            first_in_slot=bool(data.get("first_in_slot", False)),
            slot_id=str(data.get("slot_id") or "").strip(),
            date_key=str(data.get("date_key") or "").strip(),
        )


@dataclass
class Rumination:
    """Unspoken concern. Care / follow-up windows may fill this."""

    id: str
    content: str
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "created_at": format_life_dt(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Rumination | None:
        if not isinstance(data, dict):
            return None
        item_id = str(data.get("id") or "").strip()
        content = str(data.get("content") or "").strip()
        if not item_id or not content:
            return None
        return cls(
            id=item_id,
            content=content,
            created_at=parse_life_dt(data.get("created_at")),
        )


@dataclass
class InnerState:
    activity: Activity = DEFAULT_ACTIVITY
    attention: Attention = DEFAULT_ATTENTION
    private_mood: PrivateMood = DEFAULT_MOOD
    rumination: list[Rumination] = field(default_factory=list)
    pending_impulse: Impulse | None = None
    can_hear: bool = False
    last_spoke_at: datetime | None = None
    last_event_at: datetime | None = None
    activity_since: datetime | None = None

    def clone(self) -> InnerState:
        impulse = self.pending_impulse
        copied_impulse = None
        if impulse is not None:
            copied_impulse = Impulse(
                kind=impulse.kind,
                created_at=impulse.created_at,
                source_id=impulse.source_id,
                hint=impulse.hint,
                instruction=impulse.instruction,
                history_marker=impulse.history_marker,
                retrieve_memory=impulse.retrieve_memory,
                memory_query=impulse.memory_query,
                extra_memories=impulse.extra_memories,
                due_soon=impulse.due_soon,
                allow_speak=impulse.allow_speak,
                first_in_slot=impulse.first_in_slot,
                slot_id=impulse.slot_id,
                date_key=impulse.date_key,
            )
        return replace(
            self,
            rumination=[
                Rumination(
                    id=item.id,
                    content=item.content,
                    created_at=item.created_at,
                )
                for item in self.rumination
            ],
            pending_impulse=copied_impulse,
        )

    def has_rumination(self) -> bool:
        return bool(self.rumination)

    def with_rumination(self, items: list[Rumination]) -> InnerState:
        """Test helper: keep at most MAX_RUMINATION, oldest dropped first."""
        kept = list(items)[-MAX_RUMINATION:]
        copied = self.clone()
        copied.rumination = kept
        return copied

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity": self.activity,
            "attention": self.attention,
            "private_mood": self.private_mood,
            "rumination": [item.to_dict() for item in self.rumination],
            "pending_impulse": (
                self.pending_impulse.to_dict() if self.pending_impulse else None
            ),
            "can_hear": self.can_hear,
            "last_spoke_at": format_life_dt(self.last_spoke_at),
            "last_event_at": format_life_dt(self.last_event_at),
            "activity_since": format_life_dt(self.activity_since),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> InnerState:
        if not data:
            return cls()
        rumination: list[Rumination] = []
        raw_items = data.get("rumination") or []
        if isinstance(raw_items, list):
            for raw in raw_items:
                item = Rumination.from_dict(raw if isinstance(raw, dict) else None)
                if item is not None:
                    rumination.append(item)
                if len(rumination) >= MAX_RUMINATION:
                    break
        raw_impulse = data.get("pending_impulse")
        pending = Impulse.from_dict(raw_impulse if isinstance(raw_impulse, dict) else None)
        return cls(
            activity=_one_of(  # type: ignore[arg-type]
                data.get("activity"), ACTIVITIES, DEFAULT_ACTIVITY
            ),
            attention=_one_of(  # type: ignore[arg-type]
                data.get("attention"), ATTENTIONS, DEFAULT_ATTENTION
            ),
            private_mood=_one_of(  # type: ignore[arg-type]
                data.get("private_mood"), PRIVATE_MOODS, DEFAULT_MOOD
            ),
            rumination=rumination,
            pending_impulse=pending,
            can_hear=bool(data.get("can_hear", False)),
            last_spoke_at=parse_life_dt(data.get("last_spoke_at")),
            last_event_at=parse_life_dt(data.get("last_event_at")),
            activity_since=parse_life_dt(data.get("activity_since")),
        )
