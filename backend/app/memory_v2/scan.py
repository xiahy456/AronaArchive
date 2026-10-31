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

"""Commitment scan loop. It does not run inside the life tick."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx

from app.query_time import format_extract_now, format_full_datetime
from app.safety import is_crisis_text

from .commitments import Commitment, CommitmentBook
from .prompts import scan_system
from .states import StateBook
from .trace import TraceLog
from .util import (
    api_key_ready,
    first_sentence,
    has_ephemeral_time,
    loads_json_object,
    parse_iso_local,
    truncate_at_sentence,
)

logger = logging.getLogger(__name__)

DialogueFn = Callable[[float], list[dict[str, Any]]]
PendingFn = Callable[[], bool]
OfferFn = Callable[[dict[str, Any]], bool]
CompleteFn = Callable[[str, str, float], Awaitable[dict[str, Any]]]
ClockFn = Callable[[], float]
SleepFn = Callable[[float], Awaitable[None]]


def _clamp_interval(value: object, low: int, high: int) -> tuple[int, bool]:
    try:
        number = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return high, True
    if number < low:
        return low, True
    if number > high:
        return high, True
    return number, False


class CommitmentScanner:
    def __init__(
        self,
        *,
        commitments: CommitmentBook,
        states: StateBook,
        trace: TraceLog,
        dialogue: DialogueFn,
        pending_commitment: PendingFn,
        offer: OfferFn,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        timeout_sec: float = 20,
        scan_default_sec: int = 14400,
        scan_max_sec: int = 14400,
        scan_min_sec: int = 300,
        lookback_hours: float = 24,
        inject_max: int = 2,
        current_max_chars: int = 200,
        stale_after_sec: float = 2592000,
        enabled: bool = True,
        complete: CompleteFn | None = None,
        clock: ClockFn | None = None,
        sleeper: SleepFn | None = None,
    ) -> None:
        self.commitments = commitments
        self.states = states
        self.trace = trace
        self.dialogue = dialogue
        self.pending_commitment = pending_commitment
        self.offer = offer
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout_sec = float(timeout_sec)
        self.scan_default_sec = int(scan_default_sec)
        self.scan_max_sec = int(scan_max_sec)
        self.scan_min_sec = int(scan_min_sec)
        self.lookback_hours = float(lookback_hours)
        self.inject_max = max(0, int(inject_max))
        self.current_max_chars = int(current_max_chars)
        self.stale_after_sec = float(stale_after_sec)
        self.enabled = enabled
        self._injected_complete = complete is not None
        self._complete = complete or self._http_complete
        self._clock = clock or (lambda: datetime.now().timestamp())
        self._sleeper = sleeper or asyncio.sleep
        self._stopped = False

    def has_api(self) -> bool:
        if not self.enabled:
            return False
        if self._injected_complete:
            return True
        return api_key_ready(self.api_key)

    async def run(self, stop: asyncio.Event | None = None) -> None:
        self._stopped = False
        while not self._stopped:
            if stop is not None and stop.is_set():
                return
            await self.step()

    def stop(self) -> None:
        self._stopped = True

    async def step(self) -> None:
        now = float(self._clock())
        nxt = self.commitments.next_scan_at()
        if nxt is None:
            nxt = now + self.scan_default_sec
            self.commitments.set_next_scan_at(nxt)
        delay = nxt - float(self._clock())
        if delay > 0:
            await self._sleeper(delay)
        await self.scan_once(float(self._clock()))

    async def scan_once(self, now: float) -> None:
        expired = self.commitments.expire(now, self.stale_after_sec)
        for item in expired:
            self.trace.write(
                {
                    "kind": "commit_expired",
                    "id": item["id"],
                    "idle_sec": item["idle_sec"],
                    "inject_count": item["inject_count"],
                    "last_helpful_injected_at": item["last_helpful_injected_at"],
                },
                at=now,
            )
        active = self.commitments.active()
        considered = [{"id": item.id, "inject_count": item.inject_count} for item in active]
        if not active:
            when = now + self.scan_max_sec
            self.commitments.set_next_scan_at(when)
            self.trace.write(
                {
                    "kind": "scan",
                    "next_after_sec": self.scan_max_sec,
                    "clamped": False,
                    "inject": [],
                    "edits_applied": [],
                    "considered": [],
                    "conflicts": [],
                    "skipped": ["no_active"],
                    "failed": False,
                },
                at=now,
            )
            return
        if not self.has_api():
            logger.warning("memory_v2 commitment scan disabled: no API key")
            when = now + self.scan_max_sec
            self.commitments.set_next_scan_at(when)
            self.trace.write(
                {
                    "kind": "scan",
                    "next_after_sec": self.scan_max_sec,
                    "clamped": False,
                    "inject": [],
                    "edits_applied": [],
                    "considered": considered,
                    "conflicts": [],
                    "skipped": ["no_api_key"],
                    "failed": False,
                },
                at=now,
            )
            return
        prompt = self._prompt(active, now)
        try:
            parsed = await asyncio.wait_for(
                self._complete(self.model, prompt, self.timeout_sec),
                timeout=self.timeout_sec + 1,
            )
        except Exception as exc:
            logger.warning("memory_v2 commitment scan failed: %s", exc)
            self._fail(now, considered)
            return
        if not isinstance(parsed, dict):
            self._fail(now, considered)
            return
        self._apply(parsed, active, now, considered)

    def _fail(self, now: float, considered: list[dict[str, Any]]) -> None:
        self.commitments.set_next_scan_at(now + self.scan_max_sec)
        self.trace.write(
            {
                "kind": "scan",
                "next_after_sec": self.scan_max_sec,
                "clamped": False,
                "inject": [],
                "edits_applied": [],
                "considered": considered,
                "conflicts": [],
                "skipped": [],
                "failed": True,
            },
            at=now,
        )

    def _apply(
        self,
        parsed: dict[str, Any],
        active: list[Commitment],
        now: float,
        considered: list[dict[str, Any]],
    ) -> None:
        known = {item.id: item for item in active}
        interval, clamped = _clamp_interval(
            parsed.get("next_after_sec", self.scan_max_sec),
            self.scan_min_sec,
            self.scan_max_sec,
        )
        edits_applied: list[dict[str, Any]] = []
        conflicts: list[dict[str, str]] = []
        skipped: list[Any] = []
        field_errors: list[dict[str, str]] = []
        edited_ids: set[str] = set()

        raw_edits = parsed.get("edits") or []
        if not isinstance(raw_edits, list):
            raw_edits = []
        for raw in raw_edits:
            if not isinstance(raw, dict):
                continue
            commitment_id = str(raw.get("id") or "").strip()
            if commitment_id not in known:
                skipped.append({"id": commitment_id, "skipped": "unknown_id"})
                continue
            if "active" in raw:
                field_errors.append(
                    {"id": commitment_id, "dropped_field": "active"}
                )
            what = _nonempty(raw.get("what"))
            current = _nonempty(raw.get("current"))
            helpful_given = "last_helpful_injected_at" in raw
            helpful_at: float | None = None
            clear_helpful = False
            if helpful_given:
                if raw.get("last_helpful_injected_at") is None:
                    clear_helpful = True
                else:
                    parsed_at = parse_iso_local(raw.get("last_helpful_injected_at"))
                    if parsed_at is None:
                        field_errors.append(
                            {
                                "id": commitment_id,
                                "field": "last_helpful_injected_at",
                                "reason": "parse_failed",
                            }
                        )
                        helpful_given = False
                    else:
                        if parsed_at.timestamp() > now:
                            parsed_at = datetime.fromtimestamp(now)
                            field_errors.append(
                                {
                                    "id": commitment_id,
                                    "field": "last_helpful_injected_at",
                                    "reason": "clamped_future",
                                }
                            )
                        helpful_at = parsed_at.timestamp()
            if what is None and current is None and not helpful_given and not clear_helpful:
                skipped.append({"id": commitment_id, "skipped": "empty_edit"})
                continue
            if what is not None and has_ephemeral_time(what):
                field_errors.append(
                    {"id": commitment_id, "field": "what", "reason": "ephemeral_time"}
                )
                what = None
            if current is not None:
                current, _cut = truncate_at_sentence(current, self.current_max_chars)
            if what is None and current is None and not helpful_given and not clear_helpful:
                continue
            before = self.commitments.update_fields(
                commitment_id,
                what=what,
                current=current,
                last_helpful_injected_at=helpful_at,
                clear_helpful=clear_helpful,
            )
            if before is None:
                skipped.append({"id": commitment_id, "skipped": "inactive"})
                continue
            fields: list[str] = []
            if what is not None and what != before.what:
                fields.append("what")
                self.trace.write(
                    {
                        "kind": "commit_edit",
                        "id": commitment_id,
                        "field": "what",
                        "before": before.what,
                        "after": what,
                    },
                    at=now,
                )
            if current is not None and current != before.current:
                fields.append("current")
                self.trace.write(
                    {
                        "kind": "commit_edit",
                        "id": commitment_id,
                        "field": "current",
                        "before": before.current,
                        "after": current,
                    },
                    at=now,
                )
            if clear_helpful or (
                helpful_at is not None and helpful_at != before.last_helpful_injected_at
            ):
                fields.append("last_helpful_injected_at")
                self.trace.write(
                    {
                        "kind": "commit_edit",
                        "id": commitment_id,
                        "field": "last_helpful_injected_at",
                        "before": before.last_helpful_injected_at,
                        "after": None if clear_helpful else helpful_at,
                    },
                    at=now,
                )
            if fields:
                edits_applied.append({"id": commitment_id, "fields": fields})
                edited_ids.add(commitment_id)

        raw_inject = parsed.get("inject") or []
        if not isinstance(raw_inject, list):
            raw_inject = []
        inject_ids: list[str] = []
        truncated = ""
        for raw_id in raw_inject:
            commitment_id = str(raw_id or "").strip()
            if not commitment_id:
                continue
            if commitment_id in edited_ids:
                conflicts.append({"id": commitment_id, "conflict": "edit_wins"})
                continue
            if commitment_id not in known:
                skipped.append({"id": commitment_id, "skipped": "unknown_id"})
                continue
            if len(inject_ids) >= self.inject_max:
                truncated = "inject"
                continue
            inject_ids.append(commitment_id)

        deferred = ""
        offered_ids: list[str] = []
        if inject_ids:
            if self.pending_commitment():
                deferred = "pending_commitment"
            else:
                fresh = {item.id: item for item in self.commitments.active()}
                lines = []
                hints = []
                for commitment_id in inject_ids:
                    item = fresh.get(commitment_id)
                    if item is None:
                        skipped.append({"id": commitment_id, "skipped": "inactive"})
                        continue
                    lines.append(item.what)
                    hints.append(first_sentence(item.what))
                if lines:
                    accepted = self.offer(
                        {
                            "kind": "commitment",
                            "source_id": inject_ids[0],
                            "hint": "".join(hints),
                            "extra_memories": lines,
                        }
                    )
                    if accepted:
                        offered_ids = [
                            commitment_id
                            for commitment_id in inject_ids
                            if commitment_id in fresh
                        ]
                        self.commitments.mark_injected(offered_ids, now)
                    else:
                        deferred = "pending_commitment"

        self.commitments.set_next_scan_at(now + interval)
        self.trace.write(
            {
                "kind": "scan",
                "next_after_sec": interval,
                "clamped": clamped,
                "inject": offered_ids,
                "inject_requested": inject_ids,
                "edits_applied": edits_applied,
                "considered": considered,
                "conflicts": conflicts,
                "skipped": skipped,
                "field_errors": field_errors,
                "truncated": truncated,
                "deferred": deferred,
                "failed": False,
            },
            at=now,
        )

    def _prompt(self, active: list[Commitment], now: float) -> str:
        moment = datetime.fromtimestamp(now)
        since = now - self.lookback_hours * 3600
        lines = [format_extract_now(moment), "", "【最近对话】"]
        dialogue = self.dialogue(since)
        if not dialogue:
            lines.append("（无）")
        else:
            for row in dialogue:
                role = str(row.get("role") or "")
                who = "老师" if role == "user" else "阿洛娜"
                content = str(row.get("content") or "").strip()
                if not content or is_crisis_text(content):
                    continue
                stamp = str(row.get("time") or "")
                if not stamp:
                    spoken = row.get("at")
                    if isinstance(spoken, (int, float)):
                        stamp = format_full_datetime(datetime.fromtimestamp(float(spoken)))
                channel = str(row.get("method") or "direct")
                lines.append(f"[{stamp}][{channel}] {who}：{content}")
        lines.append("")
        lines.append("【生效中的承诺】")
        for item in active:
            current = item.current.strip() or "（无）"
            lines.append(f"- id={item.id}")
            lines.append(f"  what: {item.what}")
            lines.append(f"  current: {current}")
        lines.append("")
        lines.append("【老师当前情况】")
        live = [
            line
            for line in self.states.live(now)
            if line.strip() and not is_crisis_text(line)
        ]
        if live:
            lines.extend(f"- {line}" for line in live)
        else:
            lines.append("（无）")
        return "\n".join(lines)

    async def _http_complete(self, model: str, user: str, timeout: float) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": scan_system()},
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


def _nonempty(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def run_commitment_scan(scanner: CommitmentScanner, stop: asyncio.Event) -> None:
    await scanner.run(stop)
