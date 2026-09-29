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

"""Heuristic triggers for memory extraction (W2/W5)."""

from __future__ import annotations

import re

# Explicit remember
_EXPLICIT = re.compile(r"(请记住|记住这个|帮我记住|不要忘记)")

# First-person fact-ish patterns
_FACTISH = re.compile(
    r"(我叫|我的名字|我是|我姓|"
    r"我喜欢|我不喜欢|我讨厌|我爱|"
    r"我住|我家|我在|"
    r"我的爱好|我的生日|我今年|"
    r"记得我|以后叫我|称呼我)"
)

# Shared time with Arona, or a confirmed mood disclosure.
_EPISODEISH = re.compile(
    r"(一起|陪我|陪你|我们去了|我们看了|"
    r"今天被|心里|难过|开心不起来|有点慌|害怕|委屈|失眠|被批评)"
)


def should_extract(
    user_text: str,
    *,
    turn_count: int,
    every_n_turns: int,
    buffer_turns: int = 0,
    extract_buffer_turns: int = 0,
) -> bool:
    text = (user_text or "").strip()
    if not text:
        return False
    if _EXPLICIT.search(text):
        return True
    if _FACTISH.search(text):
        return True
    if _EPISODEISH.search(text):
        return True
    if every_n_turns > 0 and turn_count > 0 and turn_count % every_n_turns == 0:
        return True
    if extract_buffer_turns > 0 and buffer_turns >= extract_buffer_turns:
        return True
    return False
