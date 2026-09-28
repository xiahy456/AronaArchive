#!/usr/bin/env python3
"""Merge lip-sync animation(s) from arona_spr.json into arona_spr_full.json."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

DEFAULT_ANIMATIONS = ("Arona_Work_In_1_CN",)
ASSETS_DIR = Path(__file__).resolve().parent.parent / "Assets" / "AronaSpineAssets"


def _collect_event_names(anim: dict) -> set[str]:
    names: set[str] = set()
    for entry in anim.get("events") or []:
        if isinstance(entry, dict) and "name" in entry:
            names.add(entry["name"])
    return names


def _validate_anim(full: dict, anim_name: str, anim: dict) -> list[str]:
    errors: list[str] = []
    bone_names = {b["name"] for b in full.get("bones") or []}
    slot_names = {s["name"] for s in full.get("slots") or []}

    for bone in (anim.get("bones") or {}):
        if bone not in bone_names:
            errors.append(f"{anim_name}: bone '{bone}' missing in full skeleton")
    for slot in (anim.get("slots") or {}):
        if slot not in slot_names:
            errors.append(f"{anim_name}: slot '{slot}' missing in full skeleton")

    full_events = full.get("events") or {}
    for ev in _collect_event_names(anim):
        if ev not in full_events:
            errors.append(f"{anim_name}: event '{ev}' missing in full events")
    return errors


def merge(
    spr_path: Path,
    full_path: Path,
    anim_names: list[str],
) -> None:
    spr = json.loads(spr_path.read_text(encoding="utf-8"))
    full = json.loads(full_path.read_text(encoding="utf-8"))

    spr_anims = spr.get("animations") or {}
    full_anims = full.setdefault("animations", {})
    if full.get("events") is None:
        full["events"] = {}

    spr_events = spr.get("events") or {}
    missing_anims = [n for n in anim_names if n not in spr_anims]
    if missing_anims:
        raise SystemExit(f"animations not found in {spr_path.name}: {missing_anims}")

    for name in anim_names:
        anim = copy.deepcopy(spr_anims[name])
        for ev in _collect_event_names(anim):
            if ev not in full["events"]:
                if ev not in spr_events:
                    raise SystemExit(
                        f"event '{ev}' referenced by '{name}' but missing in {spr_path.name}"
                    )
                full["events"][ev] = copy.deepcopy(spr_events[ev])
        full_anims[name] = anim
        print(f"merged animation: {name}")

    errors: list[str] = []
    for name in anim_names:
        errors.extend(_validate_anim(full, name, full_anims[name]))
    if errors:
        raise SystemExit("validation failed:\n  " + "\n  ".join(errors))

    full_path.write_text(
        json.dumps(full, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"wrote {full_path}")
    print(
        "ok:",
        f"animations={list(anim_names)}",
        f"events={sorted(_collect_event_names(full_anims[anim_names[0]]) | set().union(*(_collect_event_names(full_anims[n]) for n in anim_names)))}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spr",
        type=Path,
        default=ASSETS_DIR / "arona_spr.json",
        help="source skeleton JSON (default: Assets/AronaSpineAssets/arona_spr.json)",
    )
    parser.add_argument(
        "--full",
        type=Path,
        default=ASSETS_DIR / "arona_spr_full.json",
        help="target skeleton JSON (default: Assets/AronaSpineAssets/arona_spr_full.json)",
    )
    parser.add_argument(
        "--anim",
        action="append",
        dest="anims",
        default=None,
        help="animation name to merge (repeatable; default: Arona_Work_In_1_CN)",
    )
    args = parser.parse_args()
    anims = args.anims or list(DEFAULT_ANIMATIONS)

    if not args.spr.is_file():
        raise SystemExit(f"missing source: {args.spr}")
    if not args.full.is_file():
        raise SystemExit(f"missing target: {args.full}")

    merge(args.spr, args.full, anims)
    return 0


if __name__ == "__main__":
    sys.exit(main())
