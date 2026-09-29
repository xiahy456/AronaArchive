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

"""Short addressee/EOT LLM call. Does not reuse the 20s Planner prompt."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from ..channel import method_label
from ..config import PlannerConfig
from .rules import ACTION_IGNORE, ACTION_REPLY, ACTION_WAIT

logger = logging.getLogger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")

ROUTER_SYSTEM = """你是桌面陪伴助手「阿洛娜」的轮次路由器。你不写台词。
根据老师刚说的话、阿洛娜上一句、静音情况，判断这一轮该怎么处理。
只输出一个 JSON 对象，不要 Markdown。
action 只能是 ignore、wait、reply：
- ignore：不是对阿洛娜说的（对别人、电话、自言自语、环境闲聊）。
- wait：像还没说完（停在“然后/就是/那个”或明显半句）。
- reply：这是对阿洛娜说的、可以开口的一轮。
JSON：{"action":"ignore"|"wait"|"reply"}"""


def _parse_action(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    candidates = [text]
    match = _JSON_OBJECT_RE.search(text)
    if match:
        candidates.append(match.group(0))
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        action = str(parsed.get("action") or "").strip().lower()
        if action in {ACTION_IGNORE, ACTION_WAIT, ACTION_REPLY}:
            return action
    return None


class LlmTurnRouter:
    def __init__(self, config: PlannerConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        key = (self.config.api_key or "").strip()
        return bool(
            getattr(self.config, "router_enabled", False)
            and self.config.enabled
            and key
            and key != "YOUR_DEEPSEEK_API_KEY"
        )

    async def route(
        self,
        *,
        user_text: str,
        last_arona: str,
        silence_ms: int,
        seconds_since_arona: float | None,
        last_method: str = "",
    ) -> str | None:
        if not self.enabled:
            return None

        timeout = float(getattr(self.config, "router_timeout_sec", 3.0) or 3.0)
        max_tokens = int(getattr(self.config, "router_max_tokens", 64) or 64)
        last = (last_arona or "").strip() or "（无）"
        shown = last if last == "（无）" else f"[{method_label(last_method)}] {last}"
        gap = (
            f"{seconds_since_arona:.1f}s"
            if seconds_since_arona is not None
            else "未知"
        )
        user_payload = (
            f"【阿洛娜上一句】{shown}\n"
            f"【距阿洛娜开口】{gap}\n"
            f"【静音】{int(silence_ms)}ms\n"
            f"【老师本段】{(user_text or '').strip()}\n"
            "请输出唯一 JSON 对象。"
        )
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": user_payload},
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            content = data["choices"][0]["message"]["content"] or ""
            action = _parse_action(content)
            if action is None:
                logger.warning("router parse failed raw=%s", content)
                return None
            logger.info("router llm action=%s raw=%s", action, content)
            return action
        except Exception as exc:
            logger.warning("router llm call failed: %s", exc)
            return None
