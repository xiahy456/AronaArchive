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

"""Rank memory candidates with reciprocal rank fusion, then optional rerank."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from ..query_time import parse_content_datetimes, relative_dates_in
from ..taxonomy import normalize_memory_category

logger = logging.getLogger(__name__)

_COOL_CATEGORIES = frozenset({"episodic", "emotional"})
_RRF_K = 60


def rrf_fuse(ranked_lists: list[list[str]], k: int = _RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, key in enumerate(ranked):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _ranked_keys(mapping: dict[str, tuple[str, float]]) -> list[str]:
    ordered = sorted(mapping.items(), key=lambda item: item[1][1], reverse=True)
    return [key for key, _ in ordered]


def _best_similarity(
    key: str,
    maps: list[dict[str, tuple[str, float]]],
) -> float:
    best = 0.0
    for mapping in maps:
        found = mapping.get(key)
        if found is not None and found[1] > best:
            best = found[1]
    return best


def _content_of(
    key: str,
    maps: list[dict[str, tuple[str, float]]],
) -> str:
    for mapping in maps:
        found = mapping.get(key)
        if found is not None and found[0].strip():
            return found[0].strip()
    return ""


def _in_time_window(content: str, now: datetime, past_days: int, future_days: int) -> bool:
    events = parse_content_datetimes(content)
    if not events:
        return False
    start = now - timedelta(days=max(0, past_days))
    end = now + timedelta(days=max(0, future_days))
    return any(start <= event <= end or event.date() == now.date() for event in events)


def _query_is_temporal(query: str, now: datetime) -> bool:
    if relative_dates_in(query, now):
        return True
    markers = ("今天", "明天", "昨天", "下周", "这周", "本周", "点")
    return any(mark in (query or "") for mark in markers)


def rank_entries(
    store: Any,
    query: str,
    *,
    top_k: int,
    query_embedding: list[float] | None,
    include_time: bool,
    time_query: str | None,
    time_query_embedding: list[float] | None,
    now: datetime,
    apply_inject_cooldown: bool,
    candidate_k: int,
) -> list[dict[str, Any]]:
    maps: list[dict[str, tuple[str, float]]] = []
    lists: list[list[str]] = []

    if query_embedding is not None:
        try:
            vector_hits = store._vector_candidates(query_embedding, candidate_k)
        except Exception:
            logger.exception("Memory vector retrieve failed query=%r", query)
            vector_hits = {}
        maps.append(vector_hits)
        lists.append(_ranked_keys(vector_hits))
        fts_keys = store._fts_candidate_keys(query, candidate_k)
        try:
            fts_scored = store._score_fts_keys(fts_keys, query_embedding)
        except Exception:
            logger.exception("Memory FTS rescore failed query=%r", query)
            fts_scored = {}
        maps.append(fts_scored)
        lists.append(_ranked_keys(fts_scored) or fts_keys)

    if include_time:
        timed_map, _timed_query, _fts_n, _vec_n = store._time_aware_score_map(
            query,
            candidate_k,
            now=now,
            time_query=time_query,
            time_query_embedding=time_query_embedding,
            fallback_embedding=query_embedding or [],
        )
        maps.append(timed_map)
        lists.append(_ranked_keys(timed_map))

    entity_keys = store._entity_candidate_keys(query, candidate_k)
    if entity_keys:
        lists.append(entity_keys)

    fused = rrf_fuse([ranked for ranked in lists if ranked])
    if not fused and not maps:
        return []

    past_days = int(getattr(store.config, "time_window_past_days", 3))
    future_days = int(getattr(store.config, "time_window_future_days", 7))
    temporal = _query_is_temporal(query, now)
    attrs = store.memory_attrs(list(fused))

    scored: list[tuple[str, str, float]] = []
    for key, rrf_score in fused.items():
        content = _content_of(key, maps) or str(attrs.get(key, {}).get("content") or "")
        if not content:
            continue
        importance = int(attrs.get(key, {}).get("importance") or 5)
        weight = 1.0 + importance / 10.0
        bonus = 0.0
        if temporal and _in_time_window(content, now, past_days, future_days):
            bonus = 0.001
        similarity = _best_similarity(key, maps)
        scored.append((key, content, rrf_score * weight + similarity * 1e-4 + bonus))

    scored.sort(key=lambda item: item[2], reverse=True)
    rerank_n = int(getattr(store.config, "rerank_candidates", 30) or 30)
    head = scored[: max(top_k, rerank_n)]
    reranker = getattr(store, "reranker", None)
    if reranker is not None and head and getattr(store.config, "rerank_enabled", False):
        try:
            scores = reranker.rerank(query, [content for _, content, _ in head])
            order = sorted(
                range(len(head)),
                key=lambda index: scores[index] if index < len(scores) else 0.0,
                reverse=True,
            )
            head = [head[index] for index in order]
        except Exception:
            logger.exception("memory rerank failed; keeping fusion order")
    head = head[: max(top_k, candidate_k)]

    categories = store._categories_for_keys([key for key, _, _ in head])
    ranked = [
        (
            key,
            content,
            score,
            normalize_memory_category(categories.get(key, attrs.get(key, {}).get("category"))),
        )
        for key, content, score in head
    ]
    coolable = [
        (key, content, score)
        for key, content, score, category in ranked
        if category in _COOL_CATEGORIES
    ]
    kept_cool = {
        key
        for key, _, _ in store._drop_cooled_entries(
            coolable,
            apply_inject_cooldown=apply_inject_cooldown,
            query=query,
        )
    }
    kept: list[dict[str, Any]] = []
    for key, content, score, category in ranked:
        if category in _COOL_CATEGORIES and key not in kept_cool:
            continue
        kept.append(
            {
                "key": key,
                "content": content,
                "category": category,
                "score": float(score),
            }
        )
        if len(kept) >= top_k:
            break
    logger.info(
        "memory retrieve query=%r fused=%d hits=%d items=%s",
        query,
        len(fused),
        len(kept),
        [item["content"] for item in kept],
    )
    return kept
