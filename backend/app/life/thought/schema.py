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

"""Parse one inner-thought JSON object. Not an IntentCard."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

_FEELINGS = frozenset({"calm", "bright", "weary", "preoccupied", "sleepy"})
_KEEPS = frozenset({"open", "drop"})
_WAITS = frozenset({"now", "simmer", "later"})
_CONFIDENCE = frozenset({"high", "low"})
_NEEDS = frozenset({"memory", "screen", "knowledge", "recent_talk"})
URGE_KINDS = frozenset(
    {
        "breakfast",
        "lunch",
        "dinner",
        "sleep",
        "festival",
        "goal",
        "mood_followup",
        "idle",
        "welcome",
        "thought",
    }
)
THOUGHT_HISTORY_PREFIX = "她想提起："


def is_thought_history_marker(text: str | None) -> bool:
    """True when this line is Arona's urge, not something the teacher said."""
    return (text or "").strip().startswith(THOUGHT_HISTORY_PREFIX)


@dataclass
class InnerThought:
    focus: str = ""
    thought: str = ""
    feeling: str = ""
    keep: str = ""
    memory_note: str = ""
    forget_id: str = ""
    speak: bool = False
    about: str = ""
    why: str = ""
    wait: str = "now"
    kind: str = "thought"
    confidence: str = ""
    need: list[str] = field(default_factory=list)


def parse_inner(raw: str | None) -> InnerThought | None:
    """Return None when the payload cannot be committed."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    focus = str(data.get("focus") or "").strip()
    thought = str(data.get("thought") or "").strip()
    keep_raw = str(data.get("keep") or "").strip()
    keep = keep_raw if keep_raw in _KEEPS else ""
    if not focus and not thought and not keep:
        return None
    feeling_raw = str(data.get("feeling") or "").strip()
    feeling = feeling_raw if feeling_raw in _FEELINGS else ""
    urge = data.get("urge") if isinstance(data.get("urge"), dict) else {}
    wait_raw = str(urge.get("wait") or "").strip()
    kind_raw = str(urge.get("kind") or "").strip()
    confidence_raw = str(data.get("confidence") or "").strip()
    need_raw = data.get("need") if isinstance(data.get("need"), list) else []
    need = []
    for item in need_raw:
        name = str(item or "").strip()
        if name in _NEEDS and name not in need:
            need.append(name)
    return InnerThought(
        focus=focus,
        thought=thought,
        feeling=feeling,
        keep=keep,
        memory_note=str(data.get("memory_note") or "").strip(),
        forget_id=str(data.get("forget_id") or "").strip(),
        speak=bool(urge.get("speak")),
        about=str(urge.get("about") or "").strip(),
        why=str(urge.get("why") or "").strip(),
        wait=wait_raw if wait_raw in _WAITS else "now",
        kind=kind_raw if kind_raw in URGE_KINDS else "thought",
        confidence=confidence_raw if confidence_raw in _CONFIDENCE else "",
        need=need,
    )
