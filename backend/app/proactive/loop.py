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

"""Process-level ticker: pick at most one motive and enqueue it as an impulse."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from .festival import birthday_from_profiles

if TYPE_CHECKING:
    from ..ws_handler import AppState

logger = logging.getLogger(__name__)

TICK_SEC = 30.0


async def load_birthday_content(state: "AppState") -> str:
    if not getattr(state.scheduler.festival_cfg, "enabled", False):
        return ""
    rows = await asyncio.to_thread(
        state.orchestrator.memory_store.list_by_category, "profile"
    )
    return birthday_from_profiles(rows)


async def run_proactive_loop(state: "AppState") -> None:
    while True:
        await asyncio.sleep(TICK_SEC)
        try:
            await tick_once(state)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("proactive tick failed")


async def tick_once(state: "AppState", now: datetime | None = None) -> bool:
    """Pick at most one motive, enqueue an impulse, maybe speak.

    Returns True if a line was sent. Listening does not skip the tick.
    """
    # Import inside the body so app.proactive.__init__ can load while
    # life.policy is still importing slots (no circular import).
    from ..life.impulse import flush_impulse, impulse_from_motive, offer_impulse

    if not state.hub.all_sessions():
        return False
    engine = getattr(state, "life", None)
    if engine is None:
        return False

    dt = now or datetime.now()
    relationship = state.orchestrator.relationship
    last_user_act = "other"
    climate = None
    if relationship is not None and state.config.proactive.relationship.enabled:
        last_user_act = relationship.state.last_user_act or "other"
        climate = relationship.peek_climate()

    birthday = await load_birthday_content(state)
    goals: list[dict] = []
    if getattr(state.scheduler.goal_cfg, "enabled", False):
        goals = await asyncio.to_thread(
            state.orchestrator.memory_store.list_by_category, "goal"
        )
    moods: list[dict] = []
    if getattr(state.scheduler.mood_cfg, "enabled", False):
        moods = await asyncio.to_thread(
            state.orchestrator.memory_store.list_by_category, "emotional"
        )

    motive = state.scheduler.pick_motive(
        dt,
        last_user_act=last_user_act,
        climate=climate,
        goals=goals,
        moods=moods,
        birthday_content=birthday,
    )
    if motive is None:
        care_reason = state.scheduler.care_block_reason(dt)
        if care_reason:
            logger.info("proactive care skipped reason=%s", care_reason)
        else:
            reason = state.scheduler.idle_block_reason(dt, last_user_act=last_user_act)
            if reason:
                logger.info("proactive idle skipped reason=%s", reason)
        if engine.state.pending_impulse is None:
            return False
        return await flush_impulse(state, now=dt)

    allow_speak = True
    if relationship is not None and state.config.proactive.relationship.enabled:
        gate = relationship.decide_proactive(motive.kind)
        allow_speak = gate.action == "initiate"
        if not allow_speak:
            logger.info(
                "impulse climate withhold kind=%s climate=%s action=%s",
                motive.kind,
                gate.climate,
                gate.action,
            )

    impulse = impulse_from_motive(motive, dt, allow_speak=allow_speak)
    offered = offer_impulse(engine, impulse)
    logger.info(
        "impulse enqueue kind=%s accepted=%s allow_speak=%s pending=%s",
        motive.kind,
        offered,
        allow_speak,
        engine.state.pending_impulse.kind if engine.state.pending_impulse else "-",
    )
    return await flush_impulse(state, now=dt)
