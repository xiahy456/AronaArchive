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

"""Write world events onto the thought queue. Does not call the model."""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import Any

from ...relationship.policy import URGENT_CLIMATES
from ...safety import is_crisis_text
from .store import PendingTrigger, ThoughtLedger

logger = logging.getLogger(__name__)


def note_aftertaste(state: Any, *, now: datetime, crisis: bool = False) -> bool:
    """Queue one delayed aftertaste from this turn. A crisis turn only stamps the time."""
    ledger = _ledger(state)
    if ledger is None:
        return False
    stamp = now.replace(microsecond=0)
    ledger.pending_triggers = [
        item for item in ledger.pending_triggers if item.kind != "aftertaste"
    ]
    accepted = ledger.enqueue(
        PendingTrigger(kind="aftertaste", not_before=stamp + timedelta(seconds=_delay_sec(state)))
    )
    if crisis:
        ledger.last_crisis_at = stamp
    _save(state, ledger)
    return accepted


def note_finished_turn(state: Any, user_text: str, *, now: datetime) -> bool:
    """A committed teacher turn, including silence and crisis. Not a listen fragment."""
    return note_aftertaste(state, now=now, crisis=is_crisis_text(user_text))


def note_arrived(state: Any, *, now: datetime) -> bool:
    return _enqueue(state, PendingTrigger(kind="arrived", not_before=_stamp(now)), now=now)


def note_left(state: Any, *, now: datetime) -> bool:
    return _enqueue(state, PendingTrigger(kind="left", not_before=_stamp(now)), now=now)


def note_glance(state: Any, summary: str, *, now: datetime) -> bool:
    text = (summary or "").strip()
    if not text or is_crisis_text(text):
        return False
    ledger = _ledger(state)
    if ledger is None:
        return False
    if text == (ledger.last_glance_seen or "").strip():
        return False
    if any(item.kind == "glance" and item.detail == text for item in ledger.pending_triggers):
        return False
    accepted = ledger.enqueue(
        PendingTrigger(kind="glance", not_before=_stamp(now), detail=text)
    )
    _save(state, ledger)
    return accepted


def note_memory(state: Any, key: str, *, now: datetime) -> bool:
    item_key = (key or "").strip()
    if not item_key:
        return False
    ledger = _ledger(state)
    if ledger is None or item_key in ledger.seen_memory_keys:
        return False
    if any(item.kind == "memory" and item.memory_key == item_key for item in ledger.pending_triggers):
        return False
    accepted = ledger.enqueue(
        PendingTrigger(kind="memory", not_before=_stamp(now), memory_key=item_key)
    )
    _save(state, ledger)
    return accepted


def note_climate_enter(state: Any, before: str, after: str, *, now: datetime) -> bool:
    """Enqueue only when peek_climate enters an urgent band from outside one."""
    if before in URGENT_CLIMATES or after not in URGENT_CLIMATES:
        return False
    return _enqueue(state, PendingTrigger(kind="climate", not_before=_stamp(now)), now=now)


def _enqueue(state: Any, trigger: PendingTrigger, *, now: datetime) -> bool:
    del now
    ledger = _ledger(state)
    if ledger is None:
        return False
    accepted = ledger.enqueue(trigger)
    _save(state, ledger)
    return accepted


def _ledger(state: Any) -> ThoughtLedger | None:
    cfg = getattr(getattr(getattr(state, "config", None), "life", None), "thought", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        return None
    if getattr(state, "thought_store", None) is None:
        return None
    ledger = getattr(state, "thought", None)
    if not isinstance(ledger, ThoughtLedger):
        ledger = ThoughtLedger()
        state.thought = ledger
    return ledger


def _save(state: Any, ledger: ThoughtLedger) -> None:
    store = getattr(state, "thought_store", None)
    if store is None:
        return
    try:
        store.save(ledger)
    except Exception:
        logger.exception("thought trigger save failed")


def _stamp(now: datetime) -> datetime:
    return now.replace(microsecond=0)


def _delay_sec(state: Any) -> float:
    cfg = getattr(getattr(getattr(state, "config", None), "life", None), "thought", None)
    lo = float(getattr(cfg, "aftertaste_min_sec", 30) or 30)
    hi = float(getattr(cfg, "aftertaste_max_sec", 90) or 90)
    if hi < lo:
        lo, hi = hi, lo
    if lo == hi:
        return lo
    return random.uniform(lo, hi)
