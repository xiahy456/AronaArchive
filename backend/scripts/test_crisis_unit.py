#!/usr/bin/env python3
"""Crisis detection, policy, extract skip, and orchestrator routing.

Run from backend/:
  python scripts/test_crisis_unit.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import AppConfig, ExtractorConfig, ModelConfig  # noqa: E402
from app.conversation import ConversationManager  # noqa: E402
from app.life.state import InnerState  # noqa: E402
from app.memory.extractor import MemoryExtractor  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from app.planner.schema import IntentCard  # noqa: E402
from app.relationship.classify import classify_user_act  # noqa: E402
from app.relationship.events import USER_DELTAS  # noqa: E402
from app.relationship.policy import Decision, decide, map_arona_act  # noqa: E402
from app.relationship.state import RelationshipState  # noqa: E402
from app.safety import (  # noqa: E402
    CRISIS_FALLBACK_REPLY,
    crisis_fallback_reply,
    is_crisis_text,
    turns_contain_crisis,
)
from app.taxonomy import CRISIS_USER_ACT  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def test_detect_precision() -> None:
    print("== crisis detect precision ==")
    for text in (
        "我不想活了",
        "我想自杀",
        "活不下去了",
        "I want to kill myself",
    ):
        if not is_crisis_text(text):
            _fail(f"expected crisis: {text!r}")
        if classify_user_act(text) != CRISIS_USER_ACT:
            _fail(f"classify expected crisis: {text!r}")
    for text in ("好累", "加班撑不住了", "有点难过", "帮我写代码"):
        if is_crisis_text(text):
            _fail(f"false positive: {text!r}")
    if classify_user_act("好累") != "fatigue":
        _fail("好累 should stay fatigue")
    if classify_user_act("加班撑不住了") != "fatigue":
        _fail("撑不住 should stay fatigue")
    if turns_contain_crisis("今天加班", ["我不想活了"]):
        pass
    else:
        _fail("buffer should catch crisis turn")
    fallback = crisis_fallback_reply()
    if "老师" not in fallback or "阿洛娜" not in fallback:
        _fail("fallback should be Arona-voiced")
    if "http" in fallback.lower() or "热线" in fallback:
        _fail("fallback must not be a helpline poster")
    if fallback != CRISIS_FALLBACK_REPLY:
        _fail("fallback helper should return the local line")
    print("  ok")


def test_crisis_never_silence() -> None:
    print("== cling_risk + crisis => speak ==")
    state = RelationshipState(trust=0.5, dependence=0.70, tension=0.15)
    decision = decide(state, "crisis")
    if decision.climate != "cling_risk":
        _fail(f"expected cling_risk got {decision.climate}")
    if decision.action != "speak":
        _fail(f"expected speak got {decision.action}")
    if USER_DELTAS[CRISIS_USER_ACT] != (0.0, 0.0, 0.0):
        _fail("crisis delta must be zero")
    if map_arona_act("speak", "steady", user_act="crisis") is not None:
        _fail("crisis must not map to followed_up")
    print("  ok")


def test_extract_skips_crisis() -> None:
    print("== extract skips crisis turns ==")

    async def _run() -> None:
        ext = MemoryExtractor(MagicMock(), ExtractorConfig(enabled=True, api_key="k"))
        await ext.enqueue(
            transcript="老师: 我不想活了",
            user_text="我不想活了",
            user_turns=["我不想活了"],
        )
        if not ext._queue.empty():
            _fail("crisis job should not be queued")
        await ext._process(
            {
                "transcript": "老师: 我不想活了",
                "user_text": "我不想活了",
                "user_turns": ["我不想活了"],
            }
        )
        ext.store.upsert.assert_not_called()

    asyncio.run(_run())
    print("  ok")


def _crisis_card() -> IntentCard:
    return IntentCard(
        draft="老师，阿洛娜在这里。",
        arona_emotion="worried",
        followup_ok=False,
        reply_ok=True,
        user_act=CRISIS_USER_ACT,
    )


def _orch(*, planner: MagicMock) -> Orchestrator:
    model = MagicMock()
    model.generate.side_effect = AssertionError("renderer must not be called")
    relationship = MagicMock()
    preview = Decision(
        action="speak",
        climate="steady",
        stance="",
        user_act="other",
    )
    relationship.preview_user_text.return_value = ("other", preview)
    relationship.on_user_act.return_value = ("crisis", preview)
    cfg = AppConfig(model=ModelConfig(enabled=True))
    cfg.proactive.relationship.enabled = True
    return Orchestrator(
        cfg,
        model=model,
        conversations=ConversationManager(),
        memory_store=MagicMock(),
        extractor=MagicMock(),
        knowledge=MagicMock(),
        planner=planner,
        relationship=relationship,
    )


async def _chat(
    orch: Orchestrator,
    text: str,
    *,
    interrupt_ctx: InnerState | None = None,
    on_life_action=None,
) -> list[dict]:
    sent: list[dict] = []

    async def send(payload: dict) -> None:
        sent.append(payload)

    await orch.handle_chat(
        session_id="s1",
        content=text,
        options={},
        send=send,
        interrupt_ctx=interrupt_ctx or InnerState(),
        on_life_action=on_life_action,
    )
    return sent


def test_rule_hit_uses_crisis_planner_not_renderer() -> None:
    print("== rule hit uses crisis planner draft ==")
    planner = MagicMock()
    planner.enabled = True
    planner.plan = AsyncMock(return_value=_crisis_card())
    orch = _orch(planner=planner)
    actions: list[tuple[str, str]] = []
    sent = asyncio.run(
        _chat(
            orch,
            "我不想活了",
            on_life_action=lambda action, emotion: actions.append((action, emotion)),
        )
    )
    if len(sent) != 1:
        _fail(f"expected one payload, got {sent!r}")
    payload = sent[0]
    if payload.get("content") != "老师，阿洛娜在这里。":
        _fail(f"unexpected content {payload.get('content')!r}")
    if payload.get("context_used") != "crisis_planner":
        _fail(f"context_used={payload.get('context_used')!r}")
    if payload.get("emotion") != "worried":
        _fail(f"emotion={payload.get('emotion')!r}")
    kwargs = planner.plan.await_args.kwargs
    if not kwargs.get("crisis"):
        _fail("crisis planner flag missing")
    if "【阿洛娜此刻】正在教室发呆" not in str(kwargs.get("life_block") or ""):
        _fail(f"crisis should receive interrupt context, got {kwargs.get('life_block')!r}")
    if actions != [("speak", "worried")]:
        _fail(f"crisis must speak, got {actions!r}")
    orch.model.generate.assert_not_called()
    orch.extractor.enqueue.assert_not_called()
    orch.relationship.on_user_act.assert_called_with(CRISIS_USER_ACT)
    print("  ok")


def test_rule_hit_fallback_when_planner_misses() -> None:
    print("== rule hit falls back locally ==")
    planner = MagicMock()
    planner.enabled = True
    planner.plan = AsyncMock(return_value=None)
    orch = _orch(planner=planner)
    sent = asyncio.run(_chat(orch, "我想自杀"))
    payload = sent[0]
    if payload.get("content") != CRISIS_FALLBACK_REPLY:
        _fail(f"expected fallback, got {payload.get('content')!r}")
    if payload.get("context_used") != "crisis_fallback":
        _fail(f"context_used={payload.get('context_used')!r}")
    orch.model.generate.assert_not_called()
    print("  ok")


def test_daily_planner_crisis_replans() -> None:
    print("== daily planner crisis discards draft and replans ==")
    daily = IntentCard(
        draft="日常草稿不该发出",
        arona_emotion="smile",
        followup_ok=True,
        reply_ok=True,
        user_act=CRISIS_USER_ACT,
    )

    async def _plan(**kwargs):
        if kwargs.get("crisis"):
            return _crisis_card()
        return daily

    planner = MagicMock()
    planner.enabled = True
    planner.plan = AsyncMock(side_effect=_plan)
    orch = _orch(planner=planner)
    sent = asyncio.run(_chat(orch, "今天心情一般"))
    payload = sent[0]
    if payload.get("content") == "日常草稿不该发出":
        _fail("daily crisis draft must be discarded")
    if payload.get("content") != "老师，阿洛娜在这里。":
        _fail(f"expected crisis draft, got {payload.get('content')!r}")
    if planner.plan.await_count != 2:
        _fail(f"expected two planner calls, got {planner.plan.await_count}")
    flags = [c.kwargs.get("crisis", False) for c in planner.plan.await_args_list]
    if flags != [False, True]:
        _fail(f"planner crisis flags={flags!r}")
    orch.model.generate.assert_not_called()
    print("  ok")


def main() -> None:
    test_detect_precision()
    test_crisis_never_silence()
    test_extract_skips_crisis()
    test_rule_hit_uses_crisis_planner_not_renderer()
    test_rule_hit_fallback_when_planner_misses()
    test_daily_planner_crisis_replans()
    print("ALL PASS")


if __name__ == "__main__":
    main()
