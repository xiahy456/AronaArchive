#!/usr/bin/env python3
"""Napcat QQ channel: clause split, inbound filter, prompt method, offline impulse."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.channel import (  # noqa: E402
    METHOD_DIRECT,
    METHOD_MESSAGE,
    default_outbound_method,
    method_label,
    resolve_outbound_method,
)
from app.config import NapcatConfig, load_config  # noqa: E402
from app.conversation import ConversationManager, DialogueEntry, _format_transcript  # noqa: E402
from app.life.impulse import _speak_impulse  # noqa: E402
from app.life.state import Impulse, InnerState  # noqa: E402
from app.napcat import NapcatLink, QqInbox, build_send_private, private_text_from_event, split_qq_clauses  # noqa: E402
from app.napcat.link import EMOJI_GAP_SEC, clause_gap_sec  # noqa: E402
from app.emoji_catalog import load_emoji_catalog, lookup_emoji, sticker_from_row  # noqa: E402
from app.planner.prompts import (  # noqa: E402
    PLANNER_SYSTEM_BASE,
    PLANNER_SYSTEM_CRISIS,
    build_planner_user_message,
)
from app.image_input import image_payload_from_napcat_file  # noqa: E402
from app.napcat.protocol import (  # noqa: E402
    QqFileImage,
    QqUrlImage,
    friend_recall_from_event,
    private_inbound_from_event,
)
from app.planner.client import qq_image_content  # noqa: E402
from app.planner.schema import parse_and_gate_intent  # noqa: E402


def _fail(msg: str) -> None:
    print("FAIL", msg)
    raise SystemExit(1)


def test_split() -> None:
    cases = [
        ("我一直在这里等着哦。", ["我一直在这里等着哦"]),
        ("诶……原来是这样吗。", ["诶……原来是这样吗"]),
        ("欢迎回来，老师！今天想做什么？", ["欢迎回来", "老师！", "今天想做什么？"]),
        (
            "诶？！怎么会这样！那就麻烦了呢……",
            ["诶？！", "怎么会这样！", "那就麻烦了呢……"],
        ),
        ("等等...我在。", ["等等...我在"]),
        ("a..b", ["a..", "b"]),
        ("不过，其实感觉还好啦", ["不过，其实感觉还好啦"]),
        ("听到老师这么说，我的脸好像有点热热的呢", ["听到老师这么说", "我的脸好像有点热热的呢"]),
        (
            "诶……老师怎么突然回这么一句啦！我、我刚刚那是为了测试才说的呀……可是，听到老师这么说，我的脸好像有点热热的呢。",
            [
                "诶……老师怎么突然回这么一句啦！",
                "我、我刚刚那是为了测试才说的呀……可是，听到老师这么说",
                "我的脸好像有点热热的呢",
            ],
        ),
        ("「诶？」这句话吗？", ["「诶？」这句话吗？"]),
        ("6.5分", ["6.5分"]),
        ("结束了.下一句", ["结束了", "下一句"]),
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


def test_clause_gap() -> None:
    if clause_gap_sec("") != 0.0:
        _fail("empty next clause gap is 0")
    if EMOJI_GAP_SEC != 0.5:
        _fail(f"emoji gap {EMOJI_GAP_SEC}")
    sample = "今天想做什么？"
    n = len(sample)
    lo, hi = 0.08 * n, 0.15 * n
    for _ in range(40):
        gap = clause_gap_sec(sample)
        if gap < lo - 1e-9 or gap > hi + 1e-9:
            _fail(f"gap {gap} outside [{lo}, {hi}] for n={n}")
        if round(gap, 2) != gap:
            _fail(f"gap {gap} must have at most two decimals")
    print("clause gap ok")


async def test_link_send() -> None:
    link = NapcatLink("42", gap_sec=0)
    ws = _Ws()
    await link.bind(ws)  # type: ignore[arg-type]
    ok = await link.send_text("欢迎回来老师！今天想做什么？")
    if not ok or len(ws.frames) != 2:
        _fail(f"expected two frames, got {ws.frames}")
    if ws.frames[0]["params"]["message"][0]["data"]["text"] != "欢迎回来老师！":
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


class _GateChat:
    """handle_chat that blocks on a per-call gate so tests can barge in."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.gates: list[asyncio.Event] = []
        self.calls = 0

    async def handle_chat(self, **kwargs):
        self.calls += 1
        if kwargs.get("inbound_method") != "message":
            _fail("qq turns must be marked message")
        gate = asyncio.Event()
        self.gates.append(gate)
        await gate.wait()
        abort_check = kwargs.get("abort_check")
        on_reply_ready = kwargs.get("on_reply_ready")
        if abort_check is not None and abort_check():
            return False
        if on_reply_ready is not None:
            on_reply_ready()
        if abort_check is not None and abort_check():
            return False
        self.texts.append(kwargs["content"])
        return True


async def _wait_gates(orch: object, count: int, *, timeout: float = 2.0) -> None:
    gates = getattr(orch, "gates")
    deadline = time.monotonic() + timeout
    while len(gates) < count:
        if time.monotonic() >= deadline:
            _fail(f"expected {count} chat gates, got {len(gates)}")
        await asyncio.sleep(0.01)


async def test_barge_in_merges() -> None:
    orch = _GateChat()
    state = _State(_Orch("sent", "message"), _Engine(_impulse()), _Hub(), None)
    state.orchestrator = orch
    state.generation_kind = ""
    state.generation_owner = ""
    state.generation_interrupts = {}
    inbox = QqInbox(state, coalesce_sec=0.05)
    await inbox.push("第一句")
    await _wait_gates(orch, 1)
    await inbox.push("第二句")
    await _wait_gates(orch, 2)
    orch.gates[-1].set()
    deadline = time.monotonic() + 2.0
    while not orch.texts and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    if orch.texts != ["第一句\n第二句"]:
        _fail(f"barge-in merge got {orch.texts} calls={orch.calls}")
    print("barge-in merge ok")


async def test_after_ready_holds() -> None:
    orch = _GateChat()
    state = _State(_Orch("sent", "message"), _Engine(_impulse()), _Hub(), None)
    state.orchestrator = orch
    state.generation_kind = ""
    state.generation_owner = ""
    state.generation_interrupts = {}
    inbox = QqInbox(state, coalesce_sec=0.05)
    await inbox.push("第一句")
    await _wait_gates(orch, 1)
    # Seal before finishing so a late message must wait for the next window.
    ready = orch.gates[0]
    # Drive seal by finishing the first turn's abort-check path via on_reply_ready:
    # release the gate; handle_chat seals then records the text.
    ready.set()
    deadline = time.monotonic() + 2.0
    while not orch.texts and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    if orch.texts != ["第一句"]:
        _fail(f"first turn should complete, got {orch.texts}")
    # After the first turn finishes, _held from a mid-deliver push would release.
    # Push while reply_ready during deliver: seal happens inside handle_chat before
    # return, then _running clears. Push after completion starts a new coalesce.
    await inbox.push("第二句")
    await _wait_gates(orch, 2)
    orch.gates[1].set()
    deadline = time.monotonic() + 2.0
    while len(orch.texts) < 2 and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    if orch.texts != ["第一句", "第二句"]:
        _fail(f"after-ready next window got {orch.texts}")
    print("after-ready hold ok")


async def test_barge_in_after_seal_keeps_reply() -> None:
    """Once on_reply_ready fires, a new message must not discard that reply."""

    class _SealThenHoldChat:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.gates: list[asyncio.Event] = []
            self.calls = 0

        async def handle_chat(self, **kwargs):
            self.calls += 1
            abort_check = kwargs.get("abort_check")
            on_reply_ready = kwargs.get("on_reply_ready")
            if on_reply_ready is not None:
                on_reply_ready()
            gate = asyncio.Event()
            self.gates.append(gate)
            await gate.wait()
            if abort_check is not None and abort_check():
                return False
            self.texts.append(kwargs["content"])
            return True

    orch = _SealThenHoldChat()
    state = _State(_Orch("sent", "message"), _Engine(_impulse()), _Hub(), None)
    state.orchestrator = orch
    state.generation_kind = ""
    state.generation_owner = ""
    state.generation_interrupts = {}
    inbox = QqInbox(state, coalesce_sec=0.05)
    await inbox.push("第一句")
    await _wait_gates(orch, 1)
    await inbox.push("第二句")
    orch.gates[0].set()
    deadline = time.monotonic() + 2.0
    while not orch.texts and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    if orch.texts != ["第一句"]:
        _fail(f"sealed reply must be kept, got {orch.texts} calls={orch.calls}")
    await _wait_gates(orch, 2)
    orch.gates[1].set()
    deadline = time.monotonic() + 2.0
    while len(orch.texts) < 2 and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    if orch.texts != ["第一句", "第二句"]:
        _fail(f"held message should follow, got {orch.texts}")
    print("after-seal keep reply ok")


def test_emoji_catalog() -> None:
    known = lookup_emoji("4b9ca94171d02f28e7829afa28709c45")
    if known is None or known.description != "抽到了":
        _fail(f"catalog lookup {known}")
    if known.package_id_value() != 235125 or not isinstance(known.package_id_value(), int):
        _fail(f"package id {known.package_id_value()!r}")
    if lookup_emoji("smile") is not None or lookup_emoji("") is not None:
        _fail("unknown or empty emoji must miss")
    if sticker_from_row({"emoji_id": "abc", "description": "x"}) is not None:
        _fail("blank fields must be skipped")
    if sticker_from_row(["not", "an", "object"]) is not None:
        _fail("non-object must be skipped")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.json").write_text(
            json.dumps(
                [
                    {
                        "emoji_package_id": "",
                        "emoji_id": "bad",
                        "key": "k",
                        "summary": "s",
                        "description": "d",
                    },
                    {
                        "emoji_package_id": "1",
                        "emoji_id": "keep",
                        "key": "k",
                        "summary": "[a]",
                        "description": "好耶",
                    },
                    "nope",
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (root / "b.json").write_text(
            json.dumps(
                [
                    {
                        "emoji_package_id": "9",
                        "emoji_id": "keep",
                        "key": "other",
                        "summary": "[b]",
                        "description": "重复",
                    }
                ]
            ),
            encoding="utf-8",
        )
        loaded = load_emoji_catalog(root)
    if len(loaded) != 1 or loaded[0].description != "好耶" or loaded[0].key != "k":
        _fail(f"catalog filter {loaded}")
    pair = "好耶：d67b510a9eb2e41c31fbe3810eb06ee6"
    if pair not in PLANNER_SYSTEM_BASE or pair not in PLANNER_SYSTEM_CRISIS:
        _fail("prompt must pair description with emoji_id")
    if "必须从下列英文值中原样选一个" not in PLANNER_SYSTEM_BASE:
        _fail("direct emotion whitelist must stay")
    kept = parse_and_gate_intent(
        '{"draft":"好耶","reply_ok":true,"method":"message",'
        '"arona_emotion":"4b9ca94171d02f28e7829afa28709c45"}'
    )
    if kept is None or kept.arona_emotion != "4b9ca94171d02f28e7829afa28709c45":
        _fail(f"message keeps emoji id {kept}")
    illegal = parse_and_gate_intent(
        '{"draft":"好耶","reply_ok":true,"method":"message","arona_emotion":"SMILE"}'
    )
    if illegal is None or illegal.arona_emotion != "SMILE":
        _fail(f"message must not fold unknown faces {illegal}")
    blank = parse_and_gate_intent(
        '{"draft":"好耶","reply_ok":true,"method":"message","arona_emotion":""}'
    )
    if blank is None or blank.arona_emotion != "":
        _fail(f"empty message emotion stays empty {blank}")
    direct = parse_and_gate_intent(
        '{"draft":"好","reply_ok":true,"method":"direct","arona_emotion":"SMILE"}'
    )
    if direct is None or direct.arona_emotion != "smile":
        _fail(f"direct still normalizes {direct}")
    unknown = parse_and_gate_intent(
        '{"draft":"好","reply_ok":true,"method":"direct","arona_emotion":"not-a-face"}'
    )
    if unknown is None or unknown.arona_emotion != "normal":
        _fail(f"direct unknown becomes normal {unknown}")
    print("emoji catalog ok")


async def test_emoji_send() -> None:
    sticker = lookup_emoji("4b9ca94171d02f28e7829afa28709c45")
    if sticker is None:
        _fail("missing sample sticker")
    link = NapcatLink("42", gap_sec=0)
    ws = _Ws()
    await link.bind(ws)  # type: ignore[arg-type]
    ok = await link.send_text("欢迎回来老师！今天想做什么？", emoji=sticker)
    if not ok or len(ws.frames) != 3:
        _fail(f"expected two texts then mface, got {ws.frames}")
    if ws.frames[0]["params"]["message"][0]["type"] != "text":
        _fail("first frame is text")
    if ws.frames[1]["params"]["message"][0]["type"] != "text":
        _fail("second frame is text")
    face = ws.frames[2]["params"]["message"][0]
    if face["type"] != "mface":
        _fail(f"third frame {face}")
    data = face["data"]
    if data["emoji_package_id"] != 235125 or not isinstance(data["emoji_package_id"], int):
        _fail(f"package id {data['emoji_package_id']!r}")
    if data["emoji_id"] != sticker.emoji_id or data["key"] != sticker.key:
        _fail(f"mface identity {data}")
    if data["summary"] != "[抽到了]":
        _fail(f"summary {data['summary']!r}")
    alone = NapcatLink("42", gap_sec=0)
    sink = _Ws()
    await alone.bind(sink)  # type: ignore[arg-type]
    if await alone.send_text("   ", emoji=sticker) or sink.frames:
        _fail("no text clause must not send a sticker alone")
    print("emoji send ok")


def test_qq_images() -> None:
    def event(message: list[dict]) -> dict:
        return {
            "post_type": "message",
            "message_type": "private",
            "user_id": 10001,
            "message": message,
        }

    known_id = "d67b510a9eb2e41c31fbe3810eb06ee6"
    mall = event(
        [
            {
                "type": "image",
                "data": {
                    "emoji_id": known_id,
                    "emoji_package_id": "235125",
                    "summary": "[星星]",
                    "url": "https://example.test/a.gif",
                },
            }
        ]
    )
    mall_in = private_inbound_from_event(mall, "10001")
    if mall_in is None or mall_in.text != "（表情包：好耶）" or mall_in.images:
        _fail(f"known mall sticker {mall_in}")
    mixed = event(
        [
            {"type": "text", "data": {"text": "看这个"}},
            {
                "type": "image",
                "data": {
                    "emoji_id": known_id,
                    "emoji_package_id": "235125",
                    "summary": "[星星]",
                    "url": "https://example.test/a.gif",
                },
            },
        ]
    )
    mixed_in = private_inbound_from_event(mixed, "10001")
    if mixed_in is None or mixed_in.text != "看这个（表情包：好耶）" or mixed_in.images:
        _fail(f"text plus mall sticker {mixed_in}")
    unknown = event(
        [
            {
                "type": "image",
                "data": {
                    "emoji_id": "not-in-catalog",
                    "emoji_package_id": "1",
                    "summary": "[期待]",
                    "url": "https://example.test/a.gif",
                },
            }
        ]
    )
    if private_inbound_from_event(unknown, "10001") is not None:
        _fail("unknown mall sticker must not enqueue")
    favorite = event(
        [
            {
                "type": "image",
                "data": {
                    "sub_type": "1",
                    "summary": "[动画表情]",
                    "url": "https://example.test/b.jpg",
                    "file": "b.jpg",
                },
            }
        ]
    )
    if private_inbound_from_event(favorite, "10001") is not None:
        _fail("favorite sticker must not enqueue")
    photo = event(
        [
            {"type": "text", "data": {"text": "看这个"}},
            {
                "type": "image",
                "data": {
                    "file": "a.png",
                    "sub_type": 0,
                    "url": "https://multimedia.nt.qq.com.cn/download?x=1",
                },
            },
        ]
    )
    inbound = private_inbound_from_event(photo, "10001")
    if inbound is None or inbound.text != "看这个" or len(inbound.images) != 1:
        _fail(f"photo inbound {inbound}")
    if not isinstance(inbound.images[0], QqUrlImage):
        _fail("photo should stay a url")
    if inbound.images[0].url != "https://multimedia.nt.qq.com.cn/download?x=1":
        _fail(f"photo url {inbound.images[0]}")
    bare = event(
        [{"type": "image", "data": {"file": "c.png", "url": "https://example.test/c.png"}}]
    )
    bare_in = private_inbound_from_event(bare, "10001")
    if bare_in is None or bare_in.text or not isinstance(bare_in.images[0], QqUrlImage):
        _fail("missing sub_type with empty summary is a photo")
    filed = event(
        [{"type": "file", "data": {"file": "shot.png", "file_id": "fid-1", "file_size": "12"}}]
    )
    filed_in = private_inbound_from_event(filed, "10001")
    if (
        filed_in is None
        or not isinstance(filed_in.images[0], QqFileImage)
        or filed_in.images[0].file_id != "fid-1"
    ):
        _fail(f"file image {filed_in}")
    pdf = event([{"type": "file", "data": {"file": "notes.pdf", "file_id": "fid-2"}}])
    if private_inbound_from_event(pdf, "10001") is not None:
        _fail("non-image file must not enqueue")
    qq_prompt = build_planner_user_message(
        user_text="看这个",
        history=[],
        memories=[],
        knowledge=[],
        has_qq_images=True,
    )
    if "本轮附带老师发来的图片，请结合图片和文字一起理解。" not in qq_prompt:
        _fail("qq image prompt")
    if "仅在回答需要截图上的信息时" in qq_prompt:
        _fail("qq images must not use the screenshot sentence")
    shot = build_planner_user_message(
        user_text="看屏幕",
        history=[],
        memories=[],
        knowledge=[],
        has_screenshot=True,
    )
    if "仅在回答需要截图上的信息时" not in shot:
        _fail("screenshot prompt")
    if "本轮附带老师发来的图片" in shot:
        _fail("screenshot must not use the qq sentence")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    encoded = base64.b64encode(png).decode("ascii")
    payload = image_payload_from_napcat_file({"data": {"base64": encoded, "file_name": "a.png"}})
    if payload is None or not payload.data_url().startswith("data:image/png;base64,"):
        _fail("get_file base64 data url")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "local.png"
        path.write_bytes(png)
        local = image_payload_from_napcat_file({"data": {"file": str(path)}})
    if local is None or local.mime != "image/png":
        _fail("get_file local path")
    content = qq_image_content("文字", ["https://example.test/a.png", payload])
    if content[0]["type"] != "text" or content[1]["image_url"]["url"] != "https://example.test/a.png":
        _fail("url image stays external")
    if not str(content[2]["image_url"]["url"]).startswith("data:image/png;base64,"):
        _fail("file image is inline")
    print("qq images ok")


async def test_get_file_roundtrip() -> None:
    link = NapcatLink("42", gap_sec=0)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    encoded = base64.b64encode(png).decode("ascii")

    class _Reply:
        async def send_text(self, raw: str) -> None:
            frame = json.loads(raw)
            if frame.get("action") != "get_file" or frame["params"].get("file_id") != "fid-1":
                _fail(f"get_file frame {frame}")
            link.complete_echo(
                {"status": "ok", "echo": frame["echo"], "data": {"base64": encoded}}
            )

    await link.bind(_Reply())  # type: ignore[arg-type]
    frame = await link.get_file("fid-1")
    payload = image_payload_from_napcat_file(frame)
    if payload is None or payload.mime != "image/png":
        _fail(f"get_file roundtrip {frame}")
    print("get_file ok")


def test_outbound_qq_fallback() -> None:
    # inbound QQ + model picked direct while desktop offline → stay on QQ
    got = resolve_outbound_method(
        METHOD_DIRECT,
        inbound=METHOD_MESSAGE,
        proactive=False,
        client_online=False,
    )
    if got != METHOD_MESSAGE:
        _fail(f"offline QQ inbound must fall back to message, got {got}")
    # desktop online: honor explicit direct
    got_online = resolve_outbound_method(
        METHOD_DIRECT,
        inbound=METHOD_MESSAGE,
        proactive=False,
        client_online=True,
    )
    if got_online != METHOD_DIRECT:
        _fail(f"online client may keep direct, got {got_online}")
    # continue after QQ: default stays on message even if client online
    cont = default_outbound_method(
        inbound=METHOD_MESSAGE,
        proactive=True,
        client_online=True,
    )
    if cont != METHOD_MESSAGE:
        _fail(f"QQ continue default must be message, got {cont}")
    print("outbound qq fallback ok")


def test_friend_recall_parse() -> None:
    notice = {
        "post_type": "notice",
        "notice_type": "friend_recall",
        "user_id": 10001,
        "message_id": 4242,
    }
    if friend_recall_from_event(notice, "10001") != "4242":
        _fail("friend_recall should yield message_id")
    if friend_recall_from_event(notice, "10002") is not None:
        _fail("other qq ids must ignore recall")
    if friend_recall_from_event({"post_type": "message"}, "10001") is not None:
        _fail("non-notice must ignore recall")
    msg = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 10001,
        "message_id": 99,
        "message": [{"type": "text", "data": {"text": "嗨"}}],
    }
    inbound = private_inbound_from_event(msg, "10001")
    if inbound is None or inbound.message_id != "99":
        _fail(f"inbound must keep message_id {inbound}")
    print("friend recall parse ok")


def test_dialogue_recall() -> None:
    store = ConversationManager(persist_path=None)
    store.append(
        "qq",
        "user",
        "第一句\n第二句",
        method="message",
        qq_parts=[
            {"message_id": "1", "text": "第一句"},
            {"message_id": "2", "text": "第二句"},
        ],
    )
    store.append("qq", "assistant", "收到", method="message")
    if not store.remove_qq_message("1"):
        _fail("remove_qq_message should find id 1")
    entries = store.entries()
    users = [item for item in entries if item.role == "user"]
    if len(users) != 1 or users[0].content != "第二句":
        _fail(f"dialogue rewrite {users}")
    if users[0].qq_parts != [{"message_id": "2", "text": "第二句"}]:
        _fail(f"qq_parts {users[0].qq_parts}")
    if not store.remove_qq_message("2"):
        _fail("remove last part")
    if any(item.role == "user" for item in store.entries()):
        _fail("empty qq user row should be deleted")
    if not any(item.role == "assistant" for item in store.entries()):
        _fail("assistant reply stays")
    print("dialogue recall ok")


async def test_inbox_recall() -> None:
    orch = _Chat()
    state = _State(_Orch("sent", "message"), _Engine(_impulse()), _Hub(), None)
    state.orchestrator = orch
    state.generation_kind = ""
    state.generation_owner = ""
    state.generation_interrupts = {}
    inbox = QqInbox(state, coalesce_sec=0.05)
    await inbox.push("留下", message_id="keep")
    await inbox.push("撤回我", message_id="drop")
    await inbox.recall("drop")
    await asyncio.sleep(0.2)
    if orch.texts != ["留下"]:
        _fail(f"buffered recall got {orch.texts}")

    gate = _GateChat()
    state.orchestrator = gate
    inbox2 = QqInbox(state, coalesce_sec=0.05)
    await inbox2.push("进行中", message_id="a")
    await inbox2.push("也留下", message_id="b")
    await _wait_gates(gate, 1)
    await inbox2.recall("a")
    await _wait_gates(gate, 2)
    for event in gate.gates:
        event.set()
    await asyncio.sleep(0.2)
    if not gate.texts or gate.texts[-1] != "也留下":
        _fail(f"final turn after recall should be remaining only, got {gate.texts}")
    print("inbox recall ok")


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
    test_clause_gap()
    test_inbound()
    test_prompt_method()
    test_emoji_catalog()
    test_qq_images()
    test_friend_recall_parse()
    test_dialogue_recall()
    test_outbound_qq_fallback()
    test_config()
    asyncio.run(test_link_send())
    asyncio.run(test_emoji_send())
    asyncio.run(test_get_file_roundtrip())
    asyncio.run(test_offline_impulse())
    asyncio.run(test_coalesce())
    asyncio.run(test_inbox_recall())
    asyncio.run(test_barge_in_merges())
    asyncio.run(test_after_ready_holds())
    asyncio.run(test_barge_in_after_seal_keeps_reply())
    print("napcat unit ok")


if __name__ == "__main__":
    main()
