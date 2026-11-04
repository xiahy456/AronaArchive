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

"""Three parallel extractors. The only source is the dialogue window."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx

from app.query_time import format_extract_now
from app.safety import is_crisis_text

from .commitments import CommitmentBook
from .events import EventLog
from .prompts import commitment_system, event_system
from .retrieve import EventRetriever
from .trace import TraceLog
from .util import (
    api_key_ready,
    clamp_importance,
    has_ephemeral_time,
    loads_json_object,
    parse_timestamp,
    truncate_at_sentence,
)

logger = logging.getLogger(__name__)

CompleteFn = Callable[[str, str, str, float], Awaitable[dict[str, Any]]]


def prepare_window(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop crisis lines. Silent, undelivered, and proactive lines stay."""
    kept: list[dict[str, Any]] = []
    for row in rows:
        role = str(row.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(row.get("content") or "").strip()
        if not content or is_crisis_text(content):
            continue
        kept.append(
            {
                "role": role,
                "content": content,
                "time": str(row.get("time") or ""),
                "method": str(row.get("method") or ""),
                "seq": row.get("seq"),
            }
        )
    return kept


def _format_window(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, row in enumerate(rows, start=1):
        who = "老师" if row["role"] == "user" else "阿洛娜"
        stamp = row.get("time") or "时间不明"
        channel = row.get("method") or "direct"
        lines.append(f"{index}. [{stamp}][{channel}] {who}：{row['content']}")
    return "\n".join(lines)


def _trim(rows: list[dict[str, Any]], *, max_turns: int, max_chars: int) -> list[dict[str, Any]]:
    window = rows[-max(1, max_turns) :]
    while window and len(_format_window(window)) > max_chars:
        window = window[1:]
    return window


class Extractor:
    def __init__(
        self,
        *,
        events: EventLog,
        commitments: CommitmentBook,
        retriever: EventRetriever,
        trace: TraceLog,
        base_url: str,
        api_key: str,
        model: str,
        timeout_sec: float = 15,
        commitment_model: str = "",
        window_max_turns: int = 40,
        window_max_chars: int = 8000,
        retry_max: int = 2,
        calls_per_day: int = 3000,
        summary_max_chars: int = 300,
        extract_max_new: int = 3,
        current_max_chars: int = 200,
        enabled: bool = True,
        complete: CompleteFn | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.events = events
        self.commitments = commitments
        self.retriever = retriever
        self.trace = trace
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.commitment_model = commitment_model or model
        self.timeout_sec = float(timeout_sec)
        self.window_max_turns = int(window_max_turns)
        self.window_max_chars = int(window_max_chars)
        self.retry_max = max(0, int(retry_max))
        self.calls_per_day = max(0, int(calls_per_day))
        self.summary_max_chars = int(summary_max_chars)
        self.extract_max_new = max(0, int(extract_max_new))
        self.current_max_chars = int(current_max_chars)
        self.enabled = enabled
        self._injected_complete = complete is not None
        self._complete = complete or self._http_complete
        self._clock = clock or datetime.now
        self._queue: asyncio.Queue[list[dict[str, Any]]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._calls = 0
        self._call_day = ""
        self._stopped = False

    def has_api(self) -> bool:
        if not self.enabled:
            return False
        if self._injected_complete:
            return True
        return api_key_ready(self.api_key)

    def enqueue(self, window: list[dict[str, Any]]) -> None:
        self._queue.put_nowait(prepare_window(window))

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stopped = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        while not self._stopped:
            window = await self._queue.get()
            try:
                await self.process(window)
            except Exception:
                logger.exception("memory_v2 extract failed")

    async def process(self, window: list[dict[str, Any]]) -> None:
        rows = _trim(
            prepare_window(window),
            max_turns=self.window_max_turns,
            max_chars=self.window_max_chars,
        )
        if not rows:
            return
        if not self.has_api():
            logger.warning(
                "memory_v2 extract disabled: no API key; nothing was written"
            )
            self.trace.write({"kind": "extract", "skipped": "no_api_key"})
            return
        transcript = _format_window(rows)
        now = self._clock()
        results = await asyncio.gather(
            self._run_layer("events", lambda: self._extract_events(transcript, now)),
            self._run_layer(
                "commitments", lambda: self._extract_commitments(transcript, now)
            ),
        )
        for name, result in zip(("events", "commitments"), results):
            if isinstance(result, Exception):
                logger.warning("memory_v2 %s extract failed: %s", name, result)

    async def _run_layer(self, name: str, factory: Callable[[], Awaitable[None]]) -> None:
        attempts = self.retry_max + 1
        last: Exception | None = None
        for _ in range(attempts):
            try:
                await factory()
                return
            except Exception as exc:
                last = exc
                logger.info("memory_v2 %s extract retry: %s", name, exc)
        if last is not None:
            raise last

    async def _extract_events(self, transcript: str, now: datetime) -> None:
        parsed = await self._call(self.model, event_system(), transcript, now)
        raw_events = parsed.get("events") or []
        if not isinstance(raw_events, list):
            return
        moment = now.timestamp()
        for item in raw_events:
            if not isinstance(item, dict):
                continue
            occurred = parse_timestamp(item.get("occurred_at"), now=now)
            if occurred is None:
                self.trace.write({"kind": "extract_drop", "layer": "events", "reason": "time"})
                continue
            if occurred > moment + 60:
                self.trace.write(
                    {"kind": "extract_drop", "layer": "events", "reason": "not_yet"}
                )
                continue
            summary = str(item.get("summary") or "").strip()
            if not summary or is_crisis_text(summary):
                continue
            summary, cut = truncate_at_sentence(summary, self.summary_max_chars)
            if not summary:
                continue
            importance, clamped = clamp_importance(item.get("importance", 5))
            if cut or clamped:
                self.trace.write(
                    {
                        "kind": "extract_fix",
                        "layer": "events",
                        "truncated": cut,
                        "importance_clamped": clamped,
                    }
                )
            event = self.events.append(
                summary=summary,
                occurred_at=occurred,
                importance=importance,
                source_turn=str(item.get("source_turn") or ""),
                recorded_at=moment,
            )
            self.retriever.add_vector(event.id, event.summary)

    async def _extract_commitments(self, transcript: str, now: datetime) -> None:
        existing = self.commitments.active_whats()
        user = transcript
        if existing:
            user += "\n\n【已有承诺】\n" + "\n".join(f"- {line}" for line in existing)
        else:
            user += "\n\n【已有承诺】\n（无）"
        parsed = await self._call(self.commitment_model, commitment_system(), user, now)
        raw_items = parsed.get("commitments") or []
        if not isinstance(raw_items, list):
            return
        known = {_norm(line) for line in existing}
        added = 0
        for item in raw_items:
            if added >= self.extract_max_new:
                self.trace.write(
                    {"kind": "extract_drop", "layer": "commitments", "reason": "max_new"}
                )
                break
            if not isinstance(item, dict):
                continue
            what = str(item.get("what") or "").strip()
            current = str(item.get("current") or "").strip()
            if not what or has_ephemeral_time(what):
                self.trace.write(
                    {"kind": "extract_drop", "layer": "commitments", "reason": "what"}
                )
                continue
            if _norm(what) in known:
                self.trace.write(
                    {"kind": "extract_drop", "layer": "commitments", "reason": "duplicate"}
                )
                continue
            if not current:
                self.trace.write(
                    {"kind": "extract_drop", "layer": "commitments", "reason": "current"}
                )
                continue
            current, cut = truncate_at_sentence(current, self.current_max_chars)
            if cut:
                self.trace.write(
                    {"kind": "extract_fix", "layer": "commitments", "truncated": True}
                )
            self.commitments.insert(
                what=what,
                current=current,
                created_at=now.timestamp(),
            )
            known.add(_norm(what))
            added += 1

    async def _call(
        self, model: str, system: str, transcript: str, now: datetime
    ) -> dict[str, Any]:
        self._note_call(now)
        user = f"{format_extract_now(now)}\n\n【对话片段】\n{transcript}"
        return await self._complete(model, system, user, self.timeout_sec)

    def _note_call(self, now: datetime) -> None:
        day = now.date().isoformat()
        if day != self._call_day:
            self._call_day = day
            self._calls = 0
        if self._calls >= self.calls_per_day:
            raise RuntimeError("memory_v2 extract daily call limit")
        self._calls += 1

    async def _http_complete(
        self, model: str, system: str, user: str, timeout: float
    ) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
            "response_format": {"type": "json_object"},
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
        content = data["choices"][0]["message"]["content"] or "{}"
        return loads_json_object(str(content))


def _norm(text: str) -> str:
    return "".join((text or "").split())
