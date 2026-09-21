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

"""WebSocket connection handler for Qt-compatible protocol."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .computer_use import (
    AGENT_CANCELLED_REPLY,
    AGENT_SPEAK_FALLBACK,
    PROBE_DISABLED_REPLY,
    ComputerUseObservation,
    ComputerUseRouter,
    ProbeResult,
    SchemaError,
    VisionClient,
    build_computer_use_instruction,
    computer_use_history_content,
    is_denied_computer_use,
    is_probe_text,
    parse_observation,
    probe_actions,
    race_route_and_chat,
    run_probe,
    run_vision_agent,
    terminal_messages,
)
from .config import AppConfig
from .conversation import ConversationManager
from .image_input import (
    ImagePayload,
    parse_optional_image,
    redact_request_json,
    save_screenshot,
)
from .input_filter import (
    ASR_FALLBACK_EMOTION,
    ASR_FALLBACK_REPLY,
    is_unusable_user_text,
)
from .interact import parse_duration_ms, resolve_interact_action
from .life import (
    Impulse,
    InnerState,
    LifeEngine,
    PresenceGate,
    WorldKind,
    apply_turn_action,
    flush_impulse,
    note_teacher_turn,
    offer_impulse,
    publish_presence,
    schedule_presence,
    world_event,
)
from .logging_utils import begin_trace, format_interactive_log, preview, reset_trace
from .orchestrator import Orchestrator
from .proactive import (
    ConnectionHub,
    HISTORY_FESTIVAL_MARKER,
    HISTORY_USER_MARKER,
    ProactiveScheduler,
    WelcomeState,
    build_festival_instruction,
    build_welcome_instruction,
    pick_welcome_closing_hint,
    resolve_welcome_context,
)
from .proactive.goal import wants_goal_mute
from .proactive.loop import load_birthday_content
from .protocol import (
    CODE_BAD_REQUEST,
    CODE_INTERNAL,
    CODE_INVALID_JSON,
    TYPE_CHAT,
    TYPE_CHAT_RESPONSE,
    TYPE_CLEAR_SESSION,
    TYPE_COMPUTER_USE_OBSERVATION,
    TYPE_CONNECTED,
    TYPE_GET_STATS,
    TYPE_INTERRUPT,
    TYPE_INTERACT,
    TYPE_LISTEN_STATE,
    TYPE_PING,
    TYPE_PONG,
    TYPE_TRANSCRIPT,
    msg_chat_response,
    msg_computer_use_done,
    msg_connected,
    msg_error,
    msg_pong,
    msg_result,
    msg_stats,
)
from .turntaking import (
    TurnBuffer,
    is_teacher_speaker,
    looks_incomplete,
)
from .turntaking.speaker import normalize_speaker

logger = logging.getLogger(__name__)


class AppState:
    def __init__(
        self,
        config: AppConfig,
        orchestrator: Orchestrator,
        conversations: ConversationManager,
        welcome: WelcomeState | None = None,
        hub: ConnectionHub | None = None,
        scheduler: ProactiveScheduler | None = None,
        life: LifeEngine | None = None,
    ) -> None:
        self.config = config
        self.orchestrator = orchestrator
        self.conversations = conversations
        self.welcome = welcome or WelcomeState()
        self.hub = hub or ConnectionHub()
        self.scheduler = scheduler
        self.life = life
        self.presence = PresenceGate()
        self.hub.set_on_all_idle(lambda: schedule_presence(self))


async def websocket_endpoint(websocket: WebSocket, state: AppState) -> None:
    await websocket.accept()
    session_id = str(uuid.uuid4())
    client = getattr(websocket, "client", None)
    client_host = getattr(client, "host", None) if client else None
    client_port = getattr(client, "port", None) if client else None
    logger.info(
        "WS connected session=%s client=%s:%s",
        session_id,
        client_host,
        client_port,
    )

    chat_recv_at: float | None = None

    turn_buffer = TurnBuffer()
    listen_cfg = state.config.listen
    generation_id = 0
    inflight_user: str | None = None
    commit_task: asyncio.Task[None] | None = None
    wait_extended = False

    async def send(payload: dict[str, Any]) -> None:
        msg_type = payload.get("type")
        if msg_type == TYPE_CHAT_RESPONSE:
            if str(payload.get("content") or "").strip():
                turn_buffer.note_arona_spoke()
                if state.life is not None:
                    state.life.note_arona_spoke()
            logger.info("%s", format_interactive_log(payload))
            reset_trace()
            logger.info(
                "WS send session=%s type=%s context=%s latency=%s content=%r",
                session_id,
                msg_type,
                payload.get("context_used"),
                payload.get("latency"),
                payload.get("content", ""),
            )
        elif msg_type not in (TYPE_PONG, TYPE_CONNECTED):
            logger.info(
                "WS send session=%s type=%s payload=%s",
                session_id,
                msg_type,
                preview(json.dumps(payload, ensure_ascii=False), 240),
            )
        await websocket.send_text(json.dumps(payload, ensure_ascii=False))

    await send(msg_connected(session_id))
    state.hub.register(session_id, send)
    if state.scheduler is not None:
        state.scheduler.note_user_activity()

    def _note_life(kind: WorldKind) -> None:
        if state.life is None:
            return
        state.life.apply(world_event(kind, session_id=session_id))
        schedule_presence(state)

    def _note_teacher_turn(kind: WorldKind) -> InnerState | None:
        return note_teacher_turn(state, kind, session_id=session_id)

    def _on_life_action(action: str, emotion: str) -> None:
        apply_turn_action(state, action, emotion)

    _note_life("teacher_arrived")
    if state.life is not None:
        await publish_presence(state, force_session=session_id)

    chat_task: asyncio.Task[None] | None = None
    inflight_kind: str | None = None
    cu_observations: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    cu_run_id: str | None = None

    def _clear_inflight() -> None:
        nonlocal inflight_user
        inflight_user = None

    async def _cancel_commit() -> None:
        nonlocal commit_task
        task = commit_task
        commit_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _persist_screenshot(image: ImagePayload) -> None:
        try:
            await asyncio.to_thread(
                save_screenshot,
                state.config.logging_dir_abs_path,
                image,
            )
        except Exception:
            logger.warning("screenshot persist failed session=%s", session_id, exc_info=True)

    async def _run_chat(
        content: str,
        options: dict[str, Any],
        request_json: str | None,
        started_at: float | None,
        abort_check: Any | None = None,
        image: ImagePayload | None = None,
        send_fn: Any | None = None,
        release_busy: bool = True,
        interrupt_ctx: InnerState | None = None,
    ) -> None:
        nonlocal inflight_kind
        inflight_kind = "chat"
        outbound = send_fn or send
        state.hub.set_busy(session_id, True)
        if state.scheduler is not None:
            if wants_goal_mute(content):
                muted = state.scheduler.mute_last_followup()
                if muted:
                    logger.info("followup muted by user key=%s", muted)
            else:
                acked = state.scheduler.ack_pending_followups()
                if acked:
                    logger.info("followup acked by user keys=%s", acked)
            state.scheduler.note_user_activity()
        try:
            await state.orchestrator.handle_chat(
                session_id=session_id,
                content=content,
                options=options,
                send=outbound,
                request_json=request_json,
                started_at=started_at,
                abort_check=abort_check,
                on_committed=_clear_inflight,
                image=image,
                interrupt_ctx=interrupt_ctx,
                on_life_action=_on_life_action,
            )
            if inflight_user:
                turn_buffer.prepend(inflight_user)
                _clear_inflight()
        except asyncio.CancelledError:
            logger.info("chat cancelled session=%s", session_id)
            raise
        except Exception as exc:
            logger.exception("Handler error session=%s", session_id)
            try:
                await outbound(msg_error(CODE_INTERNAL, str(exc)))
            except Exception:
                pass
        finally:
            inflight_kind = None
            if release_busy:
                state.hub.set_busy(session_id, False)

    def _drain_cu_observations() -> None:
        while True:
            try:
                cu_observations.get_nowait()
            except asyncio.QueueEmpty:
                return

    async def _wait_cu_observation(
        run_id: str,
        step: int,
    ) -> ComputerUseObservation | None:
        timeout = max(0.1, float(state.config.computer_use.observation_timeout_sec))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                raw = await asyncio.wait_for(cu_observations.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            try:
                observation = parse_observation(raw)
            except SchemaError as exc:
                logger.info(
                    "computer_use observation dropped session=%s reason=%s",
                    session_id,
                    exc,
                )
                continue
            if observation.run_id != run_id:
                logger.info(
                    "computer_use observation dropped session=%s reason=run_id "
                    "want=%s got=%s",
                    session_id,
                    run_id,
                    observation.run_id,
                )
                continue
            if observation.step != step:
                logger.info(
                    "computer_use observation dropped session=%s reason=step "
                    "want=%s got=%s",
                    session_id,
                    step,
                    observation.step,
                )
                continue
            if observation.image is not None:
                asyncio.create_task(_persist_screenshot(observation.image))
            return observation

    async def _send_probe_terminal(result: ProbeResult) -> None:
        for payload in terminal_messages(result):
            await send(payload)

    async def _speak_computer_use_result(user_text: str, result: ProbeResult) -> bool:
        decision = None
        climate = None
        relationship = state.orchestrator.relationship
        if (
            relationship is not None
            and state.config.proactive.relationship.enabled
        ):
            _act, decision = relationship.on_user_act("instrumental")
            climate = decision.climate
        outcome = await state.orchestrator.handle_initiate(
            session_id=session_id,
            kind="computer_use",
            instruction=build_computer_use_instruction(
                user_text=user_text,
                summary=result.summary,
                ok=result.ok,
            ),
            history_marker=computer_use_history_content(user_text),
            send=send,
            retrieve_memory=False,
            climate=climate,
            decision=decision,
            context_tags=["computer_use"],
        )
        return outcome == "sent"

    async def _send_agent_terminal(
        result: ProbeResult,
        *,
        user_text: str,
        speak: bool,
    ) -> None:
        await send(
            msg_computer_use_done(
                result.run_id,
                ok=result.ok,
                summary=result.summary,
            )
        )
        if not speak:
            await send(
                msg_chat_response(
                    AGENT_CANCELLED_REPLY
                    if result.reason == "cancelled"
                    else AGENT_SPEAK_FALLBACK,
                    context_used="computer_use",
                )
            )
            return
        spoken = False
        try:
            spoken = await _speak_computer_use_result(user_text, result)
        except Exception:
            logger.exception(
                "computer_use initiate failed session=%s",
                session_id,
            )
        if not spoken:
            await send(
                msg_chat_response(
                    AGENT_SPEAK_FALLBACK,
                    context_used="computer_use",
                )
            )

    async def _run_computer_use_session(
        *,
        mode: str,
        user_text: str = "",
    ) -> None:
        nonlocal inflight_kind, cu_run_id
        inflight_kind = "computer_use"
        state.hub.set_busy(session_id, True)
        if state.scheduler is not None:
            state.scheduler.note_user_activity()
        cfg = state.config.computer_use
        sent_terminal = False
        cu_run_id = str(uuid.uuid4())
        cu_generation = generation_id
        _drain_cu_observations()
        cancelled = ProbeResult(
            ok=False,
            summary="cancelled",
            run_id=cu_run_id,
            steps_completed=0,
            reason="cancelled",
        )
        failed = ProbeResult(
            ok=False,
            summary="internal_error",
            run_id=cu_run_id,
            steps_completed=0,
            reason="observation_failed",
        )
        try:
            if mode == "probe":
                if not cfg.enabled or not cfg.probe_enabled:
                    logger.info(
                        "computer_use probe rejected session=%s enabled=%s probe=%s",
                        session_id,
                        cfg.enabled,
                        cfg.probe_enabled,
                    )
                    await send(
                        msg_chat_response(
                            PROBE_DISABLED_REPLY,
                            context_used="computer_use",
                        )
                    )
                    sent_terminal = True
                    return
                result = await run_probe(
                    send=send,
                    wait_observation=_wait_cu_observation,
                    abort_check=lambda: generation_id != cu_generation,
                    run_id=cu_run_id,
                    max_steps=len(probe_actions()),
                )
                await _send_probe_terminal(result)
                sent_terminal = True
                return
            result = await run_vision_agent(
                send=send,
                wait_observation=_wait_cu_observation,
                client=VisionClient(state.config.planner, cfg),
                user_text=user_text,
                abort_check=lambda: generation_id != cu_generation,
                run_id=cu_run_id,
                max_steps=max(1, int(cfg.max_steps or 8)),
            )
            await _send_agent_terminal(
                result,
                user_text=user_text,
                speak=result.reason != "cancelled",
            )
            sent_terminal = True
        except asyncio.CancelledError:
            logger.info("computer_use cancelled session=%s mode=%s", session_id, mode)
            if not sent_terminal:
                try:
                    if mode == "probe":
                        await _send_probe_terminal(cancelled)
                    else:
                        await _send_agent_terminal(
                            cancelled,
                            user_text=user_text,
                            speak=False,
                        )
                except Exception:
                    logger.exception(
                        "computer_use cancel notify failed session=%s",
                        session_id,
                    )
            raise
        except Exception:
            logger.exception("computer_use error session=%s mode=%s", session_id, mode)
            if not sent_terminal:
                try:
                    if mode == "probe":
                        await _send_probe_terminal(failed)
                    else:
                        await _send_agent_terminal(
                            failed,
                            user_text=user_text,
                            speak=True,
                        )
                except Exception:
                    pass
        finally:
            inflight_kind = None
            cu_run_id = None
            _drain_cu_observations()
            state.hub.set_busy(session_id, False)

    async def _run_computer_use_probe() -> None:
        await _run_computer_use_session(mode="probe")

    async def _run_computer_use_agent(user_text: str) -> None:
        await _run_computer_use_session(mode="agent", user_text=user_text)

    async def _run_routed_user_turn(
        content: str,
        options: dict[str, Any],
        request_json: str,
        started_at: float,
        abort_check,
        image: ImagePayload | None,
        interrupt_ctx: InnerState | None = None,
    ) -> None:
        nonlocal inflight_user
        cfg = state.config.computer_use
        if not cfg.enabled or is_denied_computer_use(content):
            await _run_chat(
                content,
                options,
                request_json,
                started_at,
                abort_check,
                image,
                interrupt_ctx=interrupt_ctx,
            )
            return

        operated = False
        state.hub.set_busy(session_id, True)
        try:
            router = ComputerUseRouter(state.config.planner, cfg)
            history = state.conversations.get_history(session_id)

            async def route() -> bool:
                return await router.should_operate(content, history=history)

            async def run_chat(gated_send) -> None:
                await _run_chat(
                    content,
                    options,
                    request_json,
                    started_at,
                    abort_check,
                    image,
                    send_fn=gated_send,
                    release_busy=False,
                    interrupt_ctx=interrupt_ctx,
                )

            async def run_cu() -> None:
                nonlocal inflight_user
                inflight_user = None
                logger.info(
                    "computer_use agent start session=%s text=%r",
                    session_id,
                    content,
                )
                await _run_computer_use_agent(content)

            operated = await race_route_and_chat(
                route=route,
                run_chat=run_chat,
                run_cu=run_cu,
                send=send,
            )
        finally:
            if not operated:
                state.hub.set_busy(session_id, False)

    async def _interrupt_generation(*, restore_inflight: bool) -> None:
        nonlocal chat_task, generation_id, inflight_user
        generation_id += 1
        if restore_inflight and inflight_user:
            turn_buffer.prepend(inflight_user)
            inflight_user = None
        if chat_task is not None and not chat_task.done():
            chat_task.cancel()
            try:
                await chat_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception(
                    "Error while interrupting chat task session=%s", session_id
                )

    async def _commit_turn(*, force: bool = False) -> None:
        nonlocal commit_task, chat_task, inflight_user, wait_extended, generation_id
        commit_task = None
        if not force and not turn_buffer.listening:
            return
        image = turn_buffer.pop_image()
        drained = turn_buffer.drain()
        if not drained or is_unusable_user_text(drained):
            logger.info(
                "listen commit skipped session=%s reason=unusable text=%r",
                session_id,
                drained,
            )
            return
        wait_extended = False
        logger.info(
            "listen commit session=%s has_image=%s text=%r",
            session_id,
            image is not None,
            drained,
        )
        if chat_task is not None and not chat_task.done():
            await _interrupt_generation(restore_inflight=True)
        if is_probe_text(drained, state.config.computer_use.probe_token):
            logger.info("listen commit computer_use probe session=%s", session_id)
            inflight_user = None
            chat_task = asyncio.create_task(_run_computer_use_probe())
            return
        transcript_ctx = _note_teacher_turn("teacher_transcript")
        my_id = generation_id
        inflight_user = drained
        started = time.perf_counter()
        request_json = json.dumps(
            {
                "type": "transcript",
                "content": drained,
                "has_image": image is not None,
            },
            ensure_ascii=False,
        )
        chat_task = asyncio.create_task(
            _run_routed_user_turn(
                drained,
                {},
                request_json,
                started,
                lambda: generation_id != my_id,
                image,
                interrupt_ctx=transcript_ctx,
            )
        )

    async def _commit_after(delay_sec: float) -> None:
        try:
            await asyncio.sleep(delay_sec)
            await _commit_turn()
        except asyncio.CancelledError:
            raise

    def _schedule_commit() -> None:
        nonlocal commit_task, wait_extended
        wait_extended = False
        if commit_task is not None and not commit_task.done():
            commit_task.cancel()
        delay_ms = listen_cfg.silence_commit_ms
        if looks_incomplete(turn_buffer.last_text()):
            delay_ms = listen_cfg.incomplete_commit_ms
            wait_extended = True
        commit_task = asyncio.create_task(_commit_after(max(0.05, delay_ms / 1000.0)))

    async def _run_welcome() -> None:
        nonlocal inflight_kind
        inflight_kind = "welcome"
        try:
            slot, first = resolve_welcome_context(state.welcome)
            logger.info(
                "welcome trigger session=%s slot=%s first=%s date=%s",
                session_id,
                slot.slot_id,
                first,
                slot.date_key,
            )
            engine = state.life
            if engine is None:
                logger.info("welcome skipped session=%s reason=no_life_engine", session_id)
                return
            climate = None
            relationship = state.orchestrator.relationship
            if (
                relationship is not None
                and state.config.proactive.relationship.enabled
            ):
                climate = relationship.peek_climate()

            now = datetime.now()
            hit = None
            if state.scheduler is not None:
                birthday = await load_birthday_content(state)
                hit = state.scheduler.pending_festival(birthday_content=birthday)
            if hit is not None:
                allow_speak = True
                if (
                    relationship is not None
                    and state.config.proactive.relationship.enabled
                ):
                    gate = relationship.decide_proactive("festival")
                    allow_speak = gate.action == "initiate"
                    if not allow_speak:
                        logger.info(
                            "festival welcome withheld by climate climate=%s action=%s",
                            gate.climate,
                            gate.action,
                        )
                extras = (hit.extra_memory,) if hit.extra_memory else ()
                offer_impulse(
                    engine,
                    Impulse(
                        kind="festival",
                        created_at=now.replace(microsecond=0),
                        source_id=hit.id,
                        instruction=build_festival_instruction(hit, climate),
                        history_marker=HISTORY_FESTIVAL_MARKER,
                        extra_memories=extras,
                        allow_speak=allow_speak,
                        first_in_slot=first,
                        slot_id=str(slot.slot_id),
                        date_key=slot.date_key,
                    ),
                )
            else:
                closing_hint = pick_welcome_closing_hint()
                offer_impulse(
                    engine,
                    Impulse(
                        kind="welcome",
                        created_at=now.replace(microsecond=0),
                        instruction=build_welcome_instruction(
                            slot,
                            first_in_slot=first,
                            climate=climate,
                            closing_hint=closing_hint,
                        ),
                        history_marker=HISTORY_USER_MARKER,
                        allow_speak=True,
                        first_in_slot=first,
                        slot_id=str(slot.slot_id),
                        date_key=slot.date_key,
                    ),
                )
            ok = await flush_impulse(state, now=now, session_id=session_id)
            if not ok:
                pending = engine.state.pending_impulse
                if pending is not None:
                    logger.warning(
                        "welcome impulse deferred session=%s pending=%s",
                        session_id,
                        pending.kind,
                    )
                else:
                    logger.info(
                        "welcome impulse withheld session=%s",
                        session_id,
                    )
        except asyncio.CancelledError:
            logger.info("welcome cancelled session=%s", session_id)
            raise
        except Exception:
            logger.exception("welcome error session=%s", session_id)
        finally:
            inflight_kind = None

    async def _run_interact(action: str, duration_ms: int) -> None:
        nonlocal inflight_kind
        inflight_kind = "interact"
        state.hub.set_busy(session_id, True)
        if state.scheduler is not None:
            state.scheduler.note_user_activity()
        interact_ctx = _note_teacher_turn("teacher_touched")
        try:
            await state.orchestrator.handle_interact(
                session_id=session_id,
                action=action,
                duration_ms=duration_ms,
                send=send,
                interrupt_ctx=interact_ctx,
                on_life_action=_on_life_action,
            )
        except asyncio.CancelledError:
            logger.info("interact cancelled session=%s action=%s", session_id, action)
            raise
        except Exception as exc:
            logger.exception("interact error session=%s action=%s", session_id, action)
            try:
                await send(msg_error(CODE_INTERNAL, str(exc)))
            except Exception:
                pass
        finally:
            inflight_kind = None
            state.hub.set_busy(session_id, False)

    if state.config.proactive.welcome.enabled:
        chat_task = asyncio.create_task(_run_welcome())
    else:
        logger.info("welcome skipped session=%s reason=disabled", session_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(
                    "WS invalid JSON session=%s raw=%s",
                    session_id,
                    preview(raw, 200),
                )
                await send(msg_error(CODE_INVALID_JSON, "Invalid JSON"))
                continue

            if not isinstance(data, dict):
                logger.warning("WS non-object message session=%s", session_id)
                await send(msg_error(CODE_BAD_REQUEST, "Message must be a JSON object"))
                continue

            msg_type = data.get("type")
            try:
                if msg_type == TYPE_PING:
                    logger.debug("WS ping session=%s", session_id)
                    await send(msg_pong())
                elif msg_type == TYPE_CLEAR_SESSION:
                    logger.info("WS clear_session session=%s", session_id)
                    state.conversations.clear(session_id)
                    await send(msg_result(True, "session cleared"))
                elif msg_type == TYPE_GET_STATS:
                    logger.info("WS get_stats session=%s", session_id)
                    await send(
                        msg_stats(
                            {
                                "session_id": session_id,
                                "memory_count": state.orchestrator.memory_store.count(),
                                **state.orchestrator.stats,
                            }
                        )
                    )
                elif msg_type == TYPE_CHAT:
                    busy = (
                        (chat_task is not None and not chat_task.done())
                        or state.hub.is_busy(session_id)
                    )
                    if busy:
                        if inflight_kind == "interact":
                            logger.info(
                                "WS chat preempts interact session=%s",
                                session_id,
                            )
                            await _interrupt_generation(restore_inflight=False)
                        else:
                            logger.warning(
                                "WS chat rejected session=%s reason=in_progress",
                                session_id,
                            )
                            await send(
                                msg_error(
                                    CODE_BAD_REQUEST,
                                    "A chat request is already in progress",
                                )
                            )
                            continue
                    chat_recv_at = time.perf_counter()
                    content = data.get("content", "")
                    options = data.get("options") or {}
                    if not isinstance(options, dict):
                        options = {}
                    image = parse_optional_image(data)
                    logger.info(
                        "WS chat recv session=%s options=%s has_image=%s bytes=%s "
                        "content=%r",
                        session_id,
                        options,
                        image is not None,
                        len(image.data) if image is not None else 0,
                        content,
                    )
                    if is_unusable_user_text(str(content)):
                        logger.warning(
                            "WS chat dropped session=%s reason=unusable_user_text "
                            "content=%r",
                            session_id,
                            content,
                        )
                        begin_trace(
                            started_at=chat_recv_at,
                            request_json=redact_request_json(raw),
                        )
                        await send(
                            msg_chat_response(
                                ASR_FALLBACK_REPLY,
                                context_used="asr_filter",
                                latency=0.0,
                                emotion=ASR_FALLBACK_EMOTION,
                            )
                        )
                        continue
                    if image is not None:
                        asyncio.create_task(_persist_screenshot(image))
                    if is_probe_text(
                        str(content),
                        state.config.computer_use.probe_token,
                    ):
                        logger.info("WS computer_use probe session=%s", session_id)
                        chat_task = asyncio.create_task(_run_computer_use_probe())
                        continue
                    spoke_ctx = _note_teacher_turn("teacher_spoke")
                    chat_task = asyncio.create_task(
                        _run_routed_user_turn(
                            str(content),
                            options,
                            redact_request_json(raw),
                            chat_recv_at,
                            None,
                            image,
                            interrupt_ctx=spoke_ctx,
                        )
                    )
                elif msg_type == TYPE_COMPUTER_USE_OBSERVATION:
                    logger.info(
                        "WS computer_use observation session=%s payload=%s",
                        session_id,
                        preview(redact_request_json(raw) or "", 240),
                    )
                    if inflight_kind != "computer_use":
                        logger.info(
                            "WS computer_use observation dropped session=%s "
                            "reason=not_in_probe",
                            session_id,
                        )
                        continue
                    await cu_observations.put(data)
                elif msg_type == TYPE_INTERACT:
                    if not state.config.interact.enabled:
                        logger.info(
                            "WS interact rejected session=%s reason=disabled",
                            session_id,
                        )
                        await send(msg_error(CODE_BAD_REQUEST, "Interact is disabled"))
                        continue
                    spec = resolve_interact_action(data.get("action"))
                    if spec is None:
                        logger.warning(
                            "WS interact rejected session=%s reason=unknown_action action=%r",
                            session_id,
                            data.get("action"),
                        )
                        await send(
                            msg_error(CODE_BAD_REQUEST, "Unknown interact action")
                        )
                        continue
                    if (chat_task is not None and not chat_task.done()) or state.hub.is_busy(
                        session_id
                    ):
                        logger.info(
                            "WS interact dropped session=%s reason=busy kind=%s action=%s",
                            session_id,
                            inflight_kind,
                            spec.action,
                        )
                        continue
                    duration_ms = parse_duration_ms(data.get("duration_ms"))
                    logger.info(
                        "WS interact recv session=%s action=%s duration_ms=%s",
                        session_id,
                        spec.action,
                        duration_ms,
                    )
                    chat_task = asyncio.create_task(
                        _run_interact(spec.action, duration_ms)
                    )
                elif msg_type == TYPE_LISTEN_STATE:
                    raw_state = data.get("state") or data.get("listening")
                    if isinstance(raw_state, bool):
                        listening = raw_state
                    else:
                        listening = str(raw_state or "").strip().lower() in {
                            "on",
                            "true",
                            "1",
                            "start",
                        }
                    logger.info(
                        "WS listen_state session=%s listening=%s",
                        session_id,
                        listening,
                    )
                    await _cancel_commit()
                    wait_extended = False
                    if listening:
                        turn_buffer.set_listening(True)
                        state.hub.set_listening(session_id, True)
                        _note_life("listen_on")
                    else:
                        logger.info(
                            "WS listen stop flush session=%s pending=%r",
                            session_id,
                            turn_buffer.joined(),
                        )
                        await _commit_turn(force=True)
                        turn_buffer.set_listening(False)
                        state.hub.set_listening(session_id, False)
                        _note_life("listen_off")
                elif msg_type == TYPE_TRANSCRIPT:
                    text = str(data.get("content") or data.get("text") or "")
                    speaker = normalize_speaker(data.get("speaker"))
                    is_final = bool(data.get("is_final", True))
                    silence_ms = int(data.get("silence_ms") or 0)
                    segment_id = str(data.get("segment_id") or "")
                    image = parse_optional_image(data)
                    logger.info(
                        "WS transcript session=%s final=%s speaker=%s silence_ms=%s "
                        "segment=%s has_image=%s bytes=%s content=%r",
                        session_id,
                        is_final,
                        speaker,
                        silence_ms,
                        segment_id,
                        image is not None,
                        len(image.data) if image is not None else 0,
                        text,
                    )
                    if not turn_buffer.listening:
                        logger.info(
                            "WS transcript ignored session=%s reason=not_listening",
                            session_id,
                        )
                        continue
                    if not is_final:
                        continue
                    if not is_teacher_speaker(speaker):
                        logger.info(
                            "WS transcript dropped session=%s reason=non_teacher speaker=%s",
                            session_id,
                            speaker,
                        )
                        continue
                    if is_unusable_user_text(text):
                        logger.info(
                            "WS transcript dropped session=%s reason=unusable content=%r",
                            session_id,
                            text,
                        )
                        continue
                    if state.scheduler is not None:
                        state.scheduler.note_user_activity()
                    turn_buffer.push(
                        text=text,
                        speaker=speaker,
                        segment_id=segment_id,
                        silence_ms=silence_ms,
                        image=image,
                    )
                    if image is not None:
                        asyncio.create_task(_persist_screenshot(image))
                    _schedule_commit()
                elif msg_type == TYPE_INTERRUPT:
                    logger.info("WS interrupt session=%s", session_id)
                    _note_teacher_turn("teacher_interrupt")
                    await _interrupt_generation(restore_inflight=True)
                    if state.scheduler is not None:
                        state.scheduler.note_user_activity()
                else:
                    logger.warning(
                        "WS unknown type session=%s type=%r",
                        session_id,
                        msg_type,
                    )
                    await send(msg_error(CODE_BAD_REQUEST, f"Unknown type: {msg_type}"))
            except Exception as exc:
                logger.exception("Handler error session=%s", session_id)
                await send(msg_error(CODE_INTERNAL, str(exc)))
    except WebSocketDisconnect:
        logger.info("WS disconnected session=%s", session_id)
    finally:
        if commit_task is not None and not commit_task.done():
            commit_task.cancel()
            try:
                await commit_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception(
                    "Error while cancelling listen commit session=%s", session_id
                )
        if chat_task is not None and not chat_task.done():
            chat_task.cancel()
            try:
                await chat_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Error while cancelling chat task session=%s", session_id)
        state.hub.unregister(session_id)
        state.conversations.drop(session_id)
        _note_life("teacher_left")
