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

"""Event retrieval: RRF over FTS5, optional vectors, optional rerank."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.query_time import expand_relative_time, format_date, relative_dates_in

from .events import Event, EventLog
from .rerank import maybe_rerank
from .trace import TraceLog
from .util import approx_chars_for_tokens, fts_match

logger = logging.getLogger(__name__)

_RRF_K = 60
_COLLECTION = "arona_memory"


def _rrf(rankings: list[list[str]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked in rankings:
        for index, event_id in enumerate(ranked):
            scores[event_id] = scores.get(event_id, 0.0) + 1.0 / (_RRF_K + index + 1)
    return scores


class EventRetriever:
    def __init__(
        self,
        events: EventLog,
        trace: TraceLog,
        *,
        inject_top_k: int = 3,
        vector_enabled: bool = False,
        chroma_path: Path | None = None,
        rerank_enabled: bool = False,
        rerank_candidates: int = 12,
        rerank_model_path: Path | None = None,
        encoder: Any = None,
        token_budget_memory: int = 250,
    ) -> None:
        self.events = events
        self.trace = trace
        self.inject_top_k = max(1, int(inject_top_k))
        self.vector_enabled = bool(vector_enabled)
        self.chroma_path = Path(chroma_path) if chroma_path is not None else None
        self.rerank_enabled = bool(rerank_enabled)
        self.rerank_candidates = max(1, int(rerank_candidates))
        self.rerank_model_path = rerank_model_path or Path("../models/bge-reranker-base")
        self.encoder = encoder
        self.token_budget_memory = int(token_budget_memory)
        self._reranker = None
        self._collection = None
        self._vector_failed = False

    def add_vector(self, event_id: str, summary: str) -> None:
        if not self.vector_enabled or self.encoder is None:
            return
        collection = self._chroma()
        if collection is None:
            return
        try:
            vector = self.encoder.encode_documents([summary])[0]
            collection.upsert(ids=[event_id], documents=[summary], embeddings=[vector])
        except Exception:
            logger.exception("memory_v2 vector upsert failed id=%s", event_id)
            self._vector_failed = True

    def search(self, query: str, *, k: int | None = None, now: datetime | None = None) -> list[Event]:
        started = datetime.now()
        limit = self.inject_top_k if k is None else max(1, int(k))
        moment = now or datetime.now()
        rankings: list[list[str]] = []
        degraded = not self.vector_enabled or self.encoder is None or self._vector_failed

        lexical = fts_match(query)
        if lexical:
            rankings.append(self.events.search_ids(lexical, limit=max(limit * 4, 12)))
        for extra in self._time_queries(query, moment):
            match = fts_match(extra)
            if match:
                rankings.append(self.events.search_ids(match, limit=max(limit * 4, 12)))

        if self.vector_enabled:
            vector_ids = self._vector_ids(query, max(limit * 4, 12))
            if vector_ids is None:
                degraded = True
            else:
                rankings.append(vector_ids)
                degraded = False

        fused = _rrf(rankings)
        if not fused:
            self._trace(query, [], [], degraded, started)
            return []

        ordered_ids = sorted(fused, key=lambda event_id: fused[event_id], reverse=True)
        loaded = self.events.get_many(ordered_ids)
        weighted: list[tuple[float, Event]] = []
        for event_id in ordered_ids:
            event = loaded.get(event_id)
            if event is None:
                continue
            weight = 1.0 + (event.importance / 10.0)
            weighted.append((fused[event_id] * weight, event))
        weighted.sort(key=lambda item: item[0], reverse=True)

        pool = weighted[: self.rerank_candidates if self.rerank_enabled else len(weighted)]
        texts = [item[1].summary for item in pool]
        indexes, self._reranker = maybe_rerank(
            enabled=self.rerank_enabled,
            model_path=self.rerank_model_path,
            query=query,
            texts=texts,
            reranker=self._reranker,
        )
        ranked_events = [pool[index][1] for index in indexes if index < len(pool)]
        chosen = self._fit_budget(_dedupe(ranked_events), limit)
        self._trace(
            query,
            [{"id": event.id, "score": round(fused.get(event.id, 0.0), 4)} for event in ranked_events[:12]],
            [event.id for event in chosen],
            degraded,
            started,
        )
        return chosen

    def _fit_budget(self, events: list[Event], limit: int) -> list[Event]:
        budget = approx_chars_for_tokens(self.token_budget_memory)
        chosen: list[Event] = []
        used = len("【相关回忆】\n")
        for event in events:
            if len(chosen) >= limit:
                break
            line = f"- {event.summary}"
            extra = len(line) + (1 if chosen else 0)
            if chosen and used + extra > budget:
                break
            chosen.append(event)
            used += extra
        return chosen

    def _time_queries(self, query: str, now: datetime) -> list[str]:
        expanded = expand_relative_time(query or "", now)
        queries: list[str] = []
        if expanded and expanded != (query or "").strip():
            queries.append(expanded)
        for day in relative_dates_in(query or "", now):
            stamp = format_date(day)
            if stamp not in queries:
                queries.append(stamp)
        return queries

    def _vector_ids(self, query: str, limit: int) -> list[str] | None:
        collection = self._chroma()
        if collection is None or self.encoder is None:
            return None
        try:
            vector = self.encoder.encode_queries([query])[0]
            found = collection.query(query_embeddings=[vector], n_results=limit)
        except Exception:
            logger.exception("memory_v2 vector query failed")
            self._vector_failed = True
            return None
        ids = (found.get("ids") or [[]])[0]
        return [str(item) for item in ids]

    def _chroma(self) -> Any:
        if not self.vector_enabled or self.chroma_path is None:
            return None
        if self._collection is not None:
            return self._collection
        if self._vector_failed:
            return None
        try:
            import chromadb
            from chromadb.config import Settings

            self.chroma_path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(
                path=str(self.chroma_path),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(
                name=_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            logger.exception("memory_v2 chroma unavailable; FTS only")
            self._vector_failed = True
            return None
        return self._collection

    def _trace(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        injected: list[str],
        degraded: bool,
        started: datetime,
    ) -> None:
        latency_ms = int((datetime.now() - started).total_seconds() * 1000)
        self.trace.write(
            {
                "kind": "retrieve",
                "query": query,
                "candidates": candidates,
                "injected": injected,
                "degraded": bool(degraded),
                "latency_ms": latency_ms,
            }
        )


def _dedupe(events: list[Event]) -> list[Event]:
    seen: set[str] = set()
    out: list[Event] = []
    for event in events:
        key = event.summary.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(event)
    return out
