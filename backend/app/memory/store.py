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

"""SQLite + FTS5 + Chroma hybrid long-term memory store."""

from __future__ import annotations

import logging
import math
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import jieba

from ..config import AppConfig, MemoryConfig
from ..embeddings import LocalBgeEncoder, bge_missing_reason
from ..query_time import (
    build_time_aware_query,
    memory_time_fts_queries,
    relative_dates_in,
    relative_months_in,
)

logger = logging.getLogger(__name__)

# Function words / particles that caused false OR hits (e.g. 是 / 的).
_STOPWORDS = frozenset(
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
        "老师",
        "您",
        "阿洛娜",
        "阿罗娜",
        "arona",
        "アロナ",
    }
)

_PUNCT_RE = re.compile(r"^[\W_]+$", re.UNICODE)


def _raw_tokens(text: str) -> list[str]:
    return [t.strip() for t in jieba.cut_for_search(text or "") if t.strip()]


def _is_stop_or_punct(token: str) -> bool:
    if not token:
        return True
    if token in _STOPWORDS:
        return True
    if _PUNCT_RE.match(token):
        return True
    return False


def _tokenize(text: str) -> str:
    """Jieba tokenize then drop stopwords/punctuation for FTS indexing/query."""
    tokens = [t for t in _raw_tokens(text) if not _is_stop_or_punct(t)]
    return " ".join(tokens)


def _overlap_token_set(text: str) -> set[str]:
    return {t.lower() for t in _raw_tokens(text) if not _is_stop_or_punct(t)}


def lexical_overlap(query: str, content: str) -> int:
    """Count jieba token overlap; persona names are stopwords."""
    if not (query or "").strip() or not (content or "").strip():
        return 0
    return len(_overlap_token_set(query) & _overlap_token_set(content))


def _preview_scored(items: list[tuple[str, str, float]]) -> list[tuple[float, str]]:
    return [(round(score, 3), content[:40]) for _, content, score in items]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def normalize_content_for_compare(text: str) -> str:
    """Normalize text for exact/batch dedup keys without changing stored content."""
    s = (text or "").strip()
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[。．.！!？?]+$", "", s)
    return s.strip()


class MemoryStore:
    def __init__(
        self,
        app_config: AppConfig,
        encoder: LocalBgeEncoder | None = None,
        *,
        db_path: Path | None = None,
    ) -> None:
        self.app_config = app_config
        self.config: MemoryConfig = app_config.memory
        self.db_path = Path(db_path) if db_path is not None else app_config.memory_db_abs_path
        self.chroma_path = app_config.memory_chroma_abs_path
        self.embedding_path = app_config.knowledge_embedding_abs_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._encoder = encoder
        self._collection: Any | None = None
        self._client: Any | None = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    key TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    category TEXT,
                    updated_at REAL NOT NULL,
                    source TEXT,
                    last_injected_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(key, content, tokenize='unicode61')
                """
            )
            cols = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(memories)").fetchall()
            }
            if "last_injected_at" not in cols:
                conn.execute(
                    "ALTER TABLE memories ADD COLUMN last_injected_at REAL"
                )
            conn.commit()

    def _ensure_encoder(self) -> LocalBgeEncoder:
        if self._encoder is None:
            missing = bge_missing_reason(self.embedding_path)
            if missing is not None:
                raise FileNotFoundError(missing)
            self._encoder = LocalBgeEncoder(self.embedding_path)
        return self._encoder

    def _ensure_chroma(self) -> Any:
        if self._collection is not None:
            return self._collection

        import chromadb
        from chromadb.config import Settings

        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self._ensure_encoder()
        self._client = chromadb.PersistentClient(
            path=str(self.chroma_path),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=self.config.collection,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "Memory Chroma ready collection=%s path=%s",
            self.config.collection,
            self.chroma_path,
        )
        return self._collection

    def warmup(self) -> None:
        """Eagerly build jieba + BGE + Chroma so first retrieve is not cold."""
        logger.info("Warming up jieba dictionary")
        jieba.initialize()
        _tokenize("预热")
        logger.info("jieba dictionary ready")
        try:
            self._ensure_chroma()
        except FileNotFoundError as exc:
            logger.warning("%s", exc)
        except Exception:
            logger.exception("Memory Chroma warmup failed; will retry on first use")

    def encode_query(self, text: str) -> list[float]:
        return self._ensure_encoder().encode_query(text)

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        return self._ensure_encoder().encode_queries(texts)

    def upsert(
        self,
        key: str,
        content: str,
        category: str | None = None,
        source: str = "extractor",
    ) -> None:
        key = (key or "").strip()
        content = (content or "").strip()
        if not key or not content:
            return
        if len(content) > 200:
            content = content[:200]

        now = time.time()
        fts_body = _tokenize(f"{key} {content}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memories(key, content, category, updated_at, source)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    content=excluded.content,
                    category=excluded.category,
                    updated_at=excluded.updated_at,
                    source=excluded.source
                """,
                (key, content, category, now, source),
            )
            conn.execute("DELETE FROM memories_fts WHERE key = ?", (key,))
            conn.execute(
                "INSERT INTO memories_fts(key, content) VALUES (?, ?)",
                (key, fts_body),
            )
            conn.commit()
        logger.info("Memory upsert key=%s content=%s", key, content)
        self._chroma_upsert(key, content, category=category, source=source)

    def _chroma_upsert(
        self,
        key: str,
        content: str,
        *,
        category: str | None,
        source: str,
    ) -> None:
        try:
            collection = self._ensure_chroma()
            encoder = self._ensure_encoder()
            embedding = encoder.encode_documents([content])[0]
            collection.upsert(
                ids=[key],
                documents=[content],
                metadatas=[
                    {
                        "category": category or "",
                        "source": source or "",
                    }
                ],
                embeddings=[embedding],
            )
        except Exception:
            logger.exception("Memory Chroma upsert failed key=%s", key)

    def delete(self, key: str) -> None:
        key = (key or "").strip()
        if not key:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM memories WHERE key = ?", (key,))
            conn.execute("DELETE FROM memories_fts WHERE key = ?", (key,))
            conn.commit()
        logger.info("Memory delete key=%s", key)
        self._chroma_delete(key)

    def _chroma_delete(self, key: str) -> None:
        try:
            collection = self._ensure_chroma()
            collection.delete(ids=[key])
        except Exception:
            logger.exception("Memory Chroma delete failed key=%s", key)

    def mark_injected(
        self,
        keys: list[str],
        now: float | None = None,
    ) -> None:
        cleaned = [str(k).strip() for k in keys if str(k or "").strip()]
        if not cleaned:
            return
        ts = time.time() if now is None else float(now)
        placeholders = ",".join("?" for _ in cleaned)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE memories SET last_injected_at = ? WHERE key IN ({placeholders})",
                [ts, *cleaned],
            )
            conn.commit()
        logger.info("memory inject marked keys=%s ts=%.3f", cleaned, ts)

    def _cooled_keys(
        self,
        keys: list[str],
        now: float,
        cooldown_sec: float,
    ) -> set[str]:
        cleaned = [str(k).strip() for k in keys if str(k or "").strip()]
        if not cleaned or cooldown_sec <= 0:
            return set()
        cutoff = float(now) - float(cooldown_sec)
        placeholders = ",".join("?" for _ in cleaned)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT key FROM memories
                WHERE key IN ({placeholders})
                  AND last_injected_at IS NOT NULL
                  AND last_injected_at > ?
                """,
                [*cleaned, cutoff],
            ).fetchall()
        return {str(row["key"]) for row in rows}

    def _cooldown_bypass_reason(
        self,
        content: str,
        score: float,
        query: str,
    ) -> str | None:
        bypass = float(self.config.inject_cooldown_bypass_score)
        if score >= bypass:
            return "score"
        if query and lexical_overlap(query, content) > 0:
            return "overlap"
        return None

    def _filter_by_score(
        self,
        ranked: list[tuple[str, tuple[str, float]]],
        query: str,
    ) -> list[tuple[str, str, float]]:
        min_score = float(self.config.min_score)
        no_ov = float(self.config.min_score_no_overlap)
        passed: list[tuple[str, str, float]] = []
        for key, (content, score) in ranked:
            if not content:
                continue
            overlap = lexical_overlap(query, content)
            floor = min_score if overlap > 0 else no_ov
            if score >= floor:
                passed.append((key, content, score))
        return passed

    def _drop_cooled_entries(
        self,
        passed: list[tuple[str, str, float]],
        *,
        apply_inject_cooldown: bool,
        query: str = "",
    ) -> list[tuple[str, str, float]]:
        if not apply_inject_cooldown or not passed:
            return passed
        cooldown = float(self.config.inject_cooldown_sec)
        if cooldown <= 0:
            return passed
        cooled = self._cooled_keys(
            [key for key, _, _ in passed],
            time.time(),
            cooldown,
        )
        if not cooled:
            return passed
        remaining: list[tuple[str, str, float]] = []
        skipped: list[str] = []
        bypassed: list[tuple[str, str]] = []
        for key, content, score in passed:
            if key not in cooled:
                remaining.append((key, content, score))
                continue
            reason = self._cooldown_bypass_reason(content, score, query)
            if reason:
                remaining.append((key, content, score))
                bypassed.append((key, reason))
            else:
                skipped.append(key)
        if skipped or bypassed:
            logger.info(
                "memory retrieve cooldown skipped keys=%s remaining=%d "
                "cooldown_sec=%.0f bypass=%s",
                sorted(skipped),
                len(remaining),
                cooldown,
                bypassed,
            )
        return remaining

    def _fts_only_entries(
        self,
        query: str,
        top_k: int,
        *,
        apply_inject_cooldown: bool,
        apply_score_filter: bool = True,
    ) -> list[dict[str, Any]]:
        """SQLite FTS retrieve used when BGE / Chroma is unavailable."""
        candidate_k = max(top_k, int(self.config.candidate_top_k))
        keys = self._fts_candidate_keys(query, candidate_k)
        if not keys:
            logger.info("memory retrieve query=%r fts-only hits=0", query)
            return []
        with self._connect() as conn:
            placeholders = ",".join("?" * len(keys))
            rows = conn.execute(
                f"SELECT key, content, category FROM memories WHERE key IN ({placeholders})",
                keys,
            ).fetchall()
        by_key = {str(row["key"]): row for row in rows}
        passed: list[tuple[str, str, float]] = []
        for index, key in enumerate(keys):
            row = by_key.get(key)
            if row is None:
                continue
            content = str(row["content"] or "").strip()
            if not content:
                continue
            passed.append((key, content, 1.0 - index * 0.01))
        ranked = [(key, (content, score)) for key, content, score in passed]
        if apply_score_filter:
            passed = self._filter_by_score(ranked, query)
        else:
            passed = [
                (key, content, score)
                for key, (content, score) in ranked
                if content
            ]
        pre_scores = _preview_scored(passed)
        passed = self._drop_cooled_entries(
            passed,
            apply_inject_cooldown=apply_inject_cooldown,
            query=query,
        )[:top_k]
        categories = self._categories_for_keys([key for key, _, _ in passed])
        entries = [
            {
                "key": key,
                "content": content,
                "category": categories.get(key),
                "score": float(score),
            }
            for key, content, score in passed
        ]
        logger.info(
            "memory retrieve query=%r fts-only hits=%d pre_scores=%s items=%s",
            query,
            len(entries),
            pre_scores,
            [e["content"] for e in entries],
        )
        return entries

    @staticmethod
    def _fts_quote(token: str) -> str:
        cleaned = token.replace('"', " ").strip()
        if not cleaned:
            return ""
        return f'"{cleaned}"'

    def _fts_candidate_keys(self, query: str, limit: int) -> list[str]:
        tokens = [self._fts_quote(t) for t in _tokenize(query).split() if t]
        tokens = [t for t in tokens if t]
        if not tokens:
            return []

        and_q = " ".join(tokens)
        or_q = " OR ".join(tokens)

        with self._connect() as conn:
            rows = self._fts_search(conn, and_q, limit)
            if not rows and len(tokens) >= 2 and or_q != and_q:
                rows = self._fts_search(conn, or_q, limit)
        return [str(r["key"]) for r in rows]

    @staticmethod
    def _fts_search(conn: sqlite3.Connection, match_query: str, top_k: int) -> list[sqlite3.Row]:
        try:
            return conn.execute(
                """
                SELECT m.key, m.content
                FROM memories_fts f
                JOIN memories m ON m.key = f.key
                WHERE memories_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match_query, top_k),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            logger.warning("FTS search failed for %r: %s", match_query, exc)
            return []

    def _vector_candidates(
        self,
        query_embedding: list[float],
        limit: int,
    ) -> dict[str, tuple[str, float]]:
        """Return key -> (content, similarity) from Chroma vector search."""
        collection = self._ensure_chroma()
        n = max(1, limit)
        # Chroma errors if n_results > collection size; clamp defensively.
        try:
            count = int(collection.count())
        except Exception:
            count = n
        if count <= 0:
            return {}
        n = min(n, count)

        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=n,
            include=["documents", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        out: dict[str, tuple[str, float]] = {}
        for key, doc, dist in zip(ids, documents, distances):
            if not key:
                continue
            similarity = 1.0 - float(dist)
            content = (doc or "").strip()
            out[str(key)] = (content, similarity)
        return out

    def _score_fts_keys(
        self,
        keys: list[str],
        query_embedding: list[float],
    ) -> dict[str, tuple[str, float]]:
        """Score FTS keys that already have Chroma embeddings; drop legacy-only rows."""
        if not keys:
            return {}
        collection = self._ensure_chroma()
        try:
            got = collection.get(ids=keys, include=["documents", "embeddings"])
        except Exception:
            logger.exception("Memory Chroma get failed for FTS keys")
            return {}

        ids = got.get("ids") or []
        documents = got.get("documents")
        embeddings = got.get("embeddings")
        if documents is None:
            documents = []
        if embeddings is None:
            embeddings = []

        out: dict[str, tuple[str, float]] = {}
        for key, doc, emb in zip(ids, documents, embeddings):
            if not key or emb is None:
                continue
            # chromadb may return numpy arrays
            if hasattr(emb, "tolist"):
                emb_list = emb.tolist()
            else:
                emb_list = list(emb)
            if not emb_list or any(x is None for x in emb_list):
                continue
            if any(isinstance(x, float) and math.isnan(x) for x in emb_list):
                continue
            similarity = _cosine(query_embedding, emb_list)
            content = (doc or "").strip()
            if content:
                out[str(key)] = (content, similarity)
        return out

    def _categories_for_keys(self, keys: list[str]) -> dict[str, str]:
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT key, category FROM memories WHERE key IN ({placeholders})",
                keys,
            ).fetchall()
        out: dict[str, str] = {}
        for row in rows:
            cat = (row["category"] or "").strip()
            out[str(row["key"])] = cat or "other"
        return out

    @staticmethod
    def _merge_score_maps(
        *maps: dict[str, tuple[str, float]],
    ) -> dict[str, tuple[str, float]]:
        merged: dict[str, tuple[str, float]] = {}
        for mapping in maps:
            for key, (content, score) in mapping.items():
                prev = merged.get(key)
                if prev is None or score > prev[1]:
                    merged[key] = (content, score)
        return merged

    def _hybrid_score_map(
        self,
        query: str,
        query_embedding: list[float],
        candidate_k: int,
        *,
        fts_query: str | None = None,
    ) -> tuple[dict[str, tuple[str, float]], int, int]:
        """Vector + FTS merge for one query string. Returns (merged, fts_n, vec_n)."""
        try:
            vec_hits = self._vector_candidates(query_embedding, candidate_k)
        except Exception:
            logger.exception("Memory vector retrieve failed query=%r", query)
            vec_hits = {}

        fts_keys = self._fts_candidate_keys(
            fts_query if fts_query is not None else query, candidate_k
        )
        try:
            fts_scored = self._score_fts_keys(fts_keys, query_embedding)
        except Exception:
            logger.exception("Memory FTS rescore failed query=%r", query)
            fts_scored = {}
        return self._merge_score_maps(vec_hits, fts_scored), len(fts_keys), len(vec_hits)

    def _time_aware_score_map(
        self,
        query: str,
        candidate_k: int,
        *,
        now: datetime,
        time_query: str | None,
        time_query_embedding: list[float] | None,
        fallback_embedding: list[float],
    ) -> tuple[dict[str, tuple[str, float]], str, int, int]:
        timed_query = (time_query or "").strip() or build_time_aware_query(query, now)
        timed_emb = time_query_embedding
        if timed_emb is None:
            try:
                timed_emb = self._ensure_encoder().encode_query(timed_query)
            except Exception:
                logger.exception("Memory time-aware encode failed query=%r", timed_query)
                timed_emb = fallback_embedding

        try:
            vec_hits = self._vector_candidates(timed_emb, candidate_k)
        except Exception:
            logger.exception(
                "Memory time-aware vector retrieve failed query=%r", timed_query
            )
            vec_hits = {}

        fts_queries = memory_time_fts_queries(
            now,
            extra_dates=relative_dates_in(query, now),
            extra_months=relative_months_in(query, now),
        )
        fts_keys: list[str] = []
        seen: set[str] = set()
        for fts_q in fts_queries:
            for key in self._fts_candidate_keys(fts_q, candidate_k):
                if key not in seen:
                    seen.add(key)
                    fts_keys.append(key)
        try:
            fts_scored = self._score_fts_keys(fts_keys, timed_emb)
        except Exception:
            logger.exception("Memory time-aware FTS rescore failed query=%r", timed_query)
            fts_scored = {}
        merged = self._merge_score_maps(vec_hits, fts_scored)
        return merged, timed_query, len(fts_keys), len(vec_hits)

    def retrieve_entries(
        self,
        query: str,
        top_k: int = 3,
        query_embedding: list[float] | None = None,
        *,
        apply_inject_cooldown: bool = False,
        apply_score_filter: bool = True,
        include_time: bool = True,
        time_query: str | None = None,
        time_query_embedding: list[float] | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Hybrid retrieve returning key/content/category/score dicts."""
        query = (query or "").strip()
        if not query:
            return []

        top_k = max(1, int(top_k))
        candidate_k = max(top_k, int(self.config.candidate_top_k))
        clock = now or datetime.now()

        try:
            collection = self._ensure_chroma()
            if int(collection.count()) <= 0:
                logger.info(
                    "memory retrieve query=%r skipped empty chroma",
                    query,
                )
                return []
            if query_embedding is None:
                query_embedding = self._ensure_encoder().encode_query(query)
        except FileNotFoundError as exc:
            logger.warning("%s", exc)
            return self._fts_only_entries(
                query,
                top_k,
                apply_inject_cooldown=apply_inject_cooldown,
                apply_score_filter=apply_score_filter,
            )
        except Exception:
            logger.exception("Memory retrieve backend init failed; falling back to FTS")
            return self._fts_only_entries(
                query,
                top_k,
                apply_inject_cooldown=apply_inject_cooldown,
                apply_score_filter=apply_score_filter,
            )

        orig_merged, fts_n, vec_n = self._hybrid_score_map(
            query, query_embedding, candidate_k
        )
        timed_query = ""
        timed_fts_n = 0
        timed_vec_n = 0
        if include_time:
            timed_map, timed_query, timed_fts_n, timed_vec_n = self._time_aware_score_map(
                query,
                candidate_k,
                now=clock,
                time_query=time_query,
                time_query_embedding=time_query_embedding,
                fallback_embedding=query_embedding,
            )
            merged = self._merge_score_maps(orig_merged, timed_map)
        else:
            merged = orig_merged

        ranked = sorted(merged.items(), key=lambda item: item[1][1], reverse=True)
        if apply_score_filter:
            passed = self._filter_by_score(ranked, query)
        else:
            passed = [
                (key, content, score)
                for key, (content, score) in ranked
                if content
            ]
        pre_scores = _preview_scored(passed)
        cooled_keys = [
            key
            for key, _, _ in passed
        ]
        passed = self._drop_cooled_entries(
            passed,
            apply_inject_cooldown=apply_inject_cooldown,
            query=query,
        )
        dropped_cooled = [
            key for key in cooled_keys if key not in {k for k, _, _ in passed}
        ]
        passed = passed[:top_k]

        categories = self._categories_for_keys([key for key, _, _ in passed])
        entries = [
            {
                "key": key,
                "content": content,
                "category": categories.get(key, "other"),
                "score": float(score),
            }
            for key, content, score in passed
        ]
        logger.info(
            "memory retrieve query=%r time_query=%r fts_keys=%d timed_fts_keys=%d "
            "vec_hits=%d timed_vec_hits=%d merged=%d hits=%d min_score=%.3f "
            "min_score_no_overlap=%.3f score_filter=%s pre_scores=%s cooled=%s "
            "scores=%s items=%s",
            query,
            timed_query or None,
            fts_n,
            timed_fts_n,
            vec_n,
            timed_vec_n,
            len(merged),
            len(entries),
            float(self.config.min_score),
            float(self.config.min_score_no_overlap),
            apply_score_filter,
            pre_scores,
            dropped_cooled,
            [(round(e["score"], 3), e["content"][:40]) for e in entries],
            [e["content"] for e in entries],
        )
        return entries

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        query_embedding: list[float] | None = None,
        *,
        apply_inject_cooldown: bool = False,
        include_time: bool = True,
        time_query: str | None = None,
        time_query_embedding: list[float] | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        entries = self.retrieve_entries(
            query,
            top_k,
            query_embedding=query_embedding,
            apply_inject_cooldown=apply_inject_cooldown,
            apply_score_filter=True,
            include_time=include_time,
            time_query=time_query,
            time_query_embedding=time_query_embedding,
            now=now,
        )
        cooldown = float(self.config.inject_cooldown_sec)
        if apply_inject_cooldown and cooldown > 0 and entries:
            self.mark_injected([e["key"] for e in entries])
        return [e["content"] for e in entries]

    def find_exact_content(self, content: str) -> list[dict[str, Any]]:
        """Return rows whose stored content equals strip(content) or compare-normalized form."""
        raw = (content or "").strip()
        if not raw:
            return []
        norm = normalize_content_for_compare(raw)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, content, category FROM memories"
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            stored = str(row["content"] or "").strip()
            if stored == raw or normalize_content_for_compare(stored) == norm:
                out.append(
                    {
                        "key": str(row["key"]),
                        "content": stored,
                        "category": (str(row["category"] or "").strip() or "other"),
                        "score": 1.0,
                    }
                )
        return out

    def find_similar(
        self,
        content: str,
        *,
        exclude_key: str | None = None,
        top_k: int = 5,
        min_score: float = 0.82,
    ) -> list[dict[str, Any]]:
        """Vector-near neighbors of a memory content (for conflict reconcile)."""
        content = (content or "").strip()
        if not content:
            return []

        top_k = max(1, int(top_k))
        min_score = float(min_score)
        exclude = (exclude_key or "").strip()

        try:
            collection = self._ensure_chroma()
            count = int(collection.count())
            if count <= 0:
                return []
            encoder = self._ensure_encoder()
            # Compare memory-to-memory in document space.
            embedding = encoder.encode_documents([content])[0]
            n = min(top_k + (1 if exclude else 0), count)
            result = collection.query(
                query_embeddings=[embedding],
                n_results=n,
                include=["documents", "distances", "metadatas"],
            )
        except Exception:
            logger.exception("Memory find_similar failed content=%r", content[:80])
            return []

        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]

        entries: list[dict[str, Any]] = []
        for i, key in enumerate(ids):
            if not key or str(key) == exclude:
                continue
            dist = distances[i] if i < len(distances) else 1.0
            doc = documents[i] if i < len(documents) else ""
            meta = metadatas[i] if i < len(metadatas) else {}
            similarity = 1.0 - float(dist)
            if similarity < min_score:
                continue
            text = (doc or "").strip()
            if not text:
                continue
            meta = meta or {}
            category = str(meta.get("category") or "").strip() or "other"
            entries.append(
                {
                    "key": str(key),
                    "content": text,
                    "category": category,
                    "score": similarity,
                }
            )
            if len(entries) >= top_k:
                break

        if entries:
            # Prefer SQLite category when present (source of truth).
            cats = self._categories_for_keys([e["key"] for e in entries])
            for e in entries:
                if e["key"] in cats:
                    e["category"] = cats[e["key"]]

        logger.info(
            "memory find_similar exclude=%r min_score=%.3f hits=%d items=%s",
            exclude,
            min_score,
            len(entries),
            [(round(e["score"], 3), e["key"], e["content"][:40]) for e in entries],
        )
        return entries

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()
            return int(row["c"] if row else 0)

    def list_by_category(self, category: str) -> list[dict[str, Any]]:
        """Return stored memories in a category (SQLite is source of truth)."""
        cat = (category or "").strip()
        if not cat:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, content, category, updated_at FROM memories "
                "WHERE category = ?",
                (cat,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            key = str(row["key"] or "").strip()
            content = str(row["content"] or "").strip()
            if not key or not content:
                continue
            out.append(
                {
                    "key": key,
                    "content": content,
                    "category": str(row["category"] or "").strip() or "other",
                    "updated_at": float(row["updated_at"] or 0.0),
                }
            )
        return out

    def get_entries(self, keys: list[str]) -> list[dict[str, Any]]:
        """Return stored memories for the given keys (SQLite is source of truth)."""
        cleaned = [str(key or "").strip() for key in keys]
        cleaned = [key for key in cleaned if key]
        if not cleaned:
            return []
        placeholders = ",".join("?" * len(cleaned))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT key, content, category FROM memories WHERE key IN ({placeholders})",
                cleaned,
            ).fetchall()
        by_key = {str(row["key"]): row for row in rows}
        out: list[dict[str, Any]] = []
        for key in cleaned:
            row = by_key.get(key)
            if row is None:
                continue
            content = str(row["content"] or "").strip()
            if not content:
                continue
            out.append(
                {
                    "key": key,
                    "content": content,
                    "category": str(row["category"] or "").strip() or "other",
                    "score": 1.0,
                }
            )
        return out

    def document_similarities(
        self,
        content: str,
        candidates: list[dict[str, Any]],
    ) -> list[tuple[str, float]]:
        """Document-space cosine of content vs each candidate (for extract conflict cleanup)."""
        query = (content or "").strip()
        if not query or not candidates:
            return []
        texts = [query]
        keys: list[str] = []
        bodies: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            key = str(item.get("key") or "").strip()
            body = str(item.get("content") or "").strip()
            if not key or not body or key in seen:
                continue
            seen.add(key)
            keys.append(key)
            bodies.append(body)
        if not keys:
            return []
        try:
            encoder = self._ensure_encoder()
            embeddings = encoder.encode_documents(texts + bodies)
        except Exception:
            logger.exception("document_similarities encode failed content=%r", query[:80])
            return []
        if len(embeddings) != 1 + len(keys):
            return []
        query_emb = embeddings[0]
        out: list[tuple[str, float]] = []
        for key, emb in zip(keys, embeddings[1:]):
            out.append((key, _cosine(query_emb, emb)))
        return out
