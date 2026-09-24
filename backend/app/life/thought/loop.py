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

"""Thought beat. After the gate allows, one private result is written, with at most one second look."""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..journal import TEACHER_OPENED_SUMMARY
from ..policy import SIMMER_SEC
from ..state import InnerState
from .client import ThoughtClient
from .commit import commit_inner
from .context import gather_context
from .gate import ThoughtClocks, ThoughtDecision, ThoughtGateFacts, decide_thought
from .prompt import second_hop_system
from .schema import InnerThought, parse_inner
from .sources import SourceContext, fill_need, select_sources
from .speech import maybe_offer_thought
from .store import PendingTrigger, ThoughtLedger

if TYPE_CHECKING:
    from ...ws_handler import AppState

logger = logging.getLogger(__name__)

DEFAULT_TICK_SEC = 60.0


@dataclass
class SpontaneousGap:
    """One rolled wait. Re-rolled when presence or the last thought time changes."""

    online: bool | None = None
    anchored_at: datetime | None = None
    gap_sec: float = 0.0
    rolled: bool = False


def format_gate_log(decision: ThoughtDecision) -> str:
    if decision.kind:
        return f"thought gate kind={decision.kind}"
    return f"thought gate skip={decision.skip_reason or 'not_due'}"


def thought_tick_sec(state: "AppState") -> float:
    cfg = getattr(getattr(state.config, "life", None), "thought", None)
    raw = getattr(cfg, "tick_sec", DEFAULT_TICK_SEC) if cfg is not None else DEFAULT_TICK_SEC
    return max(0.2, float(raw))


async def run_thought_loop(state: "AppState") -> None:
    while True:
        await asyncio.sleep(thought_tick_sec(state))
        try:
            await thought_tick_once(state)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("thought tick failed")


async def thought_tick_once(
    state: "AppState",
    now: datetime | None = None,
    *,
    complete=None,
    source_context=None,
) -> ThoughtDecision:
    """Log the gate, then think once when a kind is selected and sources are ready."""
    at = now or datetime.now()
    engine = getattr(state, "life", None)
    if engine is None:
        decision = ThoughtDecision(skip_reason="no_life")
        logger.info("%s", format_gate_log(decision))
        return decision
    inner = engine.state
    ledger = getattr(state, "thought", None)
    if not isinstance(ledger, ThoughtLedger):
        ledger = ThoughtLedger()
    cfg = state.config.life.thought
    online = bool(state.hub.all_sessions())
    facts = ThoughtGateFacts(
        teacher_online=online,
        in_flight=bool(getattr(state, "thought_in_flight", False)),
        session_busy=bool(state.hub.any_busy()),
        listen_uncommitted=bool(getattr(state, "listen_uncommitted", False)),
        motive_pending=await _motive_pending(state, at),
        resting=_resting(at),
        consolidated_today=ledger.consolidated_day == at.date().isoformat(),
        teacher_just_spoke=_teacher_just_spoke(state, at),
        spontaneous_gap_sec=_gap_sec(state, online=online, last_thought_at=ledger.last_thought_at, cfg=cfg),
    )
    clocks = ThoughtClocks(
        revisit_after_sec=float(cfg.revisit_after_sec),
        refractory_sec=float(cfg.refractory_sec),
        simmer_sec=float(SIMMER_SEC),
    )
    decision = decide_thought(at, inner if isinstance(inner, InnerState) else InnerState(), ledger, facts, clocks)
    logger.info("%s", format_gate_log(decision))
    if not decision.kind:
        return decision
    state.thought_in_flight = True
    try:
        await _think(
            state,
            at,
            inner if isinstance(inner, InnerState) else InnerState(),
            ledger,
            decision,
            complete=complete,
            source_context=source_context,
            motive_pending=facts.motive_pending,
        )
    finally:
        state.thought_in_flight = False
    return decision


async def _think(
    state: "AppState",
    now: datetime,
    inner: InnerState,
    ledger: ThoughtLedger,
    decision: ThoughtDecision,
    *,
    complete,
    source_context,
    motive_pending: bool = False,
) -> None:
    trigger = decision.queued or PendingTrigger(
        kind=decision.kind, focus_id=decision.focus_id
    )
    ctx = source_context if source_context is not None else gather_context(state, now, trigger)
    sources = select_sources(trigger, now, inner, ledger, ctx)
    if sources.cancelled or not (sources.text or "").strip():
        logger.info("thought sources cancelled kind=%s", decision.kind)
        return
    caller = complete
    if caller is None:
        planner = getattr(getattr(state, "config", None), "planner", None)
        if planner is None or not ThoughtClient(planner).enabled:
            logger.info("thought model skipped reason=disabled_or_no_key")
            return
        caller = ThoughtClient(planner).complete
    raw = await _invoke(caller, sources.text)
    parsed = parse_inner(raw)
    if parsed is None:
        logger.info("thought parse failed")
        return
    if _needs_second_hop(parsed):
        second_raw = await _invoke(
            caller,
            _second_user(sources.text, raw or "", parsed, ctx, now),
            system=second_hop_system(),
        )
        second = parse_inner(second_raw)
        if second is None:
            logger.info("thought second hop failed; keeping the first")
        else:
            parsed = second
    next_inner = commit_inner(
        now=now,
        inner=inner,
        ledger=ledger,
        parsed=parsed,
        journal=getattr(state, "life_journal", None),
        arona=getattr(state, "arona_memory", None),
        queued=trigger,
    )
    engine = state.life
    engine.state = next_inner
    store = getattr(engine, "store", None)
    if store is not None:
        store.save(next_inner)
    state.thought = ledger
    thought_store = getattr(state, "thought_store", None)
    if thought_store is not None:
        thought_store.save(ledger)
    maybe_offer_thought(
        engine,
        parsed,
        now=now,
        motive_pending=motive_pending,
    )


def _needs_second_hop(parsed: InnerThought) -> bool:
    """One more look when she is unsure about speaking, or she named a missing section."""
    if parsed.confidence == "low" and parsed.speak:
        return True
    return bool(parsed.need)


def _second_user(
    text: str,
    raw: str,
    parsed: InnerThought,
    ctx: SourceContext | None,
    now: datetime,
) -> str:
    """Original material, sections she asked for, then the first JSON unchanged."""
    hop_ctx = ctx
    focus = (parsed.focus or "").strip()
    if hop_ctx is not None and focus:
        hop_ctx = replace(hop_ctx, focus_text=focus)
    filled = fill_need(text, parsed.need, hop_ctx, now=now)
    previous = (raw or "").strip()
    if not previous:
        return filled
    if not filled:
        return f"【上一次结果】\n{previous}"
    return f"{filled}\n\n【上一次结果】\n{previous}"


async def _invoke(caller: Any, user_text: str, *, system: str | None = None) -> Any:
    if system is not None and _accepts_system(caller):
        return await caller(user_text, system=system)
    return await caller(user_text)


def _accepts_system(caller: Any) -> bool:
    try:
        params = inspect.signature(caller).parameters
    except (TypeError, ValueError):
        return False
    if "system" in params:
        return True
    return any(item.kind == inspect.Parameter.VAR_KEYWORD for item in params.values())


def _gap_sec(state: "AppState", *, online: bool, last_thought_at: datetime | None, cfg: object) -> float:
    holder = getattr(state, "thought_spontaneous_gap", None)
    if not isinstance(holder, SpontaneousGap):
        holder = SpontaneousGap()
        state.thought_spontaneous_gap = holder
    if (
        not holder.rolled
        or holder.online != online
        or holder.anchored_at != last_thought_at
    ):
        if online:
            lo = float(getattr(cfg, "spontaneous_online_min_sec", 240))
            hi = float(getattr(cfg, "spontaneous_online_max_sec", 600))
        else:
            lo = float(getattr(cfg, "spontaneous_away_min_sec", 900))
            hi = float(getattr(cfg, "spontaneous_away_max_sec", 1800))
        if hi < lo:
            lo, hi = hi, lo
        holder.gap_sec = lo if lo == hi else random.uniform(lo, hi)
        holder.online = online
        holder.anchored_at = last_thought_at
        holder.rolled = True
    return holder.gap_sec


def _teacher_just_spoke(state: "AppState", now: datetime) -> bool:
    journal = getattr(state, "journal", None)
    latest: datetime | None = None
    for entry in getattr(journal, "entries", []) or []:
        if str(getattr(entry, "kind", "") or "") != "teacher_interrupt":
            continue
        if str(getattr(entry, "summary", "") or "") != TEACHER_OPENED_SUMMARY:
            continue
        spoken_at = getattr(entry, "at", None)
        if isinstance(spoken_at, datetime) and (latest is None or spoken_at > latest):
            latest = spoken_at
    if latest is None:
        return False
    return (now - latest).total_seconds() <= DEFAULT_TICK_SEC


def _resting(now: datetime) -> bool:
    from ...proactive.slots import REST_SLOTS, resolve_slot

    return resolve_slot(now).slot_id in REST_SLOTS


async def _motive_pending(state: "AppState", now: datetime) -> bool:
    scheduler = getattr(state, "scheduler", None)
    if scheduler is None:
        return False
    try:
        from ...proactive.loop import load_birthday_content

        relationship = getattr(getattr(state, "orchestrator", None), "relationship", None)
        last_user_act = "other"
        climate = None
        rel_cfg = getattr(getattr(state.config, "proactive", None), "relationship", None)
        if relationship is not None and (rel_cfg is None or getattr(rel_cfg, "enabled", True)):
            last_user_act = relationship.state.last_user_act or "other"
            climate = relationship.peek_climate()
        birthday = await load_birthday_content(state)
        goals: list[dict] = []
        moods: list[dict] = []
        memory = getattr(getattr(state, "orchestrator", None), "memory_store", None)
        if memory is not None and getattr(scheduler.goal_cfg, "enabled", False):
            goals = await asyncio.to_thread(memory.list_by_category, "goal")
        if memory is not None and getattr(scheduler.mood_cfg, "enabled", False):
            moods = await asyncio.to_thread(memory.list_by_category, "emotional")
        motive = scheduler.pick_motive(
            now,
            last_user_act=last_user_act,
            climate=climate,
            goals=goals,
            moods=moods,
            birthday_content=birthday,
        )
        return motive is not None
    except Exception:
        logger.exception("thought motive check failed")
        return False
