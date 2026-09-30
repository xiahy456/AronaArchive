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

"""One live Napcat socket. Outbound clauses are serialized and spaced."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import WebSocket

from .protocol import build_send_mface, build_send_private
from .split import split_qq_clauses

logger = logging.getLogger(__name__)

CLAUSE_GAP_SEC = 2.0


def _sticker_frame(user_qq_id: str, emoji: object) -> dict | None:
    package = getattr(emoji, "package_id_value", None)
    emoji_id = str(getattr(emoji, "emoji_id", "") or "").strip()
    key = str(getattr(emoji, "key", "") or "").strip()
    summary = str(getattr(emoji, "summary", "") or "").strip()
    if not callable(package) or not emoji_id or not key or not summary:
        return None
    return build_send_mface(
        user_qq_id,
        emoji_package_id=package(),
        emoji_id=emoji_id,
        key=key,
        summary=summary,
    )


class NapcatLink:
    def __init__(self, user_qq_id: str, *, gap_sec: float = CLAUSE_GAP_SEC) -> None:
        self.user_qq_id = str(user_qq_id or "").strip()
        self._gap_sec = max(0.0, float(gap_sec))
        self._ws: WebSocket | None = None
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}

    @property
    def connected(self) -> bool:
        return self._ws is not None and bool(self.user_qq_id)

    async def bind(self, websocket: WebSocket) -> None:
        old = self._ws
        self._ws = websocket
        if old is not None and old is not websocket:
            try:
                await old.close()
            except Exception:
                logger.info("napcat replaced an older socket")

    def unbind(self, websocket: WebSocket) -> None:
        if self._ws is websocket:
            self._ws = None
        self._fail_pending()

    def complete_echo(self, frame: dict[str, Any]) -> None:
        echo = str(frame.get("echo") or "")
        fut = self._pending.get(echo)
        if fut is None or fut.done():
            return
        fut.set_result(frame)

    def _fail_pending(self) -> None:
        pending = list(self._pending.values())
        self._pending.clear()
        for fut in pending:
            if not fut.done():
                fut.set_result({})

    async def get_file(
        self,
        file_id: str = "",
        *,
        file: str = "",
        timeout: float = 20.0,
    ) -> dict[str, Any] | None:
        """Ask Napcat for one file and wait for the matching echo."""
        params: dict[str, str] = {}
        if str(file_id or "").strip():
            params["file_id"] = str(file_id).strip()
        elif str(file or "").strip():
            params["file"] = str(file).strip()
        else:
            return None
        ws = self._ws
        if ws is None:
            return None
        echo = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[echo] = fut
        frame = {"action": "get_file", "params": params, "echo": echo}
        async with self._send_lock:
            if not await self._send_frame(ws, frame):
                self._pending.pop(echo, None)
                return None
        try:
            result = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            logger.info("napcat get_file timeout")
            return None
        finally:
            self._pending.pop(echo, None)
        if not result:
            return None
        return result

    async def send_text(self, text: str, *, emoji: object | None = None) -> bool:
        """Send every clause, then one sticker. False if text never finishes."""
        clauses = split_qq_clauses(text)
        if not clauses or not self.user_qq_id:
            return False
        async with self._send_lock:
            ws = self._ws
            if ws is None:
                return False
            for index, clause in enumerate(clauses):
                if index and self._gap_sec:
                    await asyncio.sleep(self._gap_sec)
                if not await self._send_frame(ws, build_send_private(self.user_qq_id, clause)):
                    return False
            if emoji is None:
                return True
            if self._gap_sec:
                await asyncio.sleep(self._gap_sec)
            sticker = _sticker_frame(self.user_qq_id, emoji)
            if sticker is None:
                return True
            if not await self._send_frame(ws, sticker):
                logger.info("napcat emoji undelivered after text")
                return True
            return True

    async def _send_frame(self, ws: WebSocket, frame: dict) -> bool:
        if self._ws is not ws:
            logger.info("napcat send aborted reason=socket_replaced")
            return False
        try:
            await ws.send_text(json.dumps(frame, ensure_ascii=False))
        except Exception:
            logger.exception("napcat send failed")
            self.unbind(ws)
            return False
        return True
