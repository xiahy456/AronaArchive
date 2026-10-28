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

"""Commitment schedule, idempotent fire, and mute.

Run from backend/:
  python scripts/test_memory_commitment_unit.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.memory.commitment import CommitmentStore  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def test_schedule_and_mute() -> None:
    print("== commitment schedule ==")
    created = datetime(2026, 10, 27, 7, 0)
    morning = datetime(2026, 10, 27, 8, 5)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = CommitmentStore(Path(tmp) / "memory.db", mute_sec=3600)
        store.apply(
            [
                {
                    "op": "create",
                    "id": "meds",
                    "what": "提醒老师吃药",
                    "rrule": "daily",
                    "at_time": "08:00",
                },
                {
                    "op": "create",
                    "id": "untimed",
                    "what": "提醒老师喝水",
                    "rrule": "daily",
                    "at_time": "",
                },
            ],
            created,
        )
        due = store.due(morning)
        if [item.id for item in due] != ["meds"]:
            _fail(f"only the timed promise should be due: {[item.id for item in due]}")
        store.mark_fired("meds", morning)
        if store.due(morning):
            _fail("the same morning must not fire twice")
        item = store.get("meds")
        if item is None or item.last_fired_day != "2026-10-27":
            _fail(f"fire day not stored: {item}")
        next_morning = datetime(2026, 10, 28, 9, 0)
        if [item.id for item in store.due(next_morning)] != ["meds"]:
            _fail("the next day should be due again")
        store.mark_fired("meds", next_morning)
        muted = store.get("meds")
        if muted is None or muted.muted_until is None or muted.muted_until <= next_morning.timestamp():
            _fail(f"two unanswered fires should mute: {muted}")
        if store.due(next_morning):
            _fail("muted promise must not be due")
        store.apply([{"op": "ack", "id": "meds"}], morning)
        acked = store.get("meds")
        if acked is None or acked.acked_day != "2026-10-27":
            _fail(f"ack day missing: {acked}")
    print("  ok")


def test_weekly_once_ack_and_restart() -> None:
    print("== weekly, once, ack, restart ==")
    monday = datetime(2026, 10, 26, 7, 0)
    wednesday = datetime(2026, 10, 28, 8, 5)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "memory.db"
        store = CommitmentStore(path)
        store.apply(
            [
                {
                    "op": "create",
                    "id": "weekly",
                    "what": "提醒老师开会",
                    "rrule": "weekly",
                    "weekday": 2,
                    "at_time": "08:00",
                }
            ],
            monday,
        )
        if store.due(datetime(2026, 10, 26, 10, 0)):
            _fail("weekly promise must wait for its weekday")
        if [item.id for item in store.due(wednesday)] != ["weekly"]:
            _fail(f"weekly promise should be due on Wednesday: {store.due(wednesday)}")

        once_at = datetime(2026, 10, 27, 21, 0)
        store.apply(
            [
                {
                    "op": "create",
                    "id": "once",
                    "what": "提醒老师交表",
                    "rrule": "once",
                    "at_time": "21:00",
                    "due_at": once_at.timestamp(),
                }
            ],
            datetime(2026, 10, 27, 7, 0),
        )
        if store.due(datetime(2026, 10, 27, 12, 0)):
            due_ids = [item.id for item in store.due(datetime(2026, 10, 27, 12, 0))]
            if "once" in due_ids:
                _fail("once promise must wait until its time")
        if "once" not in [item.id for item in store.due(datetime(2026, 10, 27, 21, 5))]:
            _fail("once promise should be due after 21:00")
        store.mark_fired("once", datetime(2026, 10, 27, 21, 5))
        reopened = CommitmentStore(path)
        if reopened.get("once") is None or reopened.get("once").active:
            _fail("a fired once promise must stay inactive after restart")
        if any(item.id == "once" for item in reopened.due(datetime(2026, 10, 27, 21, 6))):
            _fail("restart must not fire the once promise again")

        store.apply(
            [
                {
                    "op": "create",
                    "id": "water",
                    "what": "提醒老师喝水",
                    "rrule": "daily",
                    "at_time": "08:00",
                }
            ],
            datetime(2026, 10, 27, 7, 0),
        )
        store.apply([{"op": "ack", "id": "water"}], datetime(2026, 10, 27, 8, 5))
        if any(item.id == "water" for item in store.due(datetime(2026, 10, 27, 8, 6))):
            _fail("an acknowledged promise must not fire the same day")
    print("  ok")


def main() -> int:
    test_schedule_and_mute()
    test_weekly_once_ack_and_restart()
    print("commitment unit ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
