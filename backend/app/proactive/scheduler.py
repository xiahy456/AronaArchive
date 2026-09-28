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

"""Persist last activity / daily caps and pick at most one proactive motive."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from ..config import FestivalConfig, GoalConfig, MoodFollowupConfig
from ..taxonomy import MOOD_FOLLOWUP_KIND
from ..safety import is_crisis_text
from .care import (
    CARE_KINDS,
    CARE_MEMORY_QUERY,
    HISTORY_CARE_MARKER,
    build_care_instruction,
    care_skip_reason,
    care_window_specs,
    in_window,
)
from .festival import (
    HISTORY_FESTIVAL_MARKER,
    FestivalHit,
    build_festival_instruction,
    match_festival,
)
from .goal import (
    HISTORY_GOAL_MARKER,
    build_goal_instruction,
    can_attempt_goal,
    goal_is_due_soon,
    has_important_goal,
    last_any_goal_at,
    select_goal,
)
from .idle import (
    HISTORY_IDLE_MARKER,
    build_idle_instruction,
    idle_skip_reason,
    should_fire_idle,
)
from .mood import (
    HISTORY_MOOD_MARKER,
    build_mood_instruction,
    can_attempt_mood,
    mood_entry_age_seconds,
    select_mood_entry,
)

logger = logging.getLogger(__name__)

MotiveKind = Literal[
    "idle",
    "breakfast",
    "lunch",
    "dinner",
    "sleep",
    "goal",
    "festival",
    "mood_followup",
]


_CARE_FACT_LABEL = {
    "breakfast": "早饭",
    "lunch": "午饭",
    "dinner": "晚饭",
    "sleep": "睡觉",
}


@dataclass(frozen=True)
class SituationFact:
    """One present-tense fact. It does not write an instruction or enqueue speech."""

    kind: str
    text: str
    key: str = ""
    due_soon: bool = False


@dataclass(frozen=True)
class Motive:
    kind: MotiveKind
    instruction: str
    history_marker: str
    retrieve_memory: bool = False
    memory_query: str = ""
    goal_key: str = ""
    mood_key: str = ""
    festival_id: str = ""
    extra_memories: tuple[str, ...] = ()
    due_soon: bool = False


@dataclass
class ProactiveState:
    last_user_at: str = ""
    last_proactive_at: str = ""
    last_idle_at: str = ""
    day: str = ""
    idle_count: int = 0
    care_done: list[str] = field(default_factory=list)
    goal_last: dict[str, str] = field(default_factory=dict)
    goal_mute: dict[str, str] = field(default_factory=dict)
    goal_acked: dict[str, str] = field(default_factory=dict)
    goal_count: int = 0
    last_goal_key: str = ""
    mood_last: dict[str, str] = field(default_factory=dict)
    mood_mute: dict[str, str] = field(default_factory=dict)
    mood_acked: dict[str, str] = field(default_factory=dict)
    mood_count: int = 0
    last_mood_key: str = ""
    festival_done: list[str] = field(default_factory=list)

    def roll_day(self, now: datetime) -> None:
        today = now.date().isoformat()
        if self.day != today:
            self.day = today
            self.idle_count = 0
            self.care_done = []
            self.goal_count = 0
            self.mood_count = 0
            self.festival_done = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_user_at": self.last_user_at,
            "last_proactive_at": self.last_proactive_at,
            "last_idle_at": self.last_idle_at,
            "day": self.day,
            "idle_count": self.idle_count,
            "care_done": list(self.care_done),
            "goal_last": dict(self.goal_last),
            "goal_mute": dict(self.goal_mute),
            "goal_acked": dict(self.goal_acked),
            "goal_count": self.goal_count,
            "last_goal_key": self.last_goal_key,
            "mood_last": dict(self.mood_last),
            "mood_mute": dict(self.mood_mute),
            "mood_acked": dict(self.mood_acked),
            "mood_count": self.mood_count,
            "last_mood_key": self.last_mood_key,
            "festival_done": list(self.festival_done),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ProactiveState:
        if not data:
            return cls()
        done = data.get("care_done") or []
        if not isinstance(done, list):
            done = []
        festivals = data.get("festival_done") or []
        if not isinstance(festivals, list):
            festivals = []
        return cls(
            last_user_at=str(data.get("last_user_at") or ""),
            last_proactive_at=str(data.get("last_proactive_at") or ""),
            last_idle_at=str(data.get("last_idle_at") or ""),
            day=str(data.get("day") or ""),
            idle_count=int(data.get("idle_count") or 0),
            care_done=[str(item) for item in done if item],
            goal_last=_as_str_dict(data.get("goal_last")),
            goal_mute=_as_str_dict(data.get("goal_mute")),
            goal_acked=_as_str_dict(data.get("goal_acked")),
            goal_count=int(data.get("goal_count") or 0),
            last_goal_key=str(data.get("last_goal_key") or ""),
            mood_last=_as_str_dict(data.get("mood_last")),
            mood_mute=_as_str_dict(data.get("mood_mute")),
            mood_acked=_as_str_dict(data.get("mood_acked")),
            mood_count=int(data.get("mood_count") or 0),
            last_mood_key=str(data.get("last_mood_key") or ""),
            festival_done=[str(item) for item in festivals if item],
        )


def _as_str_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for key, item in value.items():
        k = str(key or "").strip()
        v = str(item or "").strip()
        if k and v:
            out[k] = v
    return out


def _parse_iso(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _same_day(raw: object, now: datetime) -> bool:
    stamp = _parse_iso(str(raw or ""))
    return stamp is not None and stamp.date() == now.date()


def _muted_until(raw: object, now: datetime) -> bool:
    until = _parse_iso(str(raw or ""))
    return until is not None and now < until


class ProactiveScheduler:
    def __init__(
        self,
        path: Path,
        *,
        idle_cfg: Any,
        care_cfg: Any,
        goal_cfg: Any | None = None,
        festival_cfg: Any | None = None,
        mood_cfg: Any | None = None,
    ) -> None:
        self.path = path
        self.idle_cfg = idle_cfg
        self.care_cfg = care_cfg
        self.goal_cfg = goal_cfg if goal_cfg is not None else GoalConfig()
        self.festival_cfg = (
            festival_cfg if festival_cfg is not None else FestivalConfig()
        )
        self.mood_cfg = mood_cfg if mood_cfg is not None else MoodFollowupConfig()
        self.state = self._load()

    def _load(self) -> ProactiveState:
        if not self.path.is_file():
            return ProactiveState(day=date.today().isoformat())
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("proactive load failed path=%s", self.path)
            return ProactiveState(day=date.today().isoformat())
        if not isinstance(raw, dict):
            return ProactiveState(day=date.today().isoformat())
        state = ProactiveState.from_dict(raw)
        if not state.day:
            state.day = date.today().isoformat()
        return state

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self.state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def note_user_activity(self, now: datetime | None = None) -> None:
        dt = now or datetime.now()
        self.state.roll_day(dt)
        self.state.last_user_at = dt.isoformat(timespec="seconds")
        self.save()

    def note_proactive(self, now: datetime | None = None) -> None:
        dt = now or datetime.now()
        self.state.roll_day(dt)
        self.state.last_proactive_at = dt.isoformat(timespec="seconds")
        self.save()

    def mark_fired(
        self,
        kind: MotiveKind,
        now: datetime | None = None,
        *,
        goal_key: str = "",
        festival_id: str = "",
        mood_key: str = "",
        due_soon: bool = False,
    ) -> None:
        dt = now or datetime.now()
        self.state.roll_day(dt)
        stamp = dt.isoformat(timespec="seconds")
        self.state.last_proactive_at = stamp
        if kind == "idle":
            self.state.last_idle_at = stamp
            self.state.idle_count += 1
        elif kind == "goal":
            self.state.goal_count += 1
            key = (goal_key or "").strip()
            if key:
                self.state.last_goal_key = key
                self.state.goal_last[key] = stamp
                if due_soon:
                    self.state.goal_acked[key] = stamp
        elif kind == MOOD_FOLLOWUP_KIND:
            self.state.mood_count += 1
            key = (mood_key or "").strip()
            if key:
                self.state.last_mood_key = key
                self.state.mood_last[key] = stamp
        elif kind == "festival":
            fid = (festival_id or "").strip()
            if fid and fid not in self.state.festival_done:
                self.state.festival_done.append(fid)
        elif kind not in self.state.care_done:
            self.state.care_done.append(kind)
        self.save()

    def note_mentioned(
        self,
        kind: str,
        now: datetime | None = None,
        *,
        goal_key: str = "",
        festival_id: str = "",
        mood_key: str = "",
        due_soon: bool = False,
    ) -> None:
        """Record that she already mentioned this. Does not start a cooldown or a mute."""
        dt = now or datetime.now()
        self.state.roll_day(dt)
        stamp = dt.isoformat(timespec="seconds")
        if kind == "idle":
            self.state.last_idle_at = stamp
        elif kind == "goal":
            key = (goal_key or "").strip()
            if key:
                self.state.last_goal_key = key
                self.state.goal_last[key] = stamp
                if due_soon:
                    self.state.goal_acked[key] = stamp
        elif kind == MOOD_FOLLOWUP_KIND:
            key = (mood_key or "").strip()
            if key:
                self.state.last_mood_key = key
                self.state.mood_last[key] = stamp
        elif kind == "festival":
            fid = (festival_id or "").strip()
            if fid and fid not in self.state.festival_done:
                self.state.festival_done.append(fid)
        elif kind in CARE_KINDS and kind not in self.state.care_done:
            self.state.care_done.append(kind)
        self.save()

    def mark_care_addressed(
        self, kind: MotiveKind, now: datetime | None = None
    ) -> None:
        """Mark a care kind done today without touching last_proactive_at."""
        if kind not in CARE_KINDS:
            return
        dt = now or datetime.now()
        self.state.roll_day(dt)
        if kind not in self.state.care_done:
            self.state.care_done.append(kind)
            self.save()

    def mute_last_goal(self, now: datetime | None = None) -> str | None:
        key = (self.state.last_goal_key or "").strip()
        if not key:
            return None
        dt = now or datetime.now()
        mute_sec = float(getattr(self.goal_cfg, "mute_sec", 604800))
        until = dt + timedelta(seconds=mute_sec)
        self.state.goal_mute[key] = until.isoformat(timespec="seconds")
        self.save()
        logger.info("goal muted key=%s until=%s", key, self.state.goal_mute[key])
        return key

    def ack_pending_followups(self, now: datetime | None = None) -> list[str]:
        """Ack goal/mood keys fired since last_user_at. Does not stamp user activity."""
        dt = now or datetime.now()
        stamp = dt.isoformat(timespec="seconds")
        since = _parse_iso(self.state.last_user_at)
        acked: list[str] = []
        goal_keys: list[str]
        mood_keys: list[str]
        if since is None:
            goal_keys = [self.state.last_goal_key] if self.state.last_goal_key else []
            mood_keys = [self.state.last_mood_key] if self.state.last_mood_key else []
        else:
            goal_keys = []
            for key, fired in self.state.goal_last.items():
                parsed = _parse_iso(fired)
                if parsed is not None and parsed >= since:
                    goal_keys.append(key)
            mood_keys = []
            for key, fired in self.state.mood_last.items():
                parsed = _parse_iso(fired)
                if parsed is not None and parsed >= since:
                    mood_keys.append(key)
        for key in goal_keys:
            k = (key or "").strip()
            if not k:
                continue
            self.state.goal_acked[k] = stamp
            acked.append(k)
        for key in mood_keys:
            k = (key or "").strip()
            if not k:
                continue
            self.state.mood_acked[k] = stamp
            acked.append(k)
        if acked:
            self.save()
            logger.info("followup acked keys=%s", acked)
        return acked

    def _mute_mood(self, key: str, now: datetime) -> str:
        mute_sec = float(getattr(self.mood_cfg, "mute_sec", 604800))
        until = now + timedelta(seconds=mute_sec)
        self.state.mood_mute[key] = until.isoformat(timespec="seconds")
        self.save()
        logger.info("mood muted key=%s until=%s", key, self.state.mood_mute[key])
        return key

    def mute_last_followup(self, now: datetime | None = None) -> str | None:
        """Mute the more recently fired goal or mood follow-up key."""
        dt = now or datetime.now()
        goal_key = (self.state.last_goal_key or "").strip()
        mood_key = (self.state.last_mood_key or "").strip()
        goal_at = (
            _parse_iso(str(self.state.goal_last.get(goal_key) or ""))
            if goal_key
            else None
        )
        mood_at = (
            _parse_iso(str(self.state.mood_last.get(mood_key) or ""))
            if mood_key
            else None
        )
        if mood_at is not None and (goal_at is None or mood_at >= goal_at):
            return self._mute_mood(mood_key, dt)
        if goal_key:
            return self.mute_last_goal(dt)
        if mood_key:
            return self._mute_mood(mood_key, dt)
        return None

    def pending_festival(
        self,
        now: datetime | None = None,
        *,
        birthday_content: str = "",
    ) -> FestivalHit | None:
        if not getattr(self.festival_cfg, "enabled", True):
            return None
        dt = now or datetime.now()
        self.state.roll_day(dt)
        hit = match_festival(dt, birthday_content)
        if hit is None or hit.id in self.state.festival_done:
            return None
        return hit

    def situation_facts(
        self,
        now: datetime | None = None,
        *,
        last_user_act: str = "other",
        climate: str | None = None,
        goals: list[dict[str, object]] | None = None,
        moods: list[dict[str, object]] | None = None,
        birthday_content: str = "",
        quiet_sec: float | None = None,
        speak_count: int = 0,
    ) -> list[SituationFact]:
        """Facts she can notice. Caps, cooldowns, mutes, and depart do not remove them."""
        dt = now or datetime.now()
        self.state.roll_day(dt)
        facts: list[SituationFact] = []
        if getattr(self.care_cfg, "enabled", True):
            for kind, start, end in care_window_specs(self.care_cfg):
                if not in_window(dt, start, end):
                    continue
                label = _CARE_FACT_LABEL.get(kind, kind)
                if kind in self.state.care_done:
                    text = f"今天已经提过{label}"
                else:
                    text = f"现在处于{label}窗口，今天还没提过{label}"
                facts.append(SituationFact(kind=kind, text=text))
        if getattr(self.festival_cfg, "enabled", True):
            hit = match_festival(dt, birthday_content)
            if hit is not None and hit.name:
                if hit.id in self.state.festival_done:
                    text = f"今天是{hit.name}，已经祝贺"
                else:
                    text = f"今天是{hit.name}，还没祝贺"
                facts.append(SituationFact(kind="festival", text=text, key=hit.id))
        if getattr(self.goal_cfg, "enabled", True):
            due_soon_sec = float(getattr(self.goal_cfg, "due_soon_sec", 3600) or 0)
            care_enabled = bool(getattr(self.care_cfg, "enabled", True))
            for item in goals or []:
                key = str(item.get("key") or "").strip()
                content = str(item.get("content") or "").strip()
                if not key or not content or is_crisis_text(content):
                    continue
                if not goal_is_due_soon(
                    content, dt, due_soon_sec=due_soon_sec, care_enabled=care_enabled
                ):
                    continue
                mentioned = _same_day(self.state.goal_last.get(key), dt)
                mark = "今天已经提过" if mentioned else "今天还没提过"
                text = f"{content}。{mark}"
                if _muted_until(self.state.goal_mute.get(key), dt):
                    text += "。老师说过先别提"
                facts.append(
                    SituationFact(kind="goal", text=text, key=key, due_soon=True)
                )
        if getattr(self.mood_cfg, "enabled", True):
            min_age = float(self.mood_cfg.min_age_sec)
            max_age = float(self.mood_cfg.max_age_hours) * 3600.0
            for item in moods or []:
                key = str(item.get("key") or "").strip()
                content = str(item.get("content") or "").strip()
                if not key or not content or is_crisis_text(content):
                    continue
                age = mood_entry_age_seconds(item, dt)
                if age is None or age < min_age or age > max_age:
                    continue
                mentioned = _same_day(self.state.mood_last.get(key), dt)
                mark = "今天已经提过" if mentioned else "今天还没提过"
                text = f"{content}。{mark}"
                if _muted_until(self.state.mood_mute.get(key), dt):
                    text += "。老师说过先别提"
                facts.append(SituationFact(kind=MOOD_FOLLOWUP_KIND, text=text, key=key))
        after_sec = float(getattr(self.idle_cfg, "after_sec", 0) or 0)
        elapsed = quiet_sec
        if elapsed is None:
            last_user = _parse_iso(self.state.last_user_at)
            if last_user is not None:
                elapsed = (dt - last_user).total_seconds()
        if elapsed is not None and after_sec > 0 and elapsed >= after_sec:
            count = max(0, int(speak_count))
            facts.append(
                SituationFact(
                    kind="idle",
                    text=f"老师已经安静很久。今天阿洛娜已经因为自己的想法开口{count}次",
                )
            )
        if (
            (last_user_act or "") == "depart"
            and elapsed is not None
            and after_sec > 0
            and elapsed < after_sec
        ):
            facts.append(SituationFact(kind="thought", text="老师刚刚道别"))
        band = (climate or "").strip()
        if band:
            facts.append(SituationFact(kind="thought", text=f"当前气候是{band}"))
        return facts

    def pick_motive(
        self,
        now: datetime | None = None,
        *,
        last_user_act: str = "other",
        climate: str | None = None,
        goals: list[dict[str, object]] | None = None,
        moods: list[dict[str, object]] | None = None,
        birthday_content: str = "",
    ) -> Motive | None:
        dt = now or datetime.now()
        self.state.roll_day(dt)

        if last_user_act != "depart":
            hit = self.pending_festival(dt, birthday_content=birthday_content)
            if hit is not None:
                extra = (hit.extra_memory,) if hit.extra_memory else ()
                return Motive(
                    kind="festival",
                    instruction=build_festival_instruction(hit, climate),
                    history_marker=HISTORY_FESTIVAL_MARKER,
                    festival_id=hit.id,
                    extra_memories=extra,
                )

        if getattr(self.care_cfg, "enabled", True):
            after_sec = float(getattr(self.idle_cfg, "after_sec", 0) or 0)
            last_proactive_at = _parse_iso(self.state.last_proactive_at)
            for kind, start, end in care_window_specs(self.care_cfg):
                reason = care_skip_reason(
                    kind,
                    dt,
                    done_today=self.state.care_done,
                    start=start,
                    end=end,
                    last_proactive_at=last_proactive_at,
                    after_sec=after_sec,
                )
                if reason is None:
                    return Motive(
                        kind=kind,
                        instruction=build_care_instruction(kind, climate),
                        history_marker=HISTORY_CARE_MARKER,
                        retrieve_memory=True,
                        memory_query=CARE_MEMORY_QUERY,
                    )
                if reason.startswith("after_welcome"):
                    return None

        if getattr(self.goal_cfg, "enabled", True):
            horizon = float(
                getattr(self.goal_cfg, "important_horizon_hours", 36) or 36
            )
            important_cd = float(
                getattr(self.goal_cfg, "important_cooldown_sec", 1800) or 1800
            )
            due_soon_sec = float(
                getattr(self.goal_cfg, "due_soon_sec", 3600) or 0
            )
            care_enabled = bool(getattr(self.care_cfg, "enabled", True))
            goals_list = goals or []
            has_important = has_important_goal(
                goals_list,
                dt,
                goal_mute=self.state.goal_mute,
                horizon_hours=horizon,
                goal_acked=self.state.goal_acked,
                due_soon_sec=due_soon_sec,
                care_enabled=care_enabled,
            )
            if can_attempt_goal(
                dt,
                last_user_at=_parse_iso(self.state.last_user_at),
                last_user_act=last_user_act,
                goal_count=self.state.goal_count,
                min_after_user_sec=float(self.goal_cfg.min_after_user_sec),
                max_per_day=int(self.goal_cfg.max_per_day),
                has_important=has_important,
                last_goal_at=last_any_goal_at(self.state.goal_last),
                min_gap_sec=important_cd,
            ):
                selected = select_goal(
                    goals_list,
                    dt,
                    goal_last=self.state.goal_last,
                    goal_mute=self.state.goal_mute,
                    cooldown_sec=float(self.goal_cfg.cooldown_sec),
                    important_horizon_hours=horizon,
                    important_cooldown_sec=important_cd,
                    goal_count=self.state.goal_count,
                    max_per_day=int(self.goal_cfg.max_per_day),
                    goal_acked=self.state.goal_acked,
                    due_soon_sec=due_soon_sec,
                    care_enabled=care_enabled,
                )
                if selected is not None:
                    key = str(selected.get("key") or "").strip()
                    content = str(selected.get("content") or "").strip()
                    if key and content:
                        due_soon = goal_is_due_soon(
                            content,
                            dt,
                            due_soon_sec=due_soon_sec,
                            care_enabled=care_enabled,
                        )
                        return Motive(
                            kind="goal",
                            instruction=build_goal_instruction(
                                content, climate, due_soon=due_soon
                            ),
                            history_marker=HISTORY_GOAL_MARKER,
                            goal_key=key,
                            extra_memories=(content,),
                            due_soon=due_soon,
                        )

        if getattr(self.mood_cfg, "enabled", True) and can_attempt_mood(
            dt,
            enabled=True,
            last_user_at=_parse_iso(self.state.last_user_at),
            last_user_act=last_user_act,
            climate=climate,
            mood_count=self.state.mood_count,
            min_after_user_sec=float(self.mood_cfg.min_after_user_sec),
            max_per_day=int(self.mood_cfg.max_per_day),
        ):
            selected_mood = select_mood_entry(
                moods or [],
                dt,
                mood_last=self.state.mood_last,
                mood_mute=self.state.mood_mute,
                mood_acked=self.state.mood_acked,
                min_age_sec=float(self.mood_cfg.min_age_sec),
                max_age_hours=float(self.mood_cfg.max_age_hours),
                cooldown_sec=float(self.mood_cfg.cooldown_sec),
            )
            if selected_mood is not None:
                key = str(selected_mood.get("key") or "").strip()
                content = str(selected_mood.get("content") or "").strip()
                if key and content:
                    return Motive(
                        kind=MOOD_FOLLOWUP_KIND,  # type: ignore[arg-type]
                        instruction=build_mood_instruction(content, climate),
                        history_marker=HISTORY_MOOD_MARKER,
                        mood_key=key,
                        extra_memories=(content,),
                    )

        if getattr(self.idle_cfg, "enabled", True) and should_fire_idle(
            dt,
            last_user_at=_parse_iso(self.state.last_user_at),
            last_proactive_at=_parse_iso(self.state.last_proactive_at),
            last_idle_at=_parse_iso(self.state.last_idle_at),
            idle_count=self.state.idle_count,
            last_user_act=last_user_act,
            after_sec=float(self.idle_cfg.after_sec),
            cooldown_sec=float(self.idle_cfg.cooldown_sec),
            max_per_day=int(self.idle_cfg.max_per_day),
        ):
            return Motive(
                kind="idle",
                instruction=build_idle_instruction(climate),
                history_marker=HISTORY_IDLE_MARKER,
            )
        return None

    def care_block_reason(self, now: datetime | None = None) -> str | None:
        """Skip reason when a care window is waiting after_sec."""
        if not getattr(self.care_cfg, "enabled", True):
            return None
        dt = now or datetime.now()
        self.state.roll_day(dt)
        after_sec = float(getattr(self.idle_cfg, "after_sec", 0) or 0)
        last_proactive_at = _parse_iso(self.state.last_proactive_at)
        for kind, start, end in care_window_specs(self.care_cfg):
            reason = care_skip_reason(
                kind,
                dt,
                done_today=self.state.care_done,
                start=start,
                end=end,
                last_proactive_at=last_proactive_at,
                after_sec=after_sec,
            )
            if reason is not None and reason.startswith("after_welcome"):
                return f"{kind} {reason}"
        return None

    def idle_block_reason(
        self,
        now: datetime | None = None,
        *,
        last_user_act: str = "other",
    ) -> str | None:
        """Skip reason when user after_sec is already met but idle still cannot fire."""
        if not getattr(self.idle_cfg, "enabled", True):
            return None
        dt = now or datetime.now()
        self.state.roll_day(dt)
        after_sec = float(self.idle_cfg.after_sec)
        last_user_at = _parse_iso(self.state.last_user_at)
        elapsed_user = None if last_user_at is None else (dt - last_user_at).total_seconds()
        if elapsed_user is None or elapsed_user < after_sec:
            return None
        reason = idle_skip_reason(
            dt,
            last_user_at=last_user_at,
            last_proactive_at=_parse_iso(self.state.last_proactive_at),
            last_idle_at=_parse_iso(self.state.last_idle_at),
            idle_count=self.state.idle_count,
            last_user_act=last_user_act,
            after_sec=after_sec,
            cooldown_sec=float(self.idle_cfg.cooldown_sec),
            max_per_day=int(self.idle_cfg.max_per_day),
        )
        if reason is None or reason.startswith("after_user"):
            return None
        return reason
