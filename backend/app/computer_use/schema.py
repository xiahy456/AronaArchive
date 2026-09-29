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

"""Computer-use action / observation schema (phase 0 probe)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

from ..image_input import ImagePayload, parse_optional_image
from ..protocol import msg_computer_use_action

ActionName = Literal[
    "move",
    "click",
    "double_click",
    "right_click",
    "middle_click",
    "drag",
    "right_drag",
    "scroll",
    "type",
    "key",
    "wait",
    "done",
]

COORD_SPACES = frozenset({"normalized", "image"})
ACTION_WHITELIST = frozenset(
    {
        "move",
        "click",
        "double_click",
        "right_click",
        "middle_click",
        "drag",
        "right_drag",
        "scroll",
        "type",
        "key",
        "wait",
        "done",
    }
)
POINTER_ACTIONS = frozenset(
    {
        "move",
        "click",
        "double_click",
        "right_click",
        "middle_click",
        "drag",
        "right_drag",
        "scroll",
    }
)
DRAG_ACTIONS = frozenset({"drag", "right_drag"})
SCROLL_DY_LIMIT = 8

logger = logging.getLogger(__name__)


class SchemaError(ValueError):
    """Invalid computer-use payload."""


def _as_str(value: object | None, default: str = "") -> str:
    if isinstance(value, str):
        return value.strip()
    return default


def _as_bool(value: object | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return default


def _as_int(value: object | None, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _as_float(value: object | None, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


@dataclass
class ComputerUseAction:
    action: str
    run_id: str = ""
    step: int = 0
    x: float | None = None
    y: float | None = None
    x2: float | None = None
    y2: float | None = None
    coord_space: str = "normalized"
    combo: str | None = None
    text: str | None = None
    ms: int | None = None
    dy: float | None = None
    summary: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "step": self.step,
            "action": self.action,
            "x": self.x,
            "y": self.y,
            "x2": self.x2,
            "y2": self.y2,
            "coord_space": self.coord_space,
            "combo": self.combo,
            "text": self.text,
            "ms": self.ms,
            "dy": self.dy,
            "summary": self.summary,
        }

    def to_message(self) -> dict[str, Any]:
        return msg_computer_use_action(self.to_payload())


@dataclass(frozen=True)
class ScreenGeometry:
    origin_x: int
    origin_y: int
    phys_w: int
    phys_h: int
    img_w: int
    img_h: int
    dpi_scale: float = 1.0
    cursor_x: int = 0
    cursor_y: int = 0


@dataclass
class ComputerUseObservation:
    run_id: str
    step: int
    ok: bool
    error: str = ""
    screen: ScreenGeometry | None = None
    image: ImagePayload | None = None


def parse_action(data: dict[str, Any] | None) -> ComputerUseAction:
    if not isinstance(data, dict):
        raise SchemaError("action must be an object")
    action = _as_str(data.get("action")).lower()
    if action not in ACTION_WHITELIST:
        raise SchemaError(f"unknown action: {action or data.get('action')!r}")
    coord_space = _as_str(data.get("coord_space"), "normalized").lower() or "normalized"
    if coord_space not in COORD_SPACES:
        raise SchemaError(f"unknown coord_space: {coord_space}")
    parsed = ComputerUseAction(
        action=action,
        run_id=_as_str(data.get("run_id")),
        step=_as_int(data.get("step"), 0) or 0,
        x=_as_float(data.get("x")),
        y=_as_float(data.get("y")),
        x2=_as_float(data.get("x2")),
        y2=_as_float(data.get("y2")),
        coord_space=coord_space,
        combo=_as_str(data.get("combo")) or None,
        text=_as_str(data.get("text")) or None,
        ms=_as_int(data.get("ms")),
        dy=_as_float(data.get("dy")),
        summary=_as_str(data.get("summary")) or None,
    )
    _validate_action(parsed)
    return parsed


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Return the last JSON object in text (final answer if thinking leaked in)."""
    raw = (text or "").strip()
    if not raw:
        return None
    decoder = json.JSONDecoder()
    last: dict[str, Any] | None = None
    idx = 0
    length = len(raw)
    while idx < length:
        start = raw.find("{", idx)
        if start < 0:
            break
        try:
            parsed, end = decoder.raw_decode(raw, start)
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(parsed, dict):
            last = parsed
        idx = end if end > start else start + 1
    return last


def parse_vision_action(raw: str | dict[str, Any] | None) -> ComputerUseAction:
    """Parse one vision-model action. Pointer defaults to image pixels."""
    if isinstance(raw, str):
        data = extract_json_object(raw)
    elif isinstance(raw, dict):
        data = dict(raw)
    else:
        data = None
    if not isinstance(data, dict):
        raise SchemaError("vision action must be a JSON object")
    data.pop("thought", None)
    action_name = _as_str(data.get("action")).lower()
    if action_name in POINTER_ACTIONS and not _as_str(data.get("coord_space")):
        data["coord_space"] = "image"
    parsed = parse_action(data)
    if parsed.action == "done" and not (parsed.summary or "").strip():
        raise SchemaError("done requires summary")
    return parsed


def _validate_action(action: ComputerUseAction) -> None:
    if action.action in POINTER_ACTIONS:
        if action.x is None or action.y is None:
            raise SchemaError(f"{action.action} requires x and y")
        if action.action in DRAG_ACTIONS and (action.x2 is None or action.y2 is None):
            raise SchemaError(f"{action.action} requires x2 and y2")
        if action.action == "scroll":
            if action.dy is None:
                raise SchemaError("scroll requires dy")
            notches = int(round(action.dy))
            if notches == 0:
                raise SchemaError("scroll requires non-zero dy")
            clamped = max(-SCROLL_DY_LIMIT, min(SCROLL_DY_LIMIT, notches))
            if clamped != notches:
                logger.info(
                    "computer_use scroll dy clamped from %s to %s",
                    notches,
                    clamped,
                )
            action.dy = float(clamped)
    elif action.action == "type":
        if not action.text:
            raise SchemaError("type requires text")
    elif action.action == "key":
        if not action.combo:
            raise SchemaError("key requires combo")
    elif action.action == "wait":
        if action.ms is None or action.ms < 0:
            raise SchemaError("wait requires non-negative ms")


def parse_screen(data: object | None) -> ScreenGeometry | None:
    if not isinstance(data, dict):
        return None
    origin_x = _as_int(data.get("origin_x"))
    origin_y = _as_int(data.get("origin_y"))
    phys_w = _as_int(data.get("phys_w"))
    phys_h = _as_int(data.get("phys_h"))
    img_w = _as_int(data.get("img_w"))
    img_h = _as_int(data.get("img_h"))
    if origin_x is None or origin_y is None:
        return None
    if phys_w is None or phys_h is None or phys_w <= 0 or phys_h <= 0:
        return None
    if img_w is None or img_h is None or img_w <= 0 or img_h <= 0:
        return None
    dpi = _as_float(data.get("dpi_scale"), 1.0)
    if dpi is None or dpi <= 0:
        dpi = 1.0
    return ScreenGeometry(
        origin_x=origin_x,
        origin_y=origin_y,
        phys_w=phys_w,
        phys_h=phys_h,
        img_w=img_w,
        img_h=img_h,
        dpi_scale=dpi,
        cursor_x=_as_int(data.get("cursor_x"), 0) or 0,
        cursor_y=_as_int(data.get("cursor_y"), 0) or 0,
    )


def parse_observation(data: dict[str, Any] | None) -> ComputerUseObservation:
    if not isinstance(data, dict):
        raise SchemaError("observation must be an object")
    run_id = _as_str(data.get("run_id"))
    if not run_id:
        raise SchemaError("observation requires run_id")
    step = _as_int(data.get("step"), 0) or 0
    ok = _as_bool(data.get("ok"), False)
    error = _as_str(data.get("error"))
    screen = parse_screen(data.get("screen"))
    image = parse_optional_image(data)
    if ok and screen is None:
        ok = False
        error = error or "invalid_screen"
    return ComputerUseObservation(
        run_id=run_id,
        step=step,
        ok=ok,
        error=error,
        screen=screen,
        image=image,
    )
