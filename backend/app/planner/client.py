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

"""OpenAI-compatible planner client (separate from memory extractor)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import PlannerConfig
from ..image_input import ImagePayload, redact_image_fields
from ..logging_utils import update_trace
from .prompts import (
    PLANNER_SYSTEM_CRISIS,
    build_planner_user_message,
    select_planner_system,
)
from .schema import IntentCard, parse_and_gate_intent

logger = logging.getLogger(__name__)


class PlannerClient:
    def __init__(
        self, config: PlannerConfig, *, renderer_enabled: bool = True
    ) -> None:
        self.config = config
        self.renderer_enabled = renderer_enabled

    @property
    def enabled(self) -> bool:
        key = (self.config.api_key or "").strip()
        return bool(
            self.config.enabled
            and key
            and key != "YOUR_DEEPSEEK_API_KEY"
        )

    async def plan(
        self,
        *,
        user_text: str,
        history: list[dict[str, str]],
        memories: list[str],
        knowledge: list[str],
        climate_block: str = "",
        image: ImagePayload | None = None,
        crisis: bool = False,
        memory_block: str = "",
        life_block: str = "",
    ) -> IntentCard | None:
        if not self.enabled:
            logger.info("planner skipped reason=disabled_or_no_key")
            return None

        url = self.config.base_url.rstrip("/") + "/chat/completions"
        has_image = image is not None
        user_payload = build_planner_user_message(
            user_text=user_text,
            history=history,
            memories=memories,
            knowledge=knowledge,
            climate_block=climate_block,
            has_screenshot=has_image,
            memory_block=memory_block,
            life_block=life_block,
        )
        if image is not None:
            model = (self.config.vision_model or "").strip() or self.config.model
            user_content: str | list[dict[str, Any]] = [
                {"type": "text", "text": user_payload},
                {
                    "type": "image_url",
                    "image_url": {"url": image.data_url()},
                },
            ]
        else:
            model = self.config.model
            user_content = user_payload
        system_prompt = (
            PLANNER_SYSTEM_CRISIS
            if crisis
            else select_planner_system(renderer_enabled=self.renderer_enabled)
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": user_content},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        update_trace(planner_prompt=redact_image_fields(payload["messages"]))
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_sec) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            content = data["choices"][0]["message"]["content"] or ""
            update_trace(planner_json=content)
            logger.info("planner raw json=%s", content)
            card = parse_and_gate_intent(content)
            if card is None:
                logger.warning("planner parse/gate failed raw=%s", content)
                return None
            logger.info(
                "planner ok model=%s emotion=%s reply_ok=%s user_act=%s followup_ok=%s",
                model,
                card.arona_emotion,
                card.reply_ok,
                card.user_act,
                card.followup_ok,
            )
            return card
        except Exception as exc:
            logger.warning("planner call failed: %s", exc)
            return None
