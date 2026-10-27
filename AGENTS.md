# AGENTS.md

本仓库是「阿洛娜档案」：以《蔚蓝档案》角色阿洛娜为原型的桌面自循环 AI。用户（老师）是进入她世界的事件，不是每一轮都必须得到回复的聊天对象。

## 布局

| 路径 | 职责 |
|------|------|
| `backend/app/` | FastAPI + WebSocket。入口 `main.py`，编排 `orchestrator.py` |
| `backend/app/life/` | 内状态、墙钟、冲动、心事、自己的一天、瞥屏、可打断的电脑操作 |
| `backend/app/relationship/` | 信任 / 依赖 / 张力、分类、气候分区与姿态 |
| `backend/app/planner/` | DeepSeek 意图卡。关闭或失败时回落本地单模型 |
| `backend/app/proactive/` | 欢迎、搭话、照料、回访、节日。只产生冲动，不自己开口 |
| `backend/app/memory/` | 老师的长期事实：SQLite + FTS5 + Chroma |
| `backend/app/protocol.py` | 与 Qt 客户端对齐的 WebSocket 消息 |
| `backend/scripts/` | 单元断言与联调。工作目录必须是 `backend/` |
| `frontend/AronaArchive_WindowsClient/` | Qt/C++ + Spine。工程入口 `AronaArchive_WindowsClient.sln` |
| `tts/` | GPT-SoVITS。官方与 minimal 二选一 |
| `models/` | 本地权重，不入库 |

默认 WebSocket：`ws://127.0.0.1:20456/ws`。健康检查：`http://127.0.0.1:20456/health`。源码启动的工作目录是 `backend/`，命令是 `python -m app.main`。conda 环境名是 `shittim-chest`。

## 约定

- 本项目不支持使用过于冗杂的死逻辑来追求轻量、快速但不成熟、勉强的实现。请勿为减少项目大小而引入过多的功能耦合，请勿使用正则来应对一切问题而不考虑 LLM 调用。

- 后端的 `proactive` 模块即将从系统中解耦，开发时不要与它们耦合。

## 不要碰

- 不要提交 `backend/config.yaml`、客户端 `Config/config.json`、API Key、腾讯云密钥、`server.token`。模板是 `config.example.yaml` 与 `config.example.json`。
- 不要提交 `models/` 权重、`backend/data/`、`backend/logs/`、`backend/dist/`、训练输出和 `__pycache__`。
- 不要把令牌写进 WebSocket URL。`server.public: true` 或非本机 `host` 时，空令牌和占位符 `YOUR_ACCESS_TOKEN` 必须拒绝启动。
- `tts/gpt-sovits/` 与 minimal 上游源码不在版本库里。只改本仓库跟踪的启动脚本、`launch_api.py`、`voices.json` 和文档。
- 打包脚本（`pack-*.ps1`）打出来的目录不含真实 Key，也不含 GGUF。不要为了方便把本机密钥打进发布包。

## 代码约定

新的 Python 文件沿用仓库现有的 GPL-3.0-or-later 文件头和 `from __future__ import annotations`。第三方代码许可证与 GPLv3 不同，见 [`NOTICE.md`](NOTICE.md)，不要把那些目录改成项目许可证头。

配置从 `backend/app/config.py` 读取，新增字段同时写入 `config.example.yaml` 和 `backend/README.md`。路径相对 `backend/` 解析。

测试是 `backend/scripts/test_*_unit.py` 里的普通脚本，不是 pytest 套件。脚本把 `backend/` 插入 `sys.path`，用临时目录代替 `data/memory/`。

客户端是 Qt 6.5.3（`msvc2019_64`）加 v143 平台工具集。协议和资源路径保持与现有 `config.example.json` 一致。
