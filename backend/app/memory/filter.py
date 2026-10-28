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

"""Keep the memories that matter for this turn. Failure keeps the ranked list."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import ExtractorConfig, MemoryConfig

logger = logging.getLogger(__name__)

FILTER_SYSTEM = """判断每条记忆对理解老师此刻说话有没有用。
只保留能帮助理解老师当前处境、计划、身体或心情的条目。
与本次话题无关、但说明了老师长期处境的条目也要保留。
只输出 JSON：{"keep": ["key1", "key2"]}
"""


async def filter_entries(
    *,
    memory_config: MemoryConfig,
    extractor_config: ExtractorConfig,
    query: str,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not memory_config.llm_filter_enabled or len(entries) <= 1:
        return entries
    key = (extractor_config.api_key or "").strip()
    if not key or key == "YOUR_DEEPSEEK_API_KEY":
        return entries
    limited = entries[: max(1, int(memory_config.llm_filter_max_candidates))]
    lines = [
        f"- key={item.get('key')} | {item.get('content')}"
        for item in limited
        if str(item.get("key") or "").strip()
    ]
    if len(lines) <= 1:
        return entries
    user = f"【老师此刻】\n{(query or '').strip()}\n\n【候选记忆】\n" + "\n".join(lines)
    url = extractor_config.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": extractor_config.model,
        "messages": [
            {"role": "system", "content": FILTER_SYSTEM},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=memory_config.llm_filter_timeout_sec) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"] or "{}"
        parsed = json.loads(content)
    except Exception as exc:
        logger.warning("memory filter failed; keeping ranked list: %s", exc)
        return entries
    keep = parsed.get("keep") if isinstance(parsed, dict) else None
    if not isinstance(keep, list):
        return entries
    wanted = {str(item).strip() for item in keep if str(item or "").strip()}
    if not wanted:
        return entries
    kept = [item for item in limited if str(item.get("key") or "") in wanted]
    logger.info(
        "memory filter query=%r before=%d after=%d",
        query,
        len(limited),
        len(kept),
    )
    return kept or entries
