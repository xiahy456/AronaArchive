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

"""Split a spoken line into QQ messages. Ellipsis does not break a clause."""

from __future__ import annotations

import unicodedata

_END = frozenset("。.；;？?！!")
_COMMA = frozenset("，,")
_MIN_COMMA_WORDS = 3


def split_qq_clauses(text: str) -> list[str]:
    """Split on sentence marks, and on a comma after at least three words.

    Ending `。` `.` `，` `,` are removed. `……`, `...`, `..`, `？`, and `！` stay.
    """
    raw = text or ""
    if not raw.strip():
        return []
    clauses: list[str] = []
    buf: list[str] = []
    words = 0

    def flush() -> None:
        nonlocal words
        clause = _strip_trailing_stop("".join(buf).strip())
        buf.clear()
        words = 0
        if clause:
            clauses.append(clause)

    def append_char(ch: str) -> None:
        nonlocal words
        buf.append(ch)
        if _is_word(ch):
            words += 1
        elif _is_punct(ch):
            words = 0

    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == "…":
            while i < n and raw[i] == "…":
                buf.append(raw[i])
                i += 1
            words = 0
            continue
        if ch == ".":
            j = i + 1
            while j < n and raw[j] == ".":
                j += 1
            if j - i >= 3:
                buf.extend(raw[i:j])
                i = j
                words = 0
                continue
        if ch in _COMMA and words < _MIN_COMMA_WORDS:
            append_char(ch)
            i += 1
            continue
        if ch in _END or ch in _COMMA:
            buf.append(ch)
            i += 1
            words = 0
            while i < n and _continues_delimiter(raw, i):
                if raw[i] == ".":
                    j = i + 1
                    while j < n and raw[j] == ".":
                        j += 1
                    buf.extend(raw[i:j])
                    i = j
                    continue
                buf.append(raw[i])
                i += 1
            flush()
            continue
        append_char(ch)
        i += 1
    flush()
    return clauses


def _continues_delimiter(raw: str, index: int) -> bool:
    ch = raw[index]
    if ch == "…":
        return False
    if ch == ".":
        j = index + 1
        while j < len(raw) and raw[j] == ".":
            j += 1
        return (j - index) < 3
    return ch in _END or ch in _COMMA


def _is_punct(ch: str) -> bool:
    return unicodedata.category(ch).startswith("P")


def _is_word(ch: str) -> bool:
    return not ch.isspace() and not _is_punct(ch)


def _strip_trailing_stop(clause: str) -> str:
    """Drop a trailing period or comma. Ellipsis and a two-dot run stay."""
    while clause:
        if clause.endswith("…") or clause.endswith(".."):
            return clause
        if clause[-1] in "。.，,":
            clause = clause[:-1].rstrip()
            continue
        return clause
    return clause
