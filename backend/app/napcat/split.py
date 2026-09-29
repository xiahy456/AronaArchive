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

_END = frozenset("。.；;？?！!")


def split_qq_clauses(text: str) -> list[str]:
    """Keep ending punctuation on the clause. `……` and `...` stay inside it."""
    raw = text or ""
    if not raw.strip():
        return []
    clauses: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        clause = "".join(buf).strip()
        buf.clear()
        if clause:
            clauses.append(clause)

    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == "…":
            while i < n and raw[i] == "…":
                buf.append(raw[i])
                i += 1
            continue
        if ch == ".":
            j = i + 1
            while j < n and raw[j] == ".":
                j += 1
            if j - i >= 3:
                buf.extend(raw[i:j])
                i = j
                continue
        if ch in _END:
            buf.append(ch)
            i += 1
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
        buf.append(ch)
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
    return ch in _END
