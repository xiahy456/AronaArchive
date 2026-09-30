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
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..channel import METHOD_MESSAGE, QQ_SESSION_ID
from ..image_input import image_payload_from_napcat_file
from ..proactive.goal import wants_goal_mute
from .protocol import QqFileImage, QqUrlImage

logger = logging.getLogger(__name__)

COALESCE_SEC = 10.0
_INTERRUPT_KINDS = frozenset({"interact", "computer_use"})
_BLOCK_KINDS = frozenset({"chat", "welcome", "qq"})


@dataclass(frozen=True)
class _QqPiece:
    text: str
    images: tuple[Any, ...]


class QqInbox:
    def __init__(self, state: Any, *, coalesce_sec: float = COALESCE_SEC) -> None:
        self.state = state
        self._coalesce_sec = max(0.0, float(coalesce_sec))
        self._parts: list[_QqPiece] = []
        self._held: list[_QqPiece] = []
        self._timer: asyncio.Task[None] | None = None
        self._running = False
        self._lock = asyncio.Lock()

    async def push(self, text: str, images: Any = None) -> None:
        cleaned = (text or "").strip()
        refs = tuple(images or ())
        if not cleaned and not refs:
            return
        piece = _QqPiece(cleaned, refs)
        await self._interrupt_hands()
        async with self._lock:
            if self._running or self._blocked():
                self._held.append(piece)
                return
            self._parts.append(piece)
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
            text = "\n".join(part.text for part in self._parts if part.text.strip())
            images = [image for part in self._parts for image in part.images]
            self._parts.clear()
            if not text and not images:
                return
            self._running = True
        try:
            resolved = await self._resolve_images(images)
            if not text and not resolved:
                return
            await self._generate(text, resolved)
        finally:
            async with self._lock:
                self._running = False
                if self._held and not self._blocked():
                    self._parts.extend(self._held)
                    self._held.clear()
                    self._restart_timer_locked()

    async def _resolve_images(self, images: list[Any]) -> list[Any]:
        resolved: list[Any] = []
        link = getattr(self.state, "napcat", None)
        for image in images:
            if isinstance(image, QqUrlImage):
                if image.url:
                    resolved.append(image.url)
                continue
            if not isinstance(image, QqFileImage):
                continue
            if link is None or not getattr(link, "connected", False):
                logger.info("qq file image dropped reason=napcat_down")
                continue
            frame = await link.get_file(image.file_id, file=image.file)
            payload = image_payload_from_napcat_file(frame)
            if payload is None:
                logger.info("qq file image dropped file_id=%s", image.file_id or image.file)
                continue
            resolved.append(payload)
        return resolved

    async def _generate(self, text: str, images: list[Any] | None = None) -> None:
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
                qq_images=list(images or []),
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
