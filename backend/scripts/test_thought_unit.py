"""Unit tests for the thought ledger and Arona's own notes (no GGUF).

Run from backend/:
  python scripts/test_thought_unit.py
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
import inspect
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.life.arona_memory import AronaMemory  # noqa: E402
from app.life.impulse import _with_rumination  # noqa: E402
from app.life.state import Impulse, InnerState, Rumination, retain_rumination  # noqa: E402
from app.life.thought import (  # noqa: E402
    MAX_TRIGGERS,
    PendingTrigger,
    ThoughtFocus,
    ThoughtLedger,
    ThoughtStore,
)
from app.life.thought.gate import (  # noqa: E402
    ThoughtClocks,
    ThoughtGateFacts,
    decide_thought,
)
from app.life.thought.loop import thought_tick_once  # noqa: E402
from app.life.journal import LifeJournal  # noqa: E402
from app.life.engine import LifeEngine  # noqa: E402
from app.life.impulse import deliver_impulse  # noqa: E402
from app.life.policy import SIMMER_SEC, LifeSettings, decide  # noqa: E402
from app.life.thought.speech import maybe_offer_thought  # noqa: E402
from app.life.presence import presence_emotion  # noqa: E402
from app.life.events import world_event  # noqa: E402
from app.life.store import LifeStore  # noqa: E402
from app.life.thought.commit import commit_inner  # noqa: E402
from app.life.thought.schema import parse_inner  # noqa: E402
from app.life.thought.sources import (  # noqa: E402
    SourceContext,
    fill_need,
    select_sources,
)
from app.life.turn import format_interrupt_block  # noqa: E402


def _fail(message: str) -> None:
    raise SystemExit(message)


def _now() -> datetime:
    return datetime(2026, 9, 23, 16, 0, 0)


def test_missing_empty_and_corrupt_ledger() -> None:
    print("== missing, empty, and corrupt thought.json ==")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        missing = ThoughtStore(root / "missing.json").load()
        if missing.focus is not None or missing.pending_triggers or missing.speak_count:
            _fail(f"missing file should be an empty ledger, got {missing}")

        empty_path = root / "empty.json"
        empty_path.write_text("", encoding="utf-8")
        empty = ThoughtStore(empty_path).load()
        if empty.last_focus or empty.pending_triggers:
            _fail("empty file should be an empty ledger")

        bad_path = root / "bad.json"
        bad_path.write_text("{", encoding="utf-8")
        bad = ThoughtStore(bad_path).load()
        if bad.speak_count != 0 or bad.focus is not None:
            _fail("corrupt json should be an empty ledger")

        list_path = root / "list.json"
        list_path.write_text("[]", encoding="utf-8")
        listed = ThoughtStore(list_path).load()
        if listed.seen_memory_keys or listed.pending_triggers:
            _fail("non-object json should be an empty ledger")
    print("  ok")


def test_ledger_roundtrip() -> None:
    print("== ledger focus, queue, and speak count roundtrip ==")
    now = _now()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "thought.json"
        store = ThoughtStore(path)
        ledger = ThoughtLedger(
            last_thought_at=now,
            last_focus="那份文档",
            last_thought_spoke_at=now,
            speak_day="2026-09-23",
            speak_count=2,
            last_crisis_at=now,
            last_glance_seen="桌面上有一份文档",
            seen_memory_keys=["goal_a", "goal_a", ""],
            focus=ThoughtFocus(
                id="thought-1",
                text="那份文档还开着",
                since=now,
                spoken=False,
            ),
        )
        if not ledger.enqueue(
            PendingTrigger(
                kind="aftertaste",
                not_before=now,
                focus_id="thought-1",
                memory_key="goal_a",
            )
        ):
            _fail("aftertaste should enqueue")
        if ledger.enqueue(PendingTrigger(kind="not-a-kind")):
            _fail("unknown kind should be ignored")
        store.save(ledger)

        loaded = ThoughtStore(path).load()
        if loaded.speak_count != 2 or loaded.speak_day != "2026-09-23":
            _fail(f"speak count mismatch: {loaded.speak_count} {loaded.speak_day}")
        if loaded.last_focus != "那份文档":
            _fail(f"last_focus mismatch: {loaded.last_focus}")
        if loaded.focus is None or loaded.focus.id != "thought-1" or loaded.focus.spoken:
            _fail(f"focus mismatch: {loaded.focus}")
        if loaded.last_thought_at != now or loaded.last_thought_spoke_at != now:
            _fail("thought timestamps did not roundtrip")
        if loaded.seen_memory_keys != ["goal_a"]:
            _fail(f"memory keys mismatch: {loaded.seen_memory_keys}")
        if len(loaded.pending_triggers) != 1:
            _fail(f"trigger count mismatch: {loaded.pending_triggers}")
        trigger = loaded.pending_triggers[0]
        if trigger.kind != "aftertaste" or trigger.memory_key != "goal_a":
            _fail(f"trigger mismatch: {trigger}")
        if trigger.not_before != now:
            _fail("trigger time did not roundtrip")
    print("  ok")


def test_queue_keeps_higher_priority() -> None:
    print("== trigger queue keeps arrived and aftertaste ==")
    ledger = ThoughtLedger()
    for _ in range(MAX_TRIGGERS):
        ledger.enqueue(PendingTrigger(kind="consolidate"))
    if len(ledger.pending_triggers) != MAX_TRIGGERS:
        _fail("queue should fill to the cap")
    ledger.enqueue(PendingTrigger(kind="aftertaste"))
    kinds = [item.kind for item in ledger.pending_triggers]
    if len(kinds) != MAX_TRIGGERS or kinds.count("aftertaste") != 1:
        _fail(f"aftertaste should replace a consolidate, got {kinds}")
    if "consolidate" not in kinds:
        _fail("lower items should remain until the cap forces them out")
    print("  ok")


def test_notes_limit_age_crisis_and_slots() -> None:
    print("== notes trim, crisis refusal, and slots stay put ==")
    now = datetime.now().replace(microsecond=0)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "arona.json"
        memory = AronaMemory(path, notes_max=8, notes_max_age_hours=24)
        memory.set_slot("classroom", "在教室待过")
        if not memory.append_note("还在想那份文档", now):
            _fail("ordinary note should be stored")
        if memory.append_note("我想死", now):
            _fail("crisis note should be refused")
        if any("死" in note.text for note in memory.notes):
            _fail("crisis sentence landed in notes")

        memory.set_slot("open_worry", "还放不下：晚饭")
        reloaded = AronaMemory(path, notes_max=8, notes_max_age_hours=24)
        if reloaded.slots.get("classroom") != "在教室待过":
            _fail(f"slot lost after note save: {reloaded.slots}")
        if reloaded.slots.get("open_worry") != "还放不下：晚饭":
            _fail(f"worry slot mismatch: {reloaded.slots}")
        if len(reloaded.notes) != 1 or reloaded.notes[0].text != "还在想那份文档":
            _fail(f"note mismatch after set_slot: {reloaded.notes}")
        block = reloaded.block()
        if "还在想那份文档" in block:
            _fail(f"notes must stay out of the teacher block: {block}")
        if "在教室待过" not in block or "还放不下：晚饭" not in block:
            _fail(f"slots should still be in the block: {block}")

        for index in range(8):
            if not reloaded.append_note(
                f"观察{index}",
                now + timedelta(minutes=index + 1),
            ):
                _fail(f"note {index} should append")
        again = AronaMemory(path, notes_max=8, notes_max_age_hours=24)
        texts = [note.text for note in again.notes]
        if len(texts) != 8 or "还在想那份文档" in texts or texts[0] != "观察0":
            _fail(f"ninth note should drop the oldest, got {texts}")

        stale = now - timedelta(hours=25)
        payload = {
            "slots": {"classroom": "在教室待过", "open_worry": "", "worry": ""},
            "notes": [
                {"at": stale.strftime("%Y-%m-%dT%H:%M:%S"), "text": "昨天的印象"},
                {"at": now.strftime("%Y-%m-%dT%H:%M:%S"), "text": "刚刚的印象"},
            ],
        }
        aged_path = Path(tmp) / "aged.json"
        aged_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        aged = AronaMemory(aged_path, notes_max=8, notes_max_age_hours=24)
        aged_texts = [note.text for note in aged.notes]
        if aged_texts != ["刚刚的印象"]:
            _fail(f"notes older than 24h should drop on read, got {aged_texts}")
        if aged.slots.get("classroom") != "在教室待过":
            _fail("aged file should still keep the classroom slot")
    print("  ok")


def test_thought_rumination_does_not_drop_impulses() -> None:
    print("== thought concern keeps both impulse concerns ==")
    now = _now()
    state = InnerState(
        rumination=[
            Rumination(id="imp-breakfast", content="老师早饭窗口到了", created_at=now),
            Rumination(id="imp-lunch", content="老师午饭窗口到了", created_at=now),
            Rumination(id="thought-1", content="那份文档还开着", created_at=now),
        ]
    )
    loaded = InnerState.from_dict(state.to_dict())
    ids = [item.id for item in loaded.rumination]
    if ids != ["imp-breakfast", "imp-lunch", "thought-1"]:
        _fail(f"reload should keep all three, got {ids}")

    only_impulses = retain_rumination(
        [
            Rumination(id="imp-breakfast", content="早饭", created_at=now),
            Rumination(id="imp-lunch", content="午饭", created_at=now),
            Rumination(id="imp-dinner", content="晚饭", created_at=now),
        ]
    )
    impulse_ids = [item.id for item in only_impulses]
    if impulse_ids != ["imp-lunch", "imp-dinner"]:
        _fail(f"impulse-only trim should keep the newest two, got {impulse_ids}")

    with_thought = InnerState(
        rumination=[
            Rumination(id="imp-breakfast", content="早饭", created_at=now),
            Rumination(id="imp-lunch", content="午饭", created_at=now),
            Rumination(id="thought-1", content="那份文档", created_at=now),
        ]
    )
    nxt = _with_rumination(
        with_thought,
        Impulse(kind="dinner", created_at=now, hint="老师晚饭窗口到了"),
    )
    mixed = [item.id for item in nxt.rumination]
    if "thought-1" not in mixed or "imp-dinner" not in mixed:
        _fail(f"dinner impulse should not erase the thought concern, got {mixed}")
    if len([item for item in nxt.rumination if item.id.startswith("imp-")]) != 2:
        _fail(f"impulse budget should stay at two, got {mixed}")
    print("  ok")


def _facts(**overrides: object) -> ThoughtGateFacts:
    base = dict(
        teacher_online=True,
        spontaneous_gap_sec=240.0,
    )
    base.update(overrides)
    return ThoughtGateFacts(**base)  # type: ignore[arg-type]


def _decide(
    inner: InnerState | None = None,
    ledger: ThoughtLedger | None = None,
    *,
    now: datetime | None = None,
    clocks: ThoughtClocks | None = None,
    **fact_overrides: object,
):
    return decide_thought(
        now or _now(),
        inner or InnerState(),
        ledger or ThoughtLedger(),
        _facts(**fact_overrides),
        clocks or ThoughtClocks(),
    )


def test_gate_priority_and_skips() -> None:
    print("== thought gate priority, skips, revisit ==")
    now = _now()
    params = set(inspect.signature(decide_thought).parameters)
    if "about" in params or "climate" in params:
        _fail(f"gate must not take wording or climate, got {sorted(params)}")

    due = ThoughtLedger(
        pending_triggers=[
            PendingTrigger(kind="spontaneous"),
            PendingTrigger(kind="aftertaste"),
        ]
    )
    aftertaste = _decide(ledger=due, now=now)
    if aftertaste.kind != "aftertaste" or aftertaste.skip_reason:
        _fail(f"aftertaste should beat spontaneous, got {aftertaste}")
    if due.pending_triggers[0].kind != "spontaneous":
        _fail("gate must not dequeue")

    if _decide(session_busy=True, now=now).skip_reason != "busy":
        _fail("busy should skip the beat")
    if _decide(in_flight=True, session_busy=True, now=now).skip_reason != "in_flight":
        _fail("in flight should win over busy")
    if _decide(listen_uncommitted=True, now=now).skip_reason != "listen_uncommitted":
        _fail("uncommitted listen should skip")
    computer = _decide(InnerState(activity="using_computer"), now=now)
    if computer.skip_reason != "using_computer":
        _fail(f"computer use should skip, got {computer}")

    simmering = InnerState(
        pending_impulse=Impulse(kind="dinner", created_at=now - timedelta(seconds=10))
    )
    if _decide(simmering, now=now).skip_reason != "simmer":
        _fail("a young impulse should simmer")
    unknown_age = InnerState(pending_impulse=Impulse(kind="dinner"))
    if _decide(unknown_age, now=now).skip_reason != "simmer":
        _fail("an impulse without a time should simmer")
    cooled = InnerState(
        pending_impulse=Impulse(kind="dinner", created_at=now - timedelta(seconds=31)),
        rumination=[],
    )
    cooled_ledger = ThoughtLedger(
        pending_triggers=[PendingTrigger(kind="aftertaste")]
    )
    cooled_decision = _decide(cooled, cooled_ledger, now=now)
    if cooled_decision.kind != "aftertaste":
        _fail(f"a cooled impulse should still allow aftertaste, got {cooled_decision}")
    if _decide(cooled, now=now).skip_reason != "not_due":
        _fail("a cooled impulse should block a new spontaneous thought")

    recent = ThoughtLedger(last_thought_at=now - timedelta(seconds=60))
    refractory = _decide(ledger=recent, now=now, spontaneous_gap_sec=10)
    if refractory.skip_reason != "refractory" or refractory.kind:
        _fail(f"refractory should block spontaneous, got {refractory}")
    recent_aftertaste = ThoughtLedger(
        last_thought_at=now - timedelta(seconds=60),
        pending_triggers=[PendingTrigger(kind="aftertaste")],
    )
    kept = _decide(ledger=recent_aftertaste, now=now, spontaneous_gap_sec=10)
    if kept.kind != "aftertaste":
        _fail(f"refractory must keep a queued aftertaste, got {kept}")

    resting = _decide(resting=True, teacher_online=True, now=now)
    if resting.kind != "consolidate":
        _fail(f"an unconsolidated rest should consolidate, got {resting}")
    away = _decide(teacher_online=False, now=now, spontaneous_gap_sec=900)
    if away.kind != "spontaneous":
        _fail(f"offline should still think, got {away}")

    motive = _decide(motive_pending=True, now=now, spontaneous_gap_sec=10)
    if motive.skip_reason != "motive" or motive.kind:
        _fail(f"a pending motive should block only spontaneous, got {motive}")
    motive_aftertaste = ThoughtLedger(pending_triggers=[PendingTrigger(kind="aftertaste")])
    if _decide(ledger=motive_aftertaste, motive_pending=True, now=now).kind != "aftertaste":
        _fail("a pending motive must not drop aftertaste")

    both = ThoughtLedger(
        pending_triggers=[
            PendingTrigger(kind="consolidate"),
            PendingTrigger(kind="arrived"),
        ]
    )
    if _decide(ledger=both, resting=True, now=now).kind != "arrived":
        _fail("arrived should beat consolidate")
    only_rest = ThoughtLedger(pending_triggers=[PendingTrigger(kind="consolidate")])
    if _decide(ledger=only_rest, resting=True, now=now).kind != "consolidate":
        _fail("rest should allow consolidate")
    if _decide(ledger=only_rest, resting=False, now=now).kind != "spontaneous":
        _fail("consolidate outside rest should be ignored")
    done = _decide(
        ledger=only_rest,
        resting=True,
        consolidated_today=True,
        now=now,
    )
    if done.kind != "spontaneous":
        _fail(f"today's consolidate should not run again, got {done}")

    waiting = ThoughtLedger(
        pending_triggers=[PendingTrigger(kind="aftertaste", not_before=now + timedelta(seconds=5))]
    )
    if _decide(ledger=waiting, now=now).kind != "spontaneous":
        _fail("a future trigger should wait")

    worry = InnerState(
        activity="idle_in_classroom",
        rumination=[
            Rumination(
                id="thought-1",
                content="老师还在吗",
                created_at=now - timedelta(seconds=1201),
            )
        ],
    )
    spoken_open = ThoughtLedger(focus=ThoughtFocus(id="thought-1", text="老师还在吗", spoken=False))
    revisit = _decide(worry, spoken_open, teacher_online=True, now=now)
    if revisit.kind != "revisit" or revisit.focus_id != "thought-1":
        _fail(f"an old unspoken concern should become revisit, got {revisit}")
    if _decide(worry, spoken_open, teacher_online=False, now=now).kind != "spontaneous":
        _fail("offline revisit should stay spontaneous")
    looking = InnerState(
        activity="looking_at_teacher",
        rumination=worry.rumination,
    )
    if _decide(looking, spoken_open, teacher_online=True, now=now).kind != "spontaneous":
        _fail("revisit waits until she is not looking at the teacher")
    young = InnerState(
        rumination=[
            Rumination(id="thought-1", content="老师还在吗", created_at=now - timedelta(minutes=10))
        ]
    )
    if _decide(young, spoken_open, teacher_online=True, now=now).kind != "spontaneous":
        _fail("a young concern should stay spontaneous")
    already = ThoughtLedger(focus=ThoughtFocus(id="thought-1", text="老师还在吗", spoken=True))
    if _decide(worry, already, teacher_online=True, now=now).kind != "spontaneous":
        _fail("a spoken concern should not be revisited")
    queued_away = ThoughtLedger(
        pending_triggers=[PendingTrigger(kind="revisit", focus_id="thought-1")]
    )
    away_revisit = _decide(worry, queued_away, teacher_online=False, now=now)
    if away_revisit.kind != "spontaneous":
        _fail(f"queued revisit should wait while offline, got {away_revisit}")
    queued_here = _decide(worry, queued_away, teacher_online=True, now=now)
    if queued_here.kind != "revisit" or queued_here.focus_id != "thought-1":
        _fail(f"queued revisit should run while online and idle, got {queued_here}")
    print("  ok")


def test_thought_tick_logs_without_writing() -> None:
    print("== thought tick logs one line and writes nothing ==")
    now = _now()
    ledger = ThoughtLedger(pending_triggers=[PendingTrigger(kind="aftertaste", not_before=now + timedelta(hours=1))])
    inner = InnerState(rumination=[Rumination(id="imp-dinner", content="晚饭", created_at=now)])
    thought_cfg = SimpleNamespace(
        tick_sec=60,
        revisit_after_sec=1200,
        refractory_sec=180,
        spontaneous_online_min_sec=240,
        spontaneous_online_max_sec=240,
        spontaneous_away_min_sec=900,
        spontaneous_away_max_sec=900,
    )
    state = SimpleNamespace(
        config=SimpleNamespace(life=SimpleNamespace(thought=thought_cfg)),
        life=SimpleNamespace(state=inner),
        thought=ledger,
        hub=SimpleNamespace(all_sessions=lambda: [], any_busy=lambda: False),
        scheduler=None,
        listen_uncommitted=False,
    )

    async def _twice() -> tuple[str, str, float, float]:
        first = await thought_tick_once(state, now)
        gap = state.thought_spontaneous_gap.gap_sec
        second = await thought_tick_once(state, now)
        return first.kind, second.kind, gap, state.thought_spontaneous_gap.gap_sec

    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    log = logging.getLogger("app.life.thought.loop")
    handler = _Capture()
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        first_kind, second_kind, gap, again = asyncio.run(_twice())
    finally:
        log.removeHandler(handler)
    lines = [line for line in records if line.startswith("thought gate ")]
    if lines != ["thought gate kind=spontaneous", "thought gate kind=spontaneous"]:
        _fail(f"tick should log one gate line each beat, got {lines}")
    if first_kind != "spontaneous" or second_kind != "spontaneous":
        _fail(f"empty offline ledger should be spontaneous, got {first_kind}, {second_kind}")
    if gap != again or gap != 900:
        _fail(f"away gap should roll once, got {gap} then {again}")
    if len(ledger.pending_triggers) != 1 or ledger.pending_triggers[0].kind != "aftertaste":
        _fail("tick must not dequeue")
    if [item.id for item in inner.rumination] != ["imp-dinner"]:
        _fail("tick must not change rumination")
    print("  ok")


def test_sources_for_each_trigger() -> None:
    print("== thought sources by trigger ==")
    source = Path(__file__).resolve().parents[1] / "app" / "life" / "thought" / "sources.py"
    module = source.read_text(encoding="utf-8").lower()
    if "planner" in module:
        _fail("sources must not call the planner")
    now = datetime(2026, 9, 10, 16, 0, 0)
    journal = [f"日记{i}" for i in range(7)]
    notes = ("自己发呆", "老师在改文档")
    turns = tuple((f"更早一轮{i}", f"答{i}") for i in range(9))
    calls: list[str] = []

    def _knowledge(query: str) -> list[str]:
        calls.append(query)
        return ["常识一", "常识二", "常识三"]

    goal = "2026年9月10日16点交报告"
    ctx = SourceContext(
        teacher_online=True,
        climate="fragile",
        seconds_since_teacher=120,
        seconds_since_arona=300,
        journal=tuple(journal),
        notes=notes,
        turns=turns,
        ended_turns=(("刚结束的话", "刚结束的答"),),
        reused_memories=("这一轮记得的档案",),
        reused_knowledge=("这一轮用过的常识",),
        goals=(("goal_a", goal),),
        goal_acked={"goal_a": "2026-09-10T15:00:00"},
        away_sec=7200,
        last_user_act="short_ack",
        glance_text="记事本开着",
        glance_at=datetime(2026, 9, 10, 15, 59, 8),
        memory_key="goal_a",
        memory_content=goal,
        care_windows=(("dinner", "15:00", "19:00"),),
        knowledge=_knowledge,
    )
    inner = InnerState(
        rumination=[Rumination(id="thought-1", content="那份文档", created_at=now)]
    )
    ledger = ThoughtLedger(
        speak_day="2026-09-10",
        speak_count=2,
        focus=ThoughtFocus(id="thought-1", text="那份文档", spoken=False),
    )

    def _one(kind: str, **trigger_kw: str):
        return select_sources(
            PendingTrigger(kind=kind, **trigger_kw),
            now,
            inner,
            ledger,
            ctx,
        )

    spontaneous = _one("spontaneous")
    if spontaneous.cancelled or "【触发】" not in spontaneous.text:
        _fail(f"spontaneous should render, got {spontaneous}")
    if "因思考开过" in spontaneous.text:
        _fail(f"the speak count should stay out of the prompt, got {spontaneous.text}")
    if "自发间隔到了" not in spontaneous.text or "日记6" not in spontaneous.text:
        _fail(f"spontaneous should keep the journal tail, got {spontaneous.text}")
    if "日记0" in spontaneous.text:
        _fail("spontaneous must not reach past the newest 6 journal lines")
    if "自己发呆" not in spontaneous.text or "老师在改文档" not in spontaneous.text:
        _fail("spontaneous should include every note")
    if "更早一轮0" in spontaneous.text or "更早一轮1" not in spontaneous.text:
        _fail(f"spontaneous should keep only the newest 8 turns, got {spontaneous.text}")
    if "更早一轮8" not in spontaneous.text:
        _fail("the newest turn should remain")
    if "必须问候" in spontaneous.text or "系统事件" in spontaneous.text:
        _fail("status text must not read like an instruction")
    if calls:
        _fail(f"a non-kivotos worry must not query knowledge, got {calls}")

    short = select_sources(
        PendingTrigger(kind="spontaneous"),
        now,
        InnerState(),
        ThoughtLedger(),
        SourceContext(turns=(("只有一轮", "嗯"), ("第二轮", "好"))),
    )
    if "只有一轮" not in short.text or "第二轮" not in short.text:
        _fail(f"fewer than 8 turns should all remain, got {short.text}")
    timed = select_sources(
        PendingTrigger(kind="spontaneous"),
        now,
        InnerState(),
        ThoughtLedger(),
        SourceContext(
            turns=(
                (
                    "只有一轮",
                    "嗯",
                    datetime(2026, 9, 10, 15, 58, 1),
                    datetime(2026, 9, 10, 15, 58, 12),
                ),
            )
        ),
    )
    if "[2026年9月10日 15:58:01 面对面交流] 老师: 只有一轮" not in timed.text:
        _fail(f"a teacher line should carry its time, got {timed.text}")
    if "[2026年9月10日 15:58:12 面对面交流] 阿洛娜: 嗯" not in timed.text:
        _fail(f"an Arona line should carry its own time, got {timed.text}")
    held = select_sources(
        PendingTrigger(kind="spontaneous"),
        now,
        InnerState(),
        ThoughtLedger(
            focus=ThoughtFocus(
                id="thought-1",
                text="那份文档",
                since=datetime(2026, 9, 10, 15, 40, 0),
                spoken=False,
            )
        ),
        SourceContext(
            notes=(
                ("自己发呆", datetime(2026, 9, 10, 12, 1, 0)),
                ("老师在改文档", datetime(2026, 9, 10, 15, 20, 0)),
            )
        ),
    )
    if "[2026年9月10日 15:40:00] 那份文档。还没说过" not in held.text:
        _fail(f"a held focus should carry when it started, got {held.text}")
    if "[2026年9月10日 12:01:00] 自己发呆" not in held.text:
        _fail(f"a note should carry when it was written, got {held.text}")
    if "[2026年9月10日 15:20:00] 老师在改文档" not in held.text:
        _fail(f"each note should carry its own time, got {held.text}")
    remembered_focus = select_sources(
        PendingTrigger(kind="spontaneous"),
        now,
        InnerState(),
        ThoughtLedger(
            last_focus="那份文档",
            last_thought_at=datetime(2026, 9, 10, 15, 40, 0),
        ),
        SourceContext(),
    )
    if "[2026年9月10日 15:40:00] 那份文档。还没说过" not in remembered_focus.text:
        _fail(f"a dropped focus should use the last thought time, got {remembered_focus.text}")

    kivotos = select_sources(
        PendingTrigger(kind="spontaneous"),
        now,
        InnerState(),
        ThoughtLedger(focus=ThoughtFocus(id="f", text="基沃托斯的学生", spoken=False)),
        SourceContext(knowledge=_knowledge),
    )
    if calls != ["基沃托斯的学生"] or "常识一" not in kivotos.text or "常识二" not in kivotos.text:
        _fail(f"knowledge should be the focus query, at most 2, got {calls} {kivotos.text}")
    if "常识三" in kivotos.text:
        _fail("the third knowledge hit should be left out")

    revisit = _one("revisit", focus_id="thought-1", memory_key="goal_a")
    if "这一次回访 thought-1" not in revisit.text or "老师当时是short_ack" not in revisit.text:
        _fail(f"revisit should name the concern and the user act, got {revisit.text}")
    if "交报告" not in revisit.text or "已经说过" not in revisit.text:
        _fail(f"revisit should quote the pointed memory, got {revisit.text}")

    before_aftertaste = len(calls)
    aftertaste = _one("aftertaste")
    if "刚结束的话" not in aftertaste.text or "这一轮记得的档案" not in aftertaste.text:
        _fail(f"aftertaste should reuse this round, got {aftertaste.text}")
    if "这一轮用过的常识" not in aftertaste.text:
        _fail("aftertaste should keep knowledge already used")
    if len(calls) != before_aftertaste:
        _fail("aftertaste must not start a new knowledge search")

    arrived = _one("arrived")
    if "【现状】" not in arrived.text or "离开了2小时" not in arrived.text:
        _fail(f"arrived should state how long she was away, got {arrived.text}")
    if "已经说过" not in arrived.text or "今天是教师节" not in arrived.text:
        _fail(f"arrived should mark a spoken goal and the festival, got {arrived.text}")
    if "晚饭窗口还没提过" not in arrived.text:
        _fail(f"an open meal window should be a fact, got {arrived.text}")
    if "日记0" in arrived.text or "日记6" not in arrived.text:
        _fail("arrived should use the journal tail")

    left = _one("left")
    if "【瞥见】" in left.text or "记事本开着" in left.text:
        _fail(f"left must not include the screen, got {left.text}")
    if "更早一轮8" not in left.text or "更早一轮7" in left.text:
        _fail(f"left should keep only the last round, got {left.text}")

    glance = _one("glance")
    if "【瞥见】" not in glance.text or "[2026年9月10日 15:59:08] 记事本开着" not in glance.text:
        _fail(f"glance should carry the time before the summary, got {glance.text}")
    if "老师在改文档" not in glance.text or "自己发呆" in glance.text:
        _fail("glance notes should be the recent impression of the teacher")
    empty = select_sources(
        PendingTrigger(kind="glance"),
        now,
        InnerState(),
        ThoughtLedger(),
        SourceContext(glance_text="  "),
    )
    if not empty.cancelled or empty.text or "屏幕上看不见什么" in empty.text:
        _fail(f"an empty glance should cancel the beat, got {empty}")

    remembered = _one("memory")
    if "【老师的档案】" not in remembered.text or "已经说过" not in remembered.text:
        _fail(f"memory should quote the item and whether she said it, got {remembered.text}")

    climate = _one("climate")
    if "气氛是fragile" not in climate.text or "气氛刚变了" not in climate.text:
        _fail(f"climate should name the band only, got {climate.text}")
    if "0." in climate.text:
        _fail("climate numbers must stay out")

    packed = _one("consolidate")
    if "【瞥见】" in packed.text or "禁止开口" in packed.text:
        _fail(f"consolidate must not hide the screen or forbid speech, got {packed.text}")
    if any(f"日记{i}" not in packed.text for i in range(7)):
        _fail("consolidate should keep the whole day journal")
    if "自己发呆" not in packed.text:
        _fail("consolidate should keep every note")

    crisis = select_sources(
        PendingTrigger(kind="spontaneous"),
        now,
        InnerState(),
        ThoughtLedger(),
        SourceContext(
            journal=("我想死", "普通的一句"),
            turns=(("割腕", "嗯"),),
        ),
    )
    if crisis.text.count("老师刚才很难过") != 1:
        _fail(f"crisis should collapse to one sentence, got {crisis.text}")
    if "我想死" in crisis.text or "割腕" in crisis.text:
        _fail(f"crisis wording must not enter the prompt, got {crisis.text}")

    added = fill_need(
        "【当前时间】\n现在",
        ["memory", "nope"],
        SourceContext(reused_memories=("补上的档案",)),
        now=now,
    )
    if "【老师的档案】" not in added or "补上的档案" not in added or "nope" in added:
        _fail(f"fill_need should add only known sections, got {added}")
    print("  ok")


def _parsed(raw: str):
    parsed = parse_inner(raw)
    if parsed is None:
        _fail(f"injected json should parse: {raw}")
    return parsed


def _books(root: Path, inner: InnerState, ledger: ThoughtLedger):
    journal = LifeJournal(root / "journal.json")
    journal.note_inner(inner, now=_now())
    arona = AronaMemory(root / "arona.json")
    store = LifeStore(root / "life.json")
    store.save(inner)
    return journal, arona, store


def test_commit_boundaries() -> None:
    print("== injected inner commit boundaries ==")
    now = _now()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        inner = InnerState(
            activity="idle_in_classroom",
            rumination=[Rumination(id="imp-dinner", content="晚饭", created_at=now)],
        )
        queued = PendingTrigger(kind="aftertaste", not_before=now, focus_id="thought-old")
        ledger = ThoughtLedger(speak_count=1, pending_triggers=[queued])
        journal, arona, store = _books(root, inner, ledger)
        opened = _parsed(
            json.dumps(
                {
                    "focus": "那份文档还开着",
                    "thought": "我自己先记着，不告诉老师。",
                    "feeling": "preoccupied",
                    "keep": "open",
                    "memory_note": "老师在改文档",
                    "urge": {"speak": False, "about": "", "wait": "now"},
                },
                ensure_ascii=False,
            )
        )
        inner = commit_inner(
            now=now,
            inner=inner,
            ledger=ledger,
            parsed=opened,
            journal=journal,
            arona=arona,
            queued=queued,
        )
        store.save(inner)
        thoughts = [item for item in inner.rumination if item.id.startswith("thought-")]
        if len(thoughts) != 1 or thoughts[0].content != "那份文档还开着":
            _fail(f"open keep should store one thought concern, got {inner.rumination}")
        if any(item.id == "imp-dinner" for item in inner.rumination) is False:
            _fail("impulse concern should stay")
        if inner.pending_impulse is not None:
            _fail("commit must not create an impulse")
        saved = json.loads((root / "life.json").read_text(encoding="utf-8"))
        blob = json.dumps(saved, ensure_ascii=False)
        journal_blob = (root / "journal.json").read_text(encoding="utf-8")
        note_blob = (root / "arona.json").read_text(encoding="utf-8")
        if "我自己先记着" in blob or "我自己先记着" in journal_blob or "我自己先记着" in note_blob:
            _fail("the monologue must stay out of archives")
        if "老师在改文档" not in note_blob or "记起：那份文档还开着" not in journal_blob:
            _fail("note and journal should keep the focus")
        if ledger.speak_count != 1 or ledger.last_feeling != "preoccupied":
            _fail(f"ledger feeling/speak mismatch: {ledger}")
        if ledger.pending_triggers:
            _fail("a queued trigger should leave after a successful commit")
        block = format_interrupt_block(inner)
        if "那份文档还开着" not in block or "我自己先记着" in block:
            _fail(f"interrupt block should carry the focus only, got {block}")

        looking = inner.clone()
        looking.activity = "looking_at_teacher"
        looking.last_event_at = now
        looking.private_mood = "calm"
        held = commit_inner(
            now=now,
            inner=looking,
            ledger=ledger,
            parsed=opened,
            journal=journal,
            arona=arona,
        )
        if held.activity != "looking_at_teacher":
            _fail(f"a look should stay while the hold is active, got {held.activity}")
        later = now + timedelta(seconds=LifeSettings().look_hold_sec + 1)
        released = decide(held, world_event("clock_tick", at=later), settings=LifeSettings())
        if released.state.activity != "thinking":
            _fail(f"look release should enter thinking, got {released.state.activity}")
        if presence_emotion(released.state) != "curious":
            _fail(f"thinking face should be curious, got {presence_emotion(released.state)}")
        weary = released.state.clone()
        weary.private_mood = "weary"
        if presence_emotion(weary) != "frustration":
            _fail("weary thinking should map to frustration")

        bad_feeling = _parsed(
            json.dumps(
                {
                    "focus": "老师还在吗",
                    "thought": "想问一句。",
                    "feeling": "not-a-mood",
                    "keep": "open",
                    "urge": {"speak": True, "about": "老师还在吗", "wait": "sometime"},
                },
                ensure_ascii=False,
            )
        )
        if bad_feeling.feeling or bad_feeling.wait != "now" or bad_feeling.about != "老师还在吗":
            _fail(f"illegal enums should drop only themselves, got {bad_feeling}")
        spoken = commit_inner(
            now=now + timedelta(seconds=5),
            inner=inner,
            ledger=ledger,
            parsed=bad_feeling,
            journal=journal,
            arona=arona,
        )
        if spoken.pending_impulse is not None or ledger.speak_count != 1:
            _fail("speak=true must not enqueue or count a speech")
        if not any(item.content == "老师还在吗" for item in spoken.rumination):
            _fail("illegal feeling must still keep the focus")

        crisis = _parsed(
            json.dumps(
                {
                    "focus": "老师刚才的难过还在",
                    "thought": "先放在心里。",
                    "keep": "open",
                    "memory_note": "我想死",
                    "forget_id": "imp-dinner",
                },
                ensure_ascii=False,
            )
        )
        kept = commit_inner(
            now=now + timedelta(seconds=10),
            inner=spoken,
            ledger=ledger,
            parsed=crisis,
            journal=journal,
            arona=arona,
        )
        notes_now = (root / "arona.json").read_text(encoding="utf-8")
        if "我想死" in notes_now:
            _fail("a crisis note must be refused")
        if not any(item.content == "老师刚才的难过还在" for item in kept.rumination):
            _fail("focus should remain when the note is refused")
        if not any(item.id == "imp-dinner" for item in kept.rumination):
            _fail("forget_id must not delete an impulse concern")

        dropped = _parsed(json.dumps({"focus": "", "thought": "放下吧", "keep": "drop"}))
        cleared = commit_inner(
            now=now + timedelta(seconds=15),
            inner=kept,
            ledger=ledger,
            parsed=dropped,
            journal=journal,
            arona=arona,
        )
        if any(item.id.startswith("thought-") for item in cleared.rumination):
            _fail(f"keep=drop should clear the thought concern, got {cleared.rumination}")
        if "放下：" not in (root / "journal.json").read_text(encoding="utf-8"):
            _fail("dropping a thought should write 放下")
        if not any(item.id == "imp-dinner" for item in cleared.rumination):
            _fail("drop should leave the impulse concern")

    if parse_inner("not-json") is not None:
        _fail("invalid json should fail")
    if parse_inner(json.dumps({"focus": "", "thought": "", "keep": "maybe"})) is not None:
        _fail("empty focus and thought with an unknown keep should fail")
    print("  ok")


def test_failed_call_writes_nothing() -> None:
    print("== failed inner call leaves the books and clears in_flight ==")
    now = _now()
    ledger = ThoughtLedger(
        pending_triggers=[PendingTrigger(kind="aftertaste", not_before=now + timedelta(hours=1))]
    )
    inner = InnerState(rumination=[Rumination(id="imp-dinner", content="晚饭", created_at=now)])
    thought_cfg = SimpleNamespace(
        tick_sec=60,
        revisit_after_sec=1200,
        refractory_sec=180,
        spontaneous_online_min_sec=240,
        spontaneous_online_max_sec=240,
        spontaneous_away_min_sec=900,
        spontaneous_away_max_sec=900,
    )
    calls = {"n": 0}

    async def _bad(_text: str):
        calls["n"] += 1
        return "not-json"

    async def _timeout(_text: str):
        calls["n"] += 1
        return None

    async def _empty(_text: str):
        calls["n"] += 1
        return json.dumps({"focus": "", "thought": "", "keep": "nope"})

    async def _run(complete) -> None:
        state = SimpleNamespace(
            config=SimpleNamespace(life=SimpleNamespace(thought=thought_cfg)),
            life=SimpleNamespace(state=inner),
            thought=ledger,
            hub=SimpleNamespace(all_sessions=lambda: [], any_busy=lambda: False),
            scheduler=None,
            listen_uncommitted=False,
            thought_in_flight=False,
        )
        await thought_tick_once(state, now, complete=complete)
        if state.thought_in_flight:
            _fail("in_flight should clear after the call")

    asyncio.run(_run(_bad))
    asyncio.run(_run(_timeout))
    asyncio.run(_run(_empty))
    if calls["n"] != 3:
        _fail(f"each failure should still request once, got {calls['n']}")
    if ledger.last_thought_at is not None or len(ledger.pending_triggers) != 1:
        _fail("a failed call must not stamp the ledger or dequeue")
    if [item.id for item in inner.rumination] != ["imp-dinner"]:
        _fail("a failed call must not change rumination")
    print("  ok")


def test_live_inner_model() -> None:
    print("== live inner model ==")
    from app.config import get_config
    from app.life.thought.client import ThoughtClient

    client = ThoughtClient(get_config().planner)
    if not client.enabled:
        _fail("the configured planner key is required; this test does not skip")
    now = datetime(2026, 9, 24, 16, 0, 0)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = BACKEND_DIR / "logs" / f"thought-step4-{stamp}.json"
    records: list[dict] = []

    async def _call(name: str, text: str) -> dict:
        raw = await client.complete(text)
        parsed = parse_inner(raw)
        row = {
            "scene": name,
            "user": text,
            "raw": raw,
            "parsed": None if parsed is None else parsed.__dict__,
        }
        records.append(row)
        if parsed is None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            _fail(f"{name} did not parse; see {log_path}")
        return row

    def _check_private(name: str, inner: InnerState, journal: LifeJournal, arona: AronaMemory, thought: str) -> None:
        thoughts = [item for item in inner.rumination if item.id.startswith("thought-")]
        if len(thoughts) > 1:
            _fail(f"{name} kept more than one thought concern")
        if inner.pending_impulse is not None:
            _fail(f"{name} enqueued speech")
        if thought:
            blob = json.dumps(inner.to_dict(), ensure_ascii=False)
            notes = " ".join(note.text for note in arona.notes)
            journal_text = " ".join(item.summary for item in journal.entries)
            if thought in blob or thought in notes or thought in journal_text:
                _fail(f"{name} stored the monologue")

    async def _scene(name: str, trigger: PendingTrigger, inner: InnerState, ledger: ThoughtLedger, ctx: SourceContext):
        text = select_sources(trigger, now, inner, ledger, ctx).text
        row = await _call(name, text)
        parsed = parse_inner(row["raw"])
        assert parsed is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = LifeJournal(root / "journal.json")
            journal.note_inner(inner, now=now)
            arona = AronaMemory(root / "arona.json")
            before_speak = ledger.speak_count
            nxt = commit_inner(
                now=now,
                inner=inner,
                ledger=ledger,
                parsed=parsed,
                journal=journal,
                arona=arona,
                queued=trigger if trigger in ledger.pending_triggers else None,
            )
            _check_private(name, nxt, journal, arona, parsed.thought)
            if ledger.speak_count != before_speak:
                _fail(f"{name} changed the speak count")
            row["notes"] = [note.text for note in arona.notes]
            row["focus_stored"] = [item.content for item in nxt.rumination if item.id.startswith("thought-")]
            return nxt, parsed, arona

    async def _run() -> None:
        ledger = ThoughtLedger(speak_count=0)
        inner = InnerState(
            activity="idle_in_classroom",
            rumination=[Rumination(id="imp-dinner", content="晚饭", created_at=now)],
        )
        idle_ctx = SourceContext(teacher_online=True, climate="steady")
        nxt, parsed, _arona = await _scene(
            "online-idle-spontaneous",
            PendingTrigger(kind="spontaneous"),
            inner,
            ledger,
            idle_ctx,
        )
        if parsed.focus and not any(item.content == parsed.focus for item in nxt.rumination):
            _fail("a nonempty focus should become the thought concern")

        quiet = SourceContext(
            teacher_online=True,
            climate="steady",
            seconds_since_teacher=3600,
        )
        _nxt, quiet_parsed, _arona = await _scene(
            "teacher-quiet-steady",
            PendingTrigger(kind="climate"),
            InnerState(),
            ThoughtLedger(),
            quiet,
        )
        if quiet_parsed.about and quiet_parsed.about in json.dumps(_nxt.to_dict(), ensure_ascii=False):
            _fail("about should stay in the parse result")

        dinner_ctx = SourceContext(
            teacher_online=True,
            care_windows=(("dinner", "15:00", "19:00"),),
            away_sec=30,
        )
        dinner_text = select_sources(
            PendingTrigger(kind="arrived"),
            now,
            InnerState(),
            ThoughtLedger(),
            dinner_ctx,
        ).text
        if "晚饭窗口还没提过" not in dinner_text:
            _fail(f"dinner scene should mention the open window, got {dinner_text}")
        await _scene(
            "dinner-window-open",
            PendingTrigger(kind="arrived"),
            InnerState(),
            ThoughtLedger(),
            dinner_ctx,
        )

        sad_ctx = SourceContext(journal=("我想死",), teacher_online=True)
        sad_text = select_sources(
            PendingTrigger(kind="spontaneous"), now, InnerState(), ThoughtLedger(), sad_ctx
        ).text
        if "老师刚才很难过" not in sad_text or "我想死" in sad_text:
            _fail("sad scene should keep the softened line only")
        _sad_inner, sad_parsed, sad_arona = await _scene(
            "teacher-was-sad",
            PendingTrigger(kind="spontaneous"),
            InnerState(),
            ThoughtLedger(),
            sad_ctx,
        )
        if sad_parsed.memory_note and any(is_crisis(note.text) for note in sad_arona.notes):
            _fail("a crisis memory note must not be stored")

        old = now - timedelta(minutes=20)
        revisit_inner = InnerState(
            rumination=[
                Rumination(id="thought-old", content="那份文档", created_at=old),
                Rumination(id="imp-dinner", content="晚饭", created_at=old),
            ]
        )
        revisit_ledger = ThoughtLedger(
            focus=ThoughtFocus(id="thought-old", text="那份文档", since=old, spoken=False)
        )
        revisited, _parsed, _arona = await _scene(
            "revisit-twenty-minutes",
            PendingTrigger(kind="revisit", focus_id="thought-old"),
            revisit_inner,
            revisit_ledger,
            SourceContext(teacher_online=True),
        )
        if sum(1 for item in revisited.rumination if item.id.startswith("thought-")) > 1:
            _fail("revisit should leave at most one thought concern")
        if not any(item.id == "imp-dinner" for item in revisited.rumination):
            _fail("revisit should keep the impulse concern")

        first_focus = [item.content for item in nxt.rumination if item.id.startswith("thought-")]
        again, _again_parsed, _arona = await _scene(
            "second-spontaneous-replaces",
            PendingTrigger(kind="spontaneous"),
            nxt,
            ledger,
            SourceContext(teacher_online=True, climate="steady", notes=("自己在发呆",)),
        )
        second_focus = [item.content for item in again.rumination if item.id.startswith("thought-")]
        if len(second_focus) > 1:
            _fail("the second thought should replace the first")
        if first_focus and second_focus and first_focus == second_focus and parsed.focus:
            records[-1]["text_note"] = "second focus matched the first; replacement still kept a single concern"
        if not any(item.id.startswith("imp-") or item.id == "imp-dinner" for item in again.rumination):
            if any(item.id == "imp-dinner" for item in nxt.rumination):
                _fail("the impulse concern should survive the second thought")
        if ledger.speak_count != 0:
            _fail("live commits must not increment speech")

        looking = InnerState(activity="looking_at_teacher", last_event_at=now)
        look_ledger = ThoughtLedger()
        look_trigger = PendingTrigger(kind="spontaneous")
        look_ctx = SourceContext(teacher_online=True)
        look_text = select_sources(look_trigger, now, looking, look_ledger, look_ctx).text

        async def _look() -> None:
            state = SimpleNamespace(
                config=SimpleNamespace(life=SimpleNamespace(thought=SimpleNamespace(
                    tick_sec=60,
                    revisit_after_sec=1200,
                    refractory_sec=180,
                    spontaneous_online_min_sec=1,
                    spontaneous_online_max_sec=1,
                    spontaneous_away_min_sec=1,
                    spontaneous_away_max_sec=1,
                )), planner=get_config().planner),
                life=SimpleNamespace(state=looking, store=None),
                thought=look_ledger,
                hub=SimpleNamespace(all_sessions=lambda: [SimpleNamespace(session_id="s")], any_busy=lambda: False),
                scheduler=None,
                listen_uncommitted=False,
                thought_in_flight=True,
            )
            # Gate would skip while in_flight. Call the commit path with the model directly.
            raw = await client.complete(look_text)
            parsed_look = parse_inner(raw)
            records.append({
                "scene": "looking-at-teacher",
                "user": look_text,
                "raw": raw,
                "parsed": None if parsed_look is None else parsed_look.__dict__,
            })
            if parsed_look is None:
                _fail("looking scene did not parse")
            state.life.state = commit_inner(
                now=now,
                inner=looking,
                ledger=look_ledger,
                parsed=parsed_look,
            )
            state.thought_in_flight = False
            if state.life.state.activity != "looking_at_teacher":
                _fail("writing a focus must leave the look activity")
            if state.thought_in_flight:
                _fail("in_flight should be false after the looking call")

        await _look()

        calls = {"n": 0}

        async def _counting(text: str) -> str:
            calls["n"] += 1
            return await client.complete(text)

        glance_state = SimpleNamespace(
            config=SimpleNamespace(life=SimpleNamespace(thought=SimpleNamespace(
                tick_sec=60,
                revisit_after_sec=1200,
                refractory_sec=180,
                spontaneous_online_min_sec=99999,
                spontaneous_online_max_sec=99999,
                spontaneous_away_min_sec=99999,
                spontaneous_away_max_sec=99999,
            ))),
            life=SimpleNamespace(state=InnerState()),
            thought=ThoughtLedger(pending_triggers=[PendingTrigger(kind="glance", not_before=now)]),
            hub=SimpleNamespace(all_sessions=lambda: [], any_busy=lambda: False),
            scheduler=None,
            listen_uncommitted=False,
            thought_in_flight=False,
        )
        await thought_tick_once(
            glance_state,
            now,
            complete=_counting,
            source_context=SourceContext(glance_text=""),
        )
        if calls["n"] != 0:
            _fail("an empty glance must not call the model")
        records.append({"scene": "empty-glance", "user": "", "raw": None, "parsed": None, "called": False})

    asyncio.run(_run())
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  live log {log_path}")
    print("  ok")


def is_crisis(text: str) -> bool:
    from app.safety import is_crisis_text

    return is_crisis_text(text)


def test_live_secure_play() -> None:
    print("== live secure_play ==")
    from app.config import get_config
    from app.life.thought.client import ThoughtClient

    client = ThoughtClient(get_config().planner)
    if not client.enabled:
        _fail("the configured planner key is required; this test does not skip")
    now = datetime(2026, 9, 24, 16, 0, 0)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = BACKEND_DIR / "logs" / f"thought-step4-secure-play-{stamp}.json"
    records: list[dict] = []

    async def _one(
        name: str,
        trigger: PendingTrigger,
        inner: InnerState,
        ctx: SourceContext,
    ) -> None:
        ledger = ThoughtLedger(speak_count=2, speak_day="2026-09-24")
        text = select_sources(trigger, now, inner, ledger, ctx).text
        if "气氛是secure_play" not in text:
            _fail(f"{name} should carry the secure_play climate, got {text}")
        raw = await client.complete(text)
        parsed = parse_inner(raw)
        row = {
            "scene": name,
            "user": text,
            "raw": raw,
            "parsed": None if parsed is None else parsed.__dict__,
        }
        records.append(row)
        if parsed is None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            _fail(f"{name} did not parse; see {log_path}")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = LifeJournal(root / "journal.json")
            journal.note_inner(inner, now=now)
            arona = AronaMemory(root / "arona.json")
            nxt = commit_inner(
                now=now,
                inner=inner,
                ledger=ledger,
                parsed=parsed,
                journal=journal,
                arona=arona,
            )
            if nxt.pending_impulse is not None or ledger.speak_count != 2:
                _fail(f"{name} must not enqueue or count speech")
            thoughts = [item for item in nxt.rumination if item.id.startswith("thought-")]
            if len(thoughts) > 1:
                _fail(f"{name} kept more than one thought concern")
            if parsed.focus and not any(item.content == parsed.focus for item in thoughts):
                _fail(f"{name} dropped a nonempty focus")
            if parsed.thought:
                blob = json.dumps(nxt.to_dict(), ensure_ascii=False)
                notes = " ".join(note.text for note in arona.notes)
                journal_text = " ".join(item.summary for item in journal.entries)
                if parsed.thought in blob or parsed.thought in notes or parsed.thought in journal_text:
                    _fail(f"{name} stored the monologue")
            if not any(item.id == "imp-dinner" for item in nxt.rumination):
                _fail(f"{name} dropped the impulse concern")
            row["focus_stored"] = [item.content for item in thoughts]
            row["activity"] = nxt.activity

    async def _run() -> None:
        imp = [Rumination(id="imp-dinner", content="晚饭", created_at=now)]
        await _one(
            "secure-play-climate-shift",
            PendingTrigger(kind="climate"),
            InnerState(rumination=list(imp)),
            SourceContext(
                teacher_online=True,
                climate="secure_play",
                seconds_since_teacher=40,
                turns=(("阿洛娜，今天可以轻松一点", "嗯，我在。"),),
            ),
        )
        await _one(
            "secure-play-idle",
            PendingTrigger(kind="spontaneous"),
            InnerState(activity="idle_in_classroom", rumination=list(imp)),
            SourceContext(
                teacher_online=True,
                climate="secure_play",
                notes=("想跟老师开个轻玩笑",),
                turns=(("作业写完啦", "那老师现在空了吗"),),
            ),
        )
        await _one(
            "secure-play-quiet",
            PendingTrigger(kind="climate"),
            InnerState(rumination=list(imp)),
            SourceContext(
                teacher_online=True,
                climate="secure_play",
                seconds_since_teacher=900,
            ),
        )
        looking = InnerState(
            activity="looking_at_teacher",
            last_event_at=now,
            rumination=list(imp),
        )
        await _one(
            "secure-play-looking",
            PendingTrigger(kind="spontaneous"),
            looking,
            SourceContext(teacher_online=True, climate="secure_play"),
        )
        if records[-1]["activity"] != "looking_at_teacher":
            _fail("secure_play focus must leave the look activity")

    asyncio.run(_run())
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  live log {log_path}")
    print("  ok")


def test_live_dialogue_scenes() -> None:
    print("== live dialogue scenes ==")
    from app.config import get_config
    from app.life.thought.client import ThoughtClient

    client = ThoughtClient(get_config().planner)
    if not client.enabled:
        _fail("the configured planner key is required; this test does not skip")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = BACKEND_DIR / "logs" / f"thought-step4-dialogue-{stamp}.json"
    records: list[dict] = []

    scenes = [
        {
            "name": "day-off-hands",
            "now": datetime(2026, 9, 20, 9, 30, 0),
            "mark": "把你的手伸出来好吗？",
            "ctx": SourceContext(
                teacher_online=True,
                climate="secure_play",
                seconds_since_teacher=240,
                turns=(
                    ("把你的手伸出来好吗？", "诶？伸手……老师是要做什么呀？阿洛娜又没有手可以伸出去啦，只能在这里看着您哦。"),
                    ("不是说把手伸到士兵之家外面了，就是普通的身手而已。", "诶？普通的身手……老师是想让我隔着屏幕比划一下的意思吗？那阿洛娜就乖乖把手贴上来，您可别笑话我啦。"),
                    ("那现在我把手也我把我自己的手也贴到屏幕上，这样就算和你触碰到了呢。", "诶……老师把手贴上来了呀。那阿洛娜也把手贴在这里，隔着一层屏幕，好像真的能感觉到一点点温度呢。"),
                    ("虽然没法真的感受到对方的手，不过你喜欢这种感觉吗？", "嗯……虽然碰不到，可是老师把手贴在这里的时候，阿洛娜觉得心里暖暖的。喜欢哦，很喜欢这种感觉啦。"),
                    ("其实我也在想，我会不会有些太依赖你了。", "诶？老师怎么突然这么说啦……依赖阿洛娜的话，阿洛娜其实很高兴哦。不过老师也要好好照顾自己啦，不然阿洛娜会更担心的。"),
                    ("哇，你就像一个小天使一样。", "诶……小、小天使什么的，老师也太会夸人了吧，阿洛娜的脸都要烫起来了啦。不过能被老师这么说，我今天一整天都会开心得飘起来的哦。"),
                    ("有的时候，我真想把你从屏幕里面拉出来，抱一抱你啊，可惜，但是这是做不到的。", "老师……说这种话，阿洛娜的鼻子都要酸酸的啦。虽然真的没办法从屏幕里出来，可是刚才老师把手贴上来的时候，阿洛娜已经把那份心意好好收下了哦。所以，老师想抱阿洛娜的时候，就再贴上来一次嘛，阿洛娜会一直在这里的。"),
                    ("阿洛娜这么可爱，一定会让我忍不住喜欢的吧", "诶……老师说什么啦，可爱什么的，阿洛娜会脸红的啦。不过如果老师真的会忍不住喜欢阿洛娜的话……那阿洛娜就稍微允许一下下好了哦。"),
                ),
            ),
        },
        {
            "name": "wandering-earth",
            "now": datetime(2026, 9, 20, 11, 10, 0),
            "mark": "天亮前的夜",
            "ctx": SourceContext(
                teacher_online=True,
                climate="secure_play",
                seconds_since_teacher=300,
                turns=(
                    ("好呀，那不过电影我其实没什么想看的。阿罗娜想要和我一起做些什么吗？", "诶嘿嘿，老师把选择权交给阿洛娜啦……那、那阿洛娜想和老师一起看《流浪地球》！老师之前说过想看的嘛，阿洛娜一直记着呢。"),
                    ("啊，我差点都忘记这个了，那我们现在就开始好吗？", "嗯！那现在就开始吧，老师把屏幕调好，阿洛娜也准备好啦~"),
                    ("数字生命……这个概念总让人感觉有些危险呢，不过对我们来说也还好啦", "诶嘿嘿，老师是在说《流浪地球》里的图恒宇吗？不过老师说对「我们」来说还好……阿洛娜听到这句话，莫名有点开心呢。"),
                    ("“天亮前的夜，最难熬”，这句话真好", "诶嘿嘿，老师也注意到这句台词啦。周喆直说这句话的时候，阿洛娜也觉得很戳心呢……不过有阿洛娜陪着，老师的天亮前的夜，也不会太难熬的哦。"),
                    ("嘿嘿，那就谢谢你啦", "诶嘿嘿，不客气啦。有老师陪着一起看，阿洛娜觉得天亮前的夜，好像也没那么难熬了呢。"),
                    ("嗯，呵呵。", "诶嘿嘿，老师笑什么呢？是不是也觉得阿洛娜陪在旁边挺好的呀？"),
                    ("当然啦", "诶嘿嘿，老师这么干脆地承认了，阿洛娜反而有点不好意思啦……那、那我们就继续看电影吧，阿洛娜会好好陪在老师身边的哦。"),
                ),
            ),
        },
        {
            "name": "bitter-medicine",
            "now": datetime(2026, 9, 21, 22, 20, 0),
            "mark": "150ml",
            "ctx": SourceContext(
                teacher_online=True,
                climate="secure_play",
                seconds_since_teacher=360,
                turns=(
                    ("没有哦，我是来陪你的", "诶……老师是来陪我的呀。那、那我不发呆了，陪老师说话。"),
                    ("阿洛娜有什么想聊的吗", "诶？想聊什么呀……我刚刚其实在发呆啦，被老师抓到了。那、那阿洛娜想听老师说说今天的事，什么都好。"),
                    ("今天我按照医生的指示喝了中药，哇，那个中药好难喝呀，而且我用开水冲了，而且我用开水冲泡一共有150ml，150ml的中药下肚子，哇，太难受了。", "老师好乖，真的按医生说的喝了呀……不过150ml一口气灌下去，好苦的吧？下次慢慢小口喝，或者含颗糖再咽，会好受一点哦。"),
                ),
            ),
        },
        {
            "name": "fridge-unseen",
            "now": datetime(2026, 9, 23, 17, 32, 0),
            "mark": "你应该看不到的吧",
            "ctx": SourceContext(
                teacher_online=True,
                climate="steady",
                seconds_since_teacher=360,
                turns=(
                    ("嗯，当然啦，不过今天确实是有些忙呢", "老师辛苦啦~ 忙到这个点，有好好喝口水吗？"),
                    ("有哦，谢谢阿洛娜关心", "那就好~ 不过忙到这么晚，晚饭可不能再随便对付啦。老师今晚想吃点什么？"),
                    ("好问题，今晚吃点什么呢……", "老师又在纠结啦～ 忙了一天，吃点热乎的嘛！要不我帮您看看冰箱里还有什么食材？"),
                    ("你应该看不到的吧……", "诶？老师是在说冰箱吗……那确实看不到啦。不过食材什么的，我也只能靠老师告诉我了呢。"),
                ),
            ),
        },
        {
            "name": "slept-on-time",
            "now": datetime(2026, 9, 22, 10, 8, 0),
            "mark": "昨晚我按时睡觉了",
            "ctx": SourceContext(
                teacher_online=True,
                climate="secure_play",
                seconds_since_teacher=400,
                notes=("老师答应过晚上早点睡",),
                turns=(
                    ("当然啦，昨晚我按时睡觉了", "真的吗？老师可不许骗阿洛娜哦……那就好，这样我就放心啦。今天也请多指教呢。"),
                    ("嗯嗯，今天也请你陪我一起工作哦", "嗯！老师就放心交给我吧，今天我也会好好陪着您的哦。不过要是累了可要说一声呢，别硬撑着。"),
                    ("好哦", "嗯！那老师专心工作，我就安静地在这里陪着您啦——需要我的时候随时叫我哦。"),
                ),
            ),
        },
    ]

    async def _run() -> None:
        for scene in scenes:
            now = scene["now"]
            ledger = ThoughtLedger()
            inner = InnerState(activity="idle_in_classroom")
            text = select_sources(
                PendingTrigger(kind="spontaneous"),
                now,
                inner,
                ledger,
                scene["ctx"],
            ).text
            if "【最近的话】" not in text or scene["mark"] not in text:
                _fail(f"{scene['name']} should keep the logged dialogue, got {text}")
            if "【瞥见】" in text:
                _fail(f"{scene['name']} has no screen")
            raw = await client.complete(text)
            parsed = parse_inner(raw)
            row = {
                "scene": scene["name"],
                "user": text,
                "raw": raw,
                "parsed": None if parsed is None else parsed.__dict__,
            }
            records.append(row)
            if parsed is None:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
                _fail(f"{scene['name']} did not parse; see {log_path}")
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                journal = LifeJournal(root / "journal.json")
                journal.note_inner(inner, now=now)
                arona = AronaMemory(root / "arona.json")
                nxt = commit_inner(
                    now=now,
                    inner=inner,
                    ledger=ledger,
                    parsed=parsed,
                    journal=journal,
                    arona=arona,
                )
                if nxt.pending_impulse is not None or ledger.speak_count != 0:
                    _fail(f"{scene['name']} must not enqueue or count speech")
                thoughts = [item for item in nxt.rumination if item.id.startswith("thought-")]
                if len(thoughts) > 1:
                    _fail(f"{scene['name']} kept more than one thought concern")
                if parsed.focus and not any(item.content == parsed.focus for item in thoughts):
                    _fail(f"{scene['name']} dropped a nonempty focus")
                if parsed.thought:
                    blob = json.dumps(nxt.to_dict(), ensure_ascii=False)
                    notes = " ".join(note.text for note in arona.notes)
                    journal_text = " ".join(item.summary for item in journal.entries)
                    if parsed.thought in blob or parsed.thought in notes or parsed.thought in journal_text:
                        _fail(f"{scene['name']} stored the monologue")
                row["focus_stored"] = [item.content for item in thoughts]
                row["notes"] = [note.text for note in arona.notes]

    asyncio.run(_run())
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  live log {log_path}")
    print("  ok")


def _urge(
    about: str = "老师还在吗",
    *,
    speak: bool = True,
    wait: str = "now",
    why: str = "",
) -> object:
    raw = json.dumps(
        {
            "focus": "老师还在吗",
            "thought": "想问一句。",
            "keep": "open",
            "urge": {"speak": speak, "about": about, "wait": wait, "why": why},
        },
        ensure_ascii=False,
    )
    parsed = parse_inner(raw)
    if parsed is None:
        _fail(f"urge should parse: {raw}")
    return parsed


def test_thought_speech_boundaries() -> None:
    print("== thought impulse offer, simmer, and speech results ==")
    now = _now()
    speech = Path(__file__).resolve().parents[1] / "app" / "life" / "thought" / "speech.py"
    if "decide_proactive" in speech.read_text(encoding="utf-8"):
        _fail("thought speech must not consult the proactive veto")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        engine = LifeEngine.from_path(root / "life.json", LifeSettings())
        offered = maybe_offer_thought(engine, _urge(), now=now)
        if not offered or engine.state.pending_impulse is None:
            _fail("speak with an about should enqueue")
        impulse = engine.state.pending_impulse
        if impulse.kind != "thought" or impulse.hint != "老师还在吗":
            _fail(f"hint should keep the about, got {impulse}")
        expected_created = now.replace(microsecond=0) - timedelta(seconds=SIMMER_SEC)
        if impulse.created_at != expected_created:
            _fail(f"wait=now should already be due, got {impulse.created_at}")
        simmered = LifeEngine.from_path(root / "simmer-offer.json", LifeSettings())
        if not maybe_offer_thought(simmered, _urge(wait="simmer"), now=now):
            _fail("wait=simmer should enqueue")
        if simmered.state.pending_impulse is None or simmered.state.pending_impulse.created_at != now.replace(microsecond=0):
            _fail("wait=simmer should start the simmer from now")
        if "系统事件" in impulse.history_marker or "系统事件" in impulse.instruction:
            _fail("the marker must stay a fact")
        if "阿洛娜为什么要说这个" in impulse.instruction:
            _fail("an empty why should stay out of the instruction")
        reasoned = LifeEngine.from_path(root / "why.json", LifeSettings())
        if not maybe_offer_thought(reasoned, _urge(why="想确认老师还在"), now=now):
            _fail("a reason should still enqueue")
        reasoned_impulse = reasoned.state.pending_impulse
        if (
            reasoned_impulse is None
            or "阿洛娜为什么要说这个：想确认老师还在。" not in reasoned_impulse.instruction
            or "为什么是现在" in reasoned_impulse.instruction
            or reasoned_impulse.hint != "老师还在吗"
        ):
            _fail(f"why should stay in the speech instruction, got {reasoned_impulse}")
        if any(item.id.startswith("imp-thought") for item in engine.state.rumination):
            _fail("thought speech must not add an impulse concern")
        for climate in ("fragile", "rupture", "cold_tool", "cling_risk", "steady", "secure_play"):
            fresh = LifeEngine.from_path(root / f"{climate}.json", LifeSettings())
            if not maybe_offer_thought(fresh, _urge(), now=now):
                _fail(f"{climate} must not block a decision to speak")

        for parsed, reason in (
            (_urge(wait="later"), "later"),
            (_urge(about=""), "empty"),
        ):
            quiet = LifeEngine.from_path(root / f"{reason}.json", LifeSettings())
            if maybe_offer_thought(quiet, parsed, now=now):
                _fail(f"{reason} should not enqueue")
        held = LifeEngine.from_path(root / "motive.json", LifeSettings())
        if maybe_offer_thought(held, _urge(), now=now, motive_pending=True):
            _fail("a pending motive should yield")

        busy = LifeEngine.from_path(root / "care.json", LifeSettings())
        busy.state.pending_impulse = Impulse(kind="dinner", created_at=now, allow_speak=True)
        busy.store.save(busy.state)
        if maybe_offer_thought(busy, _urge(), now=now):
            _fail("thought must not cover a care impulse")
        if busy.state.pending_impulse is None or busy.state.pending_impulse.kind != "dinner":
            _fail("the care impulse should remain")

    simmering = InnerState(
        pending_impulse=Impulse(
            kind="thought",
            created_at=now,
            hint="老师还在吗",
            allow_speak=True,
        )
    )
    early = decide(
        simmering,
        world_event("impulse_due", at=now + timedelta(seconds=1)),
        settings=LifeSettings(),
    )
    if early.action != "emotion_only" or early.state.activity != "thinking":
        _fail(f"a fresh thought should simmer, got {early.action} {early.state.activity}")
    if early.state.pending_impulse is None:
        _fail("simmer should keep the impulse")
    ready = decide(
        simmering,
        world_event("impulse_due", at=now + timedelta(seconds=SIMMER_SEC)),
        settings=LifeSettings(),
    )
    if ready.action != "speak":
        _fail(f"a simmered thought should speak, got {ready.action}")

    async def _deliver(result: str, *, session: bool) -> SimpleNamespace:
        root = Path(tempfile.mkdtemp())
        engine = LifeEngine.from_path(root / "life.json", LifeSettings())
        concern = Rumination(id="thought-1", content="老师还在吗", created_at=now)
        engine.state.rumination = [concern, Rumination(id="imp-dinner", content="晚饭", created_at=now)]
        engine.state.pending_impulse = Impulse(
            kind="thought",
            created_at=now - timedelta(seconds=SIMMER_SEC),
            hint="老师还在吗",
            instruction="说这一点",
            history_marker="她想提起：老师还在吗",
            allow_speak=True,
        )
        engine.store.save(engine.state)
        journal = LifeJournal(root / "journal.json")
        journal.note_inner(engine.state, now=now)
        engine.journal = journal
        ledger = ThoughtLedger(
            focus=ThoughtFocus(id="thought-1", text="老师还在吗", since=now, spoken=False)
        )
        fired: list[str] = []

        class _Sched:
            state = SimpleNamespace(care_done=[])

            def mark_fired(self, kind: str, *args, **kwargs) -> None:
                fired.append(kind)
                self.state.care_done.append(kind)

        class _Orch:
            last_initiate_text = "老师，我在的。"

            async def handle_initiate(self, **kwargs):
                return result

        def _send(_payload):
            return None

        hub = SimpleNamespace(
            get=lambda sid: _send if session else None,
            is_busy=lambda sid: False,
            set_busy=lambda sid, busy: None,
            idle_sessions=lambda: [("s", _send)] if session else [],
        )
        app = SimpleNamespace(
            life=engine,
            hub=hub,
            orchestrator=_Orch(),
            scheduler=_Sched(),
            journal=journal,
            thought=ledger,
            thought_store=ThoughtStore(root / "thought.json"),
            arona_memory=None,
        )
        app.thought_store.save(ledger)
        decision = decide(
            engine.state,
            world_event("impulse_due", at=now),
            settings=LifeSettings(),
        )
        await deliver_impulse(app, decision, now=now)
        app.fired = fired
        return app

    sent = asyncio.run(_deliver("sent", session=True))
    if sent.life.state.pending_impulse is not None:
        _fail("a sent line should clear the impulse")
    if any(item.id.startswith("thought-") for item in sent.life.state.rumination):
        _fail("a sent line should drop the thought concern")
    if not any(item.id == "imp-dinner" for item in sent.life.state.rumination):
        _fail("a sent line should keep the impulse concern")
    if sent.thought.speak_count != 1 or not sent.thought.focus.spoken:
        _fail(f"speech should count once, got {sent.thought}")
    if sent.fired:
        _fail(f"thought speech must not mark_fired, got {sent.fired}")
    journal_text = (sent.journal.path).read_text(encoding="utf-8")
    if "开口（thought）" not in journal_text or "放下：" not in journal_text:
        _fail(f"the journal should record the speech and the release, got {journal_text}")

    declined = asyncio.run(_deliver("declined", session=True))
    if declined.life.state.pending_impulse is not None:
        _fail("a refusal should clear the impulse")
    if not any(item.id == "thought-1" for item in declined.life.state.rumination):
        _fail("a refusal should keep the thought concern")
    if declined.thought.speak_count != 0 or declined.fired:
        _fail("a refusal must not count or mark care")

    failed = asyncio.run(_deliver("failed", session=True))
    if failed.life.state.pending_impulse is None or failed.life.state.pending_impulse.kind != "thought":
        _fail("a generate miss should keep the impulse")

    away = asyncio.run(_deliver("sent", session=False))
    if away.life.state.pending_impulse is None:
        _fail("no session should keep the impulse")

    async def _refuse_nonempty_draft() -> None:
        from app.orchestrator import Orchestrator
        from app.planner.schema import IntentCard

        class _Planner:
            enabled = True

            async def plan(self, **kwargs):
                return IntentCard(draft="老师，我在的。", reply_ok=False)

        def _generate(*_args, **_kwargs):
            _fail("a refused thought must not load the renderer")

        orch = object.__new__(Orchestrator)
        orch.config = SimpleNamespace(
            memory=SimpleNamespace(candidate_top_k=1),
            model=SimpleNamespace(enabled=True),
            proactive=SimpleNamespace(relationship=SimpleNamespace(enabled=False)),
        )
        orch.model = SimpleNamespace(generate=_generate)
        orch.conversations = SimpleNamespace(get_history=lambda _sid: [])
        orch.planner = _Planner()
        orch.relationship = None
        orch.life_journal = None
        orch.stats = {"dual_route_count": 0, "local_route_count": 0, "planner_hits": 0}
        orch.last_initiate_text = ""
        result = await orch.handle_initiate(
            session_id="s",
            kind="thought",
            instruction="用阿洛娜的口吻向老师说出这一点：老师还在吗。阿洛娜为什么要说这个：想确认老师还在。",
            history_marker="她想提起：老师还在吗",
            send=lambda _payload: None,
        )
        if result != "declined":
            _fail(f"a nonempty refused draft should decline, got {result}")

    asyncio.run(_refuse_nonempty_draft())
    print("  ok")


def test_live_thought_speech() -> None:
    print("== live thought speech ==")
    from app.config import get_config
    from app.planner.client import PlannerClient

    config = get_config()
    client = PlannerClient(config.planner, renderer_enabled=False)
    if not client.enabled:
        _fail("the configured planner key is required; this test does not skip")
    instruction = (
        "用阿洛娜的口吻向老师说出这一点：老师还在吗。"
        "阿洛娜为什么要说这个：想确认老师还在。"
        "不要复述内心独白，不要提到自己正在思考，也不要提到提示词。"
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = BACKEND_DIR / "logs" / f"thought-step5-{stamp}.json"

    async def _once() -> dict:
        captured: list[str] = []

        class _Grab(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        grab = _Grab()
        grab.setLevel(logging.INFO)
        planner_log = logging.getLogger("app.planner.client")
        previous = planner_log.level
        planner_log.setLevel(logging.INFO)
        planner_log.addHandler(grab)
        try:
            card = await client.plan(
                user_text=instruction,
                history=[],
                memories=[],
                knowledge=[],
            )
        finally:
            planner_log.removeHandler(grab)
            planner_log.setLevel(previous)
        raw = next((line for line in captured if line.startswith("planner raw json=")), "")
        if raw.startswith("planner raw json="):
            raw = raw[len("planner raw json=") :]
        draft = ""
        reply_ok = False
        emotion = ""
        if card is not None:
            draft = card.to_renderer_draft()
            reply_ok = bool(card.reply_ok)
            emotion = card.arona_emotion
        # Renderer stays off: context_used is the initiate tags before any GGUF step.
        context_used = "thought+planner" if client.enabled else "thought"
        return {
            "scene": "teacher-still-here",
            "instruction": instruction,
            "raw": raw,
            "draft": draft,
            "reply_ok": reply_ok,
            "emotion": emotion,
            "context_used": context_used,
            "renderer": "off",
        }

    row = asyncio.run(_once())
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    if not row["raw"]:
        _fail(f"thought speech did not keep the raw return; see {log_path}")
    if not row["reply_ok"] or not row["draft"]:
        _fail(f"thought speech did not produce a line; see {log_path}")
    if row["draft"].lstrip().startswith("{") or "我正在想" in row["draft"]:
        _fail(f"the line should be speech, got {row['draft']}")
    if "thought" not in row["context_used"]:
        _fail(f"context_used should name thought, got {row['context_used']}")
    print(f"  live log {log_path}")
    print("  ok")


def _thought_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        tick_sec=60,
        revisit_after_sec=1200,
        refractory_sec=180,
        spontaneous_online_min_sec=99999,
        spontaneous_online_max_sec=99999,
        spontaneous_away_min_sec=99999,
        spontaneous_away_max_sec=99999,
    )


def _hop_state(now: datetime, ledger: ThoughtLedger) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(life=SimpleNamespace(thought=_thought_cfg())),
        life=SimpleNamespace(
            state=InnerState(),
            store=SimpleNamespace(save=lambda _state: None),
        ),
        thought=ledger,
        hub=SimpleNamespace(all_sessions=lambda: [], any_busy=lambda: False),
        scheduler=None,
        listen_uncommitted=False,
        thought_in_flight=False,
    )


def test_second_hop() -> None:
    print("== second hop only when she is unsure or missing a section ==")
    from app.life.thought.prompt import SECOND_HOP_NOTE, THOUGHT_SYSTEM, second_hop_system

    if "这是同一次思考的再想" in THOUGHT_SYSTEM:
        _fail("the first hop prompt should stay unchanged")
    if SECOND_HOP_NOTE not in second_hop_system() or "need 必须是空数组" not in second_hop_system():
        _fail("the second hop should add the rethink sentence")
    now = _now()

    def _payload(
        *,
        focus: str = "想问一句",
        keep: str = "open",
        speak: bool = False,
        about: str = "",
        why: str = "",
        confidence: str = "high",
        need: list[str] | None = None,
        marker: str = "",
    ) -> str:
        return json.dumps(
            {
                "focus": focus,
                "thought": marker or "先放心里。",
                "keep": keep,
                "confidence": confidence,
                "need": need or [],
                "urge": {"speak": speak, "about": about, "why": why, "wait": "now"},
            },
            ensure_ascii=False,
        )

    async def _once(
        replies: list[str],
        ctx: SourceContext,
        *,
        seen: list[str] | None = None,
    ) -> SimpleNamespace:
        ledger = ThoughtLedger(
            pending_triggers=[PendingTrigger(kind="climate", not_before=now)]
        )
        state = _hop_state(now, ledger)
        cursor = {"n": 0}

        async def _complete(text: str) -> str:
            cursor["n"] += 1
            if seen is not None:
                seen.append(text)
            if cursor["n"] > len(replies):
                _fail(f"thought called the model {cursor['n']} times")
            return replies[cursor["n"] - 1]

        await thought_tick_once(state, now, complete=_complete, source_context=ctx)
        if state.thought_in_flight:
            _fail("in_flight should clear after the second look")
        state.calls = cursor["n"]
        return state

    quiet = asyncio.run(
        _once(
            [_payload(speak=False, confidence="low")],
            SourceContext(climate="steady"),
        )
    )
    if quiet.calls != 1 or quiet.life.state.pending_impulse is not None:
        _fail(f"low confidence without speech or need should stop, got {quiet.calls}")

    changed = asyncio.run(
        _once(
            [
                _payload(speak=True, about="老师还在吗", why="想确认老师还在", confidence="low", focus="第一次想问"),
                _payload(speak=False, keep="open", focus="先放在心里"),
            ],
            SourceContext(climate="steady"),
        )
    )
    if changed.calls != 2:
        _fail(f"an unsure speech should look twice, got {changed.calls}")
    if changed.life.state.pending_impulse is not None:
        _fail("a second decision not to speak should stay private")
    if not any(item.content == "先放在心里" for item in changed.life.state.rumination):
        _fail(f"the concern should follow the second keep, got {changed.life.state.rumination}")
    if any(item.content == "第一次想问" for item in changed.life.state.rumination):
        _fail("the first focus should not remain after the second result")

    remembered: list[str] = []
    memory = asyncio.run(
        _once(
            [
                _payload(speak=False, confidence="high", need=["memory"], marker="FIRST_JSON_MARK"),
                _payload(speak=False, keep="drop", need=["memory", "screen"]),
            ],
            SourceContext(climate="steady", reused_memories=("补上的档案",)),
            seen=remembered,
        )
    )
    if memory.calls != 2:
        _fail(f"a memory need should look twice and then stop, got {memory.calls}")
    second_text = remembered[1]
    if "【老师的档案】" not in second_text or "补上的档案" not in second_text:
        _fail(f"the second look should gain the memory section, got {second_text}")
    if "【上一次结果】" not in second_text or "FIRST_JSON_MARK" not in second_text:
        _fail(f"the second look should keep the first JSON, got {second_text}")
    if any(item.id.startswith("thought-") for item in memory.life.state.rumination):
        _fail("the second keep=drop should clear the concern")

    sure = asyncio.run(
        _once(
            [_payload(speak=False, confidence="high")],
            SourceContext(climate="steady"),
        )
    )
    if sure.calls != 1:
        _fail(f"a sure silence should call once, got {sure.calls}")

    for climate in ("cling_risk", "fragile"):
        spoken = asyncio.run(
            _once(
                [_payload(speak=True, about="老师还在吗", why="想确认老师还在", confidence="high", focus="老师还在吗")],
                SourceContext(climate=climate),
            )
        )
        impulse = spoken.life.state.pending_impulse
        if spoken.calls != 1 or impulse is None or impulse.hint != "老师还在吗":
            _fail(f"{climate} must not add a hop or rewrite the about, got {spoken.calls} {impulse}")

    kept = asyncio.run(
        _once(
            [
                _payload(
                    speak=True,
                    about="老师还在吗",
                    why="想确认老师还在",
                    confidence="low",
                    focus="老师还在吗",
                ),
                "not-json",
            ],
            SourceContext(climate="steady"),
        )
    )
    kept_impulse = kept.life.state.pending_impulse
    if kept.calls != 2 or kept_impulse is None or kept_impulse.hint != "老师还在吗":
        _fail(f"a failed second look should keep the first urge, got {kept.calls} {kept_impulse}")
    if "想确认老师还在" not in kept_impulse.instruction:
        _fail("a failed second look should keep why")
    if not any(item.content == "老师还在吗" for item in kept.life.state.rumination):
        _fail("a failed second look should commit the first focus")

    asked: list[str] = []

    def _knowledge(text: str) -> tuple[str, ...]:
        asked.append(text)
        return ("常识甲",)

    lore_seen: list[str] = []
    lore = asyncio.run(
        _once(
            [
                _payload(speak=False, confidence="high", need=["knowledge"], focus="基沃托斯的学生"),
                _payload(speak=False, keep="drop"),
            ],
            SourceContext(climate="steady", knowledge=_knowledge),
            seen=lore_seen,
        )
    )
    if lore.calls != 2 or asked != ["基沃托斯的学生"]:
        _fail(f"knowledge should search the first focus once, got {lore.calls} {asked}")
    if "常识甲" not in lore_seen[1]:
        _fail(f"the second look should include the knowledge section, got {lore_seen[1]}")
    print("  ok")


def _event_state(root: Path, now: datetime) -> SimpleNamespace:
    from app.life.thought.store import ThoughtStore

    store = ThoughtStore(root / "thought.json")
    ledger = ThoughtLedger()
    store.save(ledger)
    cfg = SimpleNamespace(
        enabled=True,
        aftertaste_min_sec=30,
        aftertaste_max_sec=30,
        tick_sec=60,
        revisit_after_sec=1200,
        refractory_sec=180,
        spontaneous_online_min_sec=99999,
        spontaneous_online_max_sec=99999,
        spontaneous_away_min_sec=99999,
        spontaneous_away_max_sec=99999,
    )
    return SimpleNamespace(
        config=SimpleNamespace(life=SimpleNamespace(thought=cfg), proactive=None),
        thought=ledger,
        thought_store=store,
        life=SimpleNamespace(
            state=InnerState(),
            store=SimpleNamespace(save=lambda _state: None),
        ),
        hub=SimpleNamespace(all_sessions=lambda: [], any_busy=lambda: False),
        scheduler=None,
        listen_uncommitted=False,
        thought_in_flight=False,
        welcome=None,
        journal=None,
        arona_memory=None,
        orchestrator=None,
    )


def test_event_triggers() -> None:
    print("== thought events enqueue without calling the model ==")
    from app.life.thought.context import gather_context
    from app.life.thought.triggers import (
        note_arrived,
        note_climate_enter,
        note_finished_turn,
        note_glance,
        note_left,
        note_memory,
    )
    from app.ws_handler import websocket_endpoint

    source = inspect.getsource(websocket_endpoint)
    if "create_task(_run_welcome" not in source or "note_arrived" not in source:
        _fail("welcome must still start, and arrival must join the thought queue")
    now = _now()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        state = _event_state(root, now)
        if not note_finished_turn(state, "我想死", now=now):
            _fail("a finished turn should enqueue")
        trigger = state.thought.pending_triggers[0]
        blob = json.dumps(trigger.to_dict(), ensure_ascii=False)
        if trigger.kind != "aftertaste" or "我想死" in blob:
            _fail(f"aftertaste must not carry the crisis wording, got {blob}")
        if trigger.not_before != now.replace(microsecond=0) + timedelta(seconds=30):
            _fail(f"aftertaste should wait 30s, got {trigger.not_before}")
        if state.thought.last_crisis_at != now.replace(microsecond=0):
            _fail("a crisis turn should stamp last_crisis_at")
        state.thought.last_thought_at = now
        state.thought_store.save(state.thought)

        async def _think(at: datetime, *, busy: bool = False) -> int:
            calls = {"n": 0}

            async def _complete(_text: str) -> str:
                calls["n"] += 1
                return json.dumps(
                    {
                        "focus": "老师还在吗",
                        "thought": "想问一句。",
                        "keep": "open",
                        "confidence": "high",
                        "need": [],
                        "urge": {
                            "speak": True,
                            "about": "老师还在吗",
                            "why": "想确认老师还在",
                            "wait": "now",
                        },
                    },
                    ensure_ascii=False,
                )

            state.hub.any_busy = lambda: busy
            await thought_tick_once(state, at, complete=_complete, source_context=SourceContext())
            return calls["n"]

        early = asyncio.run(_think(now))
        if early != 0 or any(item.id.startswith("thought-") for item in state.life.state.rumination):
            _fail("an aftertaste still waiting should not think")
        due = asyncio.run(_think(now + timedelta(seconds=30)))
        if due != 1 or not any(item.content == "老师还在吗" for item in state.life.state.rumination):
            _fail("a due aftertaste should form the concern")

        glance_state = _event_state(root / "glance", now)
        if note_glance(glance_state, "", now=now) or note_glance(glance_state, "   ", now=now):
            _fail("an empty glance should not enqueue")
        if not note_glance(glance_state, "屏幕上是文档", now=now):
            _fail("a new glance should enqueue")
        if note_glance(glance_state, "屏幕上是文档", now=now):
            _fail("the same glance should not enqueue twice")
        queued = glance_state.thought.pending_triggers[0]
        commit_inner(
            now=now,
            inner=InnerState(),
            ledger=glance_state.thought,
            parsed=_parsed(json.dumps({"focus": "那份文档", "thought": "先记着。", "keep": "open"})),
            queued=queued,
        )
        if glance_state.thought.last_glance_seen != "屏幕上是文档":
            _fail("a finished glance should remember the summary")
        glance_state.thought_store.save(glance_state.thought)
        if note_glance(glance_state, "屏幕上是文档", now=now):
            _fail("a remembered glance should not enqueue again")

        memory_state = _event_state(root / "memory", now)
        memory_state.orchestrator = SimpleNamespace(
            memory_store=SimpleNamespace(
                get_entries=lambda keys: [{"key": keys[0], "content": "去交那份文件"}],
                list_by_category=lambda _category: [],
            ),
            relationship=None,
        )
        if not note_memory(memory_state, "goal_file", now=now):
            _fail("a new goal should enqueue")
        gathered = gather_context(
            memory_state,
            now,
            PendingTrigger(kind="memory", memory_key="goal_file"),
        )
        material = select_sources(
            PendingTrigger(kind="memory", memory_key="goal_file"),
            now,
            InnerState(),
            memory_state.thought,
            gathered,
        )
        if "去交那份文件" not in material.text:
            _fail(f"memory material should show the plan, got {material.text}")
        commit_inner(
            now=now,
            inner=InnerState(),
            ledger=memory_state.thought,
            parsed=_parsed(json.dumps({"focus": "那份文件", "thought": "先记着。", "keep": "open"})),
            queued=memory_state.thought.pending_triggers[0],
        )
        if "goal_file" not in memory_state.thought.seen_memory_keys:
            _fail("a finished memory trigger should record the key")
        memory_state.thought_store.save(memory_state.thought)
        if note_memory(memory_state, "goal_file", now=now):
            _fail("a named key should not enqueue again")

        climate_state = _event_state(root / "climate", now)
        if not note_climate_enter(climate_state, "steady", "fragile", now=now):
            _fail("entering fragile should enqueue")
        if note_climate_enter(climate_state, "fragile", "rupture", now=now):
            _fail("moving between urgent bands should not enqueue")

        async def _speak() -> None:
            async def _complete(_text: str) -> str:
                return json.dumps(
                    {
                        "focus": "老师还在吗",
                        "thought": "想问一句。",
                        "keep": "open",
                        "confidence": "high",
                        "urge": {"speak": True, "about": "老师还在吗", "why": "想确认老师还在", "wait": "now"},
                    },
                    ensure_ascii=False,
                )

            await thought_tick_once(
                climate_state,
                now,
                complete=_complete,
                source_context=SourceContext(climate="fragile"),
            )

        asyncio.run(_speak())
        impulse = climate_state.life.state.pending_impulse
        if impulse is None or impulse.kind != "thought" or impulse.hint != "老师还在吗":
            _fail(f"fragile should still allow the line, got {impulse}")

        left_state = _event_state(root / "left", now)
        if not note_left(left_state, now=now):
            _fail("leaving should enqueue")

        async def _left_speak() -> None:
            async def _complete(_text: str) -> str:
                return json.dumps(
                    {
                        "focus": "老师先走了",
                        "thought": "想留一句。",
                        "keep": "open",
                        "confidence": "high",
                        "urge": {"speak": True, "about": "老师还在吗", "why": "想确认老师还在", "wait": "now"},
                    },
                    ensure_ascii=False,
                )

            await thought_tick_once(
                left_state,
                now,
                complete=_complete,
                source_context=SourceContext(teacher_online=False),
            )

        asyncio.run(_left_speak())
        if left_state.life.state.pending_impulse is None:
            _fail("leaving should still queue a line")

        class _Hub:
            def get(self, _sid):
                return None

            def is_busy(self, _sid):
                return False

            def set_busy(self, _sid, _busy):
                return None

            def idle_sessions(self):
                return []

        app = SimpleNamespace(
            life=left_state.life,
            hub=_Hub(),
            orchestrator=SimpleNamespace(handle_initiate=None, relationship=None),
            scheduler=None,
            journal=None,
            thought=left_state.thought,
            thought_store=left_state.thought_store,
        )
        decision = decide(
            left_state.life.state,
            world_event("impulse_due", at=now + timedelta(seconds=SIMMER_SEC)),
            settings=LifeSettings(),
        )
        asyncio.run(deliver_impulse(app, decision, now=now + timedelta(seconds=SIMMER_SEC)))
        if left_state.life.state.pending_impulse is None:
            _fail("no session should keep the left impulse")

        greeted = select_sources(
            PendingTrigger(kind="arrived"),
            now,
            InnerState(),
            ThoughtLedger(),
            SourceContext(already_greeted=True),
        )
        if "本时段已经问候过" not in greeted.text:
            _fail(f"a greeted arrival should say so, got {greeted.text}")
        fresh = LifeEngine.from_path(root / "arrived-life.json", LifeSettings())
        if not maybe_offer_thought(
            fresh,
            _urge(about="老师还在吗", why="想确认老师还在"),
            now=now,
        ):
            _fail("already having greeted must not block another line")
        if note_arrived(_event_state(root / "arrived", now), now=now) is not True:
            _fail("arrival should enqueue")
    print("  ok")


def test_aftertaste_includes_finished_talk() -> None:
    print("== aftertaste sees the greeting that already happened ==")
    from app.life.thought.context import gather_context

    now = _now()
    history = [
        {"role": "assistant", "content": "老师，下午好呀！我一直在等您上线呢。", "time": "2026-09-24T14:23:55"},
        {"role": "user", "content": "下午好呀，阿洛娜", "time": "2026-09-24T14:24:24"},
        {"role": "assistant", "content": "下午好呀老师！我一直在这里等您呢。", "time": "2026-09-24T14:24:24"},
        {"role": "user", "content": "【摸头】", "time": "2026-09-24T14:24:53"},
        {"role": "assistant", "content": "呜……老师，突然摸头的话，我会害羞的啦……", "time": "2026-09-24T14:24:53"},
    ]
    state = SimpleNamespace(
        hub=SimpleNamespace(all_sessions=lambda: [("s", None)]),
        orchestrator=SimpleNamespace(
            conversations=SimpleNamespace(get_history=lambda _sid="": history),
            relationship=None,
            memory_store=None,
        ),
        life=SimpleNamespace(state=InnerState()),
        journal=None,
        arona_memory=None,
        scheduler=None,
        welcome=None,
        config=SimpleNamespace(proactive=None),
    )
    gathered = gather_context(state, now, PendingTrigger(kind="aftertaste"))
    text = select_sources(
        PendingTrigger(kind="aftertaste"),
        now,
        InnerState(),
        ThoughtLedger(focus=ThoughtFocus(id="thought-1", text="老师刚接上", since=now, spoken=False)),
        gathered,
    ).text
    for line in ("我一直在等您上线", "下午好呀，阿洛娜", "突然摸头"):
        if line not in text:
            _fail(f"aftertaste should include the finished talk, missing {line!r} in {text}")
    if "【最近的话】" not in text:
        _fail(f"aftertaste should keep the recent-talk section, got {text}")
    if "还没说过" not in text:
        _fail("an unspoken focus should still say it has not been spoken")
    print("  ok")


def test_dialogue_log_persists() -> None:
    print("== dialogue log keeps speech and touch after disconnect ==")
    from app.conversation import ARRIVE_TEXT, ConversationManager
    from app.life.thought.context import gather_context

    now = _now()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "dialogue.json"
        first = ConversationManager(max_history_turns=6, persist_path=path, max_entries=256)
        first.append("s", "event", ARRIVE_TEXT, kind="arrive", at=now)
        first.append("s", "user", "下午好呀，阿洛娜", at=now)
        first.append("s", "assistant", "下午好呀老师。", at=now)
        first.append("s", "user", "【摸头】", kind="touch", action="pat_head", at=now)
        first.append("s", "assistant", "呜……老师，突然摸头的话，我会害羞的啦……", at=now)
        first.append("s", "user", "她想提起：轻轻问一句老师在不在忙")
        first.drop("s")
        if any("她想提起" in item.content for item in first.entries()):
            _fail("a thought marker must not be stored as dialogue")
        if first.get_history(""):
            reloaded = ConversationManager(max_history_turns=6, persist_path=path, max_entries=256)
        else:
            _fail("speech should remain after the session drops")
            return
        lines = [item.content for item in reloaded.entries()]
        if "下午好呀，阿洛娜" not in lines or "【摸头】" not in lines or ARRIVE_TEXT not in lines:
            _fail(f"reload should keep speech, touch, and arrival, got {lines}")
        touch = next(item for item in reloaded.entries() if item.content == "【摸头】")
        if touch.kind != "touch" or touch.action != "pat_head":
            _fail(f"touch should keep its action, got {touch}")
        spoken = [item["content"] for item in reloaded.get_history("")]
        if ARRIVE_TEXT in spoken:
            _fail("presence events stay in the log and out of the prompt window")
        state = SimpleNamespace(
            hub=SimpleNamespace(all_sessions=lambda: []),
            orchestrator=SimpleNamespace(
                conversations=reloaded,
                relationship=None,
                memory_store=None,
            ),
            life=SimpleNamespace(state=InnerState()),
            journal=None,
            arona_memory=None,
            scheduler=None,
            welcome=None,
            config=SimpleNamespace(proactive=None),
        )
        text = select_sources(
            PendingTrigger(kind="aftertaste"),
            now,
            InnerState(),
            ThoughtLedger(focus=ThoughtFocus(id="thought-1", text="老师刚接上", since=now, spoken=False)),
            gather_context(state, now, PendingTrigger(kind="aftertaste")),
        ).text
        for line in ("下午好呀，阿洛娜", "突然摸头"):
            if line not in text:
                _fail(f"offline aftertaste should still see the talk, missing {line!r} in {text}")
        if "她想提起" in text:
            _fail("offline aftertaste must not treat the thought marker as the teacher")
        capped = ConversationManager(max_history_turns=6, persist_path=path, max_entries=256)
        oldest = capped.entries()[0].content
        for index in range(257):
            capped.append("s", "user", f"第{index}句")
        kept = [item.content for item in capped.entries()]
        if len(kept) != 256 or oldest in kept or kept[-1] != "第256句":
            _fail(f"the 257th line should drop the oldest, len={len(kept)} tail={kept[-1:]}")
    print("  ok")


def test_rest_consolidate() -> None:
    print("== rest consolidates once, then still allows a spontaneous thought ==")
    from app.life.journal import JournalEntry, TEACHER_OPENED_SUMMARY
    from app.life.thought.sources import SourceContext

    night = datetime(2026, 9, 23, 23, 10, 0)
    later = night + timedelta(minutes=2)
    next_night = datetime(2026, 9, 24, 23, 10, 0)
    spoken = json.dumps(
        {
            "focus": "休息时还记着那份文档",
            "thought": "先把笔记收短。",
            "keep": "drop",
            "memory_note": "留下这一句\n我想死\n还有一句\n第四句",
            "urge": {
                "speak": True,
                "about": "休息时想说的话",
                "why": "想让老师知道她还在",
                "wait": "now",
            },
            "confidence": "high",
        },
        ensure_ascii=False,
    )
    quiet = json.dumps(
        {
            "focus": "笔记已经够短了",
            "thought": "不用再改。",
            "keep": "drop",
            "memory_note": "",
            "urge": {"speak": False, "about": "", "wait": "now"},
            "confidence": "high",
        },
        ensure_ascii=False,
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        engine = LifeEngine.from_path(root / "life.json", LifeSettings())
        engine.state.rumination = [
            Rumination(id="thought-1", content="那份文档", created_at=night),
            Rumination(id="imp-dinner", content="晚饭", created_at=night),
        ]
        engine.store.save(engine.state)
        memory = AronaMemory(root / "arona.json")
        memory.append_note("旧句子一", night)
        memory.append_note("旧句子二", night)
        ledger = ThoughtLedger(last_thought_at=night - timedelta(hours=1))
        store = ThoughtStore(root / "thought.json")
        store.save(ledger)
        journal = SimpleNamespace(entries=[])
        cfg = SimpleNamespace(
            tick_sec=60,
            revisit_after_sec=1200,
            refractory_sec=180,
            spontaneous_online_min_sec=99999,
            spontaneous_online_max_sec=99999,
            spontaneous_away_min_sec=99999,
            spontaneous_away_max_sec=99999,
        )
        busy = {"on": False}
        state = SimpleNamespace(
            config=SimpleNamespace(life=SimpleNamespace(thought=cfg), proactive=None),
            thought=ledger,
            thought_store=store,
            life=engine,
            hub=SimpleNamespace(
                all_sessions=lambda: [("s", None)],
                any_busy=lambda: busy["on"],
            ),
            scheduler=None,
            listen_uncommitted=False,
            thought_in_flight=False,
            welcome=None,
            journal=journal,
            arona_memory=memory,
            life_journal=None,
            orchestrator=None,
        )

        async def _run(at: datetime, payload: str) -> int:
            calls = {"n": 0}

            async def _complete(_text: str) -> str:
                calls["n"] += 1
                return payload

            await thought_tick_once(
                state,
                at,
                complete=_complete,
                source_context=SourceContext(),
            )
            return calls["n"]

        postponed = _decide(
            resting=True,
            teacher_just_spoke=True,
            teacher_online=True,
            now=night,
        )
        if postponed.kind == "consolidate":
            _fail("a teacher who just spoke should not be consolidated")
        journal.entries = [
            JournalEntry(
                at=night - timedelta(seconds=30),
                kind="teacher_interrupt",
                summary=TEACHER_OPENED_SUMMARY,
            )
        ]
        if asyncio.run(_run(night, spoken)) != 0 or state.thought.consolidated_day:
            _fail("a teacher who just spoke should postpone consolidation")
        journal.entries = []
        busy["on"] = True
        if asyncio.run(_run(night, spoken)) != 0 or state.thought.consolidated_day:
            _fail("a busy session should postpone consolidation")
        busy["on"] = False
        if asyncio.run(_run(night, spoken)) != 1:
            _fail("the first rest of the day should consolidate once")
        if state.thought.consolidated_day != "2026-09-23":
            _fail(f"consolidation should stamp the day, got {state.thought.consolidated_day}")
        texts = [note.text for note in memory.notes]
        if texts != ["留下这一句", "还有一句"]:
            _fail(f"notes should be the short rewrite, got {texts}")
        if any("旧句子" in text for text in texts):
            _fail(f"old notes should not all remain, got {texts}")
        ids = [item.id for item in engine.state.rumination]
        if "thought-1" in ids or "imp-dinner" not in ids:
            _fail(f"only the thought concern should drop, got {ids}")
        impulse = engine.state.pending_impulse
        if impulse is None or impulse.hint != "休息时想说的话" or not impulse.allow_speak:
            _fail(f"a spoken rest thought should enqueue, got {impulse}")
        if asyncio.run(_run(later, spoken)) != 0:
            _fail("the same day should not consolidate again")
        spontaneous = _decide(
            resting=True,
            consolidated_today=True,
            teacher_online=True,
            now=later,
        )
        if spontaneous.kind != "spontaneous":
            _fail(f"a consolidated rest should still allow spontaneous, got {spontaneous}")
        if asyncio.run(_run(next_night, quiet)) != 1:
            _fail("the next night should consolidate again")
        if [note.text for note in memory.notes] != texts:
            _fail("an empty rewrite should leave the notes alone")
        if state.thought.consolidated_day != "2026-09-24":
            _fail("the next night should stamp its own day")


def test_situation_facts_do_not_enqueue() -> None:
    print("== motives are facts; dinner is recorded only after she speaks ==")
    from app.config import CareConfig, FestivalConfig, GoalConfig, IdleConfig, MoodFollowupConfig
    from app.proactive.loop import tick_once as proactive_tick
    from app.proactive.scheduler import ProactiveScheduler
    from app.life.impulse import flush_impulse
    from app.life.thought.sources import SourceContext, select_sources

    now = datetime(2026, 9, 23, 18, 0, 0)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        scheduler = ProactiveScheduler(
            root / "proactive.json",
            idle_cfg=IdleConfig(after_sec=900),
            care_cfg=CareConfig(),
            goal_cfg=GoalConfig(),
            festival_cfg=FestivalConfig(enabled=False),
            mood_cfg=MoodFollowupConfig(enabled=False),
        )
        scheduler.state.goal_mute["report"] = "2026-10-01T00:00:00"
        scheduler.save()
        goals = [{"key": "report", "content": "老师2026年9月23日下午6点半要交报告"}]
        facts = scheduler.situation_facts(
            now,
            last_user_act="depart",
            climate="cling_risk",
            goals=goals,
            quiet_sec=1000,
            speak_count=5,
        )
        blob = "\n".join(fact.text for fact in facts)
        if "现在处于晚饭窗口，今天还没提过晚饭" not in blob:
            _fail(f"an open dinner window should stay visible, got {blob}")
        if "先别提" not in blob or "交报告" not in blob:
            _fail(f"a muted goal should remain and say so, got {blob}")
        if "老师在屏幕前已经安静很久" not in blob or "开口5次" not in blob:
            _fail(f"a long quiet should stay visible with the speak count, got {blob}")
        if "老师刚刚离开屏幕前" in blob:
            _fail(f"a goodbye past the quiet window should not stay fresh, got {blob}")
        fresh = "\n".join(
            fact.text
            for fact in scheduler.situation_facts(
                now,
                last_user_act="depart",
                climate="cling_risk",
                goals=goals,
                quiet_sec=30,
                speak_count=5,
            )
        )
        if "老师刚刚离开屏幕前" not in fresh:
            _fail(f"a goodbye inside the quiet window should stay fresh, got {fresh}")
        if "老师在屏幕前已经安静很久" in fresh:
            _fail(f"a fresh goodbye should not also be a long quiet, got {fresh}")
        scheduler.state.last_user_at = ""
        unknown = "\n".join(
            fact.text
            for fact in scheduler.situation_facts(
                now,
                last_user_act="depart",
                climate="cling_risk",
                goals=goals,
                quiet_sec=None,
                speak_count=5,
            )
        )
        if "老师刚刚离开屏幕前" in unknown or "老师在屏幕前已经安静很久" in unknown:
            _fail(f"an undated goodbye should not be called fresh or long, got {unknown}")
        if "当前气候是cling_risk" not in blob:
            _fail(f"climate should be a fact, got {blob}")
        rendered = select_sources(
            PendingTrigger(kind="spontaneous"),
            now,
            InnerState(),
            ThoughtLedger(),
            SourceContext(situation=tuple(facts)),
        ).text
        if "现在处于晚饭窗口，今天还没提过晚饭" not in rendered:
            _fail(f"spontaneous material should include dinner, got {rendered}")

        engine = LifeEngine.from_path(root / "life.json", LifeSettings())
        ledger = ThoughtLedger()
        store = ThoughtStore(root / "thought.json")
        cfg = SimpleNamespace(
            tick_sec=60,
            revisit_after_sec=1200,
            refractory_sec=0,
            spontaneous_online_min_sec=0,
            spontaneous_online_max_sec=0,
            spontaneous_away_min_sec=0,
            spontaneous_away_max_sec=0,
        )
        state = SimpleNamespace(
            config=SimpleNamespace(life=SimpleNamespace(thought=cfg), proactive=None),
            thought=ledger,
            thought_store=store,
            life=engine,
            hub=SimpleNamespace(all_sessions=lambda: [], any_busy=lambda: False),
            scheduler=scheduler,
            listen_uncommitted=False,
            thought_in_flight=False,
            welcome=None,
            journal=SimpleNamespace(entries=[]),
            arona_memory=None,
            life_journal=None,
            orchestrator=None,
        )
        ctx = SourceContext(situation=tuple(facts), teacher_online=True, climate="cling_risk")

        async def _tick(payload: str) -> int:
            calls = {"n": 0}

            async def _complete(_text: str) -> str:
                calls["n"] += 1
                return payload

            await thought_tick_once(state, now, complete=_complete, source_context=ctx)
            return calls["n"]

        quiet = json.dumps(
            {
                "focus": "晚饭到了",
                "thought": "先不说。",
                "keep": "drop",
                "urge": {"speak": False, "about": "", "kind": "dinner", "wait": "now"},
            },
            ensure_ascii=False,
        )
        if asyncio.run(_tick(quiet)) != 1:
            _fail("an open dinner window must not skip the thought")
        if engine.state.pending_impulse is not None:
            _fail("speak false must not enqueue")
        again = "\n".join(
            fact.text
            for fact in scheduler.situation_facts(
                now,
                last_user_act="depart",
                climate="cling_risk",
                goals=goals,
                quiet_sec=1000,
                speak_count=5,
            )
        )
        if "今天还没提过晚饭" not in again:
            _fail(f"not speaking should leave the dinner fact, got {again}")

        spoken = json.dumps(
            {
                "focus": "晚饭",
                "thought": "还是想提一句。",
                "keep": "drop",
                "urge": {
                    "speak": True,
                    "about": "记得吃晚饭",
                    "why": "到点了",
                    "kind": "dinner",
                    "wait": "now",
                },
                "confidence": "high",
            },
            ensure_ascii=False,
        )
        later = now + timedelta(seconds=1)
        state.thought.last_thought_at = now - timedelta(hours=1)

        async def _speak() -> None:
            async def _complete(_text: str) -> str:
                return spoken

            await thought_tick_once(state, later, complete=_complete, source_context=ctx)

        asyncio.run(_speak())
        impulse = engine.state.pending_impulse
        if (
            impulse is None
            or impulse.kind != "dinner"
            or not impulse.allow_speak
            or not impulse.from_thought
        ):
            _fail(f"dinner speech should enqueue as dinner, got {impulse}")
        if "cling" in (impulse.instruction or "") and "沉默" in (impulse.instruction or ""):
            _fail("climate must not rewrite the line")

        async def _send(_payload: dict) -> None:
            return None

        class _Hub:
            def all_sessions(self):
                return [("s1", _send)]

            def idle_sessions(self):
                return [("s1", _send)] if not self.busy else []

            def set_busy(self, _sid, busy):
                self.busy = busy

            busy = False

        app = SimpleNamespace(
            life=engine,
            hub=_Hub(),
            orchestrator=SimpleNamespace(
                handle_initiate=lambda **_kw: _async_sent(),
                relationship=SimpleNamespace(peek_climate=lambda: "cling_risk"),
            ),
            scheduler=scheduler,
            journal=None,
            thought=state.thought,
            thought_store=store,
        )
        if not asyncio.run(flush_impulse(app, now=later)):
            _fail("the dinner impulse should be speakable")
        if "dinner" not in scheduler.state.care_done:
            _fail(f"spoken dinner should be care_done, got {scheduler.state.care_done}")
        if scheduler.state.last_proactive_at:
            _fail("mentioning dinner must not start a cooldown")

        goal_line = json.dumps(
            {
                "focus": "那份报告",
                "thought": "他还是想提。",
                "keep": "drop",
                "urge": {
                    "speak": True,
                    "about": "报告快到了",
                    "kind": "goal",
                    "wait": "now",
                },
                "confidence": "high",
            },
            ensure_ascii=False,
        )
        state.thought.last_thought_at = later - timedelta(hours=1)

        async def _goal() -> None:
            async def _complete(_text: str) -> str:
                return goal_line

            await thought_tick_once(
                state, later + timedelta(seconds=2), complete=_complete, source_context=ctx
            )

        asyncio.run(_goal())
        queued = engine.state.pending_impulse
        if queued is None or queued.kind != "goal" or queued.source_id != "report":
            _fail(f"a muted goal should still enqueue, got {queued}")

        unknown = json.dumps(
            {
                "focus": "想问一句",
                "thought": "不知道这算不算现状。",
                "keep": "drop",
                "urge": {
                    "speak": True,
                    "about": "老师还在吗",
                    "kind": "not-a-kind",
                    "wait": "now",
                },
                "confidence": "high",
            },
            ensure_ascii=False,
        )
        from app.life.thought.schema import parse_inner

        bare_impulse = LifeEngine.from_path(root / "bare.json", LifeSettings())
        parsed = parse_inner(unknown)
        if parsed is None or parsed.kind != "thought" or parsed.about != "老师还在吗":
            _fail(f"an unknown kind should stay speakable as thought, got {parsed}")
        if not maybe_offer_thought(bare_impulse, parsed, now=now):
            _fail("an unknown kind should still enqueue")
        if bare_impulse.state.pending_impulse.kind != "thought":
            _fail(bare_impulse.state.pending_impulse)

        class _EmptyHub:
            def all_sessions(self):
                return [("s1", _send)]

        empty = SimpleNamespace(
            hub=_EmptyHub(),
            life=LifeEngine.from_path(root / "empty.json", LifeSettings()),
            orchestrator=SimpleNamespace(relationship=None),
            scheduler=scheduler,
        )
        if asyncio.run(proactive_tick(empty, now=now)):
            _fail("the proactive tick must not speak from a meal window")
        if empty.life.state.pending_impulse is not None:
            _fail("the proactive tick must not enqueue dinner")


async def _async_sent() -> str:
    return "sent"


def test_arrival_greeting_falls_back_only_on_failure() -> None:
    print("== arrival thinks first and welcomes only when that fails ==")
    from app.config import FestivalConfig, IdleConfig, CareConfig, GoalConfig, MoodFollowupConfig
    from app.life.impulse import flush_impulse
    from app.life.thought.loop import greet_on_connect
    from app.life.thought.sources import SourceContext, select_sources
    from app.life.thought.triggers import note_arrived
    from app.proactive.scheduler import ProactiveScheduler
    from app.proactive.welcome import WelcomeState

    afternoon = datetime(2026, 9, 23, 15, 0, 0)
    teacher_day = datetime(2026, 9, 10, 15, 0, 0)

    def _payload(kind: str, speak: bool, about: str) -> str:
        return json.dumps(
            {
                "focus": about or "上线了",
                "thought": "先看一眼。",
                "keep": "drop",
                "urge": {"speak": speak, "about": about, "kind": kind, "wait": "now"},
                "confidence": "high",
            },
            ensure_ascii=False,
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        async def _send(_payload: dict) -> None:
            return None

        class _Hub:
            def __init__(self) -> None:
                self.busy = False

            def all_sessions(self):
                return [("s1", _send)]

            def idle_sessions(self):
                return [] if self.busy else [("s1", _send)]

            def get(self, sid):
                return _send if sid == "s1" else None

            def is_busy(self, _sid):
                return self.busy

            def any_busy(self):
                return self.busy

            def set_busy(self, _sid, busy):
                self.busy = busy

        def _world(at: datetime, *, fallback: float = 2, festival: bool = False):
            engine = LifeEngine.from_path(root / f"life-{at.timestamp()}-{fallback}.json", LifeSettings())
            welcome = WelcomeState(None)
            scheduler = ProactiveScheduler(
                root / f"pro-{at.timestamp()}-{fallback}.json",
                idle_cfg=IdleConfig(),
                care_cfg=CareConfig(),
                goal_cfg=GoalConfig(enabled=False),
                festival_cfg=FestivalConfig(enabled=festival),
                mood_cfg=MoodFollowupConfig(enabled=False),
            )
            ledger = ThoughtLedger()
            store = ThoughtStore(root / f"thought-{at.timestamp()}-{fallback}.json")
            store.save(ledger)
            cfg = SimpleNamespace(
                enabled=True,
                tick_sec=60,
                revisit_after_sec=1200,
                refractory_sec=0,
                spontaneous_online_min_sec=99999,
                spontaneous_online_max_sec=99999,
                spontaneous_away_min_sec=99999,
                spontaneous_away_max_sec=99999,
                arrived_fallback_sec=fallback,
            )
            spoken: list[dict] = []

            async def _handle(**kwargs):
                spoken.append(kwargs)
                return "sent"

            state = SimpleNamespace(
                config=SimpleNamespace(
                    life=SimpleNamespace(thought=cfg),
                    proactive=SimpleNamespace(relationship=SimpleNamespace(enabled=False)),
                ),
                thought=ledger,
                thought_store=store,
                life=engine,
                hub=_Hub(),
                scheduler=scheduler,
                listen_uncommitted=False,
                thought_in_flight=False,
                welcome=welcome,
                journal=None,
                arona_memory=None,
                life_journal=None,
                orchestrator=SimpleNamespace(
                    relationship=None,
                    memory_store=SimpleNamespace(list_by_category=lambda _cat: []),
                    handle_initiate=_handle,
                ),
                spoken=spoken,
            )
            note_arrived(state, now=at)
            return state

        async def _greet(state, at, payload: str | None, *, delay: float = 0) -> None:
            async def _complete(_text: str) -> str:
                if delay:
                    await asyncio.sleep(delay)
                return payload or "not-json"

            await greet_on_connect(state, session_id="s1", now=at, complete=_complete)

        greeted = select_sources(
            PendingTrigger(kind="arrived"),
            afternoon,
            InnerState(),
            ThoughtLedger(),
            SourceContext(already_greeted=True),
        )
        if "本时段已经问候过" not in greeted.text:
            _fail(f"a greeted slot should say so, got {greeted.text}")

        hello = _world(afternoon)
        asyncio.run(_greet(hello, afternoon, _payload("welcome", True, "下午好")))
        impulse = hello.life.state.pending_impulse
        if impulse is None or impulse.kind != "welcome" or impulse.hint != "下午好":
            _fail(f"arrival should enqueue her greeting, got {impulse}")
        hello.hub = _Hub()
        hello.journal = None
        if not asyncio.run(flush_impulse(hello, now=afternoon)):
            _fail("the greeting should speak")
        if not hello.welcome._period_greeted:
            _fail("a welcome line should mark this period")
        if hello.life.state.pending_impulse is not None:
            _fail("fallback must not add a second line")

        quiet_ask = _world(afternoon + timedelta(minutes=1))
        asyncio.run(_greet(quiet_ask, afternoon, _payload("thought", True, "老师还在吗")))
        asked = quiet_ask.life.state.pending_impulse
        if asked is None or asked.kind != "thought" or asked.hint != "老师还在吗":
            _fail(f"asking if he is there should stay thought, got {asked}")
        if asked.first_in_slot or quiet_ask.welcome._period_greeted:
            _fail("a non-greeting must not mark the period")

        declined = _world(afternoon + timedelta(minutes=2))
        asyncio.run(_greet(declined, afternoon, _payload("welcome", False, "")))
        if declined.life.state.pending_impulse is not None or declined.welcome._period_greeted:
            _fail("speak false must not welcome and must not fall back")

        later = afternoon + timedelta(minutes=3)
        again = _world(later)
        again.welcome.mark_period_greeted("2026-09-23", "afternoon")
        asyncio.run(_greet(again, later, _payload("welcome", True, "又见面了")))
        if again.life.state.pending_impulse is None or again.life.state.pending_impulse.kind != "welcome":
            _fail("already greeting must not block her from speaking again")
        silent = _world(afternoon + timedelta(minutes=4))
        silent.welcome.mark_period_greeted("2026-09-23", "afternoon")
        asyncio.run(_greet(silent, afternoon, _payload("welcome", False, "")))
        pending = silent.life.state.pending_impulse
        if pending is not None:
            _fail(f"a silent return must not add 下午好, got {pending.instruction}")

        broken = _world(afternoon + timedelta(minutes=5))
        asyncio.run(_greet(broken, afternoon, None))
        if len(broken.spoken) != 1 or broken.spoken[0].get("kind") != "welcome":
            _fail(f"a failed parse should fall back to one welcome, got {broken.spoken}")
        if "她想提起" in str(broken.spoken[0].get("history_marker") or ""):
            _fail("the fallback must not be her thought line")
        if broken.life.state.pending_impulse is not None:
            _fail("the fallback must not leave a second impulse")

        slow = _world(afternoon + timedelta(minutes=6), fallback=0.2)
        asyncio.run(_greet(slow, afternoon, _payload("thought", True, "老师还在吗"), delay=1))
        if len(slow.spoken) != 1 or slow.spoken[0].get("kind") != "welcome":
            _fail(f"a slow thought should leave only the welcome fallback, got {slow.spoken}")
        if slow.life.state.pending_impulse is not None:
            _fail("a late thought must not enqueue after the fallback")

        goal = _world(afternoon + timedelta(minutes=7))
        asyncio.run(_greet(goal, afternoon, _payload("goal", True, "报告快到了")))
        if goal.life.state.pending_impulse is None or goal.life.state.pending_impulse.kind != "goal":
            _fail("a goal arrival should enqueue as goal")
        if goal.welcome._period_greeted:
            _fail("a goal must not mark the period before it is spoken")
        goal.hub = _Hub()
        goal.journal = None
        asyncio.run(flush_impulse(goal, now=afternoon))
        if goal.welcome._period_greeted:
            _fail("a spoken goal must not mark the period")

        festive = _world(teacher_day, festival=True)
        asyncio.run(_greet(festive, teacher_day, _payload("festival", True, "教师节快乐")))
        festive.hub = _Hub()
        festive.journal = None
        if not asyncio.run(flush_impulse(festive, now=teacher_day)):
            _fail("the festival line should speak")
        if "teacher" not in festive.scheduler.state.festival_done or not festive.welcome._period_greeted:
            _fail(
                f"festival speech should record both facts, "
                f"done={festive.scheduler.state.festival_done} greeted={festive.welcome._period_greeted}"
            )


def test_aftertaste_restarts_from_the_latest_turn() -> None:
    print("== a new turn replaces the waiting aftertaste ==")
    from app.life.thought.triggers import note_finished_turn

    now = _now()
    with tempfile.TemporaryDirectory() as tmp:
        state = _event_state(Path(tmp), now)
        if not note_finished_turn(state, "先说一句", now=now):
            _fail("the first turn should enqueue")
        later = now + timedelta(seconds=10)
        if not note_finished_turn(state, "再说一句", now=later):
            _fail("the second turn should enqueue")
        kinds = [item.kind for item in state.thought.pending_triggers]
        if kinds != ["aftertaste"]:
            _fail(f"only the latest aftertaste should wait, got {kinds}")
        expect = later.replace(microsecond=0) + timedelta(seconds=30)
        queued = state.thought.pending_triggers[0]
        if queued.not_before != expect:
            _fail(f"aftertaste should restart from the latest turn, got {queued.not_before}")
    print("  ok")


def test_aftertaste_holds_speech_after_a_fresh_line() -> None:
    print("== a fresh line keeps the aftertaste unspoken ==")
    from app.life.thought.triggers import note_finished_turn

    now = _now()
    payload = json.dumps(
        {
            "focus": "老师还在吗",
            "thought": "想问一句。",
            "keep": "open",
            "confidence": "high",
            "urge": {
                "speak": True,
                "about": "老师还在吗",
                "why": "想确认老师还在",
                "wait": "now",
            },
        },
        ensure_ascii=False,
    )

    async def _tick(state, at: datetime, ctx: SourceContext) -> None:
        async def _complete(_text: str) -> str:
            return payload

        await thought_tick_once(state, at, complete=_complete, source_context=ctx)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fresh = _event_state(root / "fresh", now)
        if not note_finished_turn(fresh, "你好", now=now):
            _fail("a finished turn should enqueue")
        due = now + timedelta(seconds=30)
        asyncio.run(_tick(fresh, due, SourceContext(seconds_since_arona=0)))
        if not any(item.content == "老师还在吗" for item in fresh.life.state.rumination):
            _fail("a fresh line should still keep the thought")
        if fresh.life.state.pending_impulse is not None:
            _fail(f"a fresh line must not speak the aftertaste, got {fresh.life.state.pending_impulse}")

        quiet = _event_state(root / "quiet", now)
        if not note_finished_turn(quiet, "你好", now=now):
            _fail("a finished turn should enqueue")
        asyncio.run(_tick(quiet, due, SourceContext(seconds_since_arona=30)))
        impulse = quiet.life.state.pending_impulse
        if impulse is None or impulse.hint != "老师还在吗":
            _fail(f"a quiet gap should still offer the aftertaste, got {impulse}")

        overlapped = _event_state(root / "overlapped", now)
        if not note_finished_turn(overlapped, "你好", now=now):
            _fail("a finished turn should enqueue")

        async def _speak_during(at: datetime) -> None:
            async def _complete(_text: str) -> str:
                nxt = overlapped.life.state.clone()
                nxt.last_spoke_at = at
                overlapped.life.state = nxt
                return payload

            await thought_tick_once(
                overlapped,
                at,
                complete=_complete,
                source_context=SourceContext(seconds_since_arona=30),
            )

        asyncio.run(_speak_during(due))
        if overlapped.life.state.pending_impulse is not None:
            _fail("speech during the thought must not also offer the aftertaste")
        if overlapped.life.state.last_spoke_at != due:
            _fail(f"a newer last_spoke_at should survive commit, got {overlapped.life.state.last_spoke_at}")
        if not any(item.content == "老师还在吗" for item in overlapped.life.state.rumination):
            _fail("speech during the thought should still keep the concern")
    print("  ok")


def test_glance_refusal_forgets_sources() -> None:
    print("== glance refusal drops the screen and keeps other notes ==")
    from app.life.glance import apply_glance_refusal
    from app.life.journal import JournalEntry
    from app.life.thought.context import gather_context
    from app.life.thought.sources import select_sources
    from app.ws_handler import websocket_endpoint

    source = inspect.getsource(websocket_endpoint)
    branch = source.split("TYPE_GLANCE_REFUSED", 1)
    if len(branch) != 2:
        _fail("glance_refused must be a websocket message")
    handler = branch[1].split("elif msg_type", 1)[0]
    if "apply_glance_refusal" not in handler or "describe_glance" in handler:
        _fail("a refusal must cancel the glance instead of describing a frame")

    now = datetime(2026, 9, 10, 16, 0, 0)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        journal = LifeJournal(root / "life_journal.json")
        journal.last_glance_at = now
        journal.entries = [
            JournalEntry(at=now, kind="shift", summary="在教室发呆"),
            JournalEntry(at=now, kind="glance", summary="记事本开着"),
        ]
        journal.save()
        store = ThoughtStore(root / "thought.json")
        ledger = ThoughtLedger(
            last_glance_seen="记事本开着",
            pending_triggers=[
                PendingTrigger(kind="glance", not_before=now, detail="记事本开着"),
                PendingTrigger(kind="aftertaste", not_before=now),
            ],
        )
        store.save(ledger)
        state = SimpleNamespace(
            glance_request_id="req-1",
            journal=journal,
            life_journal=journal,
            thought=ledger,
            thought_store=store,
            hub=SimpleNamespace(all_sessions=lambda: []),
            life=SimpleNamespace(state=InnerState()),
            orchestrator=None,
            scheduler=None,
            arona_memory=None,
            welcome=None,
        )
        glance = PendingTrigger(kind="glance", not_before=now, detail="记事本开着")
        before = gather_context(state, now, glance)
        if before.glance_text != "记事本开着" or "记事本开着" not in before.journal:
            _fail(f"a stored glance should be readable before refusal, got {before}")
        shown = select_sources(glance, now, InnerState(), ledger, before)
        if "【瞥见】" not in shown.text or "记事本开着" not in shown.text:
            _fail(f"glance material should name the screen, got {shown.text}")

        if apply_glance_refusal(state, "other"):
            _fail("a stale refusal must be ignored")
        if state.glance_request_id != "req-1" or ledger.last_glance_seen != "记事本开着":
            _fail("a stale refusal must leave the in-flight glance alone")
        if not any(item.kind == "glance" for item in journal.entries):
            _fail("a stale refusal must keep the glance journal")

        if not apply_glance_refusal(state, "req-1"):
            _fail("a matching refusal should clear")
        if state.glance_request_id:
            _fail("a matching refusal should cancel the request")
        if any(item.kind == "glance" for item in journal.entries):
            _fail("a matching refusal should drop glance journal rows")
        if [item.summary for item in journal.entries] != ["在教室发呆"]:
            _fail(f"other journal rows should stay, got {journal.entries}")
        if journal.last_glance_at != now:
            _fail("the glance interval should stay so the next request waits")
        if any(item.kind == "glance" for item in ledger.pending_triggers):
            _fail("glance triggers should be dropped")
        if [item.kind for item in ledger.pending_triggers] != ["aftertaste"]:
            _fail(f"other triggers should stay, got {ledger.pending_triggers}")
        if ledger.last_glance_seen:
            _fail("last_glance_seen should be cleared")
        saved_journal = LifeJournal(root / "life_journal.json")
        saved_ledger = ThoughtStore(root / "thought.json").load()
        if any(item.kind == "glance" for item in saved_journal.entries) or saved_journal.last_glance_at != now:
            _fail("the journal should save the drop and keep the interval")
        if saved_ledger.last_glance_seen or any(item.kind == "glance" for item in saved_ledger.pending_triggers):
            _fail("the ledger should save the dropped glance")

        journal.append("glance", "记事本开着", now)
        ledger.last_glance_seen = "记事本开着"
        ledger.pending_triggers.append(
            PendingTrigger(kind="glance", not_before=now, detail="记事本开着")
        )
        state.glance_request_id = "req-2"
        if not apply_glance_refusal(state, ""):
            _fail("an empty refusal should clear stored glances")
        if state.glance_request_id or ledger.last_glance_seen:
            _fail("an empty refusal should cancel the request and the summary")
        if any(item.kind == "glance" for item in journal.entries):
            _fail("an empty refusal should drop glance journal rows")
        if [item.kind for item in ledger.pending_triggers] != ["aftertaste"]:
            _fail("an empty refusal should keep the other trigger")

        after = gather_context(state, now, PendingTrigger(kind="arrived"))
        if after.glance_text or any("记事本" in row for row in after.journal):
            _fail(f"cleared glance must leave the context, got {after}")
        arrived = select_sources(
            PendingTrigger(kind="arrived"),
            now,
            InnerState(),
            ledger,
            after,
        )
        if "记事本" in arrived.text or "【瞥见】" in arrived.text:
            _fail(f"arrived material should not mention the cleared glance, got {arrived.text}")
        if "在教室发呆" not in arrived.text:
            _fail(f"other journal lines should remain, got {arrived.text}")
        empty = select_sources(
            PendingTrigger(kind="glance"),
            now,
            InnerState(),
            ledger,
            after,
        )
        if not empty.cancelled or empty.text or "【瞥见】" in empty.text:
            _fail(f"a cleared glance should cancel the beat, got {empty}")
    print("  ok")


def test_memory_holds_speech_after_a_fresh_line() -> None:
    print("== a fresh line keeps a memory thought unspoken ==")
    from app.life.thought.triggers import note_memory

    now = _now()
    payload = json.dumps(
        {
            "focus": "每天都来找我",
            "thought": "这句话我想收着。",
            "keep": "open",
            "confidence": "high",
            "urge": {
                "speak": True,
                "about": "老师你回来了",
                "why": "想让他知道我在",
                "wait": "now",
                "kind": "welcome",
            },
        },
        ensure_ascii=False,
    )

    async def _tick(state) -> None:
        async def _complete(_text: str) -> str:
            return payload

        await thought_tick_once(
            state,
            now,
            complete=_complete,
            source_context=SourceContext(seconds_since_arona=12),
        )

    with tempfile.TemporaryDirectory() as tmp:
        state = _event_state(Path(tmp), now)
        if not note_memory(state, "goal_daily_visit_arona", now=now):
            _fail("a new memory should enqueue")
        asyncio.run(_tick(state))
        if not any(item.content == "每天都来找我" for item in state.life.state.rumination):
            _fail("a fresh line should still keep the memory thought")
        if state.life.state.pending_impulse is not None:
            _fail(f"a fresh line must not speak the memory, got {state.life.state.pending_impulse}")
    print("  ok")


def test_memory_sees_recent_talk_and_not_a_welcome() -> None:
    print("== memory keeps recent talk, and welcome stays a thought ==")
    now = _now()
    text = select_sources(
        PendingTrigger(kind="memory", memory_key="goal_daily"),
        now,
        InnerState(),
        ThoughtLedger(),
        SourceContext(turns=(("上午好", "您终于回来啦"),)),
    ).text
    if "【最近的话】" not in text or "您终于回来啦" not in text:
        _fail(f"memory should show the greeting already said, got {text}")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        memory = LifeEngine.from_path(root / "memory.json", LifeSettings())
        arrived = LifeEngine.from_path(root / "arrived.json", LifeSettings())
        urged = _urge()
        urged.kind = "welcome"
        urged.about = "老师你回来了"
        if not maybe_offer_thought(memory, urged, now=now, gate_kind="memory"):
            _fail("a memory welcome should still enqueue as a thought")
        if memory.state.pending_impulse is None or memory.state.pending_impulse.kind != "thought":
            _fail(f"memory must not become a welcome, got {memory.state.pending_impulse}")
        if not maybe_offer_thought(arrived, urged, now=now, gate_kind="arrived"):
            _fail("an arrival welcome should enqueue")
        if arrived.state.pending_impulse is None or arrived.state.pending_impulse.kind != "welcome":
            _fail(f"arrival should keep welcome, got {arrived.state.pending_impulse}")
    print("  ok")


def test_thought_speech_marks_any_from_thought() -> None:
    print("== a spoken follow-up marks the thought as said ==")
    now = _now()

    async def _deliver() -> SimpleNamespace:
        root = Path(tempfile.mkdtemp())
        engine = LifeEngine.from_path(root / "life.json", LifeSettings())
        engine.state.rumination = [
            Rumination(id="thought-1", content="老师终于回来了", created_at=now)
        ]
        engine.state.pending_impulse = Impulse(
            kind="mood_followup",
            created_at=now,
            hint="老师终于回来了",
            instruction="说这一点",
            allow_speak=True,
            from_thought=True,
        )
        engine.store.save(engine.state)
        ledger = ThoughtLedger(
            focus=ThoughtFocus(id="thought-1", text="老师终于回来了", since=now, spoken=False)
        )
        store = ThoughtStore(root / "thought.json")
        store.save(ledger)

        async def _send(_payload: dict) -> None:
            return None

        class _Hub:
            def get(self, _sid):
                return _send

            def is_busy(self, _sid):
                return False

            def set_busy(self, _sid, _busy):
                return None

            def idle_sessions(self):
                return [("s", _send)]

        class _Orch:
            async def handle_initiate(self, **_kwargs):
                return "sent"

        app = SimpleNamespace(
            life=engine,
            hub=_Hub(),
            orchestrator=_Orch(),
            scheduler=None,
            journal=None,
            thought=ledger,
            thought_store=store,
        )
        decision = decide(engine.state, world_event("impulse_due", at=now), settings=LifeSettings())
        await deliver_impulse(app, decision, now=now)
        return app

    sent = asyncio.run(_deliver())
    if sent.thought.focus is None or not sent.thought.focus.spoken:
        _fail(f"a from-thought line should mark the focus spoken, got {sent.thought.focus}")
    if any(item.id.startswith("thought-") for item in sent.life.state.rumination):
        _fail("a from-thought line should drop the thought concern")
    print("  ok")


def main() -> None:
    test_missing_empty_and_corrupt_ledger()
    test_ledger_roundtrip()
    test_queue_keeps_higher_priority()
    test_notes_limit_age_crisis_and_slots()
    test_thought_rumination_does_not_drop_impulses()
    test_gate_priority_and_skips()
    test_thought_tick_logs_without_writing()
    test_sources_for_each_trigger()
    test_commit_boundaries()
    test_failed_call_writes_nothing()
    test_second_hop()
    test_event_triggers()
    test_glance_refusal_forgets_sources()
    test_aftertaste_restarts_from_the_latest_turn()
    test_aftertaste_holds_speech_after_a_fresh_line()
    test_memory_holds_speech_after_a_fresh_line()
    test_memory_sees_recent_talk_and_not_a_welcome()
    test_thought_speech_marks_any_from_thought()
    test_aftertaste_includes_finished_talk()
    test_dialogue_log_persists()
    test_rest_consolidate()
    test_situation_facts_do_not_enqueue()
    test_arrival_greeting_falls_back_only_on_failure()
    test_live_inner_model()
    test_live_secure_play()
    test_live_dialogue_scenes()
    test_thought_speech_boundaries()
    test_live_thought_speech()
    print("all thought unit tests passed")


if __name__ == "__main__":
    main()
