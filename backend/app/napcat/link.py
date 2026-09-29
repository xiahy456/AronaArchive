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

"""One live Napcat socket. Outbound clauses are serialized and spaced."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

from .protocol import build_send_private
from .split import split_qq_clauses

logger = logging.getLogger(__name__)

CLAUSE_GAP_SEC = 2.0


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

    async def send_text(self, text: str) -> bool:
        """Send every clause. False if the socket drops before the last one."""
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
                if self._ws is not ws:
                    logger.info("napcat send aborted reason=socket_replaced")
                    return False
                frame = build_send_private(self.user_qq_id, clause)
                try:
                    await ws.send_text(json.dumps(frame, ensure_ascii=False))
                except Exception:
                    logger.exception("napcat send failed")
                    self.unbind(ws)
                    return False
            return True
