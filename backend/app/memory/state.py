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

"""Resident situation sentences. Not a labeled slot map and not a vector index."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..safety import is_crisis_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StateItem:
    id: str
    text: str
    created_at: float
    updated_at: float
    importance: int
    source_key: str = ""


class StateStore:
    def __init__(
        self,
        db_path: Path,
        *,
        max_items: int = 12,
        max_chars: int = 32,
    ) -> None:
        self.db_path = Path(db_path)
        self.max_items = max(1, int(max_items))
        self.max_chars = max(1, int(max_chars))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state_items (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    importance INTEGER NOT NULL DEFAULT 5,
                    source_key TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_state_updated
                ON state_items(updated_at)
                """
            )
            conn.commit()

    def all_items(self) -> list[StateItem]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, text, created_at, updated_at, importance, source_key
                FROM state_items
                ORDER BY importance DESC, updated_at DESC, id ASC
                """
            ).fetchall()
        out: list[StateItem] = []
        for row in rows:
            text = str(row["text"] or "").strip()
            item_id = str(row["id"] or "").strip()
            if not item_id or not text:
                continue
            out.append(
                StateItem(
                    id=item_id,
                    text=text,
                    created_at=float(row["created_at"] or 0.0),
                    updated_at=float(row["updated_at"] or 0.0),
                    importance=_clamp_importance(row["importance"]),
                    source_key=str(row["source_key"] or "").strip(),
                )
            )
        return out

    def texts(self) -> list[str]:
        return [item.text for item in self.all_items()]

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM state_items").fetchone()
        return int(row["c"] if row else 0)

    def upsert(self, item: StateItem) -> bool:
        item_id = (item.id or "").strip()
        text = " ".join((item.text or "").split())
        if not item_id or not text:
            logger.info("state upsert skipped reason=empty id=%r", item_id)
            return False
        if is_crisis_text(text):
            logger.info("state upsert skipped reason=crisis id=%s", item_id)
            return False
        if len(text) > self.max_chars:
            logger.info(
                "state upsert skipped reason=too_long id=%s chars=%d limit=%d",
                item_id,
                len(text),
                self.max_chars,
            )
            return False
        now = time.time()
        importance = _clamp_importance(item.importance)
        source = (item.source_key or "").strip()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT created_at FROM state_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if existing is None and self.count() >= self.max_items:
                logger.info(
                    "state upsert skipped reason=full id=%s max=%d",
                    item_id,
                    self.max_items,
                )
                return False
            created = float(existing["created_at"]) if existing is not None else now
            conn.execute(
                """
                INSERT INTO state_items(
                    id, text, created_at, updated_at, importance, source_key
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    text=excluded.text,
                    updated_at=excluded.updated_at,
                    importance=excluded.importance,
                    source_key=excluded.source_key
                """,
                (item_id, text, created, now, importance, source),
            )
            conn.commit()
        logger.info("state upsert id=%s text=%s", item_id, text)
        return True

    def delete(self, ids: list[str]) -> int:
        cleaned = [str(item or "").strip() for item in ids if str(item or "").strip()]
        if not cleaned:
            return 0
        placeholders = ",".join("?" for _ in cleaned)
        with self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM state_items WHERE id IN ({placeholders})",
                cleaned,
            )
            conn.commit()
            removed = int(cur.rowcount or 0)
        if removed:
            logger.info("state delete ids=%s removed=%d", cleaned, removed)
        return removed


def _clamp_importance(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        number = 5
    return max(1, min(10, number))


def format_state_context(
    items: list[StateItem],
    now: datetime,
    *,
    confirm_after_hours: float,
) -> str:
    """Extractor-only listing. The age marks must never be copied into planner text."""
    lines = ["【现有状态】"]
    if not items:
        lines.append("（无）")
        return "\n".join(lines)
    confirm_after = max(0.0, float(confirm_after_hours))
    for item in items:
        age_hours = max(0.0, (now.timestamp() - float(item.updated_at)) / 3600.0)
        stamp = datetime.fromtimestamp(item.updated_at).strftime("%Y-%m-%d")
        if age_hours < 24:
            age = "不足1天"
        else:
            age = f"{int(age_hours // 24)}天前"
        mark = f"[id={item.id} | {stamp} 更新 | {age} | importance={item.importance}"
        if age_hours >= confirm_after:
            mark += " | 待确认"
        mark += "]"
        lines.append(f"- {item.text} {mark}")
    return "\n".join(lines)
