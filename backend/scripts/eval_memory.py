#!/usr/bin/env python3
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

"""Multi-turn memory scenarios that do not call a model.

Run from backend/:
  python scripts/eval_memory.py --json-out data/memory/eval_memory.json
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.life.impulse import maybe_offer_commitment  # noqa: E402
from app.life.state import Impulse, InnerState  # noqa: E402
from app.life.thought.sources import SourceContext, select_sources  # noqa: E402
from app.life.thought.store import PendingTrigger, ThoughtLedger  # noqa: E402
from app.memory.commitment import CommitmentStore  # noqa: E402
from app.memory.state import StateItem, StateStore  # noqa: E402
from app.memory.store import MemoryStore  # noqa: E402
from app.config import AppConfig  # noqa: E402
from app.planner.prompts import build_planner_user_message  # noqa: E402
from app.prompt import format_state_block  # noqa: E402


def _check(name: str, ok: bool, detail: str, results: list[dict]) -> None:
    results.append({"name": name, "ok": ok, "detail": detail})
    print(f"{'ok' if ok else 'FAIL'} {name}: {detail}")


def _shenzhen_stays(results: list[dict]) -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = StateStore(Path(tmp) / "memory.db")
        now = datetime(2026, 10, 27, 11, 0).timestamp()
        store.upsert(
            StateItem(
                id="place",
                text="老师2026年10月27日在深圳",
                created_at=now,
                updated_at=now,
                importance=7,
            )
        )
        unrelated = build_planner_user_message(
            user_text="这段代码报错了",
            history=[{"role": "user", "content": "我今天去深圳"}],
            memories=[],
            knowledge=[],
            state_block=format_state_block(store.texts()),
        )
        ok = "老师2026年10月27日在深圳" in unrelated and "所在地" not in unrelated
        _check("shenzhen stays on an unrelated turn", ok, "state sentence is resident", results)
        thought = select_sources(
            PendingTrigger(kind="spontaneous"),
            datetime(2026, 10, 27, 12, 0),
            InnerState(),
            ThoughtLedger(),
            SourceContext(state_lines=tuple(store.texts())),
        ).text
        thought_ok = "【老师当前情况】" in thought and "老师2026年10月27日在深圳" in thought
        _check("shenzhen stays while thinking", thought_ok, "thinking sees the sentence", results)
        block = format_state_block(store.texts())
        chatter = ["嗯", "好", "在吗", "哈哈", "先这样"]
        same = all(
            block in build_planner_user_message(
                user_text=text,
                history=[],
                memories=[],
                knowledge=[],
                state_block=block,
            )
            for text in chatter
        )
        _check("state block survives five unrelated turns", same, block, results)
        plain = all(line.startswith("- ") and "：" not in line for line in block.splitlines()[1:])
        _check("state lines have no labels", plain and block.startswith("【老师当前情况】"), block, results)


def _medicine_is_due(results: list[dict]) -> None:
    class _Engine:
        def __init__(self) -> None:
            self.state = InnerState()
            self.saved = False

        class _Store:
            def save(self, state) -> None:
                return None

        store = _Store()

    created = datetime(2026, 10, 27, 7, 0)
    morning = datetime(2026, 10, 27, 8, 5)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        commitments = CommitmentStore(Path(tmp) / "memory.db")
        commitments.apply(
            [
                {
                    "op": "create",
                    "id": "meds",
                    "what": "提醒老师吃药",
                    "rrule": "daily",
                    "at_time": "08:00",
                }
            ],
            created,
        )

        class _State:
            def __init__(self) -> None:
                self.commitment_store = commitments
                self.config = AppConfig()
                self.life = _Engine()

        holder = _State()
        maybe_offer_commitment(holder, morning)
        impulse = holder.life.state.pending_impulse
        ok = isinstance(impulse, Impulse) and impulse.kind == "commitment" and impulse.source_id == "meds"
        _check("medicine reminder becomes an impulse", ok, getattr(impulse, "hint", ""), results)
        commitments.mark_fired("meds", morning)
        restarted = CommitmentStore(Path(tmp) / "memory.db")
        again = restarted.due(morning)
        _check(
            "medicine does not fire twice after restart",
            not again,
            str([item.id for item in again]),
            results,
        )


def _trip_is_retrievable(results: list[dict]) -> None:
    cfg = AppConfig()
    cfg.memory.rerank_enabled = False
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = MemoryStore(cfg, db_path=Path(tmp) / "memory.db")
        store.upsert(
            "trip",
            "老师2026年10月27日去了深圳",
            category="episodic",
            entities=["深圳"],
            importance=6,
        )
        store._vector_candidates = lambda embedding, limit: {}  # type: ignore[method-assign]
        store._fts_candidate_keys = lambda query, limit: []  # type: ignore[method-assign]
        store._score_fts_keys = lambda keys, embedding: {}  # type: ignore[method-assign]
        hits = store.retrieve_entries(
            "深圳",
            top_k=3,
            query_embedding=[0.2, 0.1],
            include_time=False,
            now=datetime(2026, 10, 27, 12, 0),
        )
        contents = [item["content"] for item in hits]
        ok = any("深圳" in text for text in contents)
        _check("shenzhen trip is retrievable by entity", ok, str(contents), results)


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline memory scenario checks")
    parser.add_argument("--json-out", default="", help="Write the assertion report as JSON")
    args = parser.parse_args()
    results: list[dict] = []
    _shenzhen_stays(results)
    _medicine_is_due(results)
    _trip_is_retrievable(results)
    if args.json_out:
        out = Path(args.json_out)
        if not out.is_absolute():
            out = (ROOT / out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = [item for item in results if not item["ok"]]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
