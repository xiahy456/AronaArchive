# Copyright 2026 xia_hy456. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""JSON persistence for Arona inner state."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .state import InnerState

logger = logging.getLogger(__name__)


class LifeStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> InnerState:
        if not self.path.is_file():
            return InnerState()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("life load failed path=%s", self.path)
            return InnerState()
        if not isinstance(raw, dict):
            return InnerState()
        return InnerState.from_dict(raw)

    def save(self, state: InnerState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)
