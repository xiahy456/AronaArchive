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

"""Deterministic quality checks before persisting memories."""

from __future__ import annotations

import re

_MIN_CONTENT_LEN = 4

# Ends like a question / soft interrogative particle.
_QUESTION_END = re.compile(r"[？?吗呢]\s*$")

# Clear interrogative / undecided structures in Chinese memory text.
_INTERROGATIVE = re.compile(
    r"(什么|哪个|哪些|哪位|谁|怎么|如何|是否|有没有|是不是|要不要|好不好)"
)

# Content that is only punctuation / placeholders.
_ONLY_NOISE = re.compile(r"^[\s\-_.…·,，。！!？?~～、；;：:]+$")


def memory_reject_reason(key: str, content: str) -> str | None:
    """Return a short reject reason, or None if the memory is acceptable."""
    _ = key  # reserved for future key-based rules
    text = (content or "").strip()
    if not text:
        return "empty"
    if len(text) < _MIN_CONTENT_LEN:
        return "too_short"
    if _ONLY_NOISE.match(text):
        return "noise_only"
    if _QUESTION_END.search(text):
        return "question_like"
    if _INTERROGATIVE.search(text):
        return "interrogative"
    return None


def is_valid_memory(key: str, content: str) -> bool:
    return memory_reject_reason(key, content) is None
