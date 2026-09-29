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

"""JSON persistence for relationship climate."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .state import RelationshipState

logger = logging.getLogger(__name__)


class RelationshipStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> RelationshipState:
        if not self.path.is_file():
            return RelationshipState()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("relationship load failed path=%s", self.path)
            return RelationshipState()
        if not isinstance(raw, dict):
            return RelationshipState()
        return RelationshipState.from_dict(raw)

    def save(self, state: RelationshipState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)
