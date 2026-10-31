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

"""Parallel extract, per-layer retry, commitment dedup, and no-key shutdown.

Run from backend/:
  python scripts/test_memory_v2_extract_unit.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import MemoryV2Config, MemoryV2StorageConfig  # noqa: E402
from app.memory_v2 import MemoryV2  # noqa: E402
from app.memory_v2.extract import prepare_window  # noqa: E402


def _fail(message: str) -> None:
    raise AssertionError(message)


def _memory(tmp: Path) -> MemoryV2:
    storage = MemoryV2StorageConfig(
        db_path=str(tmp / "memory.db"),
        events_fts=str(tmp / "events_fts"),
        chroma_path=str(tmp / "chroma"),
    )
    return MemoryV2(
        MemoryV2Config(storage=storage),
        backend_dir=tmp,
        trace_path=tmp / "trace.jsonl",
        token_budget_state=400,
    )


def test_window_keeps_proactive_and_drops_crisis() -> None:
    print("== extract window ==")
    rows = prepare_window(
        [
            {"role": "user", "content": "……", "time": "t", "method": "direct"},
            {"role": "assistant", "content": "老师，吃饭了吗", "time": "t", "method": "direct"},
            {"role": "user", "content": "我想死", "time": "t", "method": "direct"},
        ]
    )
    texts = [row["content"] for row in rows]
    if "我想死" in texts:
        _fail("crisis lines must not enter the extract window")
    if "老师，吃饭了吗" not in texts or "……" not in texts:
        _fail(f"silent and proactive lines must stay: {texts}")
    print("  ok")


def test_parallel_retry_and_commitment_rules() -> None:
    print("== parallel extract ==")

    async def _run() -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            memory = _memory(Path(tmp))
            memory.commitments.insert(
                what="老师要阿洛娜每天晚饭后提醒吃药。提起时间是晚饭后，频率是一天一次。",
                current="老师2026年10月30日20:15说出了这件事。",
                created_at=1_000.0,
            )
            active = {"n": 0, "peak": 0}
            event_calls = {"n": 0}

            async def complete(model: str, system: str, user: str, timeout: float) -> dict:
                del model, user, timeout
                active["n"] += 1
                active["peak"] = max(active["peak"], active["n"])
                await asyncio.sleep(0.05)
                active["n"] -= 1
                if "已经发生" in system:
                    event_calls["n"] += 1
                    if event_calls["n"] < 3:
                        raise RuntimeError("event layer down")
                    return {
                        "events": [
                            {
                                "occurred_at": "2026-10-28T18:00:00",
                                "importance": 11,
                                "summary": "老师2026年10月28日去了广州。他先去了天河区的展会。",
                            }
                        ]
                    }
                if "托付" in system:
                    return {
                        "commitments": [
                            {
                                "what": "老师要阿洛娜每天晚饭后提醒吃药。提起时间是晚饭后，频率是一天一次。",
                                "current": "老师2026年10月31日又说了一遍。",
                            },
                            {
                                "what": "老师要阿洛娜明天提醒他交报告。",
                                "current": "老师2026年10月31日说出了这件事。",
                            },
                        ]
                    }
                return {"states": [{"key": "location", "value": "老师在广州", "importance": 5}]}

            memory.extractor._injected_complete = True
            memory.extractor._complete = complete
            memory.extractor.retry_max = 2
            window = [
                {
                    "role": "user",
                    "content": "我到广州了",
                    "time": "2026-10-28T18:00:00",
                    "method": "direct",
                }
            ]
            await memory.extractor.process(window)
            if active["peak"] < 3:
                _fail(f"three layers should overlap, peak={active['peak']}")
            if event_calls["n"] != 3:
                _fail(f"only the event layer should retry, calls={event_calls['n']}")
            if len(memory.commitments.active()) != 1:
                _fail("duplicate what and dated what must not add rows")
            events = memory.search_events("广州", k=3)
            if not events or events[0].importance != 10:
                _fail(f"importance 11 should clamp to 10, got {events}")
            if "老师在广州" not in memory.live_states():
                _fail("state sentence should be resident")

            bare = _memory(Path(tmp) / "nokey")
            bare.extractor.api_key = ""
            bare.extractor._injected_complete = False
            before = len(bare.events.get_many([]))
            await bare.extractor.process(window)
            if bare.events.search_ids("广州", 5):
                _fail("no API key must not write events")
            del before

    asyncio.run(_run())
    print("  ok")


def main() -> None:
    test_window_keeps_proactive_and_drops_crisis()
    now = datetime(2026, 10, 28, 18, 0, 0)
    del now
    test_parallel_retry_and_commitment_rules()
    print("all extract checks passed")


if __name__ == "__main__":
    main()
