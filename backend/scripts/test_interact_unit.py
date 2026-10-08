"""Unit tests for non-dialogue interact (no GGUF).

Run from backend/:
  python scripts/test_interact_unit.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import AppConfig, ModelConfig, PlannerConfig  # noqa: E402
from app.interact import (  # noqa: E402
    ACTION_PAT_HEAD,
    HISTORY_PAT_HEAD_MARKER,
    build_pat_head_instruction,
    parse_duration_ms,
    resolve_interact_action,
)
from app.orchestrator import Orchestrator  # noqa: E402
from app.planner.schema import IntentCard  # noqa: E402
from app.relationship import (  # noqa: E402
    RelationshipEngine,
    RelationshipSettings,
    RelationshipStore,
)
from app.relationship.events import USER_DELTAS  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


class _FakeConversations:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        _ = session_id
        return list(self.messages)

    def get_planner_history(self, session_id: str = "", *, now=None) -> list[dict[str, str]]:
        _ = session_id, now
        return list(self.messages)

    def append(self, session_id: str, role: str, content: str, **kwargs) -> None:
        _ = session_id, kwargs
        self.messages.append({"role": role, "content": content})


class _FakePlanner:
    enabled = True

    def __init__(self, card: IntentCard) -> None:
        self.card = card
        self.last_user_text = ""

    async def plan(self, **kwargs):  # type: ignore[no-untyped-def]
        self.last_user_text = str(kwargs.get("user_text") or "")
        return self.card


def test_action_whitelist() -> None:
    print("== interact action whitelist ==")
    spec = resolve_interact_action("pat_head")
    if spec is None or spec.action != ACTION_PAT_HEAD:
        _fail("pat_head should resolve")
    if spec.user_act != "touch":
        _fail(f"user_act {spec.user_act}")
    if spec.history_marker != HISTORY_PAT_HEAD_MARKER:
        _fail(f"marker {spec.history_marker}")
    if resolve_interact_action("PAT_HEAD") is None:
        _fail("action lookup should be case-insensitive")
    if resolve_interact_action("poke") is not None:
        _fail("unknown action must be rejected")
    if resolve_interact_action("") is not None:
        _fail("empty action must be rejected")
    if resolve_interact_action(None) is not None:
        _fail("non-string action must be rejected")
    print("  ok")


def test_instruction_is_screen_event() -> None:
    print("== pat instruction is screen system event ==")
    text = build_pat_head_instruction(2400)
    if "【系统事件】" not in text:
        _fail("missing system event prefix")
    if "屏幕" not in text:
        _fail("must mention screen")
    if "摸" not in text:
        _fail("must mention pat")
    if "老师说" in text and "这不是老师说的话" not in text:
        _fail("must not look like teacher speech")
    if "2.4 秒" not in text:
        _fail(f"duration missing: {text}")
    if "touch" not in text:
        _fail("must pin user_act touch")
    print("  ok")


def test_parse_duration_ms() -> None:
    print("== duration_ms coerce ==")
    if parse_duration_ms(2400) != 2400:
        _fail("int")
    if parse_duration_ms("1200") != 1200:
        _fail("str int")
    if parse_duration_ms(-5) != 0:
        _fail("negative")
    if parse_duration_ms("nope") != 0:
        _fail("garbage")
    if parse_duration_ms(None) != 0:
        _fail("none")
    print("  ok")


def test_touch_delta() -> None:
    print("== touch delta smaller than verbal affection ==")
    touch = USER_DELTAS["touch"]
    affection = USER_DELTAS["affection"]
    if touch[0] >= affection[0]:
        _fail(f"trust touch {touch[0]} should be < affection {affection[0]}")
    with tempfile.TemporaryDirectory() as tmp:
        store = RelationshipStore(Path(tmp) / "relationship.json")
        engine = RelationshipEngine(RelationshipSettings(), store)
        before = engine.state.trust
        act, decision = engine.on_user_act("touch")
        if act != "touch":
            _fail(f"act {act}")
        if engine.state.last_user_act != "touch":
            _fail("last_user_act")
        if engine.state.trust <= before:
            _fail("touch should raise trust")
        if decision.user_act != "touch":
            _fail("decision user_act")
    print("  ok")


def _orchestrator(card: IntentCard) -> tuple[Orchestrator, _FakeConversations, _FakePlanner]:
    conv = _FakeConversations()
    planner = _FakePlanner(card)
    orch = Orchestrator(
        AppConfig(
            model=ModelConfig(enabled=False),
            planner=PlannerConfig(enabled=True, api_key="test-key"),
        ),
        model=MagicMock(),
        conversations=conv,
        memory_store=MagicMock(),
        extractor=MagicMock(),
        knowledge=MagicMock(),
        planner=planner,  # type: ignore[arg-type]
    )
    orch.planner = planner  # type: ignore[assignment]
    return orch, conv, planner


def test_honor_reply_ok_false() -> None:
    print("== interact honors reply_ok=false empty content + emotion ==")
    card = IntentCard(
        draft="",
        arona_emotion="shy",
        followup_ok=False,
        reply_ok=False,
        user_act="touch",
    )
    orch, conv, planner = _orchestrator(card)
    sent: list[dict] = []

    async def send(payload: dict) -> None:
        sent.append(payload)

    result = asyncio.run(
        orch.handle_interact(
            session_id="s1",
            action="pat_head",
            duration_ms=2400,
            send=send,
        )
    )
    if result is not True:
        _fail(f"result {result}")
    if len(sent) != 1:
        _fail(f"sent {sent}")
    msg = sent[0]
    if msg.get("type") != "chat_response":
        _fail(f"type {msg}")
    if msg.get("content") != "":
        _fail(f"content {msg.get('content')!r}")
    if msg.get("emotion") != "shy":
        _fail(f"emotion {msg.get('emotion')}")
    context = str(msg.get("context_used") or "")
    if "interact" not in context or "pat_head" not in context or "silence" not in context:
        _fail(f"context_used {context}")
    if conv.messages != [{"role": "user", "content": HISTORY_PAT_HEAD_MARKER}]:
        _fail(f"history {conv.messages}")
    if "屏幕" not in planner.last_user_text:
        _fail("planner should see screen instruction, not teacher quote")
    if orch.stats.get("interact_count") != 1:
        _fail(f"interact_count {orch.stats.get('interact_count')}")
    print("  ok")


def test_reply_ok_true_uses_draft() -> None:
    print("== interact reply_ok=true uses planner draft ==")
    card = IntentCard(
        draft="呜哇、老师突然摸头……好、好痒啦。",
        arona_emotion="shy",
        followup_ok=False,
        reply_ok=True,
        user_act="touch",
    )
    orch, conv, _planner = _orchestrator(card)
    sent: list[dict] = []

    async def send(payload: dict) -> None:
        sent.append(payload)

    result = asyncio.run(
        orch.handle_interact(
            session_id="s1",
            action="pat_head",
            duration_ms=2500,
            send=send,
        )
    )
    if result is not True:
        _fail(f"result {result}")
    if sent[0].get("content") != card.draft:
        _fail(f"content {sent[0].get('content')!r}")
    if sent[0].get("emotion") != "shy":
        _fail(f"emotion {sent[0].get('emotion')}")
    context = str(sent[0].get("context_used") or "")
    if "interact" not in context or "pat_head" not in context:
        _fail(f"context_used {context}")
    if "silence" in context:
        _fail("spoken interact should not mark silence")
    roles = [m["role"] for m in conv.messages]
    if roles != ["user", "assistant"]:
        _fail(f"roles {roles}")
    if conv.messages[0]["content"] != HISTORY_PAT_HEAD_MARKER:
        _fail("history marker")
    print("  ok")


def main() -> None:
    test_action_whitelist()
    test_instruction_is_screen_event()
    test_parse_duration_ms()
    test_touch_delta()
    test_honor_reply_ok_false()
    test_reply_ok_true_uses_draft()
    print("all interact unit tests passed")


if __name__ == "__main__":
    main()
