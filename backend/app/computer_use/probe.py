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

"""Hardcoded phase-0 computer-use probe (move center, wait, Escape)."""

from __future__ import annotations

from .schema import ComputerUseAction

PROBE_TOKEN = "__cu_probe__"
PROBE_ALIAS = "键鼠探针"
PROBE_ALIASES = frozenset({PROBE_TOKEN, PROBE_ALIAS})

PROBE_DONE_REPLY = "键鼠探针跑完了。"
PROBE_DISABLED_REPLY = "键鼠探针未开启。"
PROBE_CANCELLED_REPLY = "键鼠探针已取消。"
PROBE_FAILED_REPLY = "键鼠探针没有跑完。"


def is_probe_text(text: str | None, token: str | None = None) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    aliases = set(PROBE_ALIASES)
    extra = (token or "").strip()
    if extra:
        aliases.add(extra)
    return stripped in aliases


def probe_actions() -> list[ComputerUseAction]:
    return [
        ComputerUseAction(
            action="move",
            x=0.5,
            y=0.5,
            coord_space="normalized",
        ),
        ComputerUseAction(action="wait", ms=400),
        ComputerUseAction(action="key", combo="escape"),
    ]
