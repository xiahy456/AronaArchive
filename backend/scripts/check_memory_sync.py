"""Compare AronaArchive memory SQLite rows against the Chroma vector collection.

Reports keys only in one store, plus content / metadata / missing-embedding drift.
Does not load the BGE encoder.

Usage (from backend/):
  python scripts/check_memory_sync.py
  python scripts/check_memory_sync.py --json
  python scripts/check_memory_sync.py --ignore-meta
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

from app.config import load_config  # noqa: E402

CHROMA_PAGE = 500


def resolve_path(path: str | None, default: Path) -> Path:
    if not path:
        return default
    p = Path(path)
    if not p.is_absolute():
        p = (BACKEND_DIR / p).resolve()
    return p


def preview(text: str, width: int = 72) -> str:
    text = (text or "").replace("\n", " ")
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _norm_meta(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _embedding_missing(emb: object) -> bool:
    if emb is None:
        return True
    if hasattr(emb, "tolist"):
        emb = emb.tolist()
    try:
        seq = list(emb)
    except TypeError:
        return True
    if not seq:
        return True
    return any(x is None for x in seq)


def load_sql(db_path: Path) -> dict[str, dict[str, str]]:
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT key, content, category, source FROM memories"
        ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to read memories: {exc}") from exc
    finally:
        conn.close()

    out: dict[str, dict[str, str]] = {}
    for row in rows:
        key = str(row["key"] or "").strip()
        if not key:
            continue
        out[key] = {
            "content": str(row["content"] or ""),
            "category": _norm_meta(row["category"]),
            "source": _norm_meta(row["source"]),
        }
    return out


def load_chroma(
    chroma_path: Path,
    collection_name: str,
) -> dict[str, dict[str, Any]]:
    if not chroma_path.exists():
        return {}

    import chromadb
    from chromadb.config import Settings

    client = chromadb.PersistentClient(
        path=str(chroma_path),
        settings=Settings(anonymized_telemetry=False),
    )
    try:
        collection = client.get_collection(name=collection_name)
    except Exception:
        return {}

    out: dict[str, dict[str, Any]] = {}
    include_with_emb = ["documents", "metadatas", "embeddings"]
    include_no_emb = ["documents", "metadatas"]
    check_embeddings = True
    offset = 0
    while True:
        batch, used_offset = _chroma_get(
            collection,
            include_with_emb if check_embeddings else include_no_emb,
            offset,
        )
        if batch is None and check_embeddings:
            check_embeddings = False
            batch, used_offset = _chroma_get(collection, include_no_emb, offset)
        if batch is None:
            raise RuntimeError("Chroma collection.get() failed")
        if not used_offset:
            offset = -1
        ids = batch.get("ids") or []
        if not ids:
            break
        documents = batch.get("documents")
        metadatas = batch.get("metadatas")
        embeddings = batch.get("embeddings") if check_embeddings else None
        if documents is None:
            documents = [None] * len(ids)
        if metadatas is None:
            metadatas = [None] * len(ids)
        for i, raw_id in enumerate(ids):
            key = str(raw_id or "").strip()
            if not key:
                continue
            meta = (
                metadatas[i]
                if i < len(metadatas) and isinstance(metadatas[i], dict)
                else {}
            )
            emb = None
            if check_embeddings and embeddings is not None and i < len(embeddings):
                emb = embeddings[i]
            out[key] = {
                "content": str(documents[i] or "") if i < len(documents) else "",
                "category": _norm_meta(meta.get("category")),
                "source": _norm_meta(meta.get("source")),
                "missing_embedding": check_embeddings and _embedding_missing(emb),
            }
        if offset < 0 or len(ids) < CHROMA_PAGE:
            break
        offset += len(ids)
    return out


def _chroma_get(
    collection: Any,
    include: list[str],
    offset: int,
) -> tuple[dict[str, Any] | None, bool]:
    """Return (batch, used_offset). Batch is None on failure."""
    try:
        if offset < 0:
            return collection.get(include=include), False
        try:
            return collection.get(include=include, limit=CHROMA_PAGE, offset=offset), True
        except TypeError:
            return collection.get(include=include), False
    except Exception:
        return None, False


def compare(
    sql: dict[str, dict[str, str]],
    chroma: dict[str, dict[str, Any]],
    *,
    check_meta: bool,
) -> dict[str, Any]:
    sql_keys = set(sql)
    chroma_keys = set(chroma)
    sql_only = sorted(sql_keys - chroma_keys)
    chroma_only = sorted(chroma_keys - sql_keys)
    shared = sorted(sql_keys & chroma_keys)

    content_mismatch: list[dict[str, str]] = []
    metadata_mismatch: list[dict[str, str]] = []
    missing_embedding: list[str] = []

    for key in shared:
        s = sql[key]
        c = chroma[key]
        if s["content"] != c["content"]:
            content_mismatch.append(
                {"key": key, "sql": s["content"], "chroma": c["content"]}
            )
        if check_meta:
            for field in ("category", "source"):
                if s[field] != c[field]:
                    metadata_mismatch.append(
                        {
                            "key": key,
                            "field": field,
                            "sql": s[field],
                            "chroma": c[field],
                        }
                    )
        if c.get("missing_embedding"):
            missing_embedding.append(key)

    drifted = (
        {item["key"] for item in content_mismatch}
        | {item["key"] for item in metadata_mismatch}
        | set(missing_embedding)
    )
    mismatch_count = (
        len(sql_only)
        + len(chroma_only)
        + len(content_mismatch)
        + len(metadata_mismatch)
        + len(missing_embedding)
    )
    return {
        "sql_only": sql_only,
        "chroma_only": chroma_only,
        "content_mismatch": content_mismatch,
        "metadata_mismatch": metadata_mismatch,
        "missing_embedding": missing_embedding,
        "matched": len(shared) - len(drifted),
        "mismatch_count": mismatch_count,
        "ok": mismatch_count == 0,
    }


def _print_key_list(
    title: str,
    keys: list[str],
    rows: dict[str, dict[str, Any]],
) -> None:
    print(f"{title} ({len(keys)}):")
    if not keys:
        print("  (none)")
        print()
        return
    for key in keys:
        print(f"  - {key}\t{preview(str(rows.get(key, {}).get('content', '')))}")
    print()


def print_report(
    sql_path: Path,
    chroma_path: Path,
    collection: str,
    sql_rows: dict[str, dict[str, str]],
    chroma_rows: dict[str, dict[str, Any]],
    result: dict[str, Any],
) -> None:
    print(f"SQLite: {sql_path}  ({len(sql_rows)} rows)")
    print(f"Chroma: {chroma_path}  collection={collection}  ({len(chroma_rows)} items)")
    print()

    _print_key_list("sql_only", result["sql_only"], sql_rows)
    _print_key_list("chroma_only", result["chroma_only"], chroma_rows)

    print(f"content_mismatch ({len(result['content_mismatch'])}):")
    if result["content_mismatch"]:
        for item in result["content_mismatch"]:
            print(f"  - {item['key']}")
            print(f"      sql:    {preview(item['sql'])}")
            print(f"      chroma: {preview(item['chroma'])}")
    else:
        print("  (none)")
    print()

    print(f"metadata_mismatch ({len(result['metadata_mismatch'])}):")
    if result["metadata_mismatch"]:
        for item in result["metadata_mismatch"]:
            print(
                f"  - {item['key']}  {item['field']}"
                f"  sql={item['sql']!r}  chroma={item['chroma']!r}"
            )
    else:
        print("  (none)")
    print()

    print(f"missing_embedding ({len(result['missing_embedding'])}):")
    if result["missing_embedding"]:
        for key in result["missing_embedding"]:
            print(f"  - {key}")
    else:
        print("  (none)")
    print()

    if result["ok"]:
        print(
            f"OK  sql={len(sql_rows)}  chroma={len(chroma_rows)}  "
            f"matched={result['matched']}"
        )
    else:
        print(f"INCONSISTENT  mismatches={result['mismatch_count']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check SQLite memories vs Chroma vector collection for drift",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite DB (default: memory.db_path from config.yaml)",
    )
    parser.add_argument(
        "--chroma",
        default=None,
        help="Path to memory Chroma dir (default: memory.chroma_path from config.yaml)",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Chroma collection name (default: memory.collection from config.yaml)",
    )
    parser.add_argument(
        "--ignore-meta",
        action="store_true",
        help="Do not compare category/source metadata",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a text report",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config()

    db_path = resolve_path(args.db, config.memory_db_abs_path)
    chroma_path = resolve_path(args.chroma, config.memory_chroma_abs_path)
    collection = args.collection or config.memory.collection

    try:
        sql_rows = load_sql(db_path)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    try:
        chroma_rows = load_chroma(chroma_path, collection)
    except Exception as exc:
        print(f"FAIL: Chroma read error: {exc}", file=sys.stderr)
        return 2

    result = compare(sql_rows, chroma_rows, check_meta=not args.ignore_meta)
    payload = {
        "sql_path": str(db_path),
        "chroma_path": str(chroma_path),
        "collection": collection,
        "sql_count": len(sql_rows),
        "chroma_count": len(chroma_rows),
        **result,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_report(
            db_path,
            chroma_path,
            collection,
            sql_rows,
            chroma_rows,
            result,
        )

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
