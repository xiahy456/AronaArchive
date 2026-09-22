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

"""AronaAI backend entrypoint."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from .config import get_config
from .conversation import ConversationManager
from .embeddings import LocalBgeEncoder, bge_missing_reason
from .knowledge import KnowledgeRetriever
from .life import LifeEngine, run_life_loop
from .life.arona_memory import AronaMemory
from .life.journal import LifeJournal
from .logging_utils import configure_logging
from .memory.extractor import MemoryExtractor
from .memory.store import MemoryStore
from .model_loader import get_model_loader
from .orchestrator import Orchestrator
from .planner import PlannerClient
from .proactive import ConnectionHub, ProactiveScheduler, WelcomeState, run_proactive_loop
from .relationship import RelationshipEngine, RelationshipSettings
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
    model = get_model_loader()
    conversations = ConversationManager(
        max_history_turns=config.conversation.max_history_turns
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
    if config.life.enabled:
        life = LifeEngine.from_config(config.life_abs_path, config.life)
        journal = LifeJournal(config.journal_abs_path)
        arona_memory = AronaMemory(config.arona_memory_abs_path)
        journal.seed(life.state)
        life.journal = journal
        life.arona_memory = arona_memory
        orchestrator.life_journal = journal
        orchestrator.arona_memory = arona_memory
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
    state.glance_request_id = ""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log_path = configure_logging()
        logger.info("Starting AronaAI backend")
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
        app.state.arona = state  # type: ignore[attr-defined]
        yield
        if life_task is not None:
            life_task.cancel()
            try:
                await life_task
            except asyncio.CancelledError:
                pass
        if loop_task is not None:
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass
        await extractor.stop()
        logger.info("AronaAI backend stopped")

    app = FastAPI(title="AronaAI Backend", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    ws_path = config.server.ws_path or "/ws"

    @app.websocket(ws_path)
    async def ws_route(websocket: WebSocket) -> None:
        await websocket_endpoint(websocket, state)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    config = get_config()
    _configure_stdio_utf8()
    configure_logging()
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
