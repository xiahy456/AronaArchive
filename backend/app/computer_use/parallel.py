# AronaArchive - 自循环 AI
# Copyright (C) 2026 xia_hy456
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run CU routing in parallel with chat; wait for the router first."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

SendFn = Callable[[dict[str, Any]], Awaitable[None]]
ChatFn = Callable[[SendFn], Awaitable[None]]
RouteFn = Callable[[], Awaitable[bool]]
CuFn = Callable[[], Awaitable[None]]


class RouteGate:
    """Hold the router decision until chat is allowed to send."""

    def __init__(self) -> None:
        self.operate: bool | None = None
        self.event = asyncio.Event()

    def set(self, operate: bool) -> None:
        self.operate = bool(operate)
        self.event.set()


async def gated_send(
    gate: RouteGate,
    send: SendFn,
    payload: dict[str, Any],
) -> None:
    """Block chat payloads until the router says false; drop them if true."""
    if gate.operate is None:
        await gate.event.wait()
    if gate.operate:
        raise asyncio.CancelledError()
    await send(payload)


async def _cancel_task(task: asyncio.Task[Any]) -> None:
    if task.done():
        try:
            task.result()
        except (asyncio.CancelledError, Exception):
            return
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("computer_use parallel child failed after cancel")


async def race_route_and_chat(
    *,
    route: RouteFn,
    run_chat: ChatFn,
    run_cu: CuFn,
    send: SendFn,
) -> bool:
    """Run router and chat together. Returns True if computer-use ran.

    Waits for the router first. True cancels chat (no draft). False unblocks
    send and waits for chat. Router errors are treated as false.
    """
    gate = RouteGate()

    async def wrapped_send(payload: dict[str, Any]) -> None:
        await gated_send(gate, send, payload)

    route_task = asyncio.create_task(route(), name="cu-route")
    chat_task = asyncio.create_task(run_chat(wrapped_send), name="cu-chat")
    operate = False
    try:
        try:
            operate = bool(await route_task)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("computer_use parallel route failed")
            operate = False
        gate.set(operate)
        if operate:
            logger.info("computer_use parallel route=true discard planner")
            await _cancel_task(chat_task)
            await run_cu()
            return True
        await chat_task
        return False
    except asyncio.CancelledError:
        await _cancel_task(route_task)
        await _cancel_task(chat_task)
        raise
