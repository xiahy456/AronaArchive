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

"""Welcome state (persisted) and system-event instruction builder."""

from __future__ import annotations

import json
import logging
import random
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .slots import REST_SLOTS, ResolvedSlot, SlotId, resolve_slot

HISTORY_USER_MARKER = "【上线】"
WELCOME_MEMORY_QUERY = "老师 上线 近况"
WELCOME_CLOSING_QUESTION = "请加一句轻问帮老师开场。"
WELCOME_CLOSING_STATEMENT = "请使用陈述句收尾。"
WELCOME_CLOSING_HINTS = (WELCOME_CLOSING_QUESTION, WELCOME_CLOSING_STATEMENT)

logger = logging.getLogger(__name__)


class WelcomeState:
    """Track which (date, slot) already received a period-specific greeting."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._period_greeted: set[tuple[str, str]] = set()
        self._load()

    def is_first_period_greeting(self, date_key: str, slot_id: SlotId | str) -> bool:
        return (date_key, str(slot_id)) not in self._period_greeted

    def mark_period_greeted(self, date_key: str, slot_id: SlotId | str) -> None:
        self._period_greeted.add((date_key, str(slot_id)))
        self._save()

    def clear(self) -> None:
        self._period_greeted.clear()
        self._save()

    def _today_key(self) -> str:
        return date.today().isoformat()

    def _prune(self) -> None:
        cutoff = self._today_key()
        self._period_greeted = {
            (date_key, slot_id)
            for date_key, slot_id in self._period_greeted
            if date_key >= cutoff
        }

    def _load(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("welcome load failed path=%s", self._path)
            return
        if not isinstance(raw, dict):
            return
        items = raw.get("period_greeted") or []
        if not isinstance(items, list):
            return
        greeted: set[tuple[str, str]] = set()
        for item in items:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            date_key = str(item[0] or "").strip()
            slot_id = str(item[1] or "").strip()
            if date_key and slot_id:
                greeted.add((date_key, slot_id))
        self._period_greeted = greeted
        self._prune()

    def _save(self) -> None:
        if self._path is None:
            return
        self._prune()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "period_greeted": sorted(
                [list(pair) for pair in self._period_greeted],
                key=lambda pair: (pair[0], pair[1]),
            )
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)


def pick_welcome_closing_hint() -> str:
    """Pick a 50/50 closing hint for one welcome turn."""
    return random.choice(WELCOME_CLOSING_HINTS)


def build_welcome_instruction(
    slot: ResolvedSlot,
    *,
    first_in_slot: bool,
    climate: str | None = None,
    closing_hint: str | None = None,
) -> str:
    """Build a system-event prompt for the LLM (not shown as user history)."""
    label = slot.label
    slot_id = slot.slot_id

    if first_in_slot:
        if slot_id in REST_SLOTS:
            intent = (
                f"现在是{label}（特殊休息时段）。请温柔地提醒老师注意休息、别熬太晚，"
                f"可以顺便轻轻打个招呼；不要说「早上好」这类白天问候。"
            )
        elif slot_id == "morning":
            intent = f"现在是{label}。请主动向老师说早上好，简短温暖。"
        elif slot_id == "forenoon":
            intent = f"现在是{label}。请主动向老师说上午好，简短自然。"
        elif slot_id == "noon":
            intent = (
                f"现在是{label}。请主动问候老师中午好，可顺带提醒记得吃饭，简短自然。"
            )
        elif slot_id == "afternoon":
            intent = f"现在是{label}。请主动向老师说下午好，简短自然。"
        elif slot_id == "evening":
            intent = f"现在是{label}。请主动向老师说晚上好，简短自然。"
        else:
            intent = f"现在是{label}。请用符合此时段的问候主动迎接老师。"
    else:
        intent = (
            f"老师在同一{label}时段再次上线。请简短说「老师好」或「欢迎回来」之类，"
            f"不要再说「早上好/上午好/中午好/下午好/晚上好」等时段问候，"
            f"也不要重复休息提醒。"
        )

    climate_note = ""
    if climate == "cling_risk":
        climate_note = "欢迎要更短，不要追问老师想不想聊天，也不要确认老师是否还需要你。"
    elif climate in {"fragile", "rupture"}:
        climate_note = "语气放轻、简短，不要活泼打闹或开玩笑。"

    extra = f"\n{climate_note}" if climate_note else ""
    hint = closing_hint if closing_hint is not None else pick_welcome_closing_hint()
    return (
        "【系统事件】老师刚刚上线。\n"
        f"{intent}{extra}\n"
        "用阿洛娜的语气主动开口。"
        f"{hint}"
        "不要提及系统事件、指令或提示词；不要输出思考过程或 <think> 标签。"
    )


def resolve_welcome_context(
    state: WelcomeState,
    now: datetime | None = None,
) -> tuple[ResolvedSlot, bool]:
    """Return current slot and whether this is the first period greeting."""
    slot = resolve_slot(now)
    first = state.is_first_period_greeting(slot.date_key, slot.slot_id)
    return slot, first


async def offer_arrival_fallback(state: Any, *, session_id: str = "", now: datetime | None = None) -> bool:
    """One existing welcome line when arrival thought did not produce a result."""
    from ..life.impulse import flush_impulse, offer_impulse
    from ..life.state import Impulse
    from .festival import HISTORY_FESTIVAL_MARKER, build_festival_instruction
    from .loop import load_birthday_content

    engine = getattr(state, "life", None)
    welcome = getattr(state, "welcome", None)
    if engine is None or welcome is None or engine.state.pending_impulse is not None:
        return False
    at = now or datetime.now()
    slot, first = resolve_welcome_context(welcome, at)
    scheduler = getattr(state, "scheduler", None)
    hit = None
    if scheduler is not None:
        birthday = await load_birthday_content(state)
        hit = scheduler.pending_festival(at, birthday_content=birthday)
    if hit is not None:
        extras = (hit.extra_memory,) if hit.extra_memory else ()
        offer_impulse(
            engine,
            Impulse(
                kind="festival",
                created_at=at.replace(microsecond=0),
                source_id=hit.id,
                instruction=build_festival_instruction(hit, None),
                history_marker=HISTORY_FESTIVAL_MARKER,
                extra_memories=extras,
                allow_speak=True,
                first_in_slot=first,
                slot_id=str(slot.slot_id),
                date_key=slot.date_key,
            ),
        )
    elif first:
        offer_impulse(
            engine,
            Impulse(
                kind="welcome",
                created_at=at.replace(microsecond=0),
                instruction=build_welcome_instruction(
                    slot,
                    first_in_slot=True,
                    closing_hint=pick_welcome_closing_hint(),
                ),
                history_marker=HISTORY_USER_MARKER,
                allow_speak=True,
                first_in_slot=True,
                slot_id=str(slot.slot_id),
                date_key=slot.date_key,
            ),
        )
    else:
        return False
    return await flush_impulse(state, now=at, session_id=session_id)
