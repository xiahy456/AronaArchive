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

"""memory_v2 is on by default and does not construct v1 beside it.

Run from backend/:
  python scripts/test_memory_v2_switch_unit.py
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import AppConfig, MemoryV2Config, MemoryV2StorageConfig  # noqa: E402
from app.memory_v2 import MemoryV2  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402


def _fail(message: str) -> None:
    raise AssertionError(message)


def test_default_and_isolation() -> None:
    print("== default switch and import isolation ==")
    if AppConfig().memory_v2.enabled is not True:
        _fail("memory_v2.enabled must default to true")
    if AppConfig().token_budget.state < 400:
        _fail("token_budget.state must be at least 400")
    banned = ("from app.memory", "import app.memory", "from app.rerank", "from app.taxonomy")
    for path in (ROOT / "app" / "memory_v2").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in banned:
            if needle in text:
                _fail(f"{path.name} imports a forbidden module: {needle}")
        for symbol in (
            "MemoryStore",
            "MemoryExtractor",
            "StateStore",
            "CommitmentStore",
            "SummaryStore",
            "MemoryConfig",
            "ExtractorConfig",
            "normalize_memory_category",
            "format_state_block",
            "format_memory_inject",
        ):
            if symbol in text:
                _fail(f"{path.name} mentions {symbol}")
    for path in (ROOT / "app" / "memory").glob("*.py"):
        if "memory_v2" in path.read_text(encoding="utf-8"):
            _fail(f"v1 memory package references memory_v2: {path.name}")
    main_text = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    enabled_at = main_text.find("if config.memory_v2.enabled")
    store_at = main_text.find("MemoryStore(")
    if enabled_at < 0 or store_at < enabled_at:
        _fail("MemoryStore must be constructed only in the v1 branch")
    print("  ok")


def test_legacy_warning_and_empty_v1_hooks() -> None:
    print("== legacy database refuses startup; v1 hooks stay empty ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        db_path = root / "memory.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE memories (key TEXT PRIMARY KEY, content TEXT)")
        conn.execute("CREATE TABLE state_items (id TEXT PRIMARY KEY, text TEXT)")
        conn.commit()
        conn.close()
        storage = MemoryV2StorageConfig(
            db_path=str(db_path),
            events_fts=str(root / "events_fts"),
            chroma_path=str(root / "chroma"),
        )
        try:
            MemoryV2(
                MemoryV2Config(storage=storage),
                backend_dir=root,
                trace_path=root / "trace.jsonl",
                token_budget_state=400,
            )
        except SystemExit as exc:
            if "迁移" not in str(exc):
                _fail(f"legacy startup should tell the user to migrate: {exc}")
        else:
            _fail("a v1 database without events must not start quietly")
        fresh = root / "fresh"
        fresh.mkdir()
        memory = MemoryV2(
            MemoryV2Config(
                storage=MemoryV2StorageConfig(
                    db_path=str(fresh / "memory.db"),
                    events_fts=str(fresh / "events_fts"),
                    chroma_path=str(fresh / "chroma"),
                )
            ),
            backend_dir=fresh,
            trace_path=fresh / "trace.jsonl",
            token_budget_state=400,
        )
        orch = Orchestrator(
            AppConfig(),
            model=MagicMock(),
            conversations=MagicMock(),
            memory_store=None,
            extractor=None,
            memory_v2=memory,
            knowledge=MagicMock(),
        )
        orch.state_store = None
        orch.summary_store = None
        orch.commitment_store = None
        if orch._state_block() or orch._summary_block():
            _fail("v2 mode must leave the v1 state and summary blocks empty")
        if orch.state_store is not None or orch.commitment_store is not None:
            _fail("v1 stores must stay unset")
    print("  ok")


def test_v1_unit_still_passes() -> None:
    print("== v1 state unit still passes ==")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "test_memory_state_unit.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        _fail(completed.stdout + completed.stderr)
    print("  ok")


def main() -> None:
    test_default_and_isolation()
    test_legacy_warning_and_empty_v1_hooks()
    test_v1_unit_still_passes()
    print("all switch checks passed")


if __name__ == "__main__":
    main()
