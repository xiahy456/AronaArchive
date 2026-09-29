# NOTICE - 许可证与第三方组件声明

## 项目许可证

**AronaArchive - 自循环 AI** 的原创源代码与文档采用 [GNU General Public License v3.0 or later (GPL-3.0-or-later)](LICENSE) 授权。

各原创源文件顶部均带有 GPL-3.0-or-later 版权头与 `SPDX-License-Identifier: GPL-3.0-or-later` 标识。

## 第三方组件

本仓库包含以下第三方代码，其许可证与 GPL-3.0-or-later 不同，**不适用 GPLv3**，按各自原始许可证授权：

### 1. Spine Runtimes

- **路径**：`frontend/AronaArchive_WindowsClient/spine-cpp/`（不含 `Qt*` 前缀的文件）
- **版权方**：Esoteric Software LLC
- **许可证**：Spine Runtimes License Agreement
- **链接**：https://esotericsoftware.com/spine-editor-license
- **说明**：Spine 2D 动画运行时。仓库中 `Qt*` 前缀的文件（如 `QtSpineManager`、`QtTextureLoader`、`QtSkeletonLoader`）为项目作者编写的 Qt 封装，属于项目原创代码，适用 GPL-3.0-or-later。

### 2. QHotkey

- **路径**：`frontend/AronaArchive_WindowsClient/QHotkey/`
- **版权方**：QHotkey 项目作者
- **许可证**：按其自身许可证（详见目录内文件）
- **说明**：第三方 Qt 全局快捷键库，整个目录保持原样，不加项目许可证头。

### 3. 其它外部依赖（不纳入仓库版权头变更范围）

以下依赖以外部形式引入，不修改其许可证，不纳入仓库版权头变更范围：

- **Qt** — 跨平台 GUI 框架，https://www.qt.io/
- **ChromaDB** — 向量数据库，https://www.trychroma.com/
- **GPT-SoVITS / GPT-SoVITS_minimal_inference** — 语音合成，https://github.com/RVC-Boss/GPT-SoVITS
- **llama.cpp / llama-cpp-python** — 本地 GGUF 推理，https://github.com/ggml-org/llama.cpp
- **bge-small-zh-v1.5** — 文本嵌入模型，https://huggingface.co/BAAI/bge-small-zh-v1.5
- **Napcat** — QQ 协议框架，https://github.com/NapNeko/NapCatQQ
- **DeepSeek API** — 外部 API 服务，https://www.deepseek.com/
- **腾讯云语音识别** — 在线语音识别服务，https://cloud.tencent.com/product/asr

## 混合授权边界

GPL-3.0-or-later **仅适用于本项目原创的源代码与文档**。上述第三方代码保留其原始许可证与版权声明，不因纳入本仓库而变更授权方式。
