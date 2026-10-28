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

"""One daily digest of the teacher's recent days. Not Arona's private notes."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

import httpx

from ..config import ExtractorConfig

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM = """你是近况整理助手。根据近一天的事件和已经写下的当前状态，写 3 到 5 句老师的客观近况。

只输出 JSON：{"lines": ["句子", "句子"]}

规则：
- 每句是可以单独读的中文短句，主语用「老师」。
- 写一段时间里的脉络，不复述已经写进当前状态的短期事实。
- 不要写阿洛娜自己的心情或猜测。
- 没有足够材料时返回 {"lines": []}。
"""


class SummaryStore:
    def __init__(self, db_path: Path, *, max_chars: int = 200) -> None:
        self.db_path = Path(db_path)
        self.max_chars = max(32, int(max_chars))
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
                CREATE TABLE IF NOT EXISTS day_summaries (
                    day TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def last_day(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT day FROM day_summaries ORDER BY day DESC LIMIT 1"
            ).fetchone()
        return str(row["day"]) if row else ""

    def latest_content(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content FROM day_summaries ORDER BY day DESC LIMIT 1"
            ).fetchone()
        return str(row["content"] or "") if row else ""

    def save(self, day: str, content: str) -> None:
        key = (day or "").strip()
        text = (content or "").strip()
        if not key or not text:
            return
        if len(text) > self.max_chars:
            text = text[: self.max_chars].rsplit("\n", 1)[0].strip() or text[: self.max_chars]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO day_summaries(day, content, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET
                    content=excluded.content,
                    created_at=excluded.created_at
                """,
                (key, text, time.time()),
            )
            conn.commit()
        logger.info("day summary saved day=%s chars=%d", key, len(text))


async def build_day_summary(
    config: ExtractorConfig,
    *,
    episodes: list[str],
    state_lines: list[str],
) -> str:
    key = (config.api_key or "").strip()
    if not key or key == "YOUR_DEEPSEEK_API_KEY":
        return ""
    episode_block = "\n".join(f"- {line}" for line in episodes if line.strip()) or "（无）"
    state_block = "\n".join(f"- {line}" for line in state_lines if line.strip()) or "（无）"
    user = f"【近一天的事件】\n{episode_block}\n\n【已经写下的当前状态】\n{state_block}"
    url = config.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=config.timeout_sec) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"] or "{}"
    parsed = json.loads(content)
    lines = parsed.get("lines") if isinstance(parsed, dict) else None
    if not isinstance(lines, list):
        return ""
    kept = [" ".join(str(line).split()) for line in lines if str(line or "").strip()]
    return "\n".join(kept[:5])
