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

"""Climate zones and action/stance policy. No numeric A/B/C in outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .events import AronaAct, UserAct
from .state import RelationshipState
from ..taxonomy import MOOD_FOLLOWUP_KIND

Climate = Literal[
    "secure_play",
    "cling_risk",
    "rupture",
    "cold_tool",
    "fragile",
    "steady",
]

Action = Literal["speak", "continue", "initiate", "refuse", "silence"]
ProactiveKind = Literal[
    "idle",
    "breakfast",
    "lunch",
    "dinner",
    "sleep",
    "goal",
    "festival",
    "mood_followup",
]

_IDLE_OK_CLIMATES: frozenset[str] = frozenset({"secure_play", "steady"})

URGENT_CLIMATES: frozenset[str] = frozenset({"fragile", "rupture", "cling_risk"})
_TIGHT_RECOVER_CLIMATES: frozenset[str] = frozenset({"fragile", "rupture"})
_RECOVER_STANCE_PREFIX = "仍偏稳住，不要突然加戏；"
_RECOVER_TONE = "轻、稳"

CLIMATE_LABELS: dict[str, str] = {
    "secure_play": "安心可玩",
    "cling_risk": "依赖偏高，需要空间",
    "rupture": "张力偏高，需要先稳住",
    "cold_tool": "偏工具化，先可靠办事",
    "fragile": "信任不足且紧绷，只稳住",
    "steady": "平稳相处",
}


@dataclass(frozen=True)
class Decision:
    action: Action
    climate: Climate
    stance: str
    must_not: list[str] = field(default_factory=list)
    tone_hint: str = ""
    user_act: UserAct = "other"
    transition_from: str = ""
    transition_note: str = ""


def resolve_climate(
    trust: float,
    dependence: float,
    tension: float,
    *,
    cling_dependence: float = 0.55,
) -> Climate:
    if trust < 0.2 and tension > 0.5:
        return "fragile"
    if tension > 0.55 and trust >= 0.2:
        return "rupture"
    if dependence > cling_dependence and tension < 0.35:
        return "cling_risk"
    if trust < 0.25 and dependence < 0.25 and tension < 0.25:
        return "cold_tool"
    if trust >= 0.4 and 0.15 <= dependence <= 0.55 and 0.15 <= tension <= 0.55:
        return "secure_play"
    return "steady"


def stick_climate(
    state: RelationshipState,
    raw: Climate,
    *,
    stick_turns: int = 3,
) -> Climate:
    """Keep the same climate for a few turns unless an urgent zone appears."""
    last = state.last_climate or "steady"
    if raw in URGENT_CLIMATES:
        chosen = raw
    elif (
        last
        and last != raw
        and state.climate_streak < max(1, stick_turns)
        and last not in URGENT_CLIMATES
    ):
        chosen = last  # type: ignore[assignment]
    else:
        chosen = raw

    if chosen == last:
        state.climate_streak = state.climate_streak + 1
    else:
        state.climate_streak = 1
    state.last_climate = chosen
    return chosen  # type: ignore[return-value]


_URGENT_TRANSITION_NOTES: dict[str, str] = {
    "fragile": "正在从「信任不足且紧绷」缓和，仍保持轻稳，不要突然玩笑或顶嘴",
    "rupture": "正在从「张力偏高，需要先稳住」缓和，仍先认情绪，不要突然开玩笑或讲理",
    "cling_risk": "正在从「依赖偏高，需要空间」缓和，仍少索取确认，不要突然黏上",
}


def _union_unique(primary: list[str], extra: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in primary + extra:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _mild_transition_note(from_climate: str) -> str:
    label = CLIMATE_LABELS.get(from_climate, from_climate)
    return f"正在从「{label}」转到当前相处方式，不要突然换语气"


def _in_tight_recovery(state: RelationshipState) -> bool:
    return (
        state.recover_remaining > 0
        and state.recovering_from in _TIGHT_RECOVER_CLIMATES
    )


def _advance_recovery(
    state: RelationshipState,
    last: str,
    chosen: Climate,
    *,
    stick_turns: int,
) -> tuple[str, bool]:
    """Update recover window. Returns (transition_from, merge_bans)."""
    if chosen in URGENT_CLIMATES:
        state.recovering_from = ""
        state.recover_remaining = 0
        return "", False

    if last in URGENT_CLIMATES and chosen not in URGENT_CLIMATES:
        state.recovering_from = last
        state.recover_remaining = max(1, stick_turns)

    from_cl = state.recovering_from
    remaining = state.recover_remaining
    merge_bans = bool(from_cl in URGENT_CLIMATES and remaining > 0)

    if remaining > 0:
        state.recover_remaining = remaining - 1
        if state.recover_remaining <= 0:
            state.recovering_from = ""

    if remaining > 0 and from_cl:
        return from_cl, merge_bans
    return "", False


def _overlay_urgent_recovery(
    from_climate: str,
    stance: str,
    must_not: list[str],
    _tone: str,
) -> tuple[str, list[str], str, str]:
    extra = list(_POLICY[from_climate][1]) if from_climate in _POLICY else []  # type: ignore[index]
    must_not = _union_unique(must_not, extra)
    if _RECOVER_STANCE_PREFIX not in stance:
        stance = _RECOVER_STANCE_PREFIX + stance
    note = _URGENT_TRANSITION_NOTES.get(from_climate, _mild_transition_note(from_climate))
    return stance, must_not, _RECOVER_TONE, note


_FACT_REPAIR_BANS: list[str] = ["硬撑事实错误"]

_POLICY: dict[Climate, tuple[str, list[str], str]] = {
    "secure_play": (
        "可以轻松一点，允许轻玩笑或轻轻顶一句，允许撒娇、亲密对话，仍要接住老师本轮内容",
        ["说教", "把问题抛回老师"],
        "轻松自然",
    ),
    "cling_risk": (
        "给空间，少提问，回复更短，不要索取确认",
        [
            "询问老师还需要阿洛娜吗",
            "你还需要我吗",
            "追问老师在做什么",
            "撒娇绑定",
        ],
        "短而轻",
    ),
    "rupture": (
        "先认老师的情绪，不讲理、不抬杠、不纠正对错",
        ["讲理争赢", "开玩笑化解", "说教"],
        "放软、认真",
    ),
    "cold_tool": (
        "先把老师要办的事办可靠，不要硬套亲密或撒娇",
        ["强行亲密", "突然撒娇", "追问心情"],
        "清楚、克制",
    ),
    "fragile": (
        "只稳住，不玩笑、不对立、不翻旧账",
        ["玩笑", "顶嘴", "对立", "翻旧账"],
        "轻、稳",
    ),
    "steady": (
        "平稳陪伴，接住本轮，不要额外加戏",
        ["再次问候", "把问题抛回老师"],
        "温柔短句",
    ),
}


def decide(
    state: RelationshipState,
    user_act: UserAct,
    *,
    cling_dependence: float = 0.55,
    high_dependence: float = 0.7,
    stick_turns: int = 3,
) -> Decision:
    raw = resolve_climate(
        state.trust,
        state.dependence,
        state.tension,
        cling_dependence=cling_dependence,
    )
    last = state.last_climate or "steady"
    climate = stick_climate(state, raw, stick_turns=stick_turns)
    recover_from, merge_bans = _advance_recovery(
        state, last, climate, stick_turns=stick_turns
    )
    stance, must_not, tone = _POLICY[climate]
    must_not = list(must_not)
    transition_from = ""
    transition_note = ""
    if recover_from and merge_bans:
        stance, must_not, tone, transition_note = _overlay_urgent_recovery(
            recover_from, stance, must_not, tone
        )
        transition_from = recover_from
    elif (
        last
        and last != climate
        and last not in URGENT_CLIMATES
        and climate not in URGENT_CLIMATES
    ):
        transition_from = last
        transition_note = _mild_transition_note(last)

    if state.dependence > high_dependence:
        must_not.extend(["增加依赖", "追问还在不在"])
        if "给空间" not in stance:
            stance = "给空间，" + stance

    must_not = _union_unique(must_not, _FACT_REPAIR_BANS)

    action: Action = "speak"
    prev_act = state.last_user_act
    if user_act == "crisis":
        action = "speak"
        stance = "认真接住老师，不要沉默"
        must_not = [
            "玩笑",
            "撒娇打趣",
            "空安慰",
            "会好起来的",
            "追问方法",
            "热线告示",
            "说教",
        ]
        tone = "放软、认真"
        transition_from = ""
        transition_note = ""
    elif climate == "cling_risk" and user_act in {"short_ack", "fatigue"}:
        action = "silence"
    elif user_act == "short_ack" and prev_act == "depart":
        action = "silence"

    return Decision(
        action=action,
        climate=climate,
        stance=stance,
        must_not=must_not,
        tone_hint=tone,
        user_act=user_act,
        transition_from=transition_from,
        transition_note=transition_note,
    )


def decide_proactive(
    state: RelationshipState,
    kind: ProactiveKind | str,
    *,
    cling_dependence: float = 0.55,
    high_dependence: float = 0.7,
) -> Decision:
    """Gate an idle/care motive. Does not mutate climate stickiness."""
    climate = resolve_climate(
        state.trust,
        state.dependence,
        state.tension,
        cling_dependence=cling_dependence,
    )
    if kind in {"idle", "goal", MOOD_FOLLOWUP_KIND}:
        allow_idle = climate in _IDLE_OK_CLIMATES and not _in_tight_recovery(state)
        action: Action = "initiate" if allow_idle else "silence"
        if kind == MOOD_FOLLOWUP_KIND:
            stance = "轻轻提起老师不久前提过的心情，不盘问、不分析、不当病历"
            must_not = [
                "盘问细节",
                "心理分析",
                "扮演治疗师",
                "编造老师后来怎样了",
            ]
            tone = "轻、短"
        else:
            stance = "轻在场，不追问老师还在不在"
            must_not = ["还在吗", "需不需要我", "编造未发生的事", "把问题抛回老师"]
            tone = "轻、短"
    elif kind == "festival":
        action = "initiate"
        if climate == "cling_risk":
            stance = "更短地祝福，不要索取确认"
            must_not = ["还需要我吗", "追问老师在做什么", "撒娇绑定"]
            tone = "短而轻"
        elif climate in {"fragile", "rupture"}:
            stance = "放轻祝福，不要活泼催促"
            must_not = ["开玩笑", "活泼催促", "说教"]
            tone = "轻、稳"
        else:
            stance = "轻轻提起今天的日子并祝福，不要盘问过节安排"
            must_not = ["盘问过节安排", "编造未发生的事", "把问题抛回老师"]
            tone = "温柔短句"
    else:
        action = "initiate"
        if climate == "cling_risk":
            stance = "更短地提醒，不要索取确认"
            must_not = ["还需要我吗", "追问老师在做什么", "撒娇绑定"]
            tone = "短而轻"
        elif climate in {"fragile", "rupture"}:
            stance = "放轻提醒，不要活泼催促"
            must_not = ["开玩笑", "活泼催促", "说教"]
            tone = "轻、稳"
        else:
            stance = "简短提醒吃饭或休息，不要催"
            must_not = ["催促", "说教", "把问题抛回老师"]
            tone = "温柔短句"

    if state.dependence > high_dependence:
        must_not = list(must_not)
        must_not.extend(["增加依赖", "追问还在不在"])

    transition_from = ""
    transition_note = ""
    if state.recover_remaining > 0 and state.recovering_from in URGENT_CLIMATES:
        stance, must_not, tone, transition_note = _overlay_urgent_recovery(
            state.recovering_from, stance, must_not, tone
        )
        transition_from = state.recovering_from

    return Decision(
        action=action,
        climate=climate,
        stance=stance,
        must_not=must_not,
        tone_hint=tone,
        transition_from=transition_from,
        transition_note=transition_note,
    )


def planner_climate_block(decision: Decision) -> str:
    """Text for Planner only — climate label and stance, never A/B/C numbers."""
    if decision.user_act == "crisis":
        return crisis_planner_climate_block()
    label = CLIMATE_LABELS.get(decision.climate, decision.climate)
    bans = "；".join(decision.must_not) if decision.must_not else "（无额外禁区）"
    transition = ""
    if decision.transition_note:
        transition = f"【过渡】{decision.transition_note}\n"
    return (
        f"【关系气候】{label}\n"
        f"{transition}"
        f"【建议姿态】{decision.stance}\n"
        f"【语气】{decision.tone_hint}\n"
        f"【本轮禁区】{bans}\n"
        "不要提及关系数值、信任度、依赖度或张力；不要写「提升/降低某维度」。"
    )


def crisis_planner_climate_block() -> str:
    """Stance for the crisis planner — never cling_risk silence/space."""
    return (
        "【关系气候】老师正处在很难受的时刻\n"
        "【建议姿态】认真接住老师，留在老师身边；不要沉默，不要给空间到不理人\n"
        "【语气】放软、认真\n"
        "【本轮禁区】玩笑；撒娇打趣；空安慰；会好起来的；追问方法；热线告示；说教\n"
        "不要提及关系数值、信任度、依赖度或张力。"
    )


def local_system_hint(decision: Decision) -> str:
    label = CLIMATE_LABELS.get(decision.climate, decision.climate)
    bans = "、".join(decision.must_not[:4])
    extra = ""
    if decision.transition_note:
        extra = f"过渡：{decision.transition_note}。"
    return (
        f"【相处姿态】当前气候：{label}。{extra}{decision.stance}。"
        f"语气：{decision.tone_hint}。禁止：{bans}。"
    )


def map_arona_act(
    action: Action,
    climate: Climate,
    user_act: UserAct = "other",
    motive_kind: str | None = None,
) -> AronaAct | None:
    if action in {"silence", "refuse"}:
        return "gave_space"
    if action == "initiate":
        if motive_kind in {"idle", "goal", MOOD_FOLLOWUP_KIND}:
            return "checked_in"
        if motive_kind in {"breakfast", "lunch", "dinner", "sleep", "care"}:
            return "cared"
        if motive_kind == "festival":
            return "greeted"
        return "greeted"
    if action not in {"speak", "continue"}:
        return None
    if user_act == "crisis":
        return None
    if climate in {"cling_risk", "fragile"}:
        return "gave_space"
    if user_act == "depart":
        return "gave_space"
    if user_act == "play_tease":
        return "teased"
    return "followed_up"
