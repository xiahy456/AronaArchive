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

"""Rebuild states as one row per key. Keep only live rows with importance > 6.

Other tables and the rest of data/memory/ are left in place. Run from backend/:

  python scripts/migrate_memory_v2_states.py --backup-only
  python scripts/migrate_memory_v2_states.py
  python scripts/migrate_memory_v2_states.py --restore data/memory_state_backup
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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

_NEW_STATES = """
CREATE TABLE states_new (
    key        TEXT NOT NULL PRIMARY KEY,
    value      TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1
);
"""


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _columns(path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(path))
    try:
        found = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if found is None:
            return set()
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    finally:
        conn.close()
    return {str(row[1]) for row in rows}


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


def backup_database(memory_dir: Path, data_dir: Path) -> Path:
    source = memory_dir / "memory.db"
    if not source.is_file():
        _fail(f"找不到 {source}")
    dest_root = data_dir / "memory_state_backup"
    if dest_root.exists():
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        dest_root = data_dir / f"memory_state_backup_{stamp}"
        suffix = 1
        while dest_root.exists():
            dest_root = data_dir / f"memory_state_backup_{stamp}_{suffix}"
            suffix += 1
        print(f"备份目录已存在，改用 {dest_root}")
    dest_root.mkdir(parents=True)
    target = dest_root / "memory.db"
    shutil.copy2(source, target)
    if source.stat().st_size != target.stat().st_size:
        _fail(f"备份大小不一致: {target}")
    if not _integrity(target):
        _fail(f"备份 integrity_check 失败: {target}")
    conn = sqlite3.connect(str(target))
    try:
        count = int(conn.execute("SELECT COUNT(*) FROM states").fetchone()[0])
    except sqlite3.OperationalError:
        count = 0
    finally:
        conn.close()
    manifest = {
        "backed_up_at": datetime.now().isoformat(timespec="seconds"),
        "files": [
            {
                "path": "memory.db",
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            }
        ],
        "states": count,
    }
    (dest_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"备份完成 {dest_root}")
    return dest_root


def restore_database(backup_dir: Path, memory_dir: Path) -> None:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file():
        _fail(f"找不到 manifest.json: {backup_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = backup_dir / "memory.db"
    if not source.is_file():
        _fail(f"备份缺少 memory.db: {backup_dir}")
    listed = {str(item.get("path")): item for item in manifest.get("files") or []}
    expected = str((listed.get("memory.db") or {}).get("sha256") or "")
    if _sha256(source) != expected:
        _fail("SHA256 不一致: memory.db")
    memory_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, memory_dir / "memory.db")
    print(f"已从 {backup_dir} 还原 memory.db 到 {memory_dir}")


def migrate_states(memory_dir: Path, backup_dir: Path) -> dict[str, Any]:
    source = memory_dir / "memory.db"
    if not source.is_file():
        _fail(f"找不到 {source}")
    columns = _columns(source, "states")
    if not columns:
        _fail(f"{source} 没有 states 表")
    if "updated_at" in columns:
        _fail("states 已经是新结构（有 updated_at）。不要重复迁移。回切请用 --restore。")
    for required in ("key", "value", "valid_from", "valid_until", "importance", "recorded_at"):
        if required not in columns:
            _fail(f"旧 states 表缺少 {required}，未替换原库")
    new_path = memory_dir / "memory.db.new"
    if new_path.exists():
        new_path.unlink()
    shutil.copy2(source, new_path)
    conn = sqlite3.connect(str(new_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    stored = 0
    try:
        total = int(conn.execute("SELECT COUNT(*) FROM states").fetchone()[0])
        rows = conn.execute(
            """
            SELECT key, value, valid_from, recorded_at, importance
            FROM states
            WHERE importance > 6 AND valid_until IS NULL
            ORDER BY importance DESC, recorded_at DESC
            """
        ).fetchall()
        kept: dict[str, sqlite3.Row] = {}
        deduped = 0
        for row in rows:
            key = str(row["key"] or "").strip()
            value = str(row["value"] or "").strip()
            if not key or not value:
                continue
            if key in kept:
                deduped += 1
                continue
            kept[key] = row
        conn.execute("BEGIN")
        conn.execute(_NEW_STATES)
        conn.executemany(
            """
            INSERT INTO states_new (key, value, created_at, updated_at, active)
            VALUES (?, ?, ?, ?, 1)
            """,
            [
                (
                    str(row["key"]).strip(),
                    str(row["value"]).strip(),
                    float(row["valid_from"] or 0),
                    float(row["recorded_at"] or 0),
                )
                for row in kept.values()
            ],
        )
        conn.execute("DROP TABLE states")
        conn.execute("ALTER TABLE states_new RENAME TO states")
        conn.execute("DROP TABLE IF EXISTS state_keys")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_states_active
            ON states(active, updated_at DESC)
            """
        )
        conn.execute("COMMIT")
        stored = int(conn.execute("SELECT COUNT(*) FROM states").fetchone()[0])
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        _fail("重建 states 失败，未替换原库。memory.db.new 已保留。")
    finally:
        try:
            conn.close()
        except sqlite3.ProgrammingError:
            pass
    if stored != len(kept):
        _fail(f"states ({stored}) 与保留条数 ({len(kept)}) 不一致，未替换原库")
    if not _integrity(new_path):
        _fail("memory.db.new integrity_check 失败，未替换原库")
    os.replace(new_path, source)
    report = {
        "source_rows": total,
        "kept": len(kept),
        "dropped": total - len(kept),
        "deduped": deduped,
    }
    (backup_dir / "states_migration_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="把 states 表重建成覆盖式单表")
    parser.add_argument("--backup-only", action="store_true")
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
        restore_database(Path(args.restore), memory_dir)
        return
    dest = backup_database(memory_dir, data_dir)
    if args.backup_only:
        return
    try:
        migrate_states(memory_dir, dest)
    except SystemExit:
        print(f"迁移未完成。原库未替换。临时文件与备份保留在 {dest}", file=sys.stderr)
        raise
    print("states 表已重建。importance 不超过 6 的行，以及已经关闭的行，没有保留。")


if __name__ == "__main__":
    main()
