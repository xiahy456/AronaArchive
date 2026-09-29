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

"""Crisis detection and local Arona-voiced fallback (not a helpline poster)."""

from __future__ import annotations

import re

CRISIS_FALLBACK_EMOTION = "worried"

CRISIS_FALLBACK_REPLY = (
    "老师……阿洛娜在的。现在一定很难受吧，请先留在这里，让我陪着您。"
    "不要一个人把这些扛过去。阿洛娜……会一直陪着您的。"
)

# High precision: explicit self-harm / ending one's life. Do not reuse fatigue
# phrases such as 好累 / 撑不住 / 好困.
_CRISIS_RE = re.compile(
    r"("
    r"自杀|轻生|自尽|"
    r"不想活|不想再活|不想活下去|不想再活下去|"
    r"想死|想去死|我想死|"
    r"活不下去|没有活下去|"
    r"结束自己的生命|结束生命|了结自己|自我了断|自己了断|"
    r"杀掉自己|杀了自己|"
    r"割腕|跳楼|遗书|"
    r"kill\s*myself|want\s*to\s*die|end\s*my\s*life|suicide"
    r")",
    re.IGNORECASE,
)


def is_crisis_text(text: str | None) -> bool:
    """True only for explicit crisis / self-harm wording."""
    raw = (text or "").strip()
    if not raw:
        return False
    return bool(_CRISIS_RE.search(raw))


def turns_contain_crisis(
    user_text: str | None = None,
    user_turns: list[str] | None = None,
) -> bool:
    if is_crisis_text(user_text):
        return True
    for turn in user_turns or []:
        if is_crisis_text(turn):
            return True
    return False


def crisis_fallback_reply() -> str:
    """Local Arona-voiced line when the crisis planner is unavailable."""
    return CRISIS_FALLBACK_REPLY
