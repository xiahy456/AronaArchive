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

"""状态更新：消息触发、6 小时窗口、补发阈值、解析与失败不写时间戳。

Run from backend/:
  python scripts/test_memory_v2_state_update_unit.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import MemoryV2Config, MemoryV2StatesConfig, MemoryV2StorageConfig  # noqa: E402
from app.memory_v2 import MemoryV2  # noqa: E402
from app.memory_v2.util import loads_json_array  # noqa: E402


def _fail(message: str) -> None:
    raise AssertionError(message)


def _memory(tmp: Path, *, max_items: int = 12) -> MemoryV2:
    storage = MemoryV2StorageConfig(
        db_path=str(tmp / "memory.db"),
        events_fts=str(tmp / "events_fts"),
        chroma_path=str(tmp / "chroma"),
    )
    return MemoryV2(
        MemoryV2Config(
            storage=storage,
            states=MemoryV2StatesConfig(max_items=max_items),
        ),
        backend_dir=tmp,
        trace_path=tmp / "memory_v2-trace.jsonl",
        token_budget_state=400,
    )


def _rows(now: float) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": "刚到上海",
            "at": now - 3600,
            "time": "2026-10-28 17:00:00",
            "method": "direct",
        },
        {
            "role": "user",
            "content": "七小时前的话",
            "at": now - 7 * 3600,
            "time": "2026-10-28 11:00:00",
            "method": "direct",
        },
        {
            "role": "user",
            "content": "我想死",
            "at": now - 100,
            "time": "2026-10-28 17:50:00",
            "method": "direct",
        },
    ]


async def _wait_calls(calls: list[Any]) -> None:
    for _ in range(50):
        if calls:
            return
        await asyncio.sleep(0.02)
    _fail("state update was not called")


async def _run() -> None:
    print("== state update ==")
    now = 1_762_000_000.0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        memory = _memory(root)
        updater = memory.state_updater
        updater._clock = lambda: now
        memory.bind_dialogue(lambda _since: _rows(now))

        calls: list[str] = []

        async def forbidden(*_args: object, **_kwargs: object) -> list:
            _fail("no API key must not call the model")
            return []

        updater._complete = forbidden
        await updater.run_once("message")
        if memory.states.last_update_at() is not None:
            _fail("no API key must not write state_update_at")
        skipped = [row for row in memory.trace.read_rows() if row.get("skipped") == "no_api_key"]
        if not skipped:
            _fail("no API key should leave a trace")

        async def complete(model: str, system: str, user: str, timeout: float) -> Any:
            del model, timeout
            calls.append(user)
            if "12 小时" not in system:
                _fail("system prompt must state the 12 hour rule")
            return []

        updater._injected_complete = True
        updater._complete = complete
        memory.states.set_last_update_at(now)
        await updater.start()
        memory.enqueue_window(
            [{"role": "user", "content": "刚到上海", "time": "t", "method": "direct"}]
        )
        await _wait_calls(calls)
        await updater.stop()
        if len(calls) != 1:
            _fail(f"enqueue_window should call once, got {len(calls)}")
        prompt = calls[0]
        if "刚到上海" not in prompt or "七小时前的话" in prompt or "我想死" in prompt:
            _fail(f"lookback window is wrong: {prompt}")

        calls.clear()
        await updater.maybe_catchup("midnight")
        if calls:
            _fail("catch-up inside 12 hours must not call")

        memory.states.set_last_update_at(now - 13 * 3600)
        await updater.maybe_catchup("midnight")
        if len(calls) != 1:
            _fail(f"catch-up past 12 hours should call once, got {len(calls)}")
        if memory.states.last_update_at() != now:
            _fail("empty array must still stamp state_update_at")
        if memory.states.live():
            _fail("empty array must not write rows")

        async def add_location(model: str, system: str, user: str, timeout: float) -> str:
            del model, system, user, timeout
            return '[{"key": "location", "value": "老师人在上海", "active": 1}]'

        updater._complete = add_location
        await updater.run_once("message")
        if memory.states.live() != ["老师人在上海"]:
            _fail(f"bare array was not applied: {memory.states.live()}")

        async def rewrite(model: str, system: str, user: str, timeout: float) -> dict:
            del model, system, user, timeout
            return {"states": [{"key": "location", "value": "老师人在广州", "active": 1}]}

        updater._complete = rewrite
        await updater.run_once("message")
        row = memory.states.get("location")
        if row is None or row.value != "老师人在广州":
            _fail("wrapped object was not applied")
        traced = [
            item
            for entry in memory.trace.read_rows()
            if entry.get("kind") == "state_update"
            for item in entry.get("applied") or []
            if item.get("op") == "modify"
        ]
        if not traced or traced[-1].get("before") != "老师人在上海":
            _fail(f"trace should keep before/after: {traced}")

        stamped = memory.states.last_update_at()

        async def boom(model: str, system: str, user: str, timeout: float) -> list:
            del model, system, user, timeout
            raise RuntimeError("down")

        updater._complete = boom
        await updater.run_once("message")
        if memory.states.last_update_at() != stamped:
            _fail("failure must not move state_update_at")
        if not any(row.get("failed") for row in memory.trace.read_rows()):
            _fail("failure should be traced")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        memory = _memory(Path(tmp), max_items=1)
        updater = memory.state_updater
        updater._clock = lambda: now
        updater._injected_complete = True
        memory.states.apply_ops(
            [{"key": "location", "value": "老师人在广州", "active": 1}], now,
        )

        async def extra(model: str, system: str, user: str, timeout: float) -> list:
            del model, system, user, timeout
            return [{"key": "routine", "value": "老师保持远程工作", "active": 1}]

        updater._complete = extra
        memory.bind_dialogue(lambda _since: _rows(now))
        await updater.run_once("message")
        dropped = [
            item
            for entry in memory.trace.read_rows()
            if entry.get("kind") == "state_update"
            for item in entry.get("dropped") or []
        ]
        if not any(item.get("reason") == "cap" for item in dropped):
            _fail(f"cap drop should be traced: {dropped}")

    parsed = loads_json_array('```json\n[{"key": "mood", "value": "老师心情平稳", "active": 1}]\n```')
    if parsed[0]["key"] != "mood":
        _fail("fenced array was not parsed")
    wrapped = loads_json_array('{"states": []}')
    if wrapped != []:
        _fail("object wrapper should yield the inner list")

    captured: list[dict[str, Any]] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "[]"}}]}

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        async def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> _Response:
            del url, headers
            captured.append(json)
            return _Response()

    import httpx

    httpx.AsyncClient = _Client  # type: ignore[misc]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        memory = _memory(Path(tmp))
        updater = memory.state_updater
        updater.api_key = "sk-test"
        updater._clock = lambda: now
        updater._complete = updater._http_complete
        memory.bind_dialogue(lambda _since: _rows(now))
        await updater.run_once("message")
    if not captured or "response_format" in captured[0]:
        _fail(f"state update must not force a json object: {captured}")
    print("  ok")


def main() -> None:
    asyncio.run(_run())
    print("all state update checks passed")


if __name__ == "__main__":
    main()
