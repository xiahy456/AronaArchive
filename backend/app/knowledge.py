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

"""Chroma + local BGE vector knowledge retriever."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import jieba

from .config import AppConfig, KnowledgeConfig
from .embeddings import LocalBgeEncoder, bge_missing_reason, cosine_similarity
from .query_time import (
    build_time_aware_query,
    cache_day_key,
    mentions_query_clock,
)

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_PUNCT_RE = re.compile(r"^[\W_]+$", re.UNICODE)
_CLAUSE_RE = re.compile(r"[，。；;？?！!\n]+")

# Token groups used only to count lexical overlap (not an intent gate).
_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"衣服", "穿", "服装", "上衣", "裙子", "发带", "伞"}),
    frozenset({"职责", "负责", "工作"}),
    frozenset({"谁", "身份"}),
)
_PHRASE_ALIASES: tuple[tuple[str, frozenset[str]], ...] = (
    ("做什么", frozenset({"职责", "负责", "工作"})),
    ("干什么", frozenset({"职责", "负责", "工作"})),
    ("是谁", frozenset({"身份", "谁"})),
    ("穿什么", frozenset({"服装", "衣服", "穿"})),
)

# Function words plus default persona names that collapse all lore chunks.
_LEXICAL_STOPWORDS = frozenset(
    {
        "的",
        "了",
        "是",
        "在",
        "有",
        "和",
        "与",
        "或",
        "也",
        "都",
        "就",
        "而",
        "及",
        "等",
        "被",
        "把",
        "让",
        "给",
        "对",
        "从",
        "向",
        "到",
        "为",
        "以",
        "于",
        "着",
        "过",
        "很",
        "更",
        "最",
        "还",
        "又",
        "再",
        "才",
        "已",
        "已经",
        "会",
        "能",
        "可以",
        "要",
        "想",
        "我",
        "你",
        "他",
        "她",
        "它",
        "我们",
        "你们",
        "他们",
        "这",
        "那",
        "这个",
        "那个",
        "什么",
        "哪",
        "哪个",
        "怎么",
        "怎样",
        "如何",
        "吗",
        "呢",
        "啊",
        "吧",
        "呀",
        "哦",
        "嗯",
        "嘛",
        "哈",
        "啦",
        "哟",
        "不",
        "没",
        "没有",
        "不是",
        "一个",
        "一些",
        "一下",
        "一样",
        "阿洛娜",
        "阿罗娜",
        "arona",
        "アロナ",
        "老师",
        "您",
    }
)


@dataclass
class KnowledgeChunk:
    id: str
    title: str
    body: str
    source: str

    @property
    def embed_text(self) -> str:
        return f"【{self.title}】\n{self.body}"


def _slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^\w\u4e00-\u9fff\-]+", "", text, flags=re.UNICODE)
    return text or "chunk"


def parse_markdown_file(path: Path) -> list[KnowledgeChunk]:
    raw = path.read_text(encoding="utf-8")
    matches = list(_HEADING_RE.finditer(raw))
    if not matches:
        return []

    file_slug = _slug(path.stem)
    chunks: list[KnowledgeChunk] = []
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        body = raw[start:end].strip()
        body = re.sub(r"^#\s+.*$", "", body, flags=re.MULTILINE).strip()
        if not title or not body:
            continue
        chunk_id = f"{file_slug}__{_slug(title)}"
        chunks.append(
            KnowledgeChunk(
                id=chunk_id,
                title=title,
                body=body,
                source=path.name,
            )
        )
    return chunks


def load_corpus(corpus_dir: Path) -> list[KnowledgeChunk]:
    if not corpus_dir.is_dir():
        raise FileNotFoundError(f"Knowledge corpus directory not found: {corpus_dir}")
    chunks: list[KnowledgeChunk] = []
    for path in sorted(corpus_dir.glob("*.md")):
        chunks.extend(parse_markdown_file(path))
    return chunks


def _lexical_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in jieba.cut_for_search(text or ""):
        token = raw.strip()
        if not token:
            continue
        lowered = token.lower()
        if lowered in _LEXICAL_STOPWORDS or token in _LEXICAL_STOPWORDS:
            continue
        if _PUNCT_RE.match(token):
            continue
        tokens.add(lowered)
    return tokens


def _expand_overlap_tokens(text: str) -> set[str]:
    tokens = _lexical_tokens(text)
    expanded = set(tokens)
    for group in _ALIAS_GROUPS:
        if expanded & group:
            expanded |= group
    blob = text or ""
    for phrase, extras in _PHRASE_ALIASES:
        if phrase in blob:
            expanded |= extras
    return expanded


def lexical_overlap(query: str, chunk_text: str) -> int:
    """Count alias-aware token overlap between a query and a chunk."""
    return len(_expand_overlap_tokens(query) & _expand_overlap_tokens(chunk_text))


def split_retrieve_clauses(query: str) -> list[str]:
    """Split on clause punctuation; drop pieces with no lexical tokens."""
    text = (query or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _CLAUSE_RE.split(text) if p.strip()]
    if len(parts) <= 1:
        return [text]
    kept = [p for p in parts if _lexical_tokens(p)]
    return kept if kept else [text]


@dataclass
class ScoredKnowledgeHit:
    similarity: float
    title: str
    text: str
    overlap: int


def filter_knowledge_hits(
    hits: list[ScoredKnowledgeHit],
    *,
    min_score: float,
    score_margin: float,
    top_k: int,
    min_score_no_overlap: float = 0.62,
) -> list[ScoredKnowledgeHit]:
    """Keep precise neighbors: score floors, gap to best hit, then lexical extras."""
    passed: list[ScoredKnowledgeHit] = []
    no_ov_floor = float(min_score_no_overlap)
    abs_floor = float(min_score)
    for hit in hits:
        if hit.overlap <= 0:
            if hit.similarity >= no_ov_floor:
                passed.append(hit)
        elif hit.similarity >= abs_floor:
            passed.append(hit)
    if not passed:
        return []
    passed.sort(key=lambda h: (-h.similarity, -h.overlap, h.title))
    top_score = passed[0].similarity
    margin = max(0.0, float(score_margin))
    passed = [h for h in passed if h.similarity >= top_score - margin]
    if len(passed) > 1:
        kept = [passed[0]]
        for hit in passed[1:]:
            if hit.overlap > 0:
                kept.append(hit)
        passed = kept
    k = max(1, int(top_k))
    return passed[:k]


@dataclass
class _QueryCacheEntry:
    embedding: list[float]
    hits: list[str]
    top_k: int
    collection_n: int
    cache_day: str


class SemanticHitCache:
    """In-process nearest-neighbor cache of filtered knowledge hit texts."""

    def __init__(self, *, size: int, min_cosine: float) -> None:
        self.size = max(1, int(size))
        self.min_cosine = float(min_cosine)
        self._entries: list[_QueryCacheEntry] = []
        self._lock = threading.Lock()

    def get(
        self,
        embedding: list[float],
        *,
        top_k: int,
        collection_n: int,
        cache_day: str = "",
    ) -> tuple[list[str], float] | None:
        with self._lock:
            best: _QueryCacheEntry | None = None
            best_cos = -1.0
            for entry in self._entries:
                if (
                    entry.top_k != top_k
                    or entry.collection_n != collection_n
                    or entry.cache_day != cache_day
                ):
                    continue
                cos = cosine_similarity(embedding, entry.embedding)
                if cos >= self.min_cosine and cos > best_cos:
                    best = entry
                    best_cos = cos
            if best is None:
                return None
            self._entries.remove(best)
            self._entries.append(best)
            return list(best.hits), best_cos

    def put(
        self,
        embedding: list[float],
        hits: list[str],
        *,
        top_k: int,
        collection_n: int,
        cache_day: str = "",
    ) -> None:
        with self._lock:
            self._entries.append(
                _QueryCacheEntry(
                    embedding=list(embedding),
                    hits=list(hits),
                    top_k=int(top_k),
                    collection_n=int(collection_n),
                    cache_day=str(cache_day),
                )
            )
            overflow = len(self._entries) - self.size
            if overflow > 0:
                del self._entries[:overflow]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


class KnowledgeRetriever:
    def __init__(
        self,
        app_config: AppConfig,
        encoder: LocalBgeEncoder | None = None,
    ) -> None:
        self.app_config = app_config
        self.config: KnowledgeConfig = app_config.knowledge
        self.enabled = bool(self.config.enabled)
        self.corpus_dir = app_config.knowledge_corpus_abs_path
        self.chroma_path = app_config.knowledge_chroma_abs_path
        self.embedding_path = app_config.knowledge_embedding_abs_path
        self._collection: Any | None = None
        self._encoder: LocalBgeEncoder | None = encoder
        self._client: Any | None = None
        self._query_cache = SemanticHitCache(
            size=int(self.config.query_cache_size),
            min_cosine=float(self.config.query_cache_min_cosine),
        )

    def _ensure_encoder(self) -> LocalBgeEncoder:
        if self._encoder is None:
            missing = bge_missing_reason(self.embedding_path)
            if missing is not None:
                raise FileNotFoundError(missing)
            self._encoder = LocalBgeEncoder(self.embedding_path)
        return self._encoder

    def _ensure_backend(self) -> None:
        if self._collection is not None and self._encoder is not None:
            return

        import chromadb
        from chromadb.config import Settings

        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self._ensure_encoder()
        self._client = chromadb.PersistentClient(
            path=str(self.chroma_path),
            settings=Settings(anonymized_telemetry=False),
        )
        # No embedding_function: we pass embeddings explicitly (query vs doc differ for BGE).
        self._collection = self._client.get_or_create_collection(
            name=self.config.collection,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "Knowledge Chroma ready collection=%s path=%s",
            self.config.collection,
            self.chroma_path,
        )

    def warmup(self) -> None:
        """Eagerly load BGE + Chroma so first RAG retrieve is not cold."""
        if not self.enabled:
            return
        jieba.initialize()
        self._ensure_backend()

    def _chroma_query(
        self,
        embedding: list[float],
        n_results: int,
    ) -> dict[str, Any]:
        assert self._collection is not None
        return self._collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

    @staticmethod
    def _hits_from_chroma(
        result: dict[str, Any],
        query_for_overlap: str,
    ) -> list[ScoredKnowledgeHit]:
        documents = (result.get("documents") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        raw_hits: list[ScoredKnowledgeHit] = []
        for doc, dist, meta in zip(documents, distances, metadatas):
            similarity = 1.0 - float(dist)
            meta_dict = meta if isinstance(meta, dict) else {}
            title = str(meta_dict.get("title") or "").strip()
            display_body = str(meta_dict.get("body") or "").strip()
            if display_body:
                text = f"{title}：{display_body}" if title else display_body
            else:
                text = (doc or "").strip()
            if not text:
                continue
            overlap = lexical_overlap(query_for_overlap, f"{title}\n{display_body or text}")
            raw_hits.append(
                ScoredKnowledgeHit(
                    similarity=similarity,
                    title=title or text[:40],
                    text=text,
                    overlap=overlap,
                )
            )
        return raw_hits

    @staticmethod
    def _merge_hits_by_title(
        groups: list[list[ScoredKnowledgeHit]],
        query_for_overlap: str,
    ) -> list[ScoredKnowledgeHit]:
        merged: dict[str, ScoredKnowledgeHit] = {}
        for group in groups:
            for hit in group:
                prev = merged.get(hit.title)
                if prev is None or hit.similarity > prev.similarity:
                    merged[hit.title] = hit
        out: list[ScoredKnowledgeHit] = []
        for hit in merged.values():
            overlap = lexical_overlap(
                query_for_overlap,
                f"{hit.title}\n{hit.text}",
            )
            out.append(
                ScoredKnowledgeHit(
                    similarity=hit.similarity,
                    title=hit.title,
                    text=hit.text,
                    overlap=overlap,
                )
            )
        out.sort(key=lambda h: (-h.similarity, -h.overlap, h.title))
        return out

    @staticmethod
    def _keep_best_by_title(
        groups: list[list[ScoredKnowledgeHit]],
    ) -> list[ScoredKnowledgeHit]:
        merged: dict[str, ScoredKnowledgeHit] = {}
        for group in groups:
            for hit in group:
                prev = merged.get(hit.title)
                if prev is None or hit.similarity > prev.similarity:
                    merged[hit.title] = hit
        out = list(merged.values())
        out.sort(key=lambda h: (-h.similarity, -h.overlap, h.title))
        return out

    def _retrieve_filtered_hits(
        self,
        query: str,
        q_emb: list[float],
        *,
        k: int,
        n_results: int,
        split_clauses: bool,
    ) -> tuple[list[ScoredKnowledgeHit], int, int]:
        """Return filtered hits, clause count, and candidate count for one query."""
        assert self._encoder is not None
        if split_clauses:
            clauses = split_retrieve_clauses(query)
        else:
            clauses = [query]
        clause_n = len(clauses)
        if len(clauses) <= 1:
            result = self._chroma_query(q_emb, n_results)
            raw_hits = self._hits_from_chroma(result, query)
            candidate_n = len((result.get("documents") or [[]])[0])
            filtered = filter_knowledge_hits(
                raw_hits,
                min_score=float(self.config.min_score),
                score_margin=float(self.config.score_margin),
                top_k=k,
                min_score_no_overlap=float(self.config.min_score_no_overlap),
            )
            return filtered, clause_n, candidate_n

        clause_embs = self._encoder.encode_queries(clauses)
        groups: list[list[ScoredKnowledgeHit]] = []
        candidate_n = 0
        abs_floor = float(self.config.min_score)
        no_ov_floor = float(self.config.min_score_no_overlap)
        margin = float(self.config.score_margin)
        for clause, emb in zip(clauses, clause_embs):
            result = self._chroma_query(emb, n_results)
            candidate_n += len((result.get("documents") or [[]])[0])
            clause_raw = self._hits_from_chroma(result, clause)
            clause_kept = filter_knowledge_hits(
                clause_raw,
                min_score=abs_floor,
                score_margin=margin,
                top_k=k,
                min_score_no_overlap=no_ov_floor,
            )
            if not clause_kept:
                ranked = sorted(
                    clause_raw,
                    key=lambda h: (-h.similarity, -h.overlap, h.title),
                )
                for hit in ranked:
                    if hit.overlap > 0 and hit.similarity >= abs_floor - 0.05:
                        clause_kept = [hit]
                        break
            if clause_kept:
                groups.append(clause_kept)
        raw_hits = self._merge_hits_by_title(groups, query) if groups else []
        filtered = filter_knowledge_hits(
            raw_hits,
            min_score=0.0,
            score_margin=1.0,
            top_k=k,
            min_score_no_overlap=no_ov_floor,
        )
        return filtered, clause_n, candidate_n

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        query_embedding: list[float] | None = None,
        *,
        include_time: bool = True,
        time_query: str | None = None,
        time_query_embedding: list[float] | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        if not self.enabled:
            return []
        query = (query or "").strip()
        if not query:
            return []

        k = top_k if top_k is not None else self.config.retrieve_top_k
        k = max(1, int(k))
        candidate_k = max(k, int(self.config.candidate_top_k))
        clock = now or datetime.now()
        day_key = cache_day_key(clock)

        try:
            self._ensure_backend()
        except FileNotFoundError as exc:
            logger.warning("%s", exc)
            return []
        except Exception:
            logger.exception("Knowledge backend init failed")
            return []

        assert self._collection is not None and self._encoder is not None
        try:
            count = int(self._collection.count())
        except Exception:
            logger.exception("Knowledge collection count failed")
            return []
        if count <= 0:
            logger.info("knowledge retrieve query=%r skipped empty chroma", query)
            return []
        n_results = min(candidate_k, count)

        try:
            q_emb = (
                query_embedding
                if query_embedding is not None
                else self._encoder.encode_query(query)
            )
            cache_on = bool(self.config.query_cache_enabled)
            if cache_on:
                cached = self._query_cache.get(
                    q_emb, top_k=k, collection_n=count, cache_day=day_key
                )
                if cached is not None:
                    hits, cosine = cached
                    logger.info(
                        "knowledge retrieve cache=hit cosine=%.3f query=%r hits=%d day=%s",
                        cosine,
                        query,
                        len(hits),
                        day_key,
                    )
                    return hits

            orig_hits, clause_n, candidate_n = self._retrieve_filtered_hits(
                query,
                q_emb,
                k=k,
                n_results=n_results,
                split_clauses=True,
            )
            timed_query = ""
            if include_time:
                timed_query = (time_query or "").strip() or build_time_aware_query(
                    query, clock
                )
                timed_emb = time_query_embedding
                if timed_emb is None:
                    timed_emb = self._encoder.encode_query(timed_query)
                timed_hits, _, timed_cand = self._retrieve_filtered_hits(
                    timed_query,
                    timed_emb,
                    k=k,
                    n_results=n_results,
                    split_clauses=False,
                )
                timed_hits = [
                    hit
                    for hit in timed_hits
                    if mentions_query_clock(
                        f"{hit.title}\n{hit.text}", clock, query
                    )
                ]
                candidate_n += timed_cand
                filtered = self._keep_best_by_title([orig_hits, timed_hits])[:k]
            else:
                filtered = orig_hits
        except Exception:
            logger.exception("Knowledge retrieve failed for query=%r", query)
            return []

        hits = [h.text for h in filtered]
        logger.info(
            "knowledge retrieve cache=miss query=%r time_query=%r clauses=%d "
            "candidates=%d hits=%d min_score=%.3f min_score_no_overlap=%.3f "
            "score_margin=%.3f scores=%s",
            query,
            timed_query or None,
            clause_n,
            candidate_n,
            len(filtered),
            self.config.min_score,
            self.config.min_score_no_overlap,
            self.config.score_margin,
            [(round(h.similarity, 3), h.title, h.overlap) for h in filtered],
        )
        if bool(self.config.query_cache_enabled):
            self._query_cache.put(
                q_emb, hits, top_k=k, collection_n=count, cache_day=day_key
            )
        return hits

    def ingest(self, *, rebuild: bool = False) -> int:
        """Load Markdown corpus into Chroma. Returns number of upserted chunks."""
        chunks = load_corpus(self.corpus_dir)
        if not chunks:
            logger.warning("No knowledge chunks found under %s", self.corpus_dir)
            return 0

        import chromadb
        from chromadb.config import Settings

        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self._ensure_encoder()
        self._client = chromadb.PersistentClient(
            path=str(self.chroma_path),
            settings=Settings(anonymized_telemetry=False),
        )

        if rebuild:
            try:
                self._client.delete_collection(self.config.collection)
                logger.info("Deleted Chroma collection %s", self.config.collection)
            except Exception:
                pass
            self._collection = None
            self._query_cache.clear()

        self._collection = self._client.get_or_create_collection(
            name=self.config.collection,
            metadata={"hnsw:space": "cosine"},
        )

        ids = [c.id for c in chunks]
        documents = [c.embed_text for c in chunks]
        metadatas = [
            {"title": c.title, "body": c.body, "source": c.source}
            for c in chunks
        ]
        embeddings = self._encoder.encode_documents(documents)
        self._collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        self._query_cache.clear()
        logger.info(
            "Ingested %d knowledge chunks into %s",
            len(chunks),
            self.config.collection,
        )
        return len(chunks)


def ingest_corpus(app_config: AppConfig, *, rebuild: bool = False) -> int:
    """Module-level helper for scripts (works even if knowledge.enabled is false)."""
    retriever = KnowledgeRetriever(app_config)
    return retriever.ingest(rebuild=rebuild)
