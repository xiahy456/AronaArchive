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

"""Overwrite the state table from dialogue. One call per delivered message, plus a midnight catch-up."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.query_time import format_extract_now, format_full_datetime
from app.safety import is_crisis_text

from .prompts import state_update_system
from .states import StateBook
from .trace import TraceLog
from .util import api_key_ready, loads_json_array

logger = logging.getLogger(__name__)

DialogueFn = Callable[[float], list[dict[str, Any]]]
CompleteFn = Callable[[str, str, str, float], Awaitable[Any]]
ClockFn = Callable[[], float]
SleepFn = Callable[[float], Awaitable[None]]


def _seconds_until_midnight(now: datetime) -> float:
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(0.0, (nxt - now).total_seconds())


def _as_ops(parsed: Any) -> list[Any]:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, str):
        return loads_json_array(parsed)
    if isinstance(parsed, dict):
        states = parsed.get("states")
        if isinstance(states, list):
            return states
    raise ValueError("state update did not return a list")


class StateUpdater:
    def __init__(
        self,
        *,
        states: StateBook,
        trace: TraceLog,
        dialogue: DialogueFn,
        base_url: str,
        api_key: str,
        model: str,
        timeout_sec: float = 15,
        retry_max: int = 2,
        calls_per_day: int = 3000,
        max_chars: int = 48,
        lookback_hours: float = 6,
        catchup_after_hours: float = 12,
        enabled: bool = True,
        complete: CompleteFn | None = None,
        clock: ClockFn | None = None,
        sleeper: SleepFn | None = None,
    ) -> None:
        self.states = states
        self.trace = trace
        self.dialogue = dialogue
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout_sec = float(timeout_sec)
        self.retry_max = max(0, int(retry_max))
        self.calls_per_day = max(0, int(calls_per_day))
        self.max_chars = int(max_chars)
        self.lookback_hours = float(lookback_hours)
        self.catchup_after_hours = float(catchup_after_hours)
        self.enabled = enabled
        self._injected_complete = complete is not None
        self._complete = complete or self._http_complete
        self._clock = clock or (lambda: datetime.now().timestamp())
        self._sleeper = sleeper or asyncio.sleep
        self._stopped = False
        self._pending = False
        self._wakeup = asyncio.Event()
        self._lock = asyncio.Lock()
        self._message_task: asyncio.Task[None] | None = None
        self._midnight_task: asyncio.Task[None] | None = None
        self._calls = 0
        self._call_day = ""

    def has_api(self) -> bool:
        if not self.enabled:
            return False
        if self._injected_complete:
            return True
        return api_key_ready(self.api_key)

    def enqueue(self) -> None:
        """Coalesce bursts: a run already in flight keeps a single follow-up."""
        if not self.enabled:
            return
        self._pending = True
        self._wakeup.set()

    async def start(self) -> None:
        if self._message_task is not None:
            return
        self._stopped = False
        self._message_task = asyncio.create_task(self._message_loop())
        self._midnight_task = asyncio.create_task(self._midnight_loop())

    async def stop(self) -> None:
        self._stopped = True
        self._wakeup.set()
        tasks = [task for task in (self._message_task, self._midnight_task) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._message_task = None
        self._midnight_task = None

    async def _message_loop(self) -> None:
        while not self._stopped:
            await self._wakeup.wait()
            self._wakeup.clear()
            if self._stopped:
                return
            if not self._pending:
                continue
            self._pending = False
            try:
                await self.run_once("message")
            except Exception:
                logger.exception("memory_v2 state update failed")
            if self._pending:
                self._wakeup.set()

    async def _midnight_loop(self) -> None:
        try:
            await self.maybe_catchup("startup")
        except Exception:
            logger.exception("memory_v2 state catch-up failed")
        while not self._stopped:
            now = datetime.fromtimestamp(float(self._clock()))
            await self._sleeper(_seconds_until_midnight(now))
            if self._stopped:
                return
            try:
                await self.maybe_catchup("midnight")
            except Exception:
                logger.exception("memory_v2 midnight state update failed")

    async def maybe_catchup(self, trigger: str) -> None:
        now = float(self._clock())
        last = self.states.last_update_at()
        limit = self.catchup_after_hours * 3600
        if last is not None and now - last <= limit:
            return
        if not self._recent(now):
            self.trace.write(
                {
                    "kind": "state_update",
                    "trigger": trigger,
                    "dialogue_lines": 0,
                    "applied": [],
                    "dropped": [],
                    "skipped": "no_dialogue",
                    "failed": False,
                },
                at=now,
            )
            return
        await self.run_once(trigger)

    async def run_once(self, trigger: str) -> None:
        async with self._lock:
            await self._run_once(trigger)

    async def _run_once(self, trigger: str) -> None:
        started = time.perf_counter()
        now = float(self._clock())
        dialogue = self._recent(now)
        if not self.has_api():
            logger.warning("memory_v2 state update disabled: no API key")
            self.trace.write(
                {
                    "kind": "state_update",
                    "trigger": trigger,
                    "dialogue_lines": len(dialogue),
                    "applied": [],
                    "dropped": [],
                    "skipped": "no_api_key",
                    "failed": False,
                    "latency_ms": _latency(started),
                },
                at=now,
            )
            return
        if not self._allow_call(datetime.fromtimestamp(now)):
            self.trace.write(
                {
                    "kind": "state_update",
                    "trigger": trigger,
                    "dialogue_lines": len(dialogue),
                    "applied": [],
                    "dropped": [],
                    "skipped": "call_limit",
                    "failed": False,
                    "latency_ms": _latency(started),
                },
                at=now,
            )
            return
        user = self._prompt(dialogue, now)
        try:
            parsed = await self._call(user)
            ops = _as_ops(parsed)
        except Exception as exc:
            logger.warning("memory_v2 state update failed: %s", exc)
            self.trace.write(
                {
                    "kind": "state_update",
                    "trigger": trigger,
                    "dialogue_lines": len(dialogue),
                    "applied": [],
                    "dropped": [],
                    "failed": True,
                    "error": str(exc),
                    "latency_ms": _latency(started),
                },
                at=now,
            )
            return
        result = self.states.apply_ops(ops, now)
        self.states.set_last_update_at(now)
        self.trace.write(
            {
                "kind": "state_update",
                "trigger": trigger,
                "dialogue_lines": len(dialogue),
                "applied": _applied(result),
                "dropped": result["dropped"],
                "failed": False,
                "latency_ms": _latency(started),
            },
            at=now,
        )

    def _recent(self, now: float) -> list[dict[str, Any]]:
        since = now - self.lookback_hours * 3600
        kept: list[dict[str, Any]] = []
        for row in self.dialogue(since) or []:
            spoken = row.get("at")
            if isinstance(spoken, (int, float)) and spoken and float(spoken) < since:
                continue
            content = str(row.get("content") or "").strip()
            if not content or is_crisis_text(content):
                continue
            role = str(row.get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            kept.append(row)
        return kept

    def _prompt(self, dialogue: list[dict[str, Any]], now: float) -> str:
        moment = datetime.fromtimestamp(now)
        lines = [format_extract_now(moment), "", "【当前状态表】"]
        rows = self.states.active()
        if not rows:
            lines.append("（无）")
        else:
            for row in rows:
                stamp = format_full_datetime(datetime.fromtimestamp(row.updated_at))
                lines.append(f"- key={row.key}")
                lines.append(f"  value: {row.value}")
                lines.append(f"  updated_at: {stamp}")
                lines.append("  active: 1")
        lines.append("")
        lines.append("【最近对话】")
        if not dialogue:
            lines.append("（无）")
        else:
            for row in dialogue:
                who = "老师" if str(row.get("role") or "") == "user" else "阿洛娜"
                content = str(row.get("content") or "").strip()
                stamp = str(row.get("time") or "")
                if not stamp:
                    spoken = row.get("at")
                    if isinstance(spoken, (int, float)) and spoken:
                        stamp = format_full_datetime(datetime.fromtimestamp(float(spoken)))
                channel = str(row.get("method") or "direct")
                lines.append(f"[{stamp}][{channel}] {who}：{content}")
        lines.append("")
        lines.append("【输出要求】")
        lines.append(
            "对照当前时间和最近对话，只返回需要新增、修改或删除的状态。"
            "12 小时后不再需要的条目删掉。不需要改的不要返回。没有要改的返回 []。"
        )
        return "\n".join(lines)

    def _allow_call(self, now: datetime) -> bool:
        day = now.date().isoformat()
        if day != self._call_day:
            self._call_day = day
            self._calls = 0
        if self._calls >= self.calls_per_day:
            return False
        self._calls += 1
        return True

    async def _call(self, user: str) -> Any:
        system = state_update_system(self.max_chars)
        last: Exception | None = None
        for _ in range(self.retry_max + 1):
            try:
                return await self._complete(self.model, system, user, self.timeout_sec)
            except Exception as exc:
                last = exc
                logger.info("memory_v2 state update retry: %s", exc)
        if last is not None:
            raise last
        raise RuntimeError("state update produced no result")

    async def _http_complete(
        self, model: str, system: str, user: str, timeout: float
    ) -> list[Any]:
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"] or "[]"
        return loads_json_array(str(content))


def _latency(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _applied(result: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind, name in (("added", "add"), ("modified", "modify"), ("deleted", "delete")):
        for item in result.get(kind) or []:
            rows.append(
                {
                    "key": item.get("key") or "",
                    "op": name,
                    "before": item.get("before") or "",
                    "after": item.get("after") or "",
                }
            )
    return rows
