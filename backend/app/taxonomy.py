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

"""Shared names for safety, memory categories, and mood follow-up.

This module is the single source of truth for those strings and meanings.
It is inert: no I/O, no user-text detection, no relationship or scheduler
side effects.

Wiring status:

- Step 1: ``crisis`` is attached to ``USER_DELTAS`` / ``UserAct``.
- Step 2: extractor JSON schema lists ``episodic`` / ``emotional``; same-day
  merge only; labeled inject. Crisis turns are still blocked from extraction.
- Step 3: ``mood_followup`` is attached to ``MotiveKind``. Default config is
  enabled; set ``proactive.mood_followup.enabled`` false to disable triggering.
  Crisis content still cannot be selected.

Meanings
--------
- ``preference`` / ``profile`` / ``goal`` / ``other``: stable facts and plans.
- ``episodic``: a shared event between the teacher and Arona, not a durable
  profile fact.
- ``emotional``: a confirmed mood disclosure (what happened and how the
  teacher felt), not a guess. Default source for mood follow-up.
- ``crisis``: user-act name, distinct from ``fatigue`` and ``self_disclose``.
  Attached to ``UserAct`` in Step 1.
- ``mood_followup``: proactive motive, alongside idle / care / goal / festival.
  Attached to ``MotiveKind`` in Step 3.
"""

from __future__ import annotations

from typing import Literal

MemoryCategory = Literal[
    "preference",
    "profile",
    "goal",
    "other",
    "episodic",
    "emotional",
]

FollowupSkipReason = Literal[
    "crisis",
    "muted",
    "too_new",
    "too_old",
    "climate",
    "blocked_user_act",
]

DEFAULT_MEMORY_CATEGORY: MemoryCategory = "other"

MEMORY_CATEGORIES: frozenset[str] = frozenset(
    {
        "preference",
        "profile",
        "goal",
        "other",
        "episodic",
        "emotional",
    }
)

FACT_CATEGORIES: frozenset[str] = frozenset(
    {"preference", "profile", "goal", "other"}
)

FOLLOWUP_SOURCE_CATEGORIES: frozenset[str] = frozenset({"emotional"})

CRISIS_USER_ACT = "crisis"

MOOD_FOLLOWUP_KIND = "mood_followup"

FOLLOWUP_OK_CLIMATES: frozenset[str] = frozenset({"steady", "secure_play"})

FOLLOWUP_BLOCK_USER_ACTS: frozenset[str] = frozenset(
    {"depart", "reject", CRISIS_USER_ACT}
)

FOLLOWUP_SKIP_REASONS: frozenset[str] = frozenset(
    {
        "crisis",
        "muted",
        "too_new",
        "too_old",
        "climate",
        "blocked_user_act",
    }
)


def normalize_memory_category(value: object | None) -> MemoryCategory:
    """Return a whitelist category; unknown/missing -> other."""
    if not isinstance(value, str):
        return DEFAULT_MEMORY_CATEGORY
    key = value.strip().lower()
    if key in MEMORY_CATEGORIES:
        return key  # type: ignore[return-value]
    return DEFAULT_MEMORY_CATEGORY


def is_followup_source_category(value: object | None) -> bool:
    """True only for categories that may be mood-followup material."""
    return normalize_memory_category(value) in FOLLOWUP_SOURCE_CATEGORIES


def climate_allows_mood_followup(climate: object | None) -> bool:
    """True only in steady / secure_play. Unknown climate is not allowed."""
    if not isinstance(climate, str):
        return False
    return climate.strip() in FOLLOWUP_OK_CLIMATES


def user_act_blocks_mood_followup(act: object | None) -> bool:
    """True when the current user_act must not trigger mood follow-up."""
    if not isinstance(act, str):
        return False
    return act.strip().lower() in FOLLOWUP_BLOCK_USER_ACTS
