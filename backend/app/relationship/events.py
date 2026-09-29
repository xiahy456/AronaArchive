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

"""Table-driven relationship deltas. LLM must never invent these floats."""

from __future__ import annotations

from typing import Literal

UserAct = Literal[
    "fatigue",
    "seek_validation",
    "self_disclose",
    "play_tease",
    "reject",
    "gratitude",
    "affection",
    "worry_bond",
    "depart",
    "instrumental",
    "short_ack",
    "touch",
    "crisis",
    "other",
]

AronaAct = Literal[
    "followed_up",
    "gave_space",
    "teased",
    "greeted",
    "checked_in",
    "cared",
    "missed_promise",
]

DEFAULT_USER_ACT: UserAct = "other"

# (trust, dependence, tension)
USER_DELTAS: dict[UserAct, tuple[float, float, float]] = {
    "fatigue": (0.0, 0.08, -0.05),
    "seek_validation": (0.04, 0.12, 0.08),
    "self_disclose": (0.08, 0.06, 0.04),
    "play_tease": (0.03, 0.0, 0.12),
    "reject": (-0.06, -0.04, 0.15),
    "gratitude": (0.10, 0.04, -0.04),
    "affection": (0.08, 0.04, -0.05),
    "worry_bond": (0.02, 0.10, 0.08),
    "depart": (0.0, -0.06, -0.06),
    "instrumental": (0.0, -0.06, -0.08),
    "short_ack": (0.0, 0.03, -0.06),
    "touch": (0.04, 0.06, -0.03),
    "crisis": (0.0, 0.0, 0.0),
    "other": (0.0, 0.0, 0.0),
}

ARONA_DELTAS: dict[AronaAct, tuple[float, float, float]] = {
    "followed_up": (0.02, 0.03, 0.01),
    "gave_space": (0.0, -0.06, -0.04),
    "teased": (0.02, 0.0, 0.08),
    "greeted": (0.03, 0.0, 0.0),
    "checked_in": (0.01, 0.0, 0.0),
    "cared": (0.02, 0.0, 0.0),
    "missed_promise": (-0.12, 0.0, 0.06),
}


USER_ACT_WHITELIST: frozenset[str] = frozenset(USER_DELTAS)
USER_ACT_WHITELIST_CSV = ", ".join(sorted(USER_ACT_WHITELIST))


def normalize_user_act(value: object | None) -> UserAct:
    """Return a whitelist user_act; unknown/missing -> other."""
    if not isinstance(value, str):
        return DEFAULT_USER_ACT
    key = value.strip().lower()
    if key in USER_DELTAS:
        return key  # type: ignore[return-value]
    return DEFAULT_USER_ACT


def user_delta(act: UserAct) -> tuple[float, float, float]:
    return USER_DELTAS.get(act, USER_DELTAS["other"])


def arona_delta(act: AronaAct) -> tuple[float, float, float]:
    return ARONA_DELTAS[act]
