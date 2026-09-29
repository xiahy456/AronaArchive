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

"""Listen-session turn taking: buffer, speaker filter, silence EOT."""

from .buffer import TurnBuffer
from .rules import looks_incomplete
from .speaker import SPEAKER_OTHER, SPEAKER_TEACHER, SPEAKER_UNKNOWN, is_teacher_speaker

__all__ = [
    "SPEAKER_OTHER",
    "SPEAKER_TEACHER",
    "SPEAKER_UNKNOWN",
    "TurnBuffer",
    "is_teacher_speaker",
    "looks_incomplete",
]
