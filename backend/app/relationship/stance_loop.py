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

"""Midnight / startup loop for the stage-decision LLM."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..channel import method_label
from ..conversation import DialogueEntry
from ..query_time import format_full_datetime
from .stance import apply_day, parse_observation, validate_observation
from .stance_reviewer import StanceClient, build_stance_user_message
from .stance_schema import StanceState
from .stance_store import StanceStore

if TYPE_CHECKING:
    from ..ws_handler import AppState

logger = logging.getLogger(__name__)


async def run_stance_loop(state: "AppState") -> None:
    """Sleep until local midnight, then review the day that just ended."""
    while True:
        now = datetime.now()
        target = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        await asyncio.sleep(max(1.0, (target - now).total_seconds()))
        try:
            await review_day(state, target.date() - timedelta(days=1))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("stance midnight review failed")


async def review_day(
    state: "AppState",
    day: date | None = None,
    *,
    force: bool = False,
) -> StanceState | None:
    """Review one local calendar day. Idempotent per date."""
    cfg = getattr(getattr(state, "config", None), "stance", None)
    store: StanceStore | None = getattr(state, "stance_store", None)
    stance_state: StanceState | None = getattr(state, "stance", None)
    if cfg is None or store is None or stance_state is None:
        return None
    if not cfg.enabled:
        return stance_state

    target = day or (datetime.now().date() - timedelta(days=1))
    date_key = target.isoformat()
    if not force and any(item.date == date_key for item in stance_state.days):
        logger.info("stance skip already recorded date=%s", date_key)
        return stance_state

    day_text, has_dialogue = format_day_transcript(
        getattr(state, "conversations", None), target
    )
    if not has_dialogue:
        result = apply_day(
            stance_state,
            day=target,
            kind="empty",
            promote_days=cfg.promote_days,
            demote_days=cfg.demote_days,
            patch_max_chars=cfg.patch_max_chars,
            retain_days=max(cfg.demote_days + 5, 60),
        )
        _commit(state, store, result.state)
        logger.info("stance empty day=%s", date_key)
        return result.state

    client = StanceClient(state.config.planner, cfg)
    user_msg = build_stance_user_message(
        day_text=day_text,
        state=stance_state,
        history_days=cfg.history_days,
    )
    raw = await client.review(user_msg)
    obs, parse_reason = parse_observation(raw)
    if obs is None:
        result = apply_day(
            stance_state,
            day=target,
            kind="invalid",
            reason=parse_reason or "parse_failed",
            promote_days=cfg.promote_days,
            demote_days=cfg.demote_days,
            patch_max_chars=cfg.patch_max_chars,
            retain_days=max(cfg.demote_days + 5, 60),
        )
        _commit(state, store, result.state)
        logger.info("stance invalid day=%s reason=%s", date_key, parse_reason)
        return result.state

    bad = validate_observation(
        obs, day_text=day_text, committed_stage=stance_state.committed_stage
    )
    if bad:
        result = apply_day(
            stance_state,
            day=target,
            kind="invalid",
            reason=bad,
            promote_days=cfg.promote_days,
            demote_days=cfg.demote_days,
            patch_max_chars=cfg.patch_max_chars,
            retain_days=max(cfg.demote_days + 5, 60),
        )
        _commit(state, store, result.state)
        logger.info("stance invalid day=%s reason=%s", date_key, bad)
        return result.state

    result = apply_day(
        stance_state,
        day=target,
        kind="observation",
        observation=obs,
        day_text=day_text,
        promote_days=cfg.promote_days,
        demote_days=cfg.demote_days,
        patch_max_chars=cfg.patch_max_chars,
        retain_days=max(cfg.demote_days + 5, 60),
    )
    _commit(state, store, result.state)
    logger.info(
        "stance day=%s stage=%s target=%s conf=%s promote=%s patch=%s reason=%s",
        date_key,
        result.state.committed_stage,
        obs.target_stage,
        obs.confidence,
        result.changed_stage,
        result.changed_patch,
        result.reason,
    )
    return result.state


def format_day_transcript(
    conversations: Any, day: date
) -> tuple[str, bool]:
    """Build stage-decision transcript lines for one local day."""
    if conversations is None:
        return "", False
    entries = getattr(conversations, "entries", lambda: [])()
    lines: list[str] = []
    for entry in entries:
        if not isinstance(entry, DialogueEntry):
            continue
        if entry.kind in {"arrive", "leave"}:
            continue
        if entry.role not in {"user", "assistant"} and entry.kind != "touch":
            continue
        stamp = _parse_time(entry.time)
        if stamp is None or stamp.date() != day:
            continue
        label = method_label(entry.method)
        prefix = f"[{format_full_datetime(stamp)} {label}] "
        if entry.kind == "touch" or entry.content.strip() == "【摸头】":
            lines.append(f"{prefix}互动：摸头")
            continue
        if entry.role == "user":
            lines.append(f"{prefix}老师：{entry.content}")
        elif entry.role == "assistant":
            lines.append(f"{prefix}阿洛娜：{entry.content}")
    return "\n".join(lines), bool(lines)


def _parse_time(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _commit(state: "AppState", store: StanceStore, stance: StanceState) -> None:
    state.stance = stance
    store.save(stance)
    orch = getattr(state, "orchestrator", None)
    if orch is not None:
        orch.stance = stance
