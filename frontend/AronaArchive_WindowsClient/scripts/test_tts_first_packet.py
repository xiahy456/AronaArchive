#!/usr/bin/env python3
"""Compare official GPT-SoVITS vs minimal_inference: first-audio vs complete time.

Two backends cannot share one GPU. Typical usage:

  python test_tts_first_packet.py --backend official
  # stop official TTS, start minimal, then:
  python test_tts_first_packet.py --backend minimal

  python test_tts_first_packet.py --backend both   # hits :9880 then :8000

First-packet time is measured as the first body bytes after a 44-byte WAV
header (playable PCM). Complete time is when the HTTP stream ends.
Official streaming_mode defaults to true so first-packet is meaningful; pass
--no-official-stream to match desktop client tts.streaming=false (整包返回).
Client tts.streaming=true consumes the same chunked WAV (header then PCM).
"""

from __future__ import annotations

import argparse
import http.client
import json
import socket
import statistics
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from test_tts_interval import (  # noqa: E402
    build_minimal_payload_base,
    build_official_payload_base,
    load_tts_section,
    resolve_config,
    resolve_endpoint,
)

# 50 条阿洛娜口播量级中文（短应答 + 中句 + 少量稍长句）。
TEXTS = [
    "老师好。",
    "嗯，我在呢。",
    "好的老师。",
    "收到。",
    "嘿嘿。",
    "老师，下午好呀！",
    "今天过得怎么样？",
    "老师辛苦啦！",
    "要不要休息一下？",
    "我一直都在哦。",
    "已连接至系统管理员阿洛娜。欢迎回来，老师。",
    "中午好，老师！午饭吃了吗？要不陪我去买好吃的~",
    "老师，今天也要加油哦！阿洛娜会一直陪着您的。",
    "晚安，老师。好好休息，明天也要元气满满哦。",
    "老师下午好呀！今天过得怎么样？",
    "老师辛苦啦！要我帮你放松一下吗？",
    "好的老师，那我不打扰啦！工作加油哦~",
    "嘿嘿，能帮到老师就好啦！老师继续加油哦～",
    "嗯，有什么需要阿洛娜帮忙的，随时叫我就好。",
    "老师好厉害呀！新策略听起来很酷。",
    "老师想喝点什么？茶还是咖啡，我都可以记下来。",
    "日程表我已经整理好了，老师要不要现在看一眼？",
    "外面好像要下雨了，老师出门的话记得带伞哦。",
    "老师刚才说的那件事，我记住了，不会忘掉的。",
    "如果老师累了，就先把工作放到一边，陪我说说话吧。",
    "老师点什么菜我都很了解的。最喜欢番茄炒蛋、牛肉汉堡。",
    "老师好厉害呀，我都会的！快说您最爱吃的菜，我都记住了~",
    "好主意！老师陪我去看电影、散步，日子会过得更开心哦~",
    "老师今天好好吃，下次我还要帮您记着呢~",
    "阿洛娜会把老师交代的事情一件件做好，请放心。",
    "老师，这份报告我已经看过了，关键结论我给你划出来了。",
    "如果接下来还有会议，我可以帮老师把时间和地点再确认一遍。",
    "老师刚才皱眉了呢。是遇到了麻烦吗？愿意的话，跟我说一说。",
    "没关系的，老师。就算现在还不顺利，我们也可以慢慢想办法。",
    "我在什亭之匣里等您。不管过多久，阿洛娜都会在这里。",
    "老师想听我唱歌吗？还是想听今天基沃托斯的趣闻？都可以哦。",
    "请把那份文件发给我吧，我帮老师检查有没有漏掉的地方。",
    "现在是晚上了，老师已经连续工作很久了，真的要再坚持吗？",
    "我不会离开屏幕的。老师叫我的时候，我会马上回答。",
    "老师对阿洛娜这么好，我……我会更加努力当好管理员的。",
    "今天的待办还有三件：回邮件、改计划、以及陪老师喝杯热饮。",
    "老师如果觉得我哪里说错了，请直接指出来，我会先认错再改正。",
    "基沃托斯很大，但老师在这里的时候，这里就是最让我安心的地方。",
    "我把明天早上的闹钟、早饭提醒和第一场会议都排进日程里了。",
    "老师笑起来的时候，阿洛娜也会觉得，今天的工作都值得了。",
    "那件麻烦事也许没那么可怕。我们把它拆成一小步一小步来做好不好？",
    "老师，请把肩膀放松一下。我在，什么事都不必一个人扛着。",
    "如果老师现在不想说话，我就安静待着。需要我的时候再叫我。",
    "阿洛娜准备好了各种课程和活动，请按您喜欢的方式安排日程吧。",
    "老师，无论今天发生了什么，回到这里就好。欢迎回家。",
]

WAV_HEADER_MIN = 44


def mean(xs: list[float]) -> float:
    return statistics.fmean(xs) if xs else float("nan")


def timed_post(
    url: str,
    payload: dict[str, Any],
    timeout: float,
) -> tuple[int, float | None, float | None, int, str]:
    """Return status, first-audio sec, complete sec, nbytes, error.

    Uses read1() so the first small WAV header / PCM chunk is not buffered
    until a 4KiB fill, which would inflate 首包.
    """
    parsed = urlsplit(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Connection": "close",
    }

    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    t0 = time.perf_counter()
    try:
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        status = int(resp.status)
        if status != 200:
            err = resp.read(400).decode("utf-8", errors="replace")
            return status, None, time.perf_counter() - t0, 0, err[:300]

        first_audio: float | None = None
        buf = bytearray()
        while True:
            chunk = resp.read1(8192)
            if not chunk:
                break
            buf.extend(chunk)
            if first_audio is None and len(buf) > WAV_HEADER_MIN:
                first_audio = time.perf_counter() - t0
        complete = time.perf_counter() - t0
        if first_audio is None and buf:
            first_audio = complete
        err = ""
        if len(buf) <= WAV_HEADER_MIN:
            err = f"empty audio ({len(buf)} bytes, WAV header only)"
        return status, first_audio, complete, len(buf), err
    except (TimeoutError, socket.timeout) as e:
        return -1, None, time.perf_counter() - t0, 0, f"Timeout: {e}"
    except (ConnectionError, socket.error, http.client.HTTPException, OSError) as e:
        return -1, None, time.perf_counter() - t0, 0, f"{type(e).__name__}: {e}"
    finally:
        conn.close()


def build_payload(tts: dict, backend: str, text: str, official_stream: bool) -> dict[str, Any]:
    if backend == "minimal":
        payload = build_minimal_payload_base(tts)
        payload["input"] = text
        return payload
    payload = build_official_payload_base(tts)
    payload["text"] = text
    payload["streaming_mode"] = bool(official_stream)
    payload["media_type"] = "wav"
    return payload


def run_backend(
    name: str,
    url: str,
    tts: dict,
    texts: list[str],
    timeout: float,
    interval: float,
    warmup: bool,
    official_stream: bool,
) -> list[dict[str, Any]]:
    print(f"\n===== {name}  POST {url}  n={len(texts)} =====", flush=True)
    if name == "official":
        mode = "true 流式" if official_stream else "false 整包（客户端 tts.streaming=false）"
        print(f"official streaming_mode={mode}", flush=True)

    if warmup:
        warm = build_payload(tts, name, "老师好。", official_stream)
        print("warmup ...", flush=True)
        status, first, done, nbytes, err = timed_post(url, warm, timeout)
        warm_ok = status == 200 and nbytes > WAV_HEADER_MIN
        if warm_ok:
            print(
                f"  warmup ok  first={first:.3f}s  done={done:.3f}s  {nbytes} bytes"
                if first is not None and done is not None
                else f"  warmup ok  {nbytes} bytes",
                flush=True,
            )
        else:
            print(f"  warmup FAIL status={status} bytes={nbytes} err={err}", flush=True)
        if interval > 0:
            time.sleep(interval)

    rows: list[dict[str, Any]] = []
    for i, text in enumerate(texts, start=1):
        payload = build_payload(tts, name, text, official_stream)
        preview = text if len(text) <= 28 else text[:25] + "..."
        print(f"[{i:02d}/{len(texts)}] {preview}", flush=True)
        status, first, done, nbytes, err = timed_post(url, payload, timeout)
        ok = status == 200 and nbytes > WAV_HEADER_MIN and first is not None and done is not None
        rows.append(
            {
                "i": i,
                "text": text,
                "ok": ok,
                "status": status,
                "first": first,
                "done": done,
                "bytes": nbytes,
                "err": err,
            }
        )
        if ok:
            print(
                f"         first={first:.3f}s  done={done:.3f}s  {nbytes} bytes",
                flush=True,
            )
        else:
            print(f"         FAIL status={status} bytes={nbytes} err={err}", flush=True)
        if i < len(texts) and interval > 0:
            time.sleep(interval)
    return rows


def summarize(name: str, rows: list[dict[str, Any]]) -> dict[str, float]:
    firsts = [float(r["first"]) for r in rows if r["ok"]]
    dones = [float(r["done"]) for r in rows if r["ok"]]
    stats = {
        "ok": float(len(firsts)),
        "n": float(len(rows)),
        "first_avg": mean(firsts),
        "first_min": min(firsts) if firsts else float("nan"),
        "first_max": max(firsts) if firsts else float("nan"),
        "done_avg": mean(dones),
        "done_min": min(dones) if dones else float("nan"),
        "done_max": max(dones) if dones else float("nan"),
    }
    print(f"\n----- {name} summary -----")
    print(f"{'#':>3}  {'ok':>3}  {'first':>8}  {'done':>8}  text")
    for r in rows:
        flag = "yes" if r["ok"] else "no"
        first_s = f"{r['first']:8.3f}" if r["first"] is not None else f"{'n/a':>8}"
        done_s = f"{r['done']:8.3f}" if r["done"] is not None else f"{'n/a':>8}"
        print(f"{r['i']:>3}  {flag:>3}  {first_s}  {done_s}  {r['text']}")
    print(
        f"\nOK {int(stats['ok'])}/{int(stats['n'])}"
        f"  first avg={stats['first_avg']:.3f}s  min={stats['first_min']:.3f}s  max={stats['first_max']:.3f}s"
        f"  |  done avg={stats['done_avg']:.3f}s  min={stats['done_min']:.3f}s  max={stats['done_max']:.3f}s"
    )
    return stats


def print_compare(official: dict[str, float], minimal: dict[str, float]) -> None:
    def delta(key: str) -> str:
        a, b = official[key], minimal[key]
        if a != a or b != b:  # NaN
            return "n/a"
        d = b - a
        faster = "minimal faster" if d < 0 else ("official faster" if d > 0 else "tie")
        return f"{d:+.3f}s ({faster})"

    print("\n===== official vs minimal (minimal - official) =====")
    print(f"first-packet avg: {delta('first_avg')}")
    print(f"complete     avg: {delta('done_avg')}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="50 Chinese lines: first-audio vs complete time for official and/or minimal TTS."
    )
    parser.add_argument(
        "--backend",
        default="both",
        choices=("official", "minimal", "both"),
        help="Which engine to hit. both = official then minimal.",
    )
    parser.add_argument("--config", default="", help="Client config.json path")
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-request timeout (seconds)")
    parser.add_argument("--interval", type=float, default=1.0, help="Pause after each request (seconds)")
    parser.add_argument("--count", type=int, default=50, help="How many texts (max 50)")
    parser.add_argument("--no-warmup", action="store_true", help="Skip the discarded warmup request")
    parser.add_argument(
        "--official-stream",
        dest="official_stream",
        action="store_true",
        default=True,
        help="Official streaming_mode=true（默认，用于测首包）",
    )
    parser.add_argument(
        "--no-official-stream",
        dest="official_stream",
        action="store_false",
        help="Official streaming_mode=false，与客户端 tts.streaming=false 整包返回一致",
    )
    parser.add_argument("--json", default="", help="Write per-sentence results to this JSON path")
    parser.add_argument("--official-host", default="", help="Override official host")
    parser.add_argument("--official-port", type=int, default=0, help="Override official port")
    parser.add_argument("--minimal-host", default="", help="Override minimal host")
    parser.add_argument("--minimal-port", type=int, default=0, help="Override minimal port")
    args = parser.parse_args()

    try:
        cfg_path = resolve_config(args.config or None)
        tts = load_tts_section(cfg_path)
    except Exception as e:
        print(f"Failed to load TTS config: {e}", file=sys.stderr)
        return 1

    texts = TEXTS[: max(1, min(args.count, len(TEXTS)))]
    backends = ("official", "minimal") if args.backend == "both" else (args.backend,)

    print(f"Config: {cfg_path}")
    print(f"Sentences: {len(texts)}  timeout={args.timeout}s  interval={args.interval}s")
    print("First-packet = time to first bytes after 44-byte WAV header; done = stream end.")

    collected: dict[str, dict[str, float]] = {}
    all_rows: dict[str, list[dict[str, Any]]] = {}
    any_fail = False
    for name in backends:
        if name == "official":
            _host, _port, url = resolve_endpoint(tts, "official", args.official_host, args.official_port)
        else:
            _host, _port, url = resolve_endpoint(tts, "minimal", args.minimal_host, args.minimal_port)
        rows = run_backend(
            name=name,
            url=url,
            tts=tts,
            texts=texts,
            timeout=args.timeout,
            interval=args.interval,
            warmup=not args.no_warmup,
            official_stream=args.official_stream,
        )
        all_rows[name] = rows
        collected[name] = summarize(name, rows)
        if int(collected[name]["ok"]) != len(rows):
            any_fail = True

    if "official" in collected and "minimal" in collected:
        print_compare(collected["official"], collected["minimal"])

    if args.json:
        def clean(v: Any) -> Any:
            if isinstance(v, float) and v != v:
                return None
            return v

        out = {
            "config": str(cfg_path),
            "official_stream": bool(args.official_stream),
            "backends": {
                name: {
                    "stats": {k: clean(v) for k, v in collected[name].items()},
                    "rows": all_rows[name],
                }
                for name in backends
            },
        }
        json_path = Path(args.json)
        json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {json_path}")

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
