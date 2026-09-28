# GPT-SoVITS 目录与部署

本目录是 AronaArchive 的 **官方 TTS 服务端**。桌面客户端在 `tts.backend` 为 `official`（缺省）时通过 HTTP 调用 `api_v2.py`（默认 `127.0.0.1:9880`）合成阿洛娜语音；后端对话服务不经过这里。

可选加速后端见 [`../gpt-sovits-minimal/DEPLOY.md`](../gpt-sovits-minimal/DEPLOY.md)。`start-all.ps1` 根据客户端 `tts.backend` **只启动一套**，不要同卡同时跑官方与 minimal。

仓库 `.gitignore` **不提交** GPT-SoVITS 本体、权重与 `runtime/`。clone 后这里通常只有启动脚本和本文件，需要自行补齐官方程序、预训练模型、阿洛娜微调权重和参考音频。

**终端用户**请先看 TTS 总览 [`../README.md`](../README.md)：默认官方引擎，把 Windows 整合包解压进本目录，再放入两个阿洛娜权重，然后 `start-all`。维护者打包：仓库根 `.\pack-tts.ps1`。

上游说明见同目录 [`README.md`](README.md)。项目总览见仓库根目录 [`README.md`](../../README.md)。

---

## 主要目录树

AronaArchive 实际用到的是 **v2 推理 API**，不必展开训练 / WebUI / UVR5 全树。完整上游结构以官方 README 为准。

```
gpt-sovits/
├── DEPLOY.md                      # 本文件
├── go-apiv2.bat                   # Windows 推荐入口（经 watchdog）
├── go-apiv2.sh                    # Linux 推荐入口（经 watchdog）
├── watch-apiv2.ps1                # Windows：崩溃 / Bert·T2S 卡死自动重启
├── watch-apiv2.sh                 # Linux：同上
├── api_v2.py                      # FastAPI 推理服务（/tts、切权重）
├── config.py                      # 设备、半精度、默认端口 9880
├── webui.py                       # 官方 WebUI（训练 / 调试用，客户端不走这条）
│
├── GPT_SoVITS/                    # 核心代码与预训练
│   ├── configs/tts_infer.yaml     # API 默认配置（custom 段指向阿洛娜 v2 权重）
│   ├── pretrained_models/         # 官方基座（推理必需）
│   │   ├── chinese-hubert-base/
│   │   ├── chinese-roberta-wwm-ext-large/
│   │   ├── gsv-v2final-pretrained/
│   │   └── s1*.ckpt / s2*.pth     # v1 / v3 基座，本项目可忽略
│   └── TTS_infer_pack/            # 推理管线
│
├── GPT_weights_v2/                # 阿洛娜 GPT 微调（T2S）
│   └── ALuoNa_cn-e15.ckpt         # 推荐
├── SoVITS_weights_v2/             # 阿洛娜 SoVITS 微调（声码器）
│   └── ALuoNa_cn_e16_s256.pth     # 推荐
├── ref_audio/Arona/
│   └── arona_academy_in_2.ogg     # 推荐参考音频
│
├── runtime/                       # Windows 整合包内嵌 Python（优先用这个）
│   └── python.exe
├── tools/                         # UVR5 / ASR 等（仅训练数据准备需要）
├── logs/                          # 独立启动时的 API 日志
└── Docker/                        # 官方镜像构建（可选）
```

权重不要放到仓库 `models/`。`models/` 只放 AronaLM / BGE，见 [`models/README.md`](../models/README.md)。

`GPT_weights/`、`GPT_weights_v3/`、`SoVITS_weights_v3/` 等是上游按版本分目录的习惯；**本项目客户端与 `tts_infer.yaml` 的 `custom` 段都指向 v2**。

---

## 环境要求

| 项 | 建议 |
|----|------|
| 系统 | Windows 10/11（与 `start-all.ps1`、整合包一致）；Linux 可作独立 TTS 机 |
| GPU | NVIDIA + CUDA；CPU 能跑但延迟高，不适合桌面实时口播 |
| 显存 | 建议 ≥ 8 GB。8 GB 档把客户端 `tts.parallel_infer` 设为 `false` |
| Python | Windows 整合包用 `runtime/python.exe`；否则 Python 3.9 / 3.10 + 官方 `requirements.txt` |
| 依赖 | FFmpeg（Windows 包内已有 `ffmpeg.exe`；Linux：`sudo apt install ffmpeg` 或 `conda install ffmpeg`） |

半精度由 `config.py` / 环境变量 `is_half` 控制。Pascal 老卡（1060/1070/1080 等）会自动关掉半精度。SSL 特征目录生成异常时，把 `is_half` 改成与显卡匹配的值再试。

---

## 部署步骤

### 1. 放入官方 GPT-SoVITS

任选一种，**解压 / clone 到本目录**（使 `api_v2.py` 位于 `tts/gpt-sovits/api_v2.py`）：

- **Windows（推荐）**：下载 [官方整合包](https://huggingface.co/lj1995/GPT-SoVITS-windows-package)，解压后把内容放到 `tts/gpt-sovits/`。国内用户也可走[语雀镜像](https://www.yuque.com/baicaigongchang1145haoyuangong/ib3g1e/dkxgpiy9zb96hob4#KTvnO)。
- **从源码安装**：见上游 README（conda 环境 `GPTSoVits` + `bash install.sh` 或 `pip install -r requirements.txt`）。预训练放到 `GPT_SoVITS/pretrained_models/`，见 [GPT-SoVITS Models](https://huggingface.co/lj1995/GPT-SoVITS)。

完成后应能看到 `api_v2.py`、`GPT_SoVITS/pretrained_models/chinese-hubert-base` 和 `chinese-roberta-wwm-ext-large`。

仓库里的 `go-apiv2.bat` / `go-apiv2.sh` 依赖同目录的 `watch-apiv2.ps1` / `watch-apiv2.sh`。若只有 `go-apiv2`、没有 watchdog，可直接 `python api_v2.py`（无自动重启）。

### 2. 放置阿洛娜权重与参考音频

```
gpt-sovits/
├── GPT_weights_v2/ALuoNa_cn-e15.ckpt
├── SoVITS_weights_v2/ALuoNa_cn_e16_s256.pth
└── ref_audio/Arona/arona_academy_in_2.ogg
```

路径一律相对 **GPT-SoVITS 进程工作目录**（即 `tts/gpt-sovits/`），不要写成客户端本机路径。

### 3. 启动 API

**本机一键（Windows）**：在仓库根目录执行 `.\start-all.ps1`。它会并行拉起后端与 GPT-SoVITS watchdog，日志在 `.start-logs/gpt-sovits.log`。

**只启动 TTS：**

```bash
cd tts/gpt-sovits
# Windows
go-apiv2.bat
# Linux
chmod +x go-apiv2.sh && ./go-apiv2.sh
```

`go-apiv2` 会在推理停在「提取文本 Bert 特征 / 预测语义 Token」且日志不再前进时杀进程并重启（默认卡住 60s、重启冷却 90s）。仅调试、不要自动重启时：

```bash
# Windows 整合包
runtime\python.exe api_v2.py
# 或 PATH 上的 python
python api_v2.py
```

默认绑定 **`127.0.0.1:9880`**。日志出现 `startup complete` / `Uvicorn running` 即就绪。

### 4. 对接桌面客户端

复制 `frontend/AronaArchive_WindowsClient/Config/config.example.json` 为 `config.json`，至少核对 `tts`：

| 字段 | 本项目推荐值 |
|------|----------------|
| `backend` | 缺省 / `official`。切加速后端时改为 `minimal`（见 [`../gpt-sovits-minimal/DEPLOY.md`](../gpt-sovits-minimal/DEPLOY.md)） |
| `host` | 本机 `127.0.0.1`；异机填官方 TTS 机 IP |
| `port` | `9880` |
| `minimal_host` / `minimal_port` | 仅 `backend=minimal` 时使用，默认 `127.0.0.1` / `8000` |
| `voice` | 仅 minimal：`voices.json` 条目名，默认 `arona` |
| `gpt_path` | `GPT_weights_v2/ALuoNa_cn-e15.ckpt` |
| `sovits_path` | `SoVITS_weights_v2/ALuoNa_cn_e16_s256.pth` |
| `ref_audio_path` | `ref_audio/Arona/arona_academy_in_2.ogg` |
| `prompt_text` / `prompt_lang` | 上文文案 / `zh` |
| `parallel_infer` | 8 GB 显卡设 `false` |
| `reload_weights_on_start` | 默认 `false`。为 `true` 时客户端启动会再切 GPT/SoVITS 权重 |
| `request_timeout_ms` | `45000`（超时仍显示字幕，不卡 UI） |

客户端启动时默认**不再**请求 `/set_gpt_weights`、`/set_sovits_weights`（权重已由 `tts_infer.yaml` 加载），而是 `GET /set_refer_audio` 再 POST 一句极短 `/tts` 预热 prompt cache，随后对话才 POST `/tts`。需要热切权重时把 `reload_weights_on_start` 设为 `true`。完整字段见 [`frontend/AronaArchive_WindowsClient/README.md`](../../frontend/AronaArchive_WindowsClient/README.md)。

---

## 部署方式建议

### 同机（默认）

后端、TTS、Qt 客户端都在一台 Windows 机器上时，用 `start-all.ps1`。Python 优先 `tts/gpt-sovits/runtime/python.exe`，没有再退回 PATH 上的 `python`。

### 异机（TTS 单独一台）

适合把 GPU 推理拆到另一台机器：

1. 在 TTS 机完成本文档第 1–2 步，工作目录仍是该机上的 `tts/gpt-sovits/`。
2. **必须改绑定地址**。watchdog 当前按无参数启动 `api_v2.py`（只听 `127.0.0.1`），局域网访问请直接：

   ```bash
   python api_v2.py -a 0.0.0.0 -p 9880
   ```

   或改 watchdog 里的启动命令，加上 `-a 0.0.0.0`。
3. 防火墙放行 TCP `9880`。
4. 客户端 `tts.host` 填 TTS 机 IP，`gpt_path` / `sovits_path` / `ref_audio_path` 仍是 **TTS 机上相对 `tts/gpt-sovits/` 的路径**。

不要把 API 暴露到公网；没有鉴权。

### Docker（可选）

上游提供 `docker-compose.yaml`，映射 `9880` 及 WebUI 端口。镜像更新慢，标签需自己核对 [Docker Hub](https://hub.docker.com/r/breakstring/gpt-sovits)。Windows Docker Desktop 请加大 `shm_size`（compose 默认 16G）。AronaArchive 日常路径仍是本机 `go-apiv2` / `start-all.ps1`，不必为桌面端单独上容器。

---

## 自检

服务起来后，在 TTS 机：

```bash
# 健康：能连上端口即可；切权重
curl "http://127.0.0.1:9880/set_gpt_weights?weights_path=GPT_weights_v2/ALuoNa_cn-e15.ckpt"
curl "http://127.0.0.1:9880/set_sovits_weights?weights_path=SoVITS_weights_v2/ALuoNa_cn_e16_s256.pth"
```

仓库内压测（会按生产同款参数连打几句）：

```bash
cd backend
python scripts/test_tts_hang.py --host 127.0.0.1 --port 9880
```

---

## 常见问题

| 现象 | 处理 |
|------|------|
| `start-all.ps1` 报缺少 `api_v2.py` / `watch-apiv2.ps1` | 官方程序未解压进本目录，或缺少 watchdog 脚本 |
| 找不到 `runtime\python.exe` 且 PATH 无 python | 使用整合包，或把 conda/官方环境的 `python` 加入 PATH |
| 客户端连不上 TTS | 确认 9880 在听；异机须 `-a 0.0.0.0` 且 `tts.host` 为 TTS 机 IP |
| 合成声线不对 / 报权重不存在 | 权重文件名与 `config.json`、`tts_infer.yaml` 一致；路径相对 TTS 工作目录 |
| 8 GB 显卡 OOM 或极慢 | `parallel_infer: false`；确认 `is_half` 为 true（老卡除外） |
| 请求卡住、日志停在 Bert / 语义 Token | 用 `go-apiv2` 让 watchdog 重启；可调 `StallSec`（`start-all.ps1` 的 `-TtsStallSec`） |
| 超时但字幕仍出 | 正常：`request_timeout_ms` 只保 UI，不代表 API 已死 |

本项目不需要为日常口播启动 `webui.py`，也不需要 v3/v4 权重。训练自己的音色时再开 WebUI，流程见上游 README。
