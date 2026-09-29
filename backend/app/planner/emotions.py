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

"""Arona Spine expression whitelist (English values only)."""

from __future__ import annotations

DEFAULT_EMOTION = "normal"

# Keep in sync with frontend AronaSpineAssets/README.md (英文值 column).
EMOTION_WHITELIST: frozenset[str] = frozenset(
    {
        "normal",
        "curious",
        "smile",
        "worried",
        "angry",
        "angry_shame",
        "disgusted",
        "disgusted_surprised",
        "disgusted_worried",
        "frustration",
        "like",
        "very_happy",
        "enjoy",
        "complaint",
        "unwilling",
        "shy",
        "shout",
        "want",
        "confident_serious",
        "sleep_very_content",
        "sleep_question",
        "confident",
        "disappointed",
        "disappointed_disgusted",
        "very_surprised",
        "dizzy",
        "surprise",
        "surprise_very_happy",
        "sleep",
    }
)

EMOTION_WHITELIST_CSV = ", ".join(sorted(EMOTION_WHITELIST))


def normalize_emotion(value: object | None) -> str:
    """Return a whitelist emotion; unknown/missing -> normal."""
    if not isinstance(value, str):
        return DEFAULT_EMOTION
    key = value.strip().lower()
    if key in EMOTION_WHITELIST:
        return key
    return DEFAULT_EMOTION
