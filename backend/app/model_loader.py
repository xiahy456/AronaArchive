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

"""llama-cpp-python GGUF loader with sync generation."""

from __future__ import annotations

import inspect
import logging
import re
import threading
import time
from typing import Any

from .config import AppConfig

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_LEADING_JUNK_PUNCT = frozenset(".,。、;；:：!！?？")
_ELLIPSIS_CHAR = "…"
_RAM_CACHE_BYTES = 32 * 1024 * 1024
_WARMUP_DRAFT = "老师好。"


def strip_think_tags(text: str) -> str:
    cleaned = _THINK_RE.sub("", text or "")
    return cleaned.strip()


def strip_leading_junk(text: str) -> str:
    """Remove accidental leading punctuation; keep ellipsis (… / ... / ......)."""
    s = (text or "").lstrip()
    while s:
        if s[0] == _ELLIPSIS_CHAR:
            break
        n = 0
        while n < len(s) and s[n] == ".":
            n += 1
        if n >= 3:
            break
        if n > 0:
            s = s[n:].lstrip()
            continue
        if s[0] in _LEADING_JUNK_PUNCT:
            s = s[1:].lstrip()
            continue
        break
    return s


def clean_model_output(text: str) -> str:
    return strip_leading_junk(strip_think_tags(text))


class ModelLoader:
    """Process-wide singleton wrapper around llama-cpp Llama."""

    def __init__(self) -> None:
        self._llm: Any = None
        self._lock = threading.Lock()
        self._config: AppConfig | None = None
        self._extra_completion_kwargs: dict[str, Any] = {}

    def load(self, config: AppConfig) -> None:
        with self._lock:
            if self._llm is not None:
                return
            from llama_cpp import Llama

            path = config.gguf_abs_path
            if not path.is_file():
                raise FileNotFoundError(f"GGUF not found: {path}")

            logger.info("Loading GGUF from %s (n_ctx=%s)", path, config.model.n_ctx)
            self._llm = Llama(
                model_path=str(path),
                n_ctx=config.model.n_ctx,
                n_gpu_layers=config.model.n_gpu_layers,
                verbose=False,
            )
            self._config = config
            self._configure_prompt_cache()
            logger.info("Model loaded")

    def _configure_prompt_cache(self) -> None:
        """Reuse Renderer system prefix KV across turns when llama-cpp allows it."""
        self._extra_completion_kwargs = {}
        if self._llm is None:
            return
        try:
            params = inspect.signature(self._llm.create_chat_completion).parameters
        except (TypeError, ValueError):
            params = {}
        if "cache_prompt" in params:
            self._extra_completion_kwargs["cache_prompt"] = True
            logger.info("llama-cpp cache_prompt enabled")
            return
        try:
            from llama_cpp import LlamaRAMCache

            cache = LlamaRAMCache(capacity_bytes=_RAM_CACHE_BYTES)
            self._llm.set_cache(cache)
            logger.info(
                "llama-cpp LlamaRAMCache enabled capacity_bytes=%d",
                _RAM_CACHE_BYTES,
            )
        except Exception:
            logger.warning(
                "prompt prefix cache unavailable; Renderer KV will recompute each turn",
                exc_info=True,
            )

    def warmup(self) -> None:
        """Prime GPU and Renderer chat-template prefix so first request is not cold."""
        if self._llm is None:
            logger.warning("Local LLM warmup skipped: model not loaded")
            return
        cfg = self._config
        if cfg is None:
            logger.warning("Local LLM warmup skipped: model not configured")
            return
        from .prompt import build_renderer_messages

        messages = build_renderer_messages(cfg, draft=_WARMUP_DRAFT)
        logger.info("Warming up local LLM with renderer prefix")
        t0 = time.perf_counter()
        try:
            with self._lock:
                result = self._llm.create_chat_completion(
                    messages=messages,
                    max_tokens=1,
                    temperature=0,
                    stream=False,
                    **self._extra_completion_kwargs,
                )
            usage = (result or {}).get("usage") or {}
            logger.info(
                "Local LLM warmup done latency=%.3fs usage=%s",
                time.perf_counter() - t0,
                usage,
            )
        except Exception:
            logger.exception(
                "Local LLM warmup failed latency=%.3fs; first request may be cold",
                time.perf_counter() - t0,
            )

    @property
    def ready(self) -> bool:
        return self._llm is not None

    def generate(self, messages: list[dict[str, str]], config: AppConfig | None = None) -> str:
        cfg = config or self._config
        if cfg is None:
            raise RuntimeError("Model not configured")
        if self._llm is None:
            raise RuntimeError("Model not loaded")

        logger.info(
            "create_chat_completion sync messages=%d max_tokens=%s temperature=%s",
            len(messages),
            cfg.model.max_new_tokens,
            cfg.model.temperature,
        )
        with self._lock:
            result = self._llm.create_chat_completion(
                messages=messages,
                max_tokens=cfg.model.max_new_tokens,
                temperature=cfg.model.temperature,
                top_p=cfg.model.top_p,
                repeat_penalty=cfg.model.repeat_penalty,
                stream=False,
                **self._extra_completion_kwargs,
            )
        content = result["choices"][0]["message"]["content"] or ""
        cleaned = clean_model_output(content)
        usage = result.get("usage") or {}
        logger.info(
            "create_chat_completion sync done raw_chars=%d cleaned_chars=%d usage=%s",
            len(content),
            len(cleaned),
            usage,
        )
        return cleaned


_model_loader: ModelLoader | None = None


def get_model_loader() -> ModelLoader:
    global _model_loader
    if _model_loader is None:
        _model_loader = ModelLoader()
    return _model_loader
