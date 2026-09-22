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

"""Impulse producer/consumer: motives become urges the life loop may ignore."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from ..proactive.care import (
    CARE_KINDS,
    CARE_MEMORY_QUERY,
    HISTORY_CARE_MARKER,
    care_window_specs,
    in_window,
)
from ..proactive.festival import needs_rest_followup
from ..proactive.scheduler import Motive
from .events import world_event
from .policy import LifeDecision
from .presence import schedule_presence
from .state import Impulse, InnerState, Rumination, MAX_RUMINATION
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
    "mood_followup": 40,
    "idle": 10,
}

_RUMINATE_KINDS: frozenset[str] = frozenset(
    {"breakfast", "lunch", "dinner", "sleep", "goal", "mood_followup"}
)

IMPULSE_HINTS: dict[str, str] = {
    "breakfast": "老师早饭窗口到了",
    "lunch": "老师午饭窗口到了",
    "dinner": "老师晚饭窗口到了",
    "sleep": "老师睡觉窗口到了",
    "goal": "老师还有未完成的计划",
    "mood_followup": "老师提过的心情还记着",
}

_CARE_FACE = "worried"
_DEFAULT_FACE = "curious"


def impulse_priority(kind: str) -> int:
    return int(IMPULSE_PRIORITY.get(kind, 0))


def impulse_from_motive(
    motive: Motive,
    now: datetime,
    *,
    allow_speak: bool,
) -> Impulse:
    hint = IMPULSE_HINTS.get(motive.kind, "")
    source = motive.goal_key or motive.mood_key or motive.festival_id
    return Impulse(
        kind=motive.kind,  # type: ignore[arg-type]
        created_at=now.replace(microsecond=0),
        source_id=source,
        hint=hint,
        instruction=motive.instruction,
        history_marker=motive.history_marker,
        retrieve_memory=motive.retrieve_memory,
        memory_query=motive.memory_query,
        extra_memories=tuple(motive.extra_memories),
        due_soon=motive.due_soon,
        allow_speak=allow_speak,
    )


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
    nxt.rumination = items[-MAX_RUMINATION:]
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


def _climate(state: Any) -> str | None:
    relationship = getattr(getattr(state, "orchestrator", None), "relationship", None)
    if relationship is None:
        return None
    rel_cfg = getattr(getattr(state, "config", None), "proactive", None)
    rel_cfg = getattr(rel_cfg, "relationship", None) if rel_cfg is not None else None
    if rel_cfg is not None and not getattr(rel_cfg, "enabled", True):
        return None
    try:
        return relationship.peek_climate()
    except Exception:
        logger.exception("impulse peek_climate failed")
        return None


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
    """Apply impulse_due and run the effector. Used by the producer and welcome."""
    engine = getattr(state, "life", None)
    if engine is None or engine.state.pending_impulse is None:
        return False
    dt = now or datetime.now()
    decision = apply_impulse_due(engine, now=dt, climate=_climate(state))
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
    if kind in CARE_KINDS:
        return _CARE_FACE
    return _DEFAULT_FACE


def _journal_of(state: Any, engine: Any) -> Any:
    return getattr(state, "journal", None) or getattr(engine, "journal", None)


def _care_kind_of(item_id: str) -> str:
    if not item_id.startswith("imp-"):
        return ""
    kind = item_id[4:]
    return kind if kind in CARE_KINDS else ""


def care_kind_live(
    kind: str,
    created_at: datetime | None,
    now: datetime,
    windows: dict[str, tuple[str, str]],
) -> bool:
    """Care worries live only inside today's window. Other kinds are not care."""
    if kind not in CARE_KINDS:
        return True
    span = windows.get(kind)
    if span is None or created_at is None:
        return False
    if created_at.date() != now.date():
        return False
    return in_window(now, span[0], span[1])


def without_stale_care(
    state: InnerState,
    now: datetime,
    windows: dict[str, tuple[str, str]],
) -> InnerState:
    """Drop meal/sleep rumination, and a matching pending impulse, after the window or the day."""
    kept = [
        item
        for item in state.rumination
        if care_kind_live(_care_kind_of(item.id), item.created_at, now, windows)
    ]
    impulse = state.pending_impulse
    drop_pending = impulse is not None and not care_kind_live(
        impulse.kind, impulse.created_at, now, windows
    )
    if len(kept) == len(state.rumination) and not drop_pending:
        return state
    nxt = state.with_rumination(kept)
    if drop_pending:
        nxt.pending_impulse = None
    return nxt


def expire_stale_care(app_state: Any, now: datetime | None = None) -> None:
    """Persist the drop so a closed care window cannot stay in life.json."""
    engine = getattr(app_state, "life", None)
    if engine is None:
        return
    care_cfg = getattr(
        getattr(getattr(app_state, "config", None), "proactive", None),
        "care",
        None,
    )
    if care_cfg is None:
        return
    at = now or datetime.now()
    windows = {kind: (start, end) for kind, start, end in care_window_specs(care_cfg)}
    nxt = without_stale_care(engine.state, at, windows)
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
    scheduler = getattr(state, "scheduler", None)
    impulse = engine.state.pending_impulse if engine is not None else None
    hint = (impulse.hint if impulse is not None else "") or ""
    if engine is not None and followup != "keep" and engine.state.pending_impulse is not None:
        clear_impulse(engine)
    if followup in {"drop", "mark_fired", "mark_care"} and hint:
        journal = _journal_of(state, engine)
        if journal is not None:
            journal.append("rumination", f"没说出口：{hint}", now)
    if scheduler is None or followup in {"keep", "drop"}:
        return
    kind = decision.impulse_kind
    source_id = decision.impulse_source_id
    due_soon = decision.impulse_due_soon
    if followup == "mark_care" and kind in CARE_KINDS:
        scheduler.mark_care_addressed(kind, now)
        logger.info("impulse withheld care kind=%s", kind)
        return
    if followup == "mark_fired" and kind:
        scheduler.mark_fired(
            kind,
            now,
            goal_key=source_id if kind == "goal" else "",
            mood_key=source_id if kind == "mood_followup" else "",
            festival_id=source_id if kind == "festival" else "",
            due_soon=due_soon,
        )
        logger.info("impulse withheld fired kind=%s", kind)


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
    if target is None:
        logger.info("impulse speak deferred kind=%s reason=busy_or_no_session", impulse.kind)
        return False
    session_id, send = target
    climate = _climate(state)
    interrupt_ctx = engine.state.clone()
    hub.set_busy(session_id, True)
    spoke = False
    try:
        result = await orchestrator.handle_initiate(
            session_id=session_id,
            kind=impulse.kind,
            instruction=impulse.instruction,
            history_marker=impulse.history_marker,
            send=send,
            retrieve_memory=impulse.retrieve_memory,
            memory_query=impulse.memory_query,
            extra_memories=list(impulse.extra_memories),
            climate=climate,
            interrupt_ctx=interrupt_ctx,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("impulse speak failed kind=%s", impulse.kind)
        result = "failed"
    finally:
        hub.set_busy(session_id, False)

    scheduler = getattr(state, "scheduler", None)
    if result == "sent":
        spoke = True
        snapshot = impulse
        clear_impulse(engine)
        if scheduler is not None:
            if snapshot.kind == "welcome":
                scheduler.note_proactive(now)
            else:
                scheduler.mark_fired(
                    snapshot.kind,  # type: ignore[arg-type]
                    now,
                    goal_key=snapshot.source_id if snapshot.kind == "goal" else "",
                    mood_key=snapshot.source_id if snapshot.kind == "mood_followup" else "",
                    festival_id=snapshot.source_id if snapshot.kind == "festival" else "",
                    due_soon=snapshot.due_soon,
                )
        welcome = getattr(state, "welcome", None)
        if (
            snapshot.first_in_slot
            and welcome is not None
            and snapshot.date_key
            and snapshot.slot_id
            and snapshot.kind in {"welcome", "festival"}
        ):
            welcome.mark_period_greeted(snapshot.date_key, snapshot.slot_id)
        logger.info("impulse spoke kind=%s session=%s", snapshot.kind, session_id)
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
        if snapshot.kind == "festival" and needs_rest_followup(now):
            _enqueue_sleep_followup(state, now)
        return True
    if result == "declined":
        kind = impulse.kind
        clear_impulse(engine)
        if scheduler is not None and kind in CARE_KINDS:
            scheduler.mark_care_addressed(kind, now)
        logger.info("impulse declined kind=%s session=%s", kind, session_id)
        return False
    logger.warning("impulse generate failed kind=%s (not marked)", impulse.kind)
    return spoke


def _enqueue_sleep_followup(state: Any, now: datetime) -> None:
    from ..proactive.care import build_care_instruction

    engine = getattr(state, "life", None)
    scheduler = getattr(state, "scheduler", None)
    if engine is None or scheduler is None:
        return
    if "sleep" in getattr(scheduler.state, "care_done", []):
        return
    climate = _climate(state)
    impulse = Impulse(
        kind="sleep",
        created_at=now.replace(microsecond=0),
        hint=IMPULSE_HINTS["sleep"],
        instruction=build_care_instruction("sleep", climate),
        history_marker=HISTORY_CARE_MARKER,
        retrieve_memory=True,
        memory_query=CARE_MEMORY_QUERY,
        allow_speak=True,
    )
    offer_impulse(engine, impulse)
    logger.info("impulse queued sleep after festival")


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
    "impulse_from_motive",
    "impulse_priority",
    "merge_impulse",
    "offer_impulse",
    "schedule_impulse_delivery",
]
