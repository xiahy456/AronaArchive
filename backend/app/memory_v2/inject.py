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

"""Prompt blocks. State lines are not clipped; events keep every sentence."""

from __future__ import annotations

from app.safety import is_crisis_text

from .events import Event


def format_resident_block(lines: list[str]) -> str:
    kept = [line.strip() for line in lines if line and line.strip() and not is_crisis_text(line)]
    if not kept:
        return ""
    body = "\n".join(f"- {line}" for line in kept)
    return f"【老师当前情况】\n{body}"


def format_event_block(events: list[Event]) -> str:
    lines: list[str] = []
    for event in events:
        summary = (event.summary or "").strip()
        if not summary or is_crisis_text(summary):
            continue
        lines.append(f"- {summary}")
    if not lines:
        return ""
    return "【相关回忆】\n" + "\n".join(lines)


def format_commitment_block(lines: list[str]) -> str:
    kept = [line.strip() for line in lines if line and line.strip() and not is_crisis_text(line)]
    if not kept:
        return ""
    body = "\n".join(f"- {line}" for line in kept)
    return f"【阿洛娜记着的事】\n{body}"
