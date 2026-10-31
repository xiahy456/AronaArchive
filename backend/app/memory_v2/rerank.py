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

"""Optional local cross-encoder. Missing weights keep RRF order."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_warned = False

DEFAULT_RERANK_PATH = Path("../models/bge-reranker-base")


def rerank_missing_reason(model_path: Path) -> str | None:
    if Path(model_path).is_dir():
        return None
    return (
        f"memory_v2 reranker not found: {model_path}. "
        "Retrieval keeps RRF order."
    )


class LocalReranker:
    def __init__(self, model_path: Path) -> None:
        missing = rerank_missing_reason(model_path)
        if missing is not None:
            raise FileNotFoundError(missing)
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(str(model_path))

    def order(self, query: str, texts: list[str]) -> list[int]:
        if not texts:
            return []
        pairs = [(query, text) for text in texts]
        scores = self._model.predict(pairs)
        ranked = sorted(range(len(texts)), key=lambda index: float(scores[index]), reverse=True)
        return ranked


def maybe_rerank(
    *,
    enabled: bool,
    model_path: Path,
    query: str,
    texts: list[str],
    reranker: LocalReranker | None = None,
) -> tuple[list[int], LocalReranker | None]:
    """Return indexes into texts. Logs the missing-weight warning once."""
    global _warned
    order = list(range(len(texts)))
    if not enabled or not texts:
        return order, reranker
    if reranker is None:
        missing = rerank_missing_reason(model_path)
        if missing is not None:
            if not _warned:
                logger.warning("%s", missing)
                _warned = True
            return order, None
        try:
            reranker = LocalReranker(model_path)
        except Exception:
            if not _warned:
                logger.exception("memory_v2 reranker load failed; keeping RRF order")
                _warned = True
            return order, None
    try:
        return reranker.order(query, texts), reranker
    except Exception:
        logger.exception("memory_v2 rerank failed; keeping RRF order")
        return order, reranker
