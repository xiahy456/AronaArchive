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

"""Bi-temporal states: one live row, expiry, and the startup budget check.

Run from backend/:
  python scripts/test_memory_v2_states_unit.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.memory_v2.db import Database  # noqa: E402
from app.memory_v2.states import StateBook, StateBudgetError, assert_state_budget  # noqa: E402


def _fail(message: str) -> None:
    raise AssertionError(message)


def test_budget() -> None:
    print("== state budget ==")
    assert_state_budget(max_items=12, max_chars_per_item=48, token_budget_state=400)
    try:
        assert_state_budget(max_items=20, max_chars_per_item=48, token_budget_state=400)
    except StateBudgetError as exc:
        if "拒绝" in str(exc) or "装不下" in str(exc):
            print("  ok")
            return
        _fail(f"budget error should explain the refusal: {exc}")
    _fail("state_max_items=20 must refuse startup")


def test_live_and_expiry() -> None:
    print("== one live row and expiry ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        db = Database(root / "memory.db", root / "events_fts")
        book = StateBook(db, max_items=12, max_chars=48)
        book.upsert(
            key="location",
            value="老师在广州",
            valid_from=1_000.0,
            valid_until=None,
            importance=5,
            recorded_at=1_000.0,
        )
        book.upsert(
            key="location",
            value="老师在深圳",
            valid_from=2_000.0,
            valid_until=None,
            importance=6,
            recorded_at=2_000.0,
        )
        live = book.live(2_000.0)
        if live != ["老师在深圳"]:
            _fail(f"only the new location should be live: {live}")
        book.upsert(
            key="current_task",
            value="老师在做记忆系统重构",
            valid_from=1_000.0,
            valid_until=1_500.0,
            importance=5,
            recorded_at=1_000.0,
        )
        if "老师在做记忆系统重构" not in book.live(1_200.0):
            _fail("bounded state should be visible before valid_until")
        if "老师在做记忆系统重构" in book.live(1_600.0):
            _fail("expired state must leave the resident block without a timer")
        rows = db.call(lambda conn: conn.execute(
            "SELECT COUNT(*) FROM states WHERE key = 'location' AND valid_until IS NULL"
        ).fetchone()[0])
        if int(rows) != 1:
            _fail(f"location should have one open row, got {rows}")
    print("  ok")


def main() -> None:
    test_budget()
    test_live_and_expiry()
    print("all state checks passed")


if __name__ == "__main__":
    main()
