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

"""Assemble the text a thought would read. No model call and no writes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from ...proactive.care import in_window
from ...proactive.festival import match_festival
from ...proactive.goal import goal_is_due_soon
from ...query_time import format_clock_stamp, format_full_datetime
from ...safety import is_crisis_text
from ..journal import ACTIVITY_SUMMARY
from ..state import THOUGHT_RUMINATION_PREFIX, InnerState
from .store import PendingTrigger, ThoughtLedger

CRISIS_LINE = "老师刚才很难过"
JOURNAL_TAIL = 6
TALK_TURNS = 8
KNOWLEDGE_MAX = 2
KNOWLEDGE_MARKS = ("基沃托斯", "学生")

SECTION_ORDER = (
    "当前时间",
    "触发",
    "阿洛娜此刻",
    "上一次想法",
    "她的笔记",
    "今天",
    "最近的话",
    "老师的档案",
    "相关常识",
    "现状",
    "瞥见",
)

_WHY = {
    "aftertaste": "回味已到点",
    "arrived": "老师刚接上",
    "left": "老师刚离开",
    "glance": "刚瞥见屏幕",
    "memory": "有一条还没在笔记里点名的档案",
    "climate": "气氛刚变了",
    "revisit": "这件事放得够久",
    "spontaneous": "自发间隔到了",
    "consolidate": "到了休息整理的时候",
}

_MOOD = {
    "calm": "平静",
    "bright": "明快",
    "weary": "疲倦",
    "preoccupied": "放不下",
    "sleepy": "想睡",
}

_ATTENTION = {
    "teacher": "老师",
    "self": "自己",
    "rumination": "心事",
    "diffuse": "散着",
}

_CARE_LABEL = {
    "breakfast": "早饭",
    "lunch": "午饭",
    "dinner": "晚饭",
    "sleep": "睡觉",
}

_NEED_SECTION = {
    "memory": "老师的档案",
    "screen": "瞥见",
    "knowledge": "相关常识",
    "recent_talk": "最近的话",
}


@dataclass(frozen=True)
class SourceContext:
    """Facts the caller already loaded. This module does not touch listen buffers."""

    teacher_online: bool = False
    climate: str = ""
    seconds_since_teacher: float | None = None
    seconds_since_arona: float | None = None
    journal: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    turns: tuple[tuple, ...] = ()
    ended_turns: tuple[tuple, ...] = ()
    reused_memories: tuple[str, ...] = ()
    reused_knowledge: tuple[str, ...] = ()
    goals: tuple[tuple[str, str], ...] = ()
    care_done: frozenset[str] = field(default_factory=frozenset)
    goal_acked: dict[str, str] = field(default_factory=dict)
    away_sec: float | None = None
    last_user_act: str = ""
    glance_text: str = ""
    glance_at: datetime | None = None
    already_greeted: bool = False
    memory_key: str = ""
    memory_content: str = ""
    care_windows: tuple[tuple[str, str, str], ...] = ()
    birthday_content: str = ""
    due_soon_sec: float = 3600.0
    focus_text: str = ""
    knowledge: Callable[[str], Sequence[str]] | None = None
    situation: tuple = ()


@dataclass(frozen=True)
class SourceText:
    cancelled: bool = False
    text: str = ""


def select_sources(
    trigger: PendingTrigger,
    now: datetime,
    inner: InnerState,
    ledger: ThoughtLedger,
    ctx: SourceContext | None = None,
) -> SourceText:
    """Build one prompt body. An empty glance cancels the beat."""
    facts = ctx or SourceContext()
    if trigger.kind == "glance" and not (facts.glance_text or "").strip():
        return SourceText(cancelled=True, text="")
    seen = {"crisis": False}
    sections = _sections(trigger, now, inner, ledger, facts, seen)
    return SourceText(cancelled=False, text=_render(sections))


def fill_need(
    text: str,
    names: Sequence[str],
    ctx: SourceContext | None = None,
    *,
    now: datetime | None = None,
) -> str:
    """Add sections named by a second hop. Unknown names are ignored."""
    facts = ctx or SourceContext()
    at = now or datetime.now()
    sections = _parse_sections(text)
    seen = {"crisis": CRISIS_LINE in (text or "")}
    for name in names:
        header = _NEED_SECTION.get(str(name or "").strip())
        if header is None or sections.get(header):
            continue
        rows = _need_rows(header, at, facts, seen)
        if rows:
            sections[header] = rows
    return _render(sections)


def _sections(
    trigger: PendingTrigger,
    now: datetime,
    inner: InnerState,
    ledger: ThoughtLedger,
    ctx: SourceContext,
    seen: dict[str, bool],
) -> dict[str, list[str]]:
    kind = trigger.kind
    focus = _focus_text(ledger, inner, trigger, ctx)
    sections: dict[str, list[str]] = {name: [] for name in SECTION_ORDER}
    sections["当前时间"] = [_keep(format_clock_stamp(now), seen)]
    why = _WHY.get(kind, "到了该想一想的时候")
    sections["触发"] = [_keep(f"{kind}。{why}", seen)]
    sections["阿洛娜此刻"] = _here(kind, inner, trigger, ctx, seen)
    sections["上一次想法"] = _previous(ledger, seen)
    sections["她的笔记"] = _notes(kind, ctx, seen)
    sections["今天"] = _today(kind, now, ledger, ctx, seen)
    sections["最近的话"] = _talk(kind, ctx, seen)
    sections["老师的档案"] = _archive(kind, trigger, now, ctx, seen)
    sections["相关常识"] = _knowledge(kind, focus, ctx, seen)
    sections["现状"] = _status(kind, now, ctx, seen)
    if kind == "glance":
        sections["瞥见"] = _glance_rows(ctx, seen)
    return sections


def _here(
    kind: str,
    inner: InnerState,
    trigger: PendingTrigger,
    ctx: SourceContext,
    seen: dict[str, bool],
) -> list[str]:
    rows = [
        _keep(ACTIVITY_SUMMARY.get(inner.activity, "在教室"), seen),
        _keep(f"心情{_MOOD.get(inner.private_mood, inner.private_mood)}", seen),
        _keep(f"注意力在{_ATTENTION.get(inner.attention, inner.attention)}", seen),
    ]
    focus_id = trigger.focus_id
    for item in inner.rumination:
        content = _keep(item.content, seen)
        if not content:
            continue
        line = f"{item.id} {content}"
        if kind == "revisit" and item.id == focus_id:
            line = f"这一次回访 {line}"
        rows.append(line)
    if kind == "revisit" and ctx.last_user_act:
        rows.append(_keep(f"老师当时是{ctx.last_user_act}", seen))
    if ctx.climate:
        rows.append(_keep(f"气氛是{ctx.climate}", seen))
    return [row for row in rows if row]


def _previous(ledger: ThoughtLedger, seen: dict[str, bool]) -> list[str]:
    focus = ledger.focus
    text = (focus.text if focus is not None else "") or ledger.last_focus
    cleaned = _keep(text, seen)
    if not cleaned:
        return []
    spoken = focus is not None and focus.spoken
    mark = "已经说过" if spoken else "还没说过"
    return [f"{cleaned}。{mark}"]


def _notes(kind: str, ctx: SourceContext, seen: dict[str, bool]) -> list[str]:
    if kind in {"spontaneous", "consolidate"}:
        rows = list(ctx.notes)
    elif kind == "glance":
        rows = [note for note in ctx.notes if "老师" in note]
    else:
        return []
    return [line for line in (_keep(row, seen) for row in rows) if line]


def _today(
    kind: str,
    now: datetime,
    ledger: ThoughtLedger,
    ctx: SourceContext,
    seen: dict[str, bool],
) -> list[str]:
    rows = [_keep("老师在线" if ctx.teacher_online else "老师不在", seen)]
    if ctx.seconds_since_teacher is not None:
        rows.append(_keep(f"距老师上次说话{_ago(ctx.seconds_since_teacher)}", seen))
    if ctx.seconds_since_arona is not None:
        rows.append(_keep(f"距她上次开口{_ago(ctx.seconds_since_arona)}", seen))
    count = ledger.speak_count if ledger.speak_day == now.date().isoformat() else 0
    rows.append(_keep(f"阿洛娜今天因思考开过{max(0, int(count))}次口", seen))
    if kind == "consolidate":
        journal = list(ctx.journal)
    elif kind in {"spontaneous", "arrived"}:
        journal = list(ctx.journal[-JOURNAL_TAIL:])
    else:
        journal = []
    rows.extend(line for line in (_keep(row, seen) for row in journal) if line)
    return [row for row in rows if row]


def _talk(kind: str, ctx: SourceContext, seen: dict[str, bool]) -> list[str]:
    if kind == "aftertaste":
        turns = ctx.ended_turns
    elif kind == "left":
        turns = ctx.turns[-1:]
    elif kind == "spontaneous":
        turns = ctx.turns[-TALK_TURNS:]
    else:
        return []
    return _format_turns(turns, seen)


def _archive(
    kind: str,
    trigger: PendingTrigger,
    now: datetime,
    ctx: SourceContext,
    seen: dict[str, bool],
) -> list[str]:
    if kind == "aftertaste":
        return [line for line in (_keep(row, seen) for row in ctx.reused_memories) if line]
    if kind == "memory" and ctx.memory_content:
        body = _keep(ctx.memory_content, seen)
        if not body:
            return []
        mark = "已经说过" if _acked_today(ctx.memory_key or trigger.memory_key, ctx, now) else "还没提过"
        return [f"{body}。{mark}"]
    if kind == "revisit":
        key = trigger.memory_key or ctx.memory_key
        if not key:
            return []
        content = ctx.memory_content
        if not content:
            for goal_key, goal_content in ctx.goals:
                if goal_key == key:
                    content = goal_content
                    break
        body = _keep(content, seen)
        if not body:
            return []
        mark = "已经说过" if _acked_today(key, ctx, now) else "还没提过"
        return [f"{body}。{mark}"]
    return []


def _knowledge(
    kind: str,
    focus: str,
    ctx: SourceContext,
    seen: dict[str, bool],
) -> list[str]:
    if kind == "aftertaste":
        rows = list(ctx.reused_knowledge[:KNOWLEDGE_MAX])
        return [line for line in (_keep(row, seen) for row in rows) if line]
    if ctx.knowledge is None or not _wants_knowledge(focus):
        return []
    found = list(ctx.knowledge(focus))[:KNOWLEDGE_MAX]
    return [line for line in (_keep(row, seen) for row in found) if line]


_STATUS_KINDS = frozenset({"arrived", "spontaneous", "revisit"})


def _status(
    kind: str,
    now: datetime,
    ctx: SourceContext,
    seen: dict[str, bool],
) -> list[str]:
    rows: list[str] = []
    if kind in _STATUS_KINDS:
        for fact in ctx.situation:
            line = _keep(str(getattr(fact, "text", "") or ""), seen)
            if line:
                rows.append(line)
    if kind != "arrived":
        return [row for row in rows if row]
    if ctx.situation:
        if ctx.away_sec is not None:
            rows.append(_keep(f"离开了{_ago(ctx.away_sec)}", seen))
        if ctx.already_greeted:
            rows.append(_keep("本时段已经问候过", seen))
        return [row for row in rows if row]
    if ctx.away_sec is not None:
        rows.append(_keep(f"离开了{_ago(ctx.away_sec)}", seen))
    if ctx.already_greeted:
        rows.append(_keep("本时段已经问候过", seen))
    for key, content in ctx.goals:
        if not goal_is_due_soon(content, now, due_soon_sec=ctx.due_soon_sec):
            continue
        body = _keep(content, seen)
        if not body:
            continue
        if _acked_today(key, ctx, now):
            body = f"{body}。已经说过"
        rows.append(body)
    hit = match_festival(now, ctx.birthday_content)
    if hit is not None and hit.name:
        rows.append(_keep(f"今天是{hit.name}", seen))
    for care_kind, start, end in ctx.care_windows:
        if not in_window(now, start, end):
            continue
        label = _CARE_LABEL.get(care_kind, care_kind)
        if care_kind in ctx.care_done:
            rows.append(_keep(f"今天已经提过{label}", seen))
        else:
            rows.append(_keep(f"{label}窗口还没提过", seen))
    return [row for row in rows if row]


def _glance_rows(ctx: SourceContext, seen: dict[str, bool]) -> list[str]:
    line = _keep(ctx.glance_text, seen)
    if not line:
        return []
    if isinstance(ctx.glance_at, datetime):
        line = f"[{format_full_datetime(ctx.glance_at)}] {line}"
    return [line]


def _need_rows(
    header: str,
    now: datetime,
    ctx: SourceContext,
    seen: dict[str, bool],
) -> list[str]:
    if header == "老师的档案":
        rows = [line for line in (_keep(row, seen) for row in ctx.reused_memories) if line]
        if rows:
            return rows
        if ctx.memory_content:
            body = _keep(ctx.memory_content, seen)
            return [body] if body else []
        return []
    if header == "瞥见":
        return _glance_rows(ctx, seen)
    if header == "相关常识":
        return _knowledge("spontaneous", ctx.focus_text, ctx, seen)
    if header == "最近的话":
        return _format_turns(ctx.turns[-TALK_TURNS:], seen)
    del now
    return []


def _format_turns(
    turns: Sequence[tuple],
    seen: dict[str, bool],
) -> list[str]:
    rows: list[str] = []
    for turn in turns:
        teacher = str(turn[0] or "") if turn else ""
        arona = str(turn[1] or "") if len(turn) > 1 else ""
        teacher_at = _talk_time(turn[2]) if len(turn) > 2 else None
        arona_at = _talk_time(turn[3]) if len(turn) > 3 else None
        teacher_line = _keep(teacher, seen)
        arona_line = _keep(arona, seen)
        if teacher_line:
            rows.append(_speak_line("老师", teacher_line, teacher_at))
        if arona_line:
            rows.append(_speak_line("阿洛娜", arona_line, arona_at))
    return rows


def _speak_line(who: str, text: str, at: datetime | None) -> str:
    if at is None:
        return f"{who}: {text}"
    return f"[{format_full_datetime(at)}] {who}: {text}"


def _talk_time(raw: object) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _focus_text(
    ledger: ThoughtLedger,
    inner: InnerState,
    trigger: PendingTrigger,
    ctx: SourceContext,
) -> str:
    if ctx.focus_text.strip():
        return ctx.focus_text.strip()
    if ledger.focus is not None and ledger.focus.text.strip():
        return ledger.focus.text.strip()
    if ledger.last_focus.strip():
        return ledger.last_focus.strip()
    for item in inner.rumination:
        if trigger.focus_id and item.id == trigger.focus_id:
            return item.content.strip()
    for item in inner.rumination:
        if item.id.startswith(THOUGHT_RUMINATION_PREFIX):
            return item.content.strip()
    return ""


def _wants_knowledge(focus: str) -> bool:
    text = (focus or "").strip()
    if not text or is_crisis_text(text):
        return False
    return any(mark in text for mark in KNOWLEDGE_MARKS)


def _acked_today(key: str, ctx: SourceContext, now: datetime) -> bool:
    raw = str(ctx.goal_acked.get(key) or "").strip()
    if not raw:
        return False
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return stamp.date() == now.date()


def _keep(text: str, seen: dict[str, bool]) -> str:
    line = " ".join((text or "").split())
    if not line:
        return ""
    if is_crisis_text(line):
        if seen["crisis"]:
            return ""
        seen["crisis"] = True
        return CRISIS_LINE
    return line


def _ago(seconds: float) -> str:
    sec = max(0, int(seconds))
    if sec < 60:
        return f"{sec}秒"
    if sec < 3600:
        return f"{sec // 60}分钟"
    return f"{sec // 3600}小时"


def _render(sections: dict[str, list[str]]) -> str:
    blocks: list[str] = []
    for name in SECTION_ORDER:
        rows = [row for row in sections.get(name, []) if row]
        if not rows:
            continue
        blocks.append(f"【{name}】\n" + "\n".join(rows))
    return "\n".join(blocks)


def _parse_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {name: [] for name in SECTION_ORDER}
    current = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("【") and line.endswith("】"):
            name = line[1:-1]
            if name in sections:
                current = name
                continue
        if current and line:
            sections[current].append(line)
    return sections
