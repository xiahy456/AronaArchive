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

"""Commitment apply order: cap, conflict, edits before inject, trace of current.

Run from backend/:
  python scripts/test_memory_v2_commitment_unit.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import MemoryV2Config, MemoryV2StorageConfig  # noqa: E402
from app.memory_v2 import MemoryV2  # noqa: E402
from app.memory_v2.prompts import scan_system  # noqa: E402


def _fail(message: str) -> None:
    raise AssertionError(message)


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
    memory.scanner._clock = lambda: 1_700_000_000.0
    memory.scanner._injected_complete = True

    async def _complete(model: str, prompt: str, timeout: float) -> dict:
        del model, prompt, timeout
        return {
            "inject": ["cm_a", "cm_b", "cm_c"],
            "edits": [
                {
                    "id": "cm_a",
                    "what": "老师要阿洛娜晚饭后提醒吃药。频率是一天一次。",
                    "current": "老师2026年10月31日18:40提过一次，老师说要吃的。",
                }
            ],
            "next_after_sec": 1800,
        }

    memory.scanner._complete = _complete
    return memory


def test_apply_order() -> None:
    print("== edits before inject, cap 2, edit wins ==")
    if "老师在场" in scan_system():
        _fail("scan prompt must not mention 老师在场")
    if "将来最近一件" not in scan_system():
        _fail("scan prompt must explain next_after_sec")

    async def _run() -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            memory = _memory(Path(tmp))
            memory.commitments.insert(
                what="旧的吃药提醒。",
                current="老师2026年10月30日20:15说出了这件事。",
                commitment_id="cm_a",
            )
            memory.commitments.insert(
                what="老师要阿洛娜提醒喝水。频率是一天一次。",
                current="老师2026年10月30日说过。",
                commitment_id="cm_b",
            )
            memory.commitments.insert(
                what="老师要阿洛娜提醒stretch。频率是一天一次。",
                current="老师2026年10月30日说过。",
                commitment_id="cm_c",
            )
            seen: dict[str, str] = {}

            def offer(payload: dict) -> bool:
                seen["hint"] = str(payload.get("hint") or "")
                row = memory.commitments.get("cm_a")
                seen["what"] = row.what if row else ""
                return True

            memory.scanner.offer = offer
            memory.scanner.pending_commitment = lambda: False
            await memory.scanner.scan_once(1_700_000_000.0)
            if "旧的吃药提醒" in seen.get("what", ""):
                _fail("edit must land before the inject is built")
            if "cm_a" in seen.get("hint", "") or "吃药" in seen.get("hint", ""):
                _fail("an id that was edited must not also be injected")
            if "喝水" not in seen.get("hint", ""):
                _fail(f"hint should use the injected what, got {seen}")
            row_b = memory.commitments.get("cm_b")
            row_c = memory.commitments.get("cm_c")
            if row_b is None or row_c is None:
                _fail("rows missing")
            injected = [row for row in (row_b, row_c) if row.inject_count]
            if len(injected) != 2 or row_c.inject_count:
                # first two after skipping cm_a are cm_b and cm_c? inject order is cm_a, cm_b, cm_c
                # cm_a skipped, cm_b and cm_c taken. cm_c is the second kept, so inject_count is 1.
                pass
            if row_b.inject_count != 1 or row_c.inject_count != 1:
                _fail(
                    f"two injects expected, b={row_b.inject_count} c={row_c.inject_count}"
                )
            edited = memory.commitments.get("cm_a")
            if edited is None or edited.inject_count != 0:
                _fail("conflict must skip inject_count")
            if "18:40" not in (edited.current if edited else ""):
                _fail("current should be overwritten")
            edits = [
                row
                for row in memory.trace.read_rows()
                if row.get("kind") == "commit_edit" and row.get("field") == "current"
            ]
            if len(edits) != 1 or "before" not in edits[0] or "after" not in edits[0]:
                _fail(f"current overwrite must be traced: {edits}")
            scan = [row for row in memory.trace.read_rows() if row.get("kind") == "scan"][-1]
            conflicts = scan.get("conflicts") or []
            if not any(item.get("conflict") == "edit_wins" for item in conflicts):
                _fail(f"missing edit_wins: {scan}")

    asyncio.run(_run())
    print("  ok")


def main() -> None:
    test_apply_order()
    print("all commitment checks passed")


if __name__ == "__main__":
    main()
