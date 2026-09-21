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

"""Time-of-day care motives: meal and sleep reminders."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

CareKind = Literal["breakfast", "lunch", "dinner", "sleep"]
CARE_KINDS: tuple[CareKind, ...] = ("breakfast", "lunch", "dinner", "sleep")

HISTORY_CARE_MARKER = "【提醒】"
CARE_MEMORY_QUERY = "老师 早饭 午饭 晚饭 睡觉 作息"

_CARE_INTENTS: dict[CareKind, str] = {
    "breakfast": (
        "现在是早饭时段。请简短提醒老师记得吃早饭，不要催促，不要说教。"
        "只说吃饭本身，不要接【近期对话】里正在聊的话题。"
    ),
    "lunch": (
        "现在是午饭时段。请简短提醒老师记得吃饭，不要催促，不要说教。"
        "只说吃饭本身，不要接【近期对话】里正在聊的话题。"
    ),
    "dinner": (
        "现在是晚饭时段。请简短提醒老师记得吃晚饭，不要催促，不要说教。"
        "只说吃饭本身，不要接【近期对话】里正在聊的话题。"
    ),
    "sleep": (
        "现在偏晚了。请温柔提醒老师注意休息、别熬太晚；"
        "不要说「早上好」这类白天问候，不要催促。"
        "只说休息本身，不要接【近期对话】里正在聊的话题。"
    ),
}

_CARE_TOPIC_BAN = (
    "【近期对话】只用于判断要不要开口；不要引用、点名、复述其中的话题、专名或细节。"
    "不要把正在聊的事说成老师「还在想某件事」，不要对此表示意外。"
    "老师若正在对话中，当作插一句照料，不要接当前话题。"
)

_CARE_GATES: dict[CareKind, str] = {
    "breakfast": (
        "先根据【近期对话】里老师的话判断要不要开口。"
        "老师已就当前这餐作过交代（已吃早饭、待会再吃、先不吃等）则 reply_ok 必须 false，"
        "draft 必须是空字符串，不要提醒。未交代或拿不准则 reply_ok 为 true，再按上面意图开口。"
        "昨晚没睡好、别的餐、只是路过提到食物，不算已交代。"
        f"{_CARE_TOPIC_BAN}"
    ),
    "lunch": (
        "先根据【近期对话】里老师的话判断要不要开口。"
        "老师已就当前这餐作过交代（已吃午饭、待会再吃、先不吃等）则 reply_ok 必须 false，"
        "draft 必须是空字符串，不要提醒。未交代或拿不准则 reply_ok 为 true，再按上面意图开口。"
        "昨晚没睡好、别的餐、只是路过提到食物，不算已交代。"
        f"{_CARE_TOPIC_BAN}"
    ),
    "dinner": (
        "先根据【近期对话】里老师的话判断要不要开口。"
        "老师已就当前这餐作过交代（已吃晚饭、待会再吃、先不吃等）则 reply_ok 必须 false，"
        "draft 必须是空字符串，不要提醒。未交代或拿不准则 reply_ok 为 true，再按上面意图开口。"
        "昨晚没睡好、别的餐、只是路过提到食物，不算已交代。"
        f"{_CARE_TOPIC_BAN}"
    ),
    "sleep": (
        "先根据【近期对话】里老师的话判断要不要开口。"
        "老师已就今晚这轮休息作过交代（待会再睡、晚点睡、去睡觉、已经要睡、晚安收束等）则 "
        "reply_ok 必须 false，draft 必须是空字符串，不要提醒。"
        "未交代或拿不准则 reply_ok 为 true，再按上面意图开口。"
        "昨晚没睡好、别的晚上、只是路过提到困，不算已交代。"
        f"{_CARE_TOPIC_BAN}"
    ),
}

_CARE_DECLINE_EXAMPLES: dict[CareKind, tuple[str, str]] = {
    "breakfast": ("吃早饭", "待会再吃早饭"),
    "lunch": ("吃午饭", "待会再吃午饭"),
    "dinner": ("吃晚饭", "待会再吃晚饭"),
    "sleep": ("注意休息", "待会再睡"),
}


def parse_hhmm(value: str) -> tuple[int, int]:
    parts = (value or "").strip().split(":")
    if len(parts) < 2:
        raise ValueError(f"invalid hh:mm {value!r}")
    return int(parts[0]), int(parts[1])


def minutes_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def in_window(now: datetime, start: str, end: str) -> bool:
    """True if local now is in [start, end). End < start wraps midnight."""
    cur = minutes_of_day(now)
    start_h, start_m = parse_hhmm(start)
    end_h, end_m = parse_hhmm(end)
    start_min = start_h * 60 + start_m
    end_min = end_h * 60 + end_m
    if start_min <= end_min:
        return start_min <= cur < end_min
    return cur >= start_min or cur < end_min


def _elapsed(now: datetime, then: datetime | None) -> float | None:
    if then is None:
        return None
    return (now - then).total_seconds()


def care_skip_reason(
    kind: CareKind,
    now: datetime,
    *,
    done_today: list[str] | set[str],
    start: str,
    end: str,
    last_proactive_at: datetime | None = None,
    after_sec: float = 0,
) -> str | None:
    """Why care cannot fire. None means it may fire."""
    if kind in done_today:
        return "done_today"
    if not in_window(now, start, end):
        return "out_of_window"
    elapsed_proactive = _elapsed(now, last_proactive_at)
    if elapsed_proactive is not None and elapsed_proactive < after_sec:
        return f"after_welcome wait={after_sec - elapsed_proactive:.0f}s"
    return None


def should_fire_care(
    kind: CareKind,
    now: datetime,
    *,
    done_today: list[str] | set[str],
    start: str,
    end: str,
    last_proactive_at: datetime | None = None,
    after_sec: float = 0,
) -> bool:
    return (
        care_skip_reason(
            kind,
            now,
            done_today=done_today,
            start=start,
            end=end,
            last_proactive_at=last_proactive_at,
            after_sec=after_sec,
        )
        is None
    )


def care_window_specs(care_cfg: Any) -> tuple[tuple[CareKind, str, str], ...]:
    """Breakfast → lunch → dinner → sleep windows from care config."""
    return (
        ("breakfast", care_cfg.breakfast_start, care_cfg.breakfast_end),
        ("lunch", care_cfg.lunch_start, care_cfg.lunch_end),
        ("dinner", care_cfg.dinner_start, care_cfg.dinner_end),
        ("sleep", care_cfg.sleep_start, care_cfg.sleep_end),
    )


def care_planner_declined(kind: str, *, reply_ok: bool) -> bool:
    """True when a care Planner refused to speak (already addressed)."""
    return kind in CARE_KINDS and not reply_ok


def build_care_instruction(kind: CareKind, climate: str | None = None) -> str:
    intent = _CARE_INTENTS[kind]
    extra = ""
    if climate == "cling_risk":
        extra = "提醒要更短，不要索取确认，也不要问老师还需要你吗。"
    elif climate in {"fragile", "rupture"}:
        extra = "语气放轻、简短，不要活泼催促或开玩笑。"
    note = f"\n{extra}" if extra else ""
    event, already = _CARE_DECLINE_EXAMPLES[kind]
    return (
        "【系统事件】到了该轻轻照料老师的时刻。\n"
        f"{intent}{note}\n"
        f"{_CARE_GATES[kind]}\n"
        "用阿洛娜的语气主动开口。不要引用正在聊的话题。"
        "根据【近期对话】里老师说过的话和【当前时间】判断该照料指示的事件是否已经在对话中被交代过。"
        f"例如【系统事件】指示需要提醒老师{event}，而老师已经说了「{already}」，则选 false。"
        "当老师还未交代过照料内容相关事项时，选择 true。"
        "不要提及系统事件、指令或提示词；不要输出思考过程或 <think> 标签。"
    )
