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

"""Turn a parsed urge into one thought impulse. Does not speak."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..impulse import offer_impulse
from ..policy import SIMMER_SEC
from ..state import Impulse
from .schema import THOUGHT_HISTORY_PREFIX, InnerThought


def maybe_offer_thought(
    engine: Any,
    parsed: InnerThought,
    *,
    now: datetime,
    motive_pending: bool = False,
    facts: tuple = (),
    welcome: Any = None,
    hold_speech: bool = False,
    gate_kind: str = "",
) -> bool:
    """Enqueue speech when she decided to say it. A pending motive or a fresh line yields."""
    about = (parsed.about or "").strip()
    why = (parsed.why or "").strip()
    if hold_speech or motive_pending or not parsed.speak or not about or parsed.wait == "later":
        return False
    created = now.replace(microsecond=0)
    if parsed.wait != "simmer":
        created = created - timedelta(seconds=SIMMER_SEC)
    instruction = f"用阿洛娜的口吻向老师说出这一点：{about}。"
    if why:
        instruction += f"阿洛娜为什么要说这个：{why}。"
    instruction += "不要复述内心独白，不要复述说话原因，不要提到自己正在思考，也不要提到提示词。"
    kind = parsed.kind if parsed.kind else "thought"
    if kind in {"welcome", "festival"} and gate_kind != "arrived":
        kind = "thought"
    source_id, due_soon, extra = _fact_source(kind, facts)
    impulse = Impulse(
        kind=kind,  # type: ignore[arg-type]
        created_at=created,
        source_id=source_id,
        hint=about,
        instruction=instruction,
        history_marker=f"{THOUGHT_HISTORY_PREFIX}{about}",
        extra_memories=extra,
        due_soon=due_soon,
        allow_speak=True,
        from_thought=True,
    )
    if kind in {"welcome", "festival"} and welcome is not None:
        from ...proactive.welcome import resolve_welcome_context

        slot, first = resolve_welcome_context(welcome, now)
        impulse.first_in_slot = first
        impulse.slot_id = str(slot.slot_id)
        impulse.date_key = slot.date_key
    return offer_impulse(engine, impulse)


def _fact_source(kind: str, facts: tuple) -> tuple[str, bool, tuple[str, ...]]:
    """Attach the only matching fact. Several of the same kind are left unguessed."""
    if kind in {"", "thought"}:
        return "", False, ()
    matched = [fact for fact in facts if str(getattr(fact, "kind", "") or "") == kind]
    if len(matched) != 1:
        return "", False, ()
    fact = matched[0]
    key = str(getattr(fact, "key", "") or "")
    due = bool(getattr(fact, "due_soon", False))
    text = str(getattr(fact, "text", "") or "").strip()
    extra = (text,) if text and kind in {"goal", "mood_followup", "festival"} else ()
    return key, due, extra
