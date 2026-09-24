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

"""Facade: classify → update A/B/C → decide → persist."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .classify import classify_user_act
from .events import (
    DEFAULT_USER_ACT,
    AronaAct,
    UserAct,
    arona_delta,
    normalize_user_act,
    user_delta,
)
from .policy import (
    URGENT_CLIMATES,
    Action,
    Climate,
    Decision,
    decide,
    decide_proactive,
    map_arona_act,
)
from .state import RelationshipState
from .store import RelationshipStore
from ..taxonomy import CRISIS_USER_ACT

logger = logging.getLogger(__name__)

# Planner labels that must not backfill a user Δ (or crisis-gate an everyday turn).
_PLANNER_BACKFILL_SKIP: frozenset[str] = frozenset(
    {DEFAULT_USER_ACT, CRISIS_USER_ACT, "touch"}
)


@dataclass
class RelationshipSettings:
    enabled: bool = True
    alpha: float = 0.3
    beta: float = 0.02
    daily_abs_cap: float = 0.35
    makeup_tension: float = 0.7
    makeup_trust_scale: float = 1.5
    cling_dependence: float = 0.55
    high_dependence: float = 0.7
    climate_stick_turns: int = 3
    baseline_trust: float = 0.55
    baseline_dependence: float = 0.30
    baseline_tension: float = 0.25

    @property
    def baseline(self) -> tuple[float, float, float]:
        return (
            self.baseline_trust,
            self.baseline_dependence,
            self.baseline_tension,
        )

    @classmethod
    def from_config(cls, rel_cfg: Any) -> RelationshipSettings:
        return cls(
            enabled=bool(getattr(rel_cfg, "enabled", True)),
            alpha=float(getattr(rel_cfg, "alpha", 0.3)),
            beta=float(getattr(rel_cfg, "beta", 0.02)),
            daily_abs_cap=float(getattr(rel_cfg, "daily_abs_cap", 0.35)),
            makeup_tension=float(getattr(rel_cfg, "makeup_tension", 0.7)),
            makeup_trust_scale=float(getattr(rel_cfg, "makeup_trust_scale", 1.5)),
            cling_dependence=float(getattr(rel_cfg, "cling_dependence", 0.55)),
            high_dependence=float(getattr(rel_cfg, "high_dependence", 0.7)),
            climate_stick_turns=int(getattr(rel_cfg, "climate_stick_turns", 3)),
            baseline_trust=float(getattr(rel_cfg, "baseline_trust", 0.55)),
            baseline_dependence=float(getattr(rel_cfg, "baseline_dependence", 0.30)),
            baseline_tension=float(getattr(rel_cfg, "baseline_tension", 0.25)),
        )


class RelationshipEngine:
    def __init__(self, settings: RelationshipSettings, store: RelationshipStore) -> None:
        self.settings = settings
        self.store = store
        self.state = store.load()
        self._last_rule_act: UserAct | None = None
        self.on_urgent_enter: Any = None

    @classmethod
    def from_path(cls, path: Path, settings: RelationshipSettings) -> RelationshipEngine:
        return cls(settings, RelationshipStore(path))

    def _apply(self, delta: tuple[float, float, float]) -> None:
        s = self.settings
        self.state.apply_delta(
            delta,
            alpha=s.alpha,
            beta=s.beta,
            baseline=s.baseline,
            daily_abs_cap=s.daily_abs_cap,
            makeup_tension=s.makeup_tension,
            makeup_trust_scale=s.makeup_trust_scale,
        )

    def preview_user_text(self, text: str) -> tuple[UserAct, Decision]:
        """Classify and decide without applying A/B/C or persisting stickiness."""
        act = classify_user_act(text)
        streak = self.state.climate_streak
        last = self.state.last_climate
        recovering_from = self.state.recovering_from
        recover_remaining = self.state.recover_remaining
        decision = decide(
            self.state,
            act,
            cling_dependence=self.settings.cling_dependence,
            high_dependence=self.settings.high_dependence,
            stick_turns=self.settings.climate_stick_turns,
        )
        self.state.climate_streak = streak
        self.state.last_climate = last
        self.state.recovering_from = recovering_from
        self.state.recover_remaining = recover_remaining
        return act, decision

    def _note_climate(self, before: str) -> None:
        after = self.peek_climate()
        if before in URGENT_CLIMATES or after not in URGENT_CLIMATES:
            return
        listener = self.on_urgent_enter
        if listener is None:
            return
        try:
            listener(before, after)
        except Exception:
            logger.exception("relationship urgent climate notify failed")

    def on_user_text(self, text: str) -> tuple[UserAct, Decision]:
        before = self.peek_climate()
        act = classify_user_act(text)
        self._apply(user_delta(act))
        decision = decide(
            self.state,
            act,
            cling_dependence=self.settings.cling_dependence,
            high_dependence=self.settings.high_dependence,
            stick_turns=self.settings.climate_stick_turns,
        )
        self.state.last_user_act = act
        self._last_rule_act = act
        self.store.save(self.state)
        logger.info(
            "relationship user_act=%s climate=%s action=%s "
            "trust=%.3f dependence=%.3f tension=%.3f",
            act,
            decision.climate,
            decision.action,
            self.state.trust,
            self.state.dependence,
            self.state.tension,
        )
        self._note_climate(before)
        return act, decision

    def on_user_act(self, act: UserAct | str) -> tuple[UserAct, Decision]:
        """Apply a known user_act Δ without classifying text."""
        before = self.peek_climate()
        normalized = normalize_user_act(act)
        self._apply(user_delta(normalized))
        decision = decide(
            self.state,
            normalized,
            cling_dependence=self.settings.cling_dependence,
            high_dependence=self.settings.high_dependence,
            stick_turns=self.settings.climate_stick_turns,
        )
        self.state.last_user_act = normalized
        self._last_rule_act = normalized
        self.store.save(self.state)
        logger.info(
            "relationship user_act=%s climate=%s action=%s "
            "trust=%.3f dependence=%.3f tension=%.3f source=direct",
            normalized,
            decision.climate,
            decision.action,
            self.state.trust,
            self.state.dependence,
            self.state.tension,
        )
        self._note_climate(before)
        return normalized, decision

    def note_planner_user_act(self, act: str) -> tuple[UserAct, bool]:
        """Overwrite last_user_act from Planner; backfill Δ only if rules said other.

        Returns (normalized_act, backfilled). ``backfilled`` is True only when this
        call applied a user Δ. Crisis/touch from Planner never backfill and do not
        overwrite last_user_act when the rule classifier was ``other``.
        """
        normalized = normalize_user_act(act)
        rule_act = self._last_rule_act
        self._last_rule_act = None

        backfilled = False
        before = self.peek_climate()
        if rule_act == DEFAULT_USER_ACT and normalized not in _PLANNER_BACKFILL_SKIP:
            self._apply(user_delta(normalized))
            self.state.last_user_act = normalized
            backfilled = True
            logger.info(
                "relationship planner_user_act=%s backfill=1 "
                "trust=%.3f dependence=%.3f tension=%.3f",
                normalized,
                self.state.trust,
                self.state.dependence,
                self.state.tension,
            )
        elif rule_act == DEFAULT_USER_ACT and normalized in {CRISIS_USER_ACT, "touch"}:
            logger.info(
                "relationship planner_user_act=%s skipped_backfill",
                normalized,
            )
        else:
            self.state.last_user_act = normalized
            logger.info("relationship planner_user_act=%s", normalized)

        self.store.save(self.state)
        if backfilled:
            self._note_climate(before)
        return normalized, backfilled

    def peek_climate(self) -> str:
        from .policy import resolve_climate

        return resolve_climate(
            self.state.trust,
            self.state.dependence,
            self.state.tension,
            cling_dependence=self.settings.cling_dependence,
        )

    def decide_proactive(self, kind: str) -> Decision:
        return decide_proactive(
            self.state,
            kind,
            cling_dependence=self.settings.cling_dependence,
            high_dependence=self.settings.high_dependence,
        )

    def on_arona_action(
        self,
        action: Action,
        climate: Climate,
        user_act: UserAct = "other",
        motive_kind: str | None = None,
    ) -> AronaAct | None:
        event = map_arona_act(action, climate, user_act, motive_kind=motive_kind)
        if event is None:
            return None
        before = self.peek_climate()
        self._apply(arona_delta(event))
        self.store.save(self.state)
        logger.info(
            "relationship arona_act=%s trust=%.3f dependence=%.3f tension=%.3f",
            event,
            self.state.trust,
            self.state.dependence,
            self.state.tension,
        )
        self._note_climate(before)
        return event
