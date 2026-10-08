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

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..emoji_catalog import lookup_emoji

logger = logging.getLogger(__name__)

_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})


@dataclass(frozen=True)
class QqUrlImage:
    url: str


@dataclass(frozen=True)
class QqFileImage:
    file_id: str = ""
    file: str = ""


@dataclass(frozen=True)
class QqInbound:
    text: str
    images: tuple[QqUrlImage | QqFileImage, ...]


def private_text_from_event(event: object, user_qq_id: str) -> str | None:
    """Text of a private message from the configured teacher. Anything else is None."""
    inbound = private_inbound_from_event(event, user_qq_id)
    if inbound is None:
        return None
    return inbound.text or None


def private_inbound_from_event(event: object, user_qq_id: str) -> QqInbound | None:
    """Teacher private text, mall stickers as text, and photo refs."""
    message = _teacher_message(event, user_qq_id)
    if message is None:
        return None
    text, images = _parse_segments(message)
    if not text and not images:
        return None
    return QqInbound(text=text, images=tuple(images))


def _teacher_message(event: object, user_qq_id: str) -> list[Any] | None:
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
    return message


def _parse_segments(message: list[Any]) -> tuple[str, list[QqUrlImage | QqFileImage]]:
    """Walk segments in order: text and mall stickers into text, photos into images."""
    parts: list[str] = []
    images: list[QqUrlImage | QqFileImage] = []
    for segment in message:
        if not isinstance(segment, dict):
            continue
        kind = segment.get("type")
        data = segment.get("data")
        if not isinstance(data, dict):
            continue
        if kind == "text":
            text = str(data.get("text") or "")
            if text:
                parts.append(text)
            continue
        if kind == "file":
            image = _file_image(data)
            if image is not None:
                images.append(image)
            continue
        if kind != "image":
            continue
        sticker = _mall_sticker_text(data)
        if sticker is not None:
            parts.append(sticker)
            continue
        image = _photo_image(data)
        if image is not None:
            images.append(image)
    return "".join(parts).strip(), images


def _mall_sticker_text(data: dict[str, Any]) -> str | None:
    """QQ mall sticker → （表情包：description）. Unknown ids are skipped."""
    emoji_id = str(data.get("emoji_id") or "").strip()
    package_id = str(data.get("emoji_package_id") or "").strip()
    if not emoji_id and not package_id:
        return None
    if not emoji_id:
        return None
    sticker = lookup_emoji(emoji_id)
    if sticker is None:
        return None
    description = (sticker.description or "").strip()
    if not description:
        return None
    return f"（表情包：{description}）"


def _file_image(data: dict[str, Any]) -> QqFileImage | None:
    name = str(data.get("file") or data.get("name") or "").strip()
    if Path(name).suffix.lower() not in _IMAGE_SUFFIXES:
        logger.info("qq file skipped reason=not_image name=%s", name or "-")
        return None
    file_id = str(data.get("file_id") or "").strip()
    if not file_id and not name:
        return None
    return QqFileImage(file_id=file_id, file=name)


def _photo_image(data: dict[str, Any]) -> QqUrlImage | None:
    if str(data.get("emoji_id") or "").strip() or str(data.get("emoji_package_id") or "").strip():
        return None
    sub_type = _sub_type(data)
    if sub_type == 1:
        return None
    summary = str(data.get("summary") or "").strip()
    if sub_type != 0 and not (sub_type is None and not summary):
        return None
    url = str(data.get("url") or "").strip()
    if not url:
        logger.info("qq image skipped reason=no_url")
        return None
    return QqUrlImage(url=url)


def _sub_type(data: dict[str, Any]) -> int | None:
    if "sub_type" not in data:
        return None
    raw = data.get("sub_type")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


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
