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

"""QQ turns: buffer, draft after a short quiet, send clauses after a longer quiet."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

from ..channel import METHOD_MESSAGE, QQ_SESSION_ID
from ..emoji_catalog import lookup_emoji
from ..image_input import image_payload_from_napcat_file
from ..logging_utils import begin_trace, format_interactive_log, reset_trace
from ..orchestrator import ChatPlan
from ..planner.prompts import TurnContext
from ..proactive.goal import wants_goal_mute
from ..protocol import msg_chat_response
from .protocol import QqFileImage, QqUrlImage
from .turn import QqPiece, QqTurn

logger = logging.getLogger(__name__)

_INTERRUPT_KINDS = frozenset({"interact", "computer_use"})
_DESKTOP_KINDS = frozenset({"chat", "welcome"})
_UNSPOKEN = frozenset({"silence", "refuse", "failed", "empty"})


class QqPipeline:
    """One live round. New messages extend it instead of starting a parallel send."""

    def __init__(
        self,
        state: Any,
        napcat_config: Any = None,
        *,
        generate_sec: float | None = None,
        deliver_sec: float | None = None,
    ) -> None:
        self.state = state
        cfg = napcat_config
        if generate_sec is None:
            generate_sec = getattr(cfg, "idle_generate_sec", 4.0)
        if deliver_sec is None:
            deliver_sec = getattr(cfg, "idle_deliver_sec", 16.0)
        self._generate_sec = max(0.0, float(generate_sec))
        self._deliver_sec = max(self._generate_sec, float(deliver_sec))
        self._turn = QqTurn()
        self._lock = asyncio.Lock()
        self._changed = asyncio.Event()
        self._interrupt = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._revision = 0
        self._last_input_at = 0.0
        self._busy = False
        self._noted = False

    async def push(
        self,
        text: str,
        images: Any = None,
        *,
        message_id: str = "",
    ) -> None:
        cleaned = (text or "").strip()
        refs = tuple(images or ())
        if not cleaned and not refs:
            return
        piece = QqPiece(cleaned, refs, str(message_id or "").strip())
        await self._interrupt_hands()
        note = False
        async with self._lock:
            note = not self._noted and not self._turn.inputs and not self._turn.sent
            self._turn.inputs.append(piece)
            self._last_input_at = time.monotonic()
            self._revision += 1
            if note:
                self._noted = True
            self._ensure_loop_locked()
        self._touch_scheduler(cleaned, activity_only=True)
        if note:
            orch = getattr(self.state, "orchestrator", None)
            if orch is not None and hasattr(orch, "note_teacher_spoke"):
                orch.note_teacher_spoke(cleaned)
        self._interrupt.set()
        self._changed.set()

    async def recall(self, message_id: str) -> None:
        mid = str(message_id or "").strip()
        if not mid:
            return
        drop_note = False
        async with self._lock:
            covered = self._turn.inputs[: self._turn.draft_covers]
            hit_covered = any(piece.message_id == mid for piece in covered)
            before = len(self._turn.inputs)
            self._turn.inputs = [
                piece for piece in self._turn.inputs if piece.message_id != mid
            ]
            if len(self._turn.inputs) == before:
                removed = False
            else:
                removed = True
                if hit_covered:
                    self._keep_draft_as_carry_locked()
                if not self._turn.inputs and not self._turn.sent:
                    self._turn = QqTurn()
                    drop_note = self._noted
                    self._noted = False
                    self._release_busy_locked()
            if removed:
                self._revision += 1
                self._changed.set()
                self._interrupt.set()
                self._ensure_loop_locked()
        if drop_note:
            self._drop_journal()
        orch = getattr(self.state, "orchestrator", None)
        conversations = getattr(orch, "conversations", None) if orch is not None else None
        if conversations is not None and hasattr(conversations, "remove_qq_message"):
            if conversations.remove_qq_message(mid):
                logger.info("qq recall dialogue message_id=%s", mid)

    def on_client_idle(self) -> None:
        """Desktop generation ended, or another channel took the mouth. Wake the loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._changed.set()

    def on_generation_idle(self) -> None:
        self.on_client_idle()

    async def close(self) -> None:
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _ensure_loop_locked(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._turn_loop())

    async def _turn_loop(self) -> None:
        try:
            while True:
                async with self._lock:
                    pending = self._turn.pending()
                    has_sent = bool(self._turn.sent)
                    current = self._turn.draft_current()
                    action = self._turn.draft.action if self._turn.draft is not None else ""
                    revision = self._revision
                    deadline_generate = self._last_input_at + self._generate_sec
                    deadline_deliver = self._last_input_at + self._deliver_sec
                    crisis = action == "crisis"
                if not pending and not has_sent and not current:
                    seen = revision
                    self._changed.clear()
                    if self._revision != seen:
                        continue
                    await self._changed.wait()
                    continue
                if not pending and (has_sent or current):
                    await self._finish()
                    continue
                if self._blocked():
                    seen = revision
                    self._changed.clear()
                    if self._revision != seen:
                        continue
                    await self._changed.wait()
                    continue
                if pending and not current:
                    if not await self._wait_quiet(deadline_generate, revision):
                        continue
                    if self._blocked():
                        continue
                    async with self._lock:
                        if self._turn.draft_current() or not self._turn.pending():
                            continue
                        if self._revision != revision:
                            continue
                    await self._generate()
                    continue
                if current and action in {"speak", "crisis"}:
                    if not crisis and time.monotonic() < deadline_deliver:
                        if not await self._wait_quiet(deadline_deliver, revision):
                            continue
                        if self._blocked():
                            continue
                        async with self._lock:
                            if not self._turn.draft_current():
                                continue
                            if self._turn.draft is None or self._turn.draft.action != action:
                                continue
                            if self._revision != revision:
                                continue
                    await self._deliver()
                    continue
                if current and action in _UNSPOKEN:
                    await self._finish()
                    continue
                seen = self._revision
                self._changed.clear()
                if self._revision != seen:
                    continue
                await self._changed.wait()
        except asyncio.CancelledError:
            raise

    async def _wait_quiet(self, deadline: float, revision: int) -> bool:
        """True when the quiet deadline passed without a newer inbound message."""
        while True:
            if self._blocked():
                return False
            if self._revision != revision:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._revision == revision and not self._blocked()
            self._changed.clear()
            if self._revision != revision or self._blocked():
                return False
            try:
                await asyncio.wait_for(self._changed.wait(), remaining)
            except asyncio.TimeoutError:
                return self._revision == revision and not self._blocked()
            return False

    async def _generate(self) -> None:
        orch = getattr(self.state, "orchestrator", None)
        if orch is None or not hasattr(orch, "prepare_chat"):
            logger.info("qq generate skipped reason=no_orchestrator")
            return
        self._acquire_busy()
        async with self._lock:
            pieces = list(self._turn.inputs)
            sent = list(self._turn.sent)
            carry = self._carry_for_prompt_locked()
            covered = len(pieces)
            revision = self._revision
        texts = [piece.text.strip() for piece in pieces if piece.text.strip()]
        turn_text = "\n".join(texts)
        raw_images = [image for piece in pieces for image in piece.images]
        try:
            images = await self._resolve_images(raw_images)
        except Exception:
            logger.exception("qq image resolve failed")
            images = []
        if not turn_text and not images:
            await self._finish()
            return
        self._touch_scheduler(turn_text, activity_only=False)
        context = TurnContext(
            inputs=tuple(texts),
            sent="\n".join(clause for clause in sent if clause.strip()),
            carry=carry,
        )
        request_json = json.dumps(
            {
                "type": "qq",
                "content": turn_text,
                "image_count": len(images),
                "message_ids": [piece.message_id for piece in pieces],
            },
            ensure_ascii=False,
        )
        begin_trace(request_json=request_json)
        try:
            plan = await orch.prepare_chat(
                session_id=QQ_SESSION_ID,
                content=turn_text,
                options={},
                qq_images=images,
                inbound_method=METHOD_MESSAGE,
                client_online=self._client_online(),
                turn_context=context,
                note_journal=False,
            )
        except asyncio.CancelledError:
            reset_trace()
            raise
        except Exception:
            logger.exception("qq prepare failed")
            plan = ChatPlan(
                session_id=QQ_SESSION_ID,
                user_text=turn_text,
                action="failed",
                inbound_method=METHOD_MESSAGE,
                client_online=self._client_online(),
            )
        async with self._lock:
            same_inputs = len(self._turn.inputs) == covered and self._revision == revision
            if not same_inputs:
                if plan.action in {"speak", "crisis"} and (plan.text or "").strip():
                    self._turn.carry = plan.text.strip()
                self._turn.draft = None
                self._turn.draft_covers = 0
                logger.info("qq draft discarded reason=input_changed generation=%s", revision)
                return
            self._turn.draft = plan
            self._turn.draft_covers = covered
            self._turn.carry = ""
            logger.info(
                "qq draft ready action=%s chars=%d covers=%d",
                plan.action,
                len(plan.text or ""),
                covered,
            )

    async def _deliver(self) -> None:
        async with self._lock:
            plan = self._turn.draft
            revision = self._revision
        if plan is None or plan.action not in {"speak", "crisis"}:
            return
        text = (plan.text or "").strip()
        if not text:
            await self._finish()
            return
        self._interrupt.clear()
        if self._revision != revision or self._blocked():
            self._interrupt.set()
            return
        link = getattr(self.state, "napcat", None)
        if link is None or not getattr(link, "connected", False):
            logger.info("qq deliver skipped reason=napcat_down")
            await self._finish()
            return
        emoji = lookup_emoji(plan.emotion)
        outcome = await link.send_text(text, emoji=emoji, interrupt=self._interrupt)
        finish = False
        async with self._lock:
            self._turn.sent.extend(outcome.sent)
            changed = self._revision != revision
            # A new message (or an explicit interrupt) rewrites the unsent tail.
            # A hard send failure commits whatever already went out, so a dead
            # socket cannot spin generate/deliver forever.
            if outcome.interrupted or changed:
                self._turn.carry = outcome.remainder
                self._turn.draft = None
                self._turn.draft_covers = 0
                logger.info(
                    "qq deliver paused sent=%d remainder=%d interrupted=%s changed=%s",
                    len(outcome.sent),
                    len(outcome.remainder),
                    outcome.interrupted,
                    changed,
                )
            else:
                finish = True
        if finish:
            await self._finish()

    async def _finish(self) -> None:
        orch = getattr(self.state, "orchestrator", None)
        async with self._lock:
            plan = self._turn.draft
            pieces = list(self._turn.inputs)
            spoken = "\n".join(clause for clause in self._turn.sent if clause.strip())
            noted = self._noted
            self._turn = QqTurn()
            self._noted = False
        if plan is None:
            self._release_busy()
            if noted and not pieces:
                self._drop_journal()
            reset_trace()
            return
        if plan.action == "crisis":
            self._drop_journal()
        delivered = bool(spoken.strip()) and plan.action in {"speak", "crisis"}
        qq_parts = self._qq_parts(pieces)
        self._log_round(plan, spoken if delivered else "")
        if orch is not None and hasattr(orch, "commit_chat"):
            try:
                await orch.commit_chat(
                    plan,
                    spoken=spoken if delivered else "",
                    delivered=delivered,
                    qq_parts=qq_parts,
                )
            except Exception:
                logger.exception("qq commit failed")
        if spoken.strip() and plan.action not in {"speak", "crisis"} and orch is not None:
            conversations = getattr(orch, "conversations", None)
            if conversations is not None:
                conversations.append(QQ_SESSION_ID, "assistant", spoken.strip(), method=METHOD_MESSAGE)
        user_text = "\n".join(piece.text.strip() for piece in pieces if piece.text.strip())
        try:
            from ..life.thought.triggers import note_finished_turn

            note_finished_turn(self.state, user_text, now=datetime.now())
        except Exception:
            logger.exception("qq finished-turn note failed")
        self._release_busy()

    def _log_round(self, plan: ChatPlan, spoken: str) -> None:
        if plan.action in {"silence", "refuse"}:
            payload = msg_chat_response(
                "",
                context_used=plan.action,
                latency=round(plan.latency, 4),
                emotion=plan.emotion,
            )
        elif plan.action in {"speak", "crisis"} and spoken.strip():
            payload = msg_chat_response(
                spoken,
                context_used=plan.context_used,
                latency=round(plan.latency, 4),
                emotion=plan.emotion,
            )
        else:
            reset_trace()
            return
        logger.info("%s", format_interactive_log(payload))
        reset_trace()

    def _carry_for_prompt_locked(self) -> str:
        carry = (self._turn.carry or "").strip()
        if carry:
            return carry
        plan = self._turn.draft
        if plan is None or self._turn.draft_covers == len(self._turn.inputs):
            return ""
        if plan.action in {"speak", "crisis"} and (plan.text or "").strip():
            return plan.text.strip()
        return ""

    def _keep_draft_as_carry_locked(self) -> None:
        plan = self._turn.draft
        if plan is not None and plan.action in {"speak", "crisis"} and (plan.text or "").strip():
            self._turn.carry = plan.text.strip()
        self._turn.draft = None
        self._turn.draft_covers = 0

    def _blocked(self) -> bool:
        kind = str(getattr(self.state, "generation_kind", "") or "")
        if kind in _DESKTOP_KINDS:
            return True
        if not self._busy and kind == "qq":
            return True
        hub = getattr(self.state, "hub", None)
        if hub is not None and not self._busy and hub.is_busy(QQ_SESSION_ID):
            return True
        return False

    def _acquire_busy(self) -> None:
        if self._busy:
            return
        self._busy = True
        hub = getattr(self.state, "hub", None)
        if hub is not None:
            hub.set_busy(QQ_SESSION_ID, True)
        self.state.generation_kind = "qq"
        self.state.generation_owner = QQ_SESSION_ID

    def _release_busy(self) -> None:
        self._release_busy_locked()

    def _release_busy_locked(self) -> None:
        if not self._busy:
            return
        self._busy = False
        hub = getattr(self.state, "hub", None)
        if hub is not None:
            hub.set_busy(QQ_SESSION_ID, False)
        if getattr(self.state, "generation_owner", "") == QQ_SESSION_ID:
            self.state.generation_kind = ""
            self.state.generation_owner = ""

    async def _interrupt_hands(self) -> None:
        kind = str(getattr(self.state, "generation_kind", "") or "")
        if kind not in _INTERRUPT_KINDS:
            return
        interrupts = getattr(self.state, "generation_interrupts", None) or {}
        for fn in list(interrupts.values()):
            try:
                await fn()
            except Exception:
                logger.exception("qq interrupt failed")

    def _touch_scheduler(self, text: str, *, activity_only: bool) -> None:
        scheduler = getattr(self.state, "scheduler", None)
        if scheduler is None:
            return
        try:
            if not activity_only:
                if wants_goal_mute(text):
                    muted = scheduler.mute_last_followup()
                    if muted:
                        logger.info("followup muted by qq key=%s", muted)
                else:
                    acked = scheduler.ack_pending_followups()
                    if acked:
                        logger.info("followup acked by qq keys=%s", acked)
            scheduler.note_user_activity()
        except Exception:
            logger.exception("qq scheduler note failed")

    def _client_online(self) -> bool:
        hub = getattr(self.state, "hub", None)
        if hub is None:
            return False
        try:
            return bool(hub.all_sessions())
        except Exception:
            return False

    def _drop_journal(self) -> None:
        orch = getattr(self.state, "orchestrator", None)
        drop = getattr(orch, "_drop_teacher_journal", None)
        if drop is None:
            return
        try:
            drop()
        except Exception:
            logger.exception("qq journal drop failed")

    def _qq_parts(self, pieces: list[QqPiece]) -> list[dict[str, str]]:
        payload: list[dict[str, str]] = []
        for piece in pieces:
            mid = (piece.message_id or "").strip()
            text = (piece.text or "").strip()
            if not mid and not text:
                continue
            payload.append({"message_id": mid, "text": text})
        return payload

    async def _resolve_images(self, images: list[Any]) -> list[Any]:
        resolved: list[Any] = []
        link = getattr(self.state, "napcat", None)
        for image in images:
            if isinstance(image, QqUrlImage):
                if image.url:
                    resolved.append(image.url)
                continue
            if not isinstance(image, QqFileImage):
                if image:
                    resolved.append(image)
                continue
            if link is None or not getattr(link, "connected", False):
                logger.info("qq file image dropped reason=napcat_down")
                continue
            frame = await link.get_file(image.file_id, file=image.file)
            payload = image_payload_from_napcat_file(frame)
            if payload is None:
                logger.info("qq file image dropped file_id=%s", image.file_id or image.file)
                continue
            resolved.append(payload)
        return resolved
