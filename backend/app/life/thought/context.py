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

"""Load already-committed facts for one thought beat. Does not read the listen buffer."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from ...proactive.care import care_window_specs
from .sources import SourceContext
from .schema import is_thought_history_marker
from .store import PendingTrigger

if TYPE_CHECKING:
    from ...ws_handler import AppState

logger = logging.getLogger(__name__)


def gather_context(
    state: "AppState",
    now: datetime,
    trigger: PendingTrigger,
) -> SourceContext:
    journal = getattr(state, "life_journal", None)
    summaries: list[str] = []
    glance = ""
    glance_at = None
    teacher_at = None
    if journal is not None:
        for entry in getattr(journal, "entries", []) or []:
            text = str(getattr(entry, "summary", "") or "").strip()
            kind = str(getattr(entry, "kind", "") or "")
            if text:
                summaries.append(text)
            if kind == "glance" and text:
                glance = text
                glance_at = getattr(entry, "at", None)
            if kind == "teacher_interrupt":
                teacher_at = getattr(entry, "at", None)
    arona = getattr(state, "arona_memory", None)
    notes: list[tuple[str, datetime | None]] = []
    if arona is not None:
        for note in getattr(arona, "notes", []) or []:
            text = str(getattr(note, "text", "") or "").strip()
            if not text:
                continue
            at = getattr(note, "at", None)
            notes.append((text, at if isinstance(at, datetime) else None))
    turns = _turns(state)
    since_teacher = None
    if isinstance(teacher_at, datetime):
        since_teacher = max(0.0, (now - teacher_at).total_seconds())
    inner = getattr(getattr(state, "life", None), "state", None)
    since_arona = None
    last_spoke = getattr(inner, "last_spoke_at", None)
    if isinstance(last_spoke, datetime):
        since_arona = max(0.0, (now - last_spoke).total_seconds())
    scheduler = getattr(state, "scheduler", None)
    sched_state = getattr(scheduler, "state", None)
    care_done = frozenset(getattr(sched_state, "care_done", []) or [])
    goal_acked = dict(getattr(sched_state, "goal_acked", {}) or {})
    relationship = getattr(getattr(state, "orchestrator", None), "relationship", None)
    climate = ""
    last_act = ""
    if relationship is not None:
        try:
            climate = str(relationship.peek_climate() or "")
        except Exception:
            logger.exception("thought climate read failed")
        last_act = str(getattr(getattr(relationship, "state", None), "last_user_act", "") or "")
    windows = _windows(state)
    goals = _goals(state)
    _picked_glance = _glance_text(trigger, glance, glance_at)
    ledger = getattr(state, "thought", None)
    speak_count = 0
    if getattr(ledger, "speak_day", "") == now.date().isoformat():
        speak_count = int(getattr(ledger, "speak_count", 0) or 0)
    situation = _situation(
        state,
        now,
        goals=goals,
        last_user_act=last_act,
        climate=climate,
        quiet_sec=since_teacher,
        speak_count=speak_count,
    )
    return SourceContext(
        teacher_online=bool(state.hub.all_sessions()),
        climate=climate,
        seconds_since_teacher=since_teacher,
        seconds_since_arona=since_arona,
        journal=tuple(summaries),
        notes=tuple(notes),
        turns=turns,
        ended_turns=turns[-4:],
        goals=goals,
        care_done=care_done,
        goal_acked=goal_acked,
        last_user_act=last_act,
        glance_text=_picked_glance[0],
        glance_at=_picked_glance[1],
        memory_key=trigger.memory_key,
        memory_content=_memory_text(state, trigger),
        already_greeted=_already_greeted(state, now),
        care_windows=windows,
        knowledge=_knowledge(state),
        situation=situation,
    )


def _glance_text(
    trigger: PendingTrigger,
    journal_glance: str,
    journal_at: datetime | None,
) -> tuple[str, datetime | None]:
    if trigger.kind != "glance":
        return "", None
    detail = (trigger.detail or "").strip()
    if detail:
        when = trigger.not_before if isinstance(trigger.not_before, datetime) else journal_at
        return detail, when
    if not journal_glance:
        return "", None
    return journal_glance, journal_at if isinstance(journal_at, datetime) else None


def _memory_text(state: "AppState", trigger: PendingTrigger) -> str:
    if trigger.kind != "memory" or not (trigger.memory_key or "").strip():
        return ""
    memory = getattr(getattr(state, "orchestrator", None), "memory_store", None)
    if memory is None:
        return ""
    try:
        rows = memory.get_entries([trigger.memory_key])
    except Exception:
        logger.exception("thought memory read failed")
        return ""
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        content = str(row.get("content") or "").strip()
        if content:
            return content
    return ""


def _already_greeted(state: "AppState", now: datetime) -> bool:
    welcome = getattr(state, "welcome", None)
    if welcome is None:
        return False
    try:
        from ...proactive.slots import resolve_slot

        slot = resolve_slot(now)
        return not welcome.is_first_period_greeting(slot.date_key, slot.slot_id)
    except Exception:
        logger.exception("thought welcome read failed")
        return False


def _turns(state: "AppState") -> tuple[tuple, ...]:
    conversation = getattr(getattr(state, "orchestrator", None), "conversations", None)
    if conversation is None:
        return ()
    try:
        history = list(conversation.get_history("") or [])
    except Exception:
        logger.exception("thought dialogue read failed")
        return ()
    pairs: list[tuple] = []
    pending_user = ""
    pending_at: datetime | None = None
    pending_method = ""
    for msg in history:
        role = str(msg.get("role") or "")
        content = str(msg.get("content") or "").strip()
        spoken_at = _message_time(msg)
        spoken_method = str(msg.get("method") or "")
        if role == "user":
            if is_thought_history_marker(content):
                continue
            if pending_user:
                pairs.append((pending_user, "", pending_at, None, pending_method, ""))
            pending_user = content
            pending_at = spoken_at
            pending_method = spoken_method
        elif role == "assistant" and content:
            if pending_user:
                pairs.append(
                    (pending_user, content, pending_at, spoken_at, pending_method, spoken_method)
                )
                pending_user = ""
                pending_at = None
                pending_method = ""
            else:
                pairs.append(("", content, None, spoken_at, "", spoken_method))
    if pending_user:
        pairs.append((pending_user, "", pending_at, None, pending_method, ""))
    return tuple(pairs)


def _message_time(msg: dict) -> datetime | None:
    raw = str(msg.get("time") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _windows(state: "AppState") -> tuple[tuple[str, str, str], ...]:
    care = getattr(getattr(getattr(state, "config", None), "proactive", None), "care", None)
    if care is None:
        return ()
    try:
        return tuple(
            (kind, start, end) for kind, start, end in care_window_specs(care)
        )
    except Exception:
        logger.exception("thought care windows failed")
        return ()


def _goals(state: "AppState") -> tuple[tuple[str, str], ...]:
    memory = getattr(getattr(state, "orchestrator", None), "memory_store", None)
    if memory is None:
        return ()
    try:
        rows = memory.list_by_category("goal")
    except Exception:
        logger.exception("thought goal list failed")
        return ()
    found: list[tuple[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or row.get("id") or "").strip()
        content = str(row.get("content") or row.get("text") or "").strip()
        if key and content:
            found.append((key, content))
    return tuple(found)


def _situation(
    state: "AppState",
    now: datetime,
    *,
    goals: tuple[tuple[str, str], ...],
    last_user_act: str,
    climate: str,
    quiet_sec: float | None,
    speak_count: int,
) -> tuple:
    scheduler = getattr(state, "scheduler", None)
    if scheduler is None or not hasattr(scheduler, "situation_facts"):
        return ()
    try:
        from ...proactive.festival import birthday_from_profiles

        birthday = ""
        memory = getattr(getattr(state, "orchestrator", None), "memory_store", None)
        if memory is not None and getattr(getattr(scheduler, "festival_cfg", None), "enabled", False):
            birthday = birthday_from_profiles(memory.list_by_category("profile"))
        moods: list[dict] = []
        if memory is not None and getattr(getattr(scheduler, "mood_cfg", None), "enabled", False):
            moods = [
                row
                for row in (memory.list_by_category("emotional") or [])
                if isinstance(row, dict)
            ]
        facts = scheduler.situation_facts(
            now,
            last_user_act=last_user_act,
            climate=climate,
            goals=[{"key": key, "content": content} for key, content in goals],
            moods=moods,
            birthday_content=birthday,
            quiet_sec=quiet_sec,
            speak_count=speak_count,
        )
    except Exception:
        logger.exception("thought situation read failed")
        return ()
    return tuple(facts)


def _knowledge(state: "AppState"):
    store = getattr(state, "knowledge", None)
    if store is None or not getattr(store, "enabled", False):
        return None

    def _query(text: str) -> list[str]:
        try:
            return list(store.retrieve(text, top_k=2) or [])
        except Exception:
            logger.exception("thought knowledge query failed")
            return []

    return _query
