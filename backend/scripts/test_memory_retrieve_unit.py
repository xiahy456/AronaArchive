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

"""RRF fusion, entity channel, and episodic-only cooldown.

Run from backend/:
  python scripts/test_memory_retrieve_unit.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import AppConfig  # noqa: E402
from app.memory.retrieve import rrf_fuse  # noqa: E402
from app.memory.store import MemoryStore  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def test_rrf_order() -> None:
    print("== rrf order ==")
    fused = rrf_fuse([["name", "nap"], ["name"]])
    if fused["name"] <= fused["nap"]:
        _fail(f"name should outrank nap: {fused}")
    print("  ok")


def test_entity_and_cooldown() -> None:
    print("== entity channel and cooldown ==")
    now = datetime(2026, 10, 27, 10, 0)
    cfg = AppConfig()
    cfg.memory.rerank_enabled = False
    cfg.memory.inject_cooldown_sec = 3600
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = MemoryStore(cfg, db_path=Path(tmp) / "memory.db")
        store.upsert(
            "place_fact",
            "老师2026年10月27日去了深圳",
            category="other",
            entities=["深圳"],
            importance=8,
        )
        store.upsert(
            "old_episode",
            "老师2026年10月20日和阿洛娜出去过",
            category="episodic",
            entities=["公园"],
        )
        store._vector_candidates = lambda embedding, limit: {}  # type: ignore[method-assign]
        store._fts_candidate_keys = lambda query, limit: []  # type: ignore[method-assign]
        store._score_fts_keys = lambda keys, embedding: {}  # type: ignore[method-assign]
        hits = store.retrieve_entries(
            "深圳",
            top_k=3,
            query_embedding=[0.1, 0.2],
            include_time=False,
            now=now,
            apply_inject_cooldown=True,
        )
        contents = [item["content"] for item in hits]
        if not contents or "深圳" not in contents[0]:
            _fail(f"entity channel should surface Shenzhen: {contents}")
        store.mark_injected(["old_episode", "place_fact"])
        cooled = store.retrieve_entries(
            "公园",
            top_k=3,
            query_embedding=[0.1, 0.2],
            include_time=False,
            now=now,
            apply_inject_cooldown=True,
        )
        cooled_keys = [item["key"] for item in cooled]
        if "old_episode" in cooled_keys:
            _fail(f"episodic cooldown should hide the walk: {cooled_keys}")
        again = store.retrieve_entries(
            "深圳",
            top_k=3,
            query_embedding=[0.1, 0.2],
            include_time=False,
            now=now,
            apply_inject_cooldown=True,
        )
        if "place_fact" not in [item["key"] for item in again]:
            _fail(f"facts must ignore cooldown: {again}")
    print("  ok")


def test_rerank_and_filter_fallback() -> None:
    print("== rerank missing and filter fallback ==")
    from app.config import ExtractorConfig, MemoryConfig
    from app.memory.filter import filter_entries
    from app.rerank import rerank_missing_reason

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        missing = rerank_missing_reason(Path(tmp) / "bge-reranker-base")
        if not missing:
            _fail("a missing reranker directory must explain the fallback")
        cfg = AppConfig()
        cfg.memory.rerank_enabled = True
        store = MemoryStore(cfg, db_path=Path(tmp) / "memory.db")
        store.reranker = None
        store.upsert("place_fact", "老师2026年10月27日去了深圳", category="other", entities=["深圳"])
        store._vector_candidates = lambda embedding, limit: {}  # type: ignore[method-assign]
        store._fts_candidate_keys = lambda query, limit: []  # type: ignore[method-assign]
        store._score_fts_keys = lambda keys, embedding: {}  # type: ignore[method-assign]
        hits = store.retrieve_entries(
            "深圳",
            top_k=3,
            query_embedding=[0.1, 0.2],
            include_time=False,
            now=datetime(2026, 10, 27, 10, 0),
        )
        if not hits or "深圳" not in hits[0]["content"]:
            _fail(f"missing reranker must keep the fused order: {hits}")

    async def _filter() -> None:
        entries = [
            {"key": "a", "content": "老师在深圳"},
            {"key": "b", "content": "老师喜欢蓝色"},
        ]
        kept = await filter_entries(
            memory_config=MemoryConfig(llm_filter_enabled=True, llm_filter_timeout_sec=0.2),
            extractor_config=ExtractorConfig(api_key="test-key", base_url="http://127.0.0.1:1"),
            query="这段代码报错了",
            entries=entries,
        )
        if kept != entries:
            _fail(f"filter failure must keep the ranked list: {kept}")

    asyncio.run(_filter())
    print("  ok")


def main() -> int:
    test_rrf_order()
    test_entity_and_cooldown()
    test_rerank_and_filter_fallback()
    print("retrieve unit ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
