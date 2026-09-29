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

"""QQ private chat through a Napcat reverse WebSocket."""

from .endpoint import napcat_endpoint
from .inbox import COALESCE_SEC, QqInbox
from .link import CLAUSE_GAP_SEC, NapcatLink
from .protocol import build_send_private, private_text_from_event
from .split import split_qq_clauses

__all__ = [
    "CLAUSE_GAP_SEC",
    "COALESCE_SEC",
    "NapcatLink",
    "QqInbox",
    "build_send_private",
    "napcat_endpoint",
    "private_text_from_event",
    "split_qq_clauses",
]
