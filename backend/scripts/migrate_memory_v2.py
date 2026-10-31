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

"""Copy v1 memory files aside, then rebuild memory.db from factual memories only.

State rows, commitments, day summaries, and every other file under data/memory/
stay out of the new database. dialogue.json, chroma/, and the life files are
not rewritten.

Run from backend/:
  python scripts/migrate_memory_v2.py --backup-only
  python scripts/migrate_memory_v2.py
  python scripts/migrate_memory_v2.py --restore data/memory_v1_backup_20261031T014000
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import socket
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import BACKEND_DIR, load_config  # noqa: E402
from app.memory_v2.db import Database  # noqa: E402
from app.memory_v2.util import clamp_importance, new_id  # noqa: E402
from app.query_time import parse_content_datetimes  # noqa: E402

FILE_NAMES = (
    "memory.db",
    "dialogue.json",
    "thought.json",
    "arona.json",
    "life.json",
    "life_journal.json",
)
V1_TABLES = ("memories", "state_items", "commitments", "day_summaries")
# v1 里 episodic / emotional 不是事实。缺省和未知类别按 other 记，属于事实。
NON_FACT_CATEGORIES = {"episodic", "emotional"}


def _fail(message: str, code: int = 1) -> None:
    del code
    print(message, file=sys.stderr)
    raise SystemExit(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_names(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


def _count_tables(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not path.is_file():
        return counts
    names = _table_names(path)
    conn = sqlite3.connect(str(path))
    try:
        for table in V1_TABLES:
            if table not in names:
                counts[table] = 0
                continue
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()
    return counts


def _integrity(path: Path) -> bool:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()
    return bool(row and str(row[0]).lower() == "ok")


def _server_is_up(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=0.3):
            return True
    except OSError:
        return False


def _iter_files(root: Path) -> list[Path]:
    found: list[Path] = []
    if not root.exists():
        return found
    if root.is_file():
        return [root]
    for path in root.rglob("*"):
        if path.is_file():
            found.append(path)
    return found


def backup_memory(memory_dir: Path, data_dir: Path) -> Path:
    dest_root = data_dir / "memory_v1_backup"
    if dest_root.exists():
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        dest_root = data_dir / f"memory_v1_backup_{stamp}"
        print(f"备份目录已存在，改用 {dest_root}")
    dest_root.mkdir(parents=True)
    copied: list[tuple[Path, Path]] = []
    for name in FILE_NAMES:
        source = memory_dir / name
        if not source.is_file():
            continue
        target = dest_root / name
        shutil.copy2(source, target)
        copied.append((source, target))
    chroma = memory_dir / "chroma"
    if chroma.is_dir():
        shutil.copytree(chroma, dest_root / "chroma")
        for path in _iter_files(dest_root / "chroma"):
            source = memory_dir / path.relative_to(dest_root)
            copied.append((source, path))
    for source, target in copied:
        if source.stat().st_size != target.stat().st_size:
            _fail(f"备份大小不一致: {target}")
    db_copy = dest_root / "memory.db"
    if db_copy.is_file() and not _integrity(db_copy):
        _fail(f"备份 integrity_check 失败: {db_copy}")
    files = []
    for path in _iter_files(dest_root):
        files.append(
            {
                "path": path.relative_to(dest_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    manifest = {
        "backed_up_at": datetime.now().isoformat(timespec="seconds"),
        "files": files,
        "counts": _count_tables(db_copy) if db_copy.is_file() else {},
    }
    (dest_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"备份完成 {dest_root}")
    return dest_root


def restore_memory(backup_dir: Path, memory_dir: Path) -> None:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file():
        _fail(f"找不到 manifest.json: {backup_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest.get("files") or []:
        relative = str(item.get("path") or "")
        if relative == "manifest.json":
            continue
        source = backup_dir / relative
        if not source.is_file():
            _fail(f"备份缺少文件: {source}")
        digest = _sha256(source)
        if digest != str(item.get("sha256") or ""):
            _fail(f"SHA256 不一致: {relative}")
        target = memory_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print(f"已从 {backup_dir} 还原到 {memory_dir}")


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _is_fact(category: str) -> bool:
    return (category or "").strip().lower() not in NON_FACT_CATEGORIES


def _occurred(content: str, updated_at: float) -> tuple[float, bool]:
    found = parse_content_datetimes(content or "")
    if found:
        return found[0].timestamp(), True
    return float(updated_at or 0), False


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["kind", "id", "content", "reason"]
        )
        writer.writeheader()
        writer.writerows(rows)


def migrate_database(
    memory_dir: Path,
    backup_dir: Path,
    *,
    llm: Any = None,
    calls_per_day: int = 0,
) -> dict[str, Any]:
    del llm, calls_per_day
    source = memory_dir / "memory.db"
    if not source.is_file():
        _fail(f"找不到 {source}")
    if "events" in _table_names(source):
        _fail("memory.db 已经是 v2（存在 events 表）。不要重复迁移。回切请用 --restore。")
    new_path = memory_dir / "memory.db.new"
    fts_path = memory_dir / "events_fts"
    if new_path.exists():
        new_path.unlink()
    if fts_path.exists():
        if fts_path.is_dir():
            shutil.rmtree(fts_path)
        else:
            fts_path.unlink()
    database = Database(new_path, fts_path)
    stats = {
        "memories": 0,
        "facts": 0,
        "events": 0,
        "states": 0,
        "commitments": 0,
        "skipped_non_facts": 0,
        "skipped_state_items": 0,
        "skipped_commitments": 0,
        "discarded_summaries": 0,
        "llm_calls": 0,
        "review": 0,
    }

    src = sqlite3.connect(str(source))
    src.row_factory = sqlite3.Row
    try:
        names = {str(row[0]) for row in src.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()}
        if "memories" in names:
            cols = _columns(src, "memories")
            for row in src.execute("SELECT * FROM memories"):
                stats["memories"] += 1
                content = str(row["content"] or "").strip()
                category = str(row["category"] or "") if "category" in cols else ""
                if not content or not _is_fact(category):
                    stats["skipped_non_facts"] += 1
                    continue
                updated = float(row["updated_at"] or 0) if "updated_at" in cols else 0.0
                occurred, _dated = _occurred(content, updated)
                importance, _changed = clamp_importance(
                    row["importance"] if "importance" in cols else 5
                )
                _insert_event(
                    database,
                    summary=content,
                    occurred_at=occurred,
                    recorded_at=updated or occurred,
                    importance=importance,
                    source_turn=str(row["key"] if "key" in cols else ""),
                )
                stats["facts"] += 1
        if "state_items" in names:
            stats["skipped_state_items"] = int(
                src.execute("SELECT COUNT(*) FROM state_items").fetchone()[0]
            )
        if "commitments" in names:
            stats["skipped_commitments"] = int(
                src.execute("SELECT COUNT(*) FROM commitments").fetchone()[0]
            )
        if "day_summaries" in names:
            stats["discarded_summaries"] = int(
                src.execute("SELECT COUNT(*) FROM day_summaries").fetchone()[0]
            )
    finally:
        src.close()

    def _counts(conn: sqlite3.Connection) -> tuple[int, int, int]:
        events = int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        states = int(conn.execute("SELECT COUNT(*) FROM states").fetchone()[0])
        commitments = int(conn.execute("SELECT COUNT(*) FROM commitments").fetchone()[0])
        return events, states, commitments

    events, states, commitments = database.call(_counts)
    if events != stats["facts"] or states != 0 or commitments != 0:
        _fail(
            f"新库应为 {stats['facts']} 条事实、0 条状态、0 条承诺，"
            f"实际 events={events} states={states} commitments={commitments}，未替换原库"
        )
    if not _integrity(new_path):
        _fail("memory.db.new integrity_check 失败，未替换原库")
    database.close()
    os_replace(new_path, memory_dir / "memory.db")
    stats["events"] = events
    stats["states"] = states
    stats["commitments"] = commitments
    _write_csv(backup_dir / "migration_review.csv", [])
    report = {
        "source_counts": _count_tables(backup_dir / "memory.db"),
        "target": stats,
        "review_rows": 0,
        "llm_calls": 0,
        "untouched": [
            "dialogue.json",
            "thought.json",
            "arona.json",
            "life.json",
            "life_journal.json",
            "chroma/",
        ],
    }
    (backup_dir / "migration_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(stats, ensure_ascii=False))
    return report


def os_replace(source: Path, target: Path) -> None:
    import os

    os.replace(source, target)


def _insert_event(
    database: Database,
    *,
    summary: str,
    occurred_at: float,
    recorded_at: float,
    importance: int,
    source_turn: str,
) -> None:
    event_id = new_id("ev")

    def _write(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO events (
                id, summary, occurred_at, recorded_at, importance, source_turn
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, summary, occurred_at, recorded_at, importance, source_turn),
        )
        database.fts_add(conn, event_id, summary)

    database.call(_write)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="备份并迁移记忆库到 memory_v2")
    parser.add_argument("--backup-only", action="store_true")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="保留的空开关。迁移只复制事实记忆，不会调用模型。",
    )
    parser.add_argument("--restore", default="")
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--check-running", action="store_true", default=True)
    parser.add_argument("--no-check-running", action="store_false", dest="check_running")
    args = parser.parse_args(argv)
    config = load_config()
    if args.data_dir:
        data_dir = Path(args.data_dir)
        memory_dir = data_dir / "memory"
    else:
        data_dir = BACKEND_DIR / "data"
        memory_dir = config.resolve_path("data/memory")
    memory_dir.mkdir(parents=True, exist_ok=True)
    if args.check_running and not args.data_dir:
        host = config.server.host or "127.0.0.1"
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        if _server_is_up(host, config.server.port):
            _fail("后端似乎仍在运行。请先停掉再迁移。")
    if args.restore:
        restore_memory(Path(args.restore), memory_dir)
        return
    dest = backup_memory(memory_dir, data_dir)
    if args.backup_only:
        return
    try:
        migrate_database(memory_dir, dest)
    except SystemExit:
        print(f"迁移未完成。原库未替换。临时文件与备份保留在 {dest}", file=sys.stderr)
        raise
    print("迁移完成。v1 代码此后无法读取 data/memory/memory.db。")


if __name__ == "__main__":
    main()
