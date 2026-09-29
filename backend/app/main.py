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

"""AronaArchive backend entrypoint."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, WebSocket

from .config import AppConfig, get_config
from .conversation import ConversationManager
from .embeddings import LocalBgeEncoder, bge_missing_reason
from .knowledge import KnowledgeRetriever
from .life import LifeEngine, run_life_loop
from .life.arona_memory import AronaMemory
from .life.impulse import expire_stale_care
from .life.journal import LifeJournal
from .life.thought import ThoughtLedger, ThoughtStore
from .life.thought.loop import run_thought_loop
from .logging_utils import configure_logging
from .memory.extractor import MemoryExtractor
from .memory.store import MemoryStore
from .model_loader import get_model_loader
from .orchestrator import Orchestrator
from .planner import PlannerClient
from .proactive import ConnectionHub, ProactiveScheduler, WelcomeState, run_proactive_loop
from .relationship import RelationshipEngine, RelationshipSettings
from .napcat import NapcatLink, QqInbox, napcat_endpoint
from .ws_auth import startup_token_error
from .ws_handler import AppState, websocket_endpoint


def _configure_stdio_utf8() -> None:
    """Force UTF-8 for terminal / redirected stdout & stderr (esp. Windows)."""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass


_configure_stdio_utf8()
configure_logging()
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    config = get_config()
    token_error = startup_token_error(
        config.server.host, config.server.public, config.server.token
    )
    napcat_error = startup_token_error(
        config.server.host,
        config.server.public,
        config.napcat.napcat_token,
        setting="napcat.napcat_token",
    )
    if token_error or napcat_error:
        logger.error("%s", token_error or napcat_error)
        raise SystemExit(1)
    model = get_model_loader()
    conversations = ConversationManager(
        max_history_turns=config.conversation.max_history_turns,
        persist_path=config.dialogue_abs_path,
        max_entries=config.conversation.max_entries,
    )
    # Shared BGE encoder for memory + knowledge retrieval. Load lazily so a
    # missing models/bge-small-zh-v1.5 does not block Planner-only startup.
    shared_encoder: LocalBgeEncoder | None = None
    missing_bge = bge_missing_reason(config.knowledge_embedding_abs_path)
    if missing_bge is None:
        shared_encoder = LocalBgeEncoder(config.knowledge_embedding_abs_path)
    else:
        logger.warning("%s", missing_bge)
    memory_store = MemoryStore(config, encoder=shared_encoder)
    extractor = MemoryExtractor(memory_store, config.memory.extractor)
    knowledge = KnowledgeRetriever(config, encoder=shared_encoder)
    planner = PlannerClient(
        config.planner, renderer_enabled=config.model.enabled
    )
    relationship = RelationshipEngine.from_path(
        config.relationship_abs_path,
        RelationshipSettings.from_config(config.proactive.relationship),
    )
    orchestrator = Orchestrator(
        config,
        model=model,
        conversations=conversations,
        memory_store=memory_store,
        extractor=extractor,
        knowledge=knowledge,
        planner=planner,
        relationship=relationship,
    )
    hub = ConnectionHub()
    scheduler = ProactiveScheduler(
        config.proactive_abs_path,
        idle_cfg=config.proactive.idle,
        care_cfg=config.proactive.care,
        goal_cfg=config.proactive.goal,
        festival_cfg=config.proactive.festival,
        mood_cfg=config.proactive.mood_followup,
    )
    life = None
    journal = None
    arona_memory = None
    thought = None
    thought_store = None
    if config.life.enabled:
        from .life.impulse import IMPULSE_PRIORITY

        IMPULSE_PRIORITY["thought"] = int(config.life.thought.impulse_priority)
        life = LifeEngine.from_config(config.life_abs_path, config.life)
        life.release_startup_look()
        journal = LifeJournal(config.journal_abs_path)
        arona_memory = AronaMemory(
            config.arona_memory_abs_path,
            notes_max=config.life.thought.notes_max,
            notes_max_age_hours=config.life.thought.notes_max_age_hours,
        )
        journal.seed(life.state)
        life.journal = journal
        life.arona_memory = arona_memory
        orchestrator.life_journal = journal
        orchestrator.arona_memory = arona_memory
        try:
            thought_store = ThoughtStore(config.thought_abs_path)
            thought = thought_store.load()
        except Exception:
            logging.getLogger(__name__).exception("thought ledger load failed")
            thought = ThoughtLedger()
            thought_store = None
    state = AppState(
        config,
        orchestrator,
        conversations,
        welcome=WelcomeState(config.welcome_abs_path),
        hub=hub,
        scheduler=scheduler,
        life=life,
    )
    state.journal = journal
    state.arona_memory = arona_memory
    state.thought = thought
    state.thought_store = thought_store
    state.glance_request_id = ""
    state.napcat = NapcatLink(config.napcat.user_qq_id)
    orchestrator.napcat = state.napcat
    state.qq_inbox = QqInbox(state)
    state.generation_kind = ""
    state.generation_owner = ""
    state.generation_interrupts = {}
    expire_stale_care(state)
    from .life.thought.triggers import note_climate_enter, note_memory

    def _on_memory(key: str, category: str) -> None:
        del category
        note_memory(state, key, now=datetime.now())

    orchestrator.extractor.on_memory_upsert = _on_memory
    if orchestrator.relationship is not None:
        def _on_urgent(before: str, after: str) -> None:
            note_climate_enter(state, before, after, now=datetime.now())

        orchestrator.relationship.on_urgent_enter = _on_urgent

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log_path = configure_logging()
        logger.info("Starting AronaArchive backend")
        logger.info("Logging to %s", log_path)
        if config.model.enabled:
            model.load(config)
            await asyncio.to_thread(model.warmup)
        else:
            logger.info("Local renderer disabled; skipping GGUF load")
        await asyncio.to_thread(memory_store.warmup)
        if knowledge.enabled:
            try:
                await asyncio.to_thread(knowledge.warmup)
            except FileNotFoundError as exc:
                logger.warning("%s", exc)
            except Exception:
                logger.exception("Knowledge warmup failed; RAG will retry on first use")
        await extractor.start()
        loop_task = None
        life_task = None
        thought_task = None
        if (
            config.proactive.idle.enabled
            or config.proactive.care.enabled
            or config.proactive.goal.enabled
            or config.proactive.festival.enabled
        ):
            loop_task = asyncio.create_task(run_proactive_loop(state))
            logger.info("proactive loop started")
        if life is not None:
            life_task = asyncio.create_task(run_life_loop(state))
            logger.info("life loop started")
            if config.life.thought.enabled:
                thought_task = asyncio.create_task(run_thought_loop(state))
                logger.info("thought loop started")
        app.state.arona = state  # type: ignore[attr-defined]
        yield
        if life_task is not None:
            life_task.cancel()
            try:
                await life_task
            except asyncio.CancelledError:
                pass
        if thought_task is not None:
            thought_task.cancel()
            try:
                await thought_task
            except asyncio.CancelledError:
                pass
        if loop_task is not None:
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass
        await extractor.stop()
        logger.info("AronaArchive backend stopped")

    app = FastAPI(title="AronaArchive Backend", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    ws_path = config.server.ws_path or "/ws"
    napcat_path = config.napcat.napcat_ws_path or "/arona"
    if napcat_path == ws_path:
        logger.error("napcat_ws_path must differ from server.ws_path")
        raise SystemExit(1)

    @app.websocket(ws_path)
    async def ws_route(websocket: WebSocket) -> None:
        await websocket_endpoint(websocket, state)

    @app.websocket(napcat_path)
    async def napcat_route(websocket: WebSocket) -> None:
        await napcat_endpoint(websocket, state)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    config = get_config()
    _configure_stdio_utf8()
    configure_logging()
    ssl_certfile, ssl_keyfile = _ssl_files(config)
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        reload=False,
        log_level="info",
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )


def _ssl_files(config: AppConfig) -> tuple[str | None, str | None]:
    cert = (config.server.ssl_certfile or "").strip()
    key = (config.server.ssl_keyfile or "").strip()
    if not cert and not key:
        return None, None
    if not cert or not key:
        logger.error("server.ssl_certfile 与 server.ssl_keyfile 需要同时填写")
        raise SystemExit(1)
    return str(config.resolve_path(cert)), str(config.resolve_path(key))


if __name__ == "__main__":
    main()
