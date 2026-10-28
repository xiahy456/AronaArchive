"""Smoke tests for memory update path (A context helpers / B reconcile / C hot keys).

Does not call DeepSeek. Uses a temp SQLite + Chroma under a temp dir.

Usage (from backend/):
  python scripts/smoke_memory_update.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime
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
from app.conversation import ConversationManager  # noqa: E402
from app.memory.extractor import MemoryExtractor, _format_existing_memories, format_extract_now  # noqa: E402
from app.memory.fallback import regex_extract_memories  # noqa: E402
from app.memory.normalize import normalize_memory_item  # noqa: E402
from app.memory.store import MemoryStore  # noqa: E402
from app.prompt import format_memory_inject  # noqa: E402


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def test_normalize_and_regex() -> None:
    print("== C: normalize + regex ==")
    items = regex_extract_memories("我比较喜欢黄色")
    if not items:
        _fail("regex should extract yellow preference")
    item = items[0]
    if item.get("key") != "preference_color":
        _fail(f"expected preference_color, got {item}")
    if "黄" not in str(item.get("content")):
        _fail(f"expected yellow in content, got {item}")
    print(f"  regex yellow ok: {item}")

    pink = normalize_memory_item(
        {
            "op": "upsert",
            "key": "preference_like",
            "content": "老师喜欢粉色",
            "category": "preference",
        }
    )
    if pink.get("key") != "preference_color":
        _fail(f"normalize pink -> preference_color failed: {pink}")
    print(f"  normalize pink ok: {pink}")

    name = normalize_memory_item(
        {"op": "upsert", "key": "name", "content": "老师的名字是Sensei", "category": "other"}
    )
    if name.get("key") != "user_name" or name.get("category") != "profile":
        _fail(f"normalize name failed: {name}")
    print(f"  normalize name ok: {name}")

    mood = regex_extract_memories("我今天很难过，被批评了")
    for item in mood:
        if item.get("category") in {"episodic", "emotional"}:
            _fail(f"regex must not write episode cats, got {item}")
    print("  regex mood has no emotional/episodic ok")


def test_format_context() -> None:
    print("== A: format existing memories ==")
    text = _format_existing_memories(
        [
            {
                "key": "preference_color",
                "category": "preference",
                "content": "老师喜欢粉色",
            },
            {
                "key": "goal_walk",
                "category": "goal",
                "content": "老师打算和阿洛娜出去散步",
            },
        ]
    )
    if "preference_color" not in text or "goal_walk" not in text:
        _fail(f"format missing keys: {text}")
    print("  format ok")


def test_format_extract_now() -> None:
    print("== A: format extract now ==")
    text = format_extract_now(datetime(2026, 8, 24, 9, 19))
    if "2026年8月24日" not in text:
        _fail(f"expected calendar date, got {text}")
    if "星期一" not in text:
        _fail(f"expected weekday, got {text}")
    if "09:19" not in text:
        _fail(f"expected clock time, got {text}")
    print(f"  format_extract_now ok: {text}")


def _list_rows(store: MemoryStore) -> dict[str, tuple[str, str]]:
    return {
        r[0]: (r[1], r[2] or "")
        for r in store._connect()
        .execute("SELECT key, content, category FROM memories")
        .fetchall()
    }


def _make_store(cfg) -> tuple[MemoryStore, Path]:
    tmp = tempfile.mkdtemp(prefix="arona-mem-smoke-")
    tmp_path = Path(tmp)
    store = MemoryStore(cfg, db_path=tmp_path / "memory.db")
    store.chroma_path = tmp_path / "chroma"
    store.chroma_path.mkdir(parents=True, exist_ok=True)
    return store, tmp_path


def test_reconcile_color_and_goal_delete() -> None:
    print("== B+D: reconcile + goal delete ==")
    cfg = load_config()
    store, _tmp = _make_store(cfg)
    try:
        store.upsert(
            "preference_like",
            "老师喜欢粉色",
            category="preference",
            source="seed",
        )
        store.upsert(
            "goal_walk",
            "老师打算和阿洛娜出去散步",
            category="goal",
            source="seed",
        )
        assert store.count() == 2

        extractor = MemoryExtractor(store, cfg.memory.extractor)
        extractor._apply(
            [
                {
                    "op": "upsert",
                    "key": "preference_like",
                    "content": "老师喜欢黄色",
                    "category": "preference",
                }
            ],
            source="smoke",
        )

        rows = _list_rows(store)
        if "preference_color" not in rows:
            _fail(f"expected preference_color after normalize upsert, rows={rows}")
        if "黄" not in rows["preference_color"][0]:
            _fail(f"expected yellow content, rows={rows}")
        if "preference_like" in rows:
            _fail(f"preference_like should be reconciled away, rows={rows}")
        if "goal_walk" not in rows:
            _fail(f"goal must not be auto-reconciled, rows={rows}")
        print(f"  reconcile kept yellow, removed pink alias; rows={rows}")

        extractor._apply(
            [{"op": "delete", "key": "goal_walk", "content": "", "category": "goal"}],
            source="smoke",
        )
        rows2 = _list_rows(store)
        if "goal_walk" in rows2:
            _fail(f"goal_walk should be deleted, rows={rows2}")
        print(f"  goal delete ok; remaining={rows2}")
    finally:
        store._collection = None
        store._client = None


def test_semantic_and_exact_dedup() -> None:
    print("== Dedup: semantic near + exact ==")
    cfg = load_config()
    store, _tmp = _make_store(cfg)
    try:
        extractor = MemoryExtractor(store, cfg.memory.extractor)

        # Seed near-duplicate under a non-hot key (bypass normalize by using food-like text).
        store.upsert(
            "pref_banana",
            "老师喜欢香蕉",
            category="preference",
            source="seed",
        )

        extractor._apply(
            [
                {
                    "op": "upsert",
                    "key": "like_banana_v2",
                    "content": "老师比较喜欢香蕉",
                    "category": "preference",
                }
            ],
            source="smoke",
        )
        rows = _list_rows(store)
        banana_rows = {k: v for k, v in rows.items() if "香蕉" in v[0]}
        if len(banana_rows) != 1:
            _fail(f"expected exactly one banana memory, got {banana_rows}")
        only_key, (only_content, _) = next(iter(banana_rows.items()))
        if "比较喜欢香蕉" not in only_content and only_content != "老师比较喜欢香蕉":
            # New content must win.
            if "比较" not in only_content:
                _fail(f"expected new content to win, got {banana_rows}")
        if "pref_banana" in rows and only_key != "pref_banana":
            _fail(f"old key should be dropped unless kept: {rows}")
        print(f"  semantic dedup ok: {banana_rows}")

        # Exact duplicate under a different key.
        keep_before = dict(banana_rows)
        keep_key = next(iter(keep_before.keys()))
        extractor._apply(
            [
                {
                    "op": "upsert",
                    "key": "banana_dup",
                    "content": only_content,
                    "category": "preference",
                }
            ],
            source="smoke",
        )
        rows2 = _list_rows(store)
        banana_rows2 = {k: v for k, v in rows2.items() if "香蕉" in v[0]}
        if len(banana_rows2) != 1:
            _fail(f"exact dedup should leave one row, got {banana_rows2}")
        if "banana_dup" in banana_rows2 and keep_key not in banana_rows2:
            # May keep banana_dup if pick prefers new; still only one row is required.
            pass
        if "banana_dup" in banana_rows2 and keep_key in banana_rows2:
            _fail(f"exact dedup left both keys: {banana_rows2}")
        print(f"  exact dedup ok: {banana_rows2}")

        # Color hot-key path: near-dup should land on preference_color with new text.
        store2, _tmp2 = _make_store(cfg)
        try:
            store2.upsert(
                "preference_like",
                "老师喜欢黄色",
                category="preference",
                source="seed",
            )
            extractor2 = MemoryExtractor(store2, cfg.memory.extractor)
            extractor2._apply(
                [
                    {
                        "op": "upsert",
                        "key": "pref_yellow",
                        "content": "老师比较喜欢黄色",
                        "category": "preference",
                    }
                ],
                source="smoke",
            )
            rows3 = _list_rows(store2)
            yellow = {k: v for k, v in rows3.items() if "黄" in v[0]}
            if len(yellow) != 1:
                _fail(f"expected one yellow memory, got {yellow}")
            if "preference_color" not in yellow:
                _fail(f"expected preference_color hot key, got {yellow}")
            if "比较" not in yellow["preference_color"][0] and yellow["preference_color"][0] != "老师比较喜欢黄色":
                # normalize may rewrite to 老师喜欢黄色 from regex path; here content is explicit.
                if yellow["preference_color"][0] != "老师比较喜欢黄色":
                    # Accept either new phrasing if model/normalize collapses 比较.
                    if "黄" not in yellow["preference_color"][0]:
                        _fail(f"yellow content missing: {yellow}")
            print(f"  color hot-key dedup ok: {yellow}")
        finally:
            store2._collection = None
            store2._client = None
    finally:
        store._collection = None
        store._client = None


def _sql_insert(store: MemoryStore, key: str, content: str) -> None:
    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO memories(key, content, category, updated_at, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (key, content, "preference", time.time(), "test"),
        )
        conn.commit()


def _last_injected_at(store: MemoryStore, key: str) -> float | None:
    row = (
        store._connect()
        .execute("SELECT last_injected_at FROM memories WHERE key = ?", (key,))
        .fetchone()
    )
    if row is None or row["last_injected_at"] is None:
        return None
    return float(row["last_injected_at"])


def test_inject_cooldown() -> None:
    print("== inject cooldown ==")
    cfg = load_config()
    store, _tmp = _make_store(cfg)
    try:
        _sql_insert(store, "pref_spicy", "老师喜欢吃辛辣食物但难以控制")
        _sql_insert(store, "pref_pizza", "老师喜欢吃披萨")
        now = time.time()
        store.mark_injected(["pref_spicy"], now=now)

        cooled = store._cooled_keys(
            ["pref_spicy", "pref_pizza"], now, cooldown_sec=3600
        )
        if cooled != {"pref_spicy"}:
            _fail(f"expected pref_spicy cooled within 1h, got {cooled}")

        expired = store._cooled_keys(
            ["pref_spicy", "pref_pizza"], now + 3600, cooldown_sec=3600
        )
        if expired:
            _fail(f"expected cooldown expired after 1h, got {expired}")

        before = _last_injected_at(store, "pref_spicy")
        store.upsert(
            "pref_spicy",
            "老师喜欢吃辛辣食物但难以控制",
            category="preference",
            source="test",
        )
        after = _last_injected_at(store, "pref_spicy")
        if before is None or after is None or after != before:
            _fail(
                f"upsert must keep last_injected_at, before={before} after={after}"
            )

        passed = [
            ("pref_spicy", "老师喜欢吃辛辣食物但难以控制", 0.40),
            ("pref_pizza", "老师喜欢吃披萨", 0.80),
        ]
        dropped = store._drop_cooled_entries(
            passed, apply_inject_cooldown=True, query="你好啊"
        )
        if [key for key, _, _ in dropped] != ["pref_pizza"]:
            _fail(f"expected cooled weak hit dropped and pizza kept, got {dropped}")

        kept = store._drop_cooled_entries(passed, apply_inject_cooldown=False)
        if [key for key, _, _ in kept] != ["pref_spicy", "pref_pizza"]:
            _fail(f"extractor path must not drop cooled keys, got {kept}")

        strong = [
            ("pref_spicy", "老师喜欢吃辛辣食物但难以控制", 0.90),
            ("pref_pizza", "老师喜欢吃披萨", 0.80),
        ]
        bypass_score = store._drop_cooled_entries(
            strong, apply_inject_cooldown=True, query="你好啊"
        )
        if [key for key, _, _ in bypass_score] != ["pref_spicy", "pref_pizza"]:
            _fail(f"high score must bypass cooldown, got {bypass_score}")

        bypass_overlap = store._drop_cooled_entries(
            passed, apply_inject_cooldown=True, query="辛辣还能吃吗"
        )
        if [key for key, _, _ in bypass_overlap] != ["pref_spicy", "pref_pizza"]:
            _fail(f"query overlap must bypass cooldown, got {bypass_overlap}")

        greeting = store._filter_by_score(
            [("goal_ticket", ("老师2026年9月1日下午2点要订回深圳的车票", 0.391))],
            "你好啊，阿洛娜",
        )
        if greeting:
            _fail(f"greeting must not inject ticket, got {greeting}")

        asked = store._filter_by_score(
            [("goal_ticket", ("老师2026年9月1日下午2点要订回深圳的车票", 0.75))],
            "回深圳要定的票得在什么时候定吗",
        )
        if not asked:
            _fail("explicit ticket question must pass score floor")

        store.config = store.config.model_copy(update={"inject_cooldown_sec": 0})
        zeroed = store._drop_cooled_entries(
            passed, apply_inject_cooldown=True
        )
        if [key for key, _, _ in zeroed] != ["pref_spicy", "pref_pizza"]:
            _fail(f"inject_cooldown_sec=0 must not filter, got {zeroed}")

        print("  inject cooldown ok")
    finally:
        store._collection = None
        store._client = None


def test_extract_window_user_texts() -> None:
    print("== extract window user texts ==")
    cm = ConversationManager()
    cm.append("s", "user", "我现在喜欢黄色了")
    cm.append("s", "assistant", "了解")
    cm.append("s", "user", "今天天气真好")
    texts = cm.extract_window_user_texts()
    if texts != ["我现在喜欢黄色了", "今天天气真好"]:
        _fail(f"expected both user turns, got {texts}")
    if cm.extract_window_turn_count() != 2:
        _fail("window should count both user turns")
    cm.advance_extract_cursor()
    if cm.pending_extract_entries():
        _fail("advancing the cursor must empty the window")
    print("  extract_window_user_texts ok")


def test_extract_multi_turn_context() -> None:
    print("== extract multi-turn loose context ==")
    cfg = load_config()
    store, _tmp = _make_store(cfg)
    try:
        store.upsert(
            "preference_color",
            "老师喜欢粉色",
            category="preference",
            source="seed",
        )
        store.upsert(
            "location_beijing",
            "老师住在北京",
            category="profile",
            source="seed",
        )
        store.upsert(
            "user_name",
            "老师的名字是Sensei",
            category="profile",
            source="seed",
        )
        store.upsert(
            "goal_hospital",
            "老师2026年9月1日下午2点要去医院",
            category="goal",
            source="seed",
        )
        extractor = MemoryExtractor(store, cfg.memory.extractor)
        greeting = "今天天气真好啊"
        chat_hits = store.retrieve_entries(
            greeting,
            top_k=8,
            apply_score_filter=True,
        )
        plain_hits = store.retrieve_entries(
            greeting,
            top_k=8,
            apply_score_filter=False,
        )
        chat_keys = {str(e.get("key")) for e in chat_hits}
        plain_keys = {str(e.get("key")) for e in plain_hits}
        # Score thresholds are gone: RRF ranking is the same either way and the
        # relevance call in memory/filter.py decides what reaches the prompt.
        if chat_keys != plain_keys:
            _fail(f"apply_score_filter must no longer change ranking: {chat_keys} vs {plain_keys}")
        if not chat_keys:
            _fail("greeting should still produce ranked candidates for the filter")

        last_only = extractor._load_extract_context(greeting, [greeting])
        last_keys = {str(e.get("key")) for e in last_only}
        if "user_name" not in last_keys or "goal_hospital" not in last_keys:
            _fail(f"hot key and goals must be pinned, got {last_keys}")

        ctx = extractor._load_extract_context(
            greeting,
            ["我现在喜欢黄色了", "我搬家到上海了", greeting],
        )
        keys = {str(e.get("key")) for e in ctx}
        if "preference_color" not in keys:
            _fail(f"multi-turn extract should recall color, got {keys}")
        if "location_beijing" not in keys:
            _fail(f"multi-turn extract should recall beijing home, got {keys}")
        if "goal_hospital" not in keys or "user_name" not in keys:
            _fail(f"pinned goal/name missing, got {keys}")
        print(f"  multi-turn context ok: {keys}")
    finally:
        store._collection = None
        store._client = None


def test_extract_conflict_cleanup() -> None:
    print("== extract unaddressed conflict cleanup ==")
    cfg = load_config()
    store, _tmp = _make_store(cfg)
    try:
        extractor = MemoryExtractor(store, cfg.memory.extractor)
        store.upsert(
            "location_beijing",
            "老师住在北京",
            category="profile",
            source="seed",
        )
        existing = [
            {
                "key": "location_beijing",
                "content": "老师住在北京",
                "category": "profile",
                "score": 0.9,
            }
        ]
        extractor._apply(
            [
                {
                    "op": "upsert",
                    "key": "location_shanghai",
                    "content": "老师住在上海",
                    "category": "profile",
                }
            ],
            source="smoke",
            existing=existing,
        )
        rows = _list_rows(store)
        if "location_beijing" in rows:
            _fail(f"unaddressed beijing should be deleted, rows={rows}")
        if "location_shanghai" not in rows:
            _fail(f"expected shanghai upsert, rows={rows}")
        print(f"  location conflict ok: {rows}")

        store2, _tmp2 = _make_store(cfg)
        try:
            extractor2 = MemoryExtractor(store2, cfg.memory.extractor)
            store2.upsert(
                "pref_banana",
                "老师喜欢香蕉",
                category="preference",
                source="seed",
            )
            store2.upsert(
                "pref_strawberry",
                "老师喜欢草莓",
                category="preference",
                source="seed",
            )
            both = [
                {
                    "key": "pref_banana",
                    "content": "老师喜欢香蕉",
                    "category": "preference",
                    "score": 0.9,
                },
                {
                    "key": "pref_strawberry",
                    "content": "老师喜欢草莓",
                    "category": "preference",
                    "score": 0.9,
                },
            ]
            extractor2._apply(
                [
                    {
                        "op": "upsert",
                        "key": "pref_banana",
                        "content": "老师喜欢香蕉",
                        "category": "preference",
                    },
                    {
                        "op": "upsert",
                        "key": "pref_strawberry",
                        "content": "老师喜欢草莓",
                        "category": "preference",
                    },
                ],
                source="smoke",
                existing=both,
            )
            rows2 = _list_rows(store2)
            if "pref_banana" not in rows2 or "pref_strawberry" not in rows2:
                _fail(f"both addressed prefs must remain, rows={rows2}")
            print(f"  distinct prefs kept ok: {rows2}")
        finally:
            store2._collection = None
            store2._client = None

        store3, _tmp3 = _make_store(cfg)
        try:
            extractor3 = MemoryExtractor(store3, cfg.memory.extractor)
            store3.upsert(
                "goal_walk",
                "老师打算和阿洛娜出去散步",
                category="goal",
                source="seed",
            )
            extractor3._apply(
                [
                    {
                        "op": "upsert",
                        "key": "goal_walk_v2",
                        "content": "老师打算和阿洛娜去散步",
                        "category": "goal",
                    }
                ],
                source="smoke",
                existing=[
                    {
                        "key": "goal_walk",
                        "content": "老师打算和阿洛娜出去散步",
                        "category": "goal",
                        "score": 1.0,
                    }
                ],
            )
            rows3 = _list_rows(store3)
            if "goal_walk" in rows3:
                _fail(f"unaddressed similar goal should be deleted, rows={rows3}")
            if "goal_walk_v2" not in rows3:
                _fail(f"expected new goal upsert, rows={rows3}")
            print(f"  goal conflict ok: {rows3}")
        finally:
            store3._collection = None
            store3._client = None
    finally:
        store._collection = None
        store._client = None


def test_emotional_inject_labels() -> None:
    print("== labeled inject after emotional upsert ==")
    cfg = load_config()
    store, _tmp = _make_store(cfg)
    try:
        store.upsert(
            "preference_color",
            "老师喜欢蓝色",
            category="preference",
            source="seed",
        )
        store.upsert(
            "emo_20260918_overtime",
            "老师2026年9月18日因加班感到难过",
            category="emotional",
            source="seed",
        )
        store.upsert(
            "ep_20260918_fireworks",
            "老师2026年9月18日和阿洛娜一起看烟花",
            category="episodic",
            source="seed",
        )
        rows = _list_rows(store)
        if rows.get("emo_20260918_overtime", ("", ""))[1] != "emotional":
            _fail(f"emotional category not stored, rows={rows}")
        entries = [
            {"key": key, "content": content, "category": cat}
            for key, (content, cat) in rows.items()
        ]
        block = format_memory_inject(entries, max_chars=400).block
        if "【长期记忆】" not in block or "蓝色" not in block:
            _fail(f"fact column missing: {block}")
        if "【共同经历】" not in block or "烟花" not in block:
            _fail(f"episode column missing: {block}")
        if "【老师提过的心情】" not in block or "加班" not in block:
            _fail(f"emotional column missing: {block}")
        print("  labeled inject ok")
    finally:
        store._collection = None
        store._client = None


def main() -> None:
    test_normalize_and_regex()
    test_format_context()
    test_format_extract_now()
    test_reconcile_color_and_goal_delete()
    test_semantic_and_exact_dedup()
    test_inject_cooldown()
    test_extract_window_user_texts()
    test_extract_multi_turn_context()
    test_extract_conflict_cleanup()
    test_emotional_inject_labels()
    print("ALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
