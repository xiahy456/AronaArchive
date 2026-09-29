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
