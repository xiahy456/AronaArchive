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

"""Rolling transcript buffer for a listen session."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .speaker import is_teacher_speaker, normalize_speaker

from ..image_input import ImagePayload


@dataclass
class TranscriptSegment:
    segment_id: str
    text: str
    speaker: str
    silence_ms: int
    received_at: float = field(default_factory=time.time)


class TurnBuffer:
    def __init__(self) -> None:
        self.listening: bool = False
        self.last_arona_at: float = 0.0
        self._segments: list[TranscriptSegment] = []
        self.latest_image: ImagePayload | None = None

    def set_listening(self, on: bool) -> None:
        self.listening = bool(on)
        if on:
            self._segments.clear()
            self.latest_image = None

    def note_arona_spoke(self, when: float | None = None) -> None:
        self.last_arona_at = float(when if when is not None else time.time())

    def seconds_since_arona(self, now: float | None = None) -> float | None:
        if self.last_arona_at <= 0:
            return None
        stamp = float(now if now is not None else time.time())
        return max(0.0, stamp - self.last_arona_at)

    def push(
        self,
        *,
        text: str,
        speaker: object = "teacher",
        segment_id: str = "",
        silence_ms: int = 0,
        image: ImagePayload | None = None,
    ) -> TranscriptSegment | None:
        cleaned = (text or "").strip()
        if not cleaned:
            return None
        tag = normalize_speaker(speaker)
        if not is_teacher_speaker(tag):
            return None
        segment = TranscriptSegment(
            segment_id=str(segment_id or ""),
            text=cleaned,
            speaker=tag,
            silence_ms=max(0, int(silence_ms or 0)),
        )
        self._segments.append(segment)
        if image is not None:
            self.latest_image = image
        return segment

    def prepend(self, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        self._segments.insert(
            0,
            TranscriptSegment(segment_id="", text=cleaned, speaker="teacher", silence_ms=0),
        )

    def joined(self) -> str:
        return "".join(item.text for item in self._segments).strip()

    def last_text(self) -> str:
        if not self._segments:
            return ""
        return self._segments[-1].text

    def drain(self) -> str:
        text = self.joined()
        self._segments.clear()
        return text

    def pop_image(self) -> ImagePayload | None:
        image = self.latest_image
        self.latest_image = None
        return image

    def clear(self) -> None:
        self._segments.clear()
        self.latest_image = None

    def __len__(self) -> int:
        return len(self._segments)
