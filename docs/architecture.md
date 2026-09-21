# 项目架构

仓库一级模块与入口见根目录 [`README.md`](../README.md)。下文为完整目录树。

```
arona-ai/
├── backend/                    # Python 后端服务（FastAPI + WebSocket）
│   ├── app/                    # 应用核心
│   │   ├── main.py             # 服务入口
│   │   ├── orchestrator.py     # 对话编排（关系决策 → 检索 → Planner/本地 → 生成 → 记忆抽取）
│   │   ├── model_loader.py     # GGUF 模型加载（llama-cpp-python）
│   │   ├── planner/            # 双模型 Planner（DeepSeek 意图卡 → Renderer）
│   │   ├── interact/           # 非对话手势（摸头等）；系统事件指令 + 白名单
│   │   ├── proactive/          # 主动事件（上线欢迎、空闲搭话、时刻照料、goal 回访、节日）
│   │   ├── relationship/       # 关系气候（信任/依赖/张力、决策）
│   │   ├── life/               # 生命循环（阿洛娜内状态、世界事件、墙钟 tick）
│   │   ├── knowledge.py        # 世界观知识 RAG
│   │   ├── conversation.py     # 多轮对话历史
│   │   ├── prompt.py           # Prompt / Renderer 消息组装
│   │   ├── input_filter.py     # ASR 脏文本过滤（入口兜底）
│   │   ├── embeddings.py       # 本地 BGE 嵌入（记忆 / 知识共用）
│   │   ├── protocol.py         # WebSocket 协议消息
│   │   ├── ws_handler.py       # WebSocket 处理
│   │   ├── config.py           # 配置加载
│   │   ├── logging_utils.py    # 日志工具
│   │   └── memory/             # 长期记忆（SQLite + FTS5 + Chroma + DeepSeek 抽取）
│   ├── scripts/                # 联调 / 灌库 / 测试脚本
│   ├── pack/                   # Windows 便携包模板（启动脚本 / README）
│   ├── dist/                   # 打包输出（gitignore）
│   │   └── AronaAI_Backend/    # Release 可执行目录
│   ├── data/                   # 记忆库、知识语料与向量库
│   │   ├── memory/             # memory.db + chroma + relationship.json + proactive.json + life.json
│   │   └── knowledge/          # 语料 corpus + chroma
│   ├── logs/                   # 后端运行日志
│   ├── config.example.yaml     # 配置模板
│   ├── requirements.txt
│   └── README.md
│
├── frontend/                   # 桌面客户端
│   └── AronaAI_Spine_WindowsClient/  # Windows 桌面客户端（Qt/C++）
│       ├── AronaAI_Spine_WindowsClient.sln  # 工程入口
│       ├── QtMainFile/         # 主界面、控制器、WebSocket 通信
│       │   └── main.cpp        # 程序入口
│       ├── QtUtils/            # 工具类（录音、语音识别、动画等）
│       ├── QHotkey/            # 全局快捷键支持
│       ├── spine-cpp/          # Spine 2D 动画运行时
│       ├── Assets/             # 资源文件（Spine 动画、UI 图片、字体）
│       ├── Config/             # 配置文件（资源路径为相对路径）
│       │   └── config.example.json  # 客户端配置模板
│       ├── dist/               # 编译后的可执行目录
│       │   ├── AronaAI_Client/          # 便携版（保留密钥）
│       │   └── AronaAI_Client_Release/  # 发布版（清除密钥）
│       ├── Dict/               # 词典文件
│       └── README.md
│
├── llm/                        # 语言模型相关（目录名沿用立项时的写法）
│   └── aronaLM/
│       └── finetune/           # Qwen3-1.7B QLoRA 微调（Unsloth）
│           ├── config/         # 训练 / 导出 / 推理配置
│           ├── training/       # 微调主脚本
│           │   └── train.py    # 训练入口
│           ├── inference/      # 交互式推理测试
│           ├── export/         # GGUF 导出
│           ├── data-process/   # 数据预处理
│           ├── start.bat       # Windows 一键训练
│           └── README.md
│
├── tts/                        # 所有语音合成后端（官方 / minimal 二选一）
│   ├── README.md               # TTS 总览
│   ├── gpt-sovits/             # 官方 GPT-SoVITS（需手动部署，或使用外部服务）
│   │   ├── GPT_SoVITS/         # 核心模型
│   │   ├── GPT_weights_v2/     # GPT 权重
│   │   │   └── ALuoNa_cn-e15.ckpt  # 阿洛娜 GPT 权重
│   │   ├── SoVITS_weights_v2/  # SoVITS 权重
│   │   │   └── ALuoNa_cn_e16_s256.pth    # 阿洛娜 SoVITS 权重
│   │   ├── api_v2.py           # API 服务
│   │   ├── watch-apiv2.ps1     # Windows：API 卡死/崩溃自动重启
│   │   ├── watch-apiv2.sh      # Linux：API 卡死/崩溃自动重启
│   │   ├── go-apiv2.bat        # Windows 一键启动 API（经 watchdog）
│   │   ├── go-apiv2.sh         # Linux 一键启动 API（经 watchdog）
│   │   └── ref_audio/          # 参考音频
│   │       └── Arona/
│   │           └── arona_academy_in_2.ogg   # 推荐的参考音频
│   └── gpt-sovits-minimal/     # GPT-SoVITS_minimal_inference（可选；与官方二选一）
│       ├── DEPLOY.md           # clone、独立 Python、voices.json
│       ├── go-api.bat / go-api.ps1
│       ├── watch-api.ps1       # 崩溃自动重启
│       ├── launch_api.py       # Arona 启动包装（不改上游源码）
│       ├── config/voices.json  # 阿洛娜 v2 权重路径（相对本目录）
│       └── api_server.py       # clone 上游后才有；默认 :8000
│
├── docs/                       # 项目文档
│   └── architecture.md         # 完整目录树
├── models/                     # 本地模型权重（需自行下载）
│   ├── README.md               # 下载与放置说明
│   ├── AronaLM-Renderer-V2.x/  # Renderer GGUF（默认双模型链路）
│   ├── AronaLM-Generator-V2.x/ # AronaLM GGUF（回落 / 本地单模型）
│   ├── bge-small-zh-v1.5/      # 知识 / 记忆嵌入模型
│   └── Qwen3-1.7B-unsloth-bnb-4bit/  # 微调基座（仅训练时需要）
├── assets/                     # 项目资源
├── start-all.ps1               # 本机一键启动
├── start-all.bat               # Windows 一键本机启动所有服务
├── pack-client.ps1             # 打包桌面客户端
├── pack-backend.ps1            # 打包后端 Windows 便携目录
├── pack-tts.ps1                # 打包 TTS 脚本与参考音频
└── setup-backend-pack-env.ps1  # 创建后端打包用最小 conda 环境
```

后端模块职责见 [`backend/README.md`](../backend/README.md)；模型放置见 [`models/README.md`](../models/README.md)。
