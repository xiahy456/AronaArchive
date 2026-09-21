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

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.life import (  # noqa: E402
    InnerState,
    LifeEngine,
    LifeSettings,
    LifeStore,
    PresenceGate,
    Rumination,
    decide,
    presence_emotion,
    publish_presence,
    world_event,
)
from app.life.loop import tick_once  # noqa: E402
from app.life.policy import LifeDecision  # noqa: E402
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


def test_impulse_due_ignored() -> None:
    print("== impulse_due does not change activity or speak ==")
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
        fake = SimpleNamespace(
            life=engine,
            orchestrator=SimpleNamespace(relationship=None),
            config=SimpleNamespace(proactive=SimpleNamespace(relationship=None)),
        )
        tick_once(fake, now=_afternoon())
        if engine.state.activity not in {"idle_in_classroom", "resting"}:
            _fail(engine.state.activity)
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


def main() -> None:
    test_json_roundtrip_isolated_from_relationship()
    test_look_hold_decays_to_idle()
    test_rest_slots_and_leave()
    test_rumination_thinking_then_idle()
    test_impulse_due_ignored()
    test_listen_on_does_not_freeze_ticks()
    test_engine_ticks_never_speak_or_chat()
    test_loop_tick_once_with_fake_state()
    test_presence_emotion_mapping()
    test_msg_presence_has_no_content()
    test_presence_publish_change_busy_and_listen()
    print("all life unit tests passed")


if __name__ == "__main__":
    main()
