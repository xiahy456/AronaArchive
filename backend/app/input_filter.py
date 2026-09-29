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

"""Reject unusable user inputs (empty / ASR SDK error strings) before chat."""

from __future__ import annotations

import re

# Soft reply when dirty ASR text is dropped at WS (does not enter history).
ASR_FALLBACK_REPLY = "刚才没听清，请再说一次～"
ASR_FALLBACK_EMOTION = "curious"

_DIRTY_SUBSTRINGS = (
    "[Tencent Speech Recognizer]",
    "Didnt recognize",
    "Didn't recognize",
    "Didnt recognize vailable content",
    "Audio data is null",
    "Request failed",
    "TencentCloud authentication",
    "TencentClout API error",
    "JSON analysis error",
)

# Whole-message English SDK / ASR error blobs
_DIRTY_FULL_RE = re.compile(
    r"^\s*\[Tencent Speech Recognizer\].+\s*$",
    re.IGNORECASE,
)


def is_unusable_user_text(content: str | None) -> bool:
    """Return True if content should not enter Planner / history."""
    if content is None:
        return True
    text = str(content).strip()
    if not text:
        return True
    lower = text.lower()
    for needle in _DIRTY_SUBSTRINGS:
        if needle.lower() in lower:
            return True
    if _DIRTY_FULL_RE.match(text):
        return True
    return False
