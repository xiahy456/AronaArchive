#!/usr/bin/env python3
"""Napcat QQ channel: clause split, inbound filter, prompt method, offline impulse."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.channel import method_label  # noqa: E402
from app.config import NapcatConfig, load_config  # noqa: E402
from app.conversation import ConversationManager, DialogueEntry, _format_transcript  # noqa: E402
from app.life.impulse import _speak_impulse  # noqa: E402
from app.life.state import Impulse, InnerState  # noqa: E402
from app.napcat import NapcatLink, QqInbox, build_send_private, private_text_from_event, split_qq_clauses  # noqa: E402
from app.napcat.link import CLAUSE_GAP_SEC  # noqa: E402
from app.planner.prompts import build_planner_user_message  # noqa: E402
from app.planner.schema import parse_and_gate_intent  # noqa: E402


def _fail(msg: str) -> None:
    print("FAIL", msg)
    raise SystemExit(1)


def test_split() -> None:
    cases = [
        ("我一直在这里等着哦。", ["我一直在这里等着哦。"]),
        ("诶……原来是这样吗。", ["诶……原来是这样吗。"]),
        ("欢迎回来，老师！今天想做什么？", ["欢迎回来，老师！", "今天想做什么？"]),
        (
            "诶？！怎么会这样！那就麻烦了呢……",
            ["诶？！", "怎么会这样！", "那就麻烦了呢……"],
        ),
        ("等等...我在。", ["等等...我在。"]),
        ("a..b", ["a..", "b"]),
    ]
    for text, expected in cases:
        got = split_qq_clauses(text)
        if got != expected:
            _fail(f"split {text!r} -> {got!r} expected {expected!r}")
    if split_qq_clauses("   ") != []:
        _fail("blank text should not send")
    print("split ok")


def test_inbound() -> None:
    event = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 10001,
        "message": [
            {"type": "text", "data": {"text": "老师"}},
            {"type": "face", "data": {"id": "1"}},
            {"type": "text", "data": {"text": "在吗"}},
        ],
    }
    if private_text_from_event(event, "10001") != "老师在吗":
        _fail("private text segments should join")
    group = dict(event, message_type="group")
    if private_text_from_event(group, "10001") is not None:
        _fail("group messages must be ignored")
    if private_text_from_event(event, "10002") is not None:
        _fail("other qq ids must be ignored")
    if private_text_from_event(event, "") is not None:
        _fail("empty user_qq_id must ignore inbound")
    image_only = dict(event, message=[{"type": "image", "data": {"file": "a.jpg"}}])
    if private_text_from_event(image_only, "10001") is not None:
        _fail("non-text segments must not become a turn")
    if private_text_from_event({"post_type": "meta_event"}, "10001") is not None:
        _fail("heartbeat must be ignored")
    frame = build_send_private("10001", "在的")
    if frame["action"] != "send_private_msg":
        _fail("outbound action")
    if frame["params"]["user_id"] != 10001:
        _fail("user_id should be an int")
    if frame["params"]["message"] != [{"type": "text", "data": {"text": "在的"}}]:
        _fail(f"array message {frame['params']['message']}")
    print("inbound ok")


def test_prompt_method() -> None:
    if method_label("") != "面对面交流" or method_label("message") != "QQ消息":
        _fail("method labels")
    msg = build_planner_user_message(
        user_text="我还在工作呢，正好现在休息一下就来看看你",
        history=[
            {
                "role": "assistant",
                "content": "我一直在这里等着哦。",
                "time": "2026-09-28T12:00:07",
                "method": "direct",
            },
            {
                "role": "user",
                "content": "下午还有工作，我待会再回来找你。",
                "time": "2026-09-28T13:12:15",
                "method": "message",
            },
            {
                "role": "user",
                "content": "旧记录没有方式",
                "time": "2026-09-28T09:00:00",
            },
        ],
        memories=[],
        knowledge=[],
        now=datetime(2026, 9, 28, 13, 12, 15),
        teacher_method="message",
        channels_block="【可送达通道】\n- 面对面：不在线\n- QQ：已连接",
    )
    if "[2026年9月28日 12:00:07 面对面交流] 阿洛娜：我一直在这里等着哦。" not in msg:
        _fail(f"direct history line missing:\n{msg}")
    if "[2026年9月28日 13:12:15 QQ消息] 老师：下午还有工作，我待会再回来找你。" not in msg:
        _fail("qq history line missing")
    if "[2026年9月28日 09:00:00 面对面交流] 老师：旧记录没有方式" not in msg:
        _fail("missing method should read as face to face")
    if "【老师本轮消息】\n[QQ消息] 我还在工作呢" not in msg:
        _fail("current turn should carry the channel")
    if "【可送达通道】" not in msg:
        _fail("channel availability should be in the planner user message")
    plain = build_planner_user_message(
        user_text="【系统事件】老师刚上线",
        history=[],
        memories=[],
        knowledge=[],
    )
    if "[面对面交流]" in plain.split("【老师本轮消息】", 1)[1]:
        _fail("system instructions must not be labeled as a teacher channel")
    card = parse_and_gate_intent(
        '{"draft":"在的","reply_ok":true,"method":"message","arona_emotion":"smile"}'
    )
    if card is None or card.method != "message":
        _fail(f"method parse {card}")
    blank = parse_and_gate_intent('{"draft":"在的","reply_ok":true,"method":"qq"}')
    if blank is None or blank.method != "":
        _fail("illegal method must stay empty for the caller to default")
    legacy = _format_transcript([{"role": "user", "content": "早"}])
    if legacy != "[面对面交流] 老师: 早":
        _fail(f"transcript default {legacy!r}")
    store = ConversationManager(persist_path=None)
    assert store._store is not None
    store._store.entries.append(
        DialogueEntry(role="user", kind="speech", content="早", time="2026-09-28T08:00:00")
    )
    line = store.get_history("")[0]
    if line.get("method"):
        _fail("old rows stay without a method value")
    print("prompt method ok")


class _Ws:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_text(self, raw: str) -> None:
        self.frames.append(json.loads(raw))


async def test_link_send() -> None:
    if CLAUSE_GAP_SEC != 2.0:
        _fail("clause gap should default to 2 seconds")
    link = NapcatLink("42", gap_sec=0)
    ws = _Ws()
    await link.bind(ws)  # type: ignore[arg-type]
    ok = await link.send_text("欢迎回来，老师！今天想做什么？")
    if not ok or len(ws.frames) != 2:
        _fail(f"expected two frames, got {ws.frames}")
    if ws.frames[0]["params"]["message"][0]["data"]["text"] != "欢迎回来，老师！":
        _fail("first clause")
    if ws.frames[1]["params"]["message"][0]["data"]["text"] != "今天想做什么？":
        _fail("second clause")
    down = NapcatLink("42", gap_sec=0)
    if await down.send_text("在吗"):
        _fail("disconnected link must not report success")
    print("link send ok")


class _Hub:
    def __init__(self) -> None:
        self._busy: set[str] = set()

    def all_sessions(self):
        return []

    def idle_sessions(self):
        return []

    def get(self, session_id: str):
        return None

    def is_busy(self, session_id: str) -> bool:
        return session_id in self._busy

    def set_busy(self, session_id: str, busy: bool) -> None:
        if busy:
            self._busy.add(session_id)
        else:
            self._busy.discard(session_id)


class _Store:
    def save(self, _state) -> None:
        return None


class _Engine:
    def __init__(self, impulse: Impulse) -> None:
        self.state = InnerState(pending_impulse=impulse)
        self.store = _Store()


class _Orch:
    def __init__(self, result: str, method: str) -> None:
        self.calls = 0
        self.result = result
        self.last_outbound_method = method
        self.relationship = None

    async def handle_initiate(self, **_kwargs):
        self.calls += 1
        return self.result


class _Link:
    def __init__(self, connected: bool) -> None:
        self.connected = connected
        self.user_qq_id = "10001"


class _State:
    def __init__(self, orch: _Orch, engine: _Engine, hub: _Hub, link: _Link | None) -> None:
        self.orchestrator = orch
        self.life = engine
        self.hub = hub
        self.napcat = link
        self.scheduler = None
        self.config = None


def _impulse() -> Impulse:
    return Impulse(kind="idle", instruction="想老师了", history_marker="")


async def test_offline_impulse() -> None:
    now = datetime(2026, 9, 29, 12, 0, 0)
    direct = _Orch("deferred", "direct")
    state = _State(direct, _Engine(_impulse()), _Hub(), _Link(True))
    spoke = await _speak_impulse(state, now=now)
    if spoke or direct.calls != 1:
        _fail(f"offline direct should plan once, calls={direct.calls} spoke={spoke}")
    pending = state.life.state.pending_impulse
    if pending is None or pending.await_channel != "client":
        _fail(f"direct while offline should wait for the client, got {pending}")
    again = await _speak_impulse(state, now=now)
    if again or direct.calls != 1:
        _fail("a held direct impulse must not call the model every tick")

    sent = _Orch("sent", "message")
    sent_state = _State(sent, _Engine(_impulse()), _Hub(), _Link(True))
    ok = await _speak_impulse(sent_state, now=now)
    if not ok or sent.calls != 1 or sent_state.life.state.pending_impulse is not None:
        _fail("message delivery should clear the impulse")

    blocked = _Orch("sent", "message")
    quiet = _State(blocked, _Engine(_impulse()), _Hub(), _Link(False))
    if await _speak_impulse(quiet, now=now) or blocked.calls:
        _fail("no channel should skip the model")
    print("offline impulse ok")


class _Chat:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def handle_chat(self, **kwargs):
        self.texts.append(kwargs["content"])
        if kwargs.get("inbound_method") != "message":
            _fail("qq turns must be marked message")
        return True


async def test_coalesce() -> None:
    orch = _Chat()
    state = _State(_Orch("sent", "message"), _Engine(_impulse()), _Hub(), None)
    state.orchestrator = orch
    state.generation_kind = ""
    state.generation_owner = ""
    state.generation_interrupts = {}
    inbox = QqInbox(state, coalesce_sec=0.05)
    await inbox.push("第一句")
    await inbox.push("第二句")
    await asyncio.sleep(0.2)
    if orch.texts != ["第一句\n第二句"]:
        _fail(f"coalesce got {orch.texts}")
    print("coalesce ok")


def test_config() -> None:
    cfg = NapcatConfig(user_qq_id=10001, napcat_ws_path="arona", napcat_token=" tok ")
    if cfg.user_qq_id != "10001" or cfg.napcat_ws_path != "/arona" or cfg.napcat_token != "tok":
        _fail(f"napcat config normalize {cfg}")
    loaded = load_config()
    if loaded.napcat.napcat_ws_path != "/arona":
        _fail("example yaml should default the napcat path")
    print("config ok")


def main() -> None:
    test_split()
    test_inbound()
    test_prompt_method()
    test_config()
    asyncio.run(test_link_send())
    asyncio.run(test_offline_impulse())
    asyncio.run(test_coalesce())
    print("napcat unit ok")


if __name__ == "__main__":
    main()
