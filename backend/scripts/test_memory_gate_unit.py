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

"""Semantic gate decisions and the extract buffer fallback.

Run from backend/:
  python scripts/test_memory_gate_unit.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import AppConfig, ExtractorConfig, ModelConfig  # noqa: E402
from app.conversation import ConversationManager  # noqa: E402
from app.memory.gate import decide_gate  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"remember": False, "kinds": []}, ensure_ascii=False)
                    }
                }
            ]
        }


class _Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        return _Response()


def test_gate_decisions() -> None:
    print("== gate decisions ==")

    async def _run() -> None:
        missing = await decide_gate(ExtractorConfig(api_key=""), "我今天去深圳")
        if not missing.failed or missing.kinds:
            _fail(f"missing key must fail open: {missing}")
        import app.memory.gate as gate_mod

        original = gate_mod.httpx.AsyncClient
        gate_mod.httpx.AsyncClient = lambda timeout=0: _Client()  # type: ignore[assignment]
        try:
            quiet = await decide_gate(
                ExtractorConfig(api_key="test-key", gate_enabled=True),
                "嗯",
            )
        finally:
            gate_mod.httpx.AsyncClient = original
        if quiet.failed or quiet.remember or quiet.kinds:
            _fail(f"empty kinds means do not remember: {quiet}")

    asyncio.run(_run())
    print("  ok")


def test_buffer_and_disclose() -> None:
    print("== buffer fallback and disclose ==")

    async def _run() -> None:
        extractor = MagicMock()
        extractor.enqueue = AsyncMock()
        cfg = AppConfig(model=ModelConfig(enabled=False))
        cfg.memory.extractor.api_key = "test-key"
        cfg.memory.extractor.every_n_turns = 99
        cfg.memory.extractor.extract_buffer_turns = 1
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

        async def _quiet(config, text):
            from app.memory.gate import GateDecision

            return GateDecision(remember=False, kinds=(), failed=False)

        import app.orchestrator as orch_mod

        original = orch_mod.decide_gate
        orch_mod.decide_gate = _quiet
        try:
            orch.conversations.append("s1", "user", "嗯")
            orch.conversations.append("s1", "assistant", "嗯。")
            await orch._maybe_extract("s1", "嗯")
        finally:
            orch_mod.decide_gate = original
        if not extractor.enqueue.await_count:
            _fail("a full buffer should extract every kind")
        kinds = extractor.enqueue.await_args.kwargs.get("kinds")
        if kinds != ["fact", "state", "commitment"]:
            _fail(f"buffer fallback kinds: {kinds}")

        extractor.enqueue.reset_mock()
        cfg.memory.extractor.api_key = ""
        cfg.memory.extractor.extract_buffer_turns = 99
        orch.conversations.append("s2", "user", "我心里很难过")
        orch.conversations.append("s2", "assistant", "老师，阿洛娜在的。")
        await orch._maybe_extract("s2", "我心里很难过")
        if not extractor.enqueue.await_count:
            _fail("self disclose should enqueue without a gate key")

    asyncio.run(_run())
    print("  ok")


def test_crisis_failure_and_clear() -> None:
    print("== crisis, gate failure, buffer clear ==")

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
        orch.conversations.append("crisis", "user", "我想死")
        orch.conversations.append("crisis", "assistant", "老师。")
        await orch._maybe_extract("crisis", "我想死")
        if extractor.enqueue.await_count:
            _fail("crisis turns must not reach the gate")

        import app.orchestrator as orch_mod

        async def _failed(config, text):
            return GateDecision(remember=False, kinds=(), failed=True)

        original = orch_mod.decide_gate
        orch_mod.decide_gate = _failed
        try:
            orch.conversations.append("fail", "user", "嗯")
            orch.conversations.append("fail", "assistant", "嗯。")
            await orch._maybe_extract("fail", "嗯")
        finally:
            orch_mod.decide_gate = original
        kinds = extractor.enqueue.await_args.kwargs.get("kinds")
        if kinds != ["fact", "state", "commitment"]:
            _fail(f"a failed gate must extract every kind: {kinds}")
        if orch.conversations.extract_window_turn_count():
            _fail("enqueue must clear the window")

        extractor.enqueue.reset_mock()

        async def _state_only(config, text):
            return GateDecision(remember=True, kinds=("state",), failed=False)

        orch_mod.decide_gate = _state_only
        try:
            orch.conversations.append("now", "user", "我今天去深圳")
            orch.conversations.append("now", "assistant", "路上小心。")
            await orch._maybe_extract("now", "我今天去深圳")
        finally:
            orch_mod.decide_gate = original
        kinds = extractor.enqueue.await_args.kwargs.get("kinds")
        if kinds != ["state"]:
            _fail(f"nonempty kinds should enqueue immediately: {kinds}")
        if orch.conversations.extract_window_turn_count():
            _fail("an immediate extract must clear the window")

    asyncio.run(_run())
    print("  ok")


def main() -> int:
    test_gate_decisions()
    test_buffer_and_disclose()
    test_crisis_failure_and_clear()
    print("gate unit ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
