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

"""Conservative text router: default do not operate the teacher's PC."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import ComputerUseConfig, PlannerConfig
from ..channel import method_label
from ..life.thought.schema import is_thought_history_marker
from ..logging_utils import format_llm_exchange
from .schema import extract_json_object

logger = logging.getLogger(__name__)

ROUTE_HISTORY_LIMIT = 4

DENY_SUBSTRINGS = (
    "晚安",
    "早安",
    "早上好",
    "摸头",
    "摸摸",
    "吃饭",
    "早饭",
    "早餐",
    "午饭",
    "晚饭",
    "晚餐",
    "想你",
    "想阿洛娜",
    "抱抱",
    "亲亲",
    "喜欢你",
    "去睡觉",
)

ROUTER_SYSTEM = """你是桌面陪伴助手「阿洛娜」的电脑操作路由器。你不写台词，也不执行操作。
结合【近期对话】和老师本段，判断是不是在请阿洛娜立刻操作这台 Windows 电脑。
只输出一个 JSON 对象，不要 Markdown。
computer_use 为 true 仅当是动手操作，不限步数长短，例如：
- 对当前已打开的窗口打字、点按钮、按快捷键。
- 当前窗口内拖（滑块、选区、画一笔、拖窗口）。
- 当前窗口内滚列表。
- 用开始菜单打开应用再操作。
- 使用浏览器、画图等软件完成操作。
- 玩游戏，包括玩到通关。
上一轮老师已经请阿洛娜操作电脑、或阿洛娜刚交代过操作结果时，「写在记事本里 / 再写一段 / 继续」应倾向 true。
以下必须 false：问好、摸头、吃饭、想你、闲聊、提问、只让阿洛娜说话、密码、不确定。
拿不准必须 false。
JSON：{"computer_use": false}"""


def is_denied_computer_use(text: str | None) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    return any(token in stripped for token in DENY_SUBSTRINGS)


def parse_route_decision(raw: str | dict[str, Any] | None) -> bool:
    if isinstance(raw, dict):
        data = raw
    else:
        data = extract_json_object(raw or "")
    if not isinstance(data, dict):
        return False
    value = data.get("computer_use")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def format_route_history(
    history: list[dict[str, str]] | None,
    *,
    limit: int = ROUTE_HISTORY_LIMIT,
) -> str:
    if not history:
        return "（无）"
    items = [item for item in history if isinstance(item, dict)][-max(1, limit) :]
    lines: list[str] = []
    for item in items:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip() or "（空）"
        if role == "user":
            if is_thought_history_marker(content):
                continue
            lines.append(f"[{method_label(item.get('method'))}] 老师：{content}")
        elif role == "assistant":
            lines.append(f"[{method_label(item.get('method'))}] 阿洛娜：{content}")
        else:
            lines.append(content)
    return "\n".join(lines) or "（无）"


def build_route_user_message(
    user_text: str | None,
    history: list[dict[str, str]] | None = None,
) -> str:
    return (
        f"【近期对话】\n{format_route_history(history)}\n"
        f"【老师本段】{(user_text or '').strip()}\n"
        "请输出唯一 JSON 对象。"
    )


class ComputerUseRouter:
    def __init__(self, planner: PlannerConfig, computer_use: ComputerUseConfig) -> None:
        self.planner = planner
        self.computer_use = computer_use

    @property
    def llm_enabled(self) -> bool:
        key = (self.planner.api_key or "").strip()
        return bool(
            self.planner.enabled
            and key
            and key != "YOUR_DEEPSEEK_API_KEY"
        )

    async def should_operate(
        self,
        user_text: str | None,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> bool:
        text = (user_text or "").strip()
        if not text or is_denied_computer_use(text):
            logger.info("computer_use route deny text=%r", text)
            return False
        if not self.llm_enabled:
            logger.info("computer_use route default_false reason=no_llm")
            return False
        timeout = float(self.computer_use.route_timeout_sec or 3.0)
        url = self.planner.base_url.rstrip("/") + "/chat/completions"
        user_payload = build_route_user_message(text, history)
        payload: dict[str, Any] = {
            "model": self.planner.model,
            "messages": [
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": user_payload},
            ],
            "temperature": 0.0,
            "max_tokens": 64,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {self.planner.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            content = data["choices"][0]["message"]["content"] or ""
            decision = parse_route_decision(content)
            logger.info(
                "%s",
                format_llm_exchange(
                    title="computer_use route",
                    prompt=payload["messages"],
                    response=content,
                    extra={"computer_use": decision},
                ),
            )
            return decision
        except Exception as exc:
            logger.warning("computer_use route llm failed: %s", exc)
            return False
