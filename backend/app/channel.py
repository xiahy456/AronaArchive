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

"""How a line travels: face to face on the client, or a QQ private message."""

from __future__ import annotations

METHOD_DIRECT = "direct"
METHOD_MESSAGE = "message"
QQ_SESSION_ID = "qq"
_METHODS = frozenset({METHOD_DIRECT, METHOD_MESSAGE})


def normalize_method(value: object | None) -> str:
    """Return direct or message. Anything else, including blank, is empty."""
    text = str(value or "").strip().lower()
    if text in _METHODS:
        return text
    return ""


def method_label(value: object | None) -> str:
    """Prompt label. Missing and unknown values are face-to-face."""
    if normalize_method(value) == METHOD_MESSAGE:
        return "QQ消息"
    return "面对面交流"


def default_outbound_method(
    *,
    inbound: str = "",
    proactive: bool = False,
    client_online: bool = False,
) -> str:
    """Used only when the model omits method or writes something illegal."""
    # QQ-originated turns (including continue) stay on QQ unless the model chooses.
    if normalize_method(inbound) == METHOD_MESSAGE:
        return METHOD_MESSAGE
    if proactive:
        return METHOD_DIRECT if client_online else METHOD_MESSAGE
    return METHOD_DIRECT


def resolve_outbound_method(
    raw: object | None,
    *,
    inbound: str = "",
    proactive: bool = False,
    client_online: bool = False,
) -> str:
    chosen = normalize_method(raw)
    # Teacher came from QQ but model picked face-to-face while desktop is offline:
    # fall back to QQ so the line is not lost as undelivered.
    if (
        chosen == METHOD_DIRECT
        and normalize_method(inbound) == METHOD_MESSAGE
        and not client_online
    ):
        return METHOD_MESSAGE
    if chosen:
        return chosen
    return default_outbound_method(
        inbound=inbound,
        proactive=proactive,
        client_online=client_online,
    )


def format_channels(*, client_online: bool, qq_connected: bool) -> str:
    face = "在线" if client_online else "不在线"
    qq = "已连接" if qq_connected else "未连接"
    return f"【可送达通道】\n- 面对面：{face}\n- QQ：{qq}"


def hold_channel_for(method: str) -> str:
    """Impulse wait key when the chosen channel cannot take the line."""
    if normalize_method(method) == METHOD_MESSAGE:
        return "napcat"
    return "client"
