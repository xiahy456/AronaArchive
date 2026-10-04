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

"""One inner-thought completion. Uses the planner endpoint, not IntentCard."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ...config import PlannerConfig, ThoughtConfig
from ...logging_utils import format_llm_exchange
from .prompt import THOUGHT_SYSTEM

logger = logging.getLogger(__name__)

_MIN_TOKENS = 1024
_THINKING_MIN_TOKENS = 8192


class ThoughtClient:
    def __init__(
        self, config: PlannerConfig, thought: ThoughtConfig | None = None
    ) -> None:
        self.config = config
        self.thought = thought or ThoughtConfig()

    @property
    def enabled(self) -> bool:
        key = (self.config.api_key or "").strip()
        return bool(self.config.enabled and key and key != "YOUR_DEEPSEEK_API_KEY")

    def _thinking_enabled(self) -> bool:
        return bool(self.thought.thinking)

    def _thinking_body(self) -> dict[str, str]:
        return {"type": "enabled" if self._thinking_enabled() else "disabled"}

    def _complete_max_tokens(self) -> int:
        n = max(int(self.config.max_tokens or 0), _MIN_TOKENS)
        if self._thinking_enabled():
            return max(n, _THINKING_MIN_TOKENS)
        return n

    async def complete(self, user_text: str, *, system: str | None = None) -> str | None:
        """Return the raw model text, or None on timeout or transport failure."""
        if not self.enabled:
            logger.info("thought model skipped reason=disabled_or_no_key")
            return None
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system or THOUGHT_SYSTEM},
                {"role": "user", "content": user_text},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self._complete_max_tokens(),
            "response_format": {"type": "json_object"},
            "thinking": self._thinking_body(),
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_sec) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            message = data["choices"][0]["message"] or {}
            content = str(message.get("content") or "")
            reasoning = str(message.get("reasoning_content") or "").strip()
            logger.info(
                "%s",
                format_llm_exchange(
                    title="thought",
                    prompt=payload["messages"],
                    response=content,
                    reasoning=reasoning or None,
                    extra={
                        "model": payload["model"],
                        "temperature": payload["temperature"],
                        "max_tokens": payload["max_tokens"],
                    },
                ),
            )
            return content
        except Exception:
            logger.exception(
                "%s",
                format_llm_exchange(
                    title="thought",
                    prompt=payload["messages"],
                    response=None,
                    extra={
                        "model": payload["model"],
                        "temperature": payload["temperature"],
                        "max_tokens": payload["max_tokens"],
                    },
                ),
            )
            return None
