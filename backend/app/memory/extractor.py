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

"""Async DeepSeek memory extraction queue."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

import httpx

from ..config import ExtractorConfig, MemoryConfig
from ..query_time import format_extract_now, parse_content_datetimes
from ..safety import is_crisis_text, turns_contain_crisis
from ..taxonomy import normalize_memory_category
from .commitment import CommitmentStore
from .fallback import regex_extract_memories
from .normalize import normalize_memory_item
from .prompts import ALL_EXTRACT_KINDS, COMMITMENT_SYSTEM, FACT_SYSTEM, STATE_SYSTEM
from .state import StateItem, StateStore, format_state_context
from .store import MemoryStore, normalize_content_for_compare
from .validate import memory_reject_reason

EXTRACT_SYSTEM = FACT_SYSTEM

logger = logging.getLogger(__name__)

_HOT_KEYS = frozenset({"user_name", "preference_color", "user_birthday"})


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
    def __init__(
        self,
        store: MemoryStore,
        config: ExtractorConfig,
        *,
        state_store: StateStore | None = None,
        commitment_store: CommitmentStore | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.state_store = state_store
        self.commitment_store = commitment_store
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._calls_by_kind: dict[str, int] = {}
        self._calls_day = time.strftime("%Y-%m-%d")
        self.on_memory_upsert: Any = None

    @property
    def _calls_today(self) -> int:
        return sum(self._calls_by_kind.values())

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
        kinds: list[str] | None = None,
        retries: dict[str, int] | None = None,
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
        selected = [
            kind
            for kind in (kinds or list(ALL_EXTRACT_KINDS))
            if kind in ALL_EXTRACT_KINDS
        ]
        if not selected:
            return
        qsize = self._queue.qsize() + 1
        logger.info(
            "memory extract queued qsize=%d user_text=%r user_turns=%d kinds=%s",
            qsize,
            user_text,
            len(turns),
            selected,
        )
        await self._queue.put(
            {
                "transcript": transcript,
                "user_text": user_text,
                "user_turns": turns,
                "kinds": selected,
                "retries": dict(retries or {}),
            }
        )

    def _reset_daily_if_needed(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if today != self._calls_day:
            self._calls_day = today
            self._calls_by_kind = {}

    def _under_quota(self) -> bool:
        self._reset_daily_if_needed()
        return self._calls_today < self.config.max_calls_per_day

    def _note_call(self, kind: str) -> None:
        self._reset_daily_if_needed()
        self._calls_by_kind[kind] = int(self._calls_by_kind.get(kind) or 0) + 1
        logger.info(
            "extract calls_today kind=%s count=%d total=%d",
            kind,
            self._calls_by_kind[kind],
            self._calls_today,
        )

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

    def _has_api(self) -> bool:
        key = (self.config.api_key or "").strip()
        return bool(key and key != "YOUR_DEEPSEEK_API_KEY")

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
        kinds = [
            str(kind)
            for kind in (job.get("kinds") or list(ALL_EXTRACT_KINDS))
            if str(kind) in ALL_EXTRACT_KINDS
        ]
        logger.info(
            "memory extract start user_text=%r user_turns=%d transcript_chars=%d kinds=%s",
            user_text,
            len(user_turns),
            len(transcript),
            kinds,
        )
        runners = {
            "fact": self._run_fact,
            "state": self._run_state,
            "commitment": self._run_commitment,
        }
        selected = [kind for kind in kinds if kind in runners]
        results = await asyncio.gather(
            *(runners[kind](job) for kind in selected),
            return_exceptions=True,
        )
        failed: list[str] = []
        for kind, result in zip(selected, results):
            if isinstance(result, Exception):
                logger.warning("memory extract kind=%s failed: %s", kind, result)
                failed.append(kind)
        if failed:
            await self._requeue_failed(job, failed)

    async def _requeue_failed(self, job: dict[str, Any], failed: list[str]) -> None:
        retries = {
            str(key): int(value)
            for key, value in dict(job.get("retries") or {}).items()
        }
        again: list[str] = []
        limit = max(0, int(self.config.extract_retry_max))
        for kind in failed:
            used = int(retries.get(kind) or 0) + 1
            retries[kind] = used
            if used <= limit:
                again.append(kind)
            else:
                logger.info("memory extract retry exhausted kind=%s", kind)
        if not again:
            return
        await self._queue.put(
            {
                "transcript": job.get("transcript") or "",
                "user_text": job.get("user_text") or "",
                "user_turns": job.get("user_turns") or [],
                "kinds": again,
                "retries": retries,
            }
        )

    async def _run_fact(self, job: dict[str, Any]) -> None:
        transcript = str(job.get("transcript") or "")
        user_text = str(job.get("user_text") or "")
        user_turns = job.get("user_turns") or []
        if not isinstance(user_turns, list):
            user_turns = []
        existing = self._load_extract_context(user_text, user_turns)
        memories: list[dict[str, Any]] = []
        used_api = False
        api_failed = False
        if self._under_quota() and self._has_api():
            user_payload = (
                f"{format_extract_now()}\n\n"
                f"{_format_existing_memories(existing)}\n\n【对话片段】\n{transcript}"
            )
            try:
                parsed = await self._call_llm(FACT_SYSTEM, user_payload)
                self._note_call("fact")
                used_api = True
                raw_items = parsed.get("memories") or []
                if isinstance(raw_items, list):
                    memories = [item for item in raw_items if isinstance(item, dict)]
                logger.info("fact extract memories=%d", len(memories))
            except Exception as exc:
                api_failed = True
                logger.warning("fact extract failed: %s", exc)
        if not memories and self.config.fallback == "regex":
            memories = regex_extract_memories(user_text)
            logger.info("fact regex fallback memories=%d", len(memories))
        if api_failed and not memories:
            raise RuntimeError("fact extract failed")
        source = "deepseek" if used_api else "regex"
        self._apply(memories, source=source, existing=existing)

    async def _run_state(self, job: dict[str, Any]) -> None:
        store = self.state_store
        if store is None or not self.memory_config.state_enabled or not self._has_api():
            return
        if not self._under_quota():
            raise RuntimeError("state extract skipped: no api quota")
        now = datetime.now()
        context = format_state_context(
            store.all_items(),
            now,
            confirm_after_hours=float(self.memory_config.state_confirm_after_hours),
        )
        user_payload = (
            f"{format_extract_now(now)}\n\n"
            f"{context}\n\n【对话片段】\n{job.get('transcript') or ''}"
        )
        parsed = await self._call_llm(STATE_SYSTEM, user_payload)
        self._note_call("state")
        items = parsed.get("items") or []
        if not isinstance(items, list):
            return
        self._apply_state([item for item in items if isinstance(item, dict)])

    async def _run_commitment(self, job: dict[str, Any]) -> None:
        store = self.commitment_store
        if store is None or not self.memory_config.commitment_enabled or not self._has_api():
            return
        if not self._under_quota():
            raise RuntimeError("commitment extract skipped: no api quota")
        now = datetime.now()
        user_payload = (
            f"{format_extract_now(now)}\n\n"
            f"{store.format_context(now)}\n\n【对话片段】\n{job.get('transcript') or ''}"
        )
        parsed = await self._call_llm(COMMITMENT_SYSTEM, user_payload)
        self._note_call("commitment")
        items = parsed.get("items") or []
        if isinstance(items, list):
            store.apply([item for item in items if isinstance(item, dict)], now)

    def _apply_state(self, items: list[dict[str, Any]]) -> None:
        store = self.state_store
        if store is None:
            return
        now = time.time()
        for raw in items:
            op = str(raw.get("op") or "upsert").strip().lower()
            item_id = str(raw.get("id") or "").strip()
            if not item_id:
                continue
            if op == "delete":
                store.delete([item_id])
                continue
            text = str(raw.get("text") or "").strip()
            if not text or is_crisis_text(text):
                continue
            try:
                importance = int(raw.get("importance") or 5)
            except (TypeError, ValueError):
                importance = 5
            store.upsert(
                StateItem(
                    id=item_id,
                    text=text,
                    created_at=now,
                    updated_at=now,
                    importance=importance,
                    source_key=str(raw.get("source_key") or "").strip(),
                )
            )

    async def _call_llm(self, system: str, user_payload: str) -> dict[str, Any]:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_payload},
            ],
            "temperature": 0.1,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
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
        if not isinstance(parsed, dict):
            return {}
        return parsed

    async def _call_deepseek(
        self,
        transcript: str,
        existing: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        user_payload = (
            f"{format_extract_now()}\n\n"
            f"{_format_existing_memories(existing)}\n\n【对话片段】\n{transcript}"
        )
        parsed = await self._call_llm(FACT_SYSTEM, user_payload)
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

    def _write_memory(
        self,
        key: str,
        content: str,
        category: str | None,
        source: str,
        importance: int | None,
        entities: list[str] | None,
    ) -> None:
        self.store.upsert(
            key,
            content,
            category=category,
            source=source,
            importance=importance,
            entities=entities,
        )

    def _upsert_with_dedup(
        self,
        *,
        key: str,
        content: str,
        category: str | None,
        source: str,
        importance: int | None = None,
        entities: list[str] | None = None,
    ) -> str:
        cfg = self.memory_config
        cat = (category or "other").strip() or "other"

        if not cfg.dedup_enabled or cat == "goal":
            self._write_memory(key, content, category, source, importance, entities)
            self._reconcile_after_upsert(key, content, category)
            return key

        candidates = self._collect_dedup_candidates(content, category=cat, new_key=key)
        if not candidates:
            self._write_memory(key, content, category, source, importance, entities)
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
        self._write_memory(keep_key, content, category, source, importance, entities)
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
            entities = raw.get("entities") if isinstance(raw.get("entities"), list) else []
            try:
                importance = int(raw.get("importance")) if raw.get("importance") is not None else None
            except (TypeError, ValueError):
                importance = None
            item = {
                "op": op,
                "key": key,
                "content": content,
                "category": category,
                "importance": importance,
                "entities": [str(part).strip() for part in entities if str(part or "").strip()],
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
                    importance=item.get("importance"),
                    entities=item.get("entities") if isinstance(item.get("entities"), list) else None,
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
