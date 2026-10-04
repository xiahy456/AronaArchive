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

"""OpenAI-compatible planner client (separate from memory extractor)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import PlannerConfig
from ..image_input import ImagePayload, redact_image_fields
from ..safety import is_crisis_text
from ..logging_utils import update_trace
from .prompts import (
    PLANNER_SYSTEM_CRISIS,
    build_planner_user_message,
    select_planner_system,
)
from .schema import IntentCard, parse_and_gate_intent

logger = logging.getLogger(__name__)

_THINKING_MIN_TOKENS = 8192


def qq_image_content(user_payload: str, images: list[str | ImagePayload]) -> list[dict[str, Any]]:
    """One text part, then each QQ image as an image_url (https or data URL)."""
    parts: list[dict[str, Any]] = [{"type": "text", "text": user_payload}]
    for image in images:
        url = image if isinstance(image, str) else image.data_url()
        if not str(url or "").strip():
            continue
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts


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

    def _thinking_body(self) -> dict[str, str]:
        return {"type": "enabled" if self.config.thinking else "disabled"}

    def _plan_max_tokens(self) -> int:
        n = int(self.config.max_tokens or 0)
        if self.config.thinking:
            return max(n, _THINKING_MIN_TOKENS)
        return n

    async def plan(
        self,
        *,
        user_text: str,
        history: list[dict[str, str]],
        memories: list[str],
        knowledge: list[str],
        climate_block: str = "",
        image: ImagePayload | None = None,
        qq_images: list[str | ImagePayload] | None = None,
        crisis: bool = False,
        memory_block: str = "",
        life_block: str = "",
        day_block: str = "",
        teacher_method: str | None = None,
        channels_block: str = "",
        stage: str = "",
        patch: str = "",
    ) -> IntentCard | None:
        if not self.enabled:
            logger.info("planner skipped reason=disabled_or_no_key")
            return None

        url = self.config.base_url.rstrip("/") + "/chat/completions"
        photos = [item for item in (qq_images or []) if item]
        has_screenshot = image is not None and not photos
        user_payload = build_planner_user_message(
            user_text=user_text,
            history=history,
            memories=memories,
            knowledge=knowledge,
            climate_block=climate_block,
            has_screenshot=has_screenshot,
            has_qq_images=bool(photos),
            memory_block=memory_block,
            life_block=life_block,
            day_block=day_block,
            teacher_method=teacher_method,
            channels_block=channels_block,
        )
        if photos:
            model = (self.config.vision_model or "").strip() or self.config.model
            user_content: str | list[dict[str, Any]] = qq_image_content(user_payload, photos)
        elif image is not None:
            model = (self.config.vision_model or "").strip() or self.config.model
            user_content = [
                {"type": "text", "text": user_payload},
                {
                    "type": "image_url",
                    "image_url": {"url": image.data_url()},
                },
            ]
        else:
            model = self.config.model
            user_content = user_payload
        if crisis:
            system_prompt = PLANNER_SYSTEM_CRISIS
        else:
            from ..relationship.stance_schema import DEFAULT_STAGE

            system_prompt = select_planner_system(
                renderer_enabled=self.renderer_enabled,
                stage=stage or DEFAULT_STAGE,
                patch=patch,
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
            "max_tokens": self._plan_max_tokens(),
            "response_format": {"type": "json_object"},
            "thinking": self._thinking_body(),
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

    async def describe_glance(self, image: ImagePayload) -> str:
        """One checkable line from a glance frame. Empty means drop it."""
        if not self.enabled:
            return ""
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        model = (self.config.vision_model or "").strip() or self.config.model
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你需要根据截图写若干句中文，描述屏幕上确实看得见的内容。字数不多于100字。"
                        "看不清、不确定、或没有有用信息时，seen 必须是空字符串。"
                        "禁止编造没看见的窗口、文件名或文字。"
                        "只输出 JSON：{\"seen\":\"...\"}。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "这帧屏幕上看得见什么？"},
                        {
                            "type": "image_url",
                            "image_url": {"url": image.data_url()},
                        },
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": 300,
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
            content = data["choices"][0]["message"]["content"] or ""
        except Exception as exc:
            logger.info("glance describe dropped reason=%s", exc)
            return ""
        return _glance_seen(content)


_UNSURE_MARKS = ("不确定", "看不清", "无法确定", "不知道", "不清楚", "unclear", "unknown")


def _glance_seen(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    seen = str(parsed.get("seen") or "").strip()
    if not seen or is_crisis_text(seen):
        return ""
    lowered = seen.lower()
    if any(mark in seen or mark in lowered for mark in _UNSURE_MARKS):
        return ""
    return seen
