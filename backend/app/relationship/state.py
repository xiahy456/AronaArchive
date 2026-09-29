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

"""Slow relationship climate: trust / dependence / tension in [-1, 1]."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


@dataclass
class RelationshipState:
    trust: float = 0.55
    dependence: float = 0.30
    tension: float = 0.25
    last_climate: str = "secure_play"
    last_user_act: str = "other"
    climate_streak: int = 0
    recovering_from: str = ""
    recover_remaining: int = 0
    day: str = ""
    day_abs_trust: float = 0.0
    day_abs_dependence: float = 0.0
    day_abs_tension: float = 0.0

    def __post_init__(self) -> None:
        if not self.day:
            self.day = date.today().isoformat()

    def snapshot(self) -> dict[str, float]:
        return {
            "trust": self.trust,
            "dependence": self.dependence,
            "tension": self.tension,
        }

    def _roll_day(self, now: datetime | None = None) -> None:
        today = (now or datetime.now()).date().isoformat()
        if self.day != today:
            self.day = today
            self.day_abs_trust = 0.0
            self.day_abs_dependence = 0.0
            self.day_abs_tension = 0.0

    def apply_delta(
        self,
        delta: tuple[float, float, float],
        *,
        alpha: float,
        beta: float,
        baseline: tuple[float, float, float],
        daily_abs_cap: float,
        makeup_tension: float = 0.7,
        makeup_trust_scale: float = 1.5,
        now: datetime | None = None,
    ) -> tuple[float, float, float]:
        """Apply Δ with inertia, regression, makeup, and daily cap.

        new = clamp(old + α*Δ - β*(old - baseline), -1, 1)
        """
        self._roll_day(now)
        da, db, dc = delta
        if self.tension > makeup_tension and da > 0:
            da *= makeup_trust_scale

        applied = [0.0, 0.0, 0.0]
        currents = [self.trust, self.dependence, self.tension]
        bases = list(baseline)
        used = [self.day_abs_trust, self.day_abs_dependence, self.day_abs_tension]
        raw_deltas = [da, db, dc]

        for i, old in enumerate(currents):
            remaining = max(0.0, daily_abs_cap - used[i])
            step = alpha * raw_deltas[i]
            if abs(step) > remaining:
                step = remaining if step > 0 else -remaining
            new = _clamp(old + step - beta * (old - bases[i]))
            applied[i] = new - old
            currents[i] = new
            used[i] += abs(step)

        self.trust, self.dependence, self.tension = currents
        self.day_abs_trust, self.day_abs_dependence, self.day_abs_tension = used
        return (applied[0], applied[1], applied[2])

    def to_dict(self) -> dict[str, Any]:
        return {
            "trust": self.trust,
            "dependence": self.dependence,
            "tension": self.tension,
            "last_climate": self.last_climate,
            "last_user_act": self.last_user_act,
            "climate_streak": self.climate_streak,
            "recovering_from": self.recovering_from,
            "recover_remaining": self.recover_remaining,
            "day": self.day,
            "day_abs_trust": self.day_abs_trust,
            "day_abs_dependence": self.day_abs_dependence,
            "day_abs_tension": self.day_abs_tension,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RelationshipState:
        if not data:
            return cls()
        return cls(
            trust=float(data.get("trust", 0.55)),
            dependence=float(data.get("dependence", 0.30)),
            tension=float(data.get("tension", 0.25)),
            last_climate=str(data.get("last_climate") or "secure_play"),
            last_user_act=str(data.get("last_user_act") or "other"),
            climate_streak=int(data.get("climate_streak") or 0),
            recovering_from=str(data.get("recovering_from") or ""),
            recover_remaining=int(data.get("recover_remaining") or 0),
            day=str(data.get("day") or ""),
            day_abs_trust=float(data.get("day_abs_trust") or 0.0),
            day_abs_dependence=float(data.get("day_abs_dependence") or 0.0),
            day_abs_tension=float(data.get("day_abs_tension") or 0.0),
        )
