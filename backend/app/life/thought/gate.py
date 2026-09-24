# Copyright 2026 xia_hy456. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Choose whether this beat thinks, and which trigger. No model, no writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..state import THOUGHT_RUMINATION_PREFIX, InnerState
from .store import TRIGGER_PRIORITY, PendingTrigger, ThoughtLedger


@dataclass(frozen=True)
class ThoughtGateFacts:
    """Facts the caller already gathered. Climate and wording are not among them."""

    teacher_online: bool = False
    in_flight: bool = False
    session_busy: bool = False
    listen_uncommitted: bool = False
    motive_pending: bool = False
    resting: bool = False
    consolidated_today: bool = False
    teacher_just_spoke: bool = False
    spontaneous_gap_sec: float = 240.0


@dataclass(frozen=True)
class ThoughtClocks:
    revisit_after_sec: float = 1200.0
    refractory_sec: float = 180.0
    simmer_sec: float = 30.0


@dataclass(frozen=True)
class ThoughtDecision:
    kind: str = ""
    skip_reason: str = ""
    focus_id: str = ""
    queued: PendingTrigger | None = None


def decide_thought(
    now: datetime,
    inner: InnerState,
    ledger: ThoughtLedger,
    facts: ThoughtGateFacts,
    clocks: ThoughtClocks | None = None,
) -> ThoughtDecision:
    """Return the one trigger for this beat, or a skip reason. Does not mutate inputs."""
    limits = clocks or ThoughtClocks()
    reason = _hard_skip(now, inner, facts, limits)
    if reason:
        return ThoughtDecision(skip_reason=reason)
    chosen = _pick_queued(now, inner, ledger, facts, limits)
    if chosen is not None:
        kind, focus_id = _maybe_revisit(now, inner, ledger, facts, limits, chosen)
        return ThoughtDecision(kind=kind, focus_id=focus_id, queued=chosen)
    if _can_consolidate(facts):
        return ThoughtDecision(kind="consolidate")
    return _synthesize_spontaneous(now, inner, ledger, facts, limits)


def _hard_skip(
    now: datetime,
    inner: InnerState,
    facts: ThoughtGateFacts,
    clocks: ThoughtClocks,
) -> str:
    if facts.in_flight:
        return "in_flight"
    if facts.session_busy:
        return "busy"
    if facts.listen_uncommitted:
        return "listen_uncommitted"
    if inner.activity == "using_computer":
        return "using_computer"
    impulse = inner.pending_impulse
    if impulse is None:
        return ""
    if impulse.created_at is None:
        return "simmer"
    age = (now - impulse.created_at).total_seconds()
    if age < clocks.simmer_sec:
        return "simmer"
    return ""


def _pick_queued(
    now: datetime,
    inner: InnerState,
    ledger: ThoughtLedger,
    facts: ThoughtGateFacts,
    clocks: ThoughtClocks,
) -> PendingTrigger | None:
    eligible: list[tuple[int, PendingTrigger]] = []
    for index, trigger in enumerate(ledger.pending_triggers):
        if not _due(trigger, now):
            continue
        if trigger.kind == "consolidate" and not _can_consolidate(facts):
            continue
        if trigger.kind == "revisit" and not _revisit_context(inner, facts):
            continue
        if trigger.kind == "spontaneous" and _spontaneous_blocked(
            now, ledger, facts, clocks
        ):
            continue
        eligible.append((index, trigger))
    if not eligible:
        return None
    eligible.sort(
        key=lambda pair: (
            -TRIGGER_PRIORITY.get(pair[1].kind, 0),
            pair[1].not_before or datetime.min,
            pair[0],
        )
    )
    return eligible[0][1]


def _can_consolidate(facts: ThoughtGateFacts) -> bool:
    return (
        facts.resting
        and not facts.consolidated_today
        and not facts.teacher_just_spoke
    )


def _synthesize_spontaneous(
    now: datetime,
    inner: InnerState,
    ledger: ThoughtLedger,
    facts: ThoughtGateFacts,
    clocks: ThoughtClocks,
) -> ThoughtDecision:
    if inner.pending_impulse is not None or not _gap_elapsed(now, ledger, facts):
        return ThoughtDecision(skip_reason="not_due")
    if _within_refractory(now, ledger, clocks):
        return ThoughtDecision(skip_reason="refractory")
    if facts.motive_pending:
        return ThoughtDecision(skip_reason="motive")
    kind, focus_id = _maybe_revisit(
        now,
        inner,
        ledger,
        facts,
        clocks,
        PendingTrigger(kind="spontaneous"),
    )
    return ThoughtDecision(kind=kind, focus_id=focus_id)


def _maybe_revisit(
    now: datetime,
    inner: InnerState,
    ledger: ThoughtLedger,
    facts: ThoughtGateFacts,
    clocks: ThoughtClocks,
    trigger: PendingTrigger,
) -> tuple[str, str]:
    if trigger.kind != "spontaneous":
        return trigger.kind, trigger.focus_id
    concern = _unspoken_thought(inner, ledger, now, clocks)
    if concern is None or not _revisit_context(inner, facts):
        return "spontaneous", trigger.focus_id
    return "revisit", concern


def _revisit_context(inner: InnerState, facts: ThoughtGateFacts) -> bool:
    return facts.teacher_online and inner.activity != "looking_at_teacher"


def _unspoken_thought(
    inner: InnerState,
    ledger: ThoughtLedger,
    now: datetime,
    clocks: ThoughtClocks,
) -> str | None:
    focus = ledger.focus
    if focus is not None and focus.spoken:
        return None
    thoughts = [
        item
        for item in inner.rumination
        if item.id.startswith(THOUGHT_RUMINATION_PREFIX) and item.created_at is not None
    ]
    if not thoughts:
        return None
    latest = max(thoughts, key=lambda item: item.created_at or datetime.min)
    age = (now - latest.created_at).total_seconds() if latest.created_at else -1
    if age < clocks.revisit_after_sec:
        return None
    return latest.id


def _spontaneous_blocked(
    now: datetime,
    ledger: ThoughtLedger,
    facts: ThoughtGateFacts,
    clocks: ThoughtClocks,
) -> bool:
    return facts.motive_pending or _within_refractory(now, ledger, clocks)


def _gap_elapsed(now: datetime, ledger: ThoughtLedger, facts: ThoughtGateFacts) -> bool:
    if ledger.last_thought_at is None:
        return True
    elapsed = (now - ledger.last_thought_at).total_seconds()
    return elapsed >= facts.spontaneous_gap_sec


def _within_refractory(now: datetime, ledger: ThoughtLedger, clocks: ThoughtClocks) -> bool:
    if ledger.last_thought_at is None:
        return False
    elapsed = (now - ledger.last_thought_at).total_seconds()
    return elapsed < clocks.refractory_sec


def _due(trigger: PendingTrigger, now: datetime) -> bool:
    return trigger.not_before is None or trigger.not_before <= now
