"""Unit tests for the life loop inner state (no GGUF).

Run from backend/:
  python scripts/test_life_unit.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.life import (  # noqa: E402
    Impulse,
    InnerState,
    LifeEngine,
    LifeSettings,
    LifeStore,
    PresenceGate,
    Rumination,
    decide,
    format_interrupt_block,
    note_teacher_turn,
    offer_impulse,
    presence_emotion,
    publish_presence,
    world_event,
)
from app.life.impulse import merge_impulse  # noqa: E402
from app.life.loop import tick_once  # noqa: E402
from app.life.policy import SIMMER_SEC, LifeDecision  # noqa: E402
from app.proactive.hub import ConnectionHub  # noqa: E402
from app.protocol import TYPE_PRESENCE, msg_presence  # noqa: E402
from app.relationship import RelationshipState, RelationshipStore  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def _settings(**overrides: float) -> LifeSettings:
    base = dict(look_hold_sec=180, think_hold_sec=120)
    base.update(overrides)
    return LifeSettings(**base)


def _afternoon() -> datetime:
    return datetime(2026, 8, 13, 15, 0, 0)


def _night() -> datetime:
    return datetime(2026, 8, 13, 23, 30, 0)


def _morning() -> datetime:
    return datetime(2026, 8, 13, 10, 0, 0)


def _assert_not_speak(decision: LifeDecision) -> None:
    if decision.action in {"speak", "glance", "emotion_only"}:
        _fail(f"layer 1 must not select {decision.action}")


def test_json_roundtrip_isolated_from_relationship() -> None:
    print("== persist roundtrip, isolated from relationship ==")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        life_path = root / "life.json"
        rel_path = root / "relationship.json"
        rel_store = RelationshipStore(rel_path)
        rel_state = RelationshipState(trust=0.42, day="2026-08-13")
        rel_store.save(rel_state)

        engine = LifeEngine.from_path(life_path, _settings())
        now = _afternoon()
        engine.apply(world_event("teacher_spoke", at=now))
        if not life_path.is_file():
            _fail("life.json was not written")
        raw = json.loads(life_path.read_text(encoding="utf-8"))
        if raw.get("activity") != "looking_at_teacher":
            _fail(f"saved activity {raw.get('activity')}")

        reloaded = LifeStore(life_path).load()
        if reloaded.activity != "looking_at_teacher":
            _fail("roundtrip lost activity")
        if reloaded.attention != "teacher":
            _fail("roundtrip lost attention")

        pending = Impulse(
            kind="lunch",
            created_at=now,
            hint="老师午饭窗口到了",
            allow_speak=True,
        )
        engine.state = engine.state.clone()
        engine.state.pending_impulse = pending
        engine.store.save(engine.state)
        again = LifeStore(life_path).load()
        if again.pending_impulse is None or again.pending_impulse.kind != "lunch":
            _fail("pending impulse must roundtrip")
        if "老师午饭窗口到了" not in (again.pending_impulse.hint or ""):
            _fail("impulse hint must roundtrip")

        rel_again = rel_store.load()
        if abs(rel_again.trust - 0.42) > 1e-9:
            _fail("life persist overwrote relationship")
        rel_text = rel_path.read_text(encoding="utf-8")
        if "looking_at_teacher" in rel_text:
            _fail("life fields leaked into relationship.json")
    print("  ok")


def test_look_hold_decays_to_idle() -> None:
    print("== looking_at_teacher decays to idle_in_classroom ==")
    now = _afternoon()
    state = InnerState()
    decision = decide(
        state,
        world_event("teacher_spoke", at=now),
        settings=_settings(look_hold_sec=180),
    )
    _assert_not_speak(decision)
    if decision.state.activity != "looking_at_teacher":
        _fail(decision.state.activity)
    later = now + timedelta(seconds=181)
    decayed = decide(
        decision.state,
        world_event("clock_tick", at=later),
        settings=_settings(look_hold_sec=180),
    )
    _assert_not_speak(decayed)
    if decayed.action != "shift_activity":
        _fail(f"expected shift got {decayed.action}")
    if decayed.state.activity != "idle_in_classroom":
        _fail(f"expected idle got {decayed.state.activity}")
    if decayed.state.attention != "diffuse":
        _fail(decayed.state.attention)
    if decayed.state.private_mood != "calm":
        _fail(decayed.state.private_mood)
    still = decide(
        decayed.state,
        world_event("clock_tick", at=later + timedelta(seconds=5)),
        settings=_settings(look_hold_sec=180),
    )
    if still.action != "continue_activity":
        _fail(still.action)
    print("  ok")


def test_rest_slots_and_leave() -> None:
    print("== REST_SLOTS -> resting, then idle after leaving ==")
    night = _night()
    state = InnerState()
    decision = decide(
        state, world_event("clock_tick", at=night), settings=_settings()
    )
    _assert_not_speak(decision)
    if decision.state.activity != "resting":
        _fail(decision.state.activity)
    if decision.state.private_mood != "sleepy":
        _fail(decision.state.private_mood)
    morning = _morning()
    left = decide(
        decision.state, world_event("clock_tick", at=morning), settings=_settings()
    )
    _assert_not_speak(left)
    if left.state.activity != "idle_in_classroom":
        _fail(left.state.activity)
    if left.state.private_mood != "calm":
        _fail(left.state.private_mood)
    print("  ok")


def test_rumination_thinking_then_idle() -> None:
    print("== rumination can enter thinking; ticks never speak ==")
    now = _afternoon()
    concern = Rumination(id="r1", content="老师中午好像没吃饭", created_at=now)
    state = InnerState().with_rumination([concern])
    looked = decide(
        state, world_event("teacher_arrived", at=now), settings=_settings()
    )
    later = now + timedelta(seconds=200)
    thinking = decide(
        looked.state, world_event("clock_tick", at=later), settings=_settings()
    )
    _assert_not_speak(thinking)
    if thinking.state.activity != "thinking":
        _fail(thinking.state.activity)
    if thinking.state.attention != "rumination":
        _fail(thinking.state.attention)
    if not thinking.state.has_rumination():
        _fail("rumination dropped while thinking")
    after = later + timedelta(seconds=121)
    idle = decide(
        thinking.state, world_event("clock_tick", at=after), settings=_settings()
    )
    _assert_not_speak(idle)
    if idle.state.activity != "idle_in_classroom":
        _fail(idle.state.activity)
    if not idle.state.has_rumination():
        _fail("rumination must remain after thinking ends")
    cursor = idle.state
    for i in range(8):
        step = decide(
            cursor,
            world_event("clock_tick", at=after + timedelta(seconds=5 * (i + 1))),
            settings=_settings(),
        )
        _assert_not_speak(step)
        cursor = step.state
    print("  ok")


def test_impulse_due_without_pending_does_not_speak() -> None:
    print("== impulse_due without pending impulse does not speak ==")
    now = _afternoon()
    state = InnerState(activity="idle_in_classroom")
    decision = decide(
        state, world_event("impulse_due", at=now), settings=_settings()
    )
    _assert_not_speak(decision)
    if decision.action != "continue_activity":
        _fail(decision.action)
    if decision.state.activity != "idle_in_classroom":
        _fail(decision.state.activity)
    print("  ok")


def test_care_impulse_simmers_then_speaks() -> None:
    print("== care impulse emotion_only then speak after simmer ==")
    now = _afternoon()
    pending = Impulse(
        kind="lunch",
        created_at=now,
        hint="老师午饭窗口到了",
        allow_speak=True,
    )
    state = InnerState(activity="idle_in_classroom", pending_impulse=pending)
    young = decide(
        state, world_event("impulse_due", at=now), settings=_settings()
    )
    if young.action != "emotion_only":
        _fail(young.action)
    if young.state.activity != "thinking":
        _fail(young.state.activity)
    if young.state.pending_impulse is None:
        _fail("simmer must keep impulse")
    with tempfile.TemporaryDirectory() as tmp:
        engine = LifeEngine.from_path(Path(tmp) / "life.json", _settings())
        offer_impulse(
            engine,
            Impulse(
                kind="lunch",
                created_at=now,
                hint="老师午饭窗口到了",
                allow_speak=True,
            ),
        )
        if "老师午饭窗口到了" not in " ".join(
            item.content for item in engine.state.rumination
        ):
            _fail("care enqueue must write rumination")
    aged = decide(
        young.state,
        world_event("impulse_due", at=now + timedelta(seconds=SIMMER_SEC + 1)),
        settings=_settings(),
    )
    if aged.action != "speak":
        _fail(aged.action)
    if aged.state.pending_impulse is None:
        _fail("speak keeps impulse until effector marks")
    empty = decide(
        InnerState(),
        world_event("clock_tick", at=now + timedelta(seconds=5)),
        settings=_settings(),
    )
    _assert_not_speak(empty)
    print("  ok")


def test_same_kind_keeps_impulse_timer() -> None:
    print("== same-kind enqueue keeps the original timer ==")
    now = _afternoon()
    first = Impulse(kind="lunch", created_at=now, hint="老师午饭窗口到了")
    state = InnerState(pending_impulse=first)
    later = Impulse(
        kind="lunch",
        created_at=now + timedelta(seconds=20),
        hint="老师午饭窗口到了",
    )
    nxt, accepted = merge_impulse(state, later)
    if not accepted:
        _fail("same kind should be accepted")
    if nxt.pending_impulse is None or nxt.pending_impulse.created_at != now:
        _fail("same kind must not reset created_at")
    festival = Impulse(kind="festival", created_at=now + timedelta(seconds=1))
    replaced, ok = merge_impulse(nxt, festival)
    if not ok or replaced.pending_impulse is None:
        _fail("higher priority festival should replace lunch")
    if replaced.pending_impulse.kind != "festival":
        _fail(replaced.pending_impulse.kind)
    print("  ok")


def test_listen_on_does_not_block_impulse() -> None:
    print("== can_hear does not block impulse_due ==")
    now = _afternoon()
    state = InnerState(
        activity="idle_in_classroom",
        can_hear=True,
        pending_impulse=Impulse(
            kind="lunch",
            created_at=now,
            hint="老师午饭窗口到了",
            allow_speak=True,
        ),
    )
    young = decide(
        state, world_event("impulse_due", at=now), settings=_settings()
    )
    if young.action != "emotion_only":
        _fail(young.action)
    if not young.state.can_hear:
        _fail("can_hear should survive impulse_due")
    if young.state.pending_impulse is None:
        _fail("simmer must keep impulse while listening")
    print("  ok")


def test_idle_impulse_over_thinking_is_emotion_only() -> None:
    print("== idle impulse does not speak over rumination ==")
    now = _afternoon()
    state = InnerState(
        activity="thinking",
        attention="rumination",
        pending_impulse=Impulse(kind="idle", created_at=now, allow_speak=True),
    ).with_rumination(
        [Rumination(id="r1", content="老师中午好像没吃饭", created_at=now)]
    )
    decision = decide(
        state, world_event("impulse_due", at=now), settings=_settings()
    )
    if decision.action != "emotion_only":
        _fail(decision.action)
    if decision.impulse_followup != "mark_fired":
        _fail(decision.impulse_followup)
    if decision.state.pending_impulse is not None:
        _fail("idle withhold should clear impulse")
    print("  ok")


def test_goal_withhold_drops_without_mark_fired() -> None:
    print("== withheld goal/mood drop impulse without mark_fired ==")
    now = _afternoon()
    decision = decide(
        InnerState(
            pending_impulse=Impulse(
                kind="goal",
                created_at=now,
                source_id="exam",
                allow_speak=False,
            )
        ),
        world_event("impulse_due", at=now),
        settings=_settings(),
    )
    if decision.action != "emotion_only":
        _fail(decision.action)
    if decision.impulse_followup != "drop":
        _fail(decision.impulse_followup)
    if decision.state.pending_impulse is not None:
        _fail("withheld goal should drop")
    print("  ok")


def test_listen_on_does_not_freeze_ticks() -> None:
    print("== listen_on does not freeze the clock ==")
    now = _afternoon()
    looked = decide(
        InnerState(),
        world_event("teacher_spoke", at=now),
        settings=_settings(look_hold_sec=180),
    )
    hearing = decide(
        looked.state,
        world_event("listen_on", at=now + timedelta(seconds=1)),
        settings=_settings(look_hold_sec=180),
    )
    if not hearing.state.can_hear:
        _fail("can_hear should be true")
    if hearing.state.activity != "looking_at_teacher":
        _fail("listen_on must not change activity")
    decayed = decide(
        hearing.state,
        world_event("clock_tick", at=now + timedelta(seconds=181)),
        settings=_settings(look_hold_sec=180),
    )
    _assert_not_speak(decayed)
    if decayed.state.activity != "idle_in_classroom":
        _fail("tick must still decay while can_hear")
    if not decayed.state.can_hear:
        _fail("can_hear should survive ticks")
    print("  ok")


def test_engine_ticks_never_speak_or_chat() -> None:
    print("== engine ticks persist without speak ==")
    with tempfile.TemporaryDirectory() as tmp:
        engine = LifeEngine.from_path(Path(tmp) / "life.json", _settings())
        now = _afternoon()
        engine.apply(world_event("teacher_touched", at=now))
        for i in range(6):
            decision = engine.tick(now + timedelta(seconds=30 * (i + 1)), climate="steady")
            if decision is None:
                _fail("tick returned None")
            _assert_not_speak(decision)
        if engine.state.last_spoke_at is not None:
            _fail("tick must not stamp last_spoke_at")
        engine.note_arona_spoke(now + timedelta(minutes=5))
        if engine.state.last_spoke_at is None:
            _fail("note_arona_spoke should stamp")
    print("  ok")


def test_loop_tick_once_with_fake_state() -> None:
    print("== tick_once on AppState-like object ==")
    with tempfile.TemporaryDirectory() as tmp:
        engine = LifeEngine.from_path(Path(tmp) / "life.json", _settings())
        planner = MagicMock()
        fake = SimpleNamespace(
            life=engine,
            orchestrator=SimpleNamespace(relationship=None, planner=planner),
            config=SimpleNamespace(proactive=SimpleNamespace(relationship=None)),
        )
        tick_once(fake, now=_afternoon())
        if engine.state.activity not in {"idle_in_classroom", "resting"}:
            _fail(engine.state.activity)
        planner.plan.assert_not_called()
    print("  ok")


def test_presence_emotion_mapping() -> None:
    print("== presence_emotion maps activity/mood onto whitelist ==")
    cases = [
        (InnerState(activity="resting", private_mood="sleepy"), "sleep"),
        (InnerState(activity="resting", private_mood="bright"), "sleep_very_content"),
        (InnerState(activity="looking_at_teacher", private_mood="bright"), "normal"),
        (InnerState(activity="looking_at_teacher", private_mood="calm"), "normal"),
        (InnerState(activity="looking_at_teacher", private_mood="sleepy"), "sleep"),
        (InnerState(activity="thinking", private_mood="preoccupied"), "curious"),
        (InnerState(activity="thinking", private_mood="weary"), "frustration"),
        (InnerState(activity="thinking", private_mood="sleepy"), "sleep"),
        (InnerState(activity="idle_in_classroom", private_mood="calm"), "normal"),
        (InnerState(activity="idle_in_classroom", private_mood="bright"), "smile"),
        (InnerState(activity="idle_in_classroom", private_mood="weary"), "frustration"),
        (InnerState(activity="idle_in_classroom", private_mood="preoccupied"), "curious"),
        (InnerState(activity="idle_in_classroom", private_mood="sleepy"), "sleep"),
        (InnerState(activity="using_computer", private_mood="sleepy"), "curious"),
        (InnerState(activity="using_computer", private_mood="calm"), "curious"),
        (
            InnerState.from_dict(
                {"activity": "idle_in_classroom", "private_mood": "not-a-mood"}
            ),
            "normal",
        ),
    ]
    for state, expected in cases:
        got = presence_emotion(state)
        if got != expected:
            _fail(f"activity={state.activity} mood={state.private_mood} -> {got} want {expected}")
    print("  ok")


def test_msg_presence_has_no_content() -> None:
    print("== msg_presence is not a chat_response ==")
    payload = msg_presence("sleep", activity="resting")
    if payload.get("type") != TYPE_PRESENCE:
        _fail(payload.get("type"))
    if "content" in payload:
        _fail("presence must not carry content")
    if payload.get("emotion") != "sleep":
        _fail(payload.get("emotion"))
    if payload.get("activity") != "resting":
        _fail(payload.get("activity"))
    print("  ok")


def _presence_state(engine: LifeEngine, hub: ConnectionHub) -> SimpleNamespace:
    return SimpleNamespace(
        life=engine,
        hub=hub,
        presence=PresenceGate(),
        orchestrator=SimpleNamespace(relationship=None),
        config=SimpleNamespace(proactive=SimpleNamespace(relationship=None)),
    )


def test_presence_publish_change_busy_and_listen() -> None:
    print("== presence pushes on emotion change; busy defers; listen still receives ==")

    async def _run() -> None:
        sent: list[dict] = []

        async def send(payload: dict) -> None:
            sent.append(dict(payload))

        with tempfile.TemporaryDirectory() as tmp:
            engine = LifeEngine.from_path(Path(tmp) / "life.json", _settings())
            hub = ConnectionHub()
            hub.register("s1", send)
            hub.set_listening("s1", True)
            state = _presence_state(engine, hub)

            await publish_presence(state)
            if not sent:
                _fail("first presence should send current face")
            if sent[-1]["type"] != "presence":
                _fail(sent[-1]["type"])
            if "content" in sent[-1]:
                _fail("presence payload must not include content")
            if sent[-1]["emotion"] != "normal":
                _fail(sent[-1]["emotion"])
            n = len(sent)
            await publish_presence(state)
            if len(sent) != n:
                _fail("same face must not resend")

            hub.set_busy("s1", True)
            engine.apply(world_event("clock_tick", at=_night()))
            await publish_presence(state)
            if len(sent) != n:
                _fail("busy must defer presence")
            if not state.presence.pending:
                _fail("deferred presence should be pending")
            hub.set_busy("s1", False)
            await publish_presence(state)
            if len(sent) != n + 1:
                _fail(f"flush after busy sent {len(sent) - n} extra")
            if sent[-1]["emotion"] != "sleep":
                _fail(sent[-1]["emotion"])
            if sent[-1]["activity"] != "resting":
                _fail(sent[-1]["activity"])

            tick_once(state, now=_night() + timedelta(seconds=5))
            await asyncio.sleep(0)
            if len(sent) != n + 1:
                _fail("tick with same face must not push")

    asyncio.run(_run())
    print("  ok")


def test_snapshot_before_apply_and_interrupt_keeps_thinking() -> None:
    print("== snapshot is pre-apply; teacher_interrupt does not look at teacher ==")
    now = _afternoon()
    with tempfile.TemporaryDirectory() as tmp:
        engine = LifeEngine.from_path(Path(tmp) / "life.json", _settings())
        concern = Rumination(id="r1", content="老师中午好像没吃饭", created_at=now)
        engine.state = InnerState(
            activity="thinking",
            attention="rumination",
            private_mood="preoccupied",
        ).with_rumination([concern])
        fake = SimpleNamespace(
            life=engine,
            hub=ConnectionHub(),
            presence=PresenceGate(),
            orchestrator=SimpleNamespace(relationship=None),
            config=SimpleNamespace(proactive=SimpleNamespace(relationship=None)),
        )
        snap = note_teacher_turn(fake, "teacher_spoke", session_id="s1")
        if snap is None or snap.activity != "thinking":
            _fail(f"snapshot should be thinking, got {None if snap is None else snap.activity}")
        if engine.state.activity != "looking_at_teacher":
            _fail(engine.state.activity)
        block = format_interrupt_block(snap)
        if "正在想事情" not in block:
            _fail(block)
        if "老师中午好像没吃饭" not in block:
            _fail(block)
        if "【老师本轮消息】" in block:
            _fail("interrupt block must not store teacher text")

        engine.state = InnerState(activity="idle_in_classroom")
        idle_snap = note_teacher_turn(fake, "teacher_spoke", session_id="s1")
        if idle_snap is None or idle_snap.activity != "idle_in_classroom":
            _fail(
                "idle snapshot should stay idle_in_classroom, got "
                f"{None if idle_snap is None else idle_snap.activity}"
            )

        engine.state = InnerState(activity="thinking", attention="rumination")
        interrupted = decide(
            engine.state,
            world_event("teacher_interrupt", at=now),
            settings=_settings(),
        )
        _assert_not_speak(interrupted)
        if interrupted.state.activity != "thinking":
            _fail(f"interrupt must keep thinking, got {interrupted.state.activity}")
    print("  ok")


def test_journal_skips_crisis_and_teacher_text() -> None:
    print("== journal ring skips crisis text and teacher utterances ==")
    from app.life.arona_memory import AronaMemory
    from app.life.journal import MAX_ENTRIES, LifeJournal

    teacher_line = "老师刚才说的原句不要入档"
    crisis_line = "我想死"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        journal = LifeJournal(root / "life_journal.json")
        memory = AronaMemory(root / "arona.json")
        now = _afternoon()
        inner = InnerState(activity="idle_in_classroom")
        journal.seed(inner)
        journal.note_inner(inner, now=now, arona=memory)
        if journal.entries:
            _fail("same activity must not log a shift")
        inner = InnerState(activity="thinking", private_mood="preoccupied")
        journal.note_inner(inner, now=now, arona=memory)
        if len(journal.entries) != 1 or journal.entries[0].kind != "shift":
            _fail(f"activity change should be one shift, got {journal.entries}")
        journal.note_teacher_opened(teacher_line)
        if journal.contains_text(teacher_line):
            _fail("teacher utterance landed in the journal")
        if not journal.append("rumination", crisis_line, now):
            pass
        elif journal.contains_text(crisis_line):
            _fail("crisis summary landed in the journal")
        if journal.contains_text(crisis_line):
            _fail("crisis summary landed in the journal")
        remembered = InnerState(
            activity="thinking",
            rumination=[
                Rumination(
                    id="imp-sleep",
                    content="老师睡觉窗口到了",
                    created_at=now,
                )
            ],
        )
        journal.note_inner(remembered, now=now, arona=memory)
        ended = InnerState(activity="thinking")
        journal.note_inner(ended, now=now + timedelta(seconds=1), arona=memory)
        if not any(item.summary.startswith("放下：") for item in journal.entries):
            _fail("ended rumination should be summarized")
        if "担心过：老师睡觉窗口到了" not in memory.lines():
            _fail(f"ended rumination should become arona memory, got {memory.lines()}")
        if "老师睡觉窗口到了" in json.dumps(memory.slots, ensure_ascii=False) and any(
            line.startswith("担心过") for line in memory.lines()
        ):
            pass
        stamp = now - timedelta(hours=25)
        journal.entries.insert(
            0,
            journal.entries[0].__class__(at=stamp, kind="shift", summary="很早以前发过呆"),
        )
        for i in range(MAX_ENTRIES + 5):
            journal.append("glance", f"看见窗口{i}", now + timedelta(seconds=i + 2))
        if len(journal.entries) != MAX_ENTRIES:
            _fail(f"ring should keep {MAX_ENTRIES}, got {len(journal.entries)}")
        if journal.contains_text("很早以前发过呆"):
            _fail("entries older than 24h should drop")
        if journal.contains_text(teacher_line) or journal.contains_text(crisis_line):
            _fail("ring still holds forbidden text")
    print("  ok")


def test_stale_care_rumination_expires() -> None:
    print("== care rumination ends with the window and the day ==")
    from app.life.impulse import without_stale_care

    windows = {
        "breakfast": ("06:30", "08:00"),
        "lunch": ("11:30", "13:00"),
        "dinner": ("17:30", "19:00"),
        "sleep": ("23:00", "23:20"),
    }
    yesterday = datetime(2026, 9, 21, 23, 18, 22)
    afternoon = datetime(2026, 9, 22, 15, 2, 0)
    stale = InnerState(
        rumination=[
            Rumination(id="imp-sleep", content="老师睡觉窗口到了", created_at=yesterday),
            Rumination(id="imp-goal", content="老师还有未完成的计划", created_at=yesterday),
        ]
    )
    fresh = without_stale_care(stale, afternoon, windows)
    ids = [item.id for item in fresh.rumination]
    if "imp-sleep" in ids:
        _fail("yesterday's sleep worry should expire")
    if "imp-goal" not in ids:
        _fail("goal rumination is not a care window")
    block = format_interrupt_block(fresh)
    if "老师睡觉窗口到了" in block:
        _fail("expired care worry must not reach the planner")
    during = datetime(2026, 9, 21, 23, 10, 0)
    live = without_stale_care(
        InnerState(
            rumination=[
                Rumination(id="imp-sleep", content="老师睡觉窗口到了", created_at=during)
            ]
        ),
        during,
        windows,
    )
    if not any(item.id == "imp-sleep" for item in live.rumination):
        _fail("sleep worry should stay inside today's window")
    after = datetime(2026, 9, 21, 23, 25, 0)
    closed = without_stale_care(live, after, windows)
    if closed.rumination:
        _fail("sleep worry should end when the window closes")
    print("  ok")


def test_glance_gate_and_hands() -> None:
    print("== glance gate and using_computer stay through rest ==")
    from app.life.glance import glance_allowed
    from app.life.hands import teacher_turn_aborts_hands
    from app.planner.client import _glance_seen

    now = _afternoon()
    recent = now - timedelta(minutes=10)
    common = dict(
        now=now,
        interval_sec=1200,
        activity="idle_in_classroom",
        attention="diffuse",
        climate="steady",
        busy=False,
    )
    if glance_allowed(last_at=recent, listening=False, **common):
        _fail("interval not elapsed should block glance")
    if glance_allowed(last_at=recent, listening=True, **common):
        _fail("listening must not shorten the glance interval")
    if not glance_allowed(last_at=None, listening=True, **common):
        _fail("listening alone should not block a due glance")
    if glance_allowed(
        last_at=None,
        activity="looking_at_teacher",
        attention="teacher",
        **{k: v for k, v in common.items() if k not in {"activity", "attention"}},
    ):
        _fail("looking at teacher should block glance")
    if glance_allowed(last_at=None, climate="fragile", **{k: v for k, v in common.items() if k != "climate"}):
        _fail("fragile climate should block glance")
    if glance_allowed(
        last_at=None,
        activity="using_computer",
        **{k: v for k, v in common.items() if k != "activity"},
    ):
        _fail("hands should block glance")
    if _glance_seen('{"seen":"看不清窗口"}'):
        _fail("uncertain glance must be dropped")
    if _glance_seen('{"seen":"我想死"}'):
        _fail("crisis glance must be dropped")
    if _glance_seen('{"seen":"记事本开着"}') != "记事本开着":
        _fail("checkable glance line should be kept")
    if not teacher_turn_aborts_hands("computer_use"):
        _fail("teacher turn should abort computer use")
    if teacher_turn_aborts_hands("chat"):
        _fail("ordinary chat is not a hands abort")
    hands = InnerState(activity="using_computer", attention="self", private_mood="calm")
    stayed = decide(hands, world_event("clock_tick", at=_night()), settings=_settings())
    _assert_not_speak(stayed)
    if stayed.state.activity != "using_computer":
        _fail(f"night tick must not yank hands, got {stayed.state.activity}")
    if stayed.action != "continue_activity":
        _fail(f"hands tick action {stayed.action}")
    block = format_interrupt_block(hands)
    if "操作电脑" not in block:
        _fail(block)
    print("  ok")


def main() -> None:
    test_json_roundtrip_isolated_from_relationship()
    test_look_hold_decays_to_idle()
    test_rest_slots_and_leave()
    test_rumination_thinking_then_idle()
    test_impulse_due_without_pending_does_not_speak()
    test_care_impulse_simmers_then_speaks()
    test_same_kind_keeps_impulse_timer()
    test_listen_on_does_not_block_impulse()
    test_idle_impulse_over_thinking_is_emotion_only()
    test_goal_withhold_drops_without_mark_fired()
    test_listen_on_does_not_freeze_ticks()
    test_engine_ticks_never_speak_or_chat()
    test_loop_tick_once_with_fake_state()
    test_presence_emotion_mapping()
    test_msg_presence_has_no_content()
    test_presence_publish_change_busy_and_listen()
    test_snapshot_before_apply_and_interrupt_keeps_thinking()
    test_journal_skips_crisis_and_teacher_text()
    test_stale_care_rumination_expires()
    test_glance_gate_and_hands()
    print("all life unit tests passed")


if __name__ == "__main__":
    main()
