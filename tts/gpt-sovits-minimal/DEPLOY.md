# GPT-SoVITS Minimal Inference 目录与部署

本目录是 AronaArchive 的 **加速 TTS 后端**（[GPT-SoVITS_minimal_inference](https://github.com/GPT-SoVITS-Devel/GPT-SoVITS_minimal_inference) 的 PyTorch `api_server.py`）。与官方 [`../gpt-sovits/`](../gpt-sovits/DEPLOY.md) **二选一**运行，不要同卡双开。

仓库 `.gitignore` **不提交**上游源码、`runtime/` 与虚拟环境。clone 后这里通常只有本文件、启动脚本、`launch_api.py`、`pack-runtime.ps1` 和 `config/voices.json`。**不要改** clone 进来的上游文件；阿洛娜侧的补丁只放在 `launch_api.py` / `watch-api.ps1`。

客户端用 `tts.backend` 选择调用哪套：`official`（默认，`127.0.0.1:9880`）或 `minimal`（本目录，`127.0.0.1:8000`）。`start-all.ps1` 只拉起配置中选中的那一个。

默认请用官方引擎，见 [`../README.md`](../README.md)。本目录是可选加速后端：客户端 `tts.backend` 设为 `minimal` 后按本文部署。本机制作 runtime：`.\pack-runtime.ps1`。

---

## 目录树

```
gpt-sovits-minimal/
├── DEPLOY.md                      # 本文件
├── go-api.bat / go-api.ps1        # Windows 入口（经 watchdog）
├── watch-api.ps1                  # 崩溃自动重启
├── launch_api.py                  # Arona 启动包装（不改上游源码）
├── pack-runtime.ps1               # 把 conda 环境拷到 runtime/（不入库）
├── config/voices.json             # 阿洛娜 v2 权重与默认参考音频（相对本目录）
├── runtime/                       # 打包后的便携 Python；日常启动优先用这个
│   └── python.exe
├── api_server.py                  # clone 后才有；OpenAI 兼容 /v1/audio/speech
└── GPT_SoVITS/                    # clone 后才有
```

权重、预训练和参考音频仍放在官方树，本进程用相对路径引用，不要复制：

```
../gpt-sovits/GPT_weights_v2/ALuoNa_cn-e15.ckpt
../gpt-sovits/SoVITS_weights_v2/ALuoNa_cn_e16_s256.pth
../gpt-sovits/GPT_SoVITS/pretrained_models/chinese-hubert-base
../gpt-sovits/GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large
../gpt-sovits/ref_audio/Arona/*.ogg
```

---

## 环境要求

| 项 | 建议 |
|----|------|
| 系统 | Windows 10/11（与 `start-all.ps1` 一致）；Linux 可作独立 TTS 机 |
| GPU | NVIDIA + CUDA 12.x；CPU 能跑但延迟高 |
| 显存 | 建议 ≥ 8 GB。与 Renderer 同卡时不要同时开官方 `api_v2` |
| Python | 日常用本目录 **`runtime/python.exe`**（`.\pack-runtime.ps1` 从 conda 环境拷出）。conda 只用于制作 runtime。**不要**用 `tts/gpt-sovits/runtime/python.exe` |
| 系统组件 | [VC++ x64 可再发行组件](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)；NVIDIA 驱动需能跑 CUDA 12.6 轮子（cu126） |

---

## 部署步骤

### 1. 官方 GPT-SoVITS 已就位

本后端复用官方权重与 BERT/HuBERT。先按 [`../gpt-sovits/DEPLOY.md`](../gpt-sovits/DEPLOY.md) 放好整合包、`ALuoNa_cn-e15.ckpt`、`ALuoNa_cn_e16_s256.pth` 和 `ref_audio/Arona/`。不必启动官方 `api_v2.py`。

### 2. Clone 上游推理仓库到本目录

在**仓库根目录**执行，使 `api_server.py` 位于 `tts/gpt-sovits-minimal/api_server.py`：

```bash
git clone --depth 1 https://github.com/GPT-SoVITS-Devel/GPT-SoVITS_minimal_inference.git gpt-sovits-minimal-src
# 把 clone 出的文件并入本目录（保留已有 DEPLOY.md / go-api / config）
# Windows 示例：先 clone 到临时目录再复制源码，或在空目录 clone 后把本仓库跟踪的文件拷回去
```

```powershell
# 仓库根目录
git clone --depth 1 https://github.com/GPT-SoVITS-Devel/GPT-SoVITS_minimal_inference.git .gpt-sovits-minimal-upstream
robocopy .gpt-sovits-minimal-upstream tts/gpt-sovits-minimal /E /XD .git /XF DEPLOY.md launch_api.py
# voices.json 若被覆盖，从 git 恢复：
git checkout -- tts/gpt-sovits-minimal/config/voices.json tts/gpt-sovits-minimal/DEPLOY.md tts/gpt-sovits-minimal/watch-api.ps1 tts/gpt-sovits-minimal/launch_api.py tts/gpt-sovits-minimal/go-api.ps1 tts/gpt-sovits-minimal/go-api.bat tts/gpt-sovits-minimal/pack-runtime.ps1
```

完成后应能看到 `tts/gpt-sovits-minimal/api_server.py`。

### 3. 独立 Python 环境（只用于制作 runtime）

不要复用官方整合包的 `runtime/python.exe`。conda / venv 用来装 CUDA Torch 和依赖，再拷进本目录 `runtime/`。日常 `go-api` / `start-all` **优先** `runtime\python.exe`。

```bash
conda create -n gpt-sovits-minimal python=3.10 -y
conda activate gpt-sovits-minimal
cd tts/gpt-sovits-minimal
# 先装 CUDA 轮子。不要用默认 PyPI：会装成 +cpu。cu124 最高 2.6，已有 2.14+cpu 时 pip 会认为已满足。
pip uninstall -y torch torchaudio torchvision
pip install torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu126
pip install -r requirements.txt
python -c "import torch; assert torch.cuda.is_available(), torch.__version__"
```

然后打包（不含权重）：

```powershell
cd tts/gpt-sovits-minimal
.\pack-runtime.ps1
# 可选：打 zip 到仓库根 release/，解压到本目录后应存在 runtime\python.exe
.\pack-runtime.ps1 -Zip
```

`pack-runtime.ps1` 会用 runtime 自己的 `python.exe` 检查 `torch.cuda.is_available()`，失败则报错，避免再打出 CPU 包。

若上游没有 `requirements.txt`，按其 README 安装 PyTorch（CUDA）以及 FastAPI / uvicorn 等 API 依赖。也可用本目录 `.venv`，但 `watch-api` 在存在 `runtime\python.exe` 时不会用它。

`watch-api.ps1` 解析 Python 的顺序：`-PythonExe` → 环境变量 `GPT_SOVITS_MINIMAL_PYTHON` → **`runtime\python.exe`** → `.venv\Scripts\python.exe` → conda 环境 `gpt-sovits-minimal` → PATH 上的 `python`。

runtime zip 只替代 Python 与 pip 依赖。用户仍需：本目录源码（`api_server.py`）、官方权重 / 预训练 / 参考音频，以及 VC++ 运行库。不要把 HuBERT、BERT、ckpt 打进 runtime。

### 4. 核对 voices.json

[`config/voices.json`](config/voices.json) 的 `arona` 条目已指向官方 v2 权重。路径相对 **本目录**（`tts/gpt-sovits-minimal/`）。改权重文件名时同步改这里；客户端 `tts.gpt_path` 在 `backend=minimal` 时不会用来切权重。

### 5. 启动 API

**本机一键（Windows）**：客户端 `config.json` 设 `"backend": "minimal"`，在仓库根目录执行 `.\start-all.ps1`。它只拉起本 watchdog，并把 `runtime\python.exe` 传给 `-PythonExe`。日志在仓库根 `.start-logs/gpt-sovits.log`。也可 `.\start-all.ps1 -TtsBackend minimal` 覆盖配置。启动横幅里 `TtsPython` 应指向 `tts\gpt-sovits-minimal\runtime\python.exe`。

**只启动 TTS：**

```bat
cd tts/gpt-sovits-minimal
go-api.bat
```

或：

```powershell
.\watch-api.ps1
```

默认绑定 **`127.0.0.1:8000`**。日志出现 `Application startup complete` / `Uvicorn running` 即就绪。

仅调试、不要自动重启时：

```powershell
conda activate gpt-sovits-minimal
python api_server.py --host 127.0.0.1 --port 8000 --voices_config config/voices.json --cnhubert_path ../gpt-sovits/GPT_SoVITS/pretrained_models/chinese-hubert-base --bert_path ../gpt-sovits/GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large
```

### 6. 对接桌面客户端

`config.json` 的 `tts`：

| 字段 | 值 |
|------|-----|
| `backend` | `minimal` |
| `minimal_host` | 本机 `127.0.0.1`；异机填 TTS 机 IP |
| `minimal_port` | `8000` |
| `voice` | `arona`（须与 `voices.json` 键名一致） |
| `refs` | 保持现有 `ref_audio/Arona/...`；客户端会自动加上 `../gpt-sovits/` 前缀 |

`host` / `port` 仍表示官方后端，切回 `backend: official` 时使用。不必改 29 条 `refs`。

客户端对 minimal 走 `POST /v1/audio/speech`，启动时不调用 `/set_gpt_weights`、`/set_refer_audio`，只 POST 一句极短合成做预热。

---

## 与官方后端切换

同一时间只跑一套：

1. 停掉当前 TTS（`start-all.ps1` 里 `stop gpt`，或关掉 watchdog 窗口）。
2. 改客户端 `tts.backend` 为 `official` 或 `minimal`。
3. 重新 `start gpt` 或再跑 `start-all.ps1`。

同卡双开会抢 Renderer 显存，不支持。要比对延迟时，先停一套再开另一套。RTT 用 [`frontend/AronaArchive_WindowsClient/scripts/test_tts_interval.py`](../../frontend/AronaArchive_WindowsClient/scripts/test_tts_interval.py)；首包 vs 生成完毕用 [`frontend/AronaArchive_WindowsClient/scripts/test_tts_first_packet.py`](../../frontend/AronaArchive_WindowsClient/scripts/test_tts_first_packet.py)。

---

## 异机

1. TTS 机完成本文档第 1–5 步，工作目录仍是该机上的 `tts/gpt-sovits-minimal/`，且能相对访问 `../gpt-sovits/`。
2. watchdog 默认听 `127.0.0.1`。局域网访问请改 `watch-api.ps1` 的 `-ListenAddress 0.0.0.0`，或直接：

   ```bash
   python api_server.py --host 0.0.0.0 --port 8000 --voices_config config/voices.json --cnhubert_path ../gpt-sovits/GPT_SoVITS/pretrained_models/chinese-hubert-base --bert_path ../gpt-sovits/GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large
   ```

3. 防火墙放行 TCP `8000`。
4. 客户端 `minimal_host` 填 TTS 机 IP。

不要把 API 暴露到公网；没有鉴权。

---

## 本期范围

只使用上游 **PyTorch** `api_server.py`。ONNX / TensorRT 导出与 `api_server_onnx.py` / `api_server_trt.py` 不在本部署路径内。

---

## 常见问题

| 现象 | 处理 |
|------|------|
| `start-all.ps1` 报缺少 `api_server.py` | 未把上游 clone 进本目录，见第 2 步 |
| 找不到 Python / conda 环境 | 先 `.\pack-runtime.ps1` 生成 `runtime\python.exe`；或创建 conda 环境 `gpt-sovits-minimal` / `.venv`，或设 `GPT_SOVITS_MINIMAL_PYTHON` |
| `start-all` 仍走 conda、横幅没有 runtime 路径 | 尚未打包 runtime。不要用官方 `tts\gpt-sovits\runtime\python.exe` |
| `Failed to load model: ... pretrained_eres2netv2w24s4ep4.ckpt` | 阿洛娜是 **v2**，不需要这份 v2Pro SV。上游默认总会加载。`launch_api.py` 在 ckpt 不存在时跳过 SV，不改上游源码。若用 v2Pro，把该 ckpt 放到 `../gpt-sovits/GPT_SoVITS/pretrained_models/sv/` 并设环境变量 `SV_MODEL_PATH` |
| HTTP 200 但只有 44 字节 WAV 头 | 推理异常被流式响应吞掉。常见是 `fast-langdetect` 找不到 `pretrained_models/fast_langdetect`。不要改上游 `langsegmenter.py`：它按 **进程工作目录** 找该路径。重启 `watch-api.ps1` 会把 `pretrained_models` junction 到官方预训练目录。看 `.start-logs/gpt-sovits.log` 的 `Inference error` |
| 客户端 TTS 超时 / 日志里 HuggingFace SSL 重试 | 迁到 `tts/` 后旧的 `pretrained_models` junction 可能仍指向仓库根 `gpt-sovits/`。重启 `watch-api.ps1` 会拆掉失效链接并指到 `tts/gpt-sovits/GPT_SoVITS/pretrained_models`。确认日志有 `Linked pretrained_models ->` 且不再访问 huggingface.co |
| `Loading models on cpu` | conda 环境是 CPU 版 PyTorch。`cu124` 最高只有 2.6，已装 `2.14.0+cpu` 时 `pip install ... cu124` 会跳过。先停掉 `watch-api.ps1`，再：`pip uninstall -y torch torchaudio` 然后 `pip install torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu126`。确认 `python -c "import torch; print(torch.__version__, torch.cuda.is_available())"` 为 `2.11.0+cu126 True` |
| 合成声线不对 / 找不到权重 | `voices.json` 路径相对本目录；官方权重文件名与路径一致 |
| 客户端有字幕无声音 | 确认走的是 `backend: minimal` 且客户端已更新（需能解析 data 长度为 0 的流式 WAV） |
| 切回官方后连不上 | `backend` 改回 `official`，确认 9880 在听且 `host`/`port` 指向官方 |
