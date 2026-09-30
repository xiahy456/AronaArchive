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

"""Load and validate backend configuration from YAML."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


def resolve_backend_dir() -> Path:
    """Directory that owns config.yaml, data/, logs/, and models/.

    Override with ARONA_BACKEND_DIR. Frozen (PyInstaller) builds use the
    executable directory. Source checkouts use the backend/ folder.
    """
    override = os.environ.get("ARONA_BACKEND_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BACKEND_DIR = resolve_backend_dir()


class NapcatConfig(BaseModel):
    user_qq_id: str = ""
    napcat_ws_path: str = "/arona"
    napcat_token: str = ""

    @field_validator("user_qq_id", "napcat_token", mode="before")
    @classmethod
    def _as_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("napcat_ws_path", mode="before")
    @classmethod
    def _ws_path(cls, value: object) -> str:
        text = str(value or "").strip() or "/arona"
        if not text.startswith("/"):
            text = "/" + text
        return text


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 20456
    ws_path: str = "/ws"
    # True when a reverse proxy publishes this process. Requires token
    # even if host stays on loopback.
    public: bool = False
    token: str = ""
    ssl_certfile: str = ""
    ssl_keyfile: str = ""


class ModelConfig(BaseModel):
    enabled: bool = True
    gguf_path: str = "../models/AronaLM-Generator-V2.0/AronaLM-Generator-V2.0.Q4_K_M.gguf"
    n_ctx: int = 2048
    n_gpu_layers: int = -1
    max_new_tokens: int = 128
    temperature: float = 0.6
    top_p: float = 0.85
    repeat_penalty: float = 1.1


class PromptConfig(BaseModel):
    local_system_prompt: str = ""


class ConversationConfig(BaseModel):
    max_history_turns: int = 6
    persist_path: str = "data/memory/dialogue.json"
    max_entries: int = 256


class KnowledgeConfig(BaseModel):
    enabled: bool = False
    corpus_dir: str = "data/knowledge/corpus"
    chroma_path: str = "data/knowledge/chroma"
    collection: str = "arona_lore"
    embedding_model_path: str = "../models/bge-small-zh-v1.5"
    retrieve_top_k: int = 3
    candidate_top_k: int = 8
    max_inject_chars: int = 400
    min_score: float = 0.45
    min_score_no_overlap: float = 0.62
    score_margin: float = 0.08
    query_cache_enabled: bool = True
    query_cache_size: int = 64
    query_cache_min_cosine: float = 0.92


class ExtractorConfig(BaseModel):
    enabled: bool = True
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-flash"
    timeout_sec: float = 15
    max_calls_per_day: int = 200
    every_n_turns: int = 6
    extract_buffer_turns: int = 6
    fallback: str = "regex"


class MemoryConfig(BaseModel):
    db_path: str = "data/memory/memory.db"
    chroma_path: str = "data/memory/chroma"
    collection: str = "arona_memory"
    retrieve_top_k: int = 3
    candidate_top_k: int = 10
    min_score: float = 0.35
    min_score_no_overlap: float = 0.60
    max_inject_chars: int = 400
    inject_cooldown_sec: float = 3600
    inject_cooldown_bypass_score: float = 0.55
    extract_context_top_k: int = 8
    extract_context_max_items: int = 24
    extract_conflict_min_score: float = 0.70
    reconcile_enabled: bool = True
    reconcile_min_score: float = 0.82
    reconcile_top_k: int = 5
    dedup_enabled: bool = True
    dedup_min_score: float = 0.88
    extractor: ExtractorConfig = Field(default_factory=ExtractorConfig)


class PlannerConfig(BaseModel):
    """Big-LLM intent planner (separate from memory extractor)."""

    enabled: bool = True
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-flash"
    timeout_sec: float = 20
    temperature: float = 0.3
    max_tokens: int = 512
    vision_model: str = "deepseek-flash"
    router_enabled: bool = False
    router_timeout_sec: float = 3.0
    router_max_tokens: int = 64


class ListenConfig(BaseModel):
    """Continuous-listen turn taking (silence commit + addressee router)."""

    silence_commit_ms: int = 1000
    incomplete_commit_ms: int = 1800
    continuation_window_sec: float = 8.0


class TokenBudgetConfig(BaseModel):
    memory: int = 250
    knowledge: int = 250
    history: int = 700


class LoggingConfig(BaseModel):
    dir: str = "logs"
    filename: str = "arona-backend.log"
    level: str = "INFO"
    max_bytes: int = 10_485_760
    backup_count: int = 5


class WelcomeConfig(BaseModel):
    enabled: bool = True
    persist_path: str = "data/memory/welcome.json"


class IdleConfig(BaseModel):
    enabled: bool = True
    after_sec: float = 900
    cooldown_sec: float = 1800
    max_per_day: int = 3


class CareConfig(BaseModel):
    enabled: bool = True
    persist_path: str = "data/memory/proactive.json"
    breakfast_start: str = "06:30"
    breakfast_end: str = "08:00"
    lunch_start: str = "11:30"
    lunch_end: str = "13:00"
    dinner_start: str = "17:30"
    dinner_end: str = "19:00"
    sleep_start: str = "23:00"
    sleep_end: str = "23:20"


class GoalConfig(BaseModel):
    enabled: bool = True
    min_after_user_sec: float = 300
    cooldown_sec: float = 21600
    important_horizon_hours: float = 36
    important_cooldown_sec: float = 1800
    due_soon_sec: float = 3600
    mute_sec: float = 604800
    max_per_day: int = 1


class MoodFollowupConfig(BaseModel):
    enabled: bool = True
    min_after_user_sec: float = 900
    min_age_sec: float = 7200
    max_age_hours: float = 72
    cooldown_sec: float = 21600
    mute_sec: float = 604800
    max_per_day: int = 1


class FestivalConfig(BaseModel):
    enabled: bool = True


class ContinueConfig(BaseModel):
    enabled: bool = True
    delay_sec: float = 2


class ThoughtConfig(BaseModel):
    """Thought ledger and the step-2 gate clock. Later steps add their own fields."""

    enabled: bool = True
    persist_path: str = "data/memory/thought.json"
    notes_max: int = 8
    notes_max_age_hours: float = 24
    tick_sec: float = 60
    revisit_after_sec: float = 1200
    spontaneous_online_min_sec: float = 240
    spontaneous_online_max_sec: float = 600
    spontaneous_away_min_sec: float = 600
    spontaneous_away_max_sec: float = 1200
    spontaneous_night_min_sec: float = 1200
    spontaneous_night_max_sec: float = 2400
    refractory_sec: float = 180
    simmer_sec: float = 30
    impulse_priority: int = 30
    aftertaste_min_sec: float = 120
    aftertaste_max_sec: float = 180
    arrived_fallback_sec: float = 2


class LifeConfig(BaseModel):
    """Wall-clock inner state. Does not speak; presence and teacher-as-event come later."""

    enabled: bool = True
    persist_path: str = "data/memory/life.json"
    journal_path: str = "data/memory/life_journal.json"
    arona_memory_path: str = "data/memory/arona.json"
    tick_sec: float = 5
    look_hold_sec: float = 180
    think_hold_sec: float = 120
    glance_interval_sec: float = 1200
    thought: ThoughtConfig = Field(default_factory=ThoughtConfig)


class InteractConfig(BaseModel):
    enabled: bool = True


class ComputerUseConfig(BaseModel):
    enabled: bool = False
    probe_enabled: bool = True
    probe_token: str = "__cu_probe__"
    observation_timeout_sec: float = 8
    max_steps: int = 8
    route_timeout_sec: float = 3
    vision_timeout_sec: float = 20
    vision_max_tokens: int = 2048
    vision_thinking: bool = True


class RelationshipConfig(BaseModel):
    enabled: bool = True
    persist_path: str = "data/memory/relationship.json"
    alpha: float = 0.3
    beta: float = 0.02
    daily_abs_cap: float = 0.35
    makeup_tension: float = 0.7
    makeup_trust_scale: float = 1.5
    cling_dependence: float = 0.55
    high_dependence: float = 0.7
    climate_stick_turns: int = 3
    baseline_trust: float = 0.55
    baseline_dependence: float = 0.30
    baseline_tension: float = 0.25


class ProactiveConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    welcome: WelcomeConfig = Field(default_factory=WelcomeConfig)
    relationship: RelationshipConfig = Field(default_factory=RelationshipConfig)
    idle: IdleConfig = Field(default_factory=IdleConfig)
    care: CareConfig = Field(default_factory=CareConfig)
    goal: GoalConfig = Field(default_factory=GoalConfig)
    mood_followup: MoodFollowupConfig = Field(default_factory=MoodFollowupConfig)
    festival: FestivalConfig = Field(default_factory=FestivalConfig)
    continue_line: ContinueConfig = Field(
        default_factory=ContinueConfig,
        alias="continue",
    )


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    prompt: PromptConfig = Field(default_factory=PromptConfig)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    listen: ListenConfig = Field(default_factory=ListenConfig)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    life: LifeConfig = Field(default_factory=LifeConfig)
    interact: InteractConfig = Field(default_factory=InteractConfig)
    computer_use: ComputerUseConfig = Field(default_factory=ComputerUseConfig)
    napcat: NapcatConfig = Field(default_factory=NapcatConfig)
    token_budget: TokenBudgetConfig = Field(default_factory=TokenBudgetConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    def resolve_path(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute():
            return path
        return (BACKEND_DIR / path).resolve()

    @property
    def gguf_abs_path(self) -> Path:
        return self.resolve_path(self.model.gguf_path)

    @property
    def memory_db_abs_path(self) -> Path:
        return self.resolve_path(self.memory.db_path)

    @property
    def memory_chroma_abs_path(self) -> Path:
        return self.resolve_path(self.memory.chroma_path)

    @property
    def knowledge_corpus_abs_path(self) -> Path:
        return self.resolve_path(self.knowledge.corpus_dir)

    @property
    def knowledge_chroma_abs_path(self) -> Path:
        return self.resolve_path(self.knowledge.chroma_path)

    @property
    def knowledge_embedding_abs_path(self) -> Path:
        return self.resolve_path(self.knowledge.embedding_model_path)

    @property
    def relationship_abs_path(self) -> Path:
        return self.resolve_path(self.proactive.relationship.persist_path)

    @property
    def dialogue_abs_path(self) -> Path:
        return self.resolve_path(self.conversation.persist_path)

    @property
    def welcome_abs_path(self) -> Path:
        return self.resolve_path(self.proactive.welcome.persist_path)

    @property
    def proactive_abs_path(self) -> Path:
        return self.resolve_path(self.proactive.care.persist_path)

    @property
    def life_abs_path(self) -> Path:
        return self.resolve_path(self.life.persist_path)

    @property
    def journal_abs_path(self) -> Path:
        return self.resolve_path(self.life.journal_path)

    @property
    def arona_memory_abs_path(self) -> Path:
        return self.resolve_path(self.life.arona_memory_path)

    @property
    def thought_abs_path(self) -> Path:
        return self.resolve_path(self.life.thought.persist_path)

    @property
    def logging_dir_abs_path(self) -> Path:
        return self.resolve_path(self.logging.dir)

    @property
    def logging_file_abs_path(self) -> Path:
        return self.logging_dir_abs_path / self.logging.filename


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Path | None = None) -> AppConfig:
    example_path = BACKEND_DIR / "config.example.yaml"
    user_path = config_path or (BACKEND_DIR / "config.yaml")

    data: dict[str, Any] = {}
    if example_path.is_file():
        with example_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    if user_path.is_file():
        with user_path.open(encoding="utf-8") as f:
            user_data = yaml.safe_load(f) or {}
        data = _deep_merge(data, user_data)

    return AppConfig.model_validate(data)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config()
