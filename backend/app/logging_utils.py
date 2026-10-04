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

"""Shared helpers for structured pipeline logging."""

from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .config import get_config

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

_APP_LOGGERS = (
    "app",
    "app.main",
    "app.ws_handler",
    "app.orchestrator",
    "app.model_loader",
    "app.knowledge",
    "app.memory.store",
    "app.memory.extractor",
    "app.turntaking",
    "app.turntaking.router",
    "app.turntaking.llm_router",
    "app.image_input",
    "app.computer_use",
    "app.life",
)


_NONE = "(none)"

_trace: ContextVar[InteractionTrace | None] = ContextVar(
    "interaction_trace", default=None
)


@dataclass
class InteractionTrace:
    started_at: float = 0.0
    request_json: str | None = None
    planner_prompt: Any = None
    planner_reasoning: str | None = None
    planner_json: str | None = None
    renderer_prompt: Any = None
    renderer_text: str | None = None


def begin_trace(
    *,
    started_at: float | None = None,
    request_json: str | None = None,
) -> InteractionTrace:
    trace = InteractionTrace(
        started_at=started_at if started_at is not None else time.perf_counter(),
        request_json=request_json,
    )
    _trace.set(trace)
    return trace


def current_trace() -> InteractionTrace | None:
    return _trace.get()


def update_trace(**fields: Any) -> None:
    trace = _trace.get()
    if trace is None:
        return
    for key, value in fields.items():
        setattr(trace, key, value)


def reset_trace() -> None:
    _trace.set(None)


def pretty_json(value: Any) -> str:
    """Pretty-print JSON-like values; fall back to original text or (none)."""
    if value is None:
        return _NONE
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return _NONE
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return value
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    return json.dumps(value, ensure_ascii=False, indent=2)


def format_llm_exchange(
    *,
    title: str,
    prompt: Any,
    response: Any,
    reasoning: Any = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Multi-line remote-LLM exchange, same indent style as interactive logs."""
    sections = [f"prompt:\n{pretty_json(prompt)}"]
    reasoning_text = reasoning
    if isinstance(reasoning, str):
        reasoning_text = reasoning.strip() or None
    if reasoning_text not in (None, ""):
        sections.append(f"reasoning:\n{pretty_json(reasoning_text)}")
    sections.append(f"response:\n{pretty_json(response)}")
    if extra:
        for key, value in extra.items():
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            elif isinstance(value, (dict, list)):
                rendered = pretty_json(value)
            else:
                rendered = str(value)
            sections.append(f"{key}: {rendered}")
    return f"{title}:\n" + "\n\n".join(sections)


def format_interactive_log(
    payload: dict[str, Any],
    *,
    elapsed: float | None = None,
) -> str:
    """Multi-line interactive information block for one chat_response."""
    trace = current_trace()
    if elapsed is None:
        started = trace.started_at if trace is not None else 0.0
        elapsed = (time.perf_counter() - started) if started else 0.0
    renderer_text = (trace.renderer_text or "").strip() if trace else ""
    if not renderer_text:
        renderer_text = _NONE
    return (
        "interactive information:\n"
        f"request:\n{pretty_json(trace.request_json if trace else None)}\n\n"
        f"planner_prompt:\n{pretty_json(trace.planner_prompt if trace else None)}\n\n"
        f"planner_reasoning:\n{pretty_json(trace.planner_reasoning if trace else None)}\n\n"
        f"planner_json:\n{pretty_json(trace.planner_json if trace else None)}\n\n"
        f"renderer_prompt:\n{pretty_json(trace.renderer_prompt if trace else None)}\n\n"
        f"renderer_text:\n{renderer_text}\n\n"
        f"response:\n{pretty_json(payload)}\n\n"
        f"elapsed: {elapsed:.3f}s"
    )


def preview(text: str | None, max_len: int = 200) -> str:
    """Collapse whitespace and truncate for compact log lines."""
    s = " ".join((text or "").split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def preview_list(items: list[str] | None, *, item_max: int = 80, list_max: int = 3) -> str:
    """Format a short preview of a string list for logs."""
    if not items:
        return "[]"
    shown = [preview(x, item_max) for x in items[:list_max]]
    extra = len(items) - list_max
    body = "; ".join(shown)
    if extra > 0:
        return f"[{body}; +{extra} more]"
    return f"[{body}]"


def _is_console_handler(handler: logging.Handler) -> bool:
    return isinstance(handler, logging.StreamHandler) and not isinstance(
        handler, logging.FileHandler
    )


def _is_target_file_handler(handler: logging.Handler, log_path: Path) -> bool:
    if not isinstance(handler, RotatingFileHandler):
        return False
    try:
        return Path(handler.baseFilename).resolve() == log_path.resolve()
    except Exception:
        return False


def configure_logging() -> Path:
    """Attach console + rotating file handlers to the root logger (idempotent)."""
    config = get_config()
    level_name = (config.logging.level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT)

    log_dir = config.logging_dir_abs_path
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = config.logging_file_abs_path

    root = logging.getLogger()
    root.setLevel(level)

    has_console = False
    has_file = False
    for handler in root.handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)
        if _is_console_handler(handler):
            has_console = True
        if _is_target_file_handler(handler, log_path):
            has_file = True

    if not has_console:
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(formatter)
        root.addHandler(console)

    if not has_file:
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=config.logging.max_bytes,
            backupCount=config.logging.backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Keep app pipeline logs visible even if uvicorn tweaks root handlers later.
    for name in _APP_LOGGERS:
        logging.getLogger(name).setLevel(level)

    return log_path
