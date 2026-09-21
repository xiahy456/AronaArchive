#!/usr/bin/env python3
"""Unit tests for computer-use probe, router, and vision loop (no GGUF, no network).

Run from backend/:
  python scripts/test_computer_use_unit.py
"""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.computer_use import (  # noqa: E402
    ACTION_WHITELIST,
    HISTORY_COMPUTER_USE_MARKER,
    PROBE_ALIAS,
    PROBE_TOKEN,
    ComputerUseAction,
    ComputerUseObservation,
    ComputerUseRouter,
    ProbeResult,
    SchemaError,
    build_route_user_message,
    computer_use_history_content,
    format_route_history,
    is_denied_computer_use,
    is_probe_text,
    parse_action,
    parse_observation,
    parse_route_decision,
    parse_screen,
    parse_vision_action,
    probe_actions,
    probe_reply_text,
    race_route_and_chat,
    run_action_loop,
    run_probe,
    run_vision_agent,
    terminal_messages,
)
from app.computer_use.prompts import (  # noqa: E402
    CURSOR_MARKER_NOTE,
    GRID_MARKER_NOTE,
    REPEAT_POINTER_WARNING,
    VISION_SYSTEM,
    build_computer_use_instruction,
    build_vision_user_message,
    cursor_to_image_xy,
    format_executed_steps,
    is_repeat_pointer,
)
from app.computer_use.router import ROUTER_SYSTEM  # noqa: E402
from app.config import ComputerUseConfig, PlannerConfig  # noqa: E402
from app.image_input import ImagePayload  # noqa: E402
from app.protocol import (  # noqa: E402
    TYPE_COMPUTER_USE_ACTION,
    msg_computer_use_action,
    msg_computer_use_done,
)

_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 16 + b"\xff\xd9"
_JPEG_B64 = base64.b64encode(_JPEG).decode("ascii")


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def _valid_screen() -> dict[str, Any]:
    return {
        "origin_x": 0, "origin_y": 0,
        "phys_w": 1920, "phys_h": 1080,
        "img_w": 1280, "img_h": 720,
    }


def _ok_obs(run_id: str, step: int) -> ComputerUseObservation:
    return ComputerUseObservation(
        run_id=run_id, step=step, ok=True, error="",
        screen=parse_screen(_valid_screen()), image=None,
    )


def _ok_obs_image(run_id: str, step: int) -> ComputerUseObservation:
    return ComputerUseObservation(
        run_id=run_id, step=step, ok=True, error="",
        screen=parse_screen(_valid_screen()),
        image=ImagePayload(mime="image/jpeg", data=_JPEG),
    )


# -- Token recognition --

def test_probe_token_recognition() -> None:
    print("== probe token recognition ==")
    if not is_probe_text(PROBE_TOKEN):
        _fail(f"should accept {PROBE_TOKEN!r}")
    if not is_probe_text(PROBE_ALIAS):
        _fail(f"should accept alias {PROBE_ALIAS!r}")
    if not is_probe_text("  __cu_probe__  "):
        _fail("should strip whitespace")
    if is_probe_text("not a probe"):
        _fail("should reject normal text")
    if is_probe_text(""):
        _fail("should reject empty")
    if is_probe_text(None):
        _fail("should reject None")
    if not is_probe_text("__custom__", "__custom__"):
        _fail("should accept custom token")
    # Default aliases are always recognized; custom token is additive
    if not is_probe_text("__cu_probe__", "__custom__"):
        _fail("default alias should still be recognized with custom token")
    print("  ok")


# -- Action whitelist --

def test_action_whitelist() -> None:
    print("== action whitelist ==")
    expected = {
        "move", "click", "double_click", "right_click", "middle_click",
        "drag", "right_drag",
        "scroll", "type", "key", "wait", "done",
    }
    if ACTION_WHITELIST != expected:
        _fail(f"whitelist mismatch: {ACTION_WHITELIST}")
    print("  ok")


def test_parse_action_move() -> None:
    print("== parse action move ==")
    action = parse_action({"action": "move", "x": 0.5, "y": 0.5})
    if action.action != "move":
        _fail(f"action={action.action}")
    if action.x != 0.5 or action.y != 0.5:
        _fail(f"x={action.x} y={action.y}")
    print("  ok")


def test_parse_action_wait() -> None:
    print("== parse action wait ==")
    action = parse_action({"action": "wait", "ms": 400})
    if action.ms != 400:
        _fail(f"ms={action.ms}")
    print("  ok")


def test_parse_action_key() -> None:
    print("== parse action key ==")
    action = parse_action({"action": "key", "combo": "escape"})
    if action.combo != "escape":
        _fail(f"combo={action.combo}")
    print("  ok")


def test_parse_action_drag() -> None:
    print("== parse action drag / right_drag ==")
    drag = parse_action({
        "action": "drag",
        "x": 120,
        "y": 200,
        "x2": 480,
        "y2": 200,
        "coord_space": "image",
    })
    if drag.action != "drag":
        _fail(f"action={drag.action}")
    if drag.x != 120 or drag.y != 200 or drag.x2 != 480 or drag.y2 != 200:
        _fail(f"start/end mismatch {drag}")
    payload = drag.to_payload()
    if payload.get("x2") != 480 or payload.get("y2") != 200:
        _fail(f"payload missing end point: {payload}")
    right = parse_action({
        "action": "right_drag",
        "x": 10,
        "y": 20,
        "x2": 30,
        "y2": 40,
    })
    if right.action != "right_drag":
        _fail(f"action={right.action}")
    if right.x2 != 30 or right.y2 != 40:
        _fail(f"right_drag end mismatch {right}")
    try:
        parse_action({"action": "drag", "x": 1, "y": 2})
        _fail("drag without x2/y2 should fail")
    except SchemaError:
        pass
    try:
        parse_action({"action": "right_drag", "x": 1, "y": 2, "x2": 3})
        _fail("right_drag without y2 should fail")
    except SchemaError:
        pass
    steps = format_executed_steps([drag])
    if "drag x=120.0 y=200.0 x2=480.0 y2=200.0" not in steps:
        _fail(f"executed steps should include endpoints: {steps}")
    print("  ok")


def test_parse_action_scroll_and_middle_click() -> None:
    print("== parse action scroll / middle_click ==")
    scroll = parse_action({
        "action": "scroll",
        "x": 640,
        "y": 360,
        "dy": -3,
        "coord_space": "image",
    })
    if scroll.action != "scroll":
        _fail(f"action={scroll.action}")
    if scroll.dy != -3:
        _fail(f"dy={scroll.dy}")
    steps = format_executed_steps([scroll])
    if "dy=-3.0" not in steps and "dy=-3" not in steps:
        _fail(f"executed steps should include dy: {steps}")
    clamped = parse_action({
        "action": "scroll",
        "x": 1,
        "y": 2,
        "dy": 20,
    })
    if clamped.dy != 8:
        _fail(f"dy should clamp to 8, got {clamped.dy}")
    try:
        parse_action({"action": "scroll", "x": 0.5, "y": 0.5})
        _fail("scroll without dy should fail")
    except SchemaError:
        pass
    try:
        parse_action({"action": "scroll", "x": 0.5, "y": 0.5, "dy": 0})
        _fail("scroll dy=0 should fail")
    except SchemaError:
        pass
    middle = parse_action({
        "action": "middle_click",
        "x": 100,
        "y": 200,
        "coord_space": "image",
    })
    if middle.action != "middle_click":
        _fail(f"action={middle.action}")
    if middle.x != 100 or middle.y != 200:
        _fail(f"middle_click coords {middle}")
    print("  ok")


def test_parse_action_rejects_unknown() -> None:
    print("== parse action rejects unknown ==")
    for bad in [
        {"action": "hover", "x": 0.5, "y": 0.5},
        {"action": "click"},
        {"action": "key"},
        {"action": "wait", "ms": -1},
        {"action": "type"},
        {"action": "scroll", "x": 0.5, "y": 0.5},
        None,
    ]:
        try:
            parse_action(bad)  # type: ignore[arg-type]
            _fail(f"should reject {bad!r}")
        except SchemaError:
            pass
    print("  ok")


def test_parse_action_rejects_bad_coord_space() -> None:
    print("== parse action rejects bad coord_space ==")
    try:
        parse_action({"action": "move", "x": 0.5, "y": 0.5, "coord_space": "pixels"})
        _fail("should reject unknown coord_space")
    except SchemaError:
        pass
    print("  ok")


# -- Observation parsing --

def test_parse_observation_ok() -> None:
    print("== parse observation ok ==")
    obs = parse_observation({
        "run_id": "rid", "step": 1, "ok": True, "error": "",
        "screen": _valid_screen(),
        "image": {"mime": "image/jpeg", "data": _JPEG_B64},
    })
    if obs.run_id != "rid":
        _fail(f"run_id={obs.run_id}")
    if not obs.ok:
        _fail(f"ok={obs.ok}")
    if obs.screen is None:
        _fail("screen is None")
    if obs.image is None:
        _fail("image is None")
    print("  ok")


def test_parse_observation_missing_screen_fails() -> None:
    print("== parse observation missing screen fails ==")
    obs = parse_observation({"run_id": "rid", "step": 1, "ok": True})
    if obs.ok:
        _fail("ok should be False when screen missing")
    if obs.error != "invalid_screen":
        _fail(f"error={obs.error}")
    print("  ok")


def test_parse_observation_rejects_missing_run_id() -> None:
    print("== parse observation rejects missing run_id ==")
    try:
        parse_observation({"step": 1, "ok": True})
        _fail("should reject missing run_id")
    except SchemaError:
        pass
    print("  ok")


def test_parse_screen_partial() -> None:
    print("== parse screen partial ==")
    if parse_screen(None) is not None:
        _fail("None should return None")
    if parse_screen({}) is not None:
        _fail("empty dict should return None")
    screen = parse_screen({
        "origin_x": -1920, "origin_y": 0,
        "phys_w": 1920, "phys_h": 1080,
        "img_w": 1280, "img_h": 720,
    })
    if screen is None:
        _fail("should parse valid screen")
    if screen.origin_x != -1920:
        _fail(f"origin_x={screen.origin_x}")
    print("  ok")


# -- Probe actions: three steps --

def test_probe_actions_order() -> None:
    print("== probe actions order ==")
    actions = probe_actions()
    if len(actions) != 3:
        _fail(f"expected 3 actions, got {len(actions)}")
    if actions[0].action != "move":
        _fail(f"step 1 action={actions[0].action}")
    if actions[0].x != 0.5 or actions[0].y != 0.5:
        _fail(f"step 1 x={actions[0].x} y={actions[0].y}")
    if actions[1].action != "wait":
        _fail(f"step 2 action={actions[1].action}")
    if actions[1].ms != 400:
        _fail(f"step 2 ms={actions[1].ms}")
    if actions[2].action != "key":
        _fail(f"step 3 action={actions[2].action}")
    if actions[2].combo != "escape":
        _fail(f"step 3 combo={actions[2].combo}")
    print("  ok")


# -- Probe loop: success --

def test_run_probe_success() -> None:
    print("== run_probe success ==")
    sent: list[dict[str, Any]] = []

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def wait_obs(run_id: str, step: int) -> ComputerUseObservation | None:
        return _ok_obs(run_id, step)

    result = asyncio.run(run_probe(
        send=send, wait_observation=wait_obs,
        run_id="test-rid", max_steps=8,
    ))
    if not result.ok:
        _fail(f"ok={result.ok} reason={result.reason}")
    if result.run_id != "test-rid":
        _fail(f"run_id={result.run_id}")
    if result.steps_completed != 3:
        _fail(f"steps_completed={result.steps_completed}")
    if len(sent) != 3:
        _fail(f"sent {len(sent)} actions, expected 3")
    for i, payload in enumerate(sent, start=1):
        if payload["type"] != TYPE_COMPUTER_USE_ACTION:
            _fail(f"payload {i} type={payload['type']}")
        if payload["run_id"] != "test-rid":
            _fail(f"payload {i} run_id={payload['run_id']}")
        if payload["step"] != i:
            _fail(f"payload {i} step={payload['step']}")
    if sent[0]["action"] != "move":
        _fail(f"action 1={sent[0]['action']}")
    if sent[1]["action"] != "wait":
        _fail(f"action 2={sent[1]['action']}")
    if sent[2]["action"] != "key":
        _fail(f"action 3={sent[2]['action']}")
    print("  ok")


# -- Probe loop: timeout --

def test_run_probe_timeout() -> None:
    print("== run_probe timeout ==")
    sent: list[dict[str, Any]] = []

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def wait_obs(run_id: str, step: int) -> ComputerUseObservation | None:
        return None

    result = asyncio.run(run_probe(
        send=send, wait_observation=wait_obs,
        run_id="timeout-rid", max_steps=8,
    ))
    if result.ok:
        _fail("ok should be False on timeout")
    if result.reason != "timeout":
        _fail(f"reason={result.reason}")
    if len(sent) != 1:
        _fail(f"sent {len(sent)} actions, expected 1")
    print("  ok")


# -- Probe loop: observation failure --

def test_run_probe_observation_failure() -> None:
    print("== run_probe observation failure ==")
    sent: list[dict[str, Any]] = []

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def wait_obs(run_id: str, step: int) -> ComputerUseObservation | None:
        return ComputerUseObservation(
            run_id=run_id, step=step, ok=False,
            error="sendinput_failed", screen=None, image=None,
        )

    result = asyncio.run(run_probe(
        send=send, wait_observation=wait_obs,
        run_id="fail-rid", max_steps=8,
    ))
    if result.ok:
        _fail("ok should be False")
    if result.reason != "observation_failed":
        _fail(f"reason={result.reason}")
    if len(sent) != 1:
        _fail(f"sent {len(sent)} actions, expected 1")
    print("  ok")


# -- Probe loop: run_id mismatch --

def test_run_probe_run_id_mismatch() -> None:
    print("== run_probe run_id mismatch ==")
    sent: list[dict[str, Any]] = []

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def wait_obs(run_id: str, step: int) -> ComputerUseObservation | None:
        return ComputerUseObservation(
            run_id="wrong-rid", step=step, ok=True,
            error="", screen=parse_screen(_valid_screen()), image=None,
        )

    result = asyncio.run(run_probe(
        send=send, wait_observation=wait_obs,
        run_id="correct-rid", max_steps=8,
    ))
    if result.ok:
        _fail("ok should be False on mismatch")
    if result.reason != "observation_failed":
        _fail(f"reason={result.reason}")
    print("  ok")


# -- Probe loop: abort --

def test_run_probe_abort() -> None:
    print("== run_probe abort ==")
    sent: list[dict[str, Any]] = []

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def wait_obs(run_id: str, step: int) -> ComputerUseObservation | None:
        return _ok_obs(run_id, step)

    def abort_check() -> bool:
        return len(sent) >= 1

    result = asyncio.run(run_probe(
        send=send, wait_observation=wait_obs,
        run_id="abort-rid", max_steps=8,
        abort_check=abort_check,
    ))
    if result.ok:
        _fail("ok should be False on abort")
    if result.reason != "cancelled":
        _fail(f"reason={result.reason}")
    if len(sent) > 1:
        _fail(f"sent {len(sent)} actions, expected at most 1")
    print("  ok")


# -- Probe loop: max_steps zero --

def test_run_probe_max_steps_zero() -> None:
    print("== run_probe max_steps zero ==")
    sent: list[dict[str, Any]] = []

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def wait_obs(run_id: str, step: int) -> ComputerUseObservation | None:
        return _ok_obs(run_id, step)

    result = asyncio.run(run_probe(
        send=send, wait_observation=wait_obs,
        run_id="max-rid", max_steps=0,
    ))
    if result.ok:
        _fail("ok should be False with max_steps=0")
    if result.reason != "max_steps":
        _fail(f"reason={result.reason}")
    if len(sent) != 0:
        _fail(f"sent {len(sent)} actions, expected 0")
    print("  ok")


# -- Terminal messages --

def test_terminal_messages_success() -> None:
    print("== terminal messages success ==")
    result = ProbeResult(
        ok=True, summary="probe complete",
        run_id="rid", steps_completed=3, reason="complete",
    )
    msgs = terminal_messages(result)
    if len(msgs) != 2:
        _fail(f"expected 2 messages, got {len(msgs)}")
    if msgs[0]["type"] != "computer_use_done":
        _fail(f"msg 0 type={msgs[0]['type']}")
    if msgs[0]["ok"] is not True:
        _fail(f"msg 0 ok={msgs[0]['ok']}")
    if msgs[1]["type"] != "chat_response":
        _fail(f"msg 1 type={msgs[1]['type']}")
    if msgs[1]["content"] != "键鼠探针跑完了。":
        _fail(f"msg 1 content={msgs[1]['content']!r}")
    print("  ok")


def test_terminal_messages_timeout() -> None:
    print("== terminal messages timeout ==")
    result = ProbeResult(
        ok=False, summary="timeout",
        run_id="rid", steps_completed=0, reason="timeout",
    )
    msgs = terminal_messages(result)
    if msgs[0]["ok"] is not False:
        _fail(f"done ok={msgs[0]['ok']}")
    if msgs[1]["content"] != "键鼠探针没有跑完。":
        _fail(f"content={msgs[1]['content']!r}")
    print("  ok")


def test_terminal_messages_cancelled() -> None:
    print("== terminal messages cancelled ==")
    result = ProbeResult(
        ok=False, summary="cancelled",
        run_id="rid", steps_completed=0, reason="cancelled",
    )
    msgs = terminal_messages(result)
    if msgs[1]["content"] != "键鼠探针已取消。":
        _fail(f"content={msgs[1]['content']!r}")
    print("  ok")


# -- Protocol helpers --

def test_msg_computer_use_action() -> None:
    print("== msg_computer_use_action ==")
    msg = msg_computer_use_action({"action": "move", "x": 0.5})
    if msg["type"] != TYPE_COMPUTER_USE_ACTION:
        _fail(f"type={msg['type']}")
    if msg["action"] != "move":
        _fail(f"action={msg['action']}")
    print("  ok")


def test_msg_computer_use_done() -> None:
    print("== msg_computer_use_done ==")
    msg = msg_computer_use_done("rid", ok=True, summary="done")
    if msg["type"] != "computer_use_done":
        _fail(f"type={msg['type']}")
    if msg["run_id"] != "rid":
        _fail(f"run_id={msg['run_id']}")
    if msg["ok"] is not True:
        _fail(f"ok={msg['ok']}")
    print("  ok")


# -- Router --

def test_router_deny_words() -> None:
    print("== router deny words ==")
    for text in ("晚安", "老师晚安", "摸头", "想你了", "吃饭了吗", "早饭吃了吗", "晚饭好了"):
        if not is_denied_computer_use(text):
            _fail(f"should deny {text!r}")
    for text in ("按 Win 打开开始菜单", "帮我点那个蓝色按钮", "在当前输入框打：你好"):
        if is_denied_computer_use(text):
            _fail(f"should allow {text!r}")
    print("  ok")


def test_router_parse_computer_use() -> None:
    print("== router parse computer_use ==")
    if parse_route_decision('{"computer_use": true}') is not True:
        _fail("true should parse")
    if parse_route_decision('{"computer_use": false}') is not False:
        _fail("false should parse")
    if parse_route_decision("not json") is not False:
        _fail("invalid json should default false")
    if parse_route_decision({"computer_use": "yes"}) is not True:
        _fail("yes string should be true")
    if parse_route_decision({"action": "reply"}) is not False:
        _fail("missing key should default false")
    print("  ok")


def test_router_default_false() -> None:
    print("== router default false ==")
    router = ComputerUseRouter(
        PlannerConfig(api_key="", enabled=True),
        ComputerUseConfig(enabled=True),
    )

    async def _run() -> None:
        if await router.should_operate("按 Win 打开开始菜单"):
            _fail("no llm key should default false")
        if await router.should_operate("晚安"):
            _fail("deny word should be false")

    asyncio.run(_run())
    print("  ok")


def test_vision_max_tokens_config() -> None:
    print("== computer_use vision_max_tokens is independent ==")
    default_cfg = ComputerUseConfig()
    if default_cfg.vision_max_tokens != 2048:
        _fail(f"default vision_max_tokens={default_cfg.vision_max_tokens}")
    custom = ComputerUseConfig(vision_max_tokens=4096)
    if custom.vision_max_tokens != 4096:
        _fail(f"explicit vision_max_tokens={custom.vision_max_tokens}")
    planner = PlannerConfig(max_tokens=512)
    if planner.max_tokens == custom.vision_max_tokens:
        _fail("planner.max_tokens should stay independent of vision_max_tokens")
    print("  ok")


def test_vision_thinking_config() -> None:
    print("== computer_use vision_thinking toggles deep thinking ==")
    default_cfg = ComputerUseConfig()
    if default_cfg.vision_thinking is not True:
        _fail(f"default vision_thinking={default_cfg.vision_thinking}")
    off = ComputerUseConfig(vision_thinking=False)
    if off.vision_thinking is not False:
        _fail(f"explicit false vision_thinking={off.vision_thinking}")
    on = ComputerUseConfig(vision_thinking=True)
    if on.vision_thinking is not True:
        _fail(f"explicit true vision_thinking={on.vision_thinking}")
    print("  ok")


def test_prompts_allow_long_tasks() -> None:
    print("== computer_use prompts are not short-task gated ==")
    if "短任务" in VISION_SYSTEM:
        _fail("VISION_SYSTEM should not mention 短任务")
    if "按老师原话把任务做完再 done" not in VISION_SYSTEM:
        _fail("VISION_SYSTEM should keep going until the teacher goal is done")
    if "任务短" in ROUTER_SYSTEM:
        _fail("ROUTER_SYSTEM should not require 任务短")
    if "玩游戏，包括玩到通关" not in ROUTER_SYSTEM:
        _fail("ROUTER_SYSTEM should allow games through to completion")
    user_msg = build_vision_user_message(
        user_text="扫雷玩到胜利",
        executed=[],
        img_w=1280,
        img_h=800,
    )
    if "仅当无法继续或目标已完成时输出 done" not in user_msg:
        _fail("vision user message should forbid early done")
    if "【坐标范围】x ∈ [0, 1279]，y ∈ [0, 799]" not in user_msg:
        _fail("vision user message should include image coordinate range")
    if "JSON 必须含 thought" not in user_msg:
        _fail("vision user message should require thought")
    if "不要用示例数字" not in user_msg:
        _fail("vision user message should tell the model not to copy example coordinates")
    if "必须带简短 thought" not in VISION_SYSTEM:
        _fail("VISION_SYSTEM should require a thought field")
    if REPEAT_POINTER_WARNING not in VISION_SYSTEM and "禁止重复点击" not in VISION_SYSTEM:
        _fail("VISION_SYSTEM should forbid repeating the last pointer")
    if CURSOR_MARKER_NOTE not in VISION_SYSTEM:
        _fail("VISION_SYSTEM should explain the magenta cursor crosshair")
    if GRID_MARKER_NOTE not in VISION_SYSTEM:
        _fail("VISION_SYSTEM should explain the cyan coordinate grid")
    if GRID_MARKER_NOTE not in user_msg:
        _fail("vision user message should explain the cyan coordinate grid")
    instruction = build_computer_use_instruction(
        user_text="扫雷",
        summary="已点一格",
        ok=True,
    )
    if "短操作" in instruction:
        _fail("initiate instruction should not call it 短操作")
    print("  ok")


def test_cursor_to_image_xy() -> None:
    print("== cursor maps into image pixels ==")
    mapped = cursor_to_image_xy(
        cursor_x=640,
        cursor_y=400,
        phys_w=1280,
        phys_h=800,
        img_w=2560,
        img_h=1600,
    )
    if mapped != (1280, 800):
        _fail(f"mapped={mapped}")
    if cursor_to_image_xy(
        cursor_x=0, cursor_y=0, phys_w=0, phys_h=800, img_w=2560, img_h=1600
    ) is not None:
        _fail("zero phys size should be None")
    print("  ok")


def test_repeat_pointer_warning() -> None:
    print("== repeat pointer injects warning ==")
    last = ComputerUseAction(
        action="click", x=1280.0, y=800.0, coord_space="image",
    )
    cursor = (1280, 800)
    if not is_repeat_pointer(
        [last], cursor, img_w=2560, img_h=1600,
    ):
        _fail("same image click and cursor should count as repeat")
    if is_repeat_pointer(
        [last], (200, 200), img_w=2560, img_h=1600,
    ):
        _fail("far cursor should not count as repeat")
    wait_only = ComputerUseAction(action="wait", ms=0)
    if is_repeat_pointer(
        [wait_only], cursor, img_w=2560, img_h=1600,
    ):
        _fail("wait should not count as repeat")
    near = ComputerUseAction(
        action="click", x=0.5, y=0.5, coord_space="normalized",
    )
    if not is_repeat_pointer(
        [near], (640, 400), img_w=1280, img_h=800,
    ):
        _fail("normalized center should map near 640,400")
    warned = build_vision_user_message(
        user_text="扫雷",
        executed=[last],
        img_w=2560,
        img_h=1600,
        cursor_img_x=1280,
        cursor_img_y=800,
        repeat_pointer=True,
    )
    if REPEAT_POINTER_WARNING not in warned:
        _fail("repeat warning missing from user message")
    if "【当前光标（image 像素）】1280,800" not in warned:
        _fail("cursor in image pixels missing from user message")
    if CURSOR_MARKER_NOTE not in warned:
        _fail("cursor marker note missing from user message")
    quiet = build_vision_user_message(
        user_text="扫雷",
        executed=[],
        img_w=1280,
        img_h=800,
        repeat_pointer=False,
    )
    if REPEAT_POINTER_WARNING in quiet:
        _fail("warning should not appear on the first step")
    if CURSOR_MARKER_NOTE in quiet:
        _fail("cursor marker note should only appear when cursor coords are known")
    if GRID_MARKER_NOTE not in quiet:
        _fail("grid marker note should appear when image size is known")
    no_size = build_vision_user_message(
        user_text="扫雷",
        executed=[],
        img_w=None,
        img_h=None,
        repeat_pointer=False,
    )
    if GRID_MARKER_NOTE in no_size:
        _fail("grid marker note should not appear without image size")
    print("  ok")


def test_format_route_history() -> None:
    print("== format route history ==")
    history = [
        {"role": "user", "content": "【上线】"},
        {"role": "assistant", "content": "欢迎回来"},
        {"role": "user", "content": "帮我打开记事本写今天日期"},
        {"role": "assistant", "content": "已经写好日期"},
        {"role": "user", "content": "再写一篇介绍"},
    ]
    text = format_route_history(history)
    if "【上线】" in text:
        _fail("should keep only last 4 messages")
    if "帮我打开记事本写今天日期" not in text:
        _fail("should include the teacher's original computer-use request")
    if "【操作电脑】" in text:
        _fail("should not replace teacher speech with the system marker")
    if "已经写好日期" not in text:
        _fail("should include last assistant line")
    if format_route_history(None) != "（无）":
        _fail("empty history should be placeholder")
    msg = build_route_user_message("我是说写在记事本里啦", history)
    if "【近期对话】" not in msg:
        _fail("prompt should include history block")
    if "我是说写在记事本里啦" not in msg:
        _fail("prompt should include current text")
    if "老师：帮我打开记事本写今天日期" not in msg:
        _fail("prompt should label the teacher's original utterance")
    print("  ok")


def test_computer_use_history_content() -> None:
    print("== computer_use history stores original speech ==")
    spoken = "帮我打开记事本写今天日期"
    if computer_use_history_content(spoken) != spoken:
        _fail("history should keep the teacher's original utterance")
    if computer_use_history_content("  写在记事本里  ") != "写在记事本里":
        _fail("history should strip surrounding whitespace")
    if computer_use_history_content("") != HISTORY_COMPUTER_USE_MARKER:
        _fail("empty utterance may fall back to marker")
    if computer_use_history_content(None) != HISTORY_COMPUTER_USE_MARKER:
        _fail("missing utterance may fall back to marker")
    print("  ok")


# -- Vision JSON --

def test_parse_vision_click_image_coords() -> None:
    print("== parse vision click image coords ==")
    action = parse_vision_action(
        '{"thought":"按钮在中间","action":"click","x":640,"y":360}'
    )
    if action.action != "click":
        _fail(f"action={action.action}")
    if action.coord_space != "image":
        _fail(f"coord_space={action.coord_space}")
    if action.x != 640 or action.y != 360:
        _fail(f"x={action.x} y={action.y}")
    print("  ok")


def test_parse_vision_drag_defaults_image() -> None:
    print("== parse vision drag defaults image coords ==")
    action = parse_vision_action(
        '{"action":"drag","x":120,"y":200,"x2":480,"y2":220}'
    )
    if action.action != "drag":
        _fail(f"action={action.action}")
    if action.coord_space != "image":
        _fail(f"coord_space={action.coord_space}")
    if action.x2 != 480 or action.y2 != 220:
        _fail(f"x2={action.x2} y2={action.y2}")
    right = parse_vision_action(
        '{"action":"right_drag","x":1,"y":2,"x2":3,"y2":4}'
    )
    if right.action != "right_drag" or right.coord_space != "image":
        _fail(f"right_drag={right}")
    print("  ok")


def test_parse_vision_scroll_and_middle_click_defaults_image() -> None:
    print("== parse vision scroll / middle_click defaults image coords ==")
    scroll = parse_vision_action(
        '{"action":"scroll","x":640,"y":360,"dy":-3}'
    )
    if scroll.action != "scroll":
        _fail(f"action={scroll.action}")
    if scroll.coord_space != "image":
        _fail(f"coord_space={scroll.coord_space}")
    if scroll.dy != -3:
        _fail(f"dy={scroll.dy}")
    middle = parse_vision_action(
        '{"action":"middle_click","x":10,"y":20}'
    )
    if middle.action != "middle_click" or middle.coord_space != "image":
        _fail(f"middle_click={middle}")
    print("  ok")


def test_parse_vision_done_requires_summary() -> None:
    print("== parse vision done requires summary ==")
    action = parse_vision_action(
        '{"action":"done","summary":"已经按下 Win。"}'
    )
    if action.summary != "已经按下 Win。":
        _fail(f"summary={action.summary!r}")
    try:
        parse_vision_action({"action": "done"})
        _fail("done without summary should fail")
    except SchemaError:
        pass
    print("  ok")


def test_parse_vision_rejects_unknown_action() -> None:
    print("== parse vision rejects unknown action ==")
    try:
        parse_vision_action('{"action":"hover","x":1,"y":1}')
        _fail("should reject hover")
    except SchemaError:
        pass
    try:
        parse_vision_action("not-json")
        _fail("should reject invalid json")
    except SchemaError:
        pass
    print("  ok")


def test_parse_vision_last_json_after_thinking() -> None:
    print("== parse vision last json after thinking ==")
    raw = (
        "The notepad already contains the date. It seems done.\n"
        '{"action":"click","x":1,"y":2}\n'
        '{"action":"done","summary":"已写入今天的日期。"}'
    )
    action = parse_vision_action(raw)
    if action.action != "done":
        _fail(f"action={action.action}")
    if action.summary != "已写入今天的日期。":
        _fail(f"summary={action.summary!r}")
    nested = parse_vision_action(
        '{"thought":{"note":"inner"},"action":"done","summary":"好了。"}'
    )
    if nested.action != "done" or nested.summary != "好了。":
        _fail(f"nested should keep outer done, got {nested}")
    print("  ok")


# -- Agent loop --

class _FakeVision:
    def __init__(self, actions: list[ComputerUseAction | None]) -> None:
        self.actions = list(actions)
        self.calls = 0

    async def plan(self, **kwargs: Any) -> ComputerUseAction | None:
        del kwargs
        if self.calls >= len(self.actions):
            return ComputerUseAction(action="done", summary="结束。")
        action = self.actions[self.calls]
        self.calls += 1
        return action


def test_agent_wait_then_done() -> None:
    print("== agent wait then done ==")
    sent: list[dict[str, Any]] = []
    fake = _FakeVision([ComputerUseAction(action="done", summary="已打开开始菜单。")])

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def wait_obs(run_id: str, step: int) -> ComputerUseObservation | None:
        return _ok_obs_image(run_id, step)

    result = asyncio.run(run_vision_agent(
        send=send, wait_observation=wait_obs,
        client=fake,  # type: ignore[arg-type]
        user_text="按 Win 打开开始菜单",
        run_id="agent-rid", max_steps=1,
    ))
    if not result.ok:
        _fail(f"ok={result.ok} reason={result.reason} summary={result.summary}")
    if result.summary != "已打开开始菜单。":
        _fail(f"summary={result.summary!r}")
    if len(sent) != 1:
        _fail(f"sent {len(sent)} actions, expected 1 wait")
    if sent[0]["action"] != "wait" or sent[0]["ms"] != 0:
        _fail(f"first action={sent[0]}")
    if fake.calls != 1:
        _fail(f"vision calls={fake.calls}")
    print("  ok")


def test_agent_max_steps_truncates_ninth() -> None:
    print("== agent max_steps truncates ninth ==")
    sent: list[dict[str, Any]] = []
    fake = _FakeVision(
        [ComputerUseAction(action="wait", ms=300) for _ in range(12)]
    )

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def wait_obs(run_id: str, step: int) -> ComputerUseObservation | None:
        return _ok_obs_image(run_id, step)

    result = asyncio.run(run_vision_agent(
        send=send, wait_observation=wait_obs,
        client=fake,  # type: ignore[arg-type]
        user_text="帮我点按钮",
        run_id="max8-rid", max_steps=8,
    ))
    if result.ok:
        _fail("ok should be False when truncated")
    if result.reason != "max_steps":
        _fail(f"reason={result.reason}")
    if len(sent) != 9:
        _fail(f"sent {len(sent)} actions, expected 1 bootstrap + 8 counted")
    if sent[0]["action"] != "wait" or sent[0]["ms"] != 0 or sent[0]["step"] != 0:
        _fail(f"bootstrap={sent[0]}")
    if result.steps_completed != 8:
        _fail(f"steps_completed={result.steps_completed}")
    print("  ok")


def test_run_action_loop_invalid_action() -> None:
    print("== action loop invalid action ==")
    sent: list[dict[str, Any]] = []

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def wait_obs(run_id: str, step: int) -> ComputerUseObservation | None:
        return _ok_obs(run_id, step)

    async def next_action(
        step: int,
        last_obs: ComputerUseObservation | None,
        executed: list[ComputerUseAction],
    ) -> ComputerUseAction | None:
        del step, last_obs, executed
        return None

    result = asyncio.run(run_action_loop(
        send=send, wait_observation=wait_obs,
        next_action=next_action, run_id="bad-rid", max_steps=5,
    ))
    if result.ok:
        _fail("ok should be False")
    if result.reason != "invalid_action":
        _fail(f"reason={result.reason}")
    if sent:
        _fail("should not send invalid action")
    print("  ok")


def test_loop_recovers_after_type_when_no_json() -> None:
    print("== loop recovers after type when no json ==")
    sent: list[dict[str, Any]] = []

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def wait_obs(run_id: str, step: int) -> ComputerUseObservation | None:
        return _ok_obs(run_id, step)

    async def next_action(
        step: int,
        last_obs: ComputerUseObservation | None,
        executed: list[ComputerUseAction],
    ) -> ComputerUseAction | None:
        del step, last_obs
        if not executed:
            return ComputerUseAction(action="type", text="2026年9月16日")
        return None

    result = asyncio.run(run_action_loop(
        send=send, wait_observation=wait_obs,
        next_action=next_action, run_id="recover-rid", max_steps=5,
    ))
    if not result.ok:
        _fail(f"ok={result.ok} reason={result.reason}")
    if result.reason != "complete":
        _fail(f"reason={result.reason}")
    if "type" not in result.summary:
        _fail(f"summary={result.summary!r}")
    if len(sent) != 1 or sent[0]["action"] != "type":
        _fail(f"sent={sent}")
    print("  ok")


def test_parallel_route_true_discards_chat() -> None:
    print("== parallel route true discards chat draft ==")
    sent: list[dict[str, Any]] = []
    cu_ran: list[bool] = []

    async def route() -> bool:
        await asyncio.sleep(0.05)
        return True

    async def run_chat(send) -> None:
        await send({"type": "chat_response", "content": "draft"})

    async def run_cu() -> None:
        cu_ran.append(True)

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    operated = asyncio.run(race_route_and_chat(
        route=route, run_chat=run_chat, run_cu=run_cu, send=send,
    ))
    if operated is not True:
        _fail(f"operated={operated}")
    if sent:
        _fail(f"chat draft should not be sent, got {sent}")
    if cu_ran != [True]:
        _fail(f"CU should run, cu_ran={cu_ran}")
    print("  ok")


def test_parallel_route_false_sends_chat() -> None:
    print("== parallel route false sends chat ==")
    sent: list[dict[str, Any]] = []
    cu_ran: list[bool] = []

    async def route() -> bool:
        return False

    async def run_chat(send) -> None:
        await asyncio.sleep(0.02)
        await send({"type": "chat_response", "content": "hello"})

    async def run_cu() -> None:
        cu_ran.append(True)

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    operated = asyncio.run(race_route_and_chat(
        route=route, run_chat=run_chat, run_cu=run_cu, send=send,
    ))
    if operated is not False:
        _fail(f"operated={operated}")
    if cu_ran:
        _fail(f"CU should not run, cu_ran={cu_ran}")
    if len(sent) != 1 or sent[0].get("content") != "hello":
        _fail(f"expected chat payload, got {sent}")
    print("  ok")


def test_parallel_route_error_treated_false() -> None:
    print("== parallel route error treated as false ==")
    sent: list[dict[str, Any]] = []
    cu_ran: list[bool] = []

    async def route() -> bool:
        raise RuntimeError("router down")

    async def run_chat(send) -> None:
        await send({"type": "chat_response", "content": "fallback"})

    async def run_cu() -> None:
        cu_ran.append(True)

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    operated = asyncio.run(race_route_and_chat(
        route=route, run_chat=run_chat, run_cu=run_cu, send=send,
    ))
    if operated is not False:
        _fail(f"operated={operated}")
    if cu_ran:
        _fail(f"CU should not run on route error, cu_ran={cu_ran}")
    if len(sent) != 1 or sent[0].get("content") != "fallback":
        _fail(f"chat should still send, got {sent}")
    print("  ok")


def test_agent_first_vision_none_fails() -> None:
    print("== agent first vision none fails ==")
    sent: list[dict[str, Any]] = []
    fake = _FakeVision([None])

    async def send(payload: dict[str, Any]) -> None:
        sent.append(payload)

    async def wait_obs(run_id: str, step: int) -> ComputerUseObservation | None:
        return _ok_obs_image(run_id, step)

    result = asyncio.run(run_vision_agent(
        send=send, wait_observation=wait_obs,
        client=fake,  # type: ignore[arg-type]
        user_text="帮我写日期",
        run_id="first-none-rid", max_steps=5,
    ))
    if result.ok:
        _fail("ok should be False when only wait ran")
    if result.reason != "invalid_action":
        _fail(f"reason={result.reason}")
    print("  ok")


# -- Main --

def main() -> None:
    tests = [
        test_probe_token_recognition,
        test_action_whitelist,
        test_parse_action_move,
        test_parse_action_wait,
        test_parse_action_key,
        test_parse_action_drag,
        test_parse_action_scroll_and_middle_click,
        test_parse_action_rejects_unknown,
        test_parse_action_rejects_bad_coord_space,
        test_parse_observation_ok,
        test_parse_observation_missing_screen_fails,
        test_parse_observation_rejects_missing_run_id,
        test_parse_screen_partial,
        test_probe_actions_order,
        test_run_probe_success,
        test_run_probe_timeout,
        test_run_probe_observation_failure,
        test_run_probe_run_id_mismatch,
        test_run_probe_abort,
        test_run_probe_max_steps_zero,
        test_terminal_messages_success,
        test_terminal_messages_timeout,
        test_terminal_messages_cancelled,
        test_msg_computer_use_action,
        test_msg_computer_use_done,
        test_router_deny_words,
        test_router_parse_computer_use,
        test_router_default_false,
        test_vision_max_tokens_config,
        test_vision_thinking_config,
        test_prompts_allow_long_tasks,
        test_cursor_to_image_xy,
        test_repeat_pointer_warning,
        test_format_route_history,
        test_computer_use_history_content,
        test_parse_vision_click_image_coords,
        test_parse_vision_drag_defaults_image,
        test_parse_vision_scroll_and_middle_click_defaults_image,
        test_parse_vision_done_requires_summary,
        test_parse_vision_rejects_unknown_action,
        test_parse_vision_last_json_after_thinking,
        test_agent_wait_then_done,
        test_agent_max_steps_truncates_ninth,
        test_run_action_loop_invalid_action,
        test_loop_recovers_after_type_when_no_json,
        test_parallel_route_true_discards_chat,
        test_parallel_route_false_sends_chat,
        test_parallel_route_error_treated_false,
        test_agent_first_vision_none_fails,
    ]
    for test in tests:
        test()
    print()
    print(f"All {len(tests)} tests passed.")


if __name__ == "__main__":
    main()
