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

"""Small helpers for memory_v2. No semantic heuristics."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

_RELATIVE_TIME = re.compile(
    r"今天|今日|明天|明日|后天|昨天|昨日|最近|这几天|下周|上周|今晚|今早|这个月|下个月|下月"
)
_ABSOLUTE_DATE = re.compile(
    r"\d{4}\s*年|\d{1,2}\s*月\s*\d{1,2}\s*[日号]|\d{4}-\d{1,2}-\d{1,2}"
)
_STATE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
_SENTENCE_END = "。！？!?."


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def has_relative_time(text: str) -> bool:
    return _RELATIVE_TIME.search(text or "") is not None


def has_absolute_date(text: str) -> bool:
    return _ABSOLUTE_DATE.search(text or "") is not None


def has_ephemeral_time(text: str) -> bool:
    """Relative words or calendar dates. Used to reject what / state value."""
    blob = text or ""
    return has_relative_time(blob) or has_absolute_date(blob)


def valid_state_key(key: str, *, max_chars: int = 24) -> bool:
    text = (key or "").strip()
    if not text or len(text) > max_chars:
        return False
    return _STATE_KEY.fullmatch(text) is not None


def clamp_importance(value: object) -> tuple[int, bool]:
    """Return a 1–10 integer and whether the original value was changed."""
    if isinstance(value, bool) or value is None:
        return 5, True
    if isinstance(value, int):
        if 1 <= value <= 10:
            return value, False
        return min(10, max(1, value)), True
    if isinstance(value, float):
        rounded = int(value + 0.5) if value >= 0 else int(value - 0.5)
        clamped = min(10, max(1, rounded))
        return clamped, True
    text = str(value).strip()
    try:
        number = float(text)
    except (TypeError, ValueError):
        return 5, True
    if number == int(number) and 1 <= int(number) <= 10:
        return int(number), False
    rounded = int(number + 0.5) if number >= 0 else int(number - 0.5)
    return min(10, max(1, rounded)), True


def truncate_at_sentence(text: str, limit: int) -> tuple[str, bool]:
    """Cut at the last sentence end within limit. Never slice a sentence in half.

    If the first sentence itself is longer than limit, keep that whole sentence.
    """
    raw = (text or "").strip()
    if limit <= 0 or len(raw) <= limit:
        return raw, False
    window = raw[:limit]
    cut = max(window.rfind(mark) for mark in _SENTENCE_END)
    if cut >= 0:
        return window[: cut + 1].strip(), True
    end = -1
    for index, char in enumerate(raw):
        if char in _SENTENCE_END:
            end = index
            break
    if end >= 0:
        return raw[: end + 1].strip(), True
    return raw, True


def parse_timestamp(value: object, *, now: datetime | None = None) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        pass
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if match:
        year, month, day = (int(match.group(i)) for i in range(1, 4))
        clock = re.search(r"(\d{1,2})[:：点时](\d{1,2})?", text[match.end() : match.end() + 12])
        hour = minute = 0
        if clock:
            hour = int(clock.group(1))
            minute = int(clock.group(2) or 0)
        try:
            return datetime(year, month, day, hour, minute).timestamp()
        except ValueError:
            return None
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        try:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            ).timestamp()
        except ValueError:
            return None
    del now
    return None


def parse_iso_local(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def first_sentence(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    end = len(raw)
    for index, char in enumerate(raw):
        if char in "。！？":
            end = index + 1
            break
    return raw[:end].strip()


def loads_json_object(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("llm json is not an object")
    return parsed


def approx_chars_for_tokens(tokens: int) -> int:
    return max(32, int(int(tokens) * 1.6))


def fts_document(text: str) -> str:
    """Space-separate characters so FTS5 unicode61 can match Chinese."""
    return " ".join(ch for ch in (text or "") if not ch.isspace())


def fts_match(text: str) -> str:
    """Phrase-AND query. Segments shorter than two characters are dropped."""
    segments: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if len(buf) >= 2:
            segments.append('"' + " ".join(buf) + '"')
        buf.clear()

    for char in text or "":
        if char.isalnum() or "\u4e00" <= char <= "\u9fff":
            buf.append(char)
        else:
            flush()
    flush()
    return " AND ".join(segments)


def api_key_ready(api_key: str) -> bool:
    key = (api_key or "").strip()
    return bool(key and key != "YOUR_DEEPSEEK_API_KEY")
