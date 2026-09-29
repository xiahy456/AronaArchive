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
