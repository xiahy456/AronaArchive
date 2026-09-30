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

"""Validate stage-decision outputs and apply promote / demote rules."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

from .stance_schema import (
    CONFIDENCES,
    DEFAULT_STAGE,
    PATCH_OPS,
    STAGE_LOVER,
    STAGE_RANK,
    DayRecord,
    PatchProposal,
    StageObservation,
    StanceState,
    normalize_stage,
)

TEACHER_EVIDENCE_MARKERS = ("老师：", "老师:")
TOUCH_MARKERS = ("互动：摸头", "【摸头】", "摸头")


@dataclass(frozen=True)
class ApplyResult:
    state: StanceState
    changed_stage: bool
    changed_patch: bool
    reason: str = ""


def parse_observation(raw: object) -> tuple[StageObservation | None, str]:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None, "empty_response"
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return None, "invalid_json"
    if not isinstance(raw, dict):
        return None, "not_object"
    stage = str(raw.get("target_stage") or "").strip()
    confidence = str(raw.get("confidence") or "").strip().lower()
    if stage not in STAGE_RANK:
        return None, "bad_stage"
    if confidence not in CONFIDENCES:
        return None, "bad_confidence"
    evidence = [
        str(item).strip()
        for item in (raw.get("evidence") or [])
        if str(item or "").strip()
    ]
    if not evidence:
        return None, "empty_evidence"
    rationale = str(raw.get("rationale") or "").strip()
    patch_raw = raw.get("personal_patch")
    if patch_raw is None:
        patch = PatchProposal()
    elif isinstance(patch_raw, dict):
        op = str(patch_raw.get("op") or "keep").strip().lower() or "keep"
        if op not in PATCH_OPS:
            return None, "bad_patch_op"
        patch = PatchProposal(
            op=op,
            text=str(patch_raw.get("text") or "").strip(),
            evidence=[
                str(item).strip()
                for item in (patch_raw.get("evidence") or [])
                if str(item or "").strip()
            ],
        )
    else:
        return None, "bad_patch"
    return (
        StageObservation(
            target_stage=stage,
            confidence=confidence,
            evidence=evidence,
            rationale=rationale,
            personal_patch=patch,
        ),
        "",
    )


def validate_observation(
    obs: StageObservation,
    *,
    day_text: str,
    committed_stage: str,
) -> str:
    """Return empty string when valid, otherwise a short reason."""
    if not all(snippet in day_text for snippet in obs.evidence):
        return "evidence_not_in_source"
    current = normalize_stage(committed_stage)
    if obs.target_stage == current:
        return ""
    if (
        STAGE_RANK[obs.target_stage] > STAGE_RANK[current]
        and obs.target_stage == STAGE_LOVER
        and _evidence_is_touch_only(obs.evidence)
    ):
        return "lover_touch_only"
    if not _has_teacher_evidence(obs.evidence):
        return "missing_teacher_evidence"
    return ""


def apply_day(
    state: StanceState,
    *,
    day: date,
    kind: str,
    observation: StageObservation | None = None,
    day_text: str = "",
    reason: str = "",
    promote_days: int = 3,
    demote_days: int = 30,
    patch_max_chars: int = 200,
    retain_days: int = 60,
) -> ApplyResult:
    """Record one calendar day and maybe update committed stage / patch."""
    date_key = day.isoformat()
    if any(item.date == date_key for item in state.days):
        return ApplyResult(
            state=state, changed_stage=False, changed_patch=False, reason="already"
        )

    next_state = StanceState(
        committed_stage=normalize_stage(state.committed_stage),
        personal_patch=state.personal_patch,
        days=list(state.days),
    )
    changed_stage = False
    changed_patch = False
    out_reason = reason

    if kind == "empty":
        next_state.days.append(
            DayRecord(date=date_key, kind="empty", reason=reason or "no_dialogue")
        )
        next_state.days = _trim_days(next_state.days, retain_days)
        return ApplyResult(
            state=next_state, changed_stage=False, changed_patch=False, reason="empty"
        )

    if kind == "invalid" or observation is None:
        next_state.days.append(
            DayRecord(date=date_key, kind="invalid", reason=reason or "invalid")
        )
        next_state.days = _trim_days(next_state.days, retain_days)
        return ApplyResult(
            state=next_state,
            changed_stage=False,
            changed_patch=False,
            reason=reason or "invalid",
        )

    record = DayRecord(
        date=date_key,
        kind="observation",
        target_stage=observation.target_stage,
        confidence=observation.confidence,
        evidence=list(observation.evidence),
        rationale=observation.rationale,
        patch_op=observation.personal_patch.op,
        patch_text=observation.personal_patch.text,
    )
    next_state.days.append(record)

    if observation.confidence == "high":
        patch_ok, patch_reason = _maybe_apply_patch(
            next_state,
            observation,
            day_text=day_text,
            patch_max_chars=patch_max_chars,
        )
        changed_patch = patch_ok
        if patch_reason:
            out_reason = patch_reason

    streak = _trailing_same_stage(next_state.days, observation.target_stage)
    current_rank = STAGE_RANK[normalize_stage(next_state.committed_stage)]
    target_rank = STAGE_RANK[observation.target_stage]
    if (
        target_rank > current_rank
        and streak >= promote_days
        and observation.confidence == "high"
    ):
        next_state.committed_stage = observation.target_stage
        changed_stage = True
        out_reason = "promote"
    elif (
        target_rank < current_rank
        and streak >= demote_days
        and observation.confidence == "high"
    ):
        next_state.committed_stage = observation.target_stage
        changed_stage = True
        out_reason = "demote"

    next_state.days = _trim_days(next_state.days, retain_days)
    return ApplyResult(
        state=next_state,
        changed_stage=changed_stage,
        changed_patch=changed_patch,
        reason=out_reason,
    )


def history_for_prompt(state: StanceState, *, history_days: int = 14) -> list[DayRecord]:
    """Recent days for the stage-decision LLM window (observations only)."""
    items = [item for item in state.days if item.kind == "observation"]
    return items[-max(1, history_days) :]


def _trailing_same_stage(days: list[DayRecord], stage: str) -> int:
    """Count adjacent calendar observation days ending today with the same stage."""
    if not days:
        return 0
    ordered = sorted(days, key=lambda item: item.date)
    streak = 0
    expected = date.fromisoformat(ordered[-1].date)
    for item in reversed(ordered):
        if item.kind != "observation":
            break
        if item.target_stage != stage:
            break
        current = date.fromisoformat(item.date)
        if current != expected:
            break
        streak += 1
        expected = current - timedelta(days=1)
    return streak


def _maybe_apply_patch(
    state: StanceState,
    observation: StageObservation,
    *,
    day_text: str,
    patch_max_chars: int,
) -> tuple[bool, str]:
    patch = observation.personal_patch
    if patch.op == "keep":
        return False, ""
    if patch.op not in {"set", "clear"}:
        return False, "bad_patch_op"
    if not patch.evidence:
        return False, "patch_no_evidence"
    if day_text and not all(snippet in day_text for snippet in patch.evidence):
        return False, "patch_evidence_missing"
    if patch.op == "clear":
        if not state.personal_patch:
            return False, ""
        state.personal_patch = ""
        return True, "patch_clear"
    text = patch.text.strip()
    if not text:
        return False, "patch_empty"
    if len(text) > patch_max_chars:
        return False, "patch_too_long"
    if not _patch_grounded(text, patch.evidence):
        return False, "patch_unmentioned"
    state.personal_patch = text
    return True, "patch_set"


def _split_tokens(text: str) -> list[str]:
    for sep in ("，", ",", "。", "；", ";", "、", " ", "\n"):
        text = text.replace(sep, "|")
    return [part.strip() for part in text.split("|") if part.strip()]


def _patch_grounded(text: str, evidence: list[str]) -> bool:
    """Require the patch to reuse wording from its cited evidence."""
    joined = "\n".join(evidence)
    if any(token in joined for token in _split_tokens(text) if len(token) >= 2):
        return True
    for snippet in evidence:
        body = snippet
        for marker in ("老师：", "老师:", "互动：", "阿洛娜：", "阿洛娜:"):
            if marker in body:
                body = body.split(marker, 1)[1]
        body = body.strip()
        for size in range(min(6, len(body)), 1, -1):
            for index in range(0, len(body) - size + 1):
                piece = body[index : index + size]
                if piece and piece in text:
                    return True
    return False


def _has_teacher_evidence(evidence: list[str]) -> bool:
    return any(
        any(marker in snippet for marker in TEACHER_EVIDENCE_MARKERS)
        for snippet in evidence
    )


def _evidence_is_touch_only(evidence: list[str]) -> bool:
    if not evidence:
        return False
    if _has_teacher_evidence(evidence):
        return False
    return all(any(marker in snippet for marker in TOUCH_MARKERS) for snippet in evidence)


def _trim_days(days: list[DayRecord], retain_days: int) -> list[DayRecord]:
    if retain_days <= 0:
        return days
    return days[-retain_days:]


def committed_defaults() -> StanceState:
    return StanceState(committed_stage=DEFAULT_STAGE, personal_patch="")


def stage_rank(stage: str) -> int:
    return STAGE_RANK[normalize_stage(stage)]
