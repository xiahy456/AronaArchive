#!/usr/bin/env python3
"""Unit smoke for listen turn-taking: speaker filter, buffer, silence EOT."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config
from app.turntaking.buffer import TurnBuffer
from app.turntaking.rules import looks_incomplete
from app.turntaking.speaker import (
    SPEAKER_OTHER,
    SPEAKER_TEACHER,
    is_teacher_speaker,
    normalize_speaker,
)


def main() -> None:
    assert normalize_speaker(None) == SPEAKER_TEACHER
    assert normalize_speaker("OTHER") == SPEAKER_OTHER
    assert is_teacher_speaker("teacher")
    assert not is_teacher_speaker("other")
    assert not is_teacher_speaker("unknown")

    buf = TurnBuffer()
    buf.set_listening(True)
    assert buf.push(text="旁人", speaker="other") is None
    assert buf.joined() == ""
    assert buf.push(text="阿洛娜你好", speaker="teacher", segment_id="1") is not None
    assert buf.joined() == "阿洛娜你好"
    buf.prepend("之前那句")
    assert buf.drain().startswith("之前那句")
    assert buf.joined() == ""

    # listen off must keep uncommitted text so the handler can force-commit
    buf.set_listening(True)
    assert buf.push(text="关麦前这句", speaker="teacher", segment_id="2") is not None
    buf.set_listening(False)
    assert buf.listening is False
    assert buf.joined() == "关麦前这句"
    assert buf.drain() == "关麦前这句"
    assert buf.joined() == ""
    assert buf.pop_image() is None

    # next listen session starts clean
    buf.set_listening(True)
    assert buf.push(text="上一轮残留", speaker="teacher") is not None
    buf.set_listening(False)
    buf.set_listening(True)
    assert buf.joined() == ""
    assert buf.listening is True

    # handler sequence: drain (force commit) then set_listening(False)
    buf.push(text="已final未满静音", speaker="teacher", segment_id="3")
    flushed = buf.drain()
    buf.set_listening(False)
    assert flushed == "已final未满静音"
    assert buf.joined() == ""
    assert buf.listening is False

    from app.image_input import ImagePayload

    jpeg = b"\xff\xd8\xff" + b"\x00" * 32
    img1 = ImagePayload(mime="image/jpeg", data=jpeg + b"1")
    img2 = ImagePayload(mime="image/jpeg", data=jpeg + b"2")
    buf.set_listening(True)
    assert buf.push(text="第一句", speaker="teacher", image=img1) is not None
    assert buf.push(text="第二句", speaker="teacher", image=img2) is not None
    assert buf.pop_image() is img2
    assert buf.drain() == "第一句第二句"
    assert buf.pop_image() is None

    buf.set_listening(True)
    assert buf.push(text="残留图", speaker="teacher", image=img1) is not None
    buf.set_listening(True)
    assert buf.joined() == ""
    assert buf.pop_image() is None

    assert looks_incomplete("那个然后")
    assert looks_incomplete("就是")
    assert not looks_incomplete("晚饭都还没吃啊。")

    from app.proactive.hub import ConnectionHub

    async def _noop(_payload: dict) -> None:
        return None

    hub = ConnectionHub()
    hub.register("s1", _noop)
    assert len(hub.idle_sessions()) == 1
    hub.set_listening("s1", True)
    assert len(hub.idle_sessions()) == 1
    hub.set_listening("s1", False)
    assert len(hub.idle_sessions()) == 1
    hub.set_busy("s1", True)
    assert hub.idle_sessions() == []
    hub.set_busy("s1", False)
    assert len(hub.idle_sessions()) == 1

    cfg = load_config()
    assert cfg.listen.silence_commit_ms >= 500
    assert cfg.listen.incomplete_commit_ms >= cfg.listen.silence_commit_ms

    print("OK: turntaking unit cases passed")


if __name__ == "__main__":
    main()
