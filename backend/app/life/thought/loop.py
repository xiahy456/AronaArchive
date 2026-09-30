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
    """One rolled wait. Re-rolled when the band, presence, or last thought time changes."""

    online: bool | None = None
    band: str = ""
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
        motive_pending=False,
        resting=_resting(at),
        consolidated_today=ledger.consolidated_day == at.date().isoformat(),
        teacher_just_spoke=_teacher_just_spoke(state, at),
        spontaneous_gap_sec=_gap_sec(
            state,
            now=at,
            online=online,
            last_thought_at=ledger.last_thought_at,
            cfg=cfg,
        ),
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
        outcome = await _think(
            state,
            at,
            inner if isinstance(inner, InnerState) else InnerState(),
            ledger,
            decision,
            complete=complete,
            source_context=source_context,
            motive_pending=facts.motive_pending,
        )
        decision = replace(decision, outcome=outcome)
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
) -> str:
    trigger = decision.queued or PendingTrigger(
        kind=decision.kind, focus_id=decision.focus_id
    )
    ctx = source_context if source_context is not None else gather_context(state, now, trigger)
    sources = select_sources(trigger, now, inner, ledger, ctx)
    if sources.cancelled or not (sources.text or "").strip():
        logger.info("thought sources cancelled kind=%s", decision.kind)
        return ""
    caller = complete
    if caller is None:
        planner = getattr(getattr(state, "config", None), "planner", None)
        if planner is None or not ThoughtClient(planner).enabled:
            logger.info("thought model skipped reason=disabled_or_no_key")
            return "failed"
        caller = ThoughtClient(planner).complete
    raw = await _invoke(caller, sources.text)
    parsed = parse_inner(raw)
    if parsed is None:
        logger.info("thought parse failed")
        return "failed"
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
    engine = state.life
    live_spoke = getattr(getattr(engine, "state", None), "last_spoke_at", None)
    next_inner = commit_inner(
        now=now,
        inner=inner,
        ledger=ledger,
        parsed=parsed,
        journal=getattr(state, "life_journal", None),
        arona=getattr(state, "arona_memory", None),
        queued=trigger,
    )
    if isinstance(live_spoke, datetime) and (
        next_inner.last_spoke_at is None or live_spoke > next_inner.last_spoke_at
    ):
        next_inner.last_spoke_at = live_spoke
    engine.state = next_inner
    store = getattr(engine, "store", None)
    if store is not None:
        store.save(next_inner)
    state.thought = ledger
    thought_store = getattr(state, "thought_store", None)
    if thought_store is not None:
        thought_store.save(ledger)
    offered_ctx = source_context if source_context is not None else ctx
    maybe_offer_thought(
        engine,
        parsed,
        now=now,
        motive_pending=motive_pending,
        facts=tuple(getattr(offered_ctx, "situation", ()) or ()),
        welcome=getattr(state, "welcome", None),
        hold_speech=_hold_fresh_speech(state, now, offered_ctx, live_spoke),
        gate_kind=decision.kind,
    )
    return "committed"


def _hold_fresh_speech(state: "AppState", now: datetime, ctx: Any, live_spoke: Any) -> bool:
    """A thought that lands on a line she just said stays unspoken."""
    cfg = getattr(getattr(getattr(state, "config", None), "life", None), "thought", None)
    floor = float(getattr(cfg, "aftertaste_min_sec", 30) or 30)
    since = getattr(ctx, "seconds_since_arona", None)
    if since is not None and float(since) < floor:
        return True
    return isinstance(live_spoke, datetime) and live_spoke >= now.replace(microsecond=0)


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


def _gap_band(now: datetime, *, online: bool) -> str:
    from ...proactive.slots import resolve_slot

    if online:
        return "online"
    if resolve_slot(now).slot_id == "late_night":
        return "night"
    return "away"


def _gap_limits(band: str, cfg: object) -> tuple[float, float]:
    if band == "online":
        lo = float(getattr(cfg, "spontaneous_online_min_sec", 240))
        hi = float(getattr(cfg, "spontaneous_online_max_sec", 600))
    elif band == "night":
        lo = float(getattr(cfg, "spontaneous_night_min_sec", 1200))
        hi = float(getattr(cfg, "spontaneous_night_max_sec", 2400))
    else:
        lo = float(getattr(cfg, "spontaneous_away_min_sec", 600))
        hi = float(getattr(cfg, "spontaneous_away_max_sec", 1200))
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def _gap_sec(
    state: "AppState",
    *,
    now: datetime,
    online: bool,
    last_thought_at: datetime | None,
    cfg: object,
) -> float:
    holder = getattr(state, "thought_spontaneous_gap", None)
    if not isinstance(holder, SpontaneousGap):
        holder = SpontaneousGap()
        state.thought_spontaneous_gap = holder
    band = _gap_band(now, online=online)
    if (
        not holder.rolled
        or holder.online != online
        or holder.band != band
        or holder.anchored_at != last_thought_at
    ):
        lo, hi = _gap_limits(band, cfg)
        holder.gap_sec = lo if lo == hi else random.uniform(lo, hi)
        holder.online = online
        holder.band = band
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


async def greet_on_connect(
    state: "AppState",
    *,
    session_id: str = "",
    now: datetime | None = None,
    complete=None,
) -> None:
    """Think once on arrival. Fall back to today's welcome only if that produces nothing."""
    from ...proactive.welcome import offer_arrival_fallback

    at = now or datetime.now()
    cfg = getattr(getattr(state.config, "life", None), "thought", None)
    limit = float(getattr(cfg, "arrived_fallback_sec", 2) or 2)
    decision: ThoughtDecision | None
    try:
        decision = await asyncio.wait_for(
            thought_tick_once(state, at, complete=complete),
            timeout=max(0.1, limit),
        )
    except asyncio.TimeoutError:
        decision = None
    engine = getattr(state, "life", None)
    if engine is not None and engine.state.pending_impulse is not None:
        return
    if decision is not None and decision.outcome != "failed":
        return
    await offer_arrival_fallback(state, session_id=session_id, now=at)


def _resting(now: datetime) -> bool:
    from ...proactive.slots import REST_SLOTS, resolve_slot

    return resolve_slot(now).slot_id in REST_SLOTS


