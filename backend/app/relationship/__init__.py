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

"""Relationship climate engine (trust / dependence / tension)."""

from .classify import classify_user_act
from .engine import RelationshipEngine, RelationshipSettings
from .events import USER_DELTAS, UserAct
from .policy import (
    CLIMATE_LABELS,
    Decision,
    decide_proactive,
    local_system_hint,
    planner_climate_block,
    crisis_planner_climate_block,
    resolve_climate,
)
from .state import RelationshipState
from .store import RelationshipStore

__all__ = [
    "CLIMATE_LABELS",
    "Decision",
    "RelationshipEngine",
    "RelationshipSettings",
    "RelationshipState",
    "RelationshipStore",
    "USER_DELTAS",
    "UserAct",
    "classify_user_act",
    "decide_proactive",
    "local_system_hint",
    "planner_climate_block",
    "crisis_planner_climate_block",
    "resolve_climate",
]
