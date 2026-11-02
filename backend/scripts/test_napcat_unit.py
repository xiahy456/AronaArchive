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
from app.napcat import (  # noqa: E402
    NapcatLink,
    QqPipeline,
    SendOutcome,
    build_send_private,
    private_text_from_event,
    split_qq_clauses,
)
from app.napcat.link import EMOJI_GAP_SEC, clause_gap_sec  # noqa: E402
from app.orchestrator import ChatPlan  # noqa: E402
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
    lo, hi = 0.1 * n, 0.5 * n
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
    if not ok.completed or ok.interrupted or len(ws.frames) != 2:
        _fail(f"expected two frames, got {ws.frames} outcome={ok}")
    if ok.sent != ("欢迎回来老师！", "今天想做什么？") or ok.remainder:
        _fail(f"outcome {ok}")
    if ws.frames[0]["params"]["message"][0]["data"]["text"] != "欢迎回来老师！":
        _fail("first clause")
    if ws.frames[1]["params"]["message"][0]["data"]["text"] != "今天想做什么？":
        _fail("second clause")
    down = NapcatLink("42", gap_sec=0)
    missed = await down.send_text("在吗")
    if missed.completed or missed.sent or missed.remainder != "在吗":
        _fail(f"disconnected link must keep the clause, got {missed}")
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


class _FastLink:
    def __init__(self) -> None:
        self.connected = True
        self.texts: list[str] = []

    async def send_text(self, text: str, *, emoji: object | None = None, interrupt: object = None):
        del emoji, interrupt
        self.texts.append(text)
        return SendOutcome(tuple(split_qq_clauses(text)), "", True, False)


class _PlanOrch:
    def __init__(self) -> None:
        self.prepares: list[dict] = []
        self.commits: list[dict] = []
        self.hold: asyncio.Event | None = None
        self.reply = "在的"

    def note_teacher_spoke(self, _text: str = "") -> None:
        return None

    def _drop_teacher_journal(self) -> None:
        return None

    async def prepare_chat(self, **kwargs):
        self.prepares.append(kwargs)
        if self.hold is not None:
            gate = self.hold
            self.hold = None
            await gate.wait()
        text = self.reply if len(self.prepares) == 1 else f"{self.reply}{len(self.prepares)}"
        return ChatPlan(
            session_id="qq",
            user_text=str(kwargs.get("content") or ""),
            action="speak",
            text=text,
            method="message",
            emotion="normal",
            context_used="planner",
            inbound_method="message",
            latency=0.01,
        )

    async def commit_chat(self, plan, *, spoken: str, delivered: bool, qq_parts=None, **_kwargs):
        self.commits.append(
            {
                "action": plan.action,
                "user": plan.user_text,
                "spoken": spoken,
                "delivered": delivered,
                "parts": qq_parts,
            }
        )


def _qq_state(orch: _PlanOrch, link: object):
    state = _State(_Orch("sent", "message"), _Engine(_impulse()), _Hub(), link)  # type: ignore[arg-type]
    state.orchestrator = orch
    state.generation_kind = ""
    state.generation_owner = ""
    state.generation_interrupts = {}
    state.scheduler = None
    return state


async def _wait_for(pred, what: str, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        await asyncio.sleep(0.01)
    _fail(what)


async def test_send_interrupt_keeps_remainder() -> None:
    import app.napcat.link as linkmod

    original = linkmod.clause_gap_sec
    linkmod.clause_gap_sec = lambda _text: 0.2
    link = NapcatLink("42")
    ws = _Ws()
    await link.bind(ws)  # type: ignore[arg-type]
    interrupt = asyncio.Event()

    async def _stop() -> None:
        await _wait_for(lambda: len(ws.frames) >= 1, "first clause")
        interrupt.set()

    stopper = asyncio.create_task(_stop())
    try:
        outcome = await link.send_text("你好呀。我还在。", interrupt=interrupt)
        await stopper
    finally:
        linkmod.clause_gap_sec = original
    if not outcome.interrupted or outcome.completed:
        _fail(f"interrupt outcome {outcome}")
    if outcome.sent != ("你好呀",) or outcome.remainder != "我还在":
        _fail(f"split remainder {outcome}")
    if len(ws.frames) != 1:
        _fail(f"stopped send should keep one frame, got {ws.frames}")
    print("send interrupt ok")


async def test_quiet_batches_then_delivers() -> None:
    orch = _PlanOrch()
    link = _FastLink()
    pipe = QqPipeline(_qq_state(orch, link), generate_sec=0.06, deliver_sec=0.18)
    try:
        await pipe.push("第一句", message_id="1")
        await pipe.push("第二句", message_id="2")
        await asyncio.sleep(0.02)
        if orch.prepares:
            _fail(f"generate started too early {orch.prepares!r}")
        await _wait_for(lambda: len(orch.prepares) == 1, "prepare did not start")
        ctx = orch.prepares[0]["turn_context"]
        if orch.prepares[0]["content"] != "第一句\n第二句" or ctx.inputs != ("第一句", "第二句"):
            _fail(f"batched input {orch.prepares[0]!r}")
        if orch.commits or link.texts:
            _fail("delivered before the long quiet")
        await _wait_for(lambda: len(orch.commits) == 1, "commit did not happen")
    finally:
        await pipe.close()
    if link.texts != ["在的"]:
        _fail(f"sent {link.texts}")
    commit = orch.commits[0]
    if not commit["delivered"] or commit["spoken"] != "在的":
        _fail(f"commit {commit}")
    if commit["parts"] != [
        {"message_id": "1", "text": "第一句"},
        {"message_id": "2", "text": "第二句"},
    ]:
        _fail(f"parts {commit['parts']}")
    if len(orch.prepares) != 1 or len(orch.commits) != 1:
        _fail(f"one prepare and one commit, got {len(orch.prepares)} {len(orch.commits)}")
    print("quiet batch ok")


async def test_slow_draft_waits_for_text() -> None:
    orch = _PlanOrch()
    gate = asyncio.Event()
    orch.hold = gate
    link = _FastLink()
    pipe = QqPipeline(_qq_state(orch, link), generate_sec=0.04, deliver_sec=0.08)
    try:
        await pipe.push("在吗", message_id="1")
        await _wait_for(lambda: bool(orch.prepares), "prepare did not start")
        await asyncio.sleep(0.12)
        if link.texts or orch.commits:
            _fail("must not send before the draft exists")
        gate.set()
        await _wait_for(lambda: bool(orch.commits), "commit after slow draft")
    finally:
        await pipe.close()
    if not orch.commits[0]["delivered"]:
        _fail(f"slow draft {orch.commits}")
    print("slow draft ok")


async def test_message_during_generate_rewrites() -> None:
    orch = _PlanOrch()
    gate = asyncio.Event()
    orch.hold = gate
    link = _FastLink()
    pipe = QqPipeline(_qq_state(orch, link), generate_sec=0.05, deliver_sec=0.4)
    try:
        await pipe.push("第一句", message_id="1")
        await _wait_for(lambda: bool(orch.prepares), "first prepare")
        await pipe.push("第二句", message_id="2")
        gate.set()
        await _wait_for(lambda: len(orch.prepares) >= 2, "rewrite prepare")
        second = orch.prepares[1]
    finally:
        await pipe.close()
    if second["content"] != "第一句\n第二句":
        _fail(f"rewrite content {second['content']!r}")
    ctx = second["turn_context"]
    if ctx.carry != "在的" or ctx.sent:
        _fail(f"old draft should be the carry, got sent={ctx.sent!r} carry={ctx.carry!r}")
    print("generate rewrite ok")


async def test_message_during_send_keeps_unsent() -> None:
    import app.napcat.link as linkmod

    original = linkmod.clause_gap_sec
    linkmod.clause_gap_sec = lambda _text: 0.35
    orch = _PlanOrch()
    orch.reply = "你好呀。我还在。"
    link = NapcatLink("42")
    ws = _Ws()
    await link.bind(ws)  # type: ignore[arg-type]
    pipe = QqPipeline(_qq_state(orch, link), generate_sec=0.04, deliver_sec=0.07)
    try:
        await pipe.push("第一句", message_id="1")
        await _wait_for(lambda: len(ws.frames) >= 1, "first clause on the wire")
        await pipe.push("第二句", message_id="2")
        await _wait_for(lambda: len(orch.prepares) >= 2, "rewrite after interrupt")
        ctx = orch.prepares[1]["turn_context"]
    finally:
        linkmod.clause_gap_sec = original
        await pipe.close()
    if ctx.sent != "你好呀" or "我还在" not in ctx.carry:
        _fail(f"partial send context sent={ctx.sent!r} carry={ctx.carry!r}")
    if orch.prepares[1]["content"] != "第一句\n第二句":
        _fail(orch.prepares[1]["content"])
    first = ws.frames[0]["params"]["message"][0]["data"]["text"]
    if first != "你好呀":
        _fail(f"first frame {first!r}")
    print("send interrupt rewrite ok")


async def test_recall_regenerates_remaining() -> None:
    orch = _PlanOrch()
    link = _FastLink()
    pipe = QqPipeline(_qq_state(orch, link), generate_sec=0.05, deliver_sec=0.5)
    try:
        await pipe.push("留下", message_id="keep")
        await pipe.push("撤回我", message_id="drop")
        await pipe.recall("drop")
        await _wait_for(lambda: bool(orch.prepares), "prepare after buffered recall")
        if orch.prepares[0]["content"] != "留下":
            _fail(f"buffered recall content {orch.prepares[0]['content']!r}")
        await pipe.close()

        orch = _PlanOrch()
        link = _FastLink()
        pipe = QqPipeline(_qq_state(orch, link), generate_sec=0.05, deliver_sec=0.5)
        await pipe.push("进行中", message_id="a")
        await pipe.push("也留下", message_id="b")
        await _wait_for(lambda: len(orch.prepares) == 1, "covered draft")
        await pipe.recall("a")
        await _wait_for(lambda: len(orch.prepares) >= 2, "regen after covered recall")
        latest = orch.prepares[-1]
    finally:
        await pipe.close()
    if latest["content"] != "也留下":
        _fail(f"remaining content {latest['content']!r}")
    if latest["turn_context"].carry != "在的":
        _fail(f"recalled draft carry {latest['turn_context']!r}")
    print("recall regen ok")


def test_turn_context_prompt() -> None:
    from app.planner.prompts import TurnContext, build_planner_user_message

    msg = build_planner_user_message(
        user_text="第二句",
        history=[],
        memories=[],
        knowledge=[],
        teacher_method="message",
        turn_context=TurnContext(inputs=("第一句", "第二句"), sent="已经说了", carry="还没发出"),
    )
    if "【老师本轮消息】" not in msg or "[QQ消息] 第一句" not in msg or "[QQ消息] 第二句" not in msg:
        _fail(f"turn inputs missing\n{msg}")
    if "【本轮已发出去的回复】" not in msg or "已经说了" not in msg:
        _fail("sent block missing")
    if "【上一版尚未发出的回复草稿】" not in msg or "还没发出" not in msg:
        _fail("carry block missing")
    if "不得重复" not in msg:
        _fail("rewrite rule missing")
    print("turn context prompt ok")


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
    if not ok.completed or len(ws.frames) != 3:
        _fail(f"expected two texts then mface, got {ws.frames} outcome={ok}")
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
    blank = await alone.send_text("   ", emoji=sticker)
    if blank.completed or sink.frames:
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


def test_config() -> None:
    cfg = NapcatConfig(user_qq_id=10001, napcat_ws_path="arona", napcat_token=" tok ")
    if cfg.user_qq_id != "10001" or cfg.napcat_ws_path != "/arona" or cfg.napcat_token != "tok":
        _fail(f"napcat config normalize {cfg}")
    if cfg.idle_generate_sec != 4 or cfg.idle_deliver_sec != 16:
        _fail(f"quiet defaults {cfg.idle_generate_sec} {cfg.idle_deliver_sec}")
    try:
        NapcatConfig(idle_generate_sec=10, idle_deliver_sec=10)
    except Exception:
        pass
    else:
        _fail("deliver quiet must be longer than generate quiet")
    loaded = load_config()
    if loaded.napcat.napcat_ws_path != "/arona":
        _fail("example yaml should default the napcat path")
    if loaded.napcat.idle_deliver_sec <= loaded.napcat.idle_generate_sec:
        _fail("loaded napcat quiet window is inverted")
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
    asyncio.run(test_send_interrupt_keeps_remainder())
    asyncio.run(test_quiet_batches_then_delivers())
    asyncio.run(test_slow_draft_waits_for_text())
    asyncio.run(test_message_during_generate_rewrites())
    asyncio.run(test_message_during_send_keeps_unsent())
    asyncio.run(test_recall_regenerates_remaining())
    test_turn_context_prompt()
    print("napcat unit ok")


if __name__ == "__main__":
    main()
