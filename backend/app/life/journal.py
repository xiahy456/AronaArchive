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

"""Ring log of Arona's own day. Teacher text and crisis content never land here."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..safety import is_crisis_text
from .state import InnerState

logger = logging.getLogger(__name__)

JOURNAL_KINDS = frozenset(
    {
        "shift",
        "rumination",
        "spoke",
        "teacher_interrupt",
        "glance",
        "hands",
    }
)
MAX_ENTRIES = 48
MAX_AGE = timedelta(hours=24)
DAY_BLOCK_LIMIT = 6
_DT_FMT = "%Y-%m-%dT%H:%M:%S"

ACTIVITY_SUMMARY = {
    "idle_in_classroom": "在教室发呆",
    "looking_at_teacher": "看着老师",
    "thinking": "在想事情",
    "resting": "在休息",
    "using_computer": "在通过什亭之匣操作电脑",
}

TEACHER_OPENED_SUMMARY = "老师开口"


@dataclass
class JournalEntry:
    at: datetime
    kind: str
    summary: str

    def to_dict(self) -> dict[str, str]:
        return {
            "at": self.at.strftime(_DT_FMT),
            "kind": self.kind,
            "summary": self.summary,
        }


def _parse_at(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.strptime(raw.strip(), _DT_FMT)
    except ValueError:
        return None


def _clean_summary(summary: str) -> str:
    text = " ".join((summary or "").split())
    if not text or is_crisis_text(text):
        return ""
    return text


class LifeJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[JournalEntry] = []
        self.last_glance_at: datetime | None = None
        self._seen = False
        self._last_activity: str | None = None
        self._last_rum: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("life journal load failed path=%s", self.path)
            return
        if not isinstance(raw, dict):
            return
        glance = _parse_at(raw.get("last_glance_at"))
        self.last_glance_at = glance
        entries: list[JournalEntry] = []
        for item in raw.get("entries") or []:
            if not isinstance(item, dict):
                continue
            at = _parse_at(item.get("at"))
            kind = str(item.get("kind") or "")
            summary = _clean_summary(str(item.get("summary") or ""))
            if at is None or kind not in JOURNAL_KINDS or not summary:
                continue
            entries.append(JournalEntry(at=at, kind=kind, summary=summary))
        self.entries = entries
        self._trim(datetime.now())

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_glance_at": (
                self.last_glance_at.strftime(_DT_FMT) if self.last_glance_at else ""
            ),
            "entries": [item.to_dict() for item in self.entries],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def seed(self, inner: InnerState) -> None:
        """Remember the loaded day so the first tick is not a fake shift."""
        self._seen = True
        self._last_activity = inner.activity
        self._last_rum = {item.id: item.content for item in inner.rumination}

    def append(
        self,
        kind: str,
        summary: str,
        now: datetime | None = None,
    ) -> bool:
        if kind not in JOURNAL_KINDS:
            return False
        text = _clean_summary(summary)
        if not text:
            return False
        at = (now or datetime.now()).replace(microsecond=0)
        self.entries.append(JournalEntry(at=at, kind=kind, summary=text))
        self._trim(at)
        try:
            self.save()
        except OSError:
            logger.exception("life journal save failed path=%s", self.path)
            return False
        return True

    def drop_last(self, kind: str, summary: str) -> None:
        if not self.entries:
            return
        last = self.entries[-1]
        if last.kind == kind and last.summary == summary:
            self.entries.pop()
            try:
                self.save()
            except OSError:
                logger.exception("life journal save failed path=%s", self.path)

    def drop_kind(self, kind: str) -> None:
        """Remove every entry of this kind. The glance interval stamp stays."""
        kept = [item for item in self.entries if item.kind != kind]
        if len(kept) == len(self.entries):
            return
        self.entries = kept
        try:
            self.save()
        except OSError:
            logger.exception("life journal save failed path=%s", self.path)

    def note_teacher_opened(self, user_text: str = "") -> None:
        """Log that the teacher spoke. The utterance itself is discarded."""
        del user_text
        self.append("teacher_interrupt", TEACHER_OPENED_SUMMARY)

    def note_requested_glance(self, now: datetime) -> None:
        self.last_glance_at = now.replace(microsecond=0)
        try:
            self.save()
        except OSError:
            logger.exception("life journal save failed path=%s", self.path)

    def note_inner(
        self,
        inner: InnerState,
        *,
        now: datetime | None = None,
        arona: Any = None,
    ) -> None:
        """Log an activity change or rumination appearing/ending. First sight only seeds."""
        at = now or datetime.now()
        activity = inner.activity
        rum = {item.id: item.content for item in inner.rumination}
        if not self._seen:
            self._seen = True
            self._last_activity = activity
            self._last_rum = rum
            return
        if activity != self._last_activity:
            before = ACTIVITY_SUMMARY.get(self._last_activity or "", "在教室")
            after = ACTIVITY_SUMMARY.get(activity, "在教室")
            self.append("shift", f"从{before}换成{after}", at)
            if arona is not None:
                arona.note_activity(activity)
        for rid, content in rum.items():
            if rid not in self._last_rum:
                self.append("rumination", f"记起：{content}", at)
                if arona is not None:
                    arona.set_slot("open_worry", f"还放不下：{content}")
        for rid, content in self._last_rum.items():
            if rid not in rum:
                self.append("rumination", f"放下：{content}", at)
                if arona is not None:
                    arona.clear_slot("open_worry")
                    arona.set_worry(content, at)
        self._last_activity = activity
        self._last_rum = rum

    def day_block(self, limit: int = DAY_BLOCK_LIMIT) -> str:
        rows = self.entries[-max(0, limit) :]
        if not rows:
            return ""
        lines = [f"- {item.summary}" for item in rows]
        return "【阿洛娜的记忆】\n" + "\n".join(lines)

    def contains_text(self, needle: str) -> bool:
        if not needle:
            return False
        blob = json.dumps(
            [item.to_dict() for item in self.entries],
            ensure_ascii=False,
        )
        return needle in blob

    def _trim(self, now: datetime) -> None:
        cutoff = now - MAX_AGE
        self.entries = [item for item in self.entries if item.at >= cutoff]
        if len(self.entries) > MAX_ENTRIES:
            self.entries = self.entries[-MAX_ENTRIES:]
