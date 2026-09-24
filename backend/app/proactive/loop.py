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

"""Process-level ticker. It delivers a queued impulse and does not author one."""

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
    """Deliver an impulse thought already queued. Motives are facts, not speech.

    Returns True if a line was sent. Listening does not skip the tick.
    """
    from ..life.impulse import flush_impulse

    if not state.hub.all_sessions():
        return False
    engine = getattr(state, "life", None)
    if engine is None or engine.state.pending_impulse is None:
        return False
    dt = now or datetime.now()
    return await flush_impulse(state, now=dt)
