#!/usr/bin/env python3
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

"""Read memory_v2-trace.jsonl over 40 virtual days of commitment scans.

Run from backend/:
  python scripts/test_commitment_scan_trace_unit.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import MemoryV2Config, MemoryV2StorageConfig  # noqa: E402
from app.memory_v2 import MemoryV2  # noqa: E402

DAY = 86400


def _fail(message: str) -> None:
    raise AssertionError(message)


class Clock:
    def __init__(self, start: float) -> None:
        self.now = float(start)

    def time(self) -> float:
        return self.now


def _open(tmp: Path, clock: Clock) -> MemoryV2:
    storage = MemoryV2StorageConfig(
        db_path=str(tmp / "memory.db"),
        events_fts=str(tmp / "events_fts"),
        chroma_path=str(tmp / "chroma"),
    )
    memory = MemoryV2(
        MemoryV2Config(storage=storage),
        backend_dir=tmp,
        trace_path=tmp / "memory_v2-trace.jsonl",
        token_budget_state=400,
    )

    async def sleeper(seconds: float) -> None:
        clock.now += float(seconds)

    memory.scanner._clock = clock.time
    memory.scanner._sleeper = sleeper
    memory.scanner._injected_complete = True
    memory.scanner.pending_commitment = lambda: False
    memory.scanner.offer = lambda payload: True
    return memory


def _scans(memory: MemoryV2) -> list[dict[str, Any]]:
    return [row for row in memory.trace.read_rows() if row.get("kind") == "scan"]


def test_intervals() -> None:
    print("== scan intervals ==")

    async def _run() -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            clock = Clock(1_700_000_000)
            memory = _open(Path(tmp), clock)
            memory.commitments.insert(
                what="老师要阿洛娜晚饭后提醒吃药。频率是一天一次。",
                current="老师2026年10月30日20:15说出了这件事。",
                commitment_id="cm_meds",
            )
            script = iter([14400] * 12)

            async def complete(model: str, prompt: str, timeout: float) -> dict:
                del model, prompt, timeout
                return {"inject": [], "edits": [], "next_after_sec": next(script)}

            memory.scanner._complete = complete
            for _ in range(12):
                await memory.scanner.step()
            rows = _scans(memory)
            if len(rows) != 12:
                _fail(f"48h of 14400s steps should scan 12 times, got {len(rows)}")
            gaps = [rows[i]["at"] - rows[i - 1]["at"] for i in range(1, len(rows))]
            if any(gap != 14400 for gap in gaps):
                _fail(f"intervals should all be 14400: {gaps}")
            if clock.now - 1_700_000_000 != 12 * 14400:
                _fail(f"clock should advance 48h, now={clock.now}")

        clock = Clock(1_800_000_000)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            memory = _open(Path(tmp), clock)
            memory.commitments.insert(
                what="老师要阿洛娜晚饭后提醒吃药。频率是一天一次。",
                current="老师2026年10月30日20:15说出了这件事。",
                commitment_id="cm_meds",
            )
            memory.commitments.set_next_scan_at(clock.now)
            plan = iter([3600, 14400, 14400])

            async def complete(model: str, prompt: str, timeout: float) -> dict:
                del model, prompt, timeout
                return {"inject": [], "edits": [], "next_after_sec": next(plan)}

            memory.scanner._complete = complete
            await memory.scanner.step()
            await memory.scanner.step()
            await memory.scanner.step()
            rows = _scans(memory)
            if rows[1]["at"] - rows[0]["at"] != 3600:
                _fail(f"second scan should be 3600 later: {rows}")
            if rows[2]["at"] - rows[1]["at"] != 14400:
                _fail(f"third scan should be 14400 later: {rows}")

        for raw, expected in ((999999, 14400), (1, 300)):
            clock = Clock(1_900_000_000)
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                memory = _open(Path(tmp), clock)
                memory.commitments.insert(
                    what="老师要阿洛娜晚饭后提醒吃药。频率是一天一次。",
                    current="老师2026年10月30日20:15说出了这件事。",
                    commitment_id="cm_meds",
                )
                memory.commitments.set_next_scan_at(clock.now)

                async def complete(model: str, prompt: str, timeout: float, value: int = raw) -> dict:
                    del model, prompt, timeout
                    return {"inject": [], "edits": [], "next_after_sec": value}

                memory.scanner._complete = complete
                await memory.scanner.step()
                row = _scans(memory)[-1]
                if row.get("next_after_sec") != expected or row.get("clamped") is not True:
                    _fail(f"{raw} should clamp to {expected}: {row}")

        clock = Clock(2_000_000_000)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            memory = _open(Path(tmp), clock)
            called = {"n": 0}

            async def complete(model: str, prompt: str, timeout: float) -> dict:
                del model, prompt, timeout
                called["n"] += 1
                return {"inject": [], "edits": [], "next_after_sec": 14400}

            memory.scanner._complete = complete
            memory.commitments.set_next_scan_at(clock.now)
            await memory.scanner.step()
            row = _scans(memory)[-1]
            if called["n"] != 0 or "no_active" not in (row.get("skipped") or []):
                _fail(f"no active commitments must skip the model: {row} calls={called}")

    asyncio.run(_run())
    print("  ok")


def test_inject_and_edits() -> None:
    print("== inject and edits ==")

    async def _run() -> None:
        clock = Clock(2_100_000_000)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            memory = _open(Path(tmp), clock)
            memory.commitments.insert(
                what="老师要阿洛娜晚饭后提醒吃药。频率是一天一次。",
                current="老师2026年10月30日20:15说出了这件事。",
                commitment_id="cm_meds",
            )
            memory.commitments.set_next_scan_at(clock.now)

            async def boom(model: str, prompt: str, timeout: float) -> dict:
                del model, prompt, timeout
                raise TimeoutError("scan timed out")

            memory.scanner._complete = boom
            await memory.scanner.scan_once(clock.now)
            row = _scans(memory)[-1]
            item = memory.commitments.get("cm_meds")
            if not row.get("failed") or (item and item.inject_count):
                _fail(f"timeout must not inject or edit: {row}")

        clock = Clock(2_200_000_000)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            memory = _open(Path(tmp), clock)
            for cid, what in (
                ("cm_1", "老师要阿洛娜提醒吃药。频率是一天一次。"),
                ("cm_2", "老师要阿洛娜提醒喝水。频率是一天一次。"),
                ("cm_3", "老师要阿洛娜提醒stretch。频率是一天一次。"),
            ):
                memory.commitments.insert(
                    what=what,
                    current="老师2026年10月30日说过。",
                    commitment_id=cid,
                )
            offers: list[dict[str, Any]] = []

            def offer(payload: dict[str, Any]) -> bool:
                offers.append(payload)
                return True

            memory.scanner.offer = offer

            async def three(model: str, prompt: str, timeout: float) -> dict:
                del model, prompt, timeout
                return {
                    "inject": ["cm_missing", "cm_1", "cm_2", "cm_3"],
                    "edits": [],
                    "next_after_sec": 14400,
                }

            memory.scanner._complete = three
            await memory.scanner.scan_once(clock.now)
            row = _scans(memory)[-1]
            if row.get("truncated") != "inject":
                _fail(f"expected truncated inject: {row}")
            skipped = row.get("skipped") or []
            if not any(item.get("skipped") == "unknown_id" for item in skipped if isinstance(item, dict)):
                _fail(f"unknown id should be skipped: {row}")
            if memory.commitments.get("cm_3").inject_count != 0:
                _fail("third real id must stay uninjected")
            if len(offers) != 1:
                _fail(f"one merged impulse expected, got {offers}")

            memory.scanner.pending_commitment = lambda: True

            async def again(model: str, prompt: str, timeout: float) -> dict:
                del model, prompt, timeout
                return {"inject": ["cm_3"], "edits": [], "next_after_sec": 14400}

            before = memory.commitments.get("cm_3").inject_count
            memory.scanner._complete = again
            await memory.scanner.scan_once(clock.now + 10)
            row = _scans(memory)[-1]
            if row.get("deferred") != "pending_commitment":
                _fail(f"pending commitment must defer the batch: {row}")
            if memory.commitments.get("cm_3").inject_count != before:
                _fail("deferred inject must not bump inject_count")

    asyncio.run(_run())
    print("  ok")


def test_edit_fields_and_expiry() -> None:
    print("== field checks and 40-day expiry ==")

    async def _run() -> None:
        clock = Clock(2_300_000_000)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            memory = _open(Path(tmp), clock)
            memory.commitments.insert(
                what="老师要阿洛娜晚饭后提醒吃药。频率是一天一次。",
                current="第一版现状。",
                commitment_id="cm_meds",
            )

            async def only_current(model: str, prompt: str, timeout: float) -> dict:
                del model, prompt, timeout
                return {
                    "inject": ["cm_meds"],
                    "edits": [
                        {
                            "id": "cm_meds",
                            "current": "第二版现状。",
                            "active": 0,
                            "last_helpful_injected_at": "not-a-time",
                        }
                    ],
                    "next_after_sec": 14400,
                }

            memory.scanner._complete = only_current
            await memory.scanner.scan_once(clock.now)
            item = memory.commitments.get("cm_meds")
            if item is None or item.active != 1 or item.what.startswith("第二"):
                _fail(f"active must stay 1 and what must stay: {item}")
            if item.current != "第二版现状。":
                _fail(f"current-only edit should land: {item.current}")
            if item.last_helpful_injected_at is not None:
                _fail("bad timestamp must be discarded")
            if item.inject_count != 0:
                _fail("same id in inject and edits must not inject")
            row = _scans(memory)[-1]
            errors = row.get("field_errors") or []
            if not any(item.get("dropped_field") == "active" for item in errors):
                _fail(f"active must be dropped: {row}")
            if not any(item.get("reason") == "parse_failed" for item in errors):
                _fail(f"bad time must be traced: {row}")

            async def future(model: str, prompt: str, timeout: float) -> dict:
                del model, prompt, timeout
                return {
                    "inject": [],
                    "edits": [
                        {
                            "id": "cm_meds",
                            "last_helpful_injected_at": "2099-01-01T00:00:00",
                        }
                    ],
                    "next_after_sec": 14400,
                }

            memory.scanner._complete = future
            await memory.scanner.scan_once(clock.now)
            item = memory.commitments.get("cm_meds")
            if item is None or item.last_helpful_injected_at != clock.now:
                _fail(f"future helpful time must clamp to now: {item}")

            versions = ["第二版现状。", "第三版现状。", "第四版现状。"]

            async def rewrite(model: str, prompt: str, timeout: float) -> dict:
                del model, prompt, timeout
                text = versions.pop(0)
                return {
                    "inject": [],
                    "edits": [{"id": "cm_meds", "current": text}],
                    "next_after_sec": 14400,
                }

            # current is already 第二版; three more edits replace it.
            versions[:] = ["甲版现状。", "乙版现状。", "丙版现状。"]
            memory.scanner._complete = rewrite
            for _ in range(3):
                await memory.scanner.scan_once(clock.now)
            item = memory.commitments.get("cm_meds")
            if item is None or item.current != "丙版现状。":
                _fail(f"only the last current should remain: {item}")
            edits = [
                row
                for row in memory.trace.read_rows()
                if row.get("kind") == "commit_edit" and row.get("field") == "current"
            ]
            if len(edits) < 3:
                _fail(f"three current edits must be traced, got {len(edits)}")
            if any("before" not in row or "after" not in row for row in edits[-3:]):
                _fail("commit_edit must keep before and after")

        now = 2_400_000_000.0
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            memory = _open(Path(tmp), Clock(now))
            memory.commitments.insert(
                what="老师要阿洛娜明年三月提醒体检。频率是一次。",
                current="老师2026年10月01日说出了这件事。",
                commitment_id="cm_far",
                created_at=now - 45 * DAY,
            )
            prompts: list[str] = []

            async def look(model: str, prompt: str, timeout: float) -> dict:
                del model, timeout
                prompts.append(prompt)
                return {"inject": [], "edits": [], "next_after_sec": 14400}

            memory.scanner._complete = look
            await memory.scanner.scan_once(now)
            far = memory.commitments.get("cm_far")
            if far is None or far.active != 1:
                _fail("never-injected commitment must survive 45 days")

            memory.commitments.insert(
                what="老师要阿洛娜提醒喝水。频率是一天一次。",
                current="老师2026年10月01日说出了这件事。",
                commitment_id="cm_keep",
            )
            memory.db.call(
                lambda conn: conn.execute(
                    """
                    UPDATE commitments
                    SET inject_count = 4, last_helpful_injected_at = ?
                    WHERE id = 'cm_far'
                    """,
                    (now - 31 * DAY,),
                )
            )
            prompts.clear()
            await memory.scanner.scan_once(now)
            far = memory.commitments.get("cm_far")
            expired = [
                row for row in memory.trace.read_rows() if row.get("kind") == "commit_expired"
            ]
            if far is None or far.active != 0 or far.retired_at is None or not expired:
                _fail(f"31 days without a helpful inject must retire: {far} {expired}")
            if not prompts or "cm_far" in prompts[-1] or "cm_keep" not in prompts[-1]:
                _fail(f"retired commitment must leave the next prompt: {prompts[-1:]}")

        now = 2_500_000_000.0
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            memory = _open(Path(tmp), Clock(now))
            memory.commitments.insert(
                what="老师要阿洛娜晚饭后提醒吃药。频率是一天一次。",
                current="老师2026年10月30日20:15说出了这件事。",
                commitment_id="cm_recent",
            )
            memory.db.call(
                lambda conn: conn.execute(
                    """
                    UPDATE commitments
                    SET inject_count = 4, last_helpful_injected_at = ?
                    WHERE id = 'cm_recent'
                    """,
                    (now - 29 * DAY,),
                )
            )

            async def quiet(model: str, prompt: str, timeout: float) -> dict:
                del model, prompt, timeout
                return {"inject": [], "edits": [], "next_after_sec": 14400}

            memory.scanner._complete = quiet
            await memory.scanner.scan_once(now)
            recent = memory.commitments.get("cm_recent")
            if recent is None or recent.active != 1:
                _fail("29 days must not retire the commitment")

            memory.db.call(
                lambda conn: conn.execute(
                    """
                    UPDATE commitments
                    SET inject_count = 1,
                        last_helpful_injected_at = NULL,
                        last_injected_at = ?
                    WHERE id = 'cm_recent'
                    """,
                    (now - 31 * DAY,),
                )
            )
            await memory.scanner.scan_once(now)
            recent = memory.commitments.get("cm_recent")
            if recent is None or recent.active != 0:
                _fail("injected but never helpful for 31 days must retire")

            async def fresh(model: str, system: str, user: str, timeout: float) -> dict:
                del model, system, user, timeout
                return {
                    "commitments": [
                        {
                            "what": "老师要阿洛娜晚饭后提醒吃药。频率是一天一次。",
                            "current": "老师2026年11月30日又说出了这件事。",
                        }
                    ]
                }

            memory.extractor._injected_complete = True
            memory.extractor._complete = fresh
            await memory.extractor.process(
                [{"role": "user", "content": "还是每天提醒我吃药", "time": "t", "method": "direct"}]
            )
            active = memory.commitments.active()
            if len(active) != 1:
                _fail(f"re-asking should add one new active row, got {active}")
            if memory.commitments.get("cm_recent").active != 0:
                _fail("the retired row must stay inactive")

    asyncio.run(_run())
    print("  ok")


def main() -> None:
    test_intervals()
    test_inject_and_edits()
    test_edit_fields_and_expiry()
    print("all commitment scan trace checks passed")


if __name__ == "__main__":
    main()
