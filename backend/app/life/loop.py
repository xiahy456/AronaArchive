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

"""Process-level ticker: advance inner state; deliver a pending impulse if any."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from .glance import maybe_request_glance
from .presence import schedule_presence
from .impulse import expire_stale_care, schedule_impulse_delivery

if TYPE_CHECKING:
    from ..ws_handler import AppState

logger = logging.getLogger(__name__)

DEFAULT_TICK_SEC = 5.0


def _tick_sec(state: "AppState") -> float:
    cfg = getattr(state.config, "life", None)
    raw = getattr(cfg, "tick_sec", DEFAULT_TICK_SEC) if cfg is not None else DEFAULT_TICK_SEC
    return max(0.2, float(raw))


def _climate(state: "AppState") -> str | None:
    relationship = getattr(state.orchestrator, "relationship", None)
    if relationship is None:
        return None
    rel_cfg = getattr(state.config.proactive, "relationship", None)
    if rel_cfg is not None and not getattr(rel_cfg, "enabled", True):
        return None
    try:
        return relationship.peek_climate()
    except Exception:
        logger.exception("life peek_climate failed")
        return None


async def run_life_loop(state: "AppState") -> None:
    delay = _tick_sec(state)
    while True:
        await asyncio.sleep(delay)
        try:
            tick_once(state)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("life tick failed")


def tick_once(state: "AppState", now: datetime | None = None) -> None:
    engine = getattr(state, "life", None)
    if engine is None:
        return
    at = now or datetime.now()
    expire_stale_care(state, at)
    decision = engine.tick(at, climate=_climate(state))
    journal = getattr(state, "journal", None)
    if journal is not None:
        journal.note_inner(
            engine.state,
            now=at,
            arona=getattr(state, "arona_memory", None),
        )
    schedule_presence(state)
    schedule_impulse_delivery(state, decision, now=at)
    maybe_request_glance(state, at)
