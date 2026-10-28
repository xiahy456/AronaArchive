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

"""Impulse producer/consumer: motives become urges the life loop may ignore."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from ..channel import QQ_SESSION_ID, hold_channel_for
from .events import world_event
from .policy import LifeDecision
from .presence import schedule_presence
from .state import Impulse, InnerState, Rumination, retain_rumination
from .turn import apply_turn_action

logger = logging.getLogger(__name__)

IMPULSE_PRIORITY: dict[str, int] = {
    "welcome": 100,
    "festival": 90,
    "breakfast": 80,
    "lunch": 80,
    "dinner": 80,
    "sleep": 80,
    "goal": 50,
    "commitment": 70,
    "mood_followup": 40,
    "thought": 30,
    "idle": 10,
}

_RUMINATE_KINDS: frozenset[str] = frozenset(
    {"breakfast", "lunch", "dinner", "sleep", "goal", "commitment", "mood_followup"}
)

IMPULSE_HINTS: dict[str, str] = {
    "breakfast": "老师早饭窗口到了",
    "lunch": "老师午饭窗口到了",
    "dinner": "老师晚饭窗口到了",
    "sleep": "老师睡觉窗口到了",
    "goal": "老师还有未完成的计划",
    "commitment": "到了该提醒老师的时候",
    "mood_followup": "老师提过的心情还记着",
}

_CARE_FACE = "worried"
_DEFAULT_FACE = "curious"
_CARE_KINDS = frozenset({"breakfast", "lunch", "dinner", "sleep"})


def impulse_priority(kind: str) -> int:
    return int(IMPULSE_PRIORITY.get(kind, 0))


def _with_rumination(state: InnerState, impulse: Impulse) -> InnerState:
    if impulse.kind not in _RUMINATE_KINDS:
        return state
    content = (impulse.hint or IMPULSE_HINTS.get(impulse.kind) or "").strip()
    if not content:
        return state
    rum_id = f"imp-{impulse.kind}"
    items = [item for item in state.rumination if item.id != rum_id]
    items.append(Rumination(id=rum_id, content=content, created_at=impulse.created_at))
    nxt = state.clone()
    nxt.rumination = retain_rumination(items)
    return nxt


def merge_impulse(state: InnerState, impulse: Impulse) -> tuple[InnerState, bool]:
    """Attach impulse if empty or higher priority. Same kind keeps the original timer."""
    existing = state.pending_impulse
    if existing is not None:
        if existing.kind == impulse.kind:
            return state.clone(), True
        if impulse_priority(impulse.kind) <= impulse_priority(existing.kind):
            return state.clone(), False
    nxt = state.clone()
    nxt.pending_impulse = impulse
    nxt = _with_rumination(nxt, impulse)
    nxt.pending_impulse = impulse
    return nxt, True


def maybe_offer_commitment(state: Any, now: datetime) -> None:
    """Queue one due promise. Fired only after the line is actually sent."""
    store = getattr(state, "commitment_store", None)
    engine = getattr(state, "life", None)
    if store is None or engine is None:
        return
    cfg = getattr(getattr(state, "config", None), "memory", None)
    if cfg is not None and not getattr(cfg, "commitment_enabled", True):
        return
    pending = getattr(getattr(engine, "state", None), "pending_impulse", None)
    if pending is not None and getattr(pending, "kind", "") == "commitment":
        return
    due = store.due(now)
    if not due:
        return
    item = due[0]
    what = (item.what or "").strip()
    if not what:
        return
    offer_impulse(
        engine,
        Impulse(
            kind="commitment",
            created_at=now,
            source_id=item.id,
            hint=what,
            extra_memories=(what,),
        ),
    )


def _speak_memories(state: Any, impulse: Impulse, now: datetime) -> list[str]:
    """Commitment reminders carry the promise and whether today already heard it."""
    extras = [str(item).strip() for item in impulse.extra_memories if str(item).strip()]
    if impulse.kind != "commitment":
        return extras
    store = getattr(state, "commitment_store", None)
    item = None
    if store is not None and impulse.source_id:
        try:
            item = store.get(impulse.source_id)
        except Exception:
            logger.exception("commitment lookup failed id=%s", impulse.source_id)
    what = (getattr(item, "what", "") or impulse.hint or "").strip()
    fired_today = bool(item is not None and item.last_fired_day == now.date().isoformat())
    status = "今天已经提醒过" if fired_today else "今天还没有提醒"
    line = f"{what}。{status}。" if what else status
    if line not in extras:
        extras.insert(0, line)
    return extras


def _mark_commitment_fired(state: Any, item_id: str, now: datetime) -> None:
    store = getattr(state, "commitment_store", None)
    if store is None:
        return
    try:
        store.mark_fired(item_id, now)
    except Exception:
        logger.exception("commitment mark_fired failed id=%s", item_id)


def offer_impulse(engine: Any, impulse: Impulse) -> bool:
    """Write a pending impulse onto the engine. Does not speak."""
    if engine is None:
        return False
    nxt, accepted = merge_impulse(engine.state, impulse)
    if nxt.to_dict() != engine.state.to_dict():
        engine.state = nxt
        try:
            engine.store.save(engine.state)
        except Exception:
            logger.exception("life impulse persist failed kind=%s", impulse.kind)
        journal = getattr(engine, "journal", None)
        if journal is not None:
            journal.note_inner(
                engine.state,
                arona=getattr(engine, "arona_memory", None),
            )
    return accepted


def clear_impulse(engine: Any) -> None:
    if engine is None or engine.state.pending_impulse is None:
        return
    nxt = engine.state.clone()
    nxt.pending_impulse = None
    engine.state = nxt
    try:
        engine.store.save(engine.state)
    except Exception:
        logger.exception("life impulse clear failed")


def apply_impulse_due(engine: Any, *, now: datetime | None = None, climate: str | None = None) -> LifeDecision | None:
    if engine is None:
        return None
    return engine.apply(
        world_event("impulse_due", at=now),
        climate=climate,
    )


async def flush_impulse(
    state: Any,
    *,
    now: datetime | None = None,
    session_id: str = "",
) -> bool:
    """Apply impulse_due and run the effector."""
    engine = getattr(state, "life", None)
    if engine is None or engine.state.pending_impulse is None:
        return False
    dt = now or datetime.now()
    decision = apply_impulse_due(engine, now=dt)
    return await deliver_impulse(state, decision, now=dt, session_id=session_id)


def _pick_session(state: Any, session_id: str = "") -> tuple[str, Any] | None:
    hub = getattr(state, "hub", None)
    if hub is None:
        return None
    if session_id:
        send = hub.get(session_id)
        if send is not None and not hub.is_busy(session_id):
            return session_id, send
    idle = hub.idle_sessions()
    if idle:
        return idle[0]
    return None


def _emotion_for(kind: str) -> str:
    if kind in _CARE_KINDS:
        return _CARE_FACE
    return _DEFAULT_FACE


def _journal_of(state: Any, engine: Any) -> Any:
    return getattr(state, "journal", None) or getattr(engine, "journal", None)


def _care_kind_of(item_id: str) -> str:
    if not item_id.startswith("imp-"):
        return ""
    kind = item_id[4:]
    return kind if kind in _CARE_KINDS else ""


def care_kind_live(
    kind: str,
    created_at: datetime | None,
    now: datetime,
) -> bool:
    """Care worries live through the calendar day they were written."""
    if kind not in _CARE_KINDS:
        return True
    if created_at is None:
        return False
    return created_at.date() == now.date()


def without_stale_care(state: InnerState, now: datetime) -> InnerState:
    """Drop meal/sleep rumination, and an unsent care reminder, after the day.

    A line she already decided to say (from_thought) stays until the life loop speaks it.
    """
    kept = [
        item
        for item in state.rumination
        if care_kind_live(_care_kind_of(item.id), item.created_at, now)
    ]
    impulse = state.pending_impulse
    drop_pending = (
        impulse is not None
        and not impulse.from_thought
        and not care_kind_live(impulse.kind, impulse.created_at, now)
    )
    if len(kept) == len(state.rumination) and not drop_pending:
        return state
    nxt = state.with_rumination(kept)
    if drop_pending:
        nxt.pending_impulse = None
    return nxt


def expire_stale_care(app_state: Any, now: datetime | None = None) -> None:
    """Persist the drop so yesterday's care worry cannot stay in life.json."""
    engine = getattr(app_state, "life", None)
    if engine is None:
        return
    at = now or datetime.now()
    nxt = without_stale_care(engine.state, at)
    if nxt.to_dict() == engine.state.to_dict():
        return
    engine.state = nxt
    try:
        engine.store.save(engine.state)
    except Exception:
        logger.exception("life save after care rumination expiry failed")
    journal = _journal_of(app_state, engine)
    if journal is not None:
        journal.note_inner(
            engine.state,
            now=at,
            arona=getattr(app_state, "arona_memory", None)
            or getattr(engine, "arona_memory", None),
        )
    logger.info("care rumination expired")


def _drop_spoken_rumination(engine: Any, kind: str) -> None:
    rum_id = f"imp-{kind}"
    items = [item for item in engine.state.rumination if item.id != rum_id]
    if len(items) == len(list(engine.state.rumination)):
        return
    engine.state = engine.state.with_rumination(items)
    try:
        engine.store.save(engine.state)
    except Exception:
        logger.exception("life save after rumination end failed")


def _apply_followup(state: Any, decision: LifeDecision, *, now: datetime) -> None:
    followup = decision.impulse_followup
    engine = getattr(state, "life", None)
    impulse = engine.state.pending_impulse if engine is not None else None
    hint = (impulse.hint if impulse is not None else "") or ""
    if engine is not None and followup != "keep" and engine.state.pending_impulse is not None:
        clear_impulse(engine)
    if followup in {"drop", "mark_fired", "mark_care"} and hint:
        journal = _journal_of(state, engine)
        if journal is not None:
            journal.append("rumination", f"没说出口：{hint}", now)


def _close_spoken_thought(state: Any, engine: Any, now: datetime) -> None:
    """Drop the spoken thought concern and count the speech. Does not mark care."""
    from .state import THOUGHT_RUMINATION_PREFIX
    from .thought.store import ThoughtLedger

    items = [
        item
        for item in engine.state.rumination
        if not item.id.startswith(THOUGHT_RUMINATION_PREFIX)
    ]
    if len(items) != len(list(engine.state.rumination)):
        engine.state = engine.state.with_rumination(items)
        try:
            engine.store.save(engine.state)
        except Exception:
            logger.exception("life save after thought speech failed")
    ledger = getattr(state, "thought", None)
    if not isinstance(ledger, ThoughtLedger):
        return
    stamp = now.replace(microsecond=0)
    if ledger.focus is not None:
        ledger.focus.spoken = True
    day = stamp.date().isoformat()
    if ledger.speak_day != day:
        ledger.speak_day = day
        ledger.speak_count = 0
    ledger.speak_count += 1
    ledger.last_thought_spoke_at = stamp
    store = getattr(state, "thought_store", None)
    if store is not None:
        try:
            store.save(ledger)
        except Exception:
            logger.exception("thought save after speech failed")


def _qq_ready(state: Any) -> bool:
    link = getattr(state, "napcat", None)
    return bool(link is not None and getattr(link, "connected", False))


def _save_impulse(engine: Any) -> None:
    store = getattr(engine, "store", None)
    if store is None:
        return
    try:
        store.save(engine.state)
    except Exception:
        logger.exception("life save after impulse hold failed")


async def _noop_send(_payload: dict[str, Any]) -> None:
    return None


_LEGACY_WHY_MARKER = "阿洛娜为什么要说这个："


def _thought_why(impulse: Impulse) -> str:
    """Prefer the stored reason. Older impulses kept it inside instruction."""
    why = (getattr(impulse, "why", "") or "").strip()
    if why:
        return why
    instruction = (getattr(impulse, "instruction", "") or "").strip()
    if _LEGACY_WHY_MARKER not in instruction:
        return ""
    rest = instruction.split(_LEGACY_WHY_MARKER, 1)[1]
    return rest.split("。", 1)[0].strip()


async def _speak_impulse(
    state: Any,
    *,
    now: datetime,
    session_id: str = "",
) -> bool:
    engine = getattr(state, "life", None)
    hub = getattr(state, "hub", None)
    orchestrator = getattr(state, "orchestrator", None)
    if engine is None or hub is None or orchestrator is None:
        return False
    expire_stale_care(state, now)
    impulse = engine.state.pending_impulse
    if impulse is None:
        return False
    target = _pick_session(state, session_id)
    qq_up = _qq_ready(state)
    client_up = target is not None
    hold = (impulse.await_channel or "").strip()
    if hold == "client" and not client_up:
        logger.info("impulse held kind=%s channel=client", impulse.kind)
        return False
    if hold == "napcat" and not qq_up:
        logger.info("impulse held kind=%s channel=napcat", impulse.kind)
        return False
    if not client_up and not qq_up:
        logger.info("impulse speak deferred kind=%s reason=no_channel", impulse.kind)
        return False
    if hold:
        impulse.await_channel = ""
        _save_impulse(engine)
    if target is None:
        session_id, send = QQ_SESSION_ID, _noop_send
        busy_id = QQ_SESSION_ID
    else:
        session_id, send = target
        busy_id = session_id
    interrupt_ctx = engine.state.clone()
    motive_block = ""
    if impulse.from_thought:
        from ..planner.prompts import build_thought_motive_block

        motive_block = build_thought_motive_block(impulse.hint, _thought_why(impulse))
    if busy_id:
        hub.set_busy(busy_id, True)
    spoke = False
    try:
        result = await orchestrator.handle_initiate(
            session_id=session_id,
            kind=impulse.kind,
            instruction="" if motive_block else impulse.instruction,
            history_marker=impulse.history_marker,
            send=send,
            retrieve_memory=impulse.retrieve_memory,
            memory_query=impulse.memory_query,
            extra_memories=_speak_memories(state, impulse, now),
            interrupt_ctx=interrupt_ctx,
            client_online=client_up,
            motive_block=motive_block,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("impulse speak failed kind=%s", impulse.kind)
        result = "failed"
    finally:
        if busy_id:
            hub.set_busy(busy_id, False)

    if result == "deferred":
        impulse.await_channel = hold_channel_for(
            getattr(orchestrator, "last_outbound_method", "")
        )
        _save_impulse(engine)
        logger.info(
            "impulse held kind=%s channel=%s",
            impulse.kind,
            impulse.await_channel,
        )
        return False
    if result == "sent":
        spoke = True
        snapshot = impulse
        clear_impulse(engine)
        logger.info("impulse spoke kind=%s session=%s", snapshot.kind, session_id)
        if snapshot.from_thought or snapshot.kind == "thought":
            _close_spoken_thought(state, engine, now)
        if snapshot.kind == "commitment" and snapshot.source_id:
            _mark_commitment_fired(state, snapshot.source_id, now)
        _drop_spoken_rumination(engine, snapshot.kind)
        journal = _journal_of(state, engine)
        if journal is not None:
            journal.note_inner(
                engine.state,
                now=now,
                arona=getattr(state, "arona_memory", None)
                or getattr(engine, "arona_memory", None),
            )
            line = str(getattr(orchestrator, "last_initiate_text", "") or "").strip()
            summary = f"开口（{snapshot.kind}）"
            if line:
                summary = f"{summary}：{line}"
            journal.append("spoke", summary, now)
        return True
    if result == "declined":
        clear_impulse(engine)
        logger.info("impulse declined kind=%s session=%s", impulse.kind, session_id)
        return False
    logger.warning("impulse generate failed kind=%s (not marked)", impulse.kind)
    return spoke


async def deliver_impulse(
    state: Any,
    decision: LifeDecision | None = None,
    *,
    now: datetime | None = None,
    session_id: str = "",
) -> bool:
    """Run the effector for the latest life decision. Returns True if a line was sent."""
    engine = getattr(state, "life", None)
    if engine is None:
        return False
    if getattr(engine, "_impulse_busy", False):
        return False
    engine._impulse_busy = True
    try:
        return await _deliver_impulse_body(
            state, decision, now=now, session_id=session_id
        )
    finally:
        engine._impulse_busy = False


async def _deliver_impulse_body(
    state: Any,
    decision: LifeDecision | None = None,
    *,
    now: datetime | None = None,
    session_id: str = "",
) -> bool:
    """Run the effector for the latest life decision. Returns True if a line was sent."""
    engine = getattr(state, "life", None)
    if engine is None:
        return False
    dt = now or datetime.now()
    resolved = decision or getattr(engine, "last_decision", None)
    if resolved is None:
        return False
    action = resolved.action
    if action == "glance":
        action = "emotion_only"
    impulse = engine.state.pending_impulse
    kind = impulse.kind if impulse is not None else ""

    if action == "speak":
        return await _speak_impulse(state, now=dt, session_id=session_id)
    if action == "emotion_only":
        apply_turn_action(state, "emotion_only", _emotion_for(kind))
        _apply_followup(state, resolved, now=dt)
        schedule_presence(state)
        return False
    if action in {"continue_activity", "shift_activity"}:
        schedule_presence(state)
    return False


async def _deliver_safe(state: Any, decision: LifeDecision | None, now: datetime | None) -> None:
    try:
        await deliver_impulse(state, decision, now=now)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("impulse deliver failed")


def schedule_impulse_delivery(
    state: Any,
    decision: LifeDecision | None = None,
    *,
    now: datetime | None = None,
) -> None:
    engine = getattr(state, "life", None)
    if engine is None:
        return
    resolved = decision or getattr(engine, "last_decision", None)
    if resolved is None:
        return
    if resolved.action not in {"speak", "emotion_only", "glance"}:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        _deliver_safe(state, resolved, now),
        name="life-impulse",
    )


# Re-export simmer constant for tests.
__all__ = [
    "IMPULSE_HINTS",
    "IMPULSE_PRIORITY",
    "apply_impulse_due",
    "clear_impulse",
    "deliver_impulse",
    "flush_impulse",
    "impulse_priority",
    "merge_impulse",
    "offer_impulse",
    "schedule_impulse_delivery",
]
