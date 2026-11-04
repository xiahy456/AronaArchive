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

"""覆盖式状态表：增改删、created_at 保持、重复 key、容量与预算断言。

Run from backend/:
  python scripts/test_memory_v2_states_unit.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import MemoryV2Config, MemoryV2StatesConfig, MemoryV2StorageConfig  # noqa: E402
from app.memory_v2 import MemoryV2  # noqa: E402


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("OK  " if ok else "FAIL") + " " + name + (("  " + detail) if detail else ""))
    if not ok:
        raise SystemExit(1)


def _memory(tmp: Path, **states: object) -> MemoryV2:
    storage = MemoryV2StorageConfig(
        db_path=str(tmp / "memory.db"),
        events_fts=str(tmp / "events_fts"),
        chroma_path=str(tmp / "chroma"),
    )
    config = MemoryV2Config(
        storage=storage,
        states=MemoryV2StatesConfig(**states),  # type: ignore[arg-type]
    )
    return MemoryV2(
        config,
        backend_dir=tmp,
        trace_path=tmp / "trace.jsonl",
        token_budget_state=400,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        book = _memory(root).states
        now = 1_700_000_000.0
        applied = book.apply_ops(
            [{"key": "location", "value": "老师人在广州", "active": 1}], now,
        )
        check("新增", bool(applied["added"]) and applied["added"][0]["key"] == "location")
        row = book.active()[0]
        check("created 与 updated 同刻", row.created_at == now and row.updated_at == now)

        later = now + 3600
        applied = book.apply_ops(
            [{"key": "location", "value": "老师人在上海", "active": 1}], later,
        )
        check(
            "修改",
            bool(applied["modified"]) and applied["modified"][0]["before"] == "老师人在广州",
        )
        row = book.get("location")
        check(
            "created_at 保持",
            row is not None and row.created_at == now and row.updated_at == later,
        )
        check("live 全量", book.live() == ["老师人在上海"])

        applied = book.apply_ops(
            [{"key": "location", "value": "", "active": 0}], later + 10,
        )
        deleted = book.get("location")
        check(
            "删除保留旧值",
            bool(applied["deleted"]) and deleted is not None and deleted.value == "老师人在上海",
        )
        check("删除后不注入", book.live() == [])

        revived = later + 20
        applied = book.apply_ops(
            [{"key": "location", "value": "老师回到广州", "active": 1}], revived,
        )
        check("重新启用走修改", bool(applied["modified"]) and not applied["added"])
        row = book.get("location")
        check(
            "重新启用不改 created_at",
            row is not None and row.created_at == now and row.active == 1,
        )

        applied = book.apply_ops(
            [
                {"key": "mood", "value": "老师心情低落", "active": 1},
                {"key": "mood", "value": "老师心情平稳", "active": 1},
            ],
            revived + 10,
        )
        check(
            "重复 key 后者优先",
            bool(applied["dropped"]) and applied["dropped"][0]["reason"] == "duplicate",
        )
        mood = book.get("mood")
        check("重复后的值", mood is not None and mood.value == "老师心情平稳")

        applied = book.apply_ops(
            [{"key": "missing", "value": "", "active": 0}], revived + 20,
        )
        check(
            "删除不存在的 key",
            bool(applied["dropped"]) and applied["dropped"][0]["reason"] == "missing",
        )

        tiny = _memory(root / "cap", max_items=1)
        base = revived + 40
        tiny.states.apply_ops(
            [{"key": "location", "value": "老师人在广州", "active": 1}], base,
        )
        applied = tiny.states.apply_ops(
            [
                {"key": "routine", "value": "老师保持远程工作", "active": 1},
                {"key": "location", "value": "老师人在上海", "active": 1},
            ],
            base + 1,
        )
        check("超容量的新增被拒", any(item["reason"] == "cap" for item in applied["dropped"]))
        check("修改不受容量限制", any(item["key"] == "location" for item in applied["modified"]))
        check("容量拒绝后仍只有一条", len(tiny.states.active()) == 1)

    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            _memory(Path(tmp), max_items=20)
    except SystemExit as exc:
        check("预算断言拒绝 20 条", "装不下" in str(exc))
    else:
        check("预算断言拒绝 20 条", False)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        db_path = root / "memory.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE states (id INTEGER PRIMARY KEY, key TEXT, value TEXT, "
            "valid_from REAL, valid_until REAL, importance INTEGER, recorded_at REAL)"
        )
        conn.commit()
        conn.close()
        try:
            _memory(root)
        except SystemExit as exc:
            check("旧表拒绝启动", "migrate_memory_v2_states.py" in str(exc))
        else:
            check("旧表拒绝启动", False)
    print("ALL PASS")


if __name__ == "__main__":
    main()
