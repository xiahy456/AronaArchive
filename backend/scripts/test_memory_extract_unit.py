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

"""Parallel fact / state / commitment extraction.

Run from backend/:
  python scripts/test_memory_extract_unit.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import ExtractorConfig, MemoryConfig  # noqa: E402
from app.memory.commitment import CommitmentStore  # noqa: E402
from app.memory.extractor import MemoryExtractor  # noqa: E402
from app.memory.prompts import COMMITMENT_SYSTEM, FACT_SYSTEM, STATE_SYSTEM  # noqa: E402
from app.memory.state import StateStore  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


class _FactStore:
    def __init__(self) -> None:
        self.config = MemoryConfig()
        self.rows: list[dict] = []

    def upsert(self, key, content, category=None, source="", importance=None, entities=None):
        self.rows.append(
            {
                "key": key,
                "content": content,
                "category": category,
                "importance": importance,
                "entities": entities,
            }
        )

    def delete(self, key):
        return None

    def find_similar(self, *args, **kwargs):
        return []

    def find_exact_content(self, content):
        return []

    def document_similarities(self, content, candidates):
        return []


def test_parallel_apply() -> None:
    print("== parallel extract apply ==")

    async def _run() -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            facts = _FactStore()
            states = StateStore(root / "memory.db", max_chars=32)
            commitments = CommitmentStore(root / "memory.db")
            extractor = MemoryExtractor(
                facts,  # type: ignore[arg-type]
                ExtractorConfig(api_key="test-key", fallback="none"),
                state_store=states,
                commitment_store=commitments,
            )
            seen: list[str] = []

            async def _fake(system: str, user_payload: str) -> dict:
                seen.append(system)
                await asyncio.sleep(0.01)
                if system is STATE_SYSTEM:
                    return {
                        "items": [
                            {
                                "op": "upsert",
                                "id": "place",
                                "text": "老师2026年10月27日在深圳",
                                "importance": 7,
                            }
                        ]
                    }
                if system is COMMITMENT_SYSTEM:
                    return {
                        "items": [
                            {
                                "op": "create",
                                "id": "meds",
                                "what": "提醒老师吃药",
                                "rrule": "daily",
                                "at_time": "08:00",
                            }
                        ]
                    }
                if system is FACT_SYSTEM:
                    return {
                        "memories": [
                            {
                                "op": "upsert",
                                "key": "trip_shenzhen",
                                "content": "老师2026年10月27日去了深圳",
                                "category": "episodic",
                                "importance": 6,
                                "entities": ["深圳"],
                            }
                        ]
                    }
                _fail(f"unexpected system: {system[:40]}")
                return {}

            extractor._call_llm = _fake  # type: ignore[method-assign]
            await extractor._process(
                {
                    "transcript": "老师：我今天去深圳。希望阿洛娜每天提醒我吃药。",
                    "user_text": "希望阿洛娜每天提醒我吃药",
                    "user_turns": ["我今天去深圳", "希望阿洛娜每天提醒我吃药"],
                    "kinds": ["fact", "state", "commitment"],
                    "retries": {},
                }
            )
            if len(seen) != 3:
                _fail(f"expected 3 extractor calls, got {len(seen)}")
            if facts.rows[0]["importance"] != 6 or facts.rows[0]["entities"] != ["深圳"]:
                _fail(f"fact attributes missing: {facts.rows}")
            if states.texts() != ["老师2026年10月27日在深圳"]:
                _fail(f"state not written: {states.texts()}")
            if not any(item.id == "meds" for item in commitments.active()):
                _fail("commitment not written")
            if extractor._calls_today != 3:
                _fail(f"quota should count each kind: {extractor._calls_today}")

    asyncio.run(_run())
    print("  ok")


def test_failed_kind_requeues() -> None:
    print("== failed kind requeues alone ==")

    async def _run() -> None:
        extractor = MemoryExtractor(
            _FactStore(),  # type: ignore[arg-type]
            ExtractorConfig(api_key="test-key", extract_retry_max=2, fallback="none"),
        )
        queued: list[dict] = []

        async def _put(job: dict) -> None:
            queued.append(job)

        extractor._queue.put = _put  # type: ignore[method-assign]

        async def _boom(system: str, user_payload: str) -> dict:
            raise RuntimeError("down")

        extractor._call_llm = _boom  # type: ignore[method-assign]
        await extractor._process(
            {
                "transcript": "老师：记住我喜欢蓝色。",
                "user_text": "记住我喜欢蓝色",
                "user_turns": ["记住我喜欢蓝色"],
                "kinds": ["fact"],
                "retries": {},
            }
        )
        if not queued or queued[0].get("kinds") != ["fact"]:
            _fail(f"fact failure should requeue fact only: {queued}")
        if int(queued[0]["retries"].get("fact") or 0) != 1:
            _fail(f"retry count missing: {queued}")

    asyncio.run(_run())
    print("  ok")


def main() -> int:
    test_parallel_apply()
    test_failed_kind_requeues()
    print("extract unit ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
