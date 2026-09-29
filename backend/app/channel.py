# Copyright 2026 xia_hy456. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
    if proactive:
        return METHOD_DIRECT if client_online else METHOD_MESSAGE
    if normalize_method(inbound) == METHOD_MESSAGE:
        return METHOD_MESSAGE
    return METHOD_DIRECT


def resolve_outbound_method(
    raw: object | None,
    *,
    inbound: str = "",
    proactive: bool = False,
    client_online: bool = False,
) -> str:
    chosen = normalize_method(raw)
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
