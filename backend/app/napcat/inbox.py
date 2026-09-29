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

"""Coalesce a burst of QQ private texts, then run one chat turn."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from ..channel import METHOD_MESSAGE, QQ_SESSION_ID
from ..proactive.goal import wants_goal_mute

logger = logging.getLogger(__name__)

COALESCE_SEC = 10.0
_INTERRUPT_KINDS = frozenset({"interact", "computer_use"})
_BLOCK_KINDS = frozenset({"chat", "welcome", "qq"})


class QqInbox:
    def __init__(self, state: Any, *, coalesce_sec: float = COALESCE_SEC) -> None:
        self.state = state
        self._coalesce_sec = max(0.0, float(coalesce_sec))
        self._parts: list[str] = []
        self._held: list[str] = []
        self._timer: asyncio.Task[None] | None = None
        self._running = False
        self._lock = asyncio.Lock()

    async def push(self, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        await self._interrupt_hands()
        async with self._lock:
            if self._running or self._blocked():
                self._held.append(cleaned)
                return
            self._parts.append(cleaned)
            self._restart_timer_locked()

    def on_generation_idle(self) -> None:
        """Client generation finished. Release texts that arrived during it."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._release_held())

    async def _release_held(self) -> None:
        async with self._lock:
            if self._running or self._blocked() or not self._held:
                return
            self._parts.extend(self._held)
            self._held.clear()
            self._restart_timer_locked()

    async def _interrupt_hands(self) -> None:
        kind = str(getattr(self.state, "generation_kind", "") or "")
        if kind not in _INTERRUPT_KINDS:
            return
        interrupts = getattr(self.state, "generation_interrupts", None) or {}
        for fn in list(interrupts.values()):
            try:
                await fn()
            except Exception:
                logger.exception("qq interrupt failed")

    def _blocked(self) -> bool:
        kind = str(getattr(self.state, "generation_kind", "") or "")
        if kind in _BLOCK_KINDS:
            return True
        hub = getattr(self.state, "hub", None)
        if hub is not None and hub.is_busy(QQ_SESSION_ID):
            return True
        return False

    def _restart_timer_locked(self) -> None:
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
        self._timer = asyncio.create_task(self._wait_and_fire())

    async def _wait_and_fire(self) -> None:
        try:
            await asyncio.sleep(self._coalesce_sec)
        except asyncio.CancelledError:
            return
        async with self._lock:
            if self._running or not self._parts:
                return
            text = "\n".join(part for part in self._parts if part.strip())
            self._parts.clear()
            if not text:
                return
            self._running = True
        try:
            await self._generate(text)
        finally:
            async with self._lock:
                self._running = False
                if self._held and not self._blocked():
                    self._parts.extend(self._held)
                    self._held.clear()
                    self._restart_timer_locked()

    async def _generate(self, text: str) -> None:
        state = self.state
        hub = getattr(state, "hub", None)
        if hub is not None:
            hub.set_busy(QQ_SESSION_ID, True)
        state.generation_kind = "qq"
        state.generation_owner = QQ_SESSION_ID
        try:
            scheduler = getattr(state, "scheduler", None)
            if scheduler is not None:
                if wants_goal_mute(text):
                    muted = scheduler.mute_last_followup()
                    if muted:
                        logger.info("followup muted by qq key=%s", muted)
                else:
                    acked = scheduler.ack_pending_followups()
                    if acked:
                        logger.info("followup acked by qq keys=%s", acked)
                scheduler.note_user_activity()
            client_online = bool(hub is not None and hub.all_sessions())
            await state.orchestrator.handle_chat(
                session_id=QQ_SESSION_ID,
                content=text,
                options={},
                send=self._send_direct,
                inbound_method=METHOD_MESSAGE,
                client_online=client_online,
            )
            from ..life.thought.triggers import note_finished_turn

            note_finished_turn(state, text, now=datetime.now())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("qq chat failed")
        finally:
            if hub is not None:
                hub.set_busy(QQ_SESSION_ID, False)
            if getattr(state, "generation_owner", "") == QQ_SESSION_ID:
                state.generation_kind = ""
                state.generation_owner = ""

    async def _send_direct(self, payload: dict[str, Any]) -> None:
        hub = getattr(self.state, "hub", None)
        if hub is None:
            return
        sessions = hub.all_sessions()
        if not sessions:
            return
        _session_id, send = sessions[0]
        await send(payload)
