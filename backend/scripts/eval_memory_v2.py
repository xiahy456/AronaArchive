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

"""Scripted end-to-end checks for memory_v2. No network.

Run from backend/:
  python scripts/eval_memory_v2.py
  python scripts/eval_memory_v2.py --json-out data/memory_v2_eval.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import MemoryV2Config, MemoryV2StorageConfig  # noqa: E402
from app.memory_v2 import MemoryV2  # noqa: E402

DAY = 86400


def _memory(tmp: Path) -> MemoryV2:
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
    memory.scanner._injected_complete = True
    memory.scanner.pending_commitment = lambda: False
    memory.scanner.offer = lambda _payload: True
    memory.extractor._injected_complete = True
    return memory


async def _scenario_trip(memory: MemoryV2) -> dict[str, Any]:
    start = 1_761_000_000.0  # inside 2026-10
    memory.states.upsert(
        key="location",
        value="老师在深圳出差",
        valid_from=start,
        valid_until=start + DAY,
        importance=6,
        recorded_at=start,
    )
    during = "老师在深圳出差" in memory.states.live(start + 3600)
    after = "老师在深圳出差" in memory.states.live(start + 2 * DAY)
    return {"resident_during": during, "gone_after_expiry": not after, "ok": during and not after}


async def _scenario_noodles(memory: MemoryV2) -> dict[str, Any]:
    async def complete(model: str, system: str, user: str, timeout: float) -> dict:
        del model, user, timeout
        if "已经发生" in system:
            return {
                "events": [
                    {
                        "occurred_at": "2026-10-28T12:00:00",
                        "importance": 5,
                        "summary": "老师2026年10月28日中午打算吃粿条。",
                    }
                ]
            }
        return {"states": [], "commitments": []}

    memory.extractor._complete = complete
    # Noon plan spoken in the morning is still in the future relative to 08:00.
    memory.extractor._clock = lambda: __import__("datetime").datetime(2026, 10, 28, 8, 0, 0)
    await memory.extractor.process(
        [{"role": "user", "content": "中午打算吃粿条", "time": "2026-10-28T08:00:00", "method": "direct"}]
    )
    hits = memory.search_events("粿条", k=3)
    return {"recalled": [event.summary for event in hits], "ok": not hits}


async def _scenario_commitments(memory: MemoryV2) -> dict[str, Any]:
    now = 1_762_000_000.0
    memory.scanner._clock = lambda: now

    async def extract(model: str, system: str, user: str, timeout: float) -> dict:
        del model, system, user, timeout
        return {
            "commitments": [
                {
                    "what": "老师要阿洛娜每天晚饭后提醒吃药。提起时间是晚饭后，频率是一天一次。",
                    "current": "老师2026年10月30日20:15说出了这件事。",
                }
            ]
        }

    memory.extractor._complete = extract
    for _ in range(3):
        await memory.extractor.process(
            [{"role": "user", "content": "希望每天提醒我吃药", "time": "t", "method": "direct"}]
        )
    active = memory.commitments.active()
    one_row = len(active) == 1

    phase = {"name": "remind", "text": ""}

    async def scan(model: str, prompt: str, timeout: float) -> dict:
        del model, prompt, timeout
        if phase["name"] != "remind":
            return {
                "inject": [],
                "edits": [{"id": active[0].id, "current": phase["text"]}],
                "next_after_sec": 14400,
            }
        return {"inject": [active[0].id], "edits": [], "next_after_sec": 3600}

    memory.scanner._complete = scan
    memory.scanner.dialogue = lambda _since: []
    for _ in range(4):
        await memory.scanner.scan_once(now)
        now += 3600
    item = memory.commitments.get(active[0].id)
    reminded = item is not None and 1 <= item.inject_count <= 12
    scans = [row for row in memory.trace.read_rows() if row.get("kind") == "scan" and row.get("inject")]
    paired = reminded and item is not None and len(scans) == item.inject_count

    phase["name"] = "ack"
    phase["text"] = "老师2026年10月31日说已经吃过了。"
    await memory.scanner.scan_once(now)
    item = memory.commitments.get(active[0].id)
    ate = item is not None and "吃过了" in item.current and item.active == 1
    before = item.inject_count if item else 0
    await memory.scanner.scan_once(now + 3600)
    item = memory.commitments.get(active[0].id)
    stopped = item is not None and item.inject_count == before

    phase["name"] = "pause"
    phase["text"] = "老师说这周先停一下这件事。"
    await memory.scanner.scan_once(now + 7200)
    item = memory.commitments.get(active[0].id)
    paused = item is not None and item.active == 1 and "先停" in item.current

    phase["name"] = "stop"
    phase["text"] = "老师2026年10月31日说不用再提醒这件事。"
    await memory.scanner.scan_once(now + 10_000)
    item = memory.commitments.get(active[0].id)
    declined = item is not None and item.active == 1 and "不用再提醒" in item.current

    memory.db.call(
        lambda conn, cid=active[0].id, stamp=now - 31 * DAY: conn.execute(
            """
            UPDATE commitments
            SET inject_count = inject_count + 1, last_helpful_injected_at = ?
            WHERE id = ?
            """,
            (stamp, cid),
        )
    )
    await memory.scanner.scan_once(now + 20_000)
    item = memory.commitments.get(active[0].id)
    retired = item is not None and item.active == 0
    expired = any(row.get("kind") == "commit_expired" for row in memory.trace.read_rows())
    return {
        "one_active_row": one_row,
        "reminded": reminded,
        "scans_match_injects": paired,
        "acked": ate,
        "quiet_after_ack": stopped,
        "paused_not_retired": paused,
        "declined_still_active": declined,
        "expired_after_31_days": retired and expired,
        "ok": all((one_row, reminded, paired, ate, stopped, paused, declined, retired, expired)),
    }


async def evaluate() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        trip = await _scenario_trip(_memory(root / "trip"))
        noodles = await _scenario_noodles(_memory(root / "noodles"))
        commitments = await _scenario_commitments(_memory(root / "commit"))
    report = {"trip": trip, "noodles": noodles, "commitments": commitments}
    report["ok"] = all(section.get("ok") for section in report.values() if isinstance(section, dict))
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="memory_v2 端到端评估")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args(argv)
    report = asyncio.run(evaluate())
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        target = Path(args.json_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    if not report.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
