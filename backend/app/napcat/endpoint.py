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

"""Reverse WebSocket: Napcat connects in, this process is the server."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ..ws_auth import reject_unauthorized
from .protocol import private_text_from_event

logger = logging.getLogger(__name__)


async def napcat_endpoint(websocket: WebSocket, state: Any) -> None:
    if await reject_unauthorized(websocket, state.config.napcat.napcat_token):
        return
    await websocket.accept()
    link = state.napcat
    inbox = state.qq_inbox
    await link.bind(websocket)
    logger.info("napcat connected user_qq_id=%s", link.user_qq_id or "-")
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.info("napcat ignored non-json")
                continue
            text = private_text_from_event(data, link.user_qq_id)
            if not text:
                continue
            logger.info("napcat private text chars=%d", len(text))
            await inbox.push(text)
    except WebSocketDisconnect:
        logger.info("napcat disconnected")
    except Exception:
        logger.exception("napcat socket failed")
    finally:
        link.unbind(websocket)
