"""Extract planner draft and renderer text from interactive information logs.

Reads backend/logs/arona-backend.log (or --input) and writes a timestamped
dump of each `app.ws_handler: interactive information` block's planner_json.draft
and renderer_text into backend/logs/.

Usage (from repo root or backend/):
  python backend/scripts/extract_interactive_drafts.py
  python scripts/extract_interactive_drafts.py --skip-missing
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = BACKEND_DIR / "logs" / "arona-backend.log"
DEFAULT_OUTPUT = BACKEND_DIR / "logs" / "interactive_draft_renderer.txt"

RECORD_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    r"\[(?P<level>\w+)\] (?P<logger>[\w.]+): (?P<msg>.*)$"
)
INTERACTIVE_PREFIX = "interactive information:"
SECTION_HEADERS = (
    "request",
    "planner_prompt",
    "planner_reasoning",
    "planner_json",
    "renderer_prompt",
    "renderer_text",
    "response",
)
SECTION_RE = re.compile(
    r"^(?P<name>" + "|".join(SECTION_HEADERS) + r"):\s*$",
    re.MULTILINE,
)
NONE = "(none)"


@dataclass
class InteractiveRecord:
    timestamp: str
    draft: str
    renderer_text: str

    @property
    def has_payload(self) -> bool:
        return self.draft != NONE or self.renderer_text != NONE


def _normalize_field(text: str | None) -> str:
    value = (text or "").strip()
    return value if value else NONE


def _extract_draft(planner_json_text: str) -> str:
    raw = _normalize_field(planner_json_text)
    if raw == NONE:
        return NONE
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return NONE
    if not isinstance(parsed, dict):
        return NONE
    draft = parsed.get("draft")
    if draft is None:
        return NONE
    if isinstance(draft, str):
        return draft.strip() if draft.strip() else NONE
    return _normalize_field(str(draft))


def parse_sections(message: str) -> dict[str, str]:
    """Split an interactive-information message into labeled sections."""
    body = message.strip()
    if body.startswith(INTERACTIVE_PREFIX):
        body = body[len(INTERACTIVE_PREFIX) :].lstrip()
    matches = list(SECTION_RE.finditer(body))
    if not matches:
        return {}
    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[match.group("name")] = body[start:end].strip()
    return sections


def parse_interactive_message(timestamp: str, message: str) -> InteractiveRecord:
    sections = parse_sections(message)
    return InteractiveRecord(
        timestamp=timestamp,
        draft=_extract_draft(sections.get("planner_json", "")),
        renderer_text=_normalize_field(sections.get("renderer_text", "")),
    )


def iter_log_records(text: str):
    current_ts = ""
    current_logger = ""
    current_msg_lines: list[str] = []

    def flush():
        if current_ts:
            yield current_ts, current_logger, "\n".join(current_msg_lines)

    for raw_line in text.splitlines():
        match = RECORD_RE.match(raw_line)
        if match:
            yield from flush()
            current_ts = match.group("ts")
            current_logger = match.group("logger")
            current_msg_lines = [match.group("msg")]
        elif current_ts:
            current_msg_lines.append(raw_line)
    yield from flush()


def extract_records(text: str) -> list[InteractiveRecord]:
    records: list[InteractiveRecord] = []
    for timestamp, logger, message in iter_log_records(text):
        if logger != "app.ws_handler":
            continue
        if not message.startswith(INTERACTIVE_PREFIX):
            continue
        records.append(parse_interactive_message(timestamp, message))
    return records


def render_output(records: list[InteractiveRecord], *, source: Path) -> str:
    lines = [
        f"# source: {source}",
        f"# generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# interactive information: {len(records)}",
        f"# with draft or renderer_text: {sum(1 for r in records if r.has_payload)}",
        "",
    ]
    for index, record in enumerate(records, start=1):
        lines.extend(
            [
                "=" * 72,
                f"[{index}] {record.timestamp}",
                "",
                "planner draft:",
                record.draft,
                "",
                "renderer text:",
                record.renderer_text,
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract planner draft and renderer text from interactive logs."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"backend log file (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output file (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--skip-missing",
        action="store_true",
        help="omit blocks that have neither planner draft nor renderer text",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log_path = args.input if args.input.is_absolute() else (Path.cwd() / args.input)
    out_path = args.output if args.output.is_absolute() else (Path.cwd() / args.output)

    if not log_path.is_file():
        print(f"log file not found: {log_path}", file=sys.stderr)
        return 1

    text = log_path.read_text(encoding="utf-8")
    records = extract_records(text)
    if args.skip_missing:
        records = [r for r in records if r.has_payload]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_output(records, source=log_path), encoding="utf-8")
    print(
        f"wrote {len(records)} records to {out_path} "
        f"(from {log_path})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
