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
import json
import logging
import time
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
    message_id: str = ""


class QqInbox:
    def __init__(self, state: Any, *, coalesce_sec: float = COALESCE_SEC) -> None:
        self.state = state
        self._coalesce_sec = max(0.0, float(coalesce_sec))
        self._parts: list[_QqPiece] = []
        self._held: list[_QqPiece] = []
        self._active: list[_QqPiece] = []
        self._timer: asyncio.Task[None] | None = None
        self._running = False
        self._reply_ready = False
        self._generation_id = 0
        self._chat_task: asyncio.Task[bool] | None = None
        self._lock = asyncio.Lock()

    async def push(
        self, text: str, images: Any = None, *, message_id: str = ""
    ) -> None:
        cleaned = (text or "").strip()
        refs = tuple(images or ())
        mid = str(message_id or "").strip()
        if not cleaned and not refs:
            return
        piece = _QqPiece(cleaned, refs, mid)
        await self._interrupt_hands()
        to_cancel: asyncio.Task[bool] | None = None
        async with self._lock:
            if self._running:
                if self._reply_ready:
                    self._held.append(piece)
                    return
                # Model still generating: barge in, merge into this round.
                self._parts.append(piece)
                self._generation_id += 1
                if self._chat_task is not None and not self._chat_task.done():
                    to_cancel = self._chat_task
                logger.info("qq barge-in generation_id=%s", self._generation_id)
            elif self._blocked():
                self._held.append(piece)
                return
            else:
                self._parts.append(piece)
                self._restart_timer_locked()
                return
        if to_cancel is not None:
            to_cancel.cancel()

    async def recall(self, message_id: str) -> None:
        mid = str(message_id or "").strip()
        if not mid:
            return
        to_cancel: asyncio.Task[bool] | None = None
        async with self._lock:
            self._parts = [part for part in self._parts if part.message_id != mid]
            self._held = [part for part in self._held if part.message_id != mid]
            hit_active = any(part.message_id == mid for part in self._active)
            if hit_active:
                self._active = [part for part in self._active if part.message_id != mid]
                self._generation_id += 1
                if self._chat_task is not None and not self._chat_task.done():
                    to_cancel = self._chat_task
                logger.info(
                    "qq recall active message_id=%s generation_id=%s left=%d",
                    mid,
                    self._generation_id,
                    len(self._active),
                )
            if not self._parts and self._timer is not None and not self._timer.done():
                self._timer.cancel()
                self._timer = None
        if to_cancel is not None:
            to_cancel.cancel()
        orch = getattr(self.state, "orchestrator", None)
        conversations = getattr(orch, "conversations", None) if orch is not None else None
        if conversations is not None and hasattr(conversations, "remove_qq_message"):
            if conversations.remove_qq_message(mid):
                logger.info("qq recall dialogue message_id=%s", mid)

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

    def _mark_reply_ready(self) -> None:
        self._reply_ready = True

    async def _wait_and_fire(self) -> None:
        try:
            await asyncio.sleep(self._coalesce_sec)
        except asyncio.CancelledError:
            return
        async with self._lock:
            if self._running or not self._parts:
                return
            self._active = list(self._parts)
            self._parts.clear()
            if not self._active:
                return
            self._running = True
            self._reply_ready = False
        try:
            await self._generate()
        finally:
            async with self._lock:
                self._running = False
                self._reply_ready = False
                self._chat_task = None
                self._active.clear()
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
                # Already-resolved URL string or ImagePayload from a prior attempt.
                if image:
                    resolved.append(image)
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

    async def _drain_barge_parts(self) -> list[_QqPiece]:
        async with self._lock:
            if not self._parts:
                return []
            drained = list(self._parts)
            self._parts.clear()
            return drained

    def _qq_parts_payload(self, pieces: list[_QqPiece]) -> list[dict[str, str]]:
        payload: list[dict[str, str]] = []
        for part in pieces:
            mid = (part.message_id or "").strip()
            text = (part.text or "").strip()
            if not mid and not text:
                continue
            payload.append({"message_id": mid, "text": text})
        return payload

    async def _generate(self) -> None:
        state = self.state
        hub = getattr(state, "hub", None)
        if hub is not None:
            hub.set_busy(QQ_SESSION_ID, True)
        state.generation_kind = "qq"
        state.generation_owner = QQ_SESSION_ID
        finished_text = ""
        try:
            scheduler = getattr(state, "scheduler", None)
            client_online = bool(hub is not None and hub.all_sessions())

            while True:
                extra = await self._drain_barge_parts()
                if extra:
                    async with self._lock:
                        self._active.extend(extra)
                async with self._lock:
                    pieces = list(self._active)
                pending_text = "\n".join(
                    part.text for part in pieces if part.text.strip()
                )
                raw_images = [image for part in pieces for image in part.images]
                pending_images = await self._resolve_images(raw_images)
                if not pending_text.strip() and not pending_images:
                    return

                if scheduler is not None:
                    if wants_goal_mute(pending_text):
                        muted = scheduler.mute_last_followup()
                        if muted:
                            logger.info("followup muted by qq key=%s", muted)
                    else:
                        acked = scheduler.ack_pending_followups()
                        if acked:
                            logger.info("followup acked by qq keys=%s", acked)
                    scheduler.note_user_activity()

                async with self._lock:
                    self._reply_ready = False
                    my_id = self._generation_id
                    turn_pieces = list(self._active)

                started_at = time.perf_counter()
                turn_text = "\n".join(
                    part.text for part in turn_pieces if part.text.strip()
                )
                turn_images = await self._resolve_images(
                    [image for part in turn_pieces for image in part.images]
                )
                qq_parts = self._qq_parts_payload(turn_pieces)
                request_json = json.dumps(
                    {
                        "type": "qq",
                        "content": turn_text,
                        "image_count": len(turn_images),
                        "message_ids": [part.message_id for part in turn_pieces],
                    },
                    ensure_ascii=False,
                )
                turn_id = my_id

                async def _run_chat() -> bool:
                    return await state.orchestrator.handle_chat(
                        session_id=QQ_SESSION_ID,
                        content=turn_text,
                        options={},
                        send=self._send_direct,
                        request_json=request_json,
                        started_at=started_at,
                        abort_check=lambda: self._generation_id != turn_id,
                        on_reply_ready=self._mark_reply_ready,
                        inbound_method=METHOD_MESSAGE,
                        client_online=client_online,
                        qq_images=turn_images,
                        qq_parts=qq_parts,
                    )

                task = asyncio.create_task(_run_chat())
                async with self._lock:
                    self._chat_task = task
                try:
                    ok = await task
                except asyncio.CancelledError:
                    async with self._lock:
                        has_more = bool(self._parts) or bool(self._active)
                        self._chat_task = None
                        self._reply_ready = False
                    if has_more:
                        logger.info("qq chat cancelled; retry with remaining")
                        continue
                    return
                finally:
                    async with self._lock:
                        if self._chat_task is task:
                            self._chat_task = None

                if not ok:
                    async with self._lock:
                        has_more = bool(self._parts) or bool(self._active)
                        self._reply_ready = False
                    if has_more:
                        logger.info("qq chat aborted; retry with remaining")
                        continue
                    return

                finished_text = turn_text
                break

            from ..life.thought.triggers import note_finished_turn

            note_finished_turn(state, finished_text, now=datetime.now())
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
