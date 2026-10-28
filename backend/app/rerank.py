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

"""Local cross-encoder reranker. Missing weights degrade to fusion order."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def rerank_missing_reason(model_path: Path) -> str | None:
    path = Path(model_path)
    if path.is_dir():
        return None
    return (
        f"Local reranker not found: {path}. "
        "Place bge-reranker-base under models/. Retrieval keeps RRF order until then."
    )


class LocalBgeReranker:
    def __init__(self, model_path: Path) -> None:
        missing = rerank_missing_reason(model_path)
        if missing is not None:
            raise FileNotFoundError(missing)
        from sentence_transformers import CrossEncoder

        logger.info("Loading local reranker from %s", model_path)
        self._model = CrossEncoder(str(model_path), local_files_only=True)

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        pairs = [(query, doc) for doc in docs]
        scores = self._model.predict(pairs, show_progress_bar=False)
        return [float(score) for score in scores]
