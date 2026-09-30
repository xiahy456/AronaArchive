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

"""Optional screenshot payloads on chat / transcript messages."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 4 * 1024 * 1024
SCREENSHOT_KEEP = 8
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_ALLOWED_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
}


@dataclass(frozen=True)
class ImagePayload:
    mime: str
    data: bytes

    def data_url(self) -> str:
        encoded = base64.b64encode(self.data).decode("ascii")
        return f"data:{self.mime};base64,{encoded}"


def _normalize_mime(raw: str) -> str | None:
    mime = (raw or "").strip().lower()
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime in _ALLOWED_MIME:
        return mime
    return None


def _infer_mime(data: bytes) -> str | None:
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    return None


def _infer_qq_mime(data: bytes) -> str | None:
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_payload_from_bytes(data: bytes) -> ImagePayload | None:
    """Bytes of a QQ file image. Screenshots keep the stricter jpeg/png parser."""
    if not data:
        return None
    if len(data) > MAX_IMAGE_BYTES:
        logger.info("image dropped reason=too_large bytes=%d", len(data))
        return None
    mime = _infer_qq_mime(data)
    if mime is None:
        logger.info("image dropped reason=not_image bytes=%d", len(data))
        return None
    return ImagePayload(mime=mime, data=data)


def image_payload_from_base64(raw: str) -> ImagePayload | None:
    data = _decode_base64(raw)
    if data is None:
        return None
    return image_payload_from_bytes(data)


def image_payload_from_napcat_file(frame: object) -> ImagePayload | None:
    """Prefer get_file base64. Otherwise read a local path in data.file."""
    if not isinstance(frame, dict):
        return None
    data = frame.get("data")
    if not isinstance(data, dict):
        return None
    encoded = data.get("base64")
    if isinstance(encoded, str) and encoded.strip():
        payload = image_payload_from_base64(encoded)
        if payload is not None:
            return payload
    path = str(data.get("file") or "").strip()
    if not path:
        return None
    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        blob = file_path.read_bytes()
    except OSError:
        logger.info("image dropped reason=unreadable path=%s", path)
        return None
    return image_payload_from_bytes(blob)


def _decode_base64(raw: str) -> bytes | None:
    text = (raw or "").strip()
    if not text:
        return None
    marker = "base64,"
    if marker in text:
        text = text.split(marker, 1)[1]
    try:
        return base64.b64decode(text, validate=False)
    except Exception:
        return None


def parse_optional_image(message: dict[str, Any] | None) -> ImagePayload | None:
    """Parse and validate an optional `image` object from a WS JSON payload."""
    if not isinstance(message, dict):
        return None
    blob = message.get("image")
    if blob is None:
        return None
    if not isinstance(blob, dict):
        logger.warning("image ignored reason=not_object")
        return None
    encoded = blob.get("data")
    if not isinstance(encoded, str) or not encoded.strip():
        logger.warning("image ignored reason=missing_data")
        return None
    data = _decode_base64(encoded)
    if data is None:
        logger.warning("image ignored reason=invalid_base64")
        return None
    if len(data) > MAX_IMAGE_BYTES:
        logger.warning("image ignored reason=too_large bytes=%d", len(data))
        return None
    mime = _normalize_mime(str(blob.get("mime") or blob.get("mime_type") or ""))
    inferred = _infer_mime(data)
    if inferred is None:
        logger.warning("image ignored reason=unknown_format")
        return None
    if mime is None:
        mime = inferred
    elif mime != inferred:
        logger.warning("image ignored reason=mime_mismatch declared=%s inferred=%s", mime, inferred)
        return None
    return ImagePayload(mime=mime, data=data)


def redact_image_fields(value: Any) -> Any:
    """Replace bulky image bytes / data URLs with placeholders for logs."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"data", "base64"} and isinstance(item, str) and len(item) > 24:
                redacted[key] = f"[redacted {len(item)} chars]"
            elif key in {"url", "image_url"}:
                redacted[key] = redact_image_fields(item)
            else:
                redacted[key] = redact_image_fields(item)
        if "url" in redacted and isinstance(redacted["url"], str):
            url = redacted["url"]
            if url.startswith("data:") and len(url) > 24:
                redacted["url"] = f"[redacted data_url {len(url)} chars]"
        return redacted
    if isinstance(value, list):
        return [redact_image_fields(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image") and len(value) > 24:
        return f"[redacted data_url {len(value)} chars]"
    return value


def redact_request_json(raw: str | None) -> str | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return json.dumps(redact_image_fields(parsed), ensure_ascii=False)


def screenshot_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    files: list[Path] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        if not path.name.startswith("screenshot_"):
            continue
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        files.append(path)
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def prune_screenshots(directory: Path, keep: int = SCREENSHOT_KEEP) -> list[Path]:
    kept = screenshot_files(directory)
    removed: list[Path] = []
    for old in kept[keep:]:
        try:
            old.unlink(missing_ok=True)
            removed.append(old)
        except OSError as exc:
            logger.warning("screenshot prune failed path=%s err=%s", old, exc)
    return kept[:keep]


def save_screenshot(
    directory: Path,
    payload: ImagePayload,
    keep: int = SCREENSHOT_KEEP,
) -> Path | None:
    directory.mkdir(parents=True, exist_ok=True)
    ext = _ALLOWED_MIME.get(payload.mime, ".jpg")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    path = directory / f"screenshot_{stamp}{ext}"
    if path.exists():
        path = directory / f"screenshot_{stamp}_{len(payload.data)}{ext}"
    try:
        path.write_bytes(payload.data)
    except OSError as exc:
        logger.warning("screenshot save failed path=%s err=%s", path, exc)
        return None
    prune_screenshots(directory, keep=keep)
    logger.info("screenshot saved path=%s bytes=%d", path.name, len(payload.data))
    return path
