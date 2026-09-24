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

"""Chat orchestrator: retrieve -> (plan) -> prompt -> generate -> async memory extract."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from typing import Any, Literal

AbortCheck = Callable[[], bool]
InitiateResult = Literal["sent", "declined", "failed"]

# Proactive mouth markers stay in the initiate instruction, not in teacher history.
PROACTIVE_HISTORY_MARKERS = frozenset(
    {
        "【上线】",
        "【搭话】",
        "【提醒】",
        "【回访】",
        "【心情回访】",
        "【节日】",
    }
)


def should_record_history_marker(marker: str) -> bool:
    return (marker or "").strip() not in PROACTIVE_HISTORY_MARKERS

from .config import AppConfig
from .conversation import ConversationManager
from .image_input import ImagePayload
from .interact import resolve_interact_action
from .knowledge import KnowledgeRetriever
from .life.state import InnerState
from .life.turn import format_interrupt_block
from .logging_utils import begin_trace, preview, preview_list, reset_trace, update_trace
from .memory.extractor import MemoryExtractor
from .memory.store import MemoryStore
from .memory.trigger import should_extract
from .model_loader import ModelLoader
from .planner import DEFAULT_EMOTION, IntentCard, PlannerClient
from .planner.schema import resolve_life_action
from .proactive import (
    HISTORY_USER_MARKER,
    WELCOME_CLOSING_QUESTION,
    ResolvedSlot,
    build_welcome_instruction,
    care_planner_declined,
    pick_welcome_closing_hint,
)
from .proactive.goal import history_follows_proactive_marker
from .proactive.followup import (
    HISTORY_CONTINUE_MARKER,
    build_continue_instruction,
    should_skip_continue,
    too_similar,
)
from .prompt import (
    build_messages,
    build_renderer_messages,
    clip_knowledge_for_inject,
    format_memory_inject,
    memory_inject_char_budget,
)
from .protocol import CODE_INTERNAL, msg_chat_response, msg_error
from .query_time import build_time_aware_query
from .relationship import (
    Decision,
    RelationshipEngine,
    crisis_planner_climate_block,
    local_system_hint,
    planner_climate_block,
)
from .relationship.classify import classify_user_act
from .safety import (
    CRISIS_FALLBACK_EMOTION,
    crisis_fallback_reply,
    is_crisis_text,
)
from .taxonomy import CRISIS_USER_ACT

logger = logging.getLogger(__name__)

SendFn = Callable[[dict[str, Any]], Awaitable[None]]
LifeActionFn = Callable[[str, str], None]


class Orchestrator:
    def __init__(
        self,
        config: AppConfig,
        *,
        model: ModelLoader,
        conversations: ConversationManager,
        memory_store: MemoryStore,
        extractor: MemoryExtractor,
        knowledge: KnowledgeRetriever,
        planner: PlannerClient | None = None,
        relationship: RelationshipEngine | None = None,
    ) -> None:
        self.config = config
        self.model = model
        self.conversations = conversations
        self.memory_store = memory_store
        self.extractor = extractor
        self.knowledge = knowledge
        self.planner = planner or PlannerClient(
            config.planner, renderer_enabled=config.model.enabled
        )
        self.relationship = relationship
        self.life_journal: Any = None
        self.arona_memory: Any = None
        self.last_initiate_text = ""
        self.stats: dict[str, Any] = {
            "chat_count": 0,
            "welcome_count": 0,
            "idle_count": 0,
            "care_count": 0,
            "goal_count": 0,
            "continue_count": 0,
            "festival_count": 0,
            "mood_followup_count": 0,
            "interact_count": 0,
            "silence_count": 0,
            "refuse_count": 0,
            "planner_hits": 0,
            "planner_fallbacks": 0,
            "local_route_count": 0,
            "dual_route_count": 0,
        }

    def _pack_memory_inject(
        self,
        entries: list[dict[str, Any]] | None = None,
        *,
        extra_contents: list[str] | None = None,
        mark: bool = True,
    ) -> tuple[list[str], str]:
        injected = format_memory_inject(
            entries,
            extra_contents=extra_contents,
            arona_lines=self._arona_lines(),
            max_chars=memory_inject_char_budget(self.config),
        )
        if mark and injected.keys:
            self.memory_store.mark_injected(injected.keys)
        return injected.contents, injected.block

    def _life_block(self, interrupt_ctx: InnerState | None) -> str:
        if interrupt_ctx is None:
            return ""
        from .life.impulse import without_stale_care
        from .proactive.care import care_window_specs

        windows = {
            kind: (start, end)
            for kind, start, end in care_window_specs(self.config.proactive.care)
        }
        fresh = without_stale_care(interrupt_ctx, datetime.now(), windows)
        return format_interrupt_block(fresh)

    def _day_block(self) -> str:
        journal = self.life_journal
        if journal is None:
            return ""
        try:
            return str(journal.day_block() or "")
        except Exception:
            logger.exception("life day block failed")
            return ""

    def _arona_lines(self) -> list[str]:
        memory = self.arona_memory
        if memory is None:
            return []
        try:
            return list(memory.lines())
        except Exception:
            logger.exception("arona memory lines failed")
            return []

    def _record_initiate_user(self, session_id: str, marker: str) -> None:
        if should_record_history_marker(marker):
            text = (marker or "").strip()
            if text:
                self.conversations.append(session_id, "user", text)

    def _note_teacher_journal(self, user_text: str) -> None:
        journal = self.life_journal
        if journal is None:
            return
        journal.note_teacher_opened(user_text)

    def _drop_teacher_journal(self) -> None:
        journal = self.life_journal
        if journal is None:
            return
        journal.drop_last("teacher_interrupt", "老师开口")

    def _emit_life_action(
        self,
        on_life_action: LifeActionFn | None,
        action: str,
        emotion: str = DEFAULT_EMOTION,
    ) -> None:
        if on_life_action is None:
            return
        try:
            on_life_action(action, emotion)
        except Exception:
            logger.exception("life turn action callback failed action=%s", action)

    async def handle_chat(
        self,
        *,
        session_id: str,
        content: str,
        options: dict[str, Any],
        send: SendFn,
        request_json: str | None = None,
        started_at: float | None = None,
        abort_check: AbortCheck | None = None,
        on_committed: Callable[[], None] | None = None,
        image: ImagePayload | None = None,
        interrupt_ctx: InnerState | None = None,
        on_life_action: LifeActionFn | None = None,
    ) -> bool:
        def _aborted() -> bool:
            return abort_check is not None and abort_check()

        def _committed() -> None:
            if on_committed is not None:
                on_committed()

        begin_trace(started_at=started_at, request_json=request_json)
        user_text = (content or "").strip()
        if not user_text:
            logger.info("chat empty content session=%s", session_id)
            await send(
                msg_chat_response(
                    "",
                    context_used="none",
                    latency=0.0,
                    emotion=DEFAULT_EMOTION,
                )
            )
            return True

        if is_crisis_text(user_text):
            return await self._deliver_crisis(
                session_id=session_id,
                user_text=user_text,
                send=send,
                start=time.perf_counter(),
                abort_check=abort_check,
                on_committed=on_committed,
                image=image,
                interrupt_ctx=interrupt_ctx,
                on_life_action=on_life_action,
            )

        self._note_teacher_journal(user_text)
        use_rag = bool(options.get("use_rag", self.config.knowledge.enabled))
        use_memory = bool(options.get("use_memory", True))

        start = time.perf_counter()
        context_parts: list[str] = []
        relationship_applied = False
        intent: IntentCard | None = None
        decision = self._preview_user_relationship(user_text)

        def _commit_relationship() -> None:
            nonlocal relationship_applied, decision
            if relationship_applied:
                return
            applied = self._note_user_relationship(user_text)
            if applied is not None:
                decision = applied
            relationship_applied = True
            if intent is not None:
                backfilled_act = self._note_planner_user_act(intent.user_act)
                if backfilled_act is not None and decision is not None:
                    decision = replace(decision, user_act=backfilled_act)

        if decision is not None:
            context_parts.append("climate")
        if decision is not None and decision.action in {"silence", "refuse"}:
            self._emit_life_action(on_life_action, "continue_activity")
            await self._skip_generation(
                session_id=session_id,
                user_text=user_text,
                decision=decision,
                send=send,
                latency=time.perf_counter() - start,
                on_sent=_commit_relationship,
            )
            _committed()
            return True

        logger.info(
            "chat start session=%s use_rag=%s use_memory=%s request=%r",
            session_id,
            use_rag,
            use_memory,
            user_text,
        )
        if image is not None:
            logger.info(
                "planner input 包含文本与图片 session=%s bytes=%d mime=%s",
                session_id,
                len(image.data),
                image.mime,
            )
        else:
            logger.info("planner input 只含文本 session=%s", session_id)

        need_rag = use_rag and self.knowledge.enabled
        query_embedding: list[float] | None = None
        time_query_embedding: list[float] | None = None
        retrieve_now = datetime.now()
        time_query = build_time_aware_query(user_text, retrieve_now)
        if use_memory or need_rag:
            t0 = time.perf_counter()
            try:
                embeddings = await asyncio.to_thread(
                    self.memory_store.encode_queries, [user_text, time_query]
                )
                query_embedding = embeddings[0]
                time_query_embedding = embeddings[1]
                logger.info(
                    "query embedding session=%s latency=%.3fs dim=%d time_query=%r",
                    session_id,
                    time.perf_counter() - t0,
                    len(query_embedding),
                    time_query,
                )
            except Exception:
                logger.exception(
                    "query embedding failed session=%s; retrieve will encode itself",
                    session_id,
                )
                query_embedding = None
                time_query_embedding = None

        memories: list[str] = []
        memory_block = ""
        if use_memory:
            t0 = time.perf_counter()
            cand_k = max(1, int(self.config.memory.candidate_top_k))
            entries = await asyncio.to_thread(
                self.memory_store.retrieve_entries,
                user_text,
                cand_k,
                query_embedding,
                apply_inject_cooldown=True,
                include_time=True,
                time_query=time_query,
                time_query_embedding=time_query_embedding,
                now=retrieve_now,
            )
            memories, memory_block = self._pack_memory_inject(entries)
            logger.info(
                "memory retrieve session=%s hits=%d latency=%.3fs items=%s",
                session_id,
                len(memories),
                time.perf_counter() - t0,
                preview_list(memories),
            )
            if memories:
                context_parts.append("memory")
        else:
            logger.info("memory retrieve skipped session=%s", session_id)

        knowledge_chunks: list[str] = []
        if use_rag:
            t0 = time.perf_counter()
            knowledge_chunks = await asyncio.to_thread(
                self.knowledge.retrieve,
                user_text,
                self.config.knowledge.retrieve_top_k,
                query_embedding,
                include_time=True,
                time_query=time_query,
                time_query_embedding=time_query_embedding,
                now=retrieve_now,
            )
            logger.info(
                "rag retrieve session=%s hits=%d latency=%.3fs items=%s",
                session_id,
                len(knowledge_chunks),
                time.perf_counter() - t0,
                preview_list(knowledge_chunks),
            )
            if knowledge_chunks:
                context_parts.append("rag")
            before_clip = len(knowledge_chunks)
            knowledge_chunks = clip_knowledge_for_inject(self.config, knowledge_chunks)
            if len(knowledge_chunks) < before_clip:
                logger.info(
                    "rag inject clipped session=%s before=%d after=%d",
                    session_id,
                    before_clip,
                    len(knowledge_chunks),
                )
        else:
            logger.info("rag retrieve skipped session=%s", session_id)

        history = self.conversations.get_history(session_id)
        if history:
            context_parts.append("history")
        logger.info(
            "history session=%s turns=%d",
            session_id,
            len(history),
        )

        use_dual = self.planner.enabled
        if use_dual:
            self.stats["dual_route_count"] += 1
        else:
            self.stats["local_route_count"] += 1

        emotion = DEFAULT_EMOTION
        if use_dual:
            context_parts.append("planner")
            t0 = time.perf_counter()
            intent = await self.planner.plan(
                user_text=user_text,
                history=history,
                memories=memories,
                knowledge=knowledge_chunks,
                climate_block=self._climate_block(decision),
                image=image,
                memory_block=memory_block,
                life_block=self._life_block(interrupt_ctx),
                day_block=self._day_block(),
            )
            logger.info(
                "planner session=%s ok=%s latency=%.3fs",
                session_id,
                intent is not None,
                time.perf_counter() - t0,
            )
            if intent is None:
                self.stats["planner_fallbacks"] += 1
                logger.info("planner fallback to local path session=%s", session_id)
            else:
                self.stats["planner_hits"] += 1
                if intent.user_act == CRISIS_USER_ACT:
                    logger.info(
                        "planner marked crisis; discard daily draft session=%s",
                        session_id,
                    )
                    self._drop_teacher_journal()
                    return await self._deliver_crisis(
                        session_id=session_id,
                        user_text=user_text,
                        send=send,
                        start=start,
                        abort_check=abort_check,
                        on_committed=on_committed,
                        memories=memories,
                        memory_block=memory_block,
                        image=image,
                        interrupt_ctx=interrupt_ctx,
                        on_life_action=on_life_action,
                    )
                emotion = intent.arona_emotion
                self._merge_decision_into_intent(intent, decision)
                if not intent.reply_ok:
                    action = resolve_life_action(intent)
                    self._emit_life_action(on_life_action, action, emotion)
                    await self._skip_generation(
                        session_id=session_id,
                        user_text=user_text,
                        decision=decision,
                        send=send,
                        reason="reply_ok_false",
                        latency=time.perf_counter() - start,
                        emotion=emotion,
                        on_sent=_commit_relationship,
                    )
                    _committed()
                    return True

        full, context_used = await self._compose_reply(
            session_id=session_id,
            intent=intent,
            user_text=user_text,
            history=history,
            memories=memories,
            knowledge=knowledge_chunks,
            context_parts=context_parts,
            extra_system=self._local_hint(decision),
            emotion=emotion,
            memory_block=memory_block,
        )
        latency = time.perf_counter() - start
        if full is None:
            logger.warning(
                "chat cannot generate session=%s reason=renderer_disabled_planner_miss",
                session_id,
            )
            reset_trace()
            await send(
                msg_error(
                    CODE_INTERNAL,
                    "Planner failed and local renderer is disabled",
                )
            )
            _committed()
            return True
        if _aborted():
            logger.info("chat aborted before send session=%s", session_id)
            reset_trace()
            return False
        await send(
            msg_chat_response(
                full,
                context_used=context_used,
                latency=round(latency, 4),
                emotion=emotion,
            )
        )
        self._emit_life_action(on_life_action, "speak", emotion)
        _commit_relationship()

        self.conversations.append(session_id, "user", user_text)
        self.conversations.append(session_id, "assistant", full)
        _committed()

        await self._maybe_extract(session_id, user_text)
        self._note_arona_relationship(decision, "speak")
        self.stats["chat_count"] += 1
        total_latency = time.perf_counter() - start
        logger.info(
            "chat done session=%s context=%s emotion=%s latency=%.3fs "
            "request=%r response=%r",
            session_id,
            context_used,
            emotion,
            total_latency,
            user_text,
            full,
        )
        await self._maybe_continue(
            session_id=session_id,
            intent=intent,
            previous=full,
            send=send,
            climate=decision.climate if decision is not None else None,
            decision=decision,
            abort_check=abort_check,
            interrupt_ctx=interrupt_ctx,
            on_life_action=on_life_action,
        )
        return True

    async def _deliver_crisis(
        self,
        *,
        session_id: str,
        user_text: str,
        send: SendFn,
        start: float,
        abort_check: AbortCheck | None = None,
        on_committed: Callable[[], None] | None = None,
        memories: list[str] | None = None,
        memory_block: str = "",
        image: ImagePayload | None = None,
        interrupt_ctx: InnerState | None = None,
        on_life_action: LifeActionFn | None = None,
    ) -> bool:
        """Speak via crisis planner draft (no renderer); local Arona fallback."""
        history = self.conversations.get_history(session_id)
        intent: IntentCard | None = None
        if self.planner.enabled:
            t0 = time.perf_counter()
            intent = await self.planner.plan(
                user_text=user_text,
                history=history,
                memories=list(memories or []),
                knowledge=[],
                climate_block=crisis_planner_climate_block(),
                image=image,
                crisis=True,
                memory_block=memory_block,
                life_block=self._life_block(interrupt_ctx),
                day_block=self._day_block(),
            )
            logger.info(
                "crisis planner session=%s ok=%s latency=%.3fs",
                session_id,
                intent is not None,
                time.perf_counter() - t0,
            )

        draft = ""
        emotion = CRISIS_FALLBACK_EMOTION
        context_used = "crisis_fallback"
        if intent is not None:
            spoken = intent.to_renderer_draft()
            if spoken and intent.reply_ok:
                draft = spoken
                emotion = intent.arona_emotion
                context_used = "crisis_planner"
        if not draft:
            draft = crisis_fallback_reply()
            emotion = CRISIS_FALLBACK_EMOTION
            context_used = "crisis_fallback"

        if abort_check is not None and abort_check():
            logger.info("crisis aborted before send session=%s", session_id)
            reset_trace()
            return False

        latency = time.perf_counter() - start
        await send(
            msg_chat_response(
                draft,
                context_used=context_used,
                latency=round(latency, 4),
                emotion=emotion,
            )
        )
        self._emit_life_action(on_life_action, "speak", emotion)
        self._commit_crisis_relationship()
        self.conversations.append(session_id, "user", user_text)
        self.conversations.append(session_id, "assistant", draft)
        if on_committed is not None:
            on_committed()
        self.conversations.clear_extract_buffer(session_id)
        self.stats["chat_count"] += 1
        logger.info(
            "chat crisis session=%s context=%s emotion=%s latency=%.3fs "
            "request=%r response=%r",
            session_id,
            context_used,
            emotion,
            time.perf_counter() - start,
            user_text,
            draft,
        )
        return True

    def _commit_crisis_relationship(self) -> None:
        if self.relationship is None or not self.config.proactive.relationship.enabled:
            return
        self.relationship.on_user_act(CRISIS_USER_ACT)

    async def handle_welcome(
        self,
        *,
        session_id: str,
        slot: ResolvedSlot,
        first_in_slot: bool,
        send: SendFn,
    ) -> bool:
        """Generate and push an online welcome greeting. Returns True on success."""
        climate = None
        if self.relationship is not None and self.config.proactive.relationship.enabled:
            climate = self.relationship.peek_climate()
        closing_hint = pick_welcome_closing_hint()
        result = await self.handle_initiate(
            session_id=session_id,
            kind="welcome",
            instruction=build_welcome_instruction(
                slot,
                first_in_slot=first_in_slot,
                climate=climate,
                closing_hint=closing_hint,
            ),
            history_marker=HISTORY_USER_MARKER,
            send=send,
            retrieve_memory=False,
            climate_block=self._welcome_climate_block(
                climate, closing_hint=closing_hint
            ),
            climate=climate,
        )
        return result == "sent"

    async def handle_interact(
        self,
        *,
        session_id: str,
        action: str,
        duration_ms: int = 0,
        send: SendFn,
        interrupt_ctx: InnerState | None = None,
        on_life_action: LifeActionFn | None = None,
    ) -> bool:
        """React to a client gesture. Unknown actions must be rejected by the WS layer."""
        spec = resolve_interact_action(action)
        if spec is None:
            logger.warning(
                "interact unknown action session=%s action=%r",
                session_id,
                action,
            )
            return False

        decision: Decision | None = None
        climate: str | None = None
        if self.relationship is not None and self.config.proactive.relationship.enabled:
            _act, decision = self.relationship.on_user_act(spec.user_act)
            climate = decision.climate

        result = await self.handle_initiate(
            session_id=session_id,
            kind="interact",
            instruction=spec.build_instruction(duration_ms),
            history_marker=spec.history_marker,
            send=send,
            retrieve_memory=False,
            climate_block=self._climate_block(decision),
            climate=climate,
            decision=decision,
            context_tags=["interact", spec.action],
            interrupt_ctx=interrupt_ctx,
            on_life_action=on_life_action,
        )
        return result == "sent"

    async def handle_initiate(
        self,
        *,
        session_id: str,
        kind: str,
        instruction: str,
        history_marker: str,
        send: SendFn,
        retrieve_memory: bool = False,
        memory_query: str = "",
        extra_memories: list[str] | tuple[str, ...] | None = None,
        climate_block: str = "",
        climate: str | None = None,
        decision: Decision | None = None,
        continue_previous: str | None = None,
        context_tags: list[str] | None = None,
        interrupt_ctx: InnerState | None = None,
        on_life_action: LifeActionFn | None = None,
    ) -> InitiateResult:
        """Generate a system-event line (welcome / idle / care / goal / continue / interact).

        sent: a line was pushed (including silent interact with empty content).
        declined: care Planner refused (no fallback).
        failed: generate miss; caller may retry.
        """
        self.last_initiate_text = ""
        user_text = instruction
        start = time.perf_counter()
        begin_trace(started_at=start)
        context_parts: list[str] = list(context_tags) if context_tags else [kind]
        if climate or decision is not None:
            context_parts.append("climate")

        logger.info(
            "initiate start session=%s kind=%s instruction=%r",
            session_id,
            kind,
            user_text,
        )

        memories: list[str] = []
        memory_block = ""
        injected = [
            item.strip()
            for item in (extra_memories or ())
            if (item or "").strip()
        ]
        if injected:
            memories, memory_block = self._pack_memory_inject(
                extra_contents=injected,
                mark=False,
            )
            context_parts.append("memory")
            logger.info(
                "initiate memory injected session=%s kind=%s hits=%d",
                session_id,
                kind,
                len(memories),
            )
        elif retrieve_memory and memory_query:
            t0 = time.perf_counter()
            cand_k = max(1, int(self.config.memory.candidate_top_k))
            entries = await asyncio.to_thread(
                self.memory_store.retrieve_entries,
                memory_query,
                cand_k,
                apply_inject_cooldown=True,
            )
            memories, memory_block = self._pack_memory_inject(entries)
            logger.info(
                "initiate memory retrieve session=%s kind=%s hits=%d latency=%.3fs",
                session_id,
                kind,
                len(memories),
                time.perf_counter() - t0,
            )
            if memories:
                context_parts.append("memory")
        else:
            logger.info(
                "initiate memory retrieve skipped session=%s kind=%s",
                session_id,
                kind,
            )

        history = self.conversations.get_history(session_id)
        if history:
            context_parts.append("history")

        use_dual = self.planner.enabled
        if use_dual:
            self.stats["dual_route_count"] += 1
        else:
            self.stats["local_route_count"] += 1

        emotion = DEFAULT_EMOTION
        intent: IntentCard | None = None
        block = climate_block or self._climate_block(decision)
        if use_dual:
            context_parts.append("planner")
            t0 = time.perf_counter()
            intent = await self.planner.plan(
                user_text=user_text,
                history=history,
                memories=memories,
                knowledge=[],
                climate_block=block,
                memory_block=memory_block,
                life_block=self._life_block(interrupt_ctx),
                day_block=self._day_block(),
            )
            logger.info(
                "initiate planner session=%s kind=%s ok=%s latency=%.3fs",
                session_id,
                kind,
                intent is not None,
                time.perf_counter() - t0,
            )
            if intent is not None and (
                care_planner_declined(kind, reply_ok=intent.reply_ok)
                or (kind == "thought" and not intent.reply_ok)
            ):
                self.stats["planner_hits"] += 1
                logger.info(
                    "initiate declined session=%s kind=%s reason=reply_ok_false",
                    session_id,
                    kind,
                )
                reset_trace()
                return "declined"
            if (
                kind == "interact"
                and intent is not None
                and not intent.reply_ok
            ):
                self.stats["planner_hits"] += 1
                emotion = intent.arona_emotion
                action = resolve_life_action(intent)
                self._emit_life_action(on_life_action, action, emotion)
                latency = time.perf_counter() - start
                context_used = "+".join([*context_parts, "silence"])
                await send(
                    msg_chat_response(
                        "",
                        context_used=context_used,
                        latency=round(latency, 4),
                        emotion=emotion,
                    )
                )
                self._record_initiate_user(session_id, history_marker)
                self.stats["silence_count"] = int(self.stats.get("silence_count", 0)) + 1
                self.stats["interact_count"] = int(self.stats.get("interact_count", 0)) + 1
                logger.info(
                    "initiate silent session=%s kind=%s context=%s emotion=%s "
                    "latency=%.3fs",
                    session_id,
                    kind,
                    context_used,
                    emotion,
                    latency,
                )
                reset_trace()
                return "sent"
            if intent is not None and not intent.reply_ok:
                if not intent.to_renderer_draft():
                    logger.info(
                        "initiate reply_ok=false empty draft treated as miss "
                        "session=%s kind=%s",
                        session_id,
                        kind,
                    )
                    intent = None
                else:
                    logger.info(
                        "initiate ignoring reply_ok=false session=%s kind=%s",
                        session_id,
                        kind,
                    )
            if intent is None:
                self.stats["planner_fallbacks"] += 1
                logger.info(
                    "initiate planner fallback session=%s kind=%s", session_id, kind
                )
            else:
                self.stats["planner_hits"] += 1
                emotion = intent.arona_emotion
                self._merge_decision_into_intent(intent, decision)

        full, context_used = await self._compose_reply(
            session_id=session_id,
            intent=intent,
            user_text=user_text,
            history=history,
            memories=memories,
            knowledge=[],
            context_parts=context_parts,
            extra_system=self._local_hint(decision) if decision is not None else None,
            emotion=emotion,
            kind=kind,
            memory_block=memory_block,
        )
        latency = time.perf_counter() - start
        if not (full or "").strip():
            logger.warning(
                "initiate empty response session=%s kind=%s", session_id, kind
            )
            reset_trace()
            return "failed"

        if kind == "continue" and too_similar(continue_previous or "", full):
            logger.info(
                "continue discarded session=%s reason=too_similar previous=%r cont=%r",
                session_id,
                continue_previous,
                full,
            )
            reset_trace()
            return "failed"

        await send(
            msg_chat_response(
                full,
                context_used=context_used,
                latency=round(latency, 4),
                emotion=emotion,
            )
        )
        if kind == "interact":
            self._emit_life_action(on_life_action, "speak", emotion)

        self._record_initiate_user(session_id, history_marker)
        self.conversations.append(session_id, "assistant", full)
        self.last_initiate_text = full

        if self.relationship is not None and self.config.proactive.relationship.enabled:
            used_climate = (
                decision.climate if decision is not None else climate
            ) or "steady"
            if kind == "interact":
                user_act = decision.user_act if decision is not None else "touch"
                self.relationship.on_arona_action("speak", used_climate, user_act)
            elif kind == "computer_use":
                user_act = (
                    decision.user_act if decision is not None else "instrumental"
                )
                self.relationship.on_arona_action("speak", used_climate, user_act)
            elif kind == "continue":
                self.relationship.on_arona_action("continue", used_climate)
            else:
                motive = None if kind == "welcome" else kind
                self.relationship.on_arona_action(
                    "initiate", used_climate, motive_kind=motive
                )
        stat_key = {
            "welcome": "welcome_count",
            "idle": "idle_count",
            "goal": "goal_count",
            "continue": "continue_count",
            "festival": "festival_count",
            "mood_followup": "mood_followup_count",
            "interact": "interact_count",
        }.get(kind, "care_count")
        self.stats[stat_key] = int(self.stats.get(stat_key, 0)) + 1
        self.stats["chat_count"] += 1
        logger.info(
            "initiate done session=%s kind=%s context=%s emotion=%s latency=%.3fs response=%r",
            session_id,
            kind,
            context_used,
            emotion,
            time.perf_counter() - start,
            full,
        )
        return "sent"

    async def _compose_reply(
        self,
        *,
        session_id: str,
        intent: IntentCard | None,
        user_text: str,
        history: list[dict[str, str]],
        memories: list[str],
        knowledge: list[str],
        context_parts: list[str],
        extra_system: str | None = None,
        emotion: str = DEFAULT_EMOTION,
        kind: str | None = None,
        memory_block: str = "",
    ) -> tuple[str | None, str]:
        """Build the spoken line: renderer GGUF, local GGUF fallback, or planner draft.

        Returns (text, context_used). text is None when the renderer is off and
        planner produced no intent.
        """
        parts = list(context_parts)
        renderer_on = self.config.model.enabled
        label = "initiate" if kind is not None else "chat"
        kind_suffix = f" kind={kind}" if kind is not None else ""

        if not renderer_on:
            context_used = "+".join(parts) if parts else "none"
            if intent is None:
                logger.warning(
                    "%s renderer disabled and planner unavailable session=%s%s",
                    label,
                    session_id,
                    kind_suffix,
                )
                return None, context_used
            full = intent.to_renderer_draft()
            if kind is None:
                logger.info(
                    "prompt built session=%s mode=draft messages=0 system_chars=0 "
                    "context=%s emotion=%s",
                    session_id,
                    context_used,
                    emotion,
                )
            else:
                logger.info(
                    "initiate prompt built session=%s kind=%s mode=draft "
                    "context=%s emotion=%s",
                    session_id,
                    kind,
                    context_used,
                    emotion,
                )
            return full, context_used

        if intent is not None:
            messages = build_renderer_messages(
                self.config,
                draft=intent.to_renderer_draft(),
            )
            parts.append("renderer")
            mode = "renderer"
        else:
            messages = build_messages(
                self.config,
                user_text=user_text,
                history=history,
                memories=memories,
                knowledge=knowledge,
                extra_system=extra_system,
                memory_block=memory_block,
            )
            mode = "local"

        update_trace(renderer_prompt=messages)
        context_used = "+".join(parts) if parts else "none"
        system_chars = len(messages[0]["content"]) if messages else 0
        if kind is None:
            logger.info(
                "prompt built session=%s mode=%s messages=%d system_chars=%d "
                "context=%s emotion=%s",
                session_id,
                mode,
                len(messages),
                system_chars,
                context_used,
                emotion,
            )
            logger.info("llm generate start session=%s mode=sync", session_id)
        else:
            logger.info(
                "initiate prompt built session=%s kind=%s mode=%s context=%s emotion=%s",
                session_id,
                kind,
                mode,
                context_used,
                emotion,
            )

        t0 = time.perf_counter()
        full = await asyncio.to_thread(self.model.generate, messages, self.config)
        generate_latency = time.perf_counter() - t0
        if kind is None:
            logger.info(
                "llm generate done session=%s mode=sync latency=%.3fs chars=%d response=%r",
                session_id,
                generate_latency,
                len(full),
                full,
            )
        else:
            logger.info(
                "initiate llm done session=%s kind=%s latency=%.3fs chars=%d response=%r",
                session_id,
                kind,
                generate_latency,
                len(full),
                full,
            )
        update_trace(renderer_text=full)
        return full, context_used

    def _preview_user_relationship(self, user_text: str) -> Decision | None:
        if self.relationship is None or not self.config.proactive.relationship.enabled:
            return None
        _act, decision = self.relationship.preview_user_text(user_text)
        return decision

    def _note_user_relationship(self, user_text: str) -> Decision | None:
        if self.relationship is None or not self.config.proactive.relationship.enabled:
            return None
        _act, decision = self.relationship.on_user_text(user_text)
        return decision

    def _note_planner_user_act(self, act: str) -> str | None:
        """Return the Planner act only when a user Δ was backfilled."""
        if self.relationship is None or not self.config.proactive.relationship.enabled:
            return None
        normalized, backfilled = self.relationship.note_planner_user_act(act)
        return normalized if backfilled else None

    def _note_arona_relationship(
        self, decision: Decision | None, action: str
    ) -> None:
        if self.relationship is None or not self.config.proactive.relationship.enabled:
            return
        climate = decision.climate if decision is not None else "steady"
        user_act = decision.user_act if decision is not None else "other"
        self.relationship.on_arona_action(action, climate, user_act)  # type: ignore[arg-type]

    async def _maybe_continue(
        self,
        *,
        session_id: str,
        intent: IntentCard | None,
        previous: str,
        send: SendFn,
        climate: str | None,
        decision: Decision | None,
        abort_check: AbortCheck | None = None,
        interrupt_ctx: InnerState | None = None,
        on_life_action: LifeActionFn | None = None,
    ) -> None:
        if intent is None or not intent.followup_ok:
            return
        if not self.config.proactive.continue_line.enabled:
            return
        if not (previous or "").strip():
            return
        if should_skip_continue(previous):
            logger.info(
                "continue skipped session=%s reason=already_two_sentences",
                session_id,
            )
            return
        delay = float(self.config.proactive.continue_line.delay_sec or 0)
        if delay > 0:
            logger.info("continue delay session=%s sec=%s", session_id, delay)
            await asyncio.sleep(delay)
        if abort_check is not None and abort_check():
            logger.info("continue aborted session=%s", session_id)
            return
        logger.info("continue start session=%s", session_id)
        await self.handle_initiate(
            session_id=session_id,
            kind="continue",
            instruction=build_continue_instruction(previous),
            history_marker=HISTORY_CONTINUE_MARKER,
            send=send,
            retrieve_memory=False,
            climate=climate,
            decision=decision,
            continue_previous=previous.strip(),
            interrupt_ctx=interrupt_ctx,
            on_life_action=on_life_action,
        )

    def _climate_block(self, decision: Decision | None) -> str:
        if decision is None:
            return ""
        return planner_climate_block(decision)

    def _local_hint(self, decision: Decision | None) -> str | None:
        if decision is None:
            return None
        return local_system_hint(decision)

    def _welcome_climate_block(
        self, climate: str | None, *, closing_hint: str
    ) -> str:
        if not climate:
            return ""
        from .relationship.policy import CLIMATE_LABELS

        label = CLIMATE_LABELS.get(climate, climate)
        if closing_hint == WELCOME_CLOSING_QUESTION:
            draft_note = "draft 以问候为主，允许一句轻问。"
        else:
            draft_note = "draft 以问候为主，使用陈述句收尾。"
        return (
            f"【关系气候】{label}\n"
            f"【建议姿态】简短迎接；{closing_hint}\n"
            "【本轮禁区】把问题抛回老师；\n"
            f"{draft_note}不要提及关系数值、信任度、依赖度或张力。"
        )

    def _merge_decision_into_intent(
        self, intent: IntentCard, decision: Decision | None
    ) -> None:
        """Relationship climate already reaches Planner via climate_block.

        V2.4: do not mutate draft from Decision card fields (must_not/stance/tone).
        """
        _ = intent, decision
        return

    async def _skip_generation(
        self,
        *,
        session_id: str,
        user_text: str,
        decision: Decision | None,
        send: SendFn,
        reason: str | None = None,
        latency: float = 0.0,
        emotion: str = DEFAULT_EMOTION,
        on_sent: Callable[[], None] | None = None,
    ) -> None:
        action = "silence" if reason == "reply_ok_false" else (
            decision.action if decision is not None else "silence"
        )
        await send(
            msg_chat_response(
                "",
                context_used=action,
                latency=round(latency, 4),
                emotion=emotion,
            )
        )
        if on_sent is not None:
            on_sent()
        key = "silence_count" if action == "silence" else "refuse_count"
        self.stats[key] = int(self.stats.get(key, 0)) + 1
        self.conversations.append(session_id, "user", user_text)
        if decision is not None:
            self._note_arona_relationship(decision, action)
        logger.info(
            "chat skipped session=%s action=%s climate=%s user_act=%s reason=%s request=%r",
            session_id,
            action,
            decision.climate if decision is not None else None,
            decision.user_act if decision is not None else None,
            reason or action,
            user_text,
        )

    async def _maybe_extract(self, session_id: str, user_text: str) -> None:
        # Buffer this completed turn (history was already appended by caller).
        history = self.conversations.get_history(session_id)
        if len(history) >= 2:
            self.conversations.append_extract_buffer(
                session_id, history[-2]["role"], history[-2]["content"]
            )
            self.conversations.append_extract_buffer(
                session_id, history[-1]["role"], history[-1]["content"]
            )

        ext = self.config.memory.extractor
        turn_count = self.conversations.turn_count(session_id)
        buffer_turns = self.conversations.extract_buffer_turn_count(session_id)
        disclose = (
            not is_crisis_text(user_text)
            and classify_user_act(user_text) == "self_disclose"
        )
        follows_followup = history_follows_proactive_marker(history)
        if (
            not disclose
            and not follows_followup
            and not should_extract(
                user_text,
                turn_count=turn_count,
                every_n_turns=ext.every_n_turns,
                buffer_turns=buffer_turns,
                extract_buffer_turns=ext.extract_buffer_turns,
            )
        ):
            logger.info(
                "memory extract skipped session=%s turns=%d buffer_turns=%d",
                session_id,
                turn_count,
                buffer_turns,
            )
            return

        transcript = self.conversations.extract_buffer_transcript(session_id)
        if not transcript:
            logger.info("memory extract skipped session=%s reason=empty_transcript", session_id)
            return
        logger.info(
            "memory extract enqueue session=%s turns=%d buffer_turns=%d transcript=%s",
            session_id,
            turn_count,
            buffer_turns,
            preview(transcript, 300),
        )
        user_turns = self.conversations.extract_buffer_user_texts(session_id)
        await self.extractor.enqueue(
            transcript=transcript,
            user_text=user_text,
            user_turns=user_turns,
        )
        self.conversations.clear_extract_buffer(session_id)
