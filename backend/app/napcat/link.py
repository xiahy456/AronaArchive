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
