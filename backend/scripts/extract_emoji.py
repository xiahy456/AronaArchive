"""Extract QQ sticker metadata from a captured message JSONL dump.

Each line is an envelope whose ``payload`` is a JSON string (or object).
Image segments that carry sticker fields are written as
``emoji_package_id``, ``emoji_id``, ``key``, ``summary``, plus an empty
``description``.

Usage (from repo root or backend/):
  python backend/scripts/extract_emoji.py
  python scripts/extract_emoji.py --input path/to/emoji_messages.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_INPUT = REPO_ROOT / "docs" / "emoji_messages.jsonl"
DEFAULT_OUTPUT = BACKEND_DIR / "data" / "knowledge" / "emoji" / "arona_emoji.json"

FIELDS = ("emoji_package_id", "emoji_id", "key", "summary")


def _load_payload(envelope: dict, source: str) -> dict:
    payload_raw = envelope.get("payload")
    if isinstance(payload_raw, str):
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{source}: invalid payload JSON: {exc}") from exc
    elif isinstance(payload_raw, dict):
        payload = payload_raw
    else:
        raise SystemExit(f"{source}: missing payload")
    if not isinstance(payload, dict):
        raise SystemExit(f"{source}: payload is not an object")
    return payload


def extract_emojis(path: Path) -> list[dict]:
    emojis: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            source = f"{path}:{line_no}"
            try:
                envelope = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{source}: invalid JSONL line: {exc}") from exc
            if not isinstance(envelope, dict):
                raise SystemExit(f"{source}: line is not a JSON object")

            payload = _load_payload(envelope, source)
            found = False
            for segment in payload.get("message") or []:
                if not isinstance(segment, dict) or segment.get("type") != "image":
                    continue
                data = segment.get("data") or {}
                if not isinstance(data, dict):
                    continue
                if "emoji_id" not in data and "emoji_package_id" not in data:
                    continue
                item: dict[str, str] = {}
                for field in FIELDS:
                    value = data.get(field)
                    if value is None or value == "":
                        raise SystemExit(f"{source}: missing {field}")
                    item[field] = str(value)
                item["description"] = ""
                emojis.append(item)
                found = True
            if not found:
                raise SystemExit(f"{source}: no emoji image segment")
    return emojis


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if not args.input.is_file():
        raise SystemExit(f"input not found: {args.input}")

    emojis = extract_emojis(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(emojis, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(emojis)} emojis to {args.output}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    main()
