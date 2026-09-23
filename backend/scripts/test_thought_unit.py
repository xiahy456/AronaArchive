"""Unit tests for the thought ledger and Arona's own notes (no GGUF).

Run from backend/:
  python scripts/test_thought_unit.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

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


def main() -> None:
    test_missing_empty_and_corrupt_ledger()
    test_ledger_roundtrip()
    test_queue_keeps_higher_priority()
    test_notes_limit_age_crisis_and_slots()
    test_thought_rumination_does_not_drop_impulses()
    print("all thought unit tests passed")


if __name__ == "__main__":
    main()
