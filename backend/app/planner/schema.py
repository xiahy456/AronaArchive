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

"""Intent draft parsing, gating, and renderer-facing serialization (V2.4)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..relationship.events import DEFAULT_USER_ACT, normalize_user_act
from .emotions import DEFAULT_EMOTION, normalize_emotion

logger = logging.getLogger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def _as_str(value: object | None, default: str = "") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _as_bool(value: object | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return default


def _as_str_list(value: object | None) -> list[str]:
    """Legacy helper for old card fields ignored after parse."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


@dataclass
class IntentCard:
    """V2.4 intent: draft + emotion + followup_ok + reply_ok + user_act.

    Legacy card fields may still appear in raw JSON; they are parsed then ignored
    for rendering (to_renderer only exposes draft).
    """

    draft: str = ""
    arona_emotion: str = DEFAULT_EMOTION
    followup_ok: bool = False
    reply_ok: bool = True
    user_act: str = DEFAULT_USER_ACT
    life_action: str = ""
    # Legacy (ignored by Renderer; kept so old payloads / tests don't explode)
    user_emotion: str = ""
    topic: str = ""
    stance: str = ""
    must_say: list[str] = field(default_factory=list)
    must_not: list[str] = field(default_factory=list)
    facts_to_use: list[str] = field(default_factory=list)
    tone: str = ""
    length: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentCard:
        draft = _as_str(data.get("draft"))
        reply_ok = _as_bool(data.get("reply_ok"), True)
        followup_ok = _as_bool(data.get("followup_ok"), False)
        if not reply_ok:
            followup_ok = False
        emotion = normalize_emotion(data.get("arona_emotion"))
        return cls(
            draft=draft,
            arona_emotion=emotion,
            followup_ok=followup_ok,
            reply_ok=reply_ok,
            user_act=normalize_user_act(data.get("user_act")),
            life_action=_as_str(data.get("life_action")).lower(),
            user_emotion=_as_str(data.get("user_emotion")),
            topic=_as_str(data.get("topic")),
            stance=_as_str(data.get("stance")),
            must_say=_as_str_list(data.get("must_say")),
            must_not=_as_str_list(data.get("must_not")),
            facts_to_use=_as_str_list(data.get("facts_to_use")),
            tone=_as_str(data.get("tone")),
            length=_as_str(data.get("length")),
        )

    def to_renderer_dict(self) -> dict[str, Any]:
        """Deprecated for V2.4; prefer to_renderer_draft()."""
        return {"draft": self.draft}

    def to_renderer_draft(self) -> str:
        return self.draft.strip()

    def to_renderer_text(self) -> str:
        return self.to_renderer_draft()


def extract_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    candidates = [raw]
    match = _JSON_OBJECT_RE.search(raw)
    if match:
        candidates.append(match.group(0))
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def parse_and_gate_intent(raw_text: str) -> IntentCard | None:
    """Parse planner output into a gated IntentCard, or None on hard failure."""
    data = extract_json_object(raw_text)
    if data is None:
        return None
    card = IntentCard.from_dict(data)
    if card.reply_ok and not card.draft.strip():
        logger.info("planner gate failed: empty draft")
        return None
    return card


LIFE_ACTIONS: frozenset[str] = frozenset(
    {"speak", "continue_activity", "emotion_only"}
)


def resolve_life_action(
    intent: IntentCard | None,
    *,
    suggested_silence: bool = False,
) -> str:
    """Loop-recognized action. reply_ok remains the speak/silence gate."""
    if suggested_silence:
        return "continue_activity"
    if intent is None:
        return "speak"
    raw = (intent.life_action or "").strip().lower()
    if raw == "glance":
        raw = "emotion_only"
    if raw not in LIFE_ACTIONS:
        raw = ""
    if not intent.reply_ok:
        if raw == "emotion_only":
            return "emotion_only"
        if raw == "continue_activity":
            return "continue_activity"
        if intent.arona_emotion != DEFAULT_EMOTION:
            return "emotion_only"
        return "continue_activity"
    return "speak"
