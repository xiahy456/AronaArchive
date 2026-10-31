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
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, WebSocket

from .config import BACKEND_DIR, AppConfig, get_config
from .conversation import ConversationManager
from .embeddings import LocalBgeEncoder, bge_missing_reason
from .knowledge import KnowledgeRetriever
from .life import LifeEngine, run_life_loop
from .life.arona_memory import AronaMemory
from .life.impulse import expire_stale_care
from .life.journal import LifeJournal
from .life.thought import PendingTrigger, ThoughtLedger, ThoughtStore
from .life.thought.loop import run_thought_loop
from .logging_utils import configure_logging
from .model_loader import get_model_loader
from .orchestrator import Orchestrator
from .planner import PlannerClient
from .proactive import ConnectionHub, ProactiveScheduler, WelcomeState
from .relationship import RelationshipEngine, RelationshipSettings
from .stance.stance_loop import review_day, run_stance_loop
from .stance.stance_store import StanceStore
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


def _dialogue_since(conversations):
    """Rows at or after `since` (unix seconds) for the commitment scan."""

    def _rows(since: float) -> list[dict[str, str | float]]:
        found: list[dict[str, str | float]] = []
        for entry in conversations.entries():
            if entry.role not in {"user", "assistant"}:
                continue
            spoken = 0.0
            if entry.time:
                try:
                    spoken = datetime.fromisoformat(entry.time).timestamp()
                except ValueError:
                    spoken = 0.0
            if spoken and spoken < since:
                continue
            found.append(
                {
                    "role": entry.role,
                    "content": entry.content,
                    "time": entry.time,
                    "method": entry.method,
                    "at": spoken,
                }
            )
        return found

    return _rows


def _enqueue_stale_summary(state) -> None:
    """If yesterday was never summarized and a recent episode exists, think once."""
    cfg = state.config.memory
    if not cfg.summary_enabled:
        return
    ledger = getattr(state, "thought", None)
    store = getattr(state, "summary_store", None)
    memory = getattr(getattr(state, "orchestrator", None), "memory_store", None)
    if ledger is None or store is None or memory is None:
        return
    today = datetime.now().date().isoformat()
    if (store.last_day() or "") >= today:
        return
    try:
        recent = memory.list_recent("episodic", since_ts=time.time() - 86400, limit=1)
    except Exception:
        logger.exception("summary catch-up lookup failed")
        return
    if not recent:
        return
    if not ledger.enqueue(PendingTrigger(kind="consolidate")):
        return
    thought_store = getattr(state, "thought_store", None)
    if thought_store is not None:
        thought_store.save(ledger)
    logger.info("summary catch-up queued")


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
        planner_history_hours=config.conversation.planner_history_hours,
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
    memory_store = None
    extractor = None
    state_store = None
    commitment_store = None
    summary_store = None
    memory_v2 = None
    if config.memory_v2.enabled:
        from .memory_v2 import MemoryV2

        memory_v2 = MemoryV2(
            config.memory_v2,
            backend_dir=BACKEND_DIR,
            trace_path=config.logging_dir_abs_path / "memory_v2-trace.jsonl",
            token_budget_state=config.token_budget.state,
            token_budget_memory=config.token_budget.memory,
            encoder=shared_encoder if config.memory_v2.events.vector_enabled else None,
        )
        logger.info("memory_v2 enabled; v1 memory stores were not created")
    else:
        from .memory.commitment import CommitmentStore
        from .memory.extractor import MemoryExtractor
        from .memory.state import StateStore
        from .memory.store import MemoryStore
        from .memory.summary import SummaryStore
        from .prompt import state_budget_fits
        from .rerank import LocalBgeReranker, rerank_missing_reason

        memory_store = MemoryStore(config, encoder=shared_encoder)
        mem_cfg = config.memory
        state_store = StateStore(
            config.memory_db_abs_path,
            max_items=mem_cfg.state_max_items,
            max_chars=mem_cfg.state_max_chars_per_item,
        )
        commitment_store = CommitmentStore(
            config.memory_db_abs_path,
            mute_sec=mem_cfg.commitment_mute_sec,
        )
        summary_store = SummaryStore(
            config.memory_db_abs_path,
            max_chars=mem_cfg.summary_max_chars,
        )
        fits, needed, budget = state_budget_fits(config)
        if not fits:
            logger.warning(
                "state block can exceed its token budget: needed=%d budget=%d",
                needed,
                budget,
            )
        if mem_cfg.rerank_enabled:
            missing_rerank = rerank_missing_reason(config.rerank_model_abs_path)
            if missing_rerank is None:
                try:
                    memory_store.reranker = LocalBgeReranker(config.rerank_model_abs_path)
                except Exception:
                    logger.exception("reranker load failed; retrieval keeps RRF order")
            else:
                logger.warning("%s", missing_rerank)
        extractor = MemoryExtractor(
            memory_store,
            config.memory.extractor,
            state_store=state_store,
            commitment_store=commitment_store,
        )
    knowledge = KnowledgeRetriever(config, encoder=shared_encoder)
    planner = PlannerClient(
        config.planner, renderer_enabled=config.model.enabled
    )
    relationship = RelationshipEngine.from_path(
        config.relationship_abs_path,
        RelationshipSettings.from_config(config.proactive.relationship),
    )
    stance_store = StanceStore(config.stance_abs_path)
    stance_state = stance_store.load()
    orchestrator = Orchestrator(
        config,
        model=model,
        conversations=conversations,
        memory_store=memory_store,
        extractor=extractor,
        memory_v2=memory_v2,
        knowledge=knowledge,
        planner=planner,
        relationship=relationship,
    )
    orchestrator.stance = stance_state
    orchestrator.state_store = state_store
    orchestrator.commitment_store = commitment_store
    orchestrator.summary_store = summary_store
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
    state.stance = stance_state
    state.stance_store = stance_store
    state.state_store = state_store
    state.commitment_store = commitment_store
    state.summary_store = summary_store
    state.memory_v2 = memory_v2
    if memory_v2 is not None:
        memory_v2.bind_life(life)
        memory_v2.bind_dialogue(_dialogue_since(conversations))
    state.glance_request_id = ""
    state.napcat = NapcatLink(config.napcat.user_qq_id)
    orchestrator.napcat = state.napcat
    state.qq_inbox = QqInbox(state)
    state.generation_kind = ""
    state.generation_owner = ""
    state.generation_interrupts = {}
    expire_stale_care(state)
    from .life.thought.triggers import note_memory

    def _on_memory(key: str, category: str) -> None:
        del category
        note_memory(state, key, now=datetime.now())

    if orchestrator.extractor is not None:
        orchestrator.extractor.on_memory_upsert = _on_memory

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
        if memory_store is not None:
            await asyncio.to_thread(memory_store.warmup)
        if knowledge.enabled:
            try:
                await asyncio.to_thread(knowledge.warmup)
            except FileNotFoundError as exc:
                logger.warning("%s", exc)
            except Exception:
                logger.exception("Knowledge warmup failed; RAG will retry on first use")
        if extractor is not None:
            await extractor.start()
        scan_task = None
        if memory_v2 is not None:
            if not memory_v2.extractor.has_api():
                logger.warning(
                    "memory_v2 extract and commitment scan disabled: no API key"
                )
            await memory_v2.extractor.start()
            scan_task = asyncio.create_task(memory_v2.scanner.run())
            logger.info("memory_v2 commitment scan started")
        _enqueue_stale_summary(state)
        life_task = None
        thought_task = None
        stance_task = None
        if life is not None:
            life_task = asyncio.create_task(run_life_loop(state))
            logger.info("life loop started")
            if config.life.thought.enabled:
                thought_task = asyncio.create_task(run_thought_loop(state))
                logger.info("thought loop started")
        if config.stance.enabled:
            try:
                await review_day(state)
            except Exception:
                logger.exception("stance startup catch-up failed")
            stance_task = asyncio.create_task(run_stance_loop(state))
            logger.info("stance loop started")
        app.state.arona = state  # type: ignore[attr-defined]
        yield
        if scan_task is not None:
            memory_v2.scanner.stop()
            scan_task.cancel()
            try:
                await scan_task
            except asyncio.CancelledError:
                pass
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
        if stance_task is not None:
            stance_task.cancel()
            try:
                await stance_task
            except asyncio.CancelledError:
                pass
        if extractor is not None:
            await extractor.stop()
        if memory_v2 is not None:
            await memory_v2.extractor.stop()
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
