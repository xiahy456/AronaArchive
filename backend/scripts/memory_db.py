"""Interactive SQL / CRUD helper for AronaArchive memory.db."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Prefer UTF-8 on Windows consoles so Chinese memory content prints correctly.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

from app.config import load_config  # noqa: E402
from app.memory.store import MemoryStore, _tokenize  # noqa: E402

WRITE_HINT = "Hint: if you changed `memories`, run .sync_fts to rebuild FTS."


def resolve_db(path: str | None) -> Path:
    if not path:
        return load_config().memory_db_abs_path
    p = Path(path)
    if not p.is_absolute():
        p = (BACKEND_DIR / p).resolve()
    return p


def make_store(db_path: Path) -> MemoryStore:
    config = load_config()
    return MemoryStore(config, db_path=db_path)


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def format_ts(value: object) -> str:
    try:
        return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(value)


def print_rows(rows: list[sqlite3.Row], *, format_updated: bool = False) -> None:
    if not rows:
        print("(0 rows)")
        return
    columns = list(rows[0].keys())
    table: list[list[str]] = []
    for row in rows:
        cells: list[str] = []
        for col in columns:
            val = row[col]
            if format_updated and col == "updated_at":
                cells.append(format_ts(val))
            else:
                cells.append("" if val is None else str(val))
        table.append(cells)

    widths = [len(c) for c in columns]
    for cells in table:
        for i, cell in enumerate(cells):
            widths[i] = max(widths[i], len(cell))

    header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(columns))
    sep = "-+-".join("-" * w for w in widths)
    print(header)
    print(sep)
    for cells in table:
        print(" | ".join(cells[i].ljust(widths[i]) for i in range(len(columns))))
    print(f"({len(rows)} rows)")


def execute_sql(conn: sqlite3.Connection, sql: str) -> None:
    sql = sql.strip()
    if not sql:
        return
    try:
        cur = conn.execute(sql)
    except sqlite3.Error as exc:
        print(f"SQL error: {exc}", file=sys.stderr)
        return

    if cur.description is not None:
        rows = cur.fetchall()
        print_rows(rows)
    else:
        conn.commit()
        print(f"{cur.rowcount} rows affected")
        lowered = sql.lstrip().lower()
        if any(lowered.startswith(kw) for kw in ("insert", "update", "delete", "replace")):
            if "memories" in lowered and "memories_fts" not in lowered:
                print(WRITE_HINT)


def sync_fts(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT key, content FROM memories").fetchall()
    conn.execute("DELETE FROM memories_fts")
    for row in rows:
        key = row["key"]
        content = row["content"]
        fts_body = _tokenize(f"{key} {content}")
        conn.execute(
            "INSERT INTO memories_fts(key, content) VALUES (?, ?)",
            (key, fts_body),
        )
    conn.commit()
    print(f"Rebuilt memories_fts from {len(rows)} memories.")


def cmd_schema(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
    ).fetchall()
    for row in rows:
        print(row["sql"] + ";")
        print()


def cmd_tables(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
    ).fetchall()
    print_rows(rows)


def print_help() -> None:
    print(
        """Dot commands:
  .help       Show this help
  .quit       Exit REPL
  .tables     List tables
  .schema     Show CREATE statements
  .sync_fts   Rebuild memories_fts from memories (jieba tokenization)

SQL:
  Enter statements ending with ';'. Multi-line input is supported.

CLI examples:
  python scripts/memory_db.py list
  python scripts/memory_db.py upsert favorite_drink "老师喜欢草莓牛奶" --category preference
  python scripts/memory_db.py -c "SELECT * FROM memories;"
"""
    )


def repl(conn: sqlite3.Connection) -> int:
    print(f"Connected to {conn.execute('PRAGMA database_list').fetchone()['file']}")
    print("Type SQL ending with ';' or .help / .quit")
    buffer: list[str] = []
    while True:
        try:
            prompt = "... " if buffer else "sql> "
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            break

        stripped = line.strip()
        if not buffer and stripped.startswith("."):
            cmd = stripped.split()[0].lower()
            if cmd in (".quit", ".exit", ".q"):
                break
            if cmd == ".help":
                print_help()
            elif cmd == ".tables":
                cmd_tables(conn)
            elif cmd == ".schema":
                cmd_schema(conn)
            elif cmd == ".sync_fts":
                sync_fts(conn)
            else:
                print(f"Unknown command: {stripped}. Try .help")
            continue

        buffer.append(line)
        text = "\n".join(buffer).strip()
        if not text.endswith(";"):
            continue
        execute_sql(conn, text)
        buffer.clear()
    return 0


def cmd_list(db_path: Path) -> int:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT key, content, category, updated_at, source FROM memories ORDER BY updated_at DESC"
        ).fetchall()
        print_rows(rows, format_updated=True)
    return 0


def cmd_get(db_path: Path, key: str) -> int:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT key, content, category, updated_at, source FROM memories WHERE key = ?",
            (key,),
        ).fetchall()
        if not rows:
            print(f"No memory with key={key!r}")
            return 1
        print_rows(rows, format_updated=True)
    return 0


def cmd_upsert(
    db_path: Path,
    key: str,
    content: str,
    category: str | None,
    source: str,
) -> int:
    store = make_store(db_path)
    store.upsert(key, content, category=category, source=source)
    print(f"upserted key={key!r}")
    return 0


def cmd_delete(db_path: Path, key: str) -> int:
    store = make_store(db_path)
    store.delete(key)
    print(f"deleted key={key!r}")
    return 0


def cmd_count(db_path: Path) -> int:
    store = make_store(db_path)
    print(store.count())
    return 0


def cmd_retrieve(db_path: Path, query: str, top_k: int) -> int:
    store = make_store(db_path)
    hits = store.retrieve(query, top_k=top_k)
    if not hits:
        print("(0 hits)")
        return 0
    for i, content in enumerate(hits, 1):
        print(f"{i}. {content}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Debug / manage AronaArchive memory.db (SQL REPL + CRUD)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite DB (default: memory.db_path from config.yaml)",
    )
    parser.add_argument(
        "-c",
        "--command",
        default=None,
        help="Execute one SQL statement and exit",
    )

    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="List all memories")

    p_get = sub.add_parser("get", help="Get one memory by key")
    p_get.add_argument("key")

    p_upsert = sub.add_parser("upsert", help="Upsert via MemoryStore (keeps FTS+Chroma in sync)")
    p_upsert.add_argument("key")
    p_upsert.add_argument("content")
    p_upsert.add_argument("--category", default=None)
    p_upsert.add_argument("--source", default="debug")

    p_delete = sub.add_parser("delete", help="Delete via MemoryStore (keeps FTS+Chroma in sync)")
    p_delete.add_argument("key")

    sub.add_parser("count", help="Count memories")

    p_retrieve = sub.add_parser("retrieve", help="Hybrid FTS+vector retrieve via MemoryStore")
    p_retrieve.add_argument("query")
    p_retrieve.add_argument("--top-k", type=int, default=3)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    db_path = resolve_db(args.db)

    if args.command is not None:
        with connect(db_path) as conn:
            execute_sql(conn, args.command)
        return 0

    if args.cmd == "list":
        return cmd_list(db_path)
    if args.cmd == "get":
        return cmd_get(db_path, args.key)
    if args.cmd == "upsert":
        return cmd_upsert(db_path, args.key, args.content, args.category, args.source)
    if args.cmd == "delete":
        return cmd_delete(db_path, args.key)
    if args.cmd == "count":
        return cmd_count(db_path)
    if args.cmd == "retrieve":
        return cmd_retrieve(db_path, args.query, args.top_k)

    with connect(db_path) as conn:
        return repl(conn)


if __name__ == "__main__":
    raise SystemExit(main())
