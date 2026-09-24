"""Unit tests for idle / care motives and scheduler (no GGUF).

Run from backend/:
  python scripts/test_proactive_unit.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import CareConfig, load_config  # noqa: E402
from app.memory.store import MemoryStore  # noqa: E402
from app.planner.schema import parse_and_gate_intent  # noqa: E402
from app.proactive.care import (  # noqa: E402
    HISTORY_CARE_MARKER,
    build_care_instruction,
    care_planner_declined,
    in_window,
    should_fire_care,
)
from app.proactive.festival import (  # noqa: E402
    HISTORY_FESTIVAL_MARKER,
    match_festival,
    needs_rest_followup,
    parse_birthday_md,
)
from app.proactive.goal import (  # noqa: E402
    HISTORY_GOAL_MARKER,
    build_goal_instruction,
    can_attempt_goal,
    goal_defers_to_care,
    goal_is_due_soon,
    has_important_goal,
    history_follows_proactive_marker,
    last_any_goal_at,
    select_goal,
    wants_goal_mute,
)
from app.proactive.hub import ConnectionHub  # noqa: E402
from app.proactive.idle import (  # noqa: E402
    HISTORY_IDLE_MARKER,
    build_idle_instruction,
    should_fire_idle,
)
from app.proactive.mood import (  # noqa: E402
    HISTORY_MOOD_MARKER,
    build_mood_instruction,
    can_attempt_mood,
    mood_entry_skip_reason,
    select_mood_entry,
    wants_topic_mute,
)
from app.proactive.scheduler import ProactiveScheduler  # noqa: E402
from app.taxonomy import MOOD_FOLLOWUP_KIND  # noqa: E402
from app.relationship.events import ARONA_DELTAS  # noqa: E402
from app.relationship.policy import decide_proactive, map_arona_act  # noqa: E402
from app.relationship.state import RelationshipState  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def _idle_kwargs(**overrides: object) -> dict[str, object]:
    now = datetime(2026, 8, 13, 15, 0, 0)
    base: dict[str, object] = {
        "last_user_at": now - timedelta(seconds=1000),
        "last_proactive_at": now - timedelta(seconds=2000),
        "last_idle_at": None,
        "idle_count": 0,
        "last_user_act": "other",
        "after_sec": 900,
        "cooldown_sec": 1800,
        "max_per_day": 3,
    }
    base.update(overrides)
    return base


def _care_cfg(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "enabled": True,
        "breakfast_start": "06:30",
        "breakfast_end": "08:00",
        "lunch_start": "11:30",
        "lunch_end": "13:00",
        "dinner_start": "17:30",
        "dinner_end": "19:00",
        "sleep_start": "23:00",
        "sleep_end": "23:20",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_idle_fire_rules() -> None:
    print("== idle fire / cooldown / rest / depart ==")
    now = datetime(2026, 8, 13, 15, 0, 0)
    if not should_fire_idle(now, **_idle_kwargs()):  # type: ignore[arg-type]
        _fail("expected idle to fire after quiet afternoon")
    if should_fire_idle(now, **_idle_kwargs(last_user_at=None)):  # type: ignore[arg-type]
        _fail("no last_user_at should not idle")
    if should_fire_idle(now, **_idle_kwargs(last_user_at=now - timedelta(seconds=100))):  # type: ignore[arg-type]
        _fail("too soon after user should not idle")
    if should_fire_idle(
        now, **_idle_kwargs(last_proactive_at=now - timedelta(seconds=60))
    ):  # type: ignore[arg-type]
        _fail("welcome gap (after_sec) should block idle")
    if should_fire_idle(
        now, **_idle_kwargs(last_idle_at=now - timedelta(seconds=60))
    ):  # type: ignore[arg-type]
        _fail("idle-to-idle cooldown should block")
    if should_fire_idle(now, **_idle_kwargs(idle_count=3)):  # type: ignore[arg-type]
        _fail("daily cap should block idle")
    if should_fire_idle(now, **_idle_kwargs(last_user_act="depart")):  # type: ignore[arg-type]
        _fail("depart should block idle")
    night = datetime(2026, 8, 13, 23, 10, 0)
    if should_fire_idle(night, **_idle_kwargs()):  # type: ignore[arg-type]
        _fail("rest slot should not idle")
    late = datetime(2026, 8, 13, 2, 0, 0)
    if should_fire_idle(
        late,
        **_idle_kwargs(  # type: ignore[arg-type]
            last_user_at=late - timedelta(seconds=1000),
            last_proactive_at=late - timedelta(seconds=2000),
        ),
    ):
        _fail("late_night should not idle")
    text = build_idle_instruction()
    if "还在不在" not in text or HISTORY_IDLE_MARKER != "【搭话】":
        _fail("idle instruction missing presence ban")
    print("  ok")


def test_care_window_once_per_day() -> None:
    print("== care window / daily once ==")
    breakfast = datetime(2026, 8, 13, 7, 40, 0)
    if not in_window(breakfast, "06:30", "08:00"):
        _fail("07:40 should be in breakfast window")
    if not should_fire_care(
        "breakfast", breakfast, done_today=[], start="06:30", end="08:00"
    ):
        _fail("breakfast should fire in window")
    if should_fire_care(
        "breakfast",
        breakfast,
        done_today=["breakfast"],
        start="06:30",
        end="08:00",
    ):
        _fail("breakfast already done today")
    lunch = datetime(2026, 8, 13, 12, 10, 0)
    if not in_window(lunch, "11:30", "13:00"):
        _fail("12:10 should be in lunch window")
    if in_window(datetime(2026, 8, 13, 13, 0, 0), "11:30", "13:00"):
        _fail("13:00 should be exclusive end")
    if not should_fire_care(
        "lunch", lunch, done_today=[], start="11:30", end="13:00"
    ):
        _fail("lunch should fire in window")
    if should_fire_care(
        "lunch", lunch, done_today=["lunch"], start="11:30", end="13:00"
    ):
        _fail("lunch already done today")
    dinner = datetime(2026, 8, 13, 18, 10, 0)
    if not in_window(dinner, "17:30", "19:00"):
        _fail("18:10 should be in dinner window")
    if not should_fire_care(
        "dinner", dinner, done_today=[], start="17:30", end="19:00"
    ):
        _fail("dinner should fire in window")
    if should_fire_care(
        "dinner", dinner, done_today=["dinner"], start="17:30", end="19:00"
    ):
        _fail("dinner already done today")
    sleep = datetime(2026, 8, 13, 23, 5, 0)
    if not should_fire_care(
        "sleep", sleep, done_today=[], start="23:00", end="23:20"
    ):
        _fail("sleep should fire in window")
    if should_fire_care(
        "sleep", datetime(2026, 8, 13, 15, 0, 0), done_today=[], start="23:00", end="23:20"
    ):
        _fail("afternoon is not sleep window")
    if should_fire_care(
        "lunch",
        lunch,
        done_today=[],
        start="11:30",
        end="13:00",
        last_proactive_at=lunch - timedelta(seconds=60),
        after_sec=900,
    ):
        _fail("welcome gap (after_sec) should block lunch")
    if should_fire_care(
        "breakfast",
        breakfast,
        done_today=[],
        start="06:30",
        end="08:00",
        last_proactive_at=breakfast - timedelta(seconds=60),
        after_sec=900,
    ):
        _fail("welcome gap (after_sec) should block breakfast")
    if should_fire_care(
        "dinner",
        dinner,
        done_today=[],
        start="17:30",
        end="19:00",
        last_proactive_at=dinner - timedelta(seconds=60),
        after_sec=900,
    ):
        _fail("welcome gap (after_sec) should block dinner")
    if not should_fire_care(
        "lunch",
        lunch,
        done_today=[],
        start="11:30",
        end="13:00",
        last_proactive_at=lunch - timedelta(seconds=1000),
        after_sec=900,
    ):
        _fail("lunch should fire after after_sec")
    if not should_fire_care(
        "lunch",
        lunch,
        done_today=[],
        start="11:30",
        end="13:00",
        last_proactive_at=None,
        after_sec=900,
    ):
        _fail("no last_proactive_at should still fire lunch")
    text = build_care_instruction("lunch", climate="cling_risk")
    if "更短" not in text or HISTORY_CARE_MARKER != "【提醒】":
        _fail("cling care should be shorter")
    breakfast_text = build_care_instruction("breakfast")
    if "已吃早饭" not in breakfast_text or "reply_ok 必须 false" not in breakfast_text:
        _fail("breakfast instruction should gate on already-addressed meal")
    if "正在聊" not in breakfast_text or "还在想" not in breakfast_text:
        _fail("breakfast instruction should ban citing the current topic")
    lunch_text = build_care_instruction("lunch")
    if "已吃午饭" not in lunch_text or "reply_ok 必须 false" not in lunch_text:
        _fail("lunch instruction should gate on already-addressed meal")
    if "正在聊" not in lunch_text or "还在想" not in lunch_text:
        _fail("lunch instruction should ban citing the current topic")
    dinner_text = build_care_instruction("dinner")
    if "已吃晚饭" not in dinner_text or "reply_ok 必须 false" not in dinner_text:
        _fail("dinner instruction should gate on already-addressed meal")
    if "正在聊" not in dinner_text or "还在想" not in dinner_text:
        _fail("dinner instruction should ban citing the current topic")
    sleep_text = build_care_instruction("sleep")
    if "待会再睡" not in sleep_text or "晚安收束" not in sleep_text:
        _fail("sleep instruction should gate on already-addressed rest")
    if "正在聊" not in sleep_text or "还在想" not in sleep_text:
        _fail("sleep instruction should ban citing the current topic")
    print("  ok")


def test_care_planner_declined() -> None:
    print("== care planner declined is care kinds reply_ok=false only ==")
    if not care_planner_declined("breakfast", reply_ok=False):
        _fail("breakfast reply_ok=false should decline")
    if not care_planner_declined("lunch", reply_ok=False):
        _fail("lunch reply_ok=false should decline")
    if not care_planner_declined("dinner", reply_ok=False):
        _fail("dinner reply_ok=false should decline")
    if not care_planner_declined("sleep", reply_ok=False):
        _fail("sleep reply_ok=false should decline")
    if care_planner_declined("breakfast", reply_ok=True):
        _fail("breakfast reply_ok=true should not decline")
    if care_planner_declined("lunch", reply_ok=True):
        _fail("lunch reply_ok=true should not decline")
    if care_planner_declined("dinner", reply_ok=True):
        _fail("dinner reply_ok=true should not decline")
    if care_planner_declined("idle", reply_ok=False):
        _fail("idle must not use care decline")
    if care_planner_declined("welcome", reply_ok=False):
        _fail("welcome must not use care decline")
    if care_planner_declined("festival", reply_ok=False):
        _fail("festival must not use care decline")
    if care_planner_declined("mood_followup", reply_ok=False):
        _fail("mood_followup must not use care decline")
    print("  ok")


def test_decide_proactive_policy() -> None:
    print("== cling_risk vetoes idle, allows short care ==")
    cling = RelationshipState(trust=0.5, dependence=0.70, tension=0.15)
    idle = decide_proactive(cling, "idle")
    if idle.action != "silence" or idle.climate != "cling_risk":
        _fail(f"cling idle should silence, got {idle.action} {idle.climate}")
    care = decide_proactive(cling, "lunch")
    if care.action != "initiate":
        _fail(f"cling care should still initiate, got {care.action}")
    if "索取确认" not in care.stance:
        _fail(f"cling care stance should be short: {care.stance}")

    play = RelationshipState(trust=0.6, dependence=0.30, tension=0.30)
    ok = decide_proactive(play, "idle")
    if ok.action != "initiate" or ok.climate != "secure_play":
        _fail(f"secure_play idle should initiate, got {ok.action} {ok.climate}")

    tool = RelationshipState(trust=0.10, dependence=0.10, tension=0.10)
    blocked = decide_proactive(tool, "idle")
    if blocked.action != "silence":
        _fail("cold_tool should not idle")

    if map_arona_act("initiate", "secure_play") != "greeted":
        _fail("welcome initiate stays greeted")
    if map_arona_act("initiate", "secure_play", motive_kind="idle") != "checked_in":
        _fail("idle initiate should be checked_in")
    if map_arona_act("initiate", "secure_play", motive_kind="lunch") != "cared":
        _fail("care initiate should be cared")
    if map_arona_act("initiate", "secure_play", motive_kind="breakfast") != "cared":
        _fail("breakfast initiate should be cared")
    if map_arona_act("initiate", "secure_play", motive_kind="dinner") != "cared":
        _fail("dinner initiate should be cared")
    goal_ok = decide_proactive(play, "goal")
    if goal_ok.action != "initiate":
        _fail(f"secure_play goal should initiate, got {goal_ok.action}")
    goal_cling = decide_proactive(cling, "goal")
    if goal_cling.action != "silence":
        _fail(f"cling goal should silence, got {goal_cling.action}")
    if map_arona_act("initiate", "secure_play", motive_kind="goal") != "checked_in":
        _fail("goal initiate should be checked_in")
    mood_ok = decide_proactive(play, "mood_followup")
    if mood_ok.action != "initiate":
        _fail(f"secure_play mood_followup should initiate, got {mood_ok.action}")
    if "不当病历" not in mood_ok.stance:
        _fail(f"mood stance missing 病历 ban: {mood_ok.stance}")
    mood_cling = decide_proactive(cling, "mood_followup")
    if mood_cling.action != "silence":
        _fail(f"cling mood_followup should silence, got {mood_cling.action}")
    frag = RelationshipState(trust=0.2, dependence=0.2, tension=0.7)
    if decide_proactive(frag, "mood_followup").action != "silence":
        _fail("fragile mood_followup should silence")
    if map_arona_act("initiate", "secure_play", motive_kind="mood_followup") != "checked_in":
        _fail("mood_followup initiate should be checked_in")
    fest = decide_proactive(cling, "festival")
    if fest.action != "initiate":
        _fail(f"cling festival should still initiate, got {fest.action}")
    if map_arona_act("initiate", "secure_play", motive_kind="festival") != "greeted":
        _fail("festival initiate should be greeted")
    if ARONA_DELTAS["checked_in"][1] != 0.0:
        _fail("checked_in must not raise dependence")
    if ARONA_DELTAS["cared"][1] != 0.0:
        _fail("cared must not raise dependence")
    print("  ok")


def test_scheduler_persist_and_priority(tmp: Path) -> None:
    print("== scheduler persist / care over idle ==")
    idle_cfg = SimpleNamespace(
        enabled=True, after_sec=900, cooldown_sec=1800, max_per_day=3
    )
    care_cfg = _care_cfg()
    path = tmp / "proactive.json"
    sched = ProactiveScheduler(path, idle_cfg=idle_cfg, care_cfg=care_cfg)
    morning = datetime(2026, 8, 13, 7, 40, 0)
    sched.note_user_activity(morning - timedelta(seconds=2000))
    sched.note_proactive(morning - timedelta(seconds=2000))
    breakfast = sched.pick_motive(
        morning,
        last_user_act="other",
        climate="secure_play",
        goals=_sample_goals(),
    )
    if breakfast is None or breakfast.kind != "breakfast":
        _fail(f"expected breakfast over goal/idle, got {breakfast}")
    sched.mark_fired("breakfast", morning)

    noon = datetime(2026, 8, 13, 12, 10, 0)
    sched.note_user_activity(noon - timedelta(seconds=2000))
    sched.note_proactive(noon - timedelta(seconds=2000))
    picked = sched.pick_motive(
        noon,
        last_user_act="other",
        climate="secure_play",
        goals=_sample_goals(),
    )
    if picked is None or picked.kind != "lunch":
        _fail(f"expected lunch over goal/idle, got {picked}")
    sched.mark_fired("lunch", noon)
    again = sched.pick_motive(noon, last_user_act="other")
    if again is not None and again.kind == "lunch":
        _fail("lunch should not fire twice the same day")

    loaded = ProactiveScheduler(path, idle_cfg=idle_cfg, care_cfg=care_cfg)
    if "breakfast" not in loaded.state.care_done:
        _fail("breakfast care_done should persist")
    if "lunch" not in loaded.state.care_done:
        _fail("care_done should persist")

    afternoon = datetime(2026, 8, 13, 15, 0, 0)
    idle = loaded.pick_motive(afternoon, last_user_act="other")
    if idle is None or idle.kind != "idle":
        _fail(f"expected idle in afternoon, got {idle}")
    loaded.mark_fired("idle", afternoon)
    if loaded.state.idle_count != 1:
        _fail(f"idle_count {loaded.state.idle_count}")
    if not loaded.state.last_idle_at:
        _fail("last_idle_at should be set after idle")
    print("  ok")


def test_welcome_does_not_eat_idle_cooldown(tmp: Path) -> None:
    print("== welcome after_sec ok; idle cooldown still holds ==")
    idle_cfg = SimpleNamespace(
        enabled=True, after_sec=30, cooldown_sec=1800, max_per_day=10
    )
    care_cfg = _care_cfg()
    path = tmp / "proactive_welcome_idle.json"
    sched = ProactiveScheduler(path, idle_cfg=idle_cfg, care_cfg=care_cfg)
    now = datetime(2026, 8, 13, 15, 10, 0)
    welcome_at = now - timedelta(seconds=240)
    user_at = now - timedelta(seconds=40)
    sched.note_user_activity(user_at)
    sched.note_proactive(welcome_at)
    picked = sched.pick_motive(now, last_user_act="other")
    if picked is None or picked.kind != "idle":
        _fail(f"welcome 4min ago + after_sec=30 should idle, got {picked}")

    sched.mark_fired("idle", now)
    soon = now + timedelta(seconds=60)
    blocked = sched.pick_motive(soon, last_user_act="other")
    if blocked is not None and blocked.kind == "idle":
        _fail("second idle should wait cooldown_sec")
    reason = sched.idle_block_reason(soon, last_user_act="other")
    if reason is None or "idle_cooldown" not in reason:
        _fail(f"expected idle_cooldown reason, got {reason}")
    print("  ok")


def test_care_waits_after_welcome(tmp: Path) -> None:
    print("== care waits idle.after_sec after welcome; no goal fallthrough ==")
    idle_cfg = SimpleNamespace(
        enabled=True, after_sec=900, cooldown_sec=1800, max_per_day=3
    )
    care_cfg = _care_cfg()
    sched = ProactiveScheduler(
        tmp / "proactive_care_welcome.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        goal_cfg=_goal_cfg(),
    )
    noon = datetime(2026, 8, 13, 12, 10, 0)
    sched.note_user_activity(noon - timedelta(seconds=2000))
    sched.note_proactive(noon - timedelta(seconds=60))
    waiting = sched.pick_motive(
        noon,
        last_user_act="other",
        climate="secure_play",
        goals=_sample_goals(),
    )
    if waiting is not None:
        _fail(f"care in window should wait after_sec, not fall through, got {waiting}")
    reason = sched.care_block_reason(noon)
    if reason is None or "after_welcome" not in reason:
        _fail(f"expected after_welcome care skip, got {reason}")

    ready = noon + timedelta(seconds=840)
    picked = sched.pick_motive(
        ready,
        last_user_act="other",
        climate="secure_play",
        goals=_sample_goals(),
    )
    if picked is None or picked.kind != "lunch":
        _fail(f"lunch should fire after after_sec, got {picked}")

    breakfast_at = datetime(2026, 8, 13, 7, 40, 0)
    breakfast_sched = ProactiveScheduler(
        tmp / "proactive_care_breakfast.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
    )
    breakfast_sched.note_proactive(breakfast_at - timedelta(seconds=60))
    blocked_breakfast = breakfast_sched.pick_motive(
        breakfast_at, last_user_act="other"
    )
    if blocked_breakfast is not None:
        _fail(
            f"breakfast should wait after_sec after welcome, got {blocked_breakfast}"
        )
    breakfast_ready = breakfast_sched.pick_motive(
        breakfast_at + timedelta(seconds=840),
        last_user_act="other",
    )
    if breakfast_ready is None or breakfast_ready.kind != "breakfast":
        _fail(f"breakfast should fire after after_sec, got {breakfast_ready}")

    dinner_at = datetime(2026, 8, 13, 18, 10, 0)
    dinner_sched = ProactiveScheduler(
        tmp / "proactive_care_dinner.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
    )
    dinner_sched.note_proactive(dinner_at - timedelta(seconds=60))
    blocked_dinner = dinner_sched.pick_motive(dinner_at, last_user_act="other")
    if blocked_dinner is not None:
        _fail(f"dinner should wait after_sec after welcome, got {blocked_dinner}")
    dinner_ready = dinner_sched.pick_motive(
        dinner_at + timedelta(seconds=840),
        last_user_act="other",
    )
    if dinner_ready is None or dinner_ready.kind != "dinner":
        _fail(f"dinner should fire after after_sec, got {dinner_ready}")

    night = datetime(2026, 8, 13, 23, 5, 0)
    night_sched = ProactiveScheduler(
        tmp / "proactive_care_sleep.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
    )
    night_sched.note_proactive(night - timedelta(seconds=60))
    blocked_sleep = night_sched.pick_motive(night, last_user_act="other")
    if blocked_sleep is not None:
        _fail(f"sleep should wait after_sec after welcome, got {blocked_sleep}")
    sleep_ready = night_sched.pick_motive(
        night + timedelta(seconds=840),
        last_user_act="other",
    )
    if sleep_ready is None or sleep_ready.kind != "sleep":
        _fail(f"sleep should fire after after_sec, got {sleep_ready}")
    print("  ok")


def test_mark_care_addressed_skips_without_proactive_stamp(tmp: Path) -> None:
    print("== mark_care_addressed skips lunch; last_proactive_at unchanged ==")
    idle_cfg = SimpleNamespace(
        enabled=True, after_sec=900, cooldown_sec=1800, max_per_day=3
    )
    care_cfg = _care_cfg()
    sched = ProactiveScheduler(
        tmp / "proactive_care_addressed.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
    )
    noon = datetime(2026, 8, 13, 12, 10, 0)
    sched.note_user_activity(noon - timedelta(seconds=2000))
    sched.note_proactive(noon - timedelta(seconds=2000))
    before = sched.state.last_proactive_at
    sched.mark_care_addressed("lunch", noon)
    if "lunch" not in sched.state.care_done:
        _fail("lunch should be in care_done after addressed")
    if sched.state.last_proactive_at != before:
        _fail("last_proactive_at must not change when care is only addressed")
    picked = sched.pick_motive(noon, last_user_act="other")
    if picked is not None and picked.kind == "lunch":
        _fail(f"addressed lunch should not be picked, got {picked}")

    evening = datetime(2026, 8, 13, 18, 10, 0)
    dinner_sched = ProactiveScheduler(
        tmp / "proactive_care_addressed_dinner.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
    )
    dinner_sched.note_user_activity(evening - timedelta(seconds=2000))
    dinner_sched.note_proactive(evening - timedelta(seconds=2000))
    dinner_before = dinner_sched.state.last_proactive_at
    dinner_sched.mark_care_addressed("dinner", evening)
    if "dinner" not in dinner_sched.state.care_done:
        _fail("dinner should be in care_done after addressed")
    if dinner_sched.state.last_proactive_at != dinner_before:
        _fail("last_proactive_at must not change when dinner is only addressed")
    dinner_picked = dinner_sched.pick_motive(evening, last_user_act="other")
    if dinner_picked is not None and dinner_picked.kind == "dinner":
        _fail(f"addressed dinner should not be picked, got {dinner_picked}")
    print("  ok")


def test_hub_busy() -> None:
    print("== hub busy filter; listening stays idle ==")
    hub = ConnectionHub()

    async def _send(_payload: dict) -> None:
        return None

    hub.register("a", _send)
    hub.register("b", _send)
    hub.set_busy("a", True)
    idle = hub.idle_sessions()
    if len(idle) != 1 or idle[0][0] != "b":
        _fail(f"expected only b idle, got {idle}")
    hub.set_listening("b", True)
    idle = hub.idle_sessions()
    if len(idle) != 1 or idle[0][0] != "b":
        _fail(f"listening must not freeze idle_sessions, got {idle}")
    hub.unregister("b")
    if hub.idle_sessions():
        _fail("no idle sessions after unregister")
    print("  ok")


def test_tick_once_enqueues_care_without_initiate() -> None:
    print("== proactive tick enqueues care impulse and does not initiate on simmer ==")
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.life import LifeEngine, LifeSettings
    from app.proactive.care import CARE_MEMORY_QUERY, HISTORY_CARE_MARKER
    from app.proactive.loop import tick_once as proactive_tick
    from app.proactive.scheduler import Motive

    with tempfile.TemporaryDirectory() as tmp:
        engine = LifeEngine.from_path(Path(tmp) / "life.json", LifeSettings())
        hub = ConnectionHub()

        async def _send(_payload: dict) -> None:
            return None

        hub.register("s1", _send)
        hub.set_listening("s1", True)
        orch = MagicMock()
        orch.relationship = None
        orch.handle_initiate = AsyncMock(
            side_effect=AssertionError("must not initiate during simmer")
        )
        orch.memory_store.list_by_category.return_value = []
        scheduler = MagicMock()
        scheduler.goal_cfg.enabled = False
        scheduler.mood_cfg.enabled = False
        scheduler.festival_cfg.enabled = False
        scheduler.pick_motive.return_value = Motive(
            kind="lunch",
            instruction="【系统事件】午饭",
            history_marker=HISTORY_CARE_MARKER,
            retrieve_memory=True,
            memory_query=CARE_MEMORY_QUERY,
        )
        fake = SimpleNamespace(
            hub=hub,
            life=engine,
            orchestrator=orch,
            scheduler=scheduler,
            config=SimpleNamespace(
                proactive=SimpleNamespace(
                    relationship=SimpleNamespace(enabled=False)
                )
            ),
        )
        now = datetime(2026, 8, 13, 12, 0, 0)
        spoke = asyncio.run(proactive_tick(fake, now=now))
        if spoke:
            _fail("a meal window must not speak by itself")
        if engine.state.pending_impulse is not None:
            _fail("a meal window must not enqueue an impulse")
        orch.handle_initiate.assert_not_called()
        scheduler.pick_motive.assert_not_called()
    print("  ok")


def test_welcome_impulse_flush_speaks() -> None:
    print("== welcome impulse flush sends via handle_initiate ==")
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.life import Impulse, LifeEngine, LifeSettings, offer_impulse
    from app.life.impulse import flush_impulse

    with tempfile.TemporaryDirectory() as tmp:
        engine = LifeEngine.from_path(Path(tmp) / "life.json", LifeSettings())
        hub = ConnectionHub()

        async def _send(_payload: dict) -> None:
            return None

        hub.register("s1", _send)
        orch = MagicMock()
        orch.relationship = None
        orch.handle_initiate = AsyncMock(return_value="sent")
        scheduler = MagicMock()
        now = datetime(2026, 8, 13, 15, 0, 0)
        offer_impulse(
            engine,
            Impulse(
                kind="welcome",
                created_at=now,
                instruction="【系统事件】老师上线了",
                history_marker="【上线】",
                allow_speak=True,
                first_in_slot=True,
                slot_id="afternoon",
                date_key="2026-08-13",
            ),
        )
        fake = SimpleNamespace(
            hub=hub,
            life=engine,
            orchestrator=orch,
            scheduler=scheduler,
            welcome=MagicMock(),
            config=SimpleNamespace(
                proactive=SimpleNamespace(
                    relationship=SimpleNamespace(enabled=False)
                )
            ),
        )
        spoke = asyncio.run(flush_impulse(fake, now=now))
        if not spoke:
            _fail("welcome should speak")
        orch.handle_initiate.assert_called_once()
        kwargs = orch.handle_initiate.await_args.kwargs
        if kwargs.get("kind") != "welcome":
            _fail(kwargs.get("kind"))
        if engine.state.pending_impulse is not None:
            _fail("spoken welcome should clear impulse")
        scheduler.note_proactive.assert_called()
        fake.welcome.mark_period_greeted.assert_called_with(
            "2026-08-13", "afternoon"
        )
    print("  ok")


def test_climate_withhold_care_does_not_initiate() -> None:
    print("== climate withhold care is emotion_only and marks addressed ==")
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.life import LifeEngine, LifeSettings
    from app.proactive.care import CARE_MEMORY_QUERY, HISTORY_CARE_MARKER
    from app.proactive.loop import tick_once as proactive_tick
    from app.proactive.scheduler import Motive

    with tempfile.TemporaryDirectory() as tmp:
        engine = LifeEngine.from_path(Path(tmp) / "life.json", LifeSettings())
        hub = ConnectionHub()

        async def _send(_payload: dict) -> None:
            return None

        hub.register("s1", _send)
        rel = MagicMock()
        rel.peek_climate.return_value = "fragile"
        rel.decide_proactive.return_value = SimpleNamespace(
            action="silence", climate="fragile"
        )
        rel.state.last_user_act = "other"
        orch = MagicMock()
        orch.relationship = rel
        orch.handle_initiate = AsyncMock(
            side_effect=AssertionError("climate withhold must not initiate")
        )
        orch.memory_store.list_by_category.return_value = []
        scheduler = MagicMock()
        scheduler.goal_cfg.enabled = False
        scheduler.mood_cfg.enabled = False
        scheduler.festival_cfg.enabled = False
        scheduler.pick_motive.return_value = Motive(
            kind="lunch",
            instruction="【系统事件】午饭",
            history_marker=HISTORY_CARE_MARKER,
            retrieve_memory=True,
            memory_query=CARE_MEMORY_QUERY,
        )
        fake = SimpleNamespace(
            hub=hub,
            life=engine,
            orchestrator=orch,
            scheduler=scheduler,
            config=SimpleNamespace(
                proactive=SimpleNamespace(
                    relationship=SimpleNamespace(enabled=True)
                )
            ),
        )
        now = datetime(2026, 8, 13, 12, 0, 0)
        spoke = asyncio.run(proactive_tick(fake, now=now))
        if spoke:
            _fail("climate must not make the ticker speak")
        orch.handle_initiate.assert_not_called()
        if engine.state.pending_impulse is not None:
            _fail("climate must not enqueue an impulse")
        scheduler.pick_motive.assert_not_called()
        rel.decide_proactive.assert_not_called()
    print("  ok")


def test_generate_fail_does_not_mark_fired() -> None:
    print("== generate failure keeps impulse and does not mark_fired ==")
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.life import Impulse, LifeEngine, LifeSettings, offer_impulse
    from app.life.impulse import flush_impulse

    with tempfile.TemporaryDirectory() as tmp:
        engine = LifeEngine.from_path(Path(tmp) / "life.json", LifeSettings())
        hub = ConnectionHub()

        async def _send(_payload: dict) -> None:
            return None

        hub.register("s1", _send)
        orch = MagicMock()
        orch.relationship = None
        orch.handle_initiate = AsyncMock(return_value="failed")
        scheduler = MagicMock()
        now = datetime(2026, 8, 13, 15, 0, 0)
        offer_impulse(
            engine,
            Impulse(
                kind="idle",
                created_at=now,
                instruction="【系统事件】轻在场",
                history_marker="【搭话】",
                allow_speak=True,
            ),
        )
        fake = SimpleNamespace(
            hub=hub,
            life=engine,
            orchestrator=orch,
            scheduler=scheduler,
            config=SimpleNamespace(
                proactive=SimpleNamespace(
                    relationship=SimpleNamespace(enabled=False)
                )
            ),
        )
        spoke = asyncio.run(flush_impulse(fake, now=now))
        if spoke:
            _fail("failed generate must not count as spoke")
        if engine.state.pending_impulse is None:
            _fail("failed generate must keep the impulse")
        scheduler.mark_fired.assert_not_called()
    print("  ok")


def test_busy_defers_impulse_speak() -> None:
    print("== hub busy defers speak and keeps impulse ==")
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.life import Impulse, LifeEngine, LifeSettings, offer_impulse
    from app.life.impulse import flush_impulse

    with tempfile.TemporaryDirectory() as tmp:
        engine = LifeEngine.from_path(Path(tmp) / "life.json", LifeSettings())
        hub = ConnectionHub()

        async def _send(_payload: dict) -> None:
            return None

        hub.register("s1", _send)
        hub.set_busy("s1", True)
        orch = MagicMock()
        orch.relationship = None
        orch.handle_initiate = AsyncMock(
            side_effect=AssertionError("busy must not initiate")
        )
        scheduler = MagicMock()
        now = datetime(2026, 8, 13, 15, 0, 0)
        offer_impulse(
            engine,
            Impulse(
                kind="welcome",
                created_at=now,
                instruction="【系统事件】老师上线了",
                allow_speak=True,
            ),
        )
        fake = SimpleNamespace(
            hub=hub,
            life=engine,
            orchestrator=orch,
            scheduler=scheduler,
            config=SimpleNamespace(
                proactive=SimpleNamespace(
                    relationship=SimpleNamespace(enabled=False)
                )
            ),
        )
        spoke = asyncio.run(flush_impulse(fake, now=now))
        if spoke:
            _fail("busy must not speak")
        if engine.state.pending_impulse is None:
            _fail("busy must keep the impulse")
        orch.handle_initiate.assert_not_called()
        scheduler.mark_fired.assert_not_called()
    print("  ok")


def test_config_loads() -> None:
    print("== config idle / care / goal / continue ==")
    cfg = load_config()
    if not cfg.proactive.idle.enabled:
        _fail("idle should default enabled")
    if cfg.proactive.idle.after_sec <= 0:
        _fail(f"after_sec {cfg.proactive.idle.after_sec}")
    if "proactive.json" not in cfg.proactive.care.persist_path:
        _fail(f"persist_path {cfg.proactive.care.persist_path}")
    if cfg.proactive.care.lunch_start != "11:30":
        _fail("lunch_start")
    if cfg.proactive.care.breakfast_start != "06:30":
        _fail("breakfast_start")
    if cfg.proactive.care.dinner_start != "17:30":
        _fail("dinner_start")
    defaults = CareConfig()
    if defaults.breakfast_start != "06:30" or defaults.breakfast_end != "08:00":
        _fail("breakfast window defaults")
    if defaults.lunch_start != "11:30" or defaults.lunch_end != "13:00":
        _fail("lunch window defaults")
    if defaults.dinner_start != "17:30" or defaults.dinner_end != "19:00":
        _fail("dinner window defaults")
    if not cfg.proactive.goal.enabled:
        _fail("goal should default enabled")
    if cfg.proactive.goal.min_after_user_sec != 300:
        _fail(f"min_after_user_sec {cfg.proactive.goal.min_after_user_sec}")
    if cfg.proactive.goal.cooldown_sec != 21600:
        _fail(f"goal cooldown {cfg.proactive.goal.cooldown_sec}")
    if cfg.proactive.goal.mute_sec != 604800:
        _fail(f"mute_sec {cfg.proactive.goal.mute_sec}")
    if cfg.proactive.goal.max_per_day != 1:
        _fail(f"goal max_per_day {cfg.proactive.goal.max_per_day}")
    if cfg.proactive.goal.important_horizon_hours != 36:
        _fail(f"horizon {cfg.proactive.goal.important_horizon_hours}")
    if cfg.proactive.goal.important_cooldown_sec != 1800:
        _fail(f"important cooldown {cfg.proactive.goal.important_cooldown_sec}")
    if cfg.proactive.goal.due_soon_sec != 3600:
        _fail(f"due_soon_sec {cfg.proactive.goal.due_soon_sec}")
    if not cfg.proactive.mood_followup.enabled:
        _fail("mood_followup should default enabled")
    if cfg.proactive.mood_followup.min_after_user_sec != 900:
        _fail(f"mood min_after {cfg.proactive.mood_followup.min_after_user_sec}")
    if cfg.proactive.mood_followup.min_age_sec != 7200:
        _fail(f"mood min_age {cfg.proactive.mood_followup.min_age_sec}")
    if cfg.proactive.mood_followup.max_age_hours != 72:
        _fail(f"mood max_age {cfg.proactive.mood_followup.max_age_hours}")
    if cfg.proactive.mood_followup.cooldown_sec != 21600:
        _fail(f"mood cooldown {cfg.proactive.mood_followup.cooldown_sec}")
    if cfg.proactive.mood_followup.max_per_day != 1:
        _fail(f"mood max_per_day {cfg.proactive.mood_followup.max_per_day}")
    if not cfg.proactive.continue_line.enabled:
        _fail("continue should default enabled")
    if cfg.proactive.continue_line.delay_sec != 2:
        _fail(f"delay_sec {cfg.proactive.continue_line.delay_sec}")
    if not cfg.proactive.festival.enabled:
        _fail("festival should default enabled")
    print("  ok")


def _goal_cfg(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "enabled": True,
        "min_after_user_sec": 300,
        "cooldown_sec": 21600,
        "mute_sec": 604800,
        "max_per_day": 1,
        "important_horizon_hours": 36,
        "important_cooldown_sec": 1800,
        "due_soon_sec": 3600,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _sample_goals() -> list[dict[str, object]]:
    return [
        {"key": "old_trip", "content": "老师想去海边", "updated_at": 100.0},
        {"key": "new_exam", "content": "老师要准备考试", "updated_at": 200.0},
    ]


def test_list_by_category() -> None:
    print("== list_by_category ==")
    cfg = load_config()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = MemoryStore(cfg, db_path=Path(tmp) / "memory.db")
        with store._connect() as conn:
            conn.execute(
                "INSERT INTO memories(key, content, category, updated_at, source) "
                "VALUES (?, ?, ?, ?, ?)",
                ("old_trip", "老师想去海边", "goal", 100.0, "test"),
            )
            conn.execute(
                "INSERT INTO memories(key, content, category, updated_at, source) "
                "VALUES (?, ?, ?, ?, ?)",
                ("drink", "老师喜欢草莓牛奶", "preference", 200.0, "test"),
            )
            conn.commit()
        goals = store.list_by_category("goal")
        if len(goals) != 1 or goals[0]["key"] != "old_trip":
            _fail(f"expected one goal, got {goals}")
        prefs = store.list_by_category("preference")
        if len(prefs) != 1 or prefs[0]["key"] != "drink":
            _fail(f"expected preference, got {prefs}")
        if store.list_by_category("missing"):
            _fail("missing category should be empty")
    print("  ok")


def test_goal_fire_rules() -> None:
    print("== goal cooldown / daily / mute / select ==")
    now = datetime(2026, 8, 13, 15, 0, 0)
    if not can_attempt_goal(
        now,
        last_user_at=now - timedelta(seconds=400),
        last_user_act="other",
        goal_count=0,
        min_after_user_sec=300,
        max_per_day=1,
    ):
        _fail("goal should be attemptable after quiet afternoon")
    if can_attempt_goal(
        now,
        last_user_at=now - timedelta(seconds=60),
        last_user_act="other",
        goal_count=0,
        min_after_user_sec=300,
        max_per_day=1,
    ):
        _fail("too soon after user should not goal")
    if can_attempt_goal(
        now,
        last_user_at=now - timedelta(seconds=400),
        last_user_act="other",
        goal_count=1,
        min_after_user_sec=300,
        max_per_day=1,
    ):
        _fail("daily cap should block goal")
    if can_attempt_goal(
        now,
        last_user_at=now - timedelta(seconds=400),
        last_user_act="depart",
        goal_count=0,
        min_after_user_sec=300,
        max_per_day=1,
    ):
        _fail("depart should block goal")
    night = datetime(2026, 8, 13, 23, 10, 0)
    if can_attempt_goal(
        night,
        last_user_at=night - timedelta(seconds=400),
        last_user_act="other",
        goal_count=0,
        min_after_user_sec=300,
        max_per_day=1,
    ):
        _fail("rest slot should not goal")

    picked = select_goal(
        _sample_goals(), now, goal_last={}, goal_mute={}, cooldown_sec=21600
    )
    if picked is None or picked["key"] != "old_trip":
        _fail(f"never-visited should pick oldest updated_at, got {picked}")

    recent = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    picked = select_goal(
        _sample_goals(),
        now,
        goal_last={"old_trip": recent},
        goal_mute={},
        cooldown_sec=21600,
    )
    if picked is None or picked["key"] != "new_exam":
        _fail(f"cooling old_trip should pick new_exam, got {picked}")

    mute_until = (now + timedelta(days=7)).isoformat(timespec="seconds")
    picked = select_goal(
        _sample_goals(),
        now,
        goal_last={},
        goal_mute={"old_trip": mute_until},
        cooldown_sec=21600,
    )
    if picked is None or picked["key"] != "new_exam":
        _fail(f"muted old_trip should pick new_exam, got {picked}")

    cooling = now.isoformat(timespec="seconds")
    if (
        select_goal(
            _sample_goals(),
            now,
            goal_last={"old_trip": cooling, "new_exam": cooling},
            goal_mute={},
            cooldown_sec=21600,
        )
        is not None
    ):
        _fail("both cooling should pick none")
    if HISTORY_GOAL_MARKER != "【回访】":
        _fail("goal history marker")

    quiet = now - timedelta(seconds=400)
    if not can_attempt_goal(
        now,
        last_user_at=quiet,
        last_user_act="other",
        goal_count=0,
        min_after_user_sec=300,
        max_per_day=1,
        has_important=True,
        last_goal_at=now - timedelta(seconds=1800),
        min_gap_sec=1800,
    ):
        _fail("global gap exactly 1800s should allow")
    if can_attempt_goal(
        now,
        last_user_at=quiet,
        last_user_act="other",
        goal_count=0,
        min_after_user_sec=300,
        max_per_day=1,
        has_important=True,
        last_goal_at=now - timedelta(seconds=30),
        min_gap_sec=1800,
    ):
        _fail("global gap should block another goal 30s later")
    latest = last_any_goal_at(
        {
            "old_trip": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
            "ticket": now.isoformat(timespec="seconds"),
        }
    )
    if latest != now:
        _fail(f"last_any_goal_at should pick latest stamp, got {latest}")
    print("  ok")


def test_goal_importance_cooldown() -> None:
    print("== important goal bypasses 6h / daily cap ==")
    now = datetime(2026, 8, 31, 14, 46, 0)
    ticket = {
        "key": "ticket",
        "content": "老师2026年9月1日下午2点要订回深圳的车票",
        "updated_at": 200.0,
    }
    trip = {
        "key": "old_trip",
        "content": "老师想去海边",
        "updated_at": 100.0,
    }
    if not has_important_goal(
        [ticket, trip], now, goal_mute={}, horizon_hours=36
    ):
        _fail("ticket should be important on Aug 31")
    if has_important_goal(
        [trip], now, goal_mute={}, horizon_hours=36
    ):
        _fail("undated trip should not be important")

    if not can_attempt_goal(
        now,
        last_user_at=now - timedelta(seconds=400),
        last_user_act="other",
        goal_count=1,
        min_after_user_sec=300,
        max_per_day=1,
        has_important=True,
    ):
        _fail("important goal should bypass daily cap")

    hour_ago = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    picked = select_goal(
        [trip, ticket],
        now,
        goal_last={"old_trip": hour_ago, "ticket": hour_ago},
        goal_mute={},
        cooldown_sec=21600,
        important_horizon_hours=36,
        important_cooldown_sec=1800,
    )
    if picked is None or picked["key"] != "ticket":
        _fail(f"important ticket should beat 6h cooldown, got {picked}")

    too_soon = (now - timedelta(seconds=600)).isoformat(timespec="seconds")
    if (
        select_goal(
            [trip, ticket],
            now,
            goal_last={"old_trip": hour_ago, "ticket": too_soon},
            goal_mute={},
            cooldown_sec=21600,
            important_horizon_hours=36,
            important_cooldown_sec=1800,
        )
        is not None
    ):
        _fail("important cooldown 30min should still block")

    mute_until = (now + timedelta(days=7)).isoformat(timespec="seconds")
    picked = select_goal(
        [trip, ticket],
        now,
        goal_last={},
        goal_mute={"ticket": mute_until},
        cooldown_sec=21600,
        important_horizon_hours=36,
        important_cooldown_sec=1800,
    )
    if picked is None or picked["key"] != "old_trip":
        _fail(f"muted important ticket should fall back to trip, got {picked}")

    picked = select_goal(
        [trip, ticket],
        now,
        goal_last={},
        goal_mute={},
        cooldown_sec=21600,
        important_horizon_hours=36,
        important_cooldown_sec=1800,
        goal_count=1,
        max_per_day=1,
    )
    if picked is None or picked["key"] != "ticket":
        _fail(f"daily cap should still allow important ticket, got {picked}")

    soon_after = datetime(2026, 9, 1, 20, 0, 0)
    if not has_important_goal(
        [ticket], soon_after, goal_mute={}, horizon_hours=36
    ):
        _fail("ticket overdue within horizon should stay important")
    stale_now = datetime(2026, 9, 10, 15, 0, 0)
    if has_important_goal(
        [ticket, trip], stale_now, goal_mute={}, horizon_hours=36
    ):
        _fail("ticket overdue beyond horizon should not be important")
    if (
        select_goal(
            [ticket, trip],
            stale_now,
            goal_last={},
            goal_mute={},
            cooldown_sec=21600,
            important_horizon_hours=36,
            important_cooldown_sec=1800,
            goal_count=1,
            max_per_day=1,
        )
        is not None
    ):
        _fail("daily cap should block overdue-beyond-horizon ticket")
    print("  ok")


def test_mute_last_goal_phrase(tmp: Path) -> None:
    print("== 先别提 mutes last goal key ==")
    if not wants_goal_mute("先别提这个了"):
        _fail("先别提 should mute")
    if not wants_goal_mute("别再问了"):
        _fail("别再问 should mute")
    if not wants_goal_mute("不用提了"):
        _fail("不用提了 should mute")
    if wants_goal_mute("今天天气不错"):
        _fail("plain chat should not mute")

    idle_cfg = SimpleNamespace(
        enabled=True, after_sec=900, cooldown_sec=1800, max_per_day=3
    )
    care_cfg = _care_cfg()
    sched = ProactiveScheduler(
        tmp / "proactive_mute.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        goal_cfg=_goal_cfg(max_per_day=2),
    )
    now = datetime(2026, 8, 13, 15, 0, 0)
    sched.mark_fired("goal", now, goal_key="old_trip")
    if sched.state.last_goal_key != "old_trip":
        _fail(f"last_goal_key {sched.state.last_goal_key}")
    muted = sched.mute_last_goal(now)
    if muted != "old_trip" or "old_trip" not in sched.state.goal_mute:
        _fail(f"mute should record old_trip, got {muted} {sched.state.goal_mute}")
    picked = select_goal(
        _sample_goals(),
        now,
        goal_last=sched.state.goal_last,
        goal_mute=sched.state.goal_mute,
        cooldown_sec=21600,
    )
    if picked is None or picked["key"] != "new_exam":
        _fail(f"muted last key should skip old_trip, got {picked}")
    print("  ok")


def test_goal_ack_and_due_soon(tmp: Path) -> None:
    print("== goal ack skips until due-soon; sleep defers to care ==")
    sleep_goal = {
        "key": "goal_early_sleep",
        "content": "老师约定2026年9月20日晚上11点多睡觉",
        "updated_at": 1.0,
    }
    ticket_goal = {
        "key": "ticket",
        "content": "老师2026年9月20日下午2点要订回深圳的车票",
        "updated_at": 2.0,
    }
    movie_goal = {
        "key": "goal_movie",
        "content": "老师答应2026年9月20日陪阿洛娜一起看一部电影",
        "updated_at": 3.0,
    }
    morning = datetime(2026, 9, 20, 10, 21, 0)
    noon = datetime(2026, 9, 20, 12, 26, 0)
    due = datetime(2026, 9, 20, 13, 10, 0)

    breakfast_goal = "老师约定2026年9月20日早上7点半吃早饭"
    dinner_goal = "老师约定2026年9月20日晚上6点吃晚饭"
    if not goal_defers_to_care(breakfast_goal, care_enabled=True):
        _fail("breakfast goal should defer to care")
    if not goal_defers_to_care(dinner_goal, care_enabled=True):
        _fail("dinner goal should defer to care")
    if goal_is_due_soon(
        sleep_goal["content"],
        datetime(2026, 9, 20, 22, 10, 0),
        due_soon_sec=3600,
        care_enabled=True,
    ):
        _fail("sleep goal must not due-soon when care is enabled")
    if goal_is_due_soon(
        breakfast_goal,
        datetime(2026, 9, 20, 6, 40, 0),
        due_soon_sec=3600,
        care_enabled=True,
    ):
        _fail("breakfast goal must not due-soon when care is enabled")
    if goal_is_due_soon(
        dinner_goal,
        datetime(2026, 9, 20, 17, 10, 0),
        due_soon_sec=3600,
        care_enabled=True,
    ):
        _fail("dinner goal must not due-soon when care is enabled")
    if not goal_is_due_soon(
        ticket_goal["content"],
        due,
        due_soon_sec=3600,
        care_enabled=True,
    ):
        _fail("ticket should be due-soon an hour before 14:00")

    first = build_goal_instruction(sleep_goal["content"])
    if "尚未完成的计划" not in first:
        _fail(f"first visit instruction: {first}")
    nudge = build_goal_instruction(ticket_goal["content"], due_soon=True)
    if "约定时间快到了" not in nudge or "再确认计划还在不在" not in nudge:
        _fail(f"due-soon instruction: {nudge}")

    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "老师好"},
        {"role": "user", "content": HISTORY_GOAL_MARKER},
        {"role": "assistant", "content": "今晚11点睡觉哦"},
        {"role": "user", "content": "嗯，当然啦"},
        {"role": "assistant", "content": "那阿洛娜就记下啦"},
    ]
    if not history_follows_proactive_marker(history):
        _fail("reply after 【回访】 should force extract")
    if history_follows_proactive_marker(history[:4]):
        _fail("the follow-up turn itself is not a reply-after-followup")

    idle_cfg = SimpleNamespace(
        enabled=True, after_sec=900, cooldown_sec=1800, max_per_day=3
    )
    care_cfg = _care_cfg()
    sched = ProactiveScheduler(
        tmp / "proactive_ack.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        goal_cfg=_goal_cfg(max_per_day=1),
    )
    sched.note_user_activity(morning - timedelta(seconds=400))
    sched.mark_fired("goal", morning, goal_key="goal_early_sleep")
    acked = sched.ack_pending_followups(morning + timedelta(seconds=20))
    if "goal_early_sleep" not in acked:
        _fail(f"sleep should be acked, got {acked}")
    sched.note_user_activity(morning + timedelta(seconds=20))

    skipped = select_goal(
        [sleep_goal, movie_goal],
        noon,
        goal_last=sched.state.goal_last,
        goal_mute=sched.state.goal_mute,
        cooldown_sec=21600,
        important_horizon_hours=36,
        important_cooldown_sec=1800,
        goal_acked=sched.state.goal_acked,
        due_soon_sec=3600,
        care_enabled=True,
    )
    if skipped is None or skipped["key"] != "goal_movie":
        _fail(f"acked sleep should yield movie, got {skipped}")

    later = sched.pick_motive(
        noon,
        last_user_act="other",
        climate="secure_play",
        goals=[sleep_goal],
    )
    if later is not None and later.kind == "goal" and later.goal_key == "goal_early_sleep":
        _fail("acked sleep must not be revisited at noon")

    sched.mark_fired("goal", morning + timedelta(minutes=30), goal_key="ticket")
    sched.ack_pending_followups(morning + timedelta(minutes=31))
    sched.note_user_activity(morning + timedelta(minutes=31))
    picked = sched.pick_motive(
        due,
        last_user_act="other",
        climate="secure_play",
        goals=[ticket_goal, sleep_goal],
    )
    if picked is None or picked.kind != "goal" or picked.goal_key != "ticket":
        _fail(f"ticket due-soon should fire, got {picked}")
    if not picked.due_soon:
        _fail("ticket motive should be due_soon")
    if "约定时间快到了" not in picked.instruction:
        _fail(f"due-soon pick instruction: {picked.instruction}")
    sched.mark_fired("goal", due, goal_key="ticket", due_soon=True)
    again = sched.pick_motive(
        due + timedelta(minutes=35),
        last_user_act="other",
        climate="secure_play",
        goals=[ticket_goal],
    )
    if again is not None and again.kind == "goal" and again.goal_key == "ticket":
        _fail("due-soon ticket must not loop after fire")

    loaded = ProactiveScheduler(
        tmp / "proactive_ack.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        goal_cfg=_goal_cfg(),
    )
    if "goal_early_sleep" not in loaded.state.goal_acked:
        _fail("goal_acked should persist")
    print("  ok")


def test_mood_ack_skips_same_day(tmp: Path) -> None:
    print("== mood ack skips same key for the rest of the day ==")
    now = datetime(2026, 9, 18, 16, 0, 0)
    aged = (now - timedelta(hours=3)).timestamp()
    moods = [
        {
            "key": "emo_ok",
            "content": "老师2026年9月18日因加班感到难过",
            "category": "emotional",
            "updated_at": aged,
        }
    ]
    skip = mood_entry_skip_reason(
        moods[0],
        now,
        mood_last={},
        mood_mute={},
        min_age_sec=7200,
        max_age_hours=72,
        cooldown_sec=21600,
        mood_acked={"emo_ok": now.isoformat(timespec="seconds")},
    )
    if skip != "acked":
        _fail(f"same-day mood ack should skip, got {skip}")
    next_day = mood_entry_skip_reason(
        moods[0],
        now + timedelta(days=1),
        mood_last={},
        mood_mute={},
        min_age_sec=7200,
        max_age_hours=72,
        cooldown_sec=21600,
        mood_acked={"emo_ok": now.isoformat(timespec="seconds")},
    )
    if next_day == "acked":
        _fail("mood ack must not block the next calendar day")
    print("  ok")


def test_goal_after_welcome_not_blocked_by_idle(tmp: Path) -> None:
    print("== welcome after_sec ok; goal ignores idle cooldown ==")
    idle_cfg = SimpleNamespace(
        enabled=True, after_sec=30, cooldown_sec=1800, max_per_day=10
    )
    care_cfg = _care_cfg()
    sched = ProactiveScheduler(
        tmp / "proactive_goal_welcome.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        goal_cfg=_goal_cfg(),
    )
    now = datetime(2026, 8, 13, 15, 10, 0)
    sched.note_user_activity(now - timedelta(seconds=400))
    sched.note_proactive(now - timedelta(seconds=60))
    picked = sched.pick_motive(
        now,
        last_user_act="other",
        climate="secure_play",
        goals=_sample_goals(),
    )
    if picked is None or picked.kind != "goal":
        _fail(f"welcome 1min ago should still allow goal, got {picked}")

    sched.mark_fired("idle", now - timedelta(seconds=60))
    later = now
    blocked_idle = sched.pick_motive(
        later,
        last_user_act="other",
        climate="secure_play",
        goals=[],
    )
    if blocked_idle is not None and blocked_idle.kind == "idle":
        _fail("idle cooldown should still hold without goals")
    still_goal = sched.pick_motive(
        later,
        last_user_act="other",
        climate="secure_play",
        goals=_sample_goals(),
    )
    if still_goal is None or still_goal.kind != "goal":
        _fail(f"idle cooldown must not block goal, got {still_goal}")
    print("  ok")


def test_important_goal_bypasses_daily_cap_pick(tmp: Path) -> None:
    print("== pick_motive important goal after daily cap ==")
    idle_cfg = SimpleNamespace(
        enabled=True, after_sec=900, cooldown_sec=1800, max_per_day=3
    )
    care_cfg = _care_cfg()
    sched = ProactiveScheduler(
        tmp / "proactive_important_goal.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        goal_cfg=_goal_cfg(),
    )
    now = datetime(2026, 8, 31, 14, 46, 0)
    sched.note_user_activity(now - timedelta(seconds=400))
    sched.mark_fired("goal", now - timedelta(hours=2), goal_key="old_trip")
    picked = sched.pick_motive(
        now,
        last_user_act="other",
        climate="secure_play",
        goals=[
            {"key": "old_trip", "content": "老师想去海边", "updated_at": 100.0},
            {
                "key": "ticket",
                "content": "老师2026年9月1日下午2点要订回深圳的车票",
                "updated_at": 200.0,
            },
        ],
    )
    if picked is None or picked.kind != "goal" or picked.goal_key != "ticket":
        _fail(f"expected important ticket after daily cap, got {picked}")
    print("  ok")


def test_goal_global_gap_blocks_other_keys(tmp: Path) -> None:
    print("== global gap blocks another goal 30s later ==")
    idle_cfg = SimpleNamespace(
        enabled=True, after_sec=900, cooldown_sec=1800, max_per_day=3
    )
    care_cfg = _care_cfg()
    sched = ProactiveScheduler(
        tmp / "proactive_goal_gap.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        goal_cfg=_goal_cfg(),
    )
    now = datetime(2026, 8, 31, 14, 46, 0)
    goals = [
        {
            "key": "ticket",
            "content": "老师2026年9月1日下午2点要订回深圳的车票",
            "updated_at": 200.0,
        },
        {
            "key": "meeting",
            "content": "老师2026年9月1日晚上8点要开会",
            "updated_at": 201.0,
        },
    ]
    sched.note_user_activity(now - timedelta(seconds=400))
    sched.mark_fired("goal", now - timedelta(seconds=30), goal_key="ticket")
    blocked = sched.pick_motive(
        now,
        last_user_act="other",
        climate="secure_play",
        goals=goals,
    )
    if blocked is not None and blocked.kind == "goal":
        _fail(f"second important goal should wait global gap, got {blocked}")

    later = now + timedelta(seconds=1800)
    picked = sched.pick_motive(
        later,
        last_user_act="other",
        climate="secure_play",
        goals=goals,
    )
    if picked is None or picked.kind != "goal" or picked.goal_key != "meeting":
        _fail(f"after global gap should pick other important goal, got {picked}")
    print("  ok")


def test_stale_dated_goal_uses_daily_cap(tmp: Path) -> None:
    print("== overdue beyond horizon uses daily cap ==")
    idle_cfg = SimpleNamespace(
        enabled=True, after_sec=900, cooldown_sec=1800, max_per_day=3
    )
    care_cfg = _care_cfg()
    sched = ProactiveScheduler(
        tmp / "proactive_stale_goal.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        goal_cfg=_goal_cfg(),
    )
    now = datetime(2026, 9, 10, 15, 0, 0)
    sched.note_user_activity(now - timedelta(seconds=400))
    sched.mark_fired("goal", now - timedelta(hours=2), goal_key="old_trip")
    picked = sched.pick_motive(
        now,
        last_user_act="other",
        climate="secure_play",
        goals=[
            {"key": "old_trip", "content": "老师想去海边", "updated_at": 100.0},
            {
                "key": "ticket",
                "content": "老师2026年9月1日下午2点要订回深圳的车票",
                "updated_at": 200.0,
            },
        ],
    )
    if picked is not None and picked.kind == "goal":
        _fail(f"stale ticket should not bypass daily cap, got {picked}")
    print("  ok")


def test_festival_calendar_and_once(tmp: Path) -> None:
    print("== festival calendar / welcome swap / rest followup ==")
    if parse_birthday_md("老师的生日是3月15日") != (3, 15):
        _fail("cn birthday parse")
    if parse_birthday_md("1990-03-15") != (3, 15):
        _fail("iso birthday parse")
    if parse_birthday_md("03-15") != (3, 15):
        _fail("md birthday parse")
    if parse_birthday_md("今天天气不错") is not None:
        _fail("plain text should not parse as birthday")

    national = match_festival(datetime(2026, 10, 1, 10, 0, 0))
    if national is None or national.id != "national" or national.name != "国庆节":
        _fail(f"expected national day, got {national}")
    lantern = match_festival(datetime(2026, 3, 3, 8, 0, 0))
    if lantern is None or lantern.id != "lantern":
        _fail(f"expected lantern, got {lantern}")
    bday = match_festival(
        datetime(2026, 10, 1, 10, 0, 0),
        birthday_content="老师的生日是10月1日",
    )
    if bday is None or bday.id != "birthday":
        _fail(f"birthday should win over national, got {bday}")
    if match_festival(datetime(2026, 8, 13, 15, 0, 0)) is not None:
        _fail("Aug 13 2026 is not a festival")
    if HISTORY_FESTIVAL_MARKER != "【节日】":
        _fail("festival history marker")

    if not needs_rest_followup(datetime(2026, 10, 1, 23, 10, 0)):
        _fail("night should allow rest followup")
    if not needs_rest_followup(datetime(2026, 10, 1, 2, 0, 0)):
        _fail("late_night should allow rest followup")
    if needs_rest_followup(datetime(2026, 10, 1, 15, 0, 0)):
        _fail("afternoon festival should be a single line")

    idle_cfg = SimpleNamespace(
        enabled=True, after_sec=900, cooldown_sec=1800, max_per_day=3
    )
    care_cfg = _care_cfg()
    sched = ProactiveScheduler(
        tmp / "proactive_festival.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        festival_cfg=SimpleNamespace(enabled=True),
    )
    noon = datetime(2026, 10, 1, 12, 10, 0)
    sched.note_user_activity(noon - timedelta(seconds=2000))
    first = sched.pending_festival(noon)
    if first is None or first.id != "national":
        _fail(f"first login should pending national, got {first}")
    picked = sched.pick_motive(noon, last_user_act="other", climate="secure_play")
    if picked is None or picked.kind != "festival":
        _fail(f"festival should beat lunch, got {picked}")
    sched.mark_fired("festival", noon, festival_id="national")
    if sched.pending_festival(noon) is not None:
        _fail("second welcome same day should not swap to festival")
    again = sched.pick_motive(noon, last_user_act="other", climate="secure_play")
    if again is not None and again.kind == "lunch":
        _fail(f"festival just fired, lunch should wait after_sec, got {again}")
    lunch_later = sched.pick_motive(
        noon + timedelta(seconds=900),
        last_user_act="other",
        climate="secure_play",
    )
    if lunch_later is None or lunch_later.kind != "lunch":
        _fail(f"after after_sec, lunch should fire, got {lunch_later}")

    night = datetime(2026, 10, 1, 23, 10, 0)
    night_sched = ProactiveScheduler(
        tmp / "proactive_festival_night.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        festival_cfg=SimpleNamespace(enabled=True),
    )
    night_picked = night_sched.pick_motive(night, last_user_act="other")
    if night_picked is None or night_picked.kind != "festival":
        _fail(f"REST_SLOTS should still festival, got {night_picked}")
    night_sched.mark_fired("festival", night, festival_id="national")
    night_sched.mark_fired("sleep", night)
    blocked_sleep = night_sched.pick_motive(night, last_user_act="other")
    if blocked_sleep is not None and blocked_sleep.kind in {"festival", "sleep"}:
        _fail(f"after rest followup, sleep/festival should be done, got {blocked_sleep}")

    depart_sched = ProactiveScheduler(
        tmp / "proactive_festival_depart.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        festival_cfg=SimpleNamespace(enabled=True),
    )
    departed = depart_sched.pick_motive(
        datetime(2026, 10, 1, 16, 0, 0),
        last_user_act="depart",
    )
    if departed is not None and departed.kind == "festival":
        _fail("tick should skip festival after depart")
    if depart_sched.pending_festival(datetime(2026, 10, 1, 16, 0, 0)) is None:
        _fail("welcome swap should still see pending festival after depart")
    print("  ok")


def test_followup_ok_default_and_gate() -> None:
    print("== followup_ok default false; draft gate ==")
    legacy = parse_and_gate_intent(
        '{"user_emotion":"平静","topic":"问候","stance":"回应",'
        '"must_say":["问好"],"must_not":[],"facts_to_use":[],'
        '"tone":"温柔","length":"1-2句","arona_emotion":"smile"}'
    )
    if legacy is not None:
        _fail("legacy card without draft must fail gate")

    raw = '{"draft":"老师好，今天也请多指教。","arona_emotion":"smile"}'
    card = parse_and_gate_intent(raw)
    if card is None:
        _fail("card should parse")
    if card.followup_ok:
        _fail("followup_ok should default false")
    if "followup_ok" in card.to_renderer_dict():
        _fail("followup_ok must not go to renderer")
    if card.to_renderer_draft() != "老师好，今天也请多指教。":
        _fail(f"unexpected draft: {card.to_renderer_draft()!r}")

    raw_ok = (
        '{"draft":"光环是阿洛娜身份的一部分，我可以慢慢讲给老师听。",'
        '"arona_emotion":"smile","followup_ok":true}'
    )
    gated = parse_and_gate_intent(raw_ok)
    if gated is None or not gated.followup_ok:
        _fail("followup_ok true should survive parse")
    print("  ok")


def test_continue_renderer_split_and_skip() -> None:
    print("== continue: planner system event; renderer draft only; too_similar ==")
    from app.planner.schema import IntentCard
    from app.prompt import build_renderer_messages
    from app.proactive.followup import (
        build_continue_instruction,
        last_teacher_utterance,
        should_skip_continue,
        too_similar,
    )

    previous = "老师今天过得真好！"
    history = [
        {"role": "user", "content": "我今天过得很好"},
        {"role": "assistant", "content": previous},
    ]
    if last_teacher_utterance(history) != "我今天过得很好":
        _fail("last teacher should skip Arona's previous line")

    instruction = build_continue_instruction(previous)
    if "【系统事件】" not in instruction or "上一句是：" not in instruction:
        _fail("Planner continue instruction still needs system event + previous line")
    if "与上一句不同的新信息" not in instruction:
        _fail("continue instruction must require new information")
    if "已经回答过的问题" not in instruction:
        _fail("continue instruction must forbid re-asking answered questions")

    draft = "那明天要不要一起去买草莓牛奶？"
    card = IntentCard(draft=draft, arona_emotion="smile", followup_ok=False)
    cfg = load_config()
    msgs = build_renderer_messages(
        cfg,
        draft=card.to_renderer_draft(),
        history=history,
        max_history_turns=2,
    )
    payload = msgs[-1]["content"]
    if "【意图草稿】" not in payload:
        _fail("Renderer payload needs 【意图草稿】")
    if draft not in payload:
        _fail("Renderer payload should contain draft")
    if "【系统事件】" in payload:
        _fail("Renderer payload must not contain 【系统事件】")
    if "上一句是：" in payload:
        _fail("Renderer payload must not contain 上一句是：")
    if "【老师原话】" in payload:
        _fail("Renderer payload must not contain 【老师原话】")
    if "【回复意图卡】" in payload:
        _fail("Renderer payload must not contain JSON intent card header")
    if "我今天过得很好" in payload or previous in payload:
        _fail("Renderer must not see teacher utterance or previous Arona line")

    if not should_skip_continue("老师今天过得真好！还去了哪里呢？"):
        _fail("two-sentence first reply should skip continue")
    if should_skip_continue("老师今天过得真好！"):
        _fail("one-sentence first reply should still allow continue")
    if should_skip_continue(""):
        _fail("empty previous is not a two-sentence skip")

    if not too_similar("老师今天过得真好！", "老师今天过得真好"):
        _fail("punctuation-only difference is similar")
    if not too_similar("老师今天过得真好！", "老师今天过得真好呀~"):
        _fail("near restatement should be similar")
    if too_similar("老师今天过得真好！", "那明天要不要一起去买草莓牛奶？"):
        _fail("new information should not be similar")
    if too_similar("", "补一句"):
        _fail("empty previous is not similar")
    print("  ok")


def _mood_cfg(**overrides: object) -> SimpleNamespace:
    ns = SimpleNamespace(
        enabled=True,
        min_after_user_sec=900,
        min_age_sec=7200,
        max_age_hours=72,
        cooldown_sec=21600,
        mute_sec=604800,
        max_per_day=1,
    )
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def test_mood_followup_select_and_gates(tmp: Path) -> None:
    print("== mood followup select / climate / mute / priority ==")
    now = datetime(2026, 9, 18, 15, 0, 0)
    quiet = now - timedelta(seconds=1200)
    aged = (now - timedelta(hours=3)).timestamp()
    newer = (now - timedelta(minutes=30)).timestamp()
    older_content = "老师2026年9月16日因加班感到难过"
    newer_content = "老师2026年9月18日因为被批评有点委屈"
    crisis = "老师不想活了"
    episodic = "老师2026年9月16日和阿洛娜一起看烟花"

    if mood_entry_skip_reason(
        {
            "key": "emo_new",
            "content": newer_content,
            "category": "emotional",
            "updated_at": newer,
        },
        now,
        mood_last={},
        mood_mute={},
        min_age_sec=7200,
        max_age_hours=72,
        cooldown_sec=21600,
    ) != "too_new":
        _fail("same-day too new should skip")
    if mood_entry_skip_reason(
        {
            "key": "emo_old",
            "content": "老师2026年9月10日因加班感到难过",
            "category": "emotional",
            "updated_at": 1.0,
        },
        now,
        mood_last={},
        mood_mute={},
        min_age_sec=7200,
        max_age_hours=72,
        cooldown_sec=21600,
    ) != "too_old":
        _fail("older than 72h should skip")
    if mood_entry_skip_reason(
        {
            "key": "emo_crisis",
            "content": crisis,
            "category": "emotional",
            "updated_at": aged,
        },
        now,
        mood_last={},
        mood_mute={},
        min_age_sec=7200,
        max_age_hours=72,
        cooldown_sec=21600,
    ) != "crisis":
        _fail("crisis content should skip")
    if mood_entry_skip_reason(
        {
            "key": "ep_1",
            "content": episodic,
            "category": "episodic",
            "updated_at": aged,
        },
        now,
        mood_last={},
        mood_mute={},
        min_age_sec=7200,
        max_age_hours=72,
        cooldown_sec=21600,
    ) != "not_source":
        _fail("episodic should not be a followup source")

    picked = select_mood_entry(
        [
            {
                "key": "emo_new",
                "content": newer_content,
                "category": "emotional",
                "updated_at": newer,
            },
            {
                "key": "emo_ok",
                "content": older_content,
                "category": "emotional",
                "updated_at": aged,
            },
            {
                "key": "emo_crisis",
                "content": crisis,
                "category": "emotional",
                "updated_at": aged,
            },
        ],
        now,
        mood_last={},
        mood_mute={},
        min_age_sec=7200,
        max_age_hours=72,
        cooldown_sec=21600,
    )
    if picked is None or picked.get("key") != "emo_ok":
        _fail(f"expected oldest in-window mood, got {picked}")

    if can_attempt_mood(
        now,
        enabled=True,
        last_user_at=quiet,
        last_user_act="other",
        climate=None,
        mood_count=0,
        min_after_user_sec=900,
        max_per_day=1,
    ):
        _fail("unknown climate must not attempt mood")
    if can_attempt_mood(
        now,
        enabled=True,
        last_user_at=quiet,
        last_user_act="depart",
        climate="steady",
        mood_count=0,
        min_after_user_sec=900,
        max_per_day=1,
    ):
        _fail("depart must not attempt mood")
    if can_attempt_mood(
        now,
        enabled=True,
        last_user_at=quiet,
        last_user_act="reject",
        climate="steady",
        mood_count=0,
        min_after_user_sec=900,
        max_per_day=1,
    ):
        _fail("reject must not attempt mood")
    if can_attempt_mood(
        now,
        enabled=True,
        last_user_at=quiet,
        last_user_act="crisis",
        climate="steady",
        mood_count=0,
        min_after_user_sec=900,
        max_per_day=1,
    ):
        _fail("crisis user_act must not attempt mood")
    if can_attempt_mood(
        now,
        enabled=True,
        last_user_at=quiet,
        last_user_act="other",
        climate="fragile",
        mood_count=0,
        min_after_user_sec=900,
        max_per_day=1,
    ):
        _fail("fragile must not attempt mood")
    if not can_attempt_mood(
        now,
        enabled=True,
        last_user_at=quiet,
        last_user_act="other",
        climate="steady",
        mood_count=0,
        min_after_user_sec=900,
        max_per_day=1,
    ):
        _fail("steady quiet afternoon should allow mood")
    if "治疗师" not in build_mood_instruction(older_content):
        _fail("mood instruction should ban therapist role")
    if HISTORY_MOOD_MARKER != "【心情回访】":
        _fail("history marker")
    if not wants_topic_mute("先别提这个了"):
        _fail("topic mute alias should match 先别提")

    idle_cfg = SimpleNamespace(
        enabled=True, after_sec=900, cooldown_sec=1800, max_per_day=3
    )
    care_cfg = _care_cfg()
    path = tmp / "proactive_mood.json"
    moods = [
        {
            "key": "emo_ok",
            "content": older_content,
            "category": "emotional",
            "updated_at": aged,
        }
    ]
    sched = ProactiveScheduler(
        path,
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        mood_cfg=_mood_cfg(),
    )
    sched.state.last_user_at = quiet.isoformat(timespec="seconds")
    sched.save()
    hit = sched.pick_motive(
        now,
        last_user_act="other",
        climate="steady",
        moods=moods,
    )
    if hit is None or hit.kind != MOOD_FOLLOWUP_KIND:
        _fail(f"expected mood_followup, got {hit}")
    if hit.mood_key != "emo_ok":
        _fail(f"mood_key {hit.mood_key}")
    if HISTORY_MOOD_MARKER not in hit.history_marker:
        _fail("mood history marker missing")

    sched.mark_fired(MOOD_FOLLOWUP_KIND, now, mood_key="emo_ok")
    if "mood_followup" in sched.state.care_done:
        _fail("mood_followup must not land in care_done")
    if sched.state.mood_count != 1 or sched.state.last_mood_key != "emo_ok":
        _fail(f"mood mark_fired failed {sched.state.mood_count} {sched.state.last_mood_key}")

    muted = sched.mute_last_followup(now)
    if muted != "emo_ok":
        _fail(f"expected mute emo_ok, got {muted}")
    next_day = now + timedelta(days=1)
    blocked = sched.pick_motive(
        next_day,
        last_user_act="other",
        climate="steady",
        moods=moods,
    )
    if blocked is not None and blocked.kind == MOOD_FOLLOWUP_KIND:
        _fail("muted mood must not fire again")

    off = ProactiveScheduler(
        tmp / "proactive_mood_off.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        mood_cfg=_mood_cfg(enabled=False),
    )
    off.state.last_user_at = quiet.isoformat(timespec="seconds")
    off.save()
    skipped = off.pick_motive(
        now,
        last_user_act="other",
        climate="steady",
        moods=moods,
    )
    if skipped is not None and skipped.kind == MOOD_FOLLOWUP_KIND:
        _fail("enabled=false must never pick mood_followup")

    lunch = datetime(2026, 9, 18, 12, 10, 0)
    lunch_sched = ProactiveScheduler(
        tmp / "proactive_mood_lunch.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        mood_cfg=_mood_cfg(),
    )
    lunch_sched.state.last_user_at = (lunch - timedelta(seconds=1200)).isoformat(
        timespec="seconds"
    )
    lunch_sched.save()
    care_hit = lunch_sched.pick_motive(
        lunch,
        last_user_act="other",
        climate="steady",
        moods=moods,
    )
    if care_hit is None or care_hit.kind != "lunch":
        _fail(f"lunch must beat mood_followup, got {care_hit}")

    goal_sched = ProactiveScheduler(
        tmp / "proactive_mood_goal.json",
        idle_cfg=idle_cfg,
        care_cfg=care_cfg,
        mood_cfg=_mood_cfg(),
    )
    goal_sched.state.last_user_at = quiet.isoformat(timespec="seconds")
    goal_sched.save()
    goal_hit = goal_sched.pick_motive(
        now,
        last_user_act="other",
        climate="steady",
        goals=[
            {
                "key": "goal_walk",
                "content": "老师打算和阿洛娜出去散步",
                "updated_at": aged,
            }
        ],
        moods=moods,
    )
    if goal_hit is None or goal_hit.kind != "goal":
        _fail(f"goal must beat mood_followup, got {goal_hit}")
    print("  ok")


def main() -> None:
    test_idle_fire_rules()
    test_care_window_once_per_day()
    test_care_planner_declined()
    test_decide_proactive_policy()
    test_list_by_category()
    test_goal_fire_rules()
    test_goal_importance_cooldown()
    test_followup_ok_default_and_gate()
    test_continue_renderer_split_and_skip()
    with tempfile.TemporaryDirectory() as tmp:
        test_scheduler_persist_and_priority(Path(tmp))
        test_welcome_does_not_eat_idle_cooldown(Path(tmp))
        test_care_waits_after_welcome(Path(tmp))
        test_mark_care_addressed_skips_without_proactive_stamp(Path(tmp))
        test_mute_last_goal_phrase(Path(tmp))
        test_goal_ack_and_due_soon(Path(tmp))
        test_mood_ack_skips_same_day(Path(tmp))
        test_goal_after_welcome_not_blocked_by_idle(Path(tmp))
        test_important_goal_bypasses_daily_cap_pick(Path(tmp))
        test_goal_global_gap_blocks_other_keys(Path(tmp))
        test_stale_dated_goal_uses_daily_cap(Path(tmp))
        test_festival_calendar_and_once(Path(tmp))
        test_mood_followup_select_and_gates(Path(tmp))
    test_hub_busy()
    test_tick_once_enqueues_care_without_initiate()
    test_welcome_impulse_flush_speaks()
    test_climate_withhold_care_does_not_initiate()
    test_generate_fail_does_not_mark_fired()
    test_busy_defers_impulse_speak()
    test_config_loads()
    print("ALL PASS")


if __name__ == "__main__":
    main()
