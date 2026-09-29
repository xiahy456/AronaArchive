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

"""Vision-driven computer-use agent: one whitelist action per step."""

from __future__ import annotations

import logging
import uuid

from .client import VisionClient
from .loop import (
    AbortCheck,
    ProbeResult,
    SendFn,
    WaitObservation,
    _fail_result,
    run_action_loop,
)
from .schema import ComputerUseAction, ComputerUseObservation

logger = logging.getLogger(__name__)

_NO_FRAME_SUMMARY = "没有收到屏幕画面，先不操作了。"
_BOOTSTRAP_STEP = 0


async def run_vision_agent(
    *,
    send: SendFn,
    wait_observation: WaitObservation,
    client: VisionClient,
    user_text: str,
    abort_check: AbortCheck | None = None,
    max_steps: int = 8,
    run_id: str | None = None,
) -> ProbeResult:
    rid = (run_id or "").strip() or str(uuid.uuid4())
    if abort_check is not None and abort_check():
        return _fail_result(run_id=rid, completed=0, reason="cancelled")

    bootstrap = ComputerUseAction(action="wait", ms=0, run_id=rid, step=_BOOTSTRAP_STEP)
    logger.info(
        "computer_use bootstrap wait0 run_id=%s step=%s",
        rid,
        _BOOTSTRAP_STEP,
    )
    await send(bootstrap.to_message())
    seed = await wait_observation(rid, _BOOTSTRAP_STEP)
    if seed is None:
        logger.info("computer_use bootstrap timeout run_id=%s", rid)
        return _fail_result(run_id=rid, completed=0, reason="timeout")
    if seed.run_id != rid or seed.step != _BOOTSTRAP_STEP:
        return _fail_result(
            run_id=rid,
            completed=0,
            reason="observation_failed",
            summary="观察结果对不上，已停止。",
        )
    if not seed.ok:
        error = seed.error or "observation_failed"
        reason = "disabled" if error == "disabled" else "observation_failed"
        logger.info("computer_use bootstrap failed run_id=%s error=%s", rid, error)
        return _fail_result(run_id=rid, completed=0, reason=reason)

    async def next_action(
        step: int,
        last_obs: ComputerUseObservation | None,
        executed: list[ComputerUseAction],
    ) -> ComputerUseAction | None:
        del step
        if last_obs is None or last_obs.image is None:
            return ComputerUseAction(action="done", summary=_NO_FRAME_SUMMARY)
        return await client.plan(
            user_text=user_text,
            executed=executed,
            observation=last_obs,
        )

    return await run_action_loop(
        send=send,
        wait_observation=wait_observation,
        next_action=next_action,
        abort_check=abort_check,
        max_steps=max_steps,
        run_id=rid,
        initial_observation=seed,
    )
