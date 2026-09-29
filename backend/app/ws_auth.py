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

"""Shared access token for the WebSocket. Empty token stays open on loopback."""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)

TOKEN_PLACEHOLDER = "YOUR_ACCESS_TOKEN"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def configured_access_token(token: str) -> str:
    """Return the token to enforce. Placeholder and blank count as unset."""
    value = (token or "").strip()
    if not value or value == TOKEN_PLACEHOLDER:
        return ""
    return value


def is_loopback_host(host: str) -> bool:
    return (host or "").strip().lower() in _LOOPBACK_HOSTS


def startup_token_error(
    host: str,
    public: bool,
    token: str,
    *,
    setting: str = "server.token",
) -> str | None:
    """Refuse a public or non-loopback listener that has no access token."""
    if is_loopback_host(host) and not public:
        return None
    if configured_access_token(token):
        return None
    return (
        f"拒绝启动：公网或非本机监听必须设置 {setting}。"
        "生成命令：python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )


def bearer_matches(authorization: str | None, expected_token: str) -> bool:
    """True when no token is configured, or the Bearer value matches."""
    expected = configured_access_token(expected_token)
    if not expected:
        return True
    presented = _presented_bearer(authorization)
    if presented is None:
        return False
    return hmac.compare_digest(_digest(presented), _digest(expected))


async def reject_unauthorized(websocket: WebSocket, expected_token: str) -> bool:
    """Close the socket before accept when the token is wrong. True means rejected."""
    if bearer_matches(websocket.headers.get("authorization"), expected_token):
        return False
    client = getattr(websocket, "client", None)
    client_host = getattr(client, "host", None) if client else None
    client_port = getattr(client, "port", None) if client else None
    logger.info(
        "WS rejected client=%s:%s reason=unauthorized",
        client_host,
        client_port,
    )
    await websocket.close(code=1008)
    return True


def _presented_bearer(authorization: str | None) -> str | None:
    raw = (authorization or "").strip()
    scheme, sep, rest = raw.partition(" ")
    if not sep or scheme.lower() != "bearer":
        return None
    token = rest.strip()
    if not token:
        return None
    return token


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()
