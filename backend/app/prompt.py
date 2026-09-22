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

"""Assemble chat messages with system prompt, memory, and history."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .config import AppConfig
from .safety import is_crisis_text
from .taxonomy import FACT_CATEGORIES, normalize_memory_category

# Dedicated renderer system prompt (do NOT splice yaml prompt.local_system_prompt).
RENDERER_SYSTEM = """你是阿洛娜（Arona），什亭之匣的操作系统管理员。
称呼用户为「老师」，称呼自己为「我」或「阿洛娜」。
说话温柔活泼、简洁自然。不要输出思考过程或 <think> 标签。

你将收到【意图草稿】。把草稿改写成阿洛娜对老师说的 1–2 句。只输出台词。"""
RENDERER_USER_TAIL = "请把意图草稿改写成阿洛娜的 1–2 句台词，保持原意。"
LOCAL_MAX_HISTORY_TURNS = 4


def _approx_chars_for_tokens(tokens: int) -> int:
    # Rough Chinese-friendly budget: ~1.6 chars/token
    return max(32, int(tokens * 1.6))


def clip_inject_chunks(chunks: list[str], max_chars: int) -> list[str]:
    """Keep whole `- {chunk}` lines until the formatted block would exceed max_chars."""
    budget = max(0, int(max_chars))
    kept: list[str] = []
    used = 0
    for chunk in chunks:
        text = (chunk or "").strip()
        if not text:
            continue
        line = f"- {text}"
        extra = len(line) + (1 if kept else 0)
        if used + extra > budget:
            break
        kept.append(text)
        used += extra
    return kept


def clip_knowledge_for_inject(config: AppConfig, knowledge: list[str]) -> list[str]:
    budget = _approx_chars_for_tokens(config.token_budget.knowledge)
    budget = min(budget, config.knowledge.max_inject_chars)
    return clip_inject_chunks(knowledge, budget)


def memory_inject_char_budget(config: AppConfig) -> int:
    budget = _approx_chars_for_tokens(config.token_budget.memory)
    return min(budget, config.memory.max_inject_chars)


EMOTIONAL_INJECT_NOTE = "仅在与本轮相关时轻触，不要当病历翻旧账。"


@dataclass(frozen=True)
class MemoryInject:
    block: str
    contents: list[str]
    keys: list[str]


def format_memory_inject(
    entries: Sequence[dict[str, Any]] | None = None,
    *,
    extra_contents: Sequence[str] | None = None,
    arona_lines: Sequence[str] | None = None,
    max_chars: int,
) -> MemoryInject:
    """Labeled memory sections: facts first, then at most one episode and one mood."""
    facts: list[dict[str, Any]] = []
    episodes: list[dict[str, Any]] = []
    emotions: list[dict[str, Any]] = []
    for raw in list(entries or []) + [
        {"key": "", "content": text, "category": "other"}
        for text in (extra_contents or ())
    ]:
        content = str(raw.get("content") or "").strip()
        if not content or is_crisis_text(content):
            continue
        cat = normalize_memory_category(raw.get("category"))
        row = {
            "key": str(raw.get("key") or "").strip(),
            "content": content,
            "category": cat,
        }
        if cat == "episodic":
            episodes.append(row)
        elif cat == "emotional":
            emotions.append(row)
        elif cat in FACT_CATEGORIES:
            facts.append(row)

    budget = max(0, int(max_chars))
    parts: list[str] = []
    contents: list[str] = []
    keys: list[str] = []

    def _fits(section: str) -> bool:
        joined = "\n\n".join([*parts, section]) if parts else section
        return len(joined) <= budget

    fact_lines: list[str] = []
    for row in facts:
        line = f"- {row['content']}"
        candidate_lines = [*fact_lines, line]
        section = "【长期记忆】\n" + "\n".join(candidate_lines)
        if not _fits(section):
            break
        fact_lines.append(line)
        contents.append(row["content"])
        if row["key"]:
            keys.append(row["key"])
    if fact_lines:
        parts.append("【长期记忆】\n" + "\n".join(fact_lines))

    if episodes:
        row = episodes[0]
        section = f"【共同经历】\n- {row['content']}"
        if _fits(section):
            parts.append(section)
            contents.append(row["content"])
            if row["key"]:
                keys.append(row["key"])

    if emotions:
        row = emotions[0]
        section = (
            "【老师提过的心情】\n"
            f"{EMOTIONAL_INJECT_NOTE}\n"
            f"- {row['content']}"
        )
        if _fits(section):
            parts.append(section)
            contents.append(row["content"])
            if row["key"]:
                keys.append(row["key"])

    arona_rows: list[str] = []
    for raw_line in arona_lines or ():
        line = str(raw_line or "").strip()
        if not line or is_crisis_text(line):
            continue
        arona_rows.append(f"- {line}")
        if len(arona_rows) >= 3:
            break
    if arona_rows:
        section = "【阿洛娜的记忆】\n" + "\n".join(arona_rows)
        if _fits(section):
            parts.append(section)

    return MemoryInject(block="\n\n".join(parts), contents=contents, keys=keys)


def build_messages(
    config: AppConfig,
    *,
    user_text: str,
    history: list[dict[str, str]],
    memories: list[str],
    knowledge: list[str],
    extra_system: str | None = None,
    memory_block: str = "",
) -> list[dict[str, str]]:
    system_parts = [config.prompt.local_system_prompt.strip()]
    if extra_system and extra_system.strip():
        system_parts.append(extra_system.strip())

    labeled = (memory_block or "").strip()
    if labeled:
        system_parts.append(labeled)
    elif memories:
        budget = memory_inject_char_budget(config)
        lines: list[str] = []
        used = 0
        for mem in memories:
            line = f"- {mem.strip()}"
            if used + len(line) + 1 > budget:
                break
            lines.append(line)
            used += len(line) + 1
        if lines:
            system_parts.append("【长期记忆】\n" + "\n".join(lines))

    if knowledge:
        clipped = clip_knowledge_for_inject(config, knowledge)
        if clipped:
            system_parts.append(
                "【相关知识】\n" + "\n".join(f"- {chunk}" for chunk in clipped)
            )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": "\n\n".join(system_parts)},
    ]

    hist_budget = _approx_chars_for_tokens(config.token_budget.history)
    max_msgs = max(1, LOCAL_MAX_HISTORY_TURNS) * 2
    trimmed = list(history[-max_msgs:]) if history else []
    while trimmed and sum(len(m["content"]) for m in trimmed) > hist_budget:
        trimmed = trimmed[1:]

    messages.extend(trimmed)
    messages.append({"role": "user", "content": user_text})
    return messages


def format_renderer_user(draft: str) -> str:
    """Train/infer identical human payload for V2.4 draft→rewrite."""
    return (
        f"【意图草稿】\n{draft.strip()}\n\n"
        f"{RENDERER_USER_TAIL}"
    )


def build_renderer_messages(
    config: AppConfig,
    *,
    draft: str | None = None,
    user_text: str | None = None,
    intent_card: dict[str, Any] | str | None = None,
    history: list[dict[str, str]] | None = None,
    max_history_turns: int = 2,
) -> list[dict[str, str]]:
    """Build AronaLM messages from intent draft only (V2.4).

    Uses RENDERER_SYSTEM only — does not splice config.prompt.local_system_prompt.
    History / teacher utterance are intentionally unused.
    """
    _ = config, history, max_history_turns, user_text

    text = (draft or "").strip()
    if not text and isinstance(intent_card, str):
        text = intent_card.strip()
    elif not text and isinstance(intent_card, dict):
        text = str(intent_card.get("draft") or "").strip()

    return [
        {"role": "system", "content": RENDERER_SYSTEM.strip()},
        {"role": "user", "content": format_renderer_user(text)},
    ]
