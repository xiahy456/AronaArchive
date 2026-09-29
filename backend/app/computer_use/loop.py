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

"""Request–observe loop for probe scripts and the vision agent."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..protocol import msg_chat_response, msg_computer_use_done
from .probe import (
    PROBE_CANCELLED_REPLY,
    PROBE_DONE_REPLY,
    PROBE_FAILED_REPLY,
    probe_actions,
)
from .prompts import format_executed_steps
from .schema import ComputerUseAction, ComputerUseObservation, SchemaError

logger = logging.getLogger(__name__)

SendFn = Callable[[dict[str, Any]], Awaitable[None]]
WaitObservation = Callable[[str, int], Awaitable[ComputerUseObservation | None]]
AbortCheck = Callable[[], bool]
NextActionFn = Callable[
    [int, ComputerUseObservation | None, list[ComputerUseAction]],
    Awaitable[ComputerUseAction | None],
]

_REASON_SUMMARIES = {
    "timeout": "客户端没有及时返回屏幕观察。",
    "cancelled": "老师取消了这次操作。",
    "max_steps": "步数用完了，还没做完。",
    "invalid_action": "模型给出了不能执行的动作，已停止。",
    "disabled": "客户端没有开启电脑操作权限。",
    "observation_failed": "这一步操作失败了。",
    "observation_mismatch": "观察结果对不上，已停止。",
}


@dataclass
class ProbeResult:
    ok: bool
    summary: str
    run_id: str
    steps_completed: int
    reason: str


def _log_action(run_id: str, step: int, action: ComputerUseAction) -> None:
    if action.action == "type":
        logger.info(
            "computer_use action run_id=%s step=%s action=type chars=%s",
            run_id,
            step,
            len(action.text or ""),
        )
        return
    logger.info(
        "computer_use action run_id=%s step=%s action=%s",
        run_id,
        step,
        action.action,
    )


def _fail_result(
    *,
    run_id: str,
    completed: int,
    reason: str,
    summary: str | None = None,
) -> ProbeResult:
    return ProbeResult(
        ok=False,
        summary=summary or _REASON_SUMMARIES.get(reason, reason),
        run_id=run_id,
        steps_completed=completed,
        reason=reason,
    )


def _has_real_work(executed: list[ComputerUseAction]) -> bool:
    return any(action.action != "wait" for action in executed)


def _recover_done(run_id: str, executed: list[ComputerUseAction]) -> ProbeResult:
    summary = (
        f"已执行：{format_executed_steps(executed)}。"
        "最后一步没有规范结束动作，按当前屏幕结束。"
    )
    return ProbeResult(
        ok=True,
        summary=summary,
        run_id=run_id,
        steps_completed=len(executed),
        reason="complete",
    )


def _missing_final_action(
    *,
    run_id: str,
    executed: list[ComputerUseAction],
    step: int,
    error: object | None = None,
) -> ProbeResult:
    if _has_real_work(executed):
        logger.info(
            "computer_use recover_done run_id=%s step=%s executed=%s error=%s",
            run_id,
            step,
            len(executed),
            error,
        )
        return _recover_done(run_id, executed)
    logger.info(
        "computer_use invalid_action run_id=%s step=%s error=%s",
        run_id,
        step,
        error,
    )
    return _fail_result(run_id=run_id, completed=len(executed), reason="invalid_action")


async def run_action_loop(
    *,
    send: SendFn,
    wait_observation: WaitObservation,
    next_action: NextActionFn,
    abort_check: AbortCheck | None = None,
    max_steps: int = 8,
    run_id: str | None = None,
    initial_observation: ComputerUseObservation | None = None,
) -> ProbeResult:
    """Drive one computer-use run. `done` is local and is not sent to the client."""
    rid = (run_id or "").strip() or str(uuid.uuid4())
    if max_steps < 1:
        return _fail_result(run_id=rid, completed=0, reason="max_steps")

    last_obs: ComputerUseObservation | None = initial_observation
    executed: list[ComputerUseAction] = []
    for index in range(1, max_steps + 1):
        if abort_check is not None and abort_check():
            return _fail_result(run_id=rid, completed=len(executed), reason="cancelled")
        try:
            action = await next_action(index, last_obs, executed)
        except SchemaError as exc:
            return _missing_final_action(
                run_id=rid,
                executed=executed,
                step=index,
                error=exc,
            )
        if action is None:
            return _missing_final_action(
                run_id=rid,
                executed=executed,
                step=index,
            )
        if action.action == "done":
            summary = (action.summary or "").strip() or "操作结束。"
            return ProbeResult(
                ok=True,
                summary=summary,
                run_id=rid,
                steps_completed=len(executed),
                reason="complete",
            )

        action.run_id = rid
        action.step = index
        _log_action(rid, index, action)
        await send(action.to_message())
        observation = await wait_observation(rid, index)
        if observation is None:
            logger.info("computer_use timeout run_id=%s step=%s", rid, index)
            return _fail_result(run_id=rid, completed=len(executed), reason="timeout")
        if observation.run_id != rid or observation.step != index:
            logger.info(
                "computer_use observation mismatch run_id=%s step=%s got=%s/%s",
                rid,
                index,
                observation.run_id,
                observation.step,
            )
            return _fail_result(
                run_id=rid,
                completed=len(executed),
                reason="observation_failed",
                summary=_REASON_SUMMARIES["observation_mismatch"],
            )
        if not observation.ok:
            error = observation.error or "observation_failed"
            reason = "disabled" if error == "disabled" else "observation_failed"
            logger.info(
                "computer_use observation failed run_id=%s step=%s error=%s",
                rid,
                index,
                error,
            )
            return _fail_result(
                run_id=rid,
                completed=len(executed),
                reason=reason,
            )
        executed.append(action)
        last_obs = observation
        if observation.screen is not None:
            logger.info(
                "computer_use observation ok run_id=%s step=%s "
                "origin=%s,%s phys=%sx%s img=%sx%s dpi=%s cursor=%s,%s",
                rid,
                index,
                observation.screen.origin_x,
                observation.screen.origin_y,
                observation.screen.phys_w,
                observation.screen.phys_h,
                observation.screen.img_w,
                observation.screen.img_h,
                observation.screen.dpi_scale,
                observation.screen.cursor_x,
                observation.screen.cursor_y,
            )
    return _fail_result(run_id=rid, completed=len(executed), reason="max_steps")


async def run_probe(
    *,
    send: SendFn,
    wait_observation: WaitObservation,
    abort_check: AbortCheck | None = None,
    actions: list[ComputerUseAction] | None = None,
    max_steps: int = 8,
    run_id: str | None = None,
) -> ProbeResult:
    """Drive the hardcoded probe. Caller sends computer_use_done + chat_response."""
    steps = list(actions if actions is not None else probe_actions())

    async def next_action(
        step: int,
        last_obs: ComputerUseObservation | None,
        executed: list[ComputerUseAction],
    ) -> ComputerUseAction | None:
        del last_obs, executed
        index = step - 1
        if index >= len(steps):
            return ComputerUseAction(action="done", summary="probe complete")
        return steps[index]

    loop_max = max_steps
    if len(steps) > 0 and max_steps >= len(steps):
        loop_max = len(steps) + 1
    return await run_action_loop(
        send=send,
        wait_observation=wait_observation,
        next_action=next_action,
        abort_check=abort_check,
        max_steps=loop_max,
        run_id=run_id,
    )


def probe_reply_text(result: ProbeResult) -> str:
    if result.ok:
        return PROBE_DONE_REPLY
    if result.reason == "cancelled":
        return PROBE_CANCELLED_REPLY
    return PROBE_FAILED_REPLY


def terminal_messages(result: ProbeResult) -> list[dict[str, Any]]:
    return [
        msg_computer_use_done(result.run_id, ok=result.ok, summary=result.summary),
        msg_chat_response(
            probe_reply_text(result),
            context_used="computer_use",
        ),
    ]
