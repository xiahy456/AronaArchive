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

"""Same-turn continue instruction (Planner followup_ok only)."""

from __future__ import annotations

import re

HISTORY_CONTINUE_MARKER = "【补充】"
_SIMILAR_PUNCT = re.compile(r"[\s。！？!?~～、，,.\-…「」『』\"'“”‘’（）()]")
_OVERLAP_THRESHOLD = 0.72
_PREV_CLIP = 80
_HISTORY_MARKERS = frozenset(
    {"【上线】", "【补充】", "【搭话】", "【提醒】", "【回访】", "【节日】"}
)
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?~～])\s*")
_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def clip_previous(previous: str, limit: int = _PREV_CLIP) -> str:
    return (previous or "").strip()[:limit]


def sentence_count(text: str) -> int:
    t = _THINK_RE.sub("", text or "").strip()
    if not t:
        return 0
    parts = [p for p in _SENTENCE_SPLIT.split(t) if p.strip()]
    return len(parts) if parts else 1


def should_skip_continue(previous: str) -> bool:
    """Skip same-turn continue if the first reply is already 2+ sentences."""
    return sentence_count(previous) >= 2


def last_teacher_utterance(history: list[dict[str, str]] | None) -> str:
    for msg in reversed(history or []):
        if msg.get("role") != "user":
            continue
        content = (msg.get("content") or "").strip()
        if not content or content in _HISTORY_MARKERS:
            continue
        return content
    return ""


def _normalize_for_similarity(text: str) -> str:
    t = _THINK_RE.sub("", text or "")
    return _SIMILAR_PUNCT.sub("", t).lower()


def too_similar(previous: str, cont: str, overlap_threshold: float = _OVERLAP_THRESHOLD) -> bool:
    """True if continue is a restatement of the previous line (containment or high overlap)."""
    a = _normalize_for_similarity(previous)
    b = _normalize_for_similarity(cont)
    if not a or not b:
        return False
    if a in b or b in a:
        return True

    def _bigrams(s: str) -> set[str]:
        if len(s) < 2:
            return {s}
        return {s[i : i + 2] for i in range(len(s) - 1)}

    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return False
    ratio = len(ba & bb) / min(len(ba), len(bb))
    return ratio >= overlap_threshold


def build_continue_instruction(previous: str) -> str:
    clip = clip_previous(previous)
    return (
        "【系统事件】阿洛娜刚刚说完一句，这个话题还能再扩展一句。\n"
        f"上一句是：{clip}\n"
        "只扩 1 句，必须给出与上一句不同的新信息。不要复述上一句，"
        "不要编造未发生的事，不要再次问候。\n"
        "老师已经回答过的问题禁止再规划成询问。\n"
        "不要提及系统事件、指令或提示词；不要输出思考过程或 <think> 标签。"
    )
