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

"""Events: sentence truncation, importance clamp, FTS, degraded retrieval.

Run from backend/:
  python scripts/test_memory_v2_events_unit.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import MemoryV2Config, MemoryV2StorageConfig  # noqa: E402
from app.memory_v2 import MemoryV2  # noqa: E402
from app.memory_v2.util import clamp_importance, truncate_at_sentence  # noqa: E402


def _fail(message: str) -> None:
    raise AssertionError(message)


def _memory(tmp: Path) -> MemoryV2:
    storage = MemoryV2StorageConfig(
        db_path=str(tmp / "memory.db"),
        events_fts=str(tmp / "events_fts"),
        chroma_path=str(tmp / "chroma"),
    )
    config = MemoryV2Config(storage=storage, trace_enabled=True)
    return MemoryV2(
        config,
        backend_dir=tmp,
        trace_path=tmp / "memory_v2-trace.jsonl",
        token_budget_state=400,
        token_budget_memory=250,
    )


def test_summary_and_clamp() -> None:
    print("== summary truncation and importance clamp ==")
    text = "老师去了广州。" + ("他见到了朋友。" * 40)
    cut, changed = truncate_at_sentence(text, 30)
    if not changed or not cut.endswith("。"):
        _fail(f"must cut on a sentence boundary: {cut!r}")
    if "他见到" in cut and not cut.endswith("。"):
        _fail("must not slice a sentence in half")
    value, changed = clamp_importance(11)
    if value != 10 or not changed:
        _fail(f"11 should clamp to 10, got {value} changed={changed}")
    value, changed = clamp_importance(5.6)
    if value != 6 or not changed:
        _fail(f"5.6 should clamp to 6, got {value}")
    value, changed = clamp_importance(5)
    if value != 5 or changed:
        _fail("5 is already a legal tier")
    print("  ok")


def test_fts_and_degraded() -> None:
    print("== fts retrieve and degraded flag ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        memory = _memory(root)
        columns = {
            str(row[1])
            for row in memory.db.call(
                lambda conn: conn.execute("PRAGMA table_info(events)").fetchall()
            )
        }
        for banned in ("category", "participants", "valence", "detail"):
            if banned in columns:
                _fail(f"events must not have {banned}")
        if not memory.db.fts_ready or not (root / "events_fts").exists():
            _fail("events_fts sidecar was not created")
        summary = (
            "老师2026年10月28日去了广州。"
            "他先去了天河区的展会，遇到几个老朋友。"
            "晚上因为下雨提前回了酒店，没吃晚饭。"
        )
        memory.events.append(
            summary=summary,
            occurred_at=1_700_000_000,
            importance=5,
            recorded_at=1_700_000_000,
        )
        found = memory.search_events("广州", k=3)
        if not found or summary not in found[0].summary:
            _fail(f"fts should return the full summary, got {found}")
        rows = memory.trace.read_rows()
        retrieve = [row for row in rows if row.get("kind") == "retrieve"]
        if not retrieve or retrieve[-1].get("degraded") is not True:
            _fail(f"missing vector store must mark degraded: {retrieve}")
    print("  ok")


def main() -> None:
    test_summary_and_clamp()
    test_fts_and_degraded()
    print("all event checks passed")


if __name__ == "__main__":
    main()
