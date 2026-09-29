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

"""Rare glance outside the classroom. Listening does not shorten the interval."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from ..protocol import msg_glance_request

logger = logging.getLogger(__name__)

BLOCK_CLIMATES = frozenset({"fragile", "rupture", "cling_risk"})
DEFAULT_INTERVAL_SEC = 1200.0


def glance_allowed(
    *,
    now: datetime,
    last_at: datetime | None,
    interval_sec: float,
    activity: str,
    attention: str,
    climate: str,
    busy: bool,
    listening: bool = False,
    pending: bool = False,
) -> bool:
    """Deterministic gate. `listening` is accepted and does not tighten the interval."""
    del listening
    if pending or busy:
        return False
    if activity in {"using_computer", "looking_at_teacher"}:
        return False
    if attention == "teacher":
        return False
    if climate in BLOCK_CLIMATES:
        return False
    wait = max(1.0, float(interval_sec))
    if last_at is not None and (now - last_at).total_seconds() < wait:
        return False
    return True


def maybe_request_glance(state: Any, now: datetime | None = None) -> None:
    """Ask the client for one frame when the gate opens. Does not speak."""
    journal = getattr(state, "journal", None)
    engine = getattr(state, "life", None)
    hub = getattr(state, "hub", None)
    life_cfg = getattr(getattr(state, "config", None), "life", None)
    if journal is None or engine is None or hub is None or life_cfg is None:
        return
    try:
        sessions = list(hub.all_sessions())
    except Exception:
        return
    if not sessions:
        return
    at = now or datetime.now()
    inner = engine.state
    interval = float(getattr(life_cfg, "glance_interval_sec", DEFAULT_INTERVAL_SEC))
    climate = ""
    relationship = getattr(getattr(state, "orchestrator", None), "relationship", None)
    rel_cfg = getattr(getattr(getattr(state, "config", None), "proactive", None), "relationship", None)
    rel_on = rel_cfg is None or bool(getattr(rel_cfg, "enabled", True))
    if relationship is not None and rel_on:
        try:
            climate = str(relationship.peek_climate() or "")
        except Exception:
            climate = ""
    if not glance_allowed(
        now=at,
        last_at=journal.last_glance_at,
        interval_sec=interval,
        activity=inner.activity,
        attention=inner.attention,
        climate=climate,
        busy=bool(hub.any_busy()),
        listening=bool(inner.can_hear),
        pending=bool(getattr(state, "glance_request_id", "")),
    ):
        return
    request_id = uuid.uuid4().hex
    state.glance_request_id = request_id
    journal.note_requested_glance(at)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        state.glance_request_id = ""
        return
    loop.create_task(_send_glance(state, request_id), name="life-glance")


def forget_glances(state: Any) -> None:
    """Delete stored glance sources. Leaves the interval stamp and inner thoughts."""
    seen: set[int] = set()
    holders = (
        getattr(state, "journal", None),
        getattr(state, "life_journal", None),
        getattr(getattr(state, "orchestrator", None), "life_journal", None),
    )
    for journal in holders:
        if journal is None or id(journal) in seen:
            continue
        seen.add(id(journal))
        drop = getattr(journal, "drop_kind", None)
        if callable(drop):
            drop("glance")
    from .thought.store import ThoughtLedger

    ledger = getattr(state, "thought", None)
    if not isinstance(ledger, ThoughtLedger):
        return
    kept = [item for item in ledger.pending_triggers if item.kind != "glance"]
    had_glance = len(kept) != len(ledger.pending_triggers) or bool(
        (ledger.last_glance_seen or "").strip()
    )
    ledger.pending_triggers = kept
    ledger.last_glance_seen = ""
    if not had_glance:
        return
    store = getattr(state, "thought_store", None)
    if store is None:
        return
    try:
        store.save(ledger)
    except Exception:
        logger.exception("glance forget save failed")


def apply_glance_refusal(state: Any, request_id: str) -> bool:
    """Cancel a refused glance and delete stored glance sources.

    An empty request id is a toggle or startup clear. A non-empty id must match
    the in-flight request, so a late refusal cannot wipe a newer glance.
    """
    pending = str(getattr(state, "glance_request_id", "") or "")
    request_id = (request_id or "").strip()
    if request_id and request_id != pending:
        logger.info("glance refusal ignored reason=stale request_id=%s", request_id)
        return False
    state.glance_request_id = ""
    forget_glances(state)
    logger.info("glance refusal cleared request_id=%s", request_id)
    return True


async def _send_glance(state: Any, request_id: str) -> None:
    hub = getattr(state, "hub", None)
    if hub is None:
        return
    payload = msg_glance_request(request_id)
    for session_id, send in hub.all_sessions():
        try:
            await send(payload)
        except Exception:
            logger.exception("glance request failed session=%s", session_id)
