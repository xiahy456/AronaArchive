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

"""Write one parsed inner thought. Speech is ignored. Failure is the caller's job."""

from __future__ import annotations

import logging
from datetime import datetime

from ..arona_memory import AronaMemory
from ..journal import LifeJournal
from ..state import THOUGHT_RUMINATION_PREFIX, InnerState, Rumination, retain_rumination
from .schema import InnerThought
from .store import PendingTrigger, ThoughtFocus, ThoughtLedger

logger = logging.getLogger(__name__)


def commit_inner(
    *,
    now: datetime,
    inner: InnerState,
    ledger: ThoughtLedger,
    parsed: InnerThought,
    journal: LifeJournal | None = None,
    arona: AronaMemory | None = None,
    queued: PendingTrigger | None = None,
) -> InnerState:
    """Replace the one thought concern, notes, and ledger. Does not enqueue speech."""
    stamp = now.replace(microsecond=0)
    if parsed.thought:
        logger.info("thought inner thought=%s", parsed.thought)
    items = list(inner.rumination)
    if parsed.keep == "drop":
        items = [item for item in items if not _is_thought(item)]
    elif parsed.forget_id:
        items = [
            item
            for item in items
            if not (_is_thought(item) and item.id == parsed.forget_id)
        ]
    if parsed.keep == "open" and parsed.focus:
        items = [item for item in items if not _is_thought(item)]
        concern_id = f"thought-{stamp.strftime('%Y%m%d%H%M%S')}"
        items.append(
            Rumination(id=concern_id, content=parsed.focus, created_at=stamp)
        )
        ledger.focus = ThoughtFocus(
            id=concern_id,
            text=parsed.focus,
            since=stamp,
            spoken=False,
        )
    elif parsed.keep == "drop":
        ledger.focus = None
    next_inner = inner.clone()
    next_inner.rumination = retain_rumination(items)
    if journal is not None:
        journal.note_inner(next_inner, now=stamp, arona=arona)
    if queued is not None and queued.kind == "consolidate":
        if arona is not None and parsed.memory_note.strip():
            arona.replace_notes(_note_lines(parsed.memory_note), stamp)
        ledger.consolidated_day = stamp.date().isoformat()
    elif arona is not None and parsed.memory_note:
        arona.append_note(parsed.memory_note, stamp)
    ledger.last_thought_at = stamp
    if parsed.focus:
        ledger.last_focus = parsed.focus
    hour = stamp.strftime("%Y-%m-%dT%H")
    if ledger.thought_hour == hour:
        ledger.thought_count += 1
    else:
        ledger.thought_hour = hour
        ledger.thought_count = 1
    if parsed.feeling:
        ledger.last_feeling = parsed.feeling
    if queued is not None:
        if queued.kind == "glance" and (queued.detail or "").strip():
            ledger.last_glance_seen = queued.detail.strip()
        if queued.kind == "memory" and queued.memory_key:
            if queued.memory_key not in ledger.seen_memory_keys:
                ledger.seen_memory_keys.append(queued.memory_key)
        ledger.pending_triggers = [
            item for item in ledger.pending_triggers if item is not queued
        ]
    return next_inner


def _note_lines(note: str) -> list[str]:
    return [line.strip() for line in note.splitlines() if line.strip()]


def _is_thought(item: Rumination) -> bool:
    return item.id.startswith(THOUGHT_RUMINATION_PREFIX)
