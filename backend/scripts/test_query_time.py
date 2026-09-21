"""Unit tests for time-aware retrieval helpers (no BGE).

Usage (from backend/):
  python scripts/test_query_time.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

from app.config import load_config  # noqa: E402
from app.memory.extractor import format_extract_now  # noqa: E402
from app.memory.store import MemoryStore  # noqa: E402
from app.query_time import (  # noqa: E402
    build_time_aware_query,
    cache_day_key,
    expand_relative_time,
    format_clock_stamp,
    format_full_datetime,
    is_currently_important,
    memory_time_fts_queries,
    mentions_query_clock,
    parse_content_clocked_datetimes,
    parse_content_datetimes,
    relative_dates_in,
    relative_months_in,
)

NOW = datetime(2026, 8, 24, 10, 14)


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def test_format_and_expand() -> None:
    print("== format / expand ==")
    stamp = format_clock_stamp(NOW)
    if stamp != "2026年8月24日 星期一 10:14":
        _fail(f"clock stamp: {stamp}")
    full = format_full_datetime(datetime(2026, 8, 24, 10, 14, 5))
    if full != "2026年8月24日 10:14:05":
        _fail(f"full datetime: {full}")
    extract = format_extract_now(NOW)
    if extract != "【当前时间】2026年8月24日 星期一 10:14":
        _fail(f"extract now: {extract}")
    if cache_day_key(NOW) != "2026-08-24":
        _fail(f"cache day: {cache_day_key(NOW)}")

    cases = {
        "今天下午做什么": "2026年8月24日下午做什么",
        "明天去医院": "2026年8月25日去医院",
        "后天和昨天": "2026年8月26日和2026年8月23日",
        "这周一开会": "2026年8月24日开会",
        "下周一交报告": "2026年8月31日交报告",
        "这个月加班": "2026年8月加班",
        "下个月3号": "2026年9月3号",
        "上个月体检": "2026年7月体检",
    }
    for src, expected in cases.items():
        got = expand_relative_time(src, NOW)
        if got != expected:
            _fail(f"expand {src!r}: expected {expected!r}, got {got!r}")

    aware = build_time_aware_query("今天下午做什么", NOW)
    if not aware.startswith("2026年8月24日下午做什么"):
        _fail(f"time-aware missing expanded date: {aware}")
    if "2026年8月24日 星期一 10:14" not in aware:
        _fail(f"time-aware missing clock stamp: {aware}")
    no_clock = build_time_aware_query("今天下午做什么", NOW, include_clock=False)
    if "10:14" in no_clock:
        _fail(f"include_clock=False still has clock: {no_clock}")
    if "星期一" not in no_clock:
        _fail(f"date+weekday missing: {no_clock}")
    print("  format / expand ok")


def test_fts_date_strings() -> None:
    print("== FTS date strings ==")
    dates = relative_dates_in("明天和今天有安排", NOW)
    if date(2026, 8, 25) not in dates or date(2026, 8, 24) not in dates:
        _fail(f"relative dates: {dates}")
    months = relative_months_in("下个月出差", NOW)
    if months != ["2026年9月"]:
        _fail(f"relative months: {months}")
    queries = memory_time_fts_queries(
        NOW,
        extra_dates=dates,
        extra_months=months,
    )
    if queries[0] != "2026年8月24日":
        _fail(f"today should be first FTS query: {queries}")
    if "2026年8月25日" not in queries:
        _fail(f"tomorrow missing from FTS: {queries}")
    if "2026年9月" not in queries:
        _fail(f"next month missing from FTS: {queries}")
    if any("10:14" in q for q in queries):
        _fail(f"clock leaked into FTS queries: {queries}")
    lore = "阿洛娜具有光环，光环一般是蓝色圆环状"
    dated = "2026年8月24日是夏莱成立纪念"
    if mentions_query_clock(lore, NOW, "今天有什么活动"):
        _fail("undated lore should not match clock needles")
    if not mentions_query_clock(dated, NOW, "今天有什么活动"):
        _fail("dated knowledge should match clock needles")
    print("  FTS date strings ok")


def test_content_importance() -> None:
    print("== content datetime / importance ==")
    ticket = "老师2026年9月1日下午2点要订回深圳的车票"
    parsed = parse_content_datetimes(ticket)
    if len(parsed) != 1 or parsed[0] != datetime(2026, 9, 1, 14, 0):
        _fail(f"ticket datetime: {parsed}")
    ask_now = datetime(2026, 8, 31, 14, 46)
    if not is_currently_important(ticket, ask_now, horizon_hours=36):
        _fail("Aug 31 afternoon should treat Sept 1 14:00 ticket as important")
    far = datetime(2026, 8, 20, 10, 0)
    if is_currently_important(ticket, far, horizon_hours=36):
        _fail("Aug 20 should not treat Sept 1 ticket as important")
    overdue = datetime(2026, 9, 2, 10, 0)
    if not is_currently_important(ticket, overdue, horizon_hours=36):
        _fail("overdue within horizon should still be important")
    stale = datetime(2026, 9, 3, 10, 0)
    if is_currently_important(ticket, stale, horizon_hours=36):
        _fail("overdue beyond horizon should not be important")
    if is_currently_important("老师想去海边", ask_now, horizon_hours=36):
        _fail("undated goal should not be important")
    nap = "老师2026年8月24日下午4点睡到晚上7点"
    nap_at = parse_content_datetimes(nap)
    if not nap_at or nap_at[0] != datetime(2026, 8, 24, 16, 0):
        _fail(f"nap datetime: {nap_at}")
    club = "老师2026年9月7日成功加入了一个社团"
    club_at = parse_content_datetimes(club)
    if not club_at or club_at[0] != datetime(2026, 9, 7, 0, 0):
        _fail(f"date-only club: {club_at}")
    if parse_content_clocked_datetimes(club):
        _fail("date-only club should not be clocked")
    if parse_content_clocked_datetimes(ticket) != parsed:
        _fail("ticket should stay clocked")
    print("  content datetime / importance ok")


class _FakeColl:
    def count(self) -> int:
        return 2


def _patch_store_for_merge(
    store: MemoryStore,
    *,
    orig_vec: dict[str, tuple[str, float]],
    timed_vec: dict[str, tuple[str, float]],
    orig_fts: dict[str, tuple[str, float]],
    timed_fts: dict[str, tuple[str, float]],
    orig_emb: list[float],
    timed_emb: list[float],
) -> None:
    store._collection = _FakeColl()  # type: ignore[method-assign]
    store._ensure_chroma = lambda: store._collection  # type: ignore[method-assign]

    def fake_vector(emb: list[float], limit: int) -> dict[str, tuple[str, float]]:
        if emb is timed_emb or emb == timed_emb:
            return dict(timed_vec)
        return dict(orig_vec)

    def fake_fts(query: str, limit: int) -> list[str]:
        if "2026年8月24日" in query or "2026年8月" == query:
            return list(timed_fts)
        return list(orig_fts)

    def fake_score(keys: list[str], emb: list[float]) -> dict[str, tuple[str, float]]:
        source = timed_fts if (emb is timed_emb or emb == timed_emb) else orig_fts
        return {k: source[k] for k in keys if k in source}

    store._vector_candidates = fake_vector  # type: ignore[method-assign]
    store._fts_candidate_keys = fake_fts  # type: ignore[method-assign]
    store._score_fts_keys = fake_score  # type: ignore[method-assign]
    store._categories_for_keys = lambda keys: {k: "other" for k in keys}  # type: ignore[method-assign]


def test_memory_merge_mock() -> None:
    print("== memory dual-retrieve mock ==")
    nap_key = "afternoon_nap"
    nap = "老师2026年8月24日下午4点睡到晚上7点"
    name_key = "user_name"
    name = "老师叫森"
    orig_emb = [1.0, 0.0]
    timed_emb = [0.0, 1.0]
    cfg = load_config()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = MemoryStore(cfg, db_path=Path(tmp) / "memory.db")
        store.config.min_score = 0.35
        store.config.min_score_no_overlap = 0.60
        store.config.candidate_top_k = 5
        _patch_store_for_merge(
            store,
            orig_vec={name_key: (name, 0.22)},
            timed_vec={nap_key: (nap, 0.62)},
            orig_fts={name_key: (name, 0.22)},
            timed_fts={nap_key: (nap, 0.58)},
            orig_emb=orig_emb,
            timed_emb=timed_emb,
        )
        hits = store.retrieve_entries(
            "今天下午做什么",
            top_k=3,
            query_embedding=orig_emb,
            include_time=True,
            time_query_embedding=timed_emb,
            now=NOW,
        )
        contents = [e["content"] for e in hits]
        if nap not in contents:
            _fail(f"expected dated nap memory, got {contents}")

        _patch_store_for_merge(
            store,
            orig_vec={name_key: (name, 0.81)},
            timed_vec={nap_key: (nap, 0.20)},
            orig_fts={name_key: (name, 0.81)},
            timed_fts={nap_key: (nap, 0.20)},
            orig_emb=orig_emb,
            timed_emb=timed_emb,
        )
        hits = store.retrieve_entries(
            "阿洛娜是谁",
            top_k=3,
            query_embedding=orig_emb,
            include_time=True,
            time_query_embedding=timed_emb,
            now=NOW,
        )
        contents = [e["content"] for e in hits]
        if nap in contents:
            _fail(f"unrelated schedule should not enter top_k: {contents}")
        if name not in contents:
            _fail(f"expected profile memory, got {contents}")
    print("  memory dual-retrieve mock ok")


def main() -> int:
    test_format_and_expand()
    test_fts_date_strings()
    test_content_importance()
    test_memory_merge_mock()
    print("PASS: time-aware retrieval helpers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
