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
]

Attention = Literal["teacher", "self", "rumination", "diffuse"]

PrivateMood = Literal["calm", "bright", "weary", "preoccupied", "sleepy"]

DEFAULT_ACTIVITY: Activity = "idle_in_classroom"
DEFAULT_ATTENTION: Attention = "diffuse"
DEFAULT_MOOD: PrivateMood = "calm"
MAX_RUMINATION = 2

ACTIVITIES: frozenset[str] = frozenset(
    {
        "idle_in_classroom",
        "looking_at_teacher",
        "thinking",
        "resting",
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
class Rumination:
    """Unspoken concern. Layer 1 does not fill this on the production path."""

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
    can_hear: bool = False
    last_spoke_at: datetime | None = None
    last_event_at: datetime | None = None
    activity_since: datetime | None = None

    def clone(self) -> InnerState:
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
            can_hear=bool(data.get("can_hear", False)),
            last_spoke_at=parse_life_dt(data.get("last_spoke_at")),
            last_event_at=parse_life_dt(data.get("last_event_at")),
            activity_since=parse_life_dt(data.get("activity_since")),
        )
