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

"""Speaker tags on transcript messages. Phase 1 always sends teacher."""

from __future__ import annotations

SPEAKER_TEACHER = "teacher"
SPEAKER_OTHER = "other"
SPEAKER_UNKNOWN = "unknown"

_USER_SPEAKERS = frozenset({SPEAKER_TEACHER})


def normalize_speaker(value: object | None) -> str:
    text = str(value or "").strip().lower()
    if text == SPEAKER_OTHER:
        return SPEAKER_OTHER
    if text == SPEAKER_UNKNOWN:
        return SPEAKER_UNKNOWN
    return SPEAKER_TEACHER


def is_teacher_speaker(value: object | None) -> bool:
    """Only teacher-tagged speech may enter the user history path."""
    return normalize_speaker(value) in _USER_SPEAKERS
