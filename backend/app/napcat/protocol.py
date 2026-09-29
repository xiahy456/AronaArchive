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

"""OneBot array frames for a Napcat reverse WebSocket."""

from __future__ import annotations

import uuid
from typing import Any


def private_text_from_event(event: object, user_qq_id: str) -> str | None:
    """Text of a private message from the configured teacher. Anything else is None."""
    expected = str(user_qq_id or "").strip()
    if not expected or not isinstance(event, dict):
        return None
    if event.get("post_type") != "message":
        return None
    if event.get("message_type") != "private":
        return None
    if str(event.get("user_id") or "").strip() != expected:
        return None
    message = event.get("message")
    if not isinstance(message, list):
        return None
    parts: list[str] = []
    for segment in message:
        if not isinstance(segment, dict) or segment.get("type") != "text":
            continue
        data = segment.get("data")
        if not isinstance(data, dict):
            continue
        text = str(data.get("text") or "")
        if text:
            parts.append(text)
    joined = "".join(parts).strip()
    return joined or None


def _user_id(user_qq_id: str) -> int | str:
    raw_id = str(user_qq_id or "").strip()
    try:
        return int(raw_id)
    except ValueError:
        return raw_id


def build_send_private(user_qq_id: str, text: str) -> dict[str, Any]:
    return {
        "action": "send_private_msg",
        "params": {
            "user_id": _user_id(user_qq_id),
            "message": [{"type": "text", "data": {"text": text}}],
        },
        "echo": str(uuid.uuid4()),
    }


def build_send_mface(
    user_qq_id: str,
    *,
    emoji_package_id: int | str,
    emoji_id: str,
    key: str,
    summary: str,
) -> dict[str, Any]:
    return {
        "action": "send_private_msg",
        "params": {
            "user_id": _user_id(user_qq_id),
            "message": [
                {
                    "type": "mface",
                    "data": {
                        "emoji_package_id": emoji_package_id,
                        "emoji_id": emoji_id,
                        "key": key,
                        "summary": summary,
                    },
                }
            ],
        },
        "echo": str(uuid.uuid4()),
    }
