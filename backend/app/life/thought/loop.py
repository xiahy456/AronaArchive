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

"""Thought beat. Logs the gate decision and does not think, speak, or dequeue."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from ..policy import SIMMER_SEC
from ..state import InnerState
from .gate import ThoughtClocks, ThoughtDecision, ThoughtGateFacts, decide_thought
from .store import ThoughtLedger

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
) -> ThoughtDecision:
    """Log one gate line. Does not write the ledger, rumination, or an impulse."""
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
        consolidated_today=False,
        spontaneous_gap_sec=_gap_sec(state, online=online, last_thought_at=ledger.last_thought_at, cfg=cfg),
    )
    clocks = ThoughtClocks(
        revisit_after_sec=float(cfg.revisit_after_sec),
        refractory_sec=float(cfg.refractory_sec),
        simmer_sec=float(SIMMER_SEC),
    )
    decision = decide_thought(at, inner if isinstance(inner, InnerState) else InnerState(), ledger, facts, clocks)
    logger.info("%s", format_gate_log(decision))
    return decision


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
