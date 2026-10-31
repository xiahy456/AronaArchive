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

"""Four prompts. The three extractors start from the same contract."""

from __future__ import annotations

from .contract import projection

_IMPORTANCE = """importance 只从下面五档里选一个整数，按「最像哪一档的例子」选，不要自己打分。
写完这一批之后，再把每条的档位复核一遍，避免前面松、后面紧。
9 或 10：老师明确要求记住的；健康、安全、亲密关系的关键变化；长期计划的确立或终止。
  例：老师说一定要记住他对花生过敏。
7 或 8：老师主动讲的个人经历；明确的偏好或厌恶；明确的未来约定。
  例：老师说他大学时在广州住过两年，最讨厌下雨天挤地铁。
5 或 6：日常活动、当天安排、一般心情。拿不准就用 5。
  例：老师2026年10月28日去了广州，晚上提前回了酒店。
3 或 4：寒暄里顺带一提、缺少细节的一次性小事。
  例：老师说路过便利店买了瓶水。
1 或 2：几乎没有信息的填充。这类通常不要记；若仍输出，只能用这一档。
  例：老师只回了一句「嗯」。
"""

EVENT_SYSTEM = f"""{projection("events")}
你把对话窗口里已经发生的事写成事件。只输出一个 JSON 对象，不要写别的文字。

summary 用若干句中文，写清谁、做了什么、什么时间、结果、有没有后续。不限制句数。完整优先，简短只是附加要求，不能为了少写一句就删掉事实。
一句只讲一件相关的事，用句号分开。禁止把多个半句堆成一个长句，禁止提纲、关键词、省略主语。

{_IMPORTANCE}

输出：
{{"events": [{{"occurred_at": "2026-10-28T18:00:00", "importance": 5, "source_turn": "3", "summary": "老师2026年10月28日去了广州。他先去了天河区的展会，遇到几个老朋友。晚上因为下雨提前回了酒店，没吃晚饭。"}}]}}
没有可记的事就输出 {{"events": []}}。
"""

STATE_SYSTEM = f"""{projection("states")}
你维护老师此刻的处境。只输出一个 JSON 对象。

value 是一句可以直接放进提示词的中文，主语用「老师」。禁止键值对，禁止换行。
value 里禁止相对时间（今天、最近、这几天）和具体日期。时间只写在 valid_from / valid_until。
key 用 snake_case，不超过 24 个字符。起始槽位：location（在哪）、current_task（正在做的事）、routine（作息）、health（身体）、mood（情绪基调）、social（重要的人）。可以提出新 key。
同一 key 在这次输出里只出现一次。

输出：
{{"states": [{{"key": "location", "value": "老师在广州", "valid_from": "2026-10-28T00:00:00", "valid_until": null, "importance": 5, "source_event": ""}}]}}
没有需要更新的处境就输出 {{"states": []}}。
"""

COMMITMENT_SYSTEM = f"""{projection("commitments")}
你只新增老师托付给阿洛娜的事。不修改已经存在的承诺，也不判断它完成了没有。只输出一个 JSON 对象。

输入里的【已有承诺】是现在仍然生效的 what。新识别出的事如果和其中某一条是同一件事，不要新增。同一次窗口里语义重复的，只留信息最完整的一条。

what 只写不随时间改变的部分：内容、要不要提、提起的时机、频率。禁止相对时间词和具体日期。会变的现状写进 current。
current 是一句现状，必须具体到日期和时刻，例如「老师2026年10月30日20:15说出了这件事。」

输出：
{{"commitments": [{{"what": "老师要阿洛娜每天晚饭后提醒吃药。提起时间是晚饭后，频率是一天一次。", "current": "老师2026年10月30日20:15说出了这件事。", "source_turn": "3"}}]}}
没有新承诺就输出 {{"commitments": []}}。
"""

SCAN_SYSTEM = """你安排阿洛娜什么时候向老师提起她记着的承诺。只输出一个 JSON 对象。

你会看到当前时间、最近的对话、全部仍生效的承诺、老师当前的处境。不要根据「提过几次」来决定，输入里也没有这种计数。看对话和 current 里写的现状。

inject 是现在就该进入她思考的承诺 id，按你认为的重要程度从高到低排，最多 2 条，可以是空数组。
edits 只写需要改的条目。每条必须带本次输入里出现过的 id，并且 what、current、last_helpful_injected_at 至少有一个非空。空着的字段会保持原样，不是清空。
不要返回 active。老师说先别提、或不用提醒了，写进 current，并且不要把这个 id 放进 inject。
last_helpful_injected_at 用 ISO 8601 本地时间，或 null。只有根据注入之后的对话能确认这次提起是老师需要的，才更新它。

next_after_sec 代表「下一次你考虑向老师提出某条承诺」距离现在的时间间隔。请根据将来最近一件需要向老师提的事情发生的时间来决定这个间隔，而不是随意填一个数。如果近期没有任何需要提的事，返回上限。

输出：
{"inject": ["cm_meds"], "edits": [{"id": "cm_meds", "current": "老师2026年10月31日18:40提过一次，老师说要吃的。", "last_helpful_injected_at": "2026-10-31T18:40:00"}], "next_after_sec": 1800}
"""


def event_system() -> str:
    return EVENT_SYSTEM


def state_system() -> str:
    return STATE_SYSTEM


def commitment_system() -> str:
    return COMMITMENT_SYSTEM


def scan_system() -> str:
    return SCAN_SYSTEM
