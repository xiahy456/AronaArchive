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

"""Load, apply world events, tick the clock, persist on change."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .events import WorldEvent, world_event
from .policy import LifeDecision, LifeSettings, decide
from .state import DEFAULT_ACTIVITY, DEFAULT_ATTENTION, InnerState, format_life_dt
from .store import LifeStore

logger = logging.getLogger(__name__)


class LifeEngine:
    def __init__(self, settings: LifeSettings, store: LifeStore) -> None:
        self.settings = settings
        self.store = store
        self.state = store.load()
        self.last_decision: LifeDecision | None = None
        self._impulse_busy = False

    @classmethod
    def from_path(cls, path: Path, settings: LifeSettings) -> LifeEngine:
        return cls(settings, LifeStore(path))

    @classmethod
    def from_config(cls, path: Path, cfg: Any) -> LifeEngine:
        settings = LifeSettings(
            look_hold_sec=float(getattr(cfg, "look_hold_sec", 180)),
            think_hold_sec=float(getattr(cfg, "think_hold_sec", 120)),
        )
        return cls.from_path(path, settings)

    def release_startup_look(self, now: datetime | None = None) -> bool:
        """A look at the teacher does not survive a process restart."""
        if self.state.activity != "looking_at_teacher":
            return False
        when = (now or datetime.now()).replace(microsecond=0)
        nxt = self.state.clone()
        nxt.activity = DEFAULT_ACTIVITY
        if nxt.attention == "teacher":
            nxt.attention = DEFAULT_ATTENTION
        nxt.activity_since = when
        self.state = nxt
        self.store.save(self.state)
        logger.info("life startup activity=%s", self.state.activity)
        return True

    def _commit(self, decision: LifeDecision, *, climate: str | None) -> LifeDecision:
        before = self.state.to_dict()
        had_impulse = self.state.pending_impulse is not None
        self.state = decision.state
        action = decision.action
        if action == "glance":
            action = "emotion_only"
            decision = LifeDecision(
                state=self.state,
                action=action,
                next_activity=self.state.activity,
                impulse_followup=decision.impulse_followup,
                impulse_kind=decision.impulse_kind,
                impulse_source_id=decision.impulse_source_id,
                impulse_due_soon=decision.impulse_due_soon,
            )
        allowed = {"continue_activity", "shift_activity"}
        if had_impulse or self.state.pending_impulse is not None:
            allowed.update({"speak", "emotion_only"})
        if action not in allowed:
            action = "continue_activity"
            decision = LifeDecision(
                state=self.state,
                action=action,
                next_activity=self.state.activity,
                impulse_followup="keep",
                impulse_kind=decision.impulse_kind,
                impulse_source_id=decision.impulse_source_id,
                impulse_due_soon=decision.impulse_due_soon,
            )
        if self.state.to_dict() != before:
            self.store.save(self.state)
            logger.info(
                "life action=%s activity=%s attention=%s mood=%s climate=%s "
                "impulse=%s followup=%s",
                decision.action,
                self.state.activity,
                self.state.attention,
                self.state.private_mood,
                climate or "-",
                (self.state.pending_impulse.kind if self.state.pending_impulse else "-"),
                decision.impulse_followup,
            )
        self.last_decision = decision
        return decision

    def apply(
        self,
        event: WorldEvent,
        *,
        climate: str | None = None,
    ) -> LifeDecision | None:
        """Apply a world event. Failures are logged; callers are not blocked."""
        try:
            decision = decide(
                self.state, event, settings=self.settings, climate=climate
            )
            return self._commit(decision, climate=climate)
        except Exception:
            logger.exception("life apply failed kind=%s", event.kind)
            return None

    def tick(
        self,
        now: datetime | None = None,
        *,
        climate: str | None = None,
    ) -> LifeDecision | None:
        event = world_event("clock_tick", at=now)
        return self.apply(event, climate=climate)

    def note_arona_spoke(self, at: datetime | None = None) -> None:
        """Stamp last_spoke_at when a non-empty chat_response is sent."""
        try:
            when = (at or datetime.now()).replace(microsecond=0)
            if format_life_dt(self.state.last_spoke_at) == format_life_dt(when):
                return
            nxt = self.state.clone()
            nxt.last_spoke_at = when
            self.state = nxt
            self.store.save(self.state)
        except Exception:
            logger.exception("life note_arona_spoke failed")
