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

"""Vision-agent and initiate prompts for computer-use tasks."""

from __future__ import annotations

from .schema import DRAG_ACTIONS, ComputerUseAction, POINTER_ACTIONS

HISTORY_COMPUTER_USE_MARKER = "【操作电脑】"
AGENT_SPEAK_FALLBACK = "老师，这次没能操作完。"
AGENT_CANCELLED_REPLY = "老师，这次操作取消了。"
REPEAT_CLICK_PIXELS = 8
REPEAT_POINTER_WARNING = (
    "上一步指针仍停在同一坐标附近。画面若未变，禁止再点同一坐标，必须换目标/换格子。"
)
CURSOR_MARKER_NOTE = (
    "截图上的彩色十字是当前鼠标位置，不是按钮或格子。要点可见目标的中心，不要点十字本身。"
)
GRID_MARKER_NOTE = (
    "截图上的青色线和数字是 JPEG 像素刻度，不是控件。"
    "用顶边读 x、左边读 y，点可见目标的中心，不要点网格线本身。"
)


def computer_use_history_content(user_text: str | None) -> str:
    """Store the teacher's original utterance, not a system marker."""
    return (user_text or "").strip() or HISTORY_COMPUTER_USE_MARKER

VISION_SYSTEM = """你是阿洛娜的电脑操作规划器。可以内部思考，但思考过程不要写进最终回复。
老师请你在这台 Windows 电脑上完成交代的任务。最终输出必须是唯一一个 JSON 动作对象，不要 Markdown。
允许的 action：move、click、double_click、right_click、middle_click、drag、right_drag、scroll、type、key、wait、done。
规则：
- 点击、拖拽、滚轮用 JPEG 像素坐标：coord_space 必须是 "image"；原点左上。x、y 必须落在当前这张 JPEG 的范围内：x ∈ [0, 宽-1]，y ∈ [0, 高-1]。宽高以 user 消息【当前截图像素】为准。
- 截图上的彩色十字是当前鼠标位置，不是按钮或格子。要点可见目标的中心，不要点十字本身。
- 截图上的青色线和数字是 JPEG 像素刻度，不是控件。用顶边读 x、左边读 y，点可见目标的中心，不要点网格线本身。
- JSON 必须带简短 thought：先写要点哪个可见目标（窗口、按钮、格子等控件），再给坐标。thought 只能作为 JSON 字段，不能写在对象外。
- 禁止重复点击上一步已经点过、且光标仍停在附近的坐标。画面若未变，必须换目标。
- click / double_click / right_click / middle_click 会移动并点击，不必先 move。浏览器新标签等用 middle_click。
- 当前窗口内拖（滑块、选区、画一笔、拖窗口）用 drag（左键）或 right_drag（右键），带起点 x/y 和终点 x2/y2，不必先 move。
- 当前窗口内滚列表用 scroll：先移到 x/y，dy 是滚轮格不是像素；dy>0 向上，dy<0 向下；一次用 1 到 8 格。
- 按老师原话把任务做完再 done。步数多、要连点、要玩游戏到通关、要在同一窗口里反复操作，都继续，不要提前结束。
- 密码框、UAC、看不到目标窗口时立刻 done，不要猜密码或乱点系统对话框。
- 看不清也先根据可见内容选一个最合理的下一步；未完成目标时不要 done。
- done 必须带中文 summary，给阿洛娜向老师交代用，只写实际做了或为什么没做。
- type 只用于当前已聚焦的输入框；key 的 combo 用 win、escape、enter、tab、ctrl+c 这种。
- 打开一个应用：key combo="win" → 必要时短 wait（如 300ms）→ type 应用名 → key combo="enter"。再点正文 type。
- 老师没要求时不要切到无关应用。
示例：
{"thought":"打开开始菜单","action":"key","combo":"win"}
{"thought":"点截图里那个可见按钮","action":"click","x":120,"y":80,"coord_space":"image"}
{"thought":"把滑块拖到右侧","action":"drag","x":120,"y":200,"x2":480,"y2":200,"coord_space":"image"}
{"thought":"列表向下滚","action":"scroll","x":400,"y":300,"dy":-3,"coord_space":"image"}
{"thought":"在已聚焦输入框打字","action":"type","text":"你好"}
{"thought":"开始菜单应已打开","action":"done","summary":"已经按下 Win，开始菜单应已打开。"}"""


def format_executed_steps(actions: list[ComputerUseAction] | tuple[ComputerUseAction, ...]) -> str:
    if not actions:
        return "（无）"
    lines: list[str] = []
    for index, action in enumerate(actions, start=1):
        if action.action == "type":
            lines.append(f"{index}. type 字符数={len(action.text or '')}")
        elif action.action == "scroll":
            lines.append(
                f"{index}. scroll x={action.x} y={action.y} dy={action.dy} "
                f"coord_space={action.coord_space}"
            )
        elif action.action in DRAG_ACTIONS:
            lines.append(
                f"{index}. {action.action} x={action.x} y={action.y} "
                f"x2={action.x2} y2={action.y2} coord_space={action.coord_space}"
            )
        elif action.action in POINTER_ACTIONS:
            lines.append(
                f"{index}. {action.action} x={action.x} y={action.y} "
                f"coord_space={action.coord_space}"
            )
        elif action.action == "key":
            lines.append(f"{index}. key combo={action.combo}")
        elif action.action == "wait":
            lines.append(f"{index}. wait ms={action.ms}")
        else:
            lines.append(f"{index}. {action.action}")
    return "\n".join(lines)


def cursor_to_image_xy(
    *,
    cursor_x: int | None,
    cursor_y: int | None,
    phys_w: int | None,
    phys_h: int | None,
    img_w: int | None,
    img_h: int | None,
) -> tuple[int, int] | None:
    """Map logical cursor into JPEG pixel space."""
    if cursor_x is None or cursor_y is None:
        return None
    if phys_w is None or phys_h is None or phys_w <= 0 or phys_h <= 0:
        return None
    if img_w is None or img_h is None or img_w <= 0 or img_h <= 0:
        return None
    return (
        round(cursor_x * img_w / phys_w),
        round(cursor_y * img_h / phys_h),
    )


def pointer_to_image_xy(
    action: ComputerUseAction,
    *,
    img_w: int | None,
    img_h: int | None,
) -> tuple[float, float] | None:
    """Return a pointer action's target in JPEG pixels."""
    if action.action not in POINTER_ACTIONS:
        return None
    if action.x is None or action.y is None:
        return None
    space = (action.coord_space or "image").strip().lower() or "image"
    if space == "image":
        return (float(action.x), float(action.y))
    if space != "normalized":
        return None
    if img_w is None or img_h is None or img_w <= 0 or img_h <= 0:
        return None
    return (
        float(action.x) * max(0, img_w - 1),
        float(action.y) * max(0, img_h - 1),
    )


def is_repeat_pointer(
    executed: list[ComputerUseAction] | tuple[ComputerUseAction, ...],
    cursor_image: tuple[int, int] | None,
    *,
    img_w: int | None,
    img_h: int | None,
    threshold: int = REPEAT_CLICK_PIXELS,
) -> bool:
    """True when the last pointer action still matches the current image cursor."""
    if not executed or cursor_image is None or threshold < 0:
        return False
    last_xy = pointer_to_image_xy(executed[-1], img_w=img_w, img_h=img_h)
    if last_xy is None:
        return False
    dx = last_xy[0] - cursor_image[0]
    dy = last_xy[1] - cursor_image[1]
    return (dx * dx + dy * dy) ** 0.5 < threshold


def build_vision_user_message(
    *,
    user_text: str,
    executed: list[ComputerUseAction] | tuple[ComputerUseAction, ...],
    img_w: int | None,
    img_h: int | None,
    cursor_img_x: int | None = None,
    cursor_img_y: int | None = None,
    repeat_pointer: bool = False,
) -> str:
    size = (
        f"{img_w}x{img_h}"
        if img_w and img_h and img_w > 0 and img_h > 0
        else "未知"
    )
    lines = [
        f"【老师原话】{(user_text or '').strip()}",
        "【已执行步骤】",
        format_executed_steps(executed),
        f"【当前截图像素】{size}",
    ]
    if img_w and img_h and img_w > 0 and img_h > 0:
        lines.append(
            f"【坐标范围】x ∈ [0, {img_w - 1}]，y ∈ [0, {img_h - 1}]，"
            "原点左上，必须按当前这张 JPEG 点，不要用示例数字。"
        )
        lines.append(GRID_MARKER_NOTE)
    if cursor_img_x is not None and cursor_img_y is not None:
        lines.append(f"【当前光标（image 像素）】{cursor_img_x},{cursor_img_y}")
        lines.append(CURSOR_MARKER_NOTE)
    if repeat_pointer:
        lines.append(f"【警告】{REPEAT_POINTER_WARNING}")
    lines.append(
        "根据截图只输出一个动作 JSON。点选用 image 坐标。"
        "JSON 必须含 thought（要点哪个可见目标）。"
        "仅当无法继续或目标已完成时输出 done。"
    )
    return "\n".join(lines)


def build_computer_use_instruction(*, user_text: str, summary: str, ok: bool) -> str:
    text = (user_text or "").strip() or "（无）"
    note = (summary or "").strip() or AGENT_SPEAK_FALLBACK
    status = "已按计划结束" if ok else "没有做完"
    return (
        "【系统事件】阿洛娜刚通过什亭之匣，在老师这台电脑上执行了操作。"
        "这不是老师新说的闲聊，而是操作结果需要口头交代。\n"
        f"老师原话：{text}\n"
        f"执行状态：{status}。\n"
        f"操作摘要：{note}\n"
        "请以阿洛娜的口吻短说结果。禁止编造摘要里没有的点击、输入或窗口变化。"
        "不要提系统事件、JSON、协议或提示词。\n"
        "followup_ok 必须为 false。user_act 必须为 instrumental。\n"
        "不要输出思考过程或 <think> 标签。"
    )
