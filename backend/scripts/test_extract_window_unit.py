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

"""Cursor-based extract window: silent turns, proactive lines, crisis carry.

Run from backend/:
  python scripts/test_extract_window_unit.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import AppConfig, ModelConfig  # noqa: E402
from app.conversation import ConversationManager  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def test_silent_and_undelivered() -> None:
    print("== silent and undelivered turns stay in the window ==")
    cm = ConversationManager()
    cm.append("s", "user", "我今天去深圳")
    if cm.extract_window_user_texts() != ["我今天去深圳"]:
        _fail(f"a silent turn must stay visible: {cm.extract_window_user_texts()}")
    cm.append("s", "user", "希望阿洛娜每天提醒我吃药")
    if cm.extract_window_turn_count() != 2:
        _fail("both silent turns must be waiting")
    cm.advance_extract_cursor()
    if cm.pending_extract_entries():
        _fail("consuming must empty the window")
    print("  ok")


def test_proactive_line_in_window() -> None:
    print("== proactive line enters the next window ==")
    cm = ConversationManager()
    cm.append("s", "user", "在吗")
    cm.append("s", "assistant", "在的。")
    cm.advance_extract_cursor()
    cm.append("s", "assistant", "老师，记得喝水。")
    rows = cm.pending_extract_entries()
    if not rows or rows[-1]["content"] != "老师，记得喝水。":
        _fail(f"proactive line missing from window: {rows}")
    if cm.extract_window_turn_count() != 0:
        _fail("a proactive line must not count as a teacher turn")
    print("  ok")


def test_crisis_carry() -> None:
    print("== crisis keeps earlier pending content ==")
    cm = ConversationManager()
    cm.append("s", "user", "我最近在改记忆系统")
    cm.append("s", "assistant", "听起来很难。")
    cm.append("s", "user", "我想死")
    cm.append("s", "assistant", "老师。")
    cm.advance_extract_cursor(keep_pending=True)
    rows = cm.pending_extract_entries()
    contents = [row["content"] for row in rows]
    if "我最近在改记忆系统" not in contents:
        _fail(f"benign content before a crisis must be kept: {contents}")
    if any("想死" in text for text in contents):
        _fail(f"crisis wording must not be carried: {contents}")
    print("  ok")


def test_restart_cursor() -> None:
    print("== restart does not re-extract history ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "dialogue.json"
        first = ConversationManager(persist_path=path)
        first.append("s", "user", "老师喜欢蓝色")
        first.append("s", "assistant", "记住了。")
        first.advance_extract_cursor()
        reopened = ConversationManager(persist_path=path)
        if reopened.pending_extract_entries():
            _fail(f"restart must not re-open consumed lines: {reopened.pending_extract_entries()}")
        reopened.append("s", "user", "现在喜欢黄色了")
        rows = reopened.pending_extract_entries()
        if [row["content"] for row in rows] != ["现在喜欢黄色了"]:
            _fail(f"only the new line should wait: {rows}")
        if rows[0].get("seq", 0) <= 0:
            _fail("persisted rows need a seq")
    print("  ok")


def test_orchestrator_enqueue_path() -> None:
    print("== orchestrator enqueues whole window ==")

    async def _run() -> None:
        from app.memory.gate import GateDecision

        extractor = MagicMock()
        extractor.enqueue = AsyncMock()
        cfg = AppConfig(model=ModelConfig(enabled=False))
        cfg.memory.extractor.api_key = "test-key"
        cfg.memory.extractor.every_n_turns = 99
        cfg.memory.extractor.extract_buffer_turns = 99
        orch = Orchestrator(
            cfg,
            model=MagicMock(),
            conversations=ConversationManager(),
            memory_store=MagicMock(),
            extractor=extractor,
            knowledge=MagicMock(),
            planner=MagicMock(),
            relationship=MagicMock(),
        )

        async def _state_only(config, text):
            return GateDecision(remember=True, kinds=("state",), failed=False)

        import app.orchestrator as orch_mod

        original = orch_mod.decide_gate
        orch_mod.decide_gate = _state_only
        try:
            orch.conversations.append("s", "user", "我今天去深圳")
            await orch._maybe_extract("s", "我今天去深圳")
        finally:
            orch_mod.decide_gate = original

        transcript = extractor.enqueue.await_args.kwargs.get("transcript")
        if "我今天去深圳" not in str(transcript):
            _fail(f"silent turn missing from transcript: {transcript}")
        if orch.conversations.pending_extract_entries():
            _fail("enqueue must advance the cursor")

    asyncio.run(_run())
    print("  ok")


def main() -> int:
    test_silent_and_undelivered()
    test_proactive_line_in_window()
    test_crisis_carry()
    test_restart_cursor()
    test_orchestrator_enqueue_path()
    print("extract window unit ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
