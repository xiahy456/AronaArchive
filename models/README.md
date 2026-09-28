# 模型 / Models

本目录存放 AronaArchive 运行与微调所需的**本地模型权重**（已在 `.gitignore` 中忽略，需自行下载放置）。

This directory holds local model weights for AronaArchive runtime and finetuning (gitignored — download and place them yourself).

---

## 目录结构 / Layout

```
models/
├── AronaLM-Renderer-V2.x/              # Renderer GGUF（双模型链路）
│   └── AronaLM-Renderer-V2.x.Q4_K_M.gguf
├── AronaLM-Generator-V2.x/                # 可选：本地单模型 / Planner 回落
│   └── AronaLM-Generator-V2.x.Q4_K_M.gguf
├── bge-small-zh-v1.5/                  # 知识 / 记忆嵌入（按需）
├── Qwen3-1.7B-unsloth-bnb-4bit/        # 微调基座（仅训练时需要）
└── Qwen3-1.7B/                         # 导出 GGUF 用 16bit 基座（仅导出时需要）
```

> TTS 权重放在 `tts/gpt-sovits/GPT_weights_v2/`、`tts/gpt-sovits/SoVITS_weights_v2/`，不放在本目录。

---

## 后端推理 / Backend Inference

启用Arona-Renderer渲染修正时，对话默认走 **Planner（DeepSeek）→ 意图卡 → Renderer（AronaLM-Renderer-V2.x）**；`llama-cpp-python` 加载本目录下的 GGUF。

| 模型 | 路径 | 用途 | 配置项 |
|------|------|------|--------|
| **AronaLM-Renderer-V2.x** | `AronaLM-Renderer-V2.x/AronaLM-Renderer-V2.x.Q4_K_M.gguf` | 按意图卡渲染回复（默认双模型链路） | `backend/config.yaml` → `model.gguf_path` |
| **AronaLM-Generator-V2.x** | `AronaLM-Generator-V2.x/AronaLM-Generator-V2.x.Q4_K_M.gguf` | 本地单模型 / Planner 关闭或失败时回落 | 同上（注释中的备用路径） |

- Renderer 下载：[xiahy456/AronaLM-Renderer-V2.4](https://www.modelscope.cn/models/xiahy456/AronaLM-Renderer-V2.4)（ModelScope）
- Generator 下载（可选）：[xiahy456/AronaLM-Generator-V2.0](https://www.modelscope.cn/models/xiahy456/AronaLM-Generator-V2.1)
- 示例默认路径：`../models/AronaLM-Renderer-V2.4/AronaLM-Renderer-V2.4.Q4_K_M.gguf`（相对 `backend/`）
- 仅跑单模型时：将 `model.gguf_path` 改为 ../models/AronaLM-Generator-V2.0/AronaLM-Generator-V2.0.Q4_K_M.gguf，并设 `planner.enabled: false`（或不填 Planner API Key）

---

## 知识 / 记忆嵌入（按需） / Embeddings (Optional)

| 模型 | 路径 | 用途 | 配置项 |
|------|------|------|--------|
| **BGE-small-zh-v1.5** | `bge-small-zh-v1.5/` | 世界观 RAG 与长期记忆向量检索（知识 / 记忆共用） | `knowledge.embedding_model_path` |

- 启用知识库：`knowledge.enabled: true`，并先执行 `backend/scripts/ingest_knowledge.py` 灌库
- 记忆向量检索也会加载同一本地 BGE（路径与 knowledge 配置共用）
- 默认路径：`../models/bge-small-zh-v1.5`（相对 `backend/`）
- 可从 Hugging Face / ModelScope 搜索 `BAAI/bge-small-zh-v1.5` 下载完整目录到此处

---

## 微调基座（仅训练） / Finetune Bases (Training Only)

自行用 `llm/aronaLM/finetune` 做 QLoRA 时需要：

| 模型 | 路径 | 用途 |
|------|------|------|
| **Qwen3-1.7B-unsloth-bnb-4bit** | `Qwen3-1.7B-unsloth-bnb-4bit/` | Unsloth 4bit 训练基座 |
| **Qwen3-1.7B** | `Qwen3-1.7B/` | 合并 LoRA 后导出 GGUF 的 16bit 基座 |

- 配置见 `llm/aronaLM/finetune/config/`（`name_or_path` / `gguf_base_model`）
- 详细步骤见 [`llm/aronaLM/finetune/README.md`](../llm/aronaLM/finetune/README.md)
- 只跑后端、不微调时**不必**下载这两项

---

## 非本地模型 / External (Cloud) Models

以下不放入本目录，通过 API Key 配置：

| 服务 | 用途 | 配置位置 |
|------|------|----------|
| **DeepSeek** | Planner 意图草稿；长期记忆异步抽取（无 Key 时抽取降级为正则） | `planner.*` / `memory.extractor.*` |
| **腾讯云 ASR** | 桌面端语音识别 | 客户端 `config.json` → `tencent_speech_recognizer` |

---

## 最小可运行集合 / Minimum to Run Backend

双模型链路至少需要：

```
models/AronaLM-Renderer-V2.4/AronaLM-Renderer-V2.4.Q4_K_M.gguf
```

并配置 `planner.api_key`（DeepSeek）。不填 Key 或关闭 Planner 时，改为放置并指向 `AronaLM-Generator-V2.0` GGUF。

启用知识 / 记忆向量检索时再补上 `bge-small-zh-v1.5/`；启用语音合成时把 GPT-SoVITS 权重放到 `tts/gpt-sovits/`，步骤见 [`tts/README.md`](../tts/README.md)。

Windows 便携后端（`AronaArchive_Backend_v*_x64.zip`）把上述路径放到**解压目录内的 `models/`**，不再使用仓库里的 `../models/`。包内 `config.yaml` 已改成 `models/bge-small-zh-v1.5` 与 `models/AronaLM-Renderer-V2.4/...`。GGUF 默认不打进 zip，需自行下载后放入。
