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

"""Relationship stage enums and persisted stance records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

STAGE_FRIEND = "朋友"
STAGE_STEADY = "挚友"
STAGE_LOVER = "恋人"
STAGES: tuple[str, ...] = (STAGE_FRIEND, STAGE_STEADY, STAGE_LOVER)
STAGE_RANK: dict[str, int] = {
    STAGE_FRIEND: 0,
    STAGE_STEADY: 1,
    STAGE_LOVER: 2,
}
DEFAULT_STAGE = STAGE_STEADY

CONFIDENCES: frozenset[str] = frozenset({"low", "medium", "high"})
PATCH_OPS: frozenset[str] = frozenset({"keep", "set", "clear"})

DayKind = Literal["observation", "empty", "invalid"]
STAGE_FILES: dict[str, str] = {
    STAGE_FRIEND: "friend.md",
    STAGE_STEADY: "steady.md",
    STAGE_LOVER: "lover.md",
}

EMPTY_PATCH_NOTE = "没有额外称呼或说话习惯，不要自造昵称。"


def normalize_stage(value: object | None, *, default: str = DEFAULT_STAGE) -> str:
    text = str(value or "").strip()
    if text in STAGE_RANK:
        return text
    return default


@dataclass
class PatchProposal:
    op: str = "keep"
    text: str = ""
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "text": self.text,
            "evidence": list(self.evidence),
        }


@dataclass
class StageObservation:
    target_stage: str
    confidence: str
    evidence: list[str] = field(default_factory=list)
    rationale: str = ""
    personal_patch: PatchProposal = field(default_factory=PatchProposal)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_stage": self.target_stage,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "rationale": self.rationale,
            "personal_patch": self.personal_patch.to_dict(),
        }


@dataclass
class DayRecord:
    date: str
    kind: DayKind
    target_stage: str = ""
    confidence: str = ""
    evidence: list[str] = field(default_factory=list)
    rationale: str = ""
    patch_op: str = "keep"
    patch_text: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "kind": self.kind,
            "target_stage": self.target_stage,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "rationale": self.rationale,
            "patch_op": self.patch_op,
            "patch_text": self.patch_text,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, raw: object) -> DayRecord | None:
        if not isinstance(raw, dict):
            return None
        date = str(raw.get("date") or "").strip()
        kind = str(raw.get("kind") or "").strip()
        if not date or kind not in {"observation", "empty", "invalid"}:
            return None
        return cls(
            date=date,
            kind=kind,  # type: ignore[arg-type]
            target_stage=str(raw.get("target_stage") or "").strip(),
            confidence=str(raw.get("confidence") or "").strip(),
            evidence=[
                str(item).strip()
                for item in (raw.get("evidence") or [])
                if str(item or "").strip()
            ],
            rationale=str(raw.get("rationale") or "").strip(),
            patch_op=str(raw.get("patch_op") or "keep").strip() or "keep",
            patch_text=str(raw.get("patch_text") or "").strip(),
            reason=str(raw.get("reason") or "").strip(),
        )


@dataclass
class StanceState:
    committed_stage: str = DEFAULT_STAGE
    personal_patch: str = ""
    days: list[DayRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "committed_stage": self.committed_stage,
            "personal_patch": self.personal_patch,
            "days": [item.to_dict() for item in self.days],
        }

    @classmethod
    def from_dict(cls, raw: object) -> StanceState:
        if not isinstance(raw, dict):
            return cls()
        days: list[DayRecord] = []
        for row in raw.get("days") or []:
            item = DayRecord.from_dict(row)
            if item is not None:
                days.append(item)
        return cls(
            committed_stage=normalize_stage(raw.get("committed_stage")),
            personal_patch=str(raw.get("personal_patch") or "").strip(),
            days=days,
        )
