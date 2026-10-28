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

"""One small call that decides which extractor jobs a turn needs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from ..config import ExtractorConfig
from .prompts import ALL_EXTRACT_KINDS, GATE_SYSTEM

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateDecision:
    remember: bool
    kinds: tuple[str, ...]
    failed: bool = False


def _normalize_kinds(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    found: list[str] = []
    for item in value:
        kind = str(item or "").strip().lower()
        if kind in ALL_EXTRACT_KINDS and kind not in found:
            found.append(kind)
    return tuple(found)


async def decide_gate(config: ExtractorConfig, user_text: str) -> GateDecision:
    key = (config.api_key or "").strip()
    if not config.gate_enabled or not key or key == "YOUR_DEEPSEEK_API_KEY":
        return GateDecision(remember=False, kinds=(), failed=True)
    url = config.base_url.rstrip("/") + "/chat/completions"
    model = (config.gate_model or "").strip() or config.model
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": GATE_SYSTEM},
            {"role": "user", "content": (user_text or "").strip()},
        ],
        "temperature": 0,
        "max_tokens": max(16, int(config.gate_max_tokens or 64)),
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=config.gate_timeout_sec) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"] or "{}"
        parsed = json.loads(content)
    except Exception as exc:
        logger.warning("memory gate failed: %s", exc)
        return GateDecision(remember=False, kinds=(), failed=True)
    if not isinstance(parsed, dict):
        return GateDecision(remember=False, kinds=(), failed=True)
    kinds = _normalize_kinds(parsed.get("kinds"))
    remember = bool(parsed.get("remember")) and bool(kinds)
    if kinds and not remember:
        remember = True
    if not kinds:
        remember = False
    logger.info("memory gate remember=%s kinds=%s", remember, list(kinds))
    return GateDecision(remember=remember, kinds=kinds, failed=False)
