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

"""WebSocket message type helpers aligned with Qt client."""

from __future__ import annotations

from typing import Any


# Client -> server
TYPE_CHAT = "chat"
TYPE_INTERACT = "interact"
TYPE_CLEAR_SESSION = "clear_session"
TYPE_GET_STATS = "get_stats"
TYPE_PING = "ping"
TYPE_LISTEN_STATE = "listen_state"
TYPE_TRANSCRIPT = "transcript"
TYPE_INTERRUPT = "interrupt"
TYPE_COMPUTER_USE_OBSERVATION = "computer_use_observation"
TYPE_GLANCE_FRAME = "glance_frame"
TYPE_GLANCE_REFUSED = "glance_refused"

# Server -> client
TYPE_CONNECTED = "connected"
TYPE_CHAT_RESPONSE = "chat_response"
TYPE_ERROR = "error"
TYPE_STATS = "stats"
TYPE_RESULT = "result"
TYPE_PONG = "pong"
TYPE_COMPUTER_USE_ACTION = "computer_use_action"
TYPE_COMPUTER_USE_DONE = "computer_use_done"
TYPE_PRESENCE = "presence"
TYPE_GLANCE_REQUEST = "glance_request"

CODE_INVALID_JSON = "INVALID_JSON"
CODE_INTERNAL = "INTERNAL_ERROR"
CODE_BAD_REQUEST = "BAD_REQUEST"


def msg_connected(session_id: str) -> dict[str, Any]:
    return {"type": TYPE_CONNECTED, "session_id": session_id}


def msg_pong() -> dict[str, Any]:
    return {"type": TYPE_PONG}


def msg_error(code: str, message: str) -> dict[str, Any]:
    return {"type": TYPE_ERROR, "code": code, "message": message}


def msg_chat_response(
    content: str,
    *,
    context_used: str = "none",
    latency: float = 0.0,
    emotion: str = "normal",
) -> dict[str, Any]:
    return {
        "type": TYPE_CHAT_RESPONSE,
        "content": content,
        "context_used": context_used,
        "latency": latency,
        "emotion": emotion,
    }


def msg_result(success: bool, message: str) -> dict[str, Any]:
    return {"type": TYPE_RESULT, "success": success, "message": message}


def msg_stats(payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": TYPE_STATS, **payload}


def msg_computer_use_action(payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": TYPE_COMPUTER_USE_ACTION, **payload}


def msg_glance_request(request_id: str) -> dict[str, Any]:
    return {"type": TYPE_GLANCE_REQUEST, "request_id": request_id}


def msg_presence(emotion: str, *, activity: str = "") -> dict[str, Any]:
    return {
        "type": TYPE_PRESENCE,
        "emotion": emotion,
        "activity": activity,
    }


def msg_computer_use_done(
    run_id: str,
    *,
    ok: bool,
    summary: str = "",
) -> dict[str, Any]:
    return {
        "type": TYPE_COMPUTER_USE_DONE,
        "run_id": run_id,
        "ok": ok,
        "summary": summary,
    }
