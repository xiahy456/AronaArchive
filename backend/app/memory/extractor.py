# Copyright 2026 xia_hy456. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Async DeepSeek memory extraction queue."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from ..config import ExtractorConfig, MemoryConfig
from ..query_time import format_extract_now, parse_content_datetimes
from ..safety import is_crisis_text, turns_contain_crisis
from ..taxonomy import normalize_memory_category
from .fallback import regex_extract_memories
from .normalize import normalize_memory_item
from .store import MemoryStore, normalize_content_for_compare
from .validate import memory_reject_reason

logger = logging.getLogger(__name__)

_HOT_KEYS = frozenset({"user_name", "preference_color", "user_birthday"})

EXTRACT_SYSTEM = """你是记忆抽取助手。根据「用户（老师）」与「阿洛娜」的对话片段、【当前时间】，以及可选的【已有相关记忆】，提取需要长期记住或需要更新/清除的用户（老师）事实。

只输出 JSON，格式：
{"memories":[{"op":"upsert或delete","key":"英文蛇形键","content":"短中文陈述句","category":"preference|profile|goal|other|episodic|emotional"}]}

规则：
- 只提取已确认的精确事实（名字、偏好、约定、未完成的计划）、已确认的共处事件、已确认的心情披露，不要闲聊、不要世界观百科。
- 无值得记忆的内容时返回 {"memories":[]}
- content 必须是短陈述句；delete 时可省略 content 或沿用旧内容
- 禁止疑问句、反问、猜测或未确认信息；错误示例：「老师喜欢什么颜色吗」
- 不要把老师的提问本身当成事实写入
- 禁止提取自伤、轻生、不想活、结束生命等危机内容
- category 含义：
  - preference：稳定偏好（颜色、食物等）
  - profile：档案信息（名字、生日等）
  - goal：未完成的计划/打算/约定（临时意图）
  - other：其它稳定事实
  - episodic：老师与阿洛娜的共处事件（「一起做过 X」），不是稳定档案。key 建议带日期，如 ep_20260918_fireworks。同日同主题才复用 key；跨日的相似事件必须新 key。禁止写成「老师经常和阿洛娜去看烟花」这类永恒人格。
  - emotional：已确认的心情披露 + 原因（「因 Y 感到难过/开心」），不是猜测、不是未说出口的分析。key 建议带日期，如 emo_20260918_overtime。同日同主题才复用 key；跨日的相似心情必须新 key。禁止写成「老师是个容易难过的人」这类永恒人格。
- 时间写入 content（对照【当前时间】换算，禁止保留相对说法）：
  - 按能确定的最细粒度写：能确定到日则写年月日（「今天 / 明天 / 后天 / 昨天 / 下周一」，如 2026年8月23日）；只能确定到月则写年月（「下个月 / 上个月 / 这个月」，如 2026年9月）；只能确定到年则写年份（「明年 / 去年」）。「下个月3号」这类已点明日的，仍写到日，不要停在月。缺少年份的绝对日期（如「8月31号」）用【当前时间】补全年份。
  - 钟点可保留，但必须带日期。正确：「老师2026年8月24日下午4点睡到晚上7点」；错误：「老师今天下午4点睡到晚上7点」
  - 区间写成覆盖的具体日期：未指定落在哪一天时用「或」（二选一）；连续时段用「到」。正确：「老师2026年8月22日或2026年8月23日要去医院」、「老师2026年8月31日到2026年9月6日要每天11点睡觉」；错误：「老师周末要去医院」、「老师下周要每天11点睡觉」。
  - 过去时态 → 最近已发生的那个日期；将来/打算 → 即将到来的那个日期；拿不准时按即将到来的日期写
  - 对话已给出带年的绝对日期则沿用，不要改成抽取当日
  - 无时间含义的稳定事实（名字、偏好、生日本身）不要硬加抽取当日
  - 无明确起止的周期性习惯保留周期表述（如「老师每周五加班」），不要压成某一天；若周期带有明确时段（如下周每天），则写成日期区间并保留周期
- 若提供了【已有相关记忆】：
  - 同主题新事实与旧记忆冲突时必须二选一：复用旧 key 做 upsert，或对旧 key 输出 op=delete 后再 upsert 新 key。禁止让冲突的旧记忆继续存在。
  - 优先复用已有记忆的 key；仅当主题全新时才新建 key
  - 对照集里出现的同主题旧条目，若本轮要写入新事实，必须在输出中点名（upsert 或 delete），不要默不作声地另开一条
  - goal：对话表明该计划已执行、正在执行或已取消时，对该 goal 的 key 输出 op=delete，不要再 upsert。对照集里的过期/已完成 goal 必须 delete
  - 已发生且无后续待办的事实不要写成 goal（例如「老师成功加入了社团」用 episodic 或 other），并 delete 对照集里同主题的旧 goal。若老师只是答应以后再做，不算已完成，不要 delete
- 高频稳定 key（若适用请直接使用）：user_name、preference_color、user_birthday
- 只记录与用户（老师）相关的记忆；例如「老师喜欢蓝色」
- 记忆必须来自于用户（老师）所述。对于阿洛娜口述的老师记忆，除非得到老师肯定，否则判定为无效。
"""


def _format_existing_memories(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "【已有相关记忆】\n（无）"
    lines = ["【已有相关记忆】"]
    for e in entries:
        lines.append(
            f"- key={e.get('key')} | category={e.get('category') or 'other'} | content={e.get('content')}"
        )
    return "\n".join(lines)


_EPISODE_CATEGORIES = frozenset({"episodic", "emotional"})


def episode_contents_same_day(left: str, right: str) -> bool:
    """True when both contents resolve to at least one shared calendar day."""
    left_days = {dt.date() for dt in parse_content_datetimes(left)}
    right_days = {dt.date() for dt in parse_content_datetimes(right)}
    if not left_days or not right_days:
        return False
    return bool(left_days & right_days)


def episode_merge_allowed(category: str, new_content: str, old_content: str) -> bool:
    """Facts may merge as before; episodic/emotional only on the same calendar day."""
    cat = (category or "").strip()
    if cat not in _EPISODE_CATEGORIES:
        return True
    return episode_contents_same_day(new_content, old_content)


def _category_of(item: dict[str, Any] | None, fallback: str | None = None) -> str:
    if item is not None:
        cat = item.get("category")
        if isinstance(cat, str) and cat.strip():
            return normalize_memory_category(cat)
    if isinstance(fallback, str) and fallback.strip():
        return normalize_memory_category(fallback)
    return "other"


def _pick_keep_key(
    new_key: str,
    candidates: list[dict[str, Any]],
) -> str:
    """Prefer hot slots, then new_key if already present, else highest-score candidate."""
    keys = {str(c.get("key") or "").strip() for c in candidates}
    keys.discard("")
    keys.add(new_key)

    for hot in ("preference_color", "user_name", "user_birthday"):
        if hot in keys:
            return hot
    if new_key in {str(c.get("key") or "").strip() for c in candidates}:
        return new_key
    ranked = sorted(
        (c for c in candidates if str(c.get("key") or "").strip()),
        key=lambda c: float(c.get("score") or 0.0),
        reverse=True,
    )
    if ranked:
        return str(ranked[0]["key"]).strip()
    return new_key


def _collapse_batch_upserts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Within one extract batch, keep last upsert per normalized content; prefer hot keys."""
    deletes: list[dict[str, Any]] = []
    # group_key -> item (later overwrites earlier)
    groups: dict[str, dict[str, Any]] = {}
    group_order: list[str] = []

    for item in items:
        op = str(item.get("op") or "upsert").lower()
        if op == "delete":
            deletes.append(item)
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        gkey = normalize_content_for_compare(content)
        key = str(item.get("key") or "").strip()
        prev = groups.get(gkey)
        if prev is None:
            groups[gkey] = dict(item)
            group_order.append(gkey)
            continue
        # Later item wins content; prefer hot key when either side has one.
        merged = dict(item)
        prev_key = str(prev.get("key") or "").strip()
        if key not in _HOT_KEYS and prev_key in _HOT_KEYS:
            merged["key"] = prev_key
        elif key in _HOT_KEYS:
            merged["key"] = key
        elif prev_key and not key:
            merged["key"] = prev_key
        groups[gkey] = merged

    return deletes + [groups[k] for k in group_order]


class MemoryExtractor:
    def __init__(self, store: MemoryStore, config: ExtractorConfig) -> None:
        self.store = store
        self.config = config
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._calls_today = 0
        self._calls_day = time.strftime("%Y-%m-%d")
        self.on_memory_upsert: Any = None

    @property
    def memory_config(self) -> MemoryConfig:
        return self.store.config

    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker(), name="memory-extractor")

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def enqueue(
        self,
        *,
        transcript: str,
        user_text: str,
        user_turns: list[str] | None = None,
    ) -> None:
        if not self.config.enabled:
            logger.info("memory extractor disabled; skip enqueue")
            return
        turns = [str(t).strip() for t in (user_turns or []) if str(t).strip()]
        if turns_contain_crisis(user_text, turns):
            logger.info(
                "memory extract skipped reason=crisis user_text=%r user_turns=%d",
                user_text,
                len(turns),
            )
            return
        qsize = self._queue.qsize() + 1
        logger.info(
            "memory extract queued qsize=%d user_text=%r user_turns=%d",
            qsize,
            user_text,
            len(turns),
        )
        await self._queue.put(
            {"transcript": transcript, "user_text": user_text, "user_turns": turns}
        )

    def _reset_daily_if_needed(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if today != self._calls_day:
            self._calls_day = today
            self._calls_today = 0

    def _under_quota(self) -> bool:
        self._reset_daily_if_needed()
        return self._calls_today < self.config.max_calls_per_day

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                await self._process(job)
            except Exception:
                logger.exception("Memory extraction job failed")
            finally:
                self._queue.task_done()

    def _load_extract_context(
        self,
        user_text: str,
        user_turns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        queries: list[str] = []
        seen_q: set[str] = set()
        for text in user_turns or []:
            query = (text or "").strip()
            if query and query not in seen_q:
                seen_q.add(query)
                queries.append(query)
        fallback = (user_text or "").strip()
        if not queries and fallback:
            queries = [fallback]

        by_key: dict[str, dict[str, Any]] = {}
        top_k = max(1, int(self.memory_config.extract_context_top_k))
        embeddings: list[list[float]] | None = None
        if queries:
            try:
                embeddings = self.store.encode_queries(queries)
            except Exception:
                logger.exception("Failed to encode extract context queries")
                embeddings = None
            for index, query in enumerate(queries):
                embedding = None
                if embeddings is not None and index < len(embeddings):
                    embedding = embeddings[index]
                try:
                    hits = self.store.retrieve_entries(
                        query,
                        top_k,
                        query_embedding=embedding,
                        apply_inject_cooldown=False,
                        apply_score_filter=False,
                        include_time=True,
                    )
                except Exception:
                    logger.exception("Failed to load extract context memories query=%r", query)
                    hits = []
                for hit in hits:
                    key = str(hit.get("key") or "").strip()
                    if not key:
                        continue
                    prev = by_key.get(key)
                    if prev is None or float(hit.get("score") or 0.0) > float(
                        prev.get("score") or 0.0
                    ):
                        by_key[key] = dict(hit)

        try:
            for goal in self.store.list_by_category("goal"):
                key = str(goal.get("key") or "").strip()
                content = str(goal.get("content") or "").strip()
                if not key or not content:
                    continue
                if key not in by_key:
                    by_key[key] = {
                        "key": key,
                        "content": content,
                        "category": "goal",
                        "score": 1.0,
                    }
                by_key[key]["pinned"] = True
        except Exception:
            logger.exception("Failed to pin goal memories for extract context")

        try:
            for entry in self.store.get_entries(sorted(_HOT_KEYS)):
                key = str(entry.get("key") or "").strip()
                if not key:
                    continue
                if key not in by_key:
                    by_key[key] = dict(entry)
                by_key[key]["pinned"] = True
        except Exception:
            logger.exception("Failed to pin hot-key memories for extract context")

        pinned = [item for item in by_key.values() if item.get("pinned")]
        rest = [item for item in by_key.values() if not item.get("pinned")]
        rest.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        max_items = max(1, int(self.memory_config.extract_context_max_items))
        leftover_slots = max(0, max_items - len(pinned))
        selected = pinned + rest[:leftover_slots]
        for item in selected:
            item.pop("pinned", None)
        logger.info(
            "extract context queries=%d hits=%d pinned=%d items=%s",
            len(queries),
            len(selected),
            len(pinned),
            [(e.get("key"), str(e.get("content") or "")[:40]) for e in selected],
        )
        return selected

    async def _process(self, job: dict[str, Any]) -> None:
        transcript = job.get("transcript") or ""
        user_text = job.get("user_text") or ""
        user_turns = job.get("user_turns") or []
        if not isinstance(user_turns, list):
            user_turns = []
        if turns_contain_crisis(user_text, [str(t) for t in user_turns]):
            logger.info(
                "memory extract dropped reason=crisis user_text=%r user_turns=%d",
                user_text,
                len(user_turns),
            )
            return
        logger.info(
            "memory extract start user_text=%r user_turns=%d transcript_chars=%d",
            user_text,
            len(user_turns),
            len(transcript),
        )

        existing = self._load_extract_context(user_text, user_turns)
        memories: list[dict[str, Any]] = []
        used_api = False

        if self._under_quota() and self.config.api_key and self.config.api_key != "YOUR_DEEPSEEK_API_KEY":
            try:
                memories = await self._call_deepseek(transcript, existing)
                used_api = True
                self._calls_today += 1
                logger.info(
                    "DeepSeek extract ok calls_today=%d memories=%d items=%s",
                    self._calls_today,
                    len(memories),
                    memories,
                )
            except Exception as exc:
                logger.warning("DeepSeek extract failed: %s", exc)
                memories = []
        else:
            logger.info(
                "DeepSeek extract skipped under_quota=%s has_key=%s",
                self._under_quota(),
                bool(self.config.api_key and self.config.api_key != "YOUR_DEEPSEEK_API_KEY"),
            )

        if not memories and self.config.fallback == "regex":
            memories = regex_extract_memories(user_text)
            if memories:
                logger.info("Applied regex fallback memories: %s", memories)
            else:
                logger.info("regex fallback found no memories")

        source = "deepseek" if used_api else "regex"
        self._apply(memories, source=source, existing=existing)
        logger.info(
            "memory extract done source=%s applied=%d",
            source,
            len(memories),
        )

    async def _call_deepseek(
        self,
        transcript: str,
        existing: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        user_payload = (
            f"{format_extract_now()}\n\n"
            f"{_format_existing_memories(existing)}\n\n【对话片段】\n{transcript}"
        )
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": user_payload},
            ],
            "temperature": 0.1,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
            # DeepSeek V4: disable thinking for extraction
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.config.timeout_sec) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"] or "{}"
        parsed = json.loads(content)
        items = parsed.get("memories") or []
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def _reconcile_after_upsert(self, key: str, content: str, category: str | None) -> None:
        cfg = self.memory_config
        if not cfg.reconcile_enabled:
            return
        cat = (category or "other").strip() or "other"
        # Goals must only be cleared by explicit delete from extraction.
        if cat == "goal":
            return
        try:
            similar = self.store.find_similar(
                content,
                exclude_key=key,
                top_k=max(1, int(cfg.reconcile_top_k)),
                min_score=float(cfg.reconcile_min_score),
            )
        except Exception:
            logger.exception("reconcile find_similar failed key=%s", key)
            return

        for hit in similar:
            hit_key = str(hit.get("key") or "").strip()
            hit_cat = str(hit.get("category") or "other").strip() or "other"
            if not hit_key or hit_key == key:
                continue
            if hit_cat == "goal":
                continue
            if hit_cat != cat:
                continue
            if not episode_merge_allowed(
                cat, content, str(hit.get("content") or "")
            ):
                continue
            score = float(hit.get("score") or 0.0)
            logger.info(
                "reconcile delete key=%s because of key=%s score=%.3f",
                hit_key,
                key,
                score,
            )
            self.store.delete(hit_key)

    def _collect_dedup_candidates(
        self,
        content: str,
        *,
        category: str,
        new_key: str,
    ) -> list[dict[str, Any]]:
        cfg = self.memory_config
        by_key: dict[str, dict[str, Any]] = {}

        try:
            for hit in self.store.find_exact_content(content):
                hit_key = str(hit.get("key") or "").strip()
                hit_cat = _category_of(hit)
                if not hit_key or hit_cat == "goal":
                    continue
                if hit_cat != category:
                    continue
                if not episode_merge_allowed(
                    category, content, str(hit.get("content") or "")
                ):
                    continue
                by_key[hit_key] = hit
        except Exception:
            logger.exception("dedup find_exact_content failed content=%r", content[:80])

        try:
            similar = self.store.find_similar(
                content,
                exclude_key=None,
                top_k=max(1, int(cfg.reconcile_top_k)),
                min_score=float(cfg.dedup_min_score),
            )
        except Exception:
            logger.exception("dedup find_similar failed content=%r", content[:80])
            similar = []

        for hit in similar:
            hit_key = str(hit.get("key") or "").strip()
            hit_cat = _category_of(hit)
            if not hit_key or hit_cat == "goal":
                continue
            if hit_cat != category:
                continue
            if not episode_merge_allowed(
                category, content, str(hit.get("content") or "")
            ):
                continue
            prev = by_key.get(hit_key)
            if prev is None or float(hit.get("score") or 0.0) > float(prev.get("score") or 0.0):
                by_key[hit_key] = hit

        # Self-hit on new_key alone is not a duplicate set.
        if set(by_key.keys()) <= {new_key}:
            return []
        return list(by_key.values())

    def _upsert_with_dedup(
        self,
        *,
        key: str,
        content: str,
        category: str | None,
        source: str,
    ) -> str:
        cfg = self.memory_config
        cat = (category or "other").strip() or "other"

        if not cfg.dedup_enabled or cat == "goal":
            self.store.upsert(key, content, category=category, source=source)
            self._reconcile_after_upsert(key, content, category)
            return key

        candidates = self._collect_dedup_candidates(content, category=cat, new_key=key)
        if not candidates:
            self.store.upsert(key, content, category=category, source=source)
            self._reconcile_after_upsert(key, content, category)
            return key

        keep_key = _pick_keep_key(key, candidates)
        drop_keys = sorted(
            {
                str(c.get("key") or "").strip()
                for c in candidates
                if str(c.get("key") or "").strip() and str(c.get("key") or "").strip() != keep_key
            }
            | ({key} if key != keep_key else set())
        )
        best_score = max((float(c.get("score") or 0.0) for c in candidates), default=0.0)
        self.store.upsert(keep_key, content, category=category, source=source)
        for drop in drop_keys:
            if drop == keep_key:
                continue
            self.store.delete(drop)
        logger.info(
            "dedup merge keep=%s drop=%s score=%.3f content=%r",
            keep_key,
            drop_keys,
            best_score,
            content,
        )
        self._reconcile_after_upsert(keep_key, content, category)
        return keep_key

    def _drop_unaddressed_context_conflicts(
        self,
        existing: list[dict[str, Any]],
        addressed_keys: set[str],
        upserted: list[dict[str, Any]],
    ) -> None:
        min_score = float(self.memory_config.extract_conflict_min_score)
        if min_score <= 0 or not existing or not upserted:
            return
        leftover = [
            item
            for item in existing
            if str(item.get("key") or "").strip()
            and str(item.get("key") or "").strip() not in addressed_keys
        ]
        if not leftover:
            return
        for item in upserted:
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            cat = _category_of(item)
            same_cat = [
                candidate
                for candidate in leftover
                if _category_of(candidate) == cat
                and str(candidate.get("key") or "").strip() not in addressed_keys
                and episode_merge_allowed(
                    cat, content, str(candidate.get("content") or "")
                )
            ]
            if not same_cat:
                continue
            try:
                scored = self.store.document_similarities(content, same_cat)
            except Exception:
                logger.exception(
                    "extract conflict score failed content=%r",
                    content[:80],
                )
                continue
            for key, score in scored:
                if not key or key in addressed_keys or score < min_score:
                    continue
                logger.info(
                    "extract conflict delete key=%s because of upsert=%s score=%.3f",
                    key,
                    item.get("key"),
                    score,
                )
                self.store.delete(key)
                addressed_keys.add(key)

    def _apply(
        self,
        memories: list[dict[str, Any]],
        *,
        source: str,
        existing: list[dict[str, Any]] | None = None,
    ) -> None:
        normalized: list[dict[str, Any]] = []
        for raw in memories:
            item = normalize_memory_item(raw)
            op = (item.get("op") or "upsert").lower()
            key = str(item.get("key") or "").strip()
            content = str(item.get("content") or "").strip()
            category = item.get("category")
            if isinstance(category, str) and category.strip():
                category = normalize_memory_category(category)
            else:
                category = None
            if not key:
                continue
            item = {
                "op": op,
                "key": key,
                "content": content,
                "category": category,
            }
            if op == "upsert" and content:
                if is_crisis_text(content):
                    logger.info(
                        "memory upsert skipped reason=crisis key=%r content=%r source=%s",
                        key,
                        content,
                        source,
                    )
                    continue
                reason = memory_reject_reason(key, content)
                if reason:
                    logger.info(
                        "memory upsert skipped reason=%s key=%r content=%r source=%s",
                        reason,
                        key,
                        content,
                        source,
                    )
                    continue
            normalized.append(item)

        addressed: set[str] = set()
        upserted: list[dict[str, Any]] = []
        for item in _collapse_batch_upserts(normalized):
            op = str(item.get("op") or "upsert").lower()
            key = str(item.get("key") or "").strip()
            content = str(item.get("content") or "").strip()
            category = item.get("category")
            if isinstance(category, str) and category.strip():
                category = normalize_memory_category(category)
            else:
                category = None
            if not key:
                continue
            if op == "delete":
                self.store.delete(key)
                addressed.add(key)
            elif op == "upsert" and content:
                keep_key = self._upsert_with_dedup(
                    key=key,
                    content=content,
                    category=category,
                    source=source,
                )
                addressed.add(key)
                if keep_key:
                    addressed.add(keep_key)
                upserted.append(
                    {
                        "op": "upsert",
                        "key": keep_key or key,
                        "content": content,
                        "category": category,
                    }
                )
                if category in {"goal", "emotional"} and self.on_memory_upsert is not None:
                    try:
                        self.on_memory_upsert(keep_key or key, category)
                    except Exception:
                        logger.exception("memory thought notify failed key=%s", keep_key or key)
        self._drop_unaddressed_context_conflicts(
            existing or [],
            addressed,
            upserted,
        )
