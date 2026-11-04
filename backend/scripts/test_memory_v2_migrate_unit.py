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

"""Backup, no-LLM migration, refusal to migrate twice, and restore.

Run from backend/:
  python scripts/test_memory_v2_migrate_unit.py
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.migrate_memory_v2 import backup_memory, main as migrate_main, migrate_database  # noqa: E402


def _fail(message: str) -> None:
    raise AssertionError(message)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed(memory_dir: Path) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "dialogue.json").write_text("[]", encoding="utf-8")
    (memory_dir / "thought.json").write_text("{}", encoding="utf-8")
    (memory_dir / "arona.json").write_text("{}", encoding="utf-8")
    (memory_dir / "life.json").write_text("{}", encoding="utf-8")
    (memory_dir / "life_journal.json").write_text("{}", encoding="utf-8")
    chroma = memory_dir / "chroma"
    chroma.mkdir()
    (chroma / "note.txt").write_text("vector", encoding="utf-8")
    conn = sqlite3.connect(memory_dir / "memory.db")
    conn.execute(
        """
        CREATE TABLE memories (
            key TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            category TEXT,
            updated_at REAL NOT NULL,
            importance INTEGER NOT NULL DEFAULT 5
        )
        """
    )
    conn.execute(
        """
        INSERT INTO memories (key, content, category, updated_at, importance)
        VALUES ('m1', '老师2026年10月28日去了广州。', 'episodic', 100, 5)
        """
    )
    conn.execute(
        """
        INSERT INTO memories (key, content, category, updated_at, importance)
        VALUES ('m2', '老师喜欢蓝色。', 'preference', 100, 5)
        """
    )
    conn.execute(
        """
        CREATE TABLE commitments (
            id TEXT PRIMARY KEY,
            what TEXT NOT NULL,
            rrule TEXT NOT NULL,
            at_time TEXT,
            next_due_at REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO commitments (id, what, rrule, at_time, next_due_at, active, updated_at)
        VALUES ('c1', '老师要阿洛娜每天提醒吃药', 'daily', '08:00', 100, 1, 100)
        """
    )
    conn.execute(
        """
        CREATE TABLE state_items (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            importance INTEGER NOT NULL DEFAULT 5
        )
        """
    )
    conn.execute(
        "INSERT INTO state_items (id, text, created_at, updated_at) VALUES ('s1', '老师在广州', 1, 1)"
    )
    conn.execute(
        """
        CREATE TABLE day_summaries (
            day TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO day_summaries (day, content, created_at) VALUES ('2026-10-28', '近况', 1)"
    )
    conn.commit()
    conn.close()


def _names(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


def test_backup_migrate_restore() -> None:
    print("== backup, no-llm migrate, restore ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        memory_dir = root / "memory"
        _seed(memory_dir)
        original = _sha(memory_dir / "memory.db")
        first = backup_memory(memory_dir, root)
        if _sha(memory_dir / "memory.db") != original:
            _fail("backup-only equivalent must not modify memory.db")
        manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
        listed = {item["path"]: item for item in manifest["files"]}
        if "memory.db" not in listed or "dialogue.json" not in listed:
            _fail(f"manifest missing files: {listed.keys()}")
        if listed["memory.db"]["sha256"] != _sha(first / "memory.db"):
            _fail("manifest sha256 does not match the backup")
        second = backup_memory(memory_dir, root)
        if second == first or first.name == second.name:
            _fail("an existing backup directory must not be overwritten")
        import httpx

        def _boom(*_args: object, **_kwargs: object) -> None:
            _fail("no-llm migration must not open an HTTP client")

        httpx.Client = _boom  # type: ignore[misc]
        before_side = {
            name: _sha(memory_dir / name)
            for name in (
                "dialogue.json",
                "thought.json",
                "arona.json",
                "life.json",
                "life_journal.json",
                "chroma/note.txt",
            )
        }
        migrate_database(memory_dir, first, llm=None, calls_per_day=10)
        names = _names(memory_dir / "memory.db")
        for banned in ("memories", "state_items", "day_summaries"):
            if banned in names:
                _fail(f"v1 table still present: {banned}")
        for required in ("events", "states", "commitments", "scan_state"):
            if required not in names:
                _fail(f"missing v2 table {required}")
        conn = sqlite3.connect(memory_dir / "memory.db")
        summaries = [str(row[0]) for row in conn.execute("SELECT summary FROM events")]
        states = conn.execute("SELECT COUNT(*) FROM states").fetchone()[0]
        commitments = conn.execute("SELECT COUNT(*) FROM commitments").fetchone()[0]
        conn.close()
        if summaries != ["老师喜欢蓝色。"]:
            _fail(f"only the factual memory should be copied: {summaries}")
        if int(states) != 0 or int(commitments) != 0:
            _fail(f"states and commitments must stay empty: {states}, {commitments}")
        for name, digest in before_side.items():
            if _sha(memory_dir / name) != digest:
                _fail(f"unrelated file was rewritten: {name}")
        report = json.loads((first / "migration_report.json").read_text(encoding="utf-8"))
        if int(report["target"]["events"]) != 1:
            _fail("report event count does not match the database")
        if int(report["target"]["skipped_state_items"]) != 1:
            _fail("state rows should be counted as skipped, not imported")
        if int(report["target"]["skipped_non_facts"]) != 1:
            _fail("episodic rows should be counted as skipped")
        if int(report["llm_calls"]) != 0:
            _fail("fact-only migration must not call a model")
        try:
            migrate_database(memory_dir, first, llm=None, calls_per_day=10)
        except SystemExit as exc:
            if "restore" not in str(exc):
                _fail(f"repeat migration should mention --restore: {exc}")
        else:
            _fail("repeat migration must be refused")
        from scripts.migrate_memory_v2 import restore_memory

        restore_memory(first, memory_dir)
        if "memories" not in _names(memory_dir / "memory.db"):
            _fail("restore should bring the v1 memories table back")
        if not (first / "memory.db").is_file():
            _fail("restore must keep the backup")
    print("  ok")


def test_backup_only_cli() -> None:
    print("== backup-only cli ==")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        memory_dir = root / "memory"
        _seed(memory_dir)
        before = _sha(memory_dir / "memory.db")
        migrate_main(["--backup-only", "--data-dir", str(root), "--no-check-running"])
        if _sha(memory_dir / "memory.db") != before:
            _fail("cli backup-only modified memory.db")
        if not (root / "memory_v1_backup" / "manifest.json").is_file():
            _fail("cli backup did not write manifest.json")
    print("  ok")


def _seed_old_states(memory_dir: Path) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(memory_dir / "memory.db")
    conn.execute(
        """
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            summary TEXT NOT NULL,
            occurred_at REAL NOT NULL,
            recorded_at REAL NOT NULL,
            importance INTEGER NOT NULL,
            source_turn TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO events (id, summary, occurred_at, recorded_at, importance) "
        "VALUES ('e1', '老师喜欢蓝色。', 1, 1, 5)"
    )
    conn.execute(
        """
        CREATE TABLE states (
            id INTEGER PRIMARY KEY,
            key TEXT,
            value TEXT,
            valid_from REAL,
            valid_until REAL,
            importance INTEGER,
            recorded_at REAL
        )
        """
    )
    conn.execute(
        "CREATE TABLE state_keys (key TEXT PRIMARY KEY, first_seen REAL)"
    )
    conn.execute("INSERT INTO state_keys (key, first_seen) VALUES ('location', 1)")
    rows = [
        ("location", "老师人在广州", 10, None, 8, 20),
        ("location", "老师人在上海", 11, None, 9, 15),
        ("location", "老师人在北京", 12, None, 9, 30),
        ("routine", "老师保持远程工作", 1, 100, 7, 10),
        ("mood", "老师心情平稳", 1, None, 6, 10),
        ("health", "老师身体稳定", 5, None, 7, 8),
    ]
    conn.executemany(
        """
        INSERT INTO states (key, value, valid_from, valid_until, importance, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def test_states_rebuild() -> None:
    print("== rebuild states ==")
    from scripts.migrate_memory_v2_states import main as states_main

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        memory_dir = root / "memory"
        _seed_old_states(memory_dir)
        before = _sha(memory_dir / "memory.db")
        states_main(["--backup-only", "--data-dir", str(root), "--no-check-running"])
        if _sha(memory_dir / "memory.db") != before:
            _fail("states backup-only modified memory.db")
        states_main(["--data-dir", str(root), "--no-check-running"])
        conn = sqlite3.connect(memory_dir / "memory.db")
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(states)")}
        kept = {
            str(row[0]): (str(row[1]), float(row[2]), float(row[3]), int(row[4]))
            for row in conn.execute(
                "SELECT key, value, created_at, updated_at, active FROM states"
            )
        }
        events = conn.execute("SELECT summary FROM events").fetchone()
        names = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        conn.close()
        if "updated_at" not in columns or "created_at" not in columns:
            _fail(f"new states columns missing: {columns}")
        if "state_keys" in names:
            _fail("state_keys should be dropped")
        if set(kept) != {"location", "health"}:
            _fail(f"wrong keys kept: {kept}")
        if kept["location"][0] != "老师人在北京" or kept["location"][1] != 12 or kept["location"][2] != 30:
            _fail(f"location should keep the newest high-importance row: {kept['location']}")
        if kept["health"][0] != "老师身体稳定" or kept["health"][3] != 1:
            _fail(f"health row was not mapped: {kept['health']}")
        if events is None or str(events[0]) != "老师喜欢蓝色。":
            _fail("events must stay untouched")
        report_path = root / "memory_state_backup_20260101T000000"
        reports = list(root.glob("memory_state_backup*/states_migration_report.json"))
        if len(reports) != 1:
            _fail(f"expected one states report, found {reports}")
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        if report["kept"] != 2 or report["source_rows"] != 6 or report["deduped"] != 2:
            _fail(f"report counts are wrong: {report}")
        del report_path
        try:
            states_main(["--data-dir", str(root), "--no-check-running"])
        except SystemExit as exc:
            if "restore" not in str(exc):
                _fail(f"repeat states migration should mention --restore: {exc}")
        else:
            _fail("repeat states migration must be refused")
        backup = reports[0].parent
        states_main(["--restore", str(backup), "--data-dir", str(root), "--no-check-running"])
        restored = _columns_states(memory_dir / "memory.db")
        if "updated_at" in restored:
            _fail("restore should bring back the old states table")
        conn = sqlite3.connect(memory_dir / "memory.db")
        count = int(conn.execute("SELECT COUNT(*) FROM states").fetchone()[0])
        conn.close()
        if count != 6:
            _fail(f"restore should bring all six rows back, got {count}")
    print("  ok")


def _columns_states(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("PRAGMA table_info(states)").fetchall()
    finally:
        conn.close()
    return {str(row[1]) for row in rows}


def main() -> None:
    test_backup_migrate_restore()
    test_backup_only_cli()
    test_states_rebuild()
    print("all migration checks passed")


if __name__ == "__main__":
    main()
