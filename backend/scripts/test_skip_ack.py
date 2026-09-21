"""Unit tests for silence/refuse skip still sending empty chat_response.

Run from backend/:
  python scripts/test_skip_ack.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import AppConfig, ModelConfig  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from app.planner import DEFAULT_EMOTION, IntentCard  # noqa: E402
from app.relationship.policy import Decision  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def _orchestrator() -> Orchestrator:
    model = MagicMock()
    model.generate.side_effect = AssertionError("generate must not be called")
    return Orchestrator(
        AppConfig(model=ModelConfig(enabled=False)),
        model=model,
        conversations=MagicMock(),
        memory_store=MagicMock(),
        extractor=MagicMock(),
        knowledge=MagicMock(),
    )


def _decision(*, action: str) -> Decision:
    return Decision(
        action=action,  # type: ignore[arg-type]
        climate="secure_play",
        stance="",
        user_act="short_ack",
    )


async def _collect_skip(
    orch: Orchestrator,
    *,
    user_text: str,
    decision: Decision | None,
    reason: str | None = None,
    latency: float = 0.0,
    emotion: str = DEFAULT_EMOTION,
) -> list[dict]:
    sent: list[dict] = []

    async def send(payload: dict) -> None:
        sent.append(payload)

    await orch._skip_generation(
        session_id="s1",
        user_text=user_text,
        decision=decision,
        send=send,
        reason=reason,
        latency=latency,
        emotion=emotion,
    )
    return sent


def test_reply_ok_false_sends_empty_silence() -> None:
    print("== reply_ok_false sends empty chat_response context_used=silence ==")
    orch = _orchestrator()
    sent = asyncio.run(
        _collect_skip(
            orch,
            user_text="嗯",
            decision=_decision(action="speak"),
            reason="reply_ok_false",
            latency=1.138,
            emotion=DEFAULT_EMOTION,
        )
    )
    if len(sent) != 1:
        _fail(f"expected one payload, got {sent!r}")
    payload = sent[0]
    if payload.get("type") != "chat_response":
        _fail(f"expected chat_response, got {payload!r}")
    if payload.get("content") != "":
        _fail(f"content should be empty, got {payload.get('content')!r}")
    if payload.get("context_used") != "silence":
        _fail(f"context_used should be silence, got {payload.get('context_used')!r}")
    if payload.get("emotion") != DEFAULT_EMOTION:
        _fail(f"emotion should be {DEFAULT_EMOTION}, got {payload.get('emotion')!r}")
    if payload.get("latency") != 1.138:
        _fail(f"latency should be 1.138, got {payload.get('latency')!r}")
    if orch.stats.get("silence_count") != 1:
        _fail(f"silence_count should be 1, got {orch.stats.get('silence_count')!r}")
    if orch.stats.get("chat_count") != 0:
        _fail("chat_count should stay 0 on skip")
    orch.conversations.append.assert_called_once_with("s1", "user", "嗯")
    orch.model.generate.assert_not_called()
    print("  ok")


def test_refuse_sends_empty_refuse() -> None:
    print("== relationship refuse sends empty chat_response context_used=refuse ==")
    orch = _orchestrator()
    sent = asyncio.run(
        _collect_skip(
            orch,
            user_text="走开",
            decision=_decision(action="refuse"),
            latency=0.0123,
        )
    )
    if len(sent) != 1:
        _fail(f"expected one payload, got {sent!r}")
    payload = sent[0]
    if payload.get("content") != "":
        _fail(f"content should be empty, got {payload.get('content')!r}")
    if payload.get("context_used") != "refuse":
        _fail(f"context_used should be refuse, got {payload.get('context_used')!r}")
    if payload.get("latency") != 0.0123:
        _fail(f"latency should be rounded to 0.0123, got {payload.get('latency')!r}")
    if orch.stats.get("refuse_count") != 1:
        _fail(f"refuse_count should be 1, got {orch.stats.get('refuse_count')!r}")
    if orch.stats.get("silence_count") != 0:
        _fail("silence_count should stay 0 on refuse")
    orch.conversations.append.assert_called_once_with("s1", "user", "走开")
    print("  ok")


def test_relationship_silence_emits_continue_activity() -> None:
    print("== relationship silence still empty ack and continue_activity ==")
    orch = _orchestrator()
    cfg = orch.config
    cfg.proactive.relationship.enabled = True
    preview = Decision(
        action="silence",
        climate="cling_risk",
        stance="",
        user_act="short_ack",
    )
    relationship = MagicMock()
    relationship.preview_user_text.return_value = ("short_ack", preview)
    relationship.on_user_text.return_value = ("short_ack", preview)
    relationship.note_planner_user_act.return_value = ("short_ack", False)
    orch.relationship = relationship
    planner = MagicMock()
    planner.enabled = True
    planner.plan = MagicMock(side_effect=AssertionError("planner must not run"))
    orch.planner = planner
    actions: list[tuple[str, str]] = []
    sent: list[dict] = []

    async def send(payload: dict) -> None:
        sent.append(payload)

    asyncio.run(
        orch.handle_chat(
            session_id="s1",
            content="嗯",
            options={},
            send=send,
            on_life_action=lambda action, emotion: actions.append((action, emotion)),
        )
    )
    if len(sent) != 1 or sent[0].get("content") != "":
        _fail(f"expected empty chat_response, got {sent!r}")
    if sent[0].get("context_used") != "silence":
        _fail(sent[0].get("context_used"))
    if actions != [("continue_activity", "normal")]:
        _fail(f"life action {actions!r}")
    orch.planner.plan.assert_not_called()
    print("  ok")


def test_reply_ok_false_emits_life_action() -> None:
    print("== reply_ok=false empty ack and emotion_only ==")
    orch = _orchestrator()
    orch.conversations.get_history.return_value = []
    card = IntentCard(
        draft="",
        arona_emotion="smile",
        followup_ok=False,
        reply_ok=False,
        user_act="short_ack",
    )
    planner = MagicMock()
    planner.enabled = True
    planner.plan = AsyncMock(return_value=card)
    orch.planner = planner
    actions: list[tuple[str, str]] = []
    sent: list[dict] = []

    async def send(payload: dict) -> None:
        sent.append(payload)

    asyncio.run(
        orch.handle_chat(
            session_id="s1",
            content="嗯",
            options={"use_rag": False, "use_memory": False},
            send=send,
            on_life_action=lambda action, emotion: actions.append((action, emotion)),
        )
    )
    if len(sent) != 1 or sent[0].get("content") != "":
        _fail(f"expected empty chat_response, got {sent!r}")
    if sent[0].get("context_used") != "silence":
        _fail(sent[0].get("context_used"))
    if actions != [("emotion_only", "smile")]:
        _fail(f"life action {actions!r}")
    print("  ok")


def main() -> None:
    test_reply_ok_false_sends_empty_silence()
    test_refuse_sends_empty_refuse()
    test_relationship_silence_emits_continue_activity()
    test_reply_ok_false_emits_life_action()
    print("ALL PASS")


if __name__ == "__main__":
    main()
