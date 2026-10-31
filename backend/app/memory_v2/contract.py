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

"""Single definition of what belongs to events, states, and commitments."""

from __future__ import annotations

TIME_RULES = """时间规则（对照【当前时间】换算，禁止把相对说法原样留下）：
- 能确定到日就写年月日；能确定到时刻就写到时刻。只能确定到月或年时，停在那一层。
- 今天、明天、后天、昨天、下周、下个月，都换成绝对日期。缺少年份的月日，用【当前时间】补年份。
- 事件的 occurred_at 是这件事发生的时间，用 ISO 8601 本地时间（2026-10-28T13:46:00）。时刻不明就用 00:00:00。
- 状态的 valid_from / valid_until 也用 ISO 8601。valid_until 为空表示这条处境仍然成立、没有已知的结束时刻。
- 状态句子和承诺的 what 本身不写相对时间，也不写具体日期。会过期的说法放进状态的时间字段，或承诺的 current。
"""

_CROSS = """跨层规则：
1. 同一句话可以同时产生事件和状态，但状态只记「因此老师现在处于什么处境」，不把事件本身再写一遍。
2. 未来要做的事归承诺。若它同时改变了当前处境（「明天出发，今天在收拾行李」），状态只记现在的处境。
3. 拿不准这条归哪一层时，不要产出，留给下一次对话窗口。
"""

_LAYERS = {
    "events": """你这一层只记已经发生的事，而且能确定或推断出发生时间。
不归你管：还没发生的事；老师此刻仍然成立的处境（那是状态）；老师托阿洛娜以后去做的事（那是承诺）。
""",
    "states": """你这一层只记此刻仍然成立、并且会随时间改变的处境。
不归你管：已经做完的单次事件；稳定不变的偏好；未来计划本身。计划若改变了现在的处境，只写现在的处境。
""",
    "commitments": """你这一层只记老师托付阿洛娜在将来去做或提醒的事。
不归你管：老师自己的计划；已经完成的事；单纯的情绪。你只新增，不判断完成、暂停或过期。
""",
}


def projection(layer: str) -> str:
    """Prompt prefix shared by the three extractors. One definition, three views."""
    body = _LAYERS.get(layer)
    if body is None:
        raise ValueError(f"unknown memory_v2 layer: {layer}")
    return f"{body}\n{_CROSS}\n{TIME_RULES}"
