"""Minimal WebSocket smoke test against local AronaArchive backend."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def run(url: str, message: str) -> int:
    try:
        import websockets
    except ImportError:
        print("Please install websockets: pip install websockets", file=sys.stderr)
        return 1

    async with websockets.connect(url) as ws:
        hello = json.loads(await ws.recv())
        print("<<", hello)
        if hello.get("type") != "connected":
            print("Expected connected", file=sys.stderr)
            return 1

        await ws.send(json.dumps({"type": "ping"}))
        print("<<", await ws.recv())

        payload = {
            "type": "chat",
            "content": message,
            "options": {"use_rag": False, "use_memory": True},
        }
        await ws.send(json.dumps(payload, ensure_ascii=False))
        print(">>", payload)

        raw = await ws.recv()
        data = json.loads(raw)
        print("<<", data)
        if data.get("type") != "chat_response":
            return 1

        await asyncio.sleep(2.5)
        interact = {
            "type": "interact",
            "action": "pat_head",
            "duration_ms": 2400,
        }
        await ws.send(json.dumps(interact, ensure_ascii=False))
        print(">>", interact)
        interact_resp = json.loads(await ws.recv())
        print("<<", interact_resp)
        if interact_resp.get("type") != "chat_response":
            return 1
        if "interact" not in str(interact_resp.get("context_used") or ""):
            print("Expected interact context_used", file=sys.stderr)
            return 1

        await ws.send(
            json.dumps(
                {
                    "type": "chat",
                    "content": "请记住：我喜欢草莓牛奶",
                    "options": {"use_rag": False, "use_memory": True},
                },
                ensure_ascii=False,
            )
        )
        mem_resp = json.loads(await ws.recv())
        print("<<", mem_resp)

        await asyncio.sleep(2.0)
        await ws.send(json.dumps({"type": "get_stats"}))
        print("<<", await ws.recv())

    print("smoke ok")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="AronaArchive WS smoke test")
    parser.add_argument("--url", default="ws://127.0.0.1:20456/ws")
    parser.add_argument("--message", default="老师好，阿洛娜~")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.url, args.message)))


if __name__ == "__main__":
    main()
