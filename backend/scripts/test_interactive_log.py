"""Unit tests for interactive information log formatting (no GGUF).

Run from backend/:
  python scripts/test_interactive_log.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import AppConfig  # noqa: E402
from app.image_input import redact_image_fields  # noqa: E402
from app.logging_utils import (  # noqa: E402
    begin_trace,
    current_trace,
    format_interactive_log,
    format_llm_exchange,
    pretty_json,
    reset_trace,
    update_trace,
)
from app.orchestrator import Orchestrator  # noqa: E402
from app.planner.schema import IntentCard  # noqa: E402
from app.relationship.engine import RelationshipEngine, RelationshipSettings  # noqa: E402
from app.relationship.policy import Decision  # noqa: E402
from app.relationship.store import RelationshipStore  # noqa: E402


def _fail(msg: str) -> None:
    raise AssertionError(msg)


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _orchestrator() -> Orchestrator:
    return Orchestrator(
        AppConfig(),
        model=MagicMock(),
        conversations=MagicMock(),
        memory_store=MagicMock(),
        extractor=MagicMock(),
        knowledge=MagicMock(),
    )


def _seed_qq_trace() -> str:
    request = json.dumps(
        {"type": "qq", "content": "老师在吗", "image_count": 1},
        ensure_ascii=False,
    )
    begin_trace(started_at=1.0, request_json=request)
    update_trace(
        planner_prompt=[
            {"role": "system", "content": "你是规划参谋"},
            {"role": "user", "content": "【老师本轮消息】\n老师在吗"},
        ],
        planner_json=(
            '{"draft":"在的，老师。","arona_emotion":"smile","followup_ok":false}'
        ),
        renderer_prompt=[
            {"role": "system", "content": "你是阿洛娜"},
            {"role": "user", "content": "【意图草稿】\n在的，老师。"},
        ],
        renderer_text="在的，老师。",
    )
    return request



def test_pretty_json() -> None:
    print("== pretty_json indent / none / fallback ==")
    pretty = pretty_json({"type": "chat", "content": "好"})
    if "\n" not in pretty or '"type": "chat"' not in pretty:
        _fail(f"object should be indented JSON: {pretty!r}")
    from_text = pretty_json('{"draft":"陪老师","followup_ok":false}')
    if "\n" not in from_text or '"draft": "陪老师"' not in from_text:
        _fail(f"JSON string should re-indent: {from_text!r}")
    if pretty_json(None) != "(none)":
        _fail("None should be (none)")
    if pretty_json("") != "(none)":
        _fail("empty string should be (none)")
    if pretty_json("老师慢慢来") != "老师慢慢来":
        _fail("plain text should stay as-is")
    print("  ok")


def test_format_interactive_log_block() -> None:
    print("== format_interactive_log sections and blanks ==")
    reset_trace()
    begin_trace(
        started_at=1.0,
        request_json='{"type":"chat","content":"好","options":{"use_rag":true}}',
    )
    update_trace(
        planner_prompt=[
            {"role": "system", "content": "你是规划参谋"},
            {"role": "user", "content": "【老师本轮消息】\n好"},
        ],
        planner_json='{"draft":"嗯嗯，我在这儿等您。","arona_emotion":"smile","followup_ok":false}',
        renderer_prompt=[
            {"role": "system", "content": "你是阿洛娜"},
            {"role": "user", "content": "【意图草稿】\n嗯嗯，我在这儿等您。"},
        ],
        renderer_text="嗯，我在这儿等您回来哦。",
    )
    payload = {
        "type": "chat_response",
        "content": "嗯，我在这儿等您回来哦。",
        "context_used": "climate+planner+renderer",
        "latency": 2.1,
        "emotion": "smile",
    }
    block = format_interactive_log(payload, elapsed=2.157)
    for label in (
        "interactive information:",
        "request:",
        "planner_prompt:",
        "planner_json:",
        "renderer_prompt:",
        "renderer_text:",
        "response:",
        "elapsed: 2.157s",
    ):
        if label not in block:
            _fail(f"missing {label!r} in:\n{block}")
    if "request:\n{\n" not in block:
        _fail(f"request JSON should start on next line:\n{block}")
    if '"content": "好"' not in block:
        _fail("request JSON should be pretty-printed")
    if '"followup_ok": false' not in block:
        _fail("planner_json should be pretty-printed")
    if "嗯，我在这儿等您回来哦。" not in block:
        _fail("renderer_text should appear")
    if "\n\nplanner_prompt:\n" not in block:
        _fail("blank line between request and planner_prompt")
    if "\n\nplanner_json:\n" not in block:
        _fail("blank line between planner_prompt and planner_json")
    if "\n\nrenderer_prompt:\n" not in block:
        _fail("blank line before renderer_prompt")
    if "\n\nrenderer_text:\n" not in block:
        _fail("blank line before renderer_text")
    if "\n\nresponse:\n" not in block:
        _fail("blank line before response")
    if "\n\nelapsed: 2.157s" not in block:
        _fail("blank line before elapsed")
    reset_trace()
    print("  ok")


def test_format_missing_fields_are_none() -> None:
    print("== missing planner/renderer are (none) ==")
    reset_trace()
    begin_trace(started_at=10.0, request_json=None)
    block = format_interactive_log(
        {"type": "chat_response", "content": "刚才没听清，请再说一次～"},
        elapsed=0.012,
    )
    if block.count("(none)") < 4:
        _fail(f"expected (none) for absent fields:\n{block}")
    if "request:\n(none)" not in block:
        _fail("system-initiated request should be (none)")
    if "renderer_text:\n(none)" not in block:
        _fail("empty renderer_text should be (none)")
    reset_trace()
    empty = format_interactive_log({"type": "chat_response", "content": ""}, elapsed=0.0)
    if "request:\n(none)" not in empty:
        _fail("no trace should still render (none) fields")
    print("  ok")


def test_format_listen_transcript_request() -> None:
    print("== listen transcript request is pretty-printed ==")
    reset_trace()
    content = "这就导致一个什么问题呢？就是导致。"
    begin_trace(
        started_at=1.0,
        request_json=json.dumps(
            {"type": "transcript", "content": content},
            ensure_ascii=False,
        ),
    )
    block = format_interactive_log(
        {"type": "chat_response", "content": "老师，您慢慢说。"},
        elapsed=0.5,
    )
    if "request:\n(none)" in block:
        _fail("listen request should not be (none)")
    if '"type": "transcript"' not in block:
        _fail(f"request should show transcript type:\n{block}")
    if f'"content": "{content}"' not in block:
        _fail(f"request should pretty-print listen content:\n{block}")
    reset_trace()
    print("  ok")


def test_format_renderer_disabled_is_none() -> None:
    print("== renderer off: renderer_text is (none), content is draft ==")
    reset_trace()
    draft = "老师好，我在这儿。"
    begin_trace(
        started_at=1.0,
        request_json='{"type":"chat","content":"好"}',
    )
    update_trace(
        planner_prompt=[{"role": "system", "content": "你是规划参谋"}],
        planner_json='{"draft":"老师好，我在这儿。","arona_emotion":"smile","followup_ok":false}',
    )
    payload = {
        "type": "chat_response",
        "content": draft,
        "context_used": "climate+planner",
        "latency": 0.4,
        "emotion": "smile",
    }
    block = format_interactive_log(payload, elapsed=0.4)
    if "renderer_text:\n(none)" not in block:
        _fail(f"disabled renderer should log renderer_text (none):\n{block}")
    if "renderer_prompt:\n(none)" not in block:
        _fail(f"disabled renderer should log renderer_prompt (none):\n{block}")
    if f'"content": "{draft}"' not in block:
        _fail(f"response content should be planner draft:\n{block}")
    reset_trace()
    print("  ok")


def test_qq_request_json_in_interactive_log() -> None:
    print("== QQ request_json pretty-prints in interactive information ==")
    reset_trace()
    request = _seed_qq_trace()
    payload = {
        "type": "chat_response",
        "content": "在的，老师。",
        "context_used": "planner+renderer",
        "latency": 1.2,
        "emotion": "smile",
    }
    block = format_interactive_log(payload, elapsed=1.25)
    if "interactive information:" not in block:
        _fail(f"missing interactive header:\n{block}")
    if '"type": "qq"' not in block or '"image_count": 1' not in block:
        _fail(f"QQ request should be pretty-printed:\n{block}")
    if "老师在吗" not in block:
        _fail(f"QQ request content missing:\n{block}")
    if "planner_prompt:\n[" not in block:
        _fail(f"planner_prompt should be indented JSON:\n{block}")
    if json.loads(request)["type"] != "qq":
        _fail("seed request should be type=qq")
    reset_trace()
    print("  ok")


def test_qq_deliver_spoken_emits_interactive_log() -> None:
    print("== QQ _deliver_spoken emits interactive log and resets trace ==")
    reset_trace()
    orch = _orchestrator()
    link = MagicMock()
    link.connected = True
    link.send_text = AsyncMock(return_value=True)
    orch.napcat = link

    handler = _CaptureHandler()
    handler.setLevel(logging.INFO)
    logger = logging.getLogger("app.orchestrator")
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    async def _run() -> tuple[bool, object]:
        _seed_qq_trace()
        ok = await orch._deliver_spoken(
            text="在的，老师。",
            emotion="smile",
            method="message",
            send=AsyncMock(),
            context_used="planner+renderer",
            latency=1.2,
            on_life_action=None,
            client_online=False,
            emit_emotion=False,
        )
        return ok, current_trace()

    try:
        ok, leftover = asyncio.run(_run())
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
        reset_trace()

    if not ok:
        _fail("deliver should succeed when napcat connected")
    link.send_text.assert_awaited()
    blocks = [m for m in handler.messages if m.startswith("interactive information:")]
    if len(blocks) != 1:
        _fail(f"expected one interactive information block, got {len(blocks)}")
    block = blocks[0]
    if "planner_prompt:" not in block or '"role": "system"' not in block:
        _fail(f"QQ deliver log missing planner_prompt:\n{block}")
    if "renderer_text:\n在的，老师。" not in block:
        _fail(f"QQ deliver log missing renderer_text:\n{block}")
    if '"type": "qq"' not in block:
        _fail(f"QQ deliver log missing request:\n{block}")
    if leftover is not None:
        _fail("trace should be reset after QQ interactive log")
    print("  ok")


def test_qq_skip_generation_emits_interactive_log() -> None:
    print("== QQ _skip_generation emits interactive log and resets trace ==")
    reset_trace()
    orch = _orchestrator()
    orch.conversations.append = MagicMock()
    decision = Decision(
        action="silence",
        climate="steady",
        stance="",
        must_not=[],
        tone_hint="",
        user_act="other",
    )

    handler = _CaptureHandler()
    handler.setLevel(logging.INFO)
    logger = logging.getLogger("app.orchestrator")
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    async def _run() -> object:
        _seed_qq_trace()
        await orch._skip_generation(
            session_id="qq",
            user_text="老师在吗",
            decision=decision,
            send=AsyncMock(),
            reason="reply_ok_false",
            latency=0.5,
            emotion="normal",
            inbound_method="message",
            client_online=False,
        )
        return current_trace()

    try:
        leftover = asyncio.run(_run())
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
        reset_trace()

    blocks = [m for m in handler.messages if m.startswith("interactive information:")]
    if len(blocks) != 1:
        _fail(f"expected one interactive information block, got {len(blocks)}")
    block = blocks[0]
    if "response:\n{" not in block:
        _fail(f"QQ skip log missing response:\n{block}")
    if "planner_prompt:" not in block:
        _fail(f"QQ skip log missing planner_prompt:\n{block}")
    if leftover is not None:
        _fail("trace should be reset after QQ skip interactive log")
    print("  ok")


def test_format_llm_exchange_indent_and_sections() -> None:
    print("== format_llm_exchange indent / prompt / response ==")
    messages = [
        {"role": "system", "content": "你是电脑操作路由器"},
        {"role": "user", "content": "【老师本段】打开记事本写今天日期"},
    ]
    block = format_llm_exchange(
        title="computer_use route",
        prompt=messages,
        response='{"computer_use": true}',
        extra={"computer_use": True},
    )
    if not block.startswith("computer_use route:\n"):
        _fail(f"title should start the block:\n{block}")
    if "\n" not in block:
        _fail(f"block should be multi-line:\n{block}")
    if "prompt:\n" not in block:
        _fail(f"missing prompt section:\n{block}")
    if "response:\n" not in block:
        _fail(f"missing response section:\n{block}")
    if "\n\nresponse:\n" not in block:
        _fail(f"blank line before response:\n{block}")
    if '"role": "system"' not in block or "  " not in block:
        _fail(f"prompt JSON should be indented:\n{block}")
    if '"computer_use": true' not in block:
        _fail(f"response JSON should be pretty-printed:\n{block}")
    if "computer_use: true" not in block:
        _fail(f"extra bool should render as true/false:\n{block}")
    if "reasoning:" in block:
        _fail(f"absent reasoning should omit the section:\n{block}")
    print("  ok")


def test_format_llm_exchange_optional_reasoning() -> None:
    print("== format_llm_exchange optional reasoning ==")
    with_reason = format_llm_exchange(
        title="computer_use vision",
        prompt=[{"role": "user", "content": "截图"}],
        response='{"action":"wait","ms":0}',
        reasoning="先看桌面再点开始菜单。",
    )
    if "\n\nreasoning:\n先看桌面再点开始菜单。\n\nresponse:\n" not in with_reason:
        _fail(f"reasoning should sit between prompt and response:\n{with_reason}")
    blank = format_llm_exchange(
        title="computer_use vision",
        prompt=[],
        response="not json at all",
        reasoning="   ",
    )
    if "reasoning:" in blank:
        _fail(f"blank reasoning should be omitted:\n{blank}")
    if "not json at all" not in blank:
        _fail(f"non-JSON response should stay as text:\n{blank}")
    print("  ok")


def test_format_llm_exchange_redacts_data_url() -> None:
    print("== format_llm_exchange redacts screenshot data_url ==")
    payload = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看屏幕"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
                    },
                },
            ],
        }
    ]
    raw_url = payload[0]["content"][1]["image_url"]["url"]
    block = format_llm_exchange(
        title="computer_use vision",
        prompt=redact_image_fields(payload),
        response='{"action":"done"}',
    )
    if raw_url in block:
        _fail("raw data URL must not appear in the log")
    if "data:image/png;base64," in block:
        _fail("data URL prefix must not appear after redact")
    if "[redacted data_url" not in block or "chars]" not in block:
        _fail(f"expected redacted data_url placeholder:\n{block}")
    if "看屏幕" not in block:
        _fail(f"text part of prompt should remain:\n{block}")
    if "Authorization" in block or "api_key" in block:
        _fail(f"must not log credentials:\n{block}")
    print("  ok")


def test_qq_undelivered_skips_relationship_commit() -> None:
    print("== QQ undelivered chat does not commit relationship Δ ==")

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rel.json"
            settings = RelationshipSettings(beta=0.02)
            engine = RelationshipEngine.from_path(path, settings)
            engine.state.trust = 0.80
            engine.state.dependence = 0.50
            engine.state.tension = 0.40
            engine.store.save(engine.state)
            before = engine.state.snapshot()

            cfg = AppConfig()
            cfg.proactive.relationship.enabled = True
            cfg.knowledge.enabled = False
            orch = Orchestrator(
                cfg,
                model=MagicMock(),
                conversations=MagicMock(),
                memory_store=MagicMock(),
                extractor=MagicMock(),
                knowledge=MagicMock(),
            )
            orch.relationship = engine
            orch.conversations.get_history.return_value = []
            orch.conversations.append = MagicMock()
            orch.conversations.turn_count.return_value = 0
            orch.conversations.extract_buffer_turn_count.return_value = 0
            orch.knowledge.enabled = False
            orch.planner = MagicMock()
            orch.planner.enabled = True
            orch.planner.plan = AsyncMock(
                return_value=IntentCard(
                    draft="在的，老师。",
                    arona_emotion="smile",
                    followup_ok=False,
                    reply_ok=True,
                    user_act="other",
                    method="message",
                )
            )
            orch._deliver_spoken = AsyncMock(return_value=False)

            await orch.handle_chat(
                session_id="qq",
                content="你好啊",
                options={"use_rag": False, "use_memory": False},
                send=AsyncMock(),
                inbound_method="message",
                client_online=False,
            )

            reloaded = RelationshipStore(path).load()
            if (
                reloaded.trust != before["trust"]
                or reloaded.dependence != before["dependence"]
                or reloaded.tension != before["tension"]
            ):
                _fail(
                    f"undelivered must not change A/B/C: before={before} "
                    f"after={reloaded.snapshot()}"
                )

    asyncio.run(_run())
    print("  ok")


def main() -> None:
    try:
        test_pretty_json()
        test_format_interactive_log_block()
        test_format_missing_fields_are_none()
        test_format_listen_transcript_request()
        test_format_renderer_disabled_is_none()
        test_qq_request_json_in_interactive_log()
        test_qq_deliver_spoken_emits_interactive_log()
        test_qq_skip_generation_emits_interactive_log()
        test_qq_undelivered_skips_relationship_commit()
        test_format_llm_exchange_indent_and_sections()
        test_format_llm_exchange_optional_reasoning()
        test_format_llm_exchange_redacts_data_url()
    finally:
        reset_trace()
    print("ALL PASS")


if __name__ == "__main__":
    main()
