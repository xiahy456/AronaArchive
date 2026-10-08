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

"""QQ private chat through a Napcat reverse WebSocket."""

from .endpoint import napcat_endpoint
from .inbox import COALESCE_SEC, QqInbox
from .link import EMOJI_GAP_SEC, NapcatLink, clause_gap_sec
from .protocol import (
    build_send_private,
    friend_recall_from_event,
    private_inbound_from_event,
    private_text_from_event,
)
from .split import split_qq_clauses

__all__ = [
    "COALESCE_SEC",
    "EMOJI_GAP_SEC",
    "NapcatLink",
    "QqInbox",
    "build_send_private",
    "clause_gap_sec",
    "friend_recall_from_event",
    "napcat_endpoint",
    "private_inbound_from_event",
    "private_text_from_event",
    "split_qq_clauses",
]
