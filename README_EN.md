# AronaAI

<p align="center">
  <img src="assets/logo.png" alt="AronaAI Logo" width="200"/>
</p>

<p align="center">
  <strong>A non-conversational desktop AI based on Arona from <em>Blue Archive</em></strong>
</p>

<p align="center">
  Through Arona's own independent loop, the system is built as a presence that exists on its own, rather than one that only answers turn by turn. The user enters her logical world as an event.
</p>

<p align="center">
  <sub>The difference between this logical world and the real one is that the real world does not stop for any one person — but this one does.</sub>
</p>

<p align="center">
  <em>Version: 3.2.1</em>
</p>

<p align="center">
  <a href="README.md">中文</a> · <strong>English</strong>
</p>

---

## 📖 Introduction

**AronaAI** is a non-conversational desktop AI modeled after Arona from the game *Blue Archive*. In lore she is the OS administrator of the Shittim Chest: cheerful, enthusiastic, and always ready to help Sensei (the user).

The project wires a life loop, relationship climate, **Planner → AronaLM Renderer**, proactive impulses, memory and world-lore, voice interaction, screen operation, and Spine 2D character animation into one desktop pipeline, so Arona stays on your screen instead of inside a chat box.

<p align="center">
  <img src="assets/running_example_2.png" alt="Running Example" width="600"/>
</p>

<p align="center">
  <em>Desktop client screenshot — Arona & settings UI</em>
</p>

---

## 🏗️ Project Architecture

```
arona-ai/
├── backend/                              # Python backend (FastAPI + WebSocket)
├── frontend/                             # Desktop client (Qt/C++ + Spine)
├── tts/                                  # TTS backend (official / minimal)
├── llm/aronaLM/finetune/                 # AronaLM fine-tune (not actually a large model… I wrote that wrong earlier and still haven't changed it)
├── models/                               # Local model weights (download yourself)
├── docs/                                 # Architecture, hot-word lists, and other docs
├── assets/                               # Project assets
├── start-all.bat                         # Windows one-click local start for all services
├── pack-client.ps1                       # pack the desktop client
├── pack-backend.ps1                      # pack the Windows portable backend
└── pack-tts.ps1                          # pack TTS scripts and reference audio
```

See [`docs/architecture.md`](docs/architecture.md) for the full directory tree.

---

## ✨ Core Features

### 🤖 AI Engine

- **Life loop**: Arona keeps a self-running realtime state; Sensei's actions enter her current thoughts and behavior
- **Relationship climate**: three scalars — trust / dependence / tension — form a vector. User actions are classified by rules, then a lookup table updates the climate; climate zones decide whether she speaks, how she holds herself, or stays silent
- **Dual-model pipeline**: Planner intent planning → Renderer (AronaLM-Renderer-V2.x)
- **Proactive impulses**: thoughts that arise in the loop, and thoughts that enter her thinking, first become impulses; she then decides for herself whether to put them into words or action
- **Screen vision and computer use**: when she needs information she reads the screen, and she completes tasks by operating the computer
- **Continuous dictation**: ASR fragments go into a buffer first and are submitted after silence; the system decides when to reply
- **Memory and knowledge are separate**: long-term user facts go to SQLite + FTS5 + Chroma; Arona's short-term memory goes to a JSON sliding window; world-lore goes Markdown corpus → local BGE + Chroma RAG; they are never mixed, and each is injected into the prompt on demand
- **Async memory extraction**: the main dialogue path is not blocked; LLM JSON extraction

### 🖥️ Desktop Client & Voice

- **Spine 2D animation**: Arona's character art, expressions, and touch interaction
- **Qt UI**: Windows desktop app talking to the backend over WebSocket; the system tray can show/hide the window and toggle click-through and screenshot input
- **Text and voice**: a global hotkey opens a multi-line input box; Enter sends. Tencent Cloud real-time ASR turns speech into text; GPT-SoVITS synthesizes speech
- **Global hotkeys** (all of these can be changed in `config.json`):

| Default hotkey | Action |
|----------------|--------|
| `Ctrl+Alt+V` | Toggle voice input |
| `Ctrl+Alt+C` | Toggle click-through |
| `Ctrl+Alt+T` | Open text input |
| `Ctrl+Alt+X` | Toggle screen-capture input |
| `Ctrl+Alt+S` | Cancel the current computer-use run |

---

## 🚀 Quick Start

### Backend

Download the packaged portable backend from the [Releases](https://github.com/xiahy456/AronaAI/releases) page. The bundle includes a Python runtime; you do **not** need conda or Python installed on the machine.

1. Open the Releases page and download the latest **portable zip** (`AronaAI_Backend_v*_x64.zip`)

2. After extracting, edit `config.yaml` in the directory and fill in at least these keys:

   - `planner.api_key` / `memory.extractor.api_key`: replace `YOUR_DEEPSEEK_API_KEY` with your DeepSeek API Key. **Planner requires a key**; without a key, or with `planner.enabled` off, the backend falls back to the local single model. Memory extraction without a key uses the regex fallback. When a screenshot or computer use is involved, Planner uses `planner.vision_model` (default `deepseek-flash`)
   - `model.enabled`: whether to enable Arona-Renderer rendering correction; `true` enables it, `false` uses the Planner draft only. Place the GGUF only when this is enabled. **Disabled by default**
   - `knowledge.enabled`: whether to enable world-lore RAG. Official zip packages that already have the corpus ingested keep this **enabled by default**; the sample config for running from source is `false` until you ingest the corpus
   - `computer_use.enabled`: whether to allow Arona to operate Sensei's computer. **Enabled by default**; the client and backend need to be turned on together

3. Place models under `models/` in the extracted directory as needed (paths are already set in the bundled `config.yaml`; see the bundled `models/README.txt` or [`models/README.md`](models/README.md)):

   - When Renderer is enabled: `models/AronaLM-Renderer-V2.4/AronaLM-Renderer-V2.4.Q4_K_M.gguf`

4. Double-click `AronaAI_Backend.bat` to start. Set the desktop client's `websocket_url` to `ws://127.0.0.1:20456/ws` (this is already the default).

> **System requirements**: Windows 10 / 11 x64. If it fails to start, run the bundled `vc_redist.x64.exe` first. Renderer GPU layers need an NVIDIA GPU and a reasonably recent driver. Do not extract a new version over a directory you are already using (unless you do not need to keep memory); runtime data lives in `data/memory/` and `logs/`.

Full field docs and running from source (conda env `shittim-chest` / `python -m app.main`) are in [`backend/README.md`](backend/README.md).

### Client

Download the packaged client from the [Releases](https://github.com/xiahy456/AronaAI/releases) page.

1. Open the Releases page and download the latest **installer** (`AronaAI_WindowsClient_v*_x64_Setup.exe`) or **portable zip** (`AronaAI_WindowsClient_v*_x64.zip`)
2. After installing or extracting, edit `Config/config.json` in the program directory and fill in at least these keys:

```json
{
  "aronalm": {
    "websocket_url": "ws://127.0.0.1:20456/ws"
  },
  "tts": {
    "host": "127.0.0.1"
  },
  "tencent_speech_recognizer": {
    "secret_id": "${TENCENT_SECRET_ID}",
    "secret_key": "${TENCENT_SECRET_KEY}",
    "app_id": "${TENCENT_APP_ID}"
  }
}
```

For a remote setup, change `websocket_url` / `tts.host` to the corresponding IPs. Full field docs and building from source are in [`frontend/AronaAI_Spine_WindowsClient/README.md`](frontend/AronaAI_Spine_WindowsClient/README.md).

> **Note**: Upload [`docs/hot_word.txt`](docs/hot_word.txt) as a hot-word list in Tencent Cloud ASR and set it as the default hot-word list.

3. Start the client by running the client executable.

### TTS Service

The official engine is used by default. See [`tts/README.md`](tts/README.md) for the full guide. To use the faster backend, set the client's `tts.backend` to `minimal`; steps are in [`tts/gpt-sovits-minimal/DEPLOY.md`](tts/gpt-sovits-minimal/DEPLOY.md).

1. Extract the [GPT-SoVITS Windows package](https://huggingface.co/lj1995/GPT-SoVITS-windows-package) (a [Yuque mirror](https://www.yuque.com/baicaigongchang1145haoyuangong/ib3g1e/dkxgpiy9zb96hob4#KTvnO) is available in China) into `tts/gpt-sovits/`. You should see `api_v2.py` and `runtime\python.exe`. If prompted to overwrite, skip `go-apiv2` / `ref_audio`.
2. Place the two voice files:

```
tts/gpt-sovits/
├── GPT_weights_v2/            # GPT weights
│   └── ALuoNa_cn-e15.ckpt
└── SoVITS_weights_v2/         # SoVITS weights
    └── ALuoNa_cn_e16_s256.pth
```

3. Extract `AronaAI_GPTSoVITS_v*_x64.zip` from Releases to the repo root.
4. From the repo root, run `.\start-all.ps1`.

---

## 📚 Modules & Configuration

| Module | Docs |
|------|------|
| **Backend** | [`backend/README.md`](backend/README.md) |
| **Desktop client** | [`frontend/AronaAI_Spine_WindowsClient/README.md`](frontend/AronaAI_Spine_WindowsClient/README.md) |
| **TTS** | [`tts/README.md`](tts/README.md) · [`tts/gpt-sovits/DEPLOY.md`](tts/gpt-sovits/DEPLOY.md) · [`tts/gpt-sovits-minimal/DEPLOY.md`](tts/gpt-sovits-minimal/DEPLOY.md) |
| **Models** | [`models/README.md`](models/README.md) |
| **AronaLM fine-tune** (for developers) | [`llm/aronaLM/finetune/README.md`](llm/aronaLM/finetune/README.md) |

---

## 🙏 Acknowledgements

- **Blue Archive (ブルーアーカイブ)** — where all miracles begin (https://bluearchive-cn.com/)
- **Spine** — 2D animation engine (https://esotericsoftware.com/)
- **Kivo Wiki** — in-game assets and Blueaka font (https://kivo.wiki/)
- **Qt** — cross-platform GUI framework (https://www.qt.io/)
- **llama.cpp / llama-cpp-python** — local GGUF inference (https://github.com/ggml-org/llama.cpp)
- **Qwen3-1.7B** — fine-tune base model (https://huggingface.co/Qwen/Qwen3-1.7B)
- **Unsloth** — efficient QLoRA fine-tuning (https://unsloth.ai/)
- **ChromaDB** — vector database (https://www.trychroma.com/products/chromadb)
- **DeepSeek** — Planner intent planning, vision screen-reading, computer-use multimodal control, and memory extraction API (https://www.deepseek.com/)
- **GPT-SoVITS** — speech synthesis (https://github.com/RVC-Boss/GPT-SoVITS)
- **GPT-SoVITS_minimal_inference** — accelerated inference backend (https://github.com/GPT-SoVITS-Devel/GPT-SoVITS_minimal_inference)
- **Tencent Cloud ASR** — online speech recognition (https://cloud.tencent.com/product/asr)
- **bge-small-zh-v1.5** — text embedding model (https://huggingface.co/BAAI/bge-small-zh-v1.5)

<p align="center">
  <strong>Thanks to everyone who helped with development, and to all the creators in the Blue Archive community</strong>
</p>
<p align="center">
  <strong>Thank you for the amazing works and energy you bring to this community</strong>
</p>

---

## ⚖️ License, Copyright & Intellectual Property

This project is licensed under [Apache License 2.0](LICENSE).

This project is an **unofficial fan work** inspired by Arona from *Blue Archive*, and has **no affiliation, partnership, or authorization** with NEXON, NEXON Games, Yostar, or other related rights holders. All characters, settings, trademarks, and other intellectual property in the game remain with the original rights holders; references in this project do not imply a license or any claim of ownership.

[Apache License 2.0](LICENSE) **applies only to this project's original source code and documentation**. This project is **not for commercial profit**. If a rights holder wishes related material removed, please contact us using the details in **[About the Developer](#-about-the-developer)** below; we will cooperate promptly.

---

## ⭐ About the Developer

- **Project lead**: xia_hy456
- **Blog**: https://xia-hy456.top/
- **Feedback**: 2066961858@qq.com

---

<p align="center">
  <sub>/* イチゴミルクのような 甘い甘い奇跡 */</sub>
</p>
