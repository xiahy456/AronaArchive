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

"""One open QQ round: every inbound piece, what was already sent, and the current draft."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..orchestrator import ChatPlan


@dataclass(frozen=True)
class QqPiece:
    text: str
    images: tuple[Any, ...] = ()
    message_id: str = ""


@dataclass
class QqTurn:
    inputs: list[QqPiece] = field(default_factory=list)
    sent: list[str] = field(default_factory=list)
    carry: str = ""
    draft: ChatPlan | None = None
    draft_covers: int = 0

    def pending(self) -> bool:
        return any((piece.text or "").strip() or piece.images for piece in self.inputs)

    def draft_current(self) -> bool:
        return self.draft is not None and self.draft_covers == len(self.inputs)
