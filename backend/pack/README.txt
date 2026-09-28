AronaArchive 后端 {{VERSION}}（Windows x64 便携包）

本目录自带 Python 运行时，不需要安装 conda 或全局 Python。

系统要求
--------
- Windows 10 / 11 x64
- 若无法启动，先安装 Microsoft Visual C++ 运行库（运行 vc_redist.x64.exe）
- 若启用 Arona-Renderer 的 GPU 层，需要 NVIDIA 显卡与较新的 Game Ready / Studio 驱动
  （包内 llama-cpp-python 为 CUDA 构建）

快速开始
--------
1. 编辑 config.yaml，把 planner.api_key 与 memory.extractor.api_key
   中的 YOUR_DEEPSEEK_API_KEY 换成你的 DeepSeek Key。
2. 放置嵌入模型（若 zip 已包含 bge-small-zh-v1.5 可跳过）：

     models/bge-small-zh-v1.5/

   从 Hugging Face 或 ModelScope 下载 BAAI/bge-small-zh-v1.5。
   没有 BGE 时后端仍可启动（Planner + SQLite FTS）；向量记忆 / 知识 RAG
   会关闭，直到该目录就位。

3. 可选：启用 Arona-Renderer
   - 从 https://www.modelscope.cn/models/xiahy456/AronaLM-Renderer-V2.4
     下载 AronaLM-Renderer-V2.4 Q4_K_M.gguf
   - 放到：
     models/AronaLM-Renderer-V2.4/AronaLM-Renderer-V2.4.Q4_K_M.gguf
   - 在 config.yaml 将 model.enabled 设为 true

4. 双击 AronaArchive_Backend.bat
5. 健康检查：http://127.0.0.1:20456/health
6. 桌面客户端 websocket_url 填：
     ws://127.0.0.1:20456/ws
   （若客户端在另一台机器，改为 ws://<本机IP>:20456/ws，
    并把 config.yaml 的 server.host 设为 0.0.0.0）

不要把新版本直接覆盖正在用的目录，除非你不需要保留记忆。运行时数据在：

  data/memory/memory.db
  data/memory/chroma/
  data/memory/relationship.json
  data/memory/proactive.json
  logs/

本 zip 不含 GGUF，也不含真实 API Key。
项目主页：https://github.com/xiahy456/AronaArchive
