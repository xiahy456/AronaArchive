# Arona-owned launcher. Do not edit clone files from GPT-SoVITS_minimal_inference.
"""Run upstream api_server.py with local hooks (offline BERT, optional SV skip)."""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
    sys.path.insert(0, os.path.join(_HERE, "GPT_SoVITS"))

logger = logging.getLogger("gpt-sovits-api")

# 中文 v2 读不出英文音素时，只把这一小段字母换成读音，不截断后面的中文。
_LETTER_ZH = {
    "A": "诶",
    "B": "比",
    "C": "西",
    "D": "迪",
    "E": "伊",
    "F": "艾弗",
    "G": "吉",
    "H": "艾尺",
    "I": "爱",
    "J": "杰",
    "K": "开",
    "L": "艾勒",
    "M": "艾姆",
    "N": "恩",
    "O": "欧",
    "P": "批",
    "Q": "丘",
    "R": "艾儿",
    "S": "艾丝",
    "T": "提",
    "U": "优",
    "V": "维",
    "W": "达不留",
    "X": "艾克斯",
    "Y": "歪",
    "Z": "贼",
}
_en_frontend_warned = False


def _spell_latin(text: str) -> str:
    parts: list[str] = []
    for ch in text:
        if ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
            parts.append(_LETTER_ZH[ch.upper()])
        else:
            parts.append(ch)
    return "".join(parts)


def _warn_en_frontend_once(exc: BaseException) -> None:
    global _en_frontend_warned
    if _en_frontend_warned:
        return
    _en_frontend_warned = True
    logger.error(
        "English frontend unavailable (%s: %s). "
        "Install g2p_en and NLTK data cmudict, averaged_perceptron_tagger "
        "in the minimal runtime. English words will be spelled as letters.",
        type(exc).__name__,
        exc,
    )


def _split_text_keep_ellipsis(text: str) -> list[str]:
    """Same merge rules as upstream split_text, but ellipsis is not a sentence boundary."""
    text = text.strip("\n")
    if not text:
        return []

    # Upstream also splits on "…", which cuts 「老师……那个AE」before the English.
    parts = re.split(r"([。！？!?\n])", text)
    sentences: list[str] = []
    for i in range(0, len(parts) - 1, 2):
        sentences.append(parts[i] + parts[i + 1])
    if len(parts) % 2 == 1:
        sentences.append(parts[-1])

    sentences = [s.strip() for s in sentences if s.strip()]

    merged: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) < 10:
            current += sentence
        else:
            if current:
                merged.append(current)
            current = sentence
    if current:
        merged.append(current)
    return merged


def _install_text_hooks() -> None:
    import run_optimized_inference as roi
    import GPT_SoVITS.text.cleaner as cleaner

    roi.split_text = _split_text_keep_ellipsis

    orig_clean = cleaner.clean_text

    def clean_text(text, language, version=None):
        try:
            return orig_clean(text, language, version)
        except Exception as exc:
            if language != "en":
                raise
            if isinstance(exc, (ImportError, LookupError)):
                _warn_en_frontend_once(exc)
            else:
                logger.warning(
                    "English G2P failed for %r (%s: %s); spelling letters",
                    text,
                    type(exc).__name__,
                    exc,
                )
            return orig_clean(_spell_latin(text), "zh", version)

    cleaner.clean_text = clean_text
    # infer_optimized 使用的是「from cleaner import clean_text」绑进本模块的名字。
    if hasattr(roi, "clean_text"):
        roi.clean_text = clean_text


def _wrap_from_pretrained(owner, name: str) -> None:
    orig = getattr(owner, name)

    def wrapped(*args, **kwargs):
        kwargs.setdefault("local_files_only", True)
        return orig(*args, **kwargs)

    setattr(owner, name, wrapped)


def _install_hooks() -> None:
    from transformers import AutoModelForMaskedLM, AutoTokenizer

    _wrap_from_pretrained(AutoTokenizer, "from_pretrained")
    _wrap_from_pretrained(AutoModelForMaskedLM, "from_pretrained")

    # run_optimized_inference 会「from sv import SV」。缺权重时必须先换成空实现，
    # 再装文本钩子，否则推理模块拿到的仍是会 torch.load 的原类。
    import GPT_SoVITS.sv as sv_mod

    sv_path = os.environ.get(
        "SV_MODEL_PATH",
        os.path.join(os.getcwd(), "pretrained_models", "sv", "pretrained_eres2netv2w24s4ep4.ckpt"),
    )
    if not os.path.isfile(sv_path):

        class SVOptional:
            def __init__(self, device, is_half):
                self.device = device
                self.is_half = is_half
                logger.info("SV checkpoint not found (%s); skipping (v2 / non-v2Pro).", sv_path)

            def compute_embedding3(self, wav):
                return None

        sv_mod.SV = SVOptional

    _install_text_hooks()


def _preload_default_voice(api_server) -> None:
    names = list(api_server.voice_manager.voices.keys())
    if not names:
        logger.warning("No voices in config; skipping engine preload.")
        return
    name = names[0]
    voice_config = api_server.voice_manager.get_voice(name)
    logger.info("Preloading voice engine: %s", name)
    try:
        api_server.model_manager.get_engine(voice_config["gpt_path"], voice_config["sovits_path"])
    except Exception:
        logger.exception("Preload failed for voice %s", name)
        raise
    logger.info("Preloaded voice engine: %s", name)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    _install_hooks()

    import api_server
    import uvicorn

    @api_server.app.on_event("startup")
    def _on_startup():
        _preload_default_voice(api_server)

    parser = argparse.ArgumentParser(description="Arona launcher for GPT-SoVITS minimal api_server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--cnhubert_path")
    parser.add_argument("--bert_path")
    parser.add_argument("--voices_config")
    args = parser.parse_args()
    uvicorn.run(api_server.app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
