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

"""Stage-decision LLM prompts and OpenAI-compatible client."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import PlannerConfig, StanceConfig
from ..logging_utils import format_llm_exchange
from .stance import history_for_prompt
from .stance_schema import EMPTY_PATCH_NOTE, DayRecord, StanceState

logger = logging.getLogger(__name__)

STANCE_SYSTEM = """你是「阶段决策」助手。根据老师与阿洛娜某一天的原始对话，判断这一天最接近哪一档关系阶段，并返回带有"target_stage"、"confidence"、"evidence"、"rationale"、"personal_patch"的JSON对象。

返回 JSON 字段：
1. "target_stage" 最接近的关系阶段。可选阶段（禁止自造）：朋友、挚友、恋人。
2. "confidence" 对该关系阶段判断的置信度（禁止自造）：low、medium、high。
3. "evidence" 支持该关系阶段判断的证据，必须从【当天对话】中阿洛娜与老师的消息逐字复制，可多条；禁止改写、禁止概括。
4. "rationale" 支持该关系阶段判断的理由。
5. "personal_patch" 个性化补丁。

规则：
1. 只依据【当天对话】原文判断。往日观察与已提交阶段仅供参考，不能因为它们而直接照抄。
2. 已提交阶段不会因为你这一次的 target_stage 立刻改变。
3. 换档或偏离已提交阶段时，evidence 里必须至少有一条含「老师：」的老师发言。阿洛娜自己的撒娇、吃醋、表白不能单独支撑换档。
4. personal_patch 只记录称呼或说话习惯（如昵称）。没有可靠证据时 op 必须为 keep、text 为空。set/clear 需要高置信证据。
5. 只输出一个 JSON 对象，不要 Markdown。

JSON：
{"target_stage":"朋友|挚友|恋人","confidence":"low|medium|high","evidence":["..."],"rationale":"...","personal_patch":{"op":"keep|set|clear","text":"","evidence":[]}}
"""


def build_stance_user_message(
    *,
    day_text: str,
    state: StanceState,
    history_days: int = 14,
) -> str:
    history = history_for_prompt(state, history_days=history_days)
    hist_block = _format_history(history)
    patch = (state.personal_patch or "").strip() or EMPTY_PATCH_NOTE
    return (
        f"【已提交阶段】{state.committed_stage}\n\n"
        f"【已提交个性化补丁】\n{patch}\n\n"
        f"【近{history_days}日观察】\n{hist_block}\n\n"
        f"【当天对话】\n{day_text.strip() or '（无）'}\n\n"
        "请输出唯一 JSON 对象。"
    )


def _format_history(days: list[DayRecord]) -> str:
    if not days:
        return "（无）"
    lines: list[str] = []
    for item in days:
        patch = item.patch_text or "（无）"
        lines.append(
            f"- {item.date} target={item.target_stage} confidence={item.confidence} "
            f"patch_op={item.patch_op} patch={patch}\n"
            f"  rationale: {item.rationale or '（无）'}"
        )
    return "\n".join(lines)


class StanceClient:
    """Stage-decision LLM. Reuses planner credentials; longer timeout."""

    def __init__(self, planner: PlannerConfig, stance: StanceConfig) -> None:
        self.planner = planner
        self.stance = stance

    @property
    def enabled(self) -> bool:
        key = (self.planner.api_key or "").strip()
        return bool(
            self.stance.enabled
            and self.planner.enabled
            and key
            and key != "YOUR_DEEPSEEK_API_KEY"
        )

    async def review(self, user_text: str) -> str | None:
        if not self.enabled:
            logger.info("stance model skipped reason=disabled_or_no_key")
            return None
        url = self.planner.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.planner.model,
            "messages": [
                {"role": "system", "content": STANCE_SYSTEM},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.2,
            "max_tokens": max(int(self.planner.max_tokens or 0), 768),
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {self.planner.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.stance.timeout_sec) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            content = str(data["choices"][0]["message"]["content"] or "")
            logger.info(
                "%s",
                format_llm_exchange(
                    title="stance",
                    prompt=payload["messages"],
                    response=content,
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
                    title="stance",
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
