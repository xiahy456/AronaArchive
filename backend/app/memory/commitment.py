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

"""Time-triggered promises the teacher asked Arona to keep."""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_AT_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_AT_ZH_RE = re.compile(r"^(\d{1,2})点(?:(\d{1,2})分?)?$")
_WEEKDAY = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}


@dataclass(frozen=True)
class Commitment:
    id: str
    what: str
    rrule: str
    at_time: str
    weekday: int | None
    due_at: float | None
    next_due_at: float
    last_fired_at: float | None
    last_fired_day: str
    acked_day: str
    muted_until: float | None
    active: bool
    source_key: str
    updated_at: float
    miss_streak: int


def normalize_rrule(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"daily", "每天", "每日"}:
        return "daily"
    if text in {"weekly", "每周", "每星期"}:
        return "weekly"
    if text in {"once", "一次", "单次"}:
        return "once"
    return ""


def parse_at_time(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _AT_RE.match(text) or _AT_ZH_RE.match(text)
    if match is None:
        return ""
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def parse_weekday(value: object) -> int | None:
    if isinstance(value, int) and 0 <= value <= 6:
        return value
    text = str(value or "").strip()
    if text.isdigit():
        number = int(text)
        if 0 <= number <= 6:
            return number
    if text in _WEEKDAY:
        return _WEEKDAY[text]
    return None


def _clock(at_time: str) -> tuple[int, int] | None:
    parsed = parse_at_time(at_time)
    if not parsed:
        return None
    hour, minute = parsed.split(":")
    return int(hour), int(minute)


def next_occurrence(
    *,
    rrule: str,
    at_time: str,
    weekday: int | None,
    due_at: float | None,
    now: datetime,
) -> datetime | None:
    rule = normalize_rrule(rrule)
    if rule == "once":
        if due_at is None:
            return None
        return datetime.fromtimestamp(float(due_at))
    clock = _clock(at_time)
    if clock is None:
        return None
    hour, minute = clock
    if rule == "daily":
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    if rule == "weekly":
        target = 0 if weekday is None else int(weekday)
        days = (target - now.weekday()) % 7
        candidate = (now + timedelta(days=days)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate
    return None


def advance_after_fire(
    item: Commitment,
    now: datetime,
) -> tuple[float, bool]:
    """Return (next_due_at, still_active) strictly after now."""
    if item.rrule == "once":
        return item.next_due_at, False
    nxt = next_occurrence(
        rrule=item.rrule,
        at_time=item.at_time,
        weekday=item.weekday,
        due_at=item.due_at,
        now=now,
    )
    if nxt is None:
        return item.next_due_at, False
    return nxt.timestamp(), True


class CommitmentStore:
    def __init__(self, db_path: Path, *, mute_sec: float = 604800) -> None:
        self.db_path = Path(db_path)
        self.mute_sec = max(0.0, float(mute_sec))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS commitments (
                    id TEXT PRIMARY KEY,
                    what TEXT NOT NULL,
                    rrule TEXT NOT NULL,
                    at_time TEXT,
                    weekday INTEGER,
                    due_at REAL,
                    next_due_at REAL NOT NULL,
                    last_fired_at REAL,
                    last_fired_day TEXT,
                    acked_day TEXT,
                    muted_until REAL,
                    active INTEGER NOT NULL DEFAULT 1,
                    source_key TEXT,
                    updated_at REAL NOT NULL,
                    miss_streak INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_commit_due
                ON commitments(active, next_due_at)
                """
            )
            cols = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(commitments)").fetchall()
            }
            if "miss_streak" not in cols:
                conn.execute(
                    "ALTER TABLE commitments ADD COLUMN miss_streak INTEGER NOT NULL DEFAULT 0"
                )
            conn.commit()

    def active(self) -> list[Commitment]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM commitments
                WHERE active = 1
                ORDER BY next_due_at ASC, id ASC
                """
            ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, item_id: str) -> Commitment | None:
        key = (item_id or "").strip()
        if not key:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM commitments WHERE id = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return self._row(row)

    def due(self, now: datetime) -> list[Commitment]:
        today = now.date().isoformat()
        ts = now.timestamp()
        found: list[Commitment] = []
        for item in self.active():
            if not item.at_time and item.rrule != "once":
                continue
            if item.next_due_at > ts:
                continue
            if item.muted_until is not None and item.muted_until > ts:
                continue
            if item.last_fired_day == today:
                continue
            if item.acked_day == today:
                continue
            found.append(item)
        return found

    def apply(self, items: list[dict[str, Any]], now: datetime | None = None) -> None:
        clock = now or datetime.now()
        for raw in items:
            if not isinstance(raw, dict):
                continue
            op = str(raw.get("op") or "create").strip().lower()
            if op == "create":
                self._create(raw, clock)
            elif op == "ack":
                self._ack(str(raw.get("id") or ""), clock)
            elif op == "mute":
                self._mute(str(raw.get("id") or ""), clock)
            elif op == "cancel":
                self._cancel(str(raw.get("id") or ""))

    def mark_fired(self, item_id: str, now: datetime) -> None:
        item = self.get(item_id)
        if item is None or not item.active:
            return
        today = now.date().isoformat()
        streak = item.miss_streak
        if item.last_fired_day and item.acked_day != item.last_fired_day:
            streak += 1
        else:
            streak = 0
        muted_until = item.muted_until
        if streak >= 1 and item.last_fired_day:
            muted_until = now.timestamp() + self.mute_sec
            streak = 0
            logger.info("commitment muted id=%s until=%s", item.id, muted_until)
        next_due, active = advance_after_fire(item, now)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE commitments SET
                    last_fired_at = ?,
                    last_fired_day = ?,
                    next_due_at = ?,
                    active = ?,
                    muted_until = ?,
                    miss_streak = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    now.timestamp(),
                    today,
                    next_due,
                    1 if active else 0,
                    muted_until,
                    streak,
                    time.time(),
                    item.id,
                ),
            )
            conn.commit()
        logger.info("commitment fired id=%s day=%s active=%s", item.id, today, active)

    def format_context(self, now: datetime) -> str:
        lines = ["【生效中的承诺】"]
        items = self.active()
        if not items:
            lines.append("（无）")
            return "\n".join(lines)
        today = now.date().isoformat()
        for item in items:
            due = datetime.fromtimestamp(item.next_due_at).strftime("%Y-%m-%d %H:%M")
            fired = "今日已提醒" if item.last_fired_day == today else "今日未提醒"
            acked = "今日已完成" if item.acked_day == today else "今日未完成"
            when = item.at_time or "未指定钟点"
            lines.append(
                f"- id={item.id} | {item.rrule} {when} | {item.what} | 下次={due} | {fired} | {acked}"
            )
        return "\n".join(lines)

    def _create(self, raw: dict[str, Any], now: datetime) -> None:
        what = " ".join(str(raw.get("what") or "").split())
        rule = normalize_rrule(raw.get("rrule"))
        if not what or not rule:
            logger.info("commitment create skipped what=%r rrule=%r", what, raw.get("rrule"))
            return
        at_time = parse_at_time(raw.get("at_time"))
        weekday = parse_weekday(raw.get("weekday"))
        due_at = _as_float(raw.get("due_at"))
        valid_from = str(raw.get("valid_from") or "").strip()
        anchor = now
        if rule == "once" and due_at is None and valid_from:
            due_at = _parse_date_ts(valid_from, at_time, now)
        nxt = next_occurrence(
            rrule=rule,
            at_time=at_time,
            weekday=weekday,
            due_at=due_at,
            now=anchor,
        )
        if nxt is None:
            # Keep the promise visible, but it will not fire until a time exists.
            nxt = datetime.max.replace(microsecond=0)
            if nxt.year > 9990:
                nxt = now + timedelta(days=3650)
        item_id = str(raw.get("id") or "").strip() or _make_id(what, rule, at_time)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO commitments(
                    id, what, rrule, at_time, weekday, due_at, next_due_at,
                    active, source_key, updated_at, miss_streak
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 0)
                ON CONFLICT(id) DO UPDATE SET
                    what=excluded.what,
                    rrule=excluded.rrule,
                    at_time=excluded.at_time,
                    weekday=excluded.weekday,
                    due_at=excluded.due_at,
                    next_due_at=excluded.next_due_at,
                    active=1,
                    source_key=excluded.source_key,
                    updated_at=excluded.updated_at
                """,
                (
                    item_id,
                    what,
                    rule,
                    at_time,
                    weekday,
                    due_at,
                    nxt.timestamp(),
                    str(raw.get("source_key") or "").strip(),
                    time.time(),
                ),
            )
            conn.commit()
        logger.info("commitment upsert id=%s what=%s rrule=%s", item_id, what, rule)

    def _ack(self, item_id: str, now: datetime) -> None:
        item = self.get(item_id)
        if item is None:
            return
        today = now.date().isoformat()
        active = 0 if item.rrule == "once" else 1
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE commitments
                SET acked_day = ?, active = ?, miss_streak = 0, updated_at = ?
                WHERE id = ?
                """,
                (today, active, time.time(), item.id),
            )
            conn.commit()
        logger.info("commitment ack id=%s day=%s", item.id, today)

    def _mute(self, item_id: str, now: datetime) -> None:
        item = self.get(item_id)
        if item is None:
            return
        until = now.timestamp() + self.mute_sec
        with self._connect() as conn:
            conn.execute(
                "UPDATE commitments SET muted_until = ?, updated_at = ? WHERE id = ?",
                (until, time.time(), item.id),
            )
            conn.commit()

    def _cancel(self, item_id: str) -> None:
        item = self.get(item_id)
        if item is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE commitments SET active = 0, updated_at = ? WHERE id = ?",
                (time.time(), item.id),
            )
            conn.commit()
        logger.info("commitment cancel id=%s", item.id)

    @staticmethod
    def _row(row: sqlite3.Row) -> Commitment:
        weekday = row["weekday"]
        due_at = row["due_at"]
        last_fired = row["last_fired_at"]
        muted = row["muted_until"]
        return Commitment(
            id=str(row["id"]),
            what=str(row["what"] or ""),
            rrule=str(row["rrule"] or ""),
            at_time=str(row["at_time"] or ""),
            weekday=int(weekday) if weekday is not None else None,
            due_at=float(due_at) if due_at is not None else None,
            next_due_at=float(row["next_due_at"] or 0.0),
            last_fired_at=float(last_fired) if last_fired is not None else None,
            last_fired_day=str(row["last_fired_day"] or ""),
            acked_day=str(row["acked_day"] or ""),
            muted_until=float(muted) if muted is not None else None,
            active=bool(row["active"]),
            source_key=str(row["source_key"] or ""),
            updated_at=float(row["updated_at"] or 0.0),
            miss_streak=int(row["miss_streak"] or 0),
        )


def _make_id(what: str, rule: str, at_time: str) -> str:
    digest = hashlib.sha1(f"{rule}|{at_time}|{what}".encode("utf-8")).hexdigest()[:10]
    return f"cm_{digest}"


def _as_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse_date_ts(day: str, at_time: str, now: datetime) -> float | None:
    try:
        year, month, dom = [int(part) for part in day.split("-")]
        clock = _clock(at_time) or (now.hour, now.minute)
        return datetime(year, month, dom, clock[0], clock[1]).timestamp()
    except (TypeError, ValueError):
        return None
