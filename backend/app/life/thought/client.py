# Copyright 2026 xia_hy456. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""One inner-thought completion. Uses the planner endpoint, not IntentCard."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ...config import PlannerConfig
from .prompt import THOUGHT_SYSTEM

logger = logging.getLogger(__name__)

_MIN_TOKENS = 1024


class ThoughtClient:
    def __init__(self, config: PlannerConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        key = (self.config.api_key or "").strip()
        return bool(self.config.enabled and key and key != "YOUR_DEEPSEEK_API_KEY")

    async def complete(self, user_text: str) -> str | None:
        """Return the raw model text, or None on timeout or transport failure."""
        if not self.enabled:
            logger.info("thought model skipped reason=disabled_or_no_key")
            return None
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": THOUGHT_SYSTEM},
                {"role": "user", "content": user_text},
            ],
            "temperature": self.config.temperature,
            "max_tokens": max(int(self.config.max_tokens or 0), _MIN_TOKENS),
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
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
            return str(data["choices"][0]["message"]["content"] or "")
        except Exception:
            logger.exception("thought model call failed")
            return None
