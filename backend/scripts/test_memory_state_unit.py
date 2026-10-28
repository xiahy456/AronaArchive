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

"""Resident state sentences: budget, rejection, and prompt text.

Run from backend/:
  python scripts/test_memory_state_unit.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import AppConfig  # noqa: E402
from app.memory.state import StateItem, StateStore, format_state_context  # noqa: E402
from app.planner.prompts import build_planner_user_message  # noqa: E402
from app.prompt import format_state_block, state_budget_fits  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def _item(item_id: str, text: str, updated_at: float) -> StateItem:
    return StateItem(
        id=item_id,
        text=text,
        created_at=updated_at,
        updated_at=updated_at,
        importance=5,
    )


def test_budget_and_block() -> None:
    print("== state budget and block ==")
    fits, needed, budget = state_budget_fits(AppConfig())
    if not fits:
        _fail(f"default state budget does not fit: needed={needed} budget={budget}")
    block = format_state_block(
        ["老师2026年10月27日在深圳", "老师想死"],
        max_chars=8,
    )
    if "所在地" in block or "id=" in block:
        _fail(f"state block must be plain sentences: {block}")
    if "老师2026年10月27日在深圳" not in block:
        _fail(f"sentence missing: {block}")
    if "想死" in block:
        _fail("crisis sentence must not be injected")
    if len(block) <= 8:
        _fail("resident state must not be clipped to the budget")
    print("  ok")


def test_store_rules() -> None:
    print("== state store rules ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = StateStore(Path(tmp) / "memory.db", max_items=1, max_chars=16)
        now = time.time()
        if not store.upsert(_item("place", "老师在深圳", now)):
            _fail("first sentence should be stored")
        created = store.all_items()[0].created_at
        if store.upsert(_item("place", "这是一句超过十六个字的状态所以要整句拒绝掉", now + 5)):
            _fail("over-long sentence must be rejected whole")
        if store.texts() != ["老师在深圳"]:
            _fail(f"rejected write changed the sentence: {store.texts()}")
        later = now + 10
        if not store.upsert(_item("place", "老师在广州", later)):
            _fail("same id should overwrite")
        kept = store.all_items()[0]
        if kept.created_at != created or kept.text != "老师在广州":
            _fail(f"overwrite lost created_at or text: {kept}")
        if store.upsert(_item("other", "老师在家", later)):
            _fail("a new id must be rejected when full")
        context = format_state_context(
            [
                StateItem(
                    id="place",
                    text="老师在广州",
                    created_at=created,
                    updated_at=(datetime.now() - timedelta(hours=72)).timestamp(),
                    importance=5,
                )
            ],
            datetime.now(),
            confirm_after_hours=48,
        )
        if "待确认" not in context or "今天" in context:
            _fail(f"extractor context marks are wrong: {context}")
        planner = build_planner_user_message(
            user_text="代码报错了",
            history=[],
            memories=[],
            knowledge=[],
            state_block=format_state_block(store.texts()),
        )
        if "老师在广州" not in planner or "待确认" in planner or "所在地" in planner:
            _fail(f"planner state text is wrong: {planner}")
    print("  ok")


def test_delete_and_empty() -> None:
    print("== state delete and empty block ==")
    if format_state_block(()) != "":
        _fail("an empty state set must not render a section")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = StateStore(Path(tmp) / "memory.db")
        now = time.time()
        store.upsert(_item("place", "老师在深圳", now))
        if store.delete(["place"]) != 1 or store.texts():
            _fail(f"delete should remove the sentence: {store.texts()}")
    print("  ok")


def main() -> int:
    test_budget_and_block()
    test_store_rules()
    test_delete_and_empty()
    print("state unit ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
