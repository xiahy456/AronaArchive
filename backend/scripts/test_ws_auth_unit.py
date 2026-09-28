#!/usr/bin/env python3
"""Access token: public bind refuses to start; handshake rejects a bad bearer."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, WebSocket  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ws_auth import (  # noqa: E402
    reject_unauthorized,
    startup_token_error,
)

TOKEN = "test-token-value"


def _fail(msg: str) -> None:
    print("FAIL", msg)
    raise SystemExit(1)


def _check_startup() -> None:
    if startup_token_error("127.0.0.1", False, "") is not None:
        _fail("loopback without token should start")
    if startup_token_error("localhost", False, "") is not None:
        _fail("localhost without token should start")
    if startup_token_error("::1", False, "") is not None:
        _fail("ipv6 loopback without token should start")
    if startup_token_error("127.0.0.1", True, "") is None:
        _fail("public loopback without token must refuse")
    if startup_token_error("127.0.0.1", True, "YOUR_ACCESS_TOKEN") is None:
        _fail("placeholder token must refuse when public")
    if startup_token_error("0.0.0.0", False, "") is None:
        _fail("non-loopback without token must refuse")
    if startup_token_error("0.0.0.0", False, TOKEN) is not None:
        _fail("non-loopback with token should start")
    if startup_token_error("127.0.0.1", True, TOKEN) is not None:
        _fail("public loopback with token should start")


def _app(token: str) -> FastAPI:
    app = FastAPI()

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        if await reject_unauthorized(websocket, token):
            return
        await websocket.accept()
        await websocket.send_json({"type": "connected"})

    return app


def _expect_connected(token: str, headers: dict[str, str] | None) -> None:
    client = TestClient(_app(token))
    kwargs = {} if headers is None else {"headers": headers}
    with client.websocket_connect("/ws", **kwargs) as ws:
        hello = ws.receive_json()
    if hello.get("type") != "connected":
        _fail(f"expected connected, got {hello!r}")


def _expect_rejected(token: str, headers: dict[str, str] | None) -> None:
    client = TestClient(_app(token))
    kwargs = {} if headers is None else {"headers": headers}
    try:
        with client.websocket_connect("/ws", **kwargs) as ws:
            ws.receive_json()
    except Exception:
        return
    _fail("handshake should have failed")


def main() -> None:
    _check_startup()
    _expect_connected("", None)
    _expect_connected(TOKEN, {"Authorization": f"Bearer {TOKEN}"})
    _expect_connected(TOKEN, {"Authorization": f"bearer {TOKEN}"})
    _expect_rejected(TOKEN, None)
    _expect_rejected(TOKEN, {"Authorization": "Bearer wrong-token"})
    _expect_rejected(TOKEN, {"Authorization": "Basic abc"})
    print("OK: ws auth cases passed")


if __name__ == "__main__":
    main()
