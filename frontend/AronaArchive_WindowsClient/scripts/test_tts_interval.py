#!/usr/bin/env python3
"""Send typical Arona replies to the configured TTS backend and report RTT."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CLIENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = CLIENT_ROOT / "Config" / "config.json"
DEFAULT_EXAMPLE = CLIENT_ROOT / "Config" / "config.example.json"

# 1–2 sentence Renderer-style lines (welcome / chat / continue / care).
TEXTS = [
    "老师，下午好呀！今天过得怎么样？",
    "老师辛苦啦！要我帮你放松一下吗？",
    "好的老师，那我不打扰啦！工作加油哦~",
    "老师好厉害呀！新策略听起来很酷，能想到优化性能的办法真棒！",
    "嘿嘿，能帮到老师就好啦！老师继续加油哦～",
    "已连接至系统管理员阿洛娜。欢迎回来，老师。",
    "中午好，老师！午饭吃了吗？要不陪我去买好吃的~",
    "老师，今天也要加油哦！阿洛娜会一直陪着您的。",
    "嗯，我在呢。有什么需要阿洛娜帮忙的，随时叫我就好。",
    "晚安，老师。好好休息，明天也要元气满满哦。",
]

TTS_KEYS = (
    "text_lang",
    "ref_audio_path",
    "prompt_text",
    "prompt_lang",
    "top_k",
    "top_p",
    "temperature",
    "text_split_method",
    "batch_size",
    "batch_threshold",
    "split_bucket",
    "speed_factor",
    "fragment_interval",
    "seed",
    "parallel_infer",
    "repetition_penalty",
    "sample_steps",
    "super_sampling",
)


def load_tts_section(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    tts = data.get("tts")
    if not isinstance(tts, dict):
        raise ValueError(f"no tts object in {path}")
    return tts


def resolve_backend(tts: dict, override: str) -> str:
    raw = (override or str(tts.get("backend") or "official")).strip().lower()
    if raw in ("official", "minimal"):
        return raw
    raise ValueError(f"unknown TTS backend: {raw}")


def rewrite_ref_audio_path(path: str, backend: str) -> str:
    if backend != "minimal" or not path:
        return path
    normalized = path.replace("\\", "/")
    if Path(path).is_absolute() or normalized.startswith("../gpt-sovits/"):
        return path
    return "../gpt-sovits/" + normalized.lstrip("/")


def build_official_payload_base(tts: dict) -> dict:
    base = {
        "text_lang": "zh",
        "ref_audio_path": "ref_audio/Arona/arona_academy_in_2.ogg",
        "prompt_text": "这里为您准备了各种课程和活动，请按您喜欢的方式安排日程吧！",
        "prompt_lang": "zh",
        "top_k": 15,
        "top_p": 1.0,
        "temperature": 1.0,
        "text_split_method": "cut0",
        "batch_size": 1,
        "batch_threshold": 0.75,
        "split_bucket": True,
        "speed_factor": 1.0,
        "fragment_interval": 0.3,
        "seed": -1,
        "streaming_mode": False,
        "parallel_infer": True,
        "repetition_penalty": 1.35,
        "sample_steps": 32,
        "super_sampling": False,
        "media_type": "wav",
    }
    for key in TTS_KEYS:
        if key in tts:
            base[key] = tts[key]
    base["streaming_mode"] = False
    base["media_type"] = "wav"
    return base


def build_minimal_payload_base(tts: dict) -> dict:
    official = build_official_payload_base(tts)
    voice = str(tts.get("voice") or "arona")
    return {
        "voice": voice,
        "model": "gpt-sovits-v2",
        "response_format": "wav",
        "text_lang": official["text_lang"],
        "speed": official["speed_factor"],
        "top_k": official["top_k"],
        "top_p": official["top_p"],
        "temperature": official["temperature"],
        "pause_length": official["fragment_interval"],
        "ref_audio": rewrite_ref_audio_path(str(official["ref_audio_path"]), "minimal"),
        "ref_text": official["prompt_text"],
        "ref_lang": official["prompt_lang"],
    }


def call_tts(url: str, payload: dict, timeout: float) -> tuple[int, float, int, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            elapsed = time.perf_counter() - t0
            return resp.status, elapsed, len(body), ""
    except urllib.error.HTTPError as e:
        elapsed = time.perf_counter() - t0
        try:
            msg = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            msg = str(e)
        return e.code, elapsed, 0, msg
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return -1, elapsed, 0, f"{type(e).__name__}: {e}"


def resolve_config(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    if DEFAULT_CONFIG.is_file():
        return DEFAULT_CONFIG
    if DEFAULT_EXAMPLE.is_file():
        return DEFAULT_EXAMPLE
    raise FileNotFoundError("Config/config.json and config.example.json not found")


def resolve_endpoint(tts: dict, backend: str, host_override: str, port_override: int) -> tuple[str, int, str]:
    if backend == "minimal":
        host = host_override or str(tts.get("minimal_host") or tts.get("host") or "127.0.0.1")
        port = port_override or int(tts.get("minimal_port") or 8000)
        return host, port, f"http://{host}:{port}/v1/audio/speech"
    host = host_override or str(tts.get("host") or "127.0.0.1")
    port = port_override or int(tts.get("port") or 9880)
    return host, port, f"http://{host}:{port}/tts"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="POST typical Arona lines to official /tts or minimal /v1/audio/speech."
    )
    parser.add_argument("--host", default="", help="Override TTS host from config")
    parser.add_argument("--port", type=int, default=0, help="Override TTS port from config")
    parser.add_argument("--backend", default="", help="official or minimal (default: tts.backend)")
    parser.add_argument("--config", default="", help="Client config.json path")
    parser.add_argument("--interval", type=float, default=15.0, help="Seconds to wait after each reply")
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-request HTTP timeout (seconds)")
    parser.add_argument("--count", type=int, default=10, help="How many texts to send (max 10)")
    args = parser.parse_args()

    try:
        cfg_path = resolve_config(args.config or None)
        tts = load_tts_section(cfg_path)
        backend = resolve_backend(tts, args.backend)
    except Exception as e:
        print(f"Failed to load TTS config: {e}", file=sys.stderr)
        return 1

    host, port, url = resolve_endpoint(tts, backend, args.host, args.port)
    if backend == "minimal":
        base = build_minimal_payload_base(tts)
        ref_label = f"ref_audio={base['ref_audio']} voice={base['voice']}"
        text_key = "input"
    else:
        base = build_official_payload_base(tts)
        ref_label = f"ref_audio_path={base['ref_audio_path']} parallel_infer={base['parallel_infer']}"
        text_key = "text"
    texts = TEXTS[: max(1, min(args.count, len(TEXTS)))]

    print(f"Config: {cfg_path}")
    print(f"Backend: {backend}")
    print(f"POST {url} interval={args.interval}s timeout={args.timeout}s n={len(texts)}")
    print(ref_label)
    print(flush=True)

    rows: list[tuple[int, str, bool, float, int]] = []
    for i, text in enumerate(texts, start=1):
        payload = dict(base)
        payload[text_key] = text
        preview = text if len(text) <= 36 else text[:33] + "..."
        print(f"[{i}/{len(texts)}] {preview}", flush=True)
        status, elapsed, nbytes, err = call_tts(url, payload, args.timeout)
        ok = status == 200 and nbytes > 0
        rows.append((i, text, ok, elapsed, nbytes))
        if ok:
            print(f"         OK  {elapsed:.3f}s  {nbytes} bytes", flush=True)
        else:
            print(f"         FAIL status={status} {elapsed:.3f}s err={err}", flush=True)
        if i < len(texts) and args.interval > 0:
            print(f"         wait {args.interval:.0f}s ...", flush=True)
            time.sleep(args.interval)

    ok_times = [elapsed for _, _, ok, elapsed, _ in rows if ok]
    print("\n----- summary -----")
    print(f"{'#':>3}  {'ok':>3}  {'sec':>8}  text")
    for i, text, ok, elapsed, _nbytes in rows:
        flag = "yes" if ok else "no"
        print(f"{i:>3}  {flag:>3}  {elapsed:8.3f}  {text}")
    if ok_times:
        avg = sum(ok_times) / len(ok_times)
        print(
            f"\nOK {len(ok_times)}/{len(rows)}  "
            f"min={min(ok_times):.3f}s  max={max(ok_times):.3f}s  avg={avg:.3f}s"
        )
    else:
        print(f"\nOK 0/{len(rows)}  no successful responses")
        return 1
    return 0 if len(ok_times) == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
