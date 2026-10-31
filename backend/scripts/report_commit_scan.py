#!/usr/bin/env python3
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

"""Histogram of commitment scan intervals from memory_v2-trace.jsonl.

Run from backend/:
  python scripts/report_commit_scan.py logs/memory_v2-trace.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def load_intervals(path: Path) -> list[int]:
    intervals: list[int] = []
    if not path.is_file():
        return intervals
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        row = json.loads(text)
        if row.get("kind") != "scan":
            continue
        if "next_after_sec" not in row:
            continue
        intervals.append(int(row["next_after_sec"]))
    return intervals


def render(intervals: list[int]) -> str:
    if not intervals:
        return "没有 kind=scan 的记录。"
    counts = Counter(intervals)
    width = max(counts.values())
    lines = [f"扫描 {len(intervals)} 次，平均间隔 {sum(intervals) / len(intervals):.0f} 秒", ""]
    for value, count in sorted(counts.items()):
        bar = "#" * max(1, int(32 * count / width))
        lines.append(f"{value:6d}s  {bar}  {count}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="统计承诺调度的 next_after_sec")
    parser.add_argument(
        "trace",
        nargs="?",
        default="logs/memory_v2-trace.jsonl",
        help="memory_v2-trace.jsonl 路径",
    )
    args = parser.parse_args(argv)
    print(render(load_intervals(Path(args.trace))))


if __name__ == "__main__":
    main()
