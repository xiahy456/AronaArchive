#!/usr/bin/env python3
"""Episodic/emotional extract, same-day merge, and labeled inject.

Run from backend/:
  python scripts/test_episode_memory_unit.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import AppConfig, ExtractorConfig, MemoryConfig, ModelConfig  # noqa: E402
from app.conversation import ConversationManager  # noqa: E402
from app.memory.extractor import (  # noqa: E402
    EXTRACT_SYSTEM,
    MemoryExtractor,
    episode_contents_same_day,
    episode_merge_allowed,
)
from app.memory.fallback import regex_extract_memories  # noqa: E402
from app.memory.normalize import normalize_memory_item  # noqa: E402
from app.memory.trigger import should_extract  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from app.planner.prompts import (  # noqa: E402
    PLANNER_SYSTEM_BASE,
    build_planner_user_message,
)
from app.prompt import EMOTIONAL_INJECT_NOTE, build_messages, format_memory_inject  # noqa: E402
from app.relationship.classify import classify_user_act  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


class _FakeStore:
    def __init__(self, hits: list[dict] | None = None) -> None:
        self.config = MemoryConfig()
        self.hits = list(hits or [])
        self.deleted: list[str] = []
        self.upserted: list[tuple[str, str, str | None]] = []

    def find_similar(self, content, exclude_key=None, top_k=5, min_score=0.0):
        return list(self.hits)

    def find_exact_content(self, content):
        return []

    def upsert(self, key, content, category=None, source=""):
        self.upserted.append((key, content, category))

    def delete(self, key):
        self.deleted.append(key)

    def document_similarities(self, content, candidates):
        return []


def test_extract_schema_and_normalize() -> None:
    print("== extract schema + normalize keep category ==")
    if "episodic" not in EXTRACT_SYSTEM or "emotional" not in EXTRACT_SYSTEM:
        _fail("EXTRACT_SYSTEM must list episodic/emotional")
    if "ep_20260918_fireworks" not in EXTRACT_SYSTEM:
        _fail("EXTRACT_SYSTEM should suggest dated episodic keys")
    if "成功加入了社团" not in EXTRACT_SYSTEM:
        _fail("EXTRACT_SYSTEM should tell completed past facts not to stay as goal")
    item = normalize_memory_item(
        {
            "op": "upsert",
            "key": "ep_20260918_fireworks",
            "content": "老师2026年9月18日和阿洛娜一起看烟花",
            "category": "episodic",
        }
    )
    if item.get("category") != "episodic":
        _fail(f"normalize must keep episodic, got {item}")
    emo = normalize_memory_item(
        {
            "op": "upsert",
            "key": "emo_20260918_overtime",
            "content": "老师2026年9月18日因加班感到难过",
            "category": "EMOTIONAL",
        }
    )
    if emo.get("category") != "emotional":
        _fail(f"normalize must keep emotional, got {emo}")
    print("  ok")


def test_regex_no_episode_cats() -> None:
    print("== regex fallback never writes episodic/emotional ==")
    items = regex_extract_memories("我今天很难过，被批评了，陪我一下")
    cats = {str(item.get("category") or "") for item in items}
    if "episodic" in cats or "emotional" in cats:
        _fail(f"regex must not write episode cats, got {items}")
    print("  ok")


def test_should_extract_mood_and_together() -> None:
    print("== should_extract mood / together ==")
    kwargs = {"turn_count": 1, "every_n_turns": 99}
    if not should_extract("我心里很难过", **kwargs):
        _fail("mood disclosure should extract")
    if not should_extract("我们一起去看了烟花", **kwargs):
        _fail("shared event should extract")
    if should_extract("今天天气真好啊", **kwargs):
        _fail("chit-chat should not extract")
    if classify_user_act("我心里很难过") != "self_disclose":
        _fail("心里很难过 should classify as self_disclose")
    print("  ok")


def test_same_day_merge() -> None:
    print("== same-day merge / cross-day keep ==")
    if not episode_contents_same_day(
        "老师2026年9月18日因加班感到难过",
        "老师2026年9月18日因为加班有点难过",
    ):
        _fail("same calendar day should match")
    if episode_contents_same_day(
        "老师2026年9月18日因加班感到难过",
        "老师2026年9月17日因加班感到难过",
    ):
        _fail("cross-day must not match")
    if episode_contents_same_day("老师因加班感到难过", "老师因加班感到难过"):
        _fail("missing dates must not merge")
    if episode_merge_allowed(
        "preference",
        "老师喜欢蓝色",
        "老师喜欢浅蓝",
    ) is not True:
        _fail("facts may still merge")

    same = _FakeStore(
        [
            {
                "key": "emo_20260918_work",
                "content": "老师2026年9月18日因加班感到难过",
                "category": "emotional",
                "score": 0.95,
            }
        ]
    )
    ext = MemoryExtractor(same, ExtractorConfig())
    keep = ext._upsert_with_dedup(
        key="emo_20260918_overtime",
        content="老师2026年9月18日因为加班有点难过",
        category="emotional",
        source="test",
    )
    merged_keys = {"emo_20260918_work", "emo_20260918_overtime"}
    if not (merged_keys & set(same.deleted)):
        _fail(
            f"same-day emotional near-dup should drop a key, "
            f"keep={keep} deleted={same.deleted}"
        )

    cross = _FakeStore(
        [
            {
                "key": "emo_20260917_overtime",
                "content": "老师2026年9月17日因加班感到难过",
                "category": "emotional",
                "score": 0.95,
            }
        ]
    )
    MemoryExtractor(cross, ExtractorConfig())._upsert_with_dedup(
        key="emo_20260918_overtime",
        content="老师2026年9月18日因加班感到难过",
        category="emotional",
        source="test",
    )
    if cross.deleted:
        _fail(f"cross-day emotional must not merge, deleted={cross.deleted}")

    nodate = _FakeStore(
        [
            {
                "key": "emo_undated",
                "content": "老师因加班感到难过",
                "category": "emotional",
                "score": 0.95,
            }
        ]
    )
    MemoryExtractor(nodate, ExtractorConfig())._reconcile_after_upsert(
        "emo_20260918_overtime",
        "老师2026年9月18日因加班感到难过",
        "emotional",
    )
    if nodate.deleted:
        _fail(f"undated emotional must not reconcile, deleted={nodate.deleted}")
    print("  ok")


def test_crisis_content_skipped() -> None:
    print("== crisis content still skipped ==")
    store = _FakeStore()
    MemoryExtractor(store, ExtractorConfig())._apply(
        [
            {
                "op": "upsert",
                "key": "emo_crisis",
                "content": "老师不想活了",
                "category": "emotional",
            }
        ],
        source="test",
    )
    if store.upserted:
        _fail(f"crisis content must not upsert, got {store.upserted}")
    print("  ok")


def test_labeled_inject() -> None:
    print("== labeled inject facts-first ==")
    entries = [
        {
            "key": "preference_color",
            "content": "老师喜欢蓝色",
            "category": "preference",
        },
        {
            "key": "ep_20260918_fireworks",
            "content": "老师2026年9月18日和阿洛娜一起看烟花",
            "category": "episodic",
        },
        {
            "key": "ep_extra",
            "content": "老师2026年9月18日和阿洛娜一起吃晚饭",
            "category": "episodic",
        },
        {
            "key": "emo_20260918_overtime",
            "content": "老师2026年9月18日因加班感到难过",
            "category": "emotional",
        },
        {
            "key": "emo_crisis",
            "content": "老师不想活了",
            "category": "emotional",
        },
    ]
    injected = format_memory_inject(entries, max_chars=400)
    block = injected.block
    if "【长期记忆】" not in block or "老师喜欢蓝色" not in block:
        _fail(f"facts section missing: {block}")
    if "【共同经历】" not in block or "烟花" not in block:
        _fail(f"episode section missing: {block}")
    if "晚饭" in block:
        _fail(f"must inject at most one episode: {block}")
    if "【老师提过的心情】" not in block or "加班" not in block:
        _fail(f"emotional section missing: {block}")
    if EMOTIONAL_INJECT_NOTE not in block:
        _fail("emotional note missing")
    if "不想活" in block:
        _fail("crisis content must be dropped from inject")

    planner_msg = build_planner_user_message(
        user_text="今天还好吗",
        history=[],
        memories=[],
        knowledge=[],
        memory_block=block,
    )
    if planner_msg.count("【长期记忆】") != 1:
        _fail("planner must not wrap labeled block again")
    if "【共同经历】" not in planner_msg:
        _fail("planner user message should keep episode label")
    if "心情与共同经历不是稳定档案" not in PLANNER_SYSTEM_BASE:
        _fail("daily planner must say moods are not durable persona")

    cfg = AppConfig(model=ModelConfig(enabled=False))
    local = build_messages(
        cfg,
        user_text="今天还好吗",
        history=[],
        memories=[],
        knowledge=[],
        memory_block=block,
    )
    if "【老师提过的心情】" not in local[0]["content"]:
        _fail("local messages should use labeled inject")

    long_facts = [
        {
            "key": f"fact_{i}",
            "content": "老师喜欢草莓牛奶" + ("蓝" * 8),
            "category": "preference",
        }
        for i in range(8)
    ]
    long_facts.append(
        {
            "key": "ep_budget",
            "content": "老师2026年9月18日和阿洛娜一起看烟花",
            "category": "episodic",
        }
    )
    tight = format_memory_inject(long_facts, max_chars=80)
    if "【长期记忆】" not in tight.block:
        _fail("facts should occupy the budget first")
    if "【共同经历】" in tight.block:
        _fail("episode must yield to fact budget")
    print("  ok")


def test_disclose_forces_extract() -> None:
    print("== self_disclose forces extract ==")

    async def _run() -> None:
        extractor = MagicMock()
        extractor.enqueue = AsyncMock()
        cfg = AppConfig(model=ModelConfig(enabled=False))
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
        orch.conversations.append("s1", "user", "我心里很难过")
        orch.conversations.append("s1", "assistant", "老师，阿洛娜在的。")
        await orch._maybe_extract("s1", "我心里很难过")
        if not extractor.enqueue.await_count:
            _fail("self_disclose should enqueue extract")

    asyncio.run(_run())
    print("  ok")


def main() -> None:
    test_extract_schema_and_normalize()
    test_regex_no_episode_cats()
    test_should_extract_mood_and_together()
    test_same_day_merge()
    test_crisis_content_skipped()
    test_labeled_inject()
    test_disclose_forces_extract()
    print("OK: episode memory cases passed")


if __name__ == "__main__":
    main()
