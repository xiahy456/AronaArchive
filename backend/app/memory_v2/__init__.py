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

"""Public entry for the v2 memory package."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from app.safety import is_crisis_text

from .commitments import CommitmentBook
from .db import Database
from .events import Event, EventLog
from .extract import Extractor
from .inject import format_event_block, format_resident_block
from .rerank import DEFAULT_RERANK_PATH
from .retrieve import EventRetriever
from .scan import CommitmentScanner
from .states import StateBook, assert_state_budget
from .trace import TraceLog
from .util import first_sentence

logger = logging.getLogger(__name__)


class MemoryV2:
    """States, events, and commitments. Does not share code with the v1 package."""

    def __init__(
        self,
        config: Any,
        *,
        backend_dir: Path,
        trace_path: Path,
        token_budget_state: int,
        token_budget_memory: int = 250,
        encoder: Any = None,
        dialogue: Callable[[float], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.config = config
        storage = config.storage
        self.db = Database(
            _resolve(backend_dir, storage.db_path),
            _resolve(backend_dir, storage.events_fts),
        )
        if self.db.legacy_v1:
            self._refuse_legacy()
        states_cfg = config.states
        events_cfg = config.events
        commit_cfg = config.commitment
        extract_cfg = config.extractor
        assert_state_budget(
            max_items=states_cfg.max_items,
            max_chars_per_item=states_cfg.max_chars_per_item,
            token_budget_state=token_budget_state,
        )
        self.trace = TraceLog(trace_path, enabled=bool(config.trace_enabled))
        self.states = StateBook(
            self.db,
            max_items=states_cfg.max_items,
            max_chars=states_cfg.max_chars_per_item,
            key_max_chars=states_cfg.key_max_chars,
        )
        self.events = EventLog(self.db)
        self.commitments = CommitmentBook(self.db)
        rerank_path = DEFAULT_RERANK_PATH
        if not rerank_path.is_absolute():
            rerank_path = (backend_dir / rerank_path).resolve()
        self.retriever = EventRetriever(
            self.events,
            self.trace,
            inject_top_k=events_cfg.inject_top_k,
            vector_enabled=events_cfg.vector_enabled,
            chroma_path=_resolve(backend_dir, storage.chroma_path),
            rerank_enabled=events_cfg.rerank_enabled,
            rerank_candidates=events_cfg.rerank_candidates,
            rerank_model_path=rerank_path,
            encoder=encoder,
            token_budget_memory=token_budget_memory,
        )
        self.extractor = Extractor(
            events=self.events,
            states=self.states,
            commitments=self.commitments,
            retriever=self.retriever,
            trace=self.trace,
            base_url=extract_cfg.base_url,
            api_key=extract_cfg.api_key,
            model=extract_cfg.model,
            timeout_sec=extract_cfg.timeout_sec,
            state_model=extract_cfg.state_model,
            commitment_model=extract_cfg.commitment_model,
            window_max_turns=extract_cfg.window_max_turns,
            window_max_chars=extract_cfg.window_max_chars,
            retry_max=extract_cfg.retry_max,
            calls_per_day=extract_cfg.calls_per_day,
            summary_max_chars=events_cfg.summary_max_chars,
            extract_max_new=commit_cfg.extract_max_new,
            current_max_chars=commit_cfg.current_max_chars,
            enabled=extract_cfg.enabled,
        )
        self._pending_lines: list[str] = []
        self._dialogue = dialogue or (lambda _since: [])
        self._life: Any = None
        scan_model = commit_cfg.scan_model or extract_cfg.model
        self.scanner = CommitmentScanner(
            commitments=self.commitments,
            states=self.states,
            trace=self.trace,
            dialogue=self._recent_dialogue,
            pending_commitment=self._commitment_pending,
            offer=self._offer_commitment,
            base_url=extract_cfg.base_url,
            api_key=extract_cfg.api_key,
            model=scan_model,
            timeout_sec=commit_cfg.scan_timeout_sec,
            scan_default_sec=commit_cfg.scan_default_sec,
            scan_max_sec=commit_cfg.scan_max_sec,
            scan_min_sec=commit_cfg.scan_min_sec,
            lookback_hours=commit_cfg.scan_lookback_hours,
            inject_max=commit_cfg.inject_max,
            current_max_chars=commit_cfg.current_max_chars,
            stale_after_sec=commit_cfg.stale_after_sec,
            enabled=commit_cfg.enabled,
        )
        if not self.db.fts_ready:
            raise RuntimeError(
                f"memory_v2 failed to create events_fts at {self.db.fts_path}"
            )

    def live_states(self) -> list[str]:
        return [
            line
            for line in self.states.live()
            if line.strip() and not is_crisis_text(line)
        ]

    def state_block(self) -> str:
        return format_resident_block(self.live_states())

    def search_events(self, query: str, *, k: int | None = None) -> list[Event]:
        return self.retriever.search(query, k=k)

    def event_block(self, query: str, *, k: int | None = None) -> tuple[list[str], str]:
        events = self.search_events(query, k=k)
        block = format_event_block(events)
        return [event.summary for event in events], block

    def enqueue_window(self, window: list[dict[str, Any]]) -> None:
        self.extractor.enqueue(window)

    def pending_commitment_lines(self) -> list[str]:
        return list(self._pending_lines)

    def bind_life(self, life: Any) -> None:
        self._life = life

    def bind_dialogue(self, dialogue: Callable[[float], list[dict[str, Any]]]) -> None:
        self._dialogue = dialogue

    def _recent_dialogue(self, since: float) -> list[dict[str, Any]]:
        rows = self._dialogue(since)
        return list(rows or [])

    def _commitment_pending(self) -> bool:
        engine = self._life
        state = getattr(engine, "state", None)
        pending = getattr(state, "pending_impulse", None)
        return getattr(pending, "kind", "") == "commitment"

    def _offer_commitment(self, payload: dict[str, Any]) -> bool:
        lines = [str(item).strip() for item in payload.get("extra_memories") or [] if str(item).strip()]
        if self._commitment_pending():
            return False
        engine = self._life
        if engine is None:
            self._pending_lines = lines
            return True
        from app.life.impulse import offer_impulse
        from app.life.state import Impulse

        source_id = str(payload.get("source_id") or "")
        accepted = offer_impulse(
            engine,
            Impulse(
                kind="commitment",
                created_at=datetime.now(),
                source_id=source_id,
                hint=str(payload.get("hint") or first_sentence("".join(lines))),
                extra_memories=tuple(lines),
            ),
        )
        pending = getattr(getattr(engine, "state", None), "pending_impulse", None)
        if not accepted or getattr(pending, "source_id", "") != source_id:
            return False
        self._pending_lines = lines
        return True

    def _refuse_legacy(self) -> None:
        message = (
            "memory.db 仍是 v1 结构（存在 memories 或 state_items，没有 events）。"
            "请先停止后端，运行 python scripts/migrate_memory_v2.py 完成迁移后再启动。"
            "直接继续会忽略尚未迁移的 v1 记忆。"
        )
        logger.error("%s", message)
        print(message, file=sys.stderr)
        raise SystemExit(message)


def _resolve(backend_dir: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        return path
    return (backend_dir / path).resolve()
