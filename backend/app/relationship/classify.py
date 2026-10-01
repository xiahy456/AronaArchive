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

"""Rule-based user-act classifier. Unrecognized text is `other`."""

from __future__ import annotations

import re

from ..safety import is_crisis_text
from ..taxonomy import CRISIS_USER_ACT
from .events import UserAct

_REJECT_RE = re.compile(
    r"(别烦|不要烦|闭嘴|你说得不对|说得不对|滚|烦死|走开|别烦我)"
)
# Strong leave-taking: match anywhere in a single utterance.
_HARD_DEPART_RE = re.compile(
    r"(离开一会|离开一下|先走了|我得走|有事情要干|有事要忙|我先去忙|我去忙|"
    r"回头再聊|失陪|有个任务|任务需要完成|我先去办|"
    r"去做别的|做别的事)"
)
# Soft wait / brief pause: only short utterances count as depart.
_SOFT_WAIT_RE = re.compile(
    r"(稍等|等一下|等我一下|马上回来|马上就回|一会就回|一会儿就回)"
)
_SOFT_WAIT_MAX_COMPACT = 24
_WORRY_BOND_RE = re.compile(
    r"(会不会感到厌烦|会不会厌烦|嫌弃|打扰到你|烦到你|你会不会厌|是不是烦)"
)
_AFFECTION_RE = re.compile(
    r"(也是我的幸福|我的幸福|很开心|心情很好|心情不错|过得很好|过得不错|"
    r"好喜欢|喜欢你|想你|开心见到|看到阿洛娜)"
)
_GRATITUDE_RE = re.compile(r"(谢谢|感谢|多谢|谢啦|谢了)")
_VALIDATION_RE = re.compile(
    r"(做得对吗|做的对吗|你觉得我|对不对|是不是该|有没有搞错|这样可以吗)"
)
_FATIGUE_RE = re.compile(r"(好累|累了|好困|不想动|疲惫|好疲|撑不住)")
_TEASE_RE = re.compile(r"(笨笨|傻瓜|小笨蛋|阿洛娜笨|你好笨|哈哈你)")
_INSTRUMENTAL_RE = re.compile(
    r"(帮我写|帮我查|帮我改|怎么实现|如何实现|翻译一下|解释一下代码|这段代码)"
)
_DISCLOSE_RE = re.compile(
    r"(今天被|心里|难过|开心不起来|有点慌|害怕|委屈|失眠|被批评)"
)
_SHORT_ACK_RE = re.compile(
    r"^(嗯+|哦+|啊+|呃+|好+|行|ok|okay|嗯嗯|哦哦|好的|好吧|知道了)$",
    re.IGNORECASE,
)


def _compact(text: str) -> str:
    return re.sub(r"[\s!~！。？?~～…,.，、]+", "", text)


def _classify_single(raw: str) -> UserAct:
    """Classify one utterance (no newline coalescing)."""
    text = (raw or "").strip()
    if not text:
        return "other"
    compact = _compact(text)

    if is_crisis_text(text):
        return CRISIS_USER_ACT  # type: ignore[return-value]
    if _REJECT_RE.search(text):
        return "reject"
    if _HARD_DEPART_RE.search(text):
        return "depart"
    if _SOFT_WAIT_RE.search(text) and len(compact) <= _SOFT_WAIT_MAX_COMPACT:
        return "depart"
    if _WORRY_BOND_RE.search(text):
        return "worry_bond"
    if _AFFECTION_RE.search(text):
        return "affection"
    if _GRATITUDE_RE.search(text):
        return "gratitude"
    if _VALIDATION_RE.search(text):
        return "seek_validation"
    if _FATIGUE_RE.search(text):
        return "fatigue"
    if _TEASE_RE.search(text):
        return "play_tease"
    if _INSTRUMENTAL_RE.search(text):
        return "instrumental"
    if _DISCLOSE_RE.search(text):
        return "self_disclose"
    if len(compact) <= 6 and _SHORT_ACK_RE.match(compact):
        return "short_ack"
    if len(compact) <= 2 and compact in {"嗯", "哦", "啊", "好", "行"}:
        return "short_ack"
    return "other"


def classify_user_act(text: str) -> UserAct:
    raw = (text or "").strip()
    if not raw:
        return "other"

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) <= 1:
        return _classify_single(raw)

    # QQ coalesce joins bursts with \\n. Only treat as depart when the last
    # line (or a majority of lines) is leave-taking; otherwise keep the
    # strongest non-depart intent from the burst.
    acts = [_classify_single(line) for line in lines]
    depart_count = sum(1 for act in acts if act == "depart")
    if acts[-1] == "depart" or depart_count > len(acts) / 2:
        return "depart"
    for act in reversed(acts):
        if act not in {"depart", "other"}:
            return act
    for act in reversed(acts):
        if act != "depart":
            return act
    return "other"
