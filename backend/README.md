# AronaArchive Backend

非交互式桌面AI 的本地后端：FastAPI WebSocket + AronaLM（llama-cpp）+ 关系气候决策 + SQLite 记忆 + DeepSeek 异步抽取 + 向量知识 RAG。

对话默认走 **关系决策 → Planner（DeepSeek）→ 意图卡 → Renderer（AronaLM）**；Planner 关闭或失败时回落本地单模型路径。决策层可以选择沉默，不调用 LLM。

## 模块详解


| 模块            | 路径                                       | 功能描述                                                      |
| ------------- | ---------------------------------------- | --------------------------------------------------------- |
| **服务入口**      | `app/main.py`                            | FastAPI 应用、健康检查、WebSocket 路由；启动时加载关系引擎                    |
| **对话编排**      | `app/orchestrator.py`                    | 老师输入先快照内状态再进循环；关系决策 → Planner（含【阿洛娜此刻】）或本地 → 循环认 `life_action` → 生成 / 空 ack |
| **关系气候**      | `app/relationship/`                      | 信任/依赖/张力状态、事件 Δ 表、规则分类、气候分区与行动策略、JSON 落盘                  |
| **生命循环**      | `app/life/`                              | 阿洛娜内状态、自己的一天、匣外瞥屏与可打断的电脑操作；墙钟 tick 无冲动只换脸 |
| **主动事件**      | `app/proactive/`                         | 上线欢迎、空闲轻搭话、吃饭与睡觉照料、goal 回访、节日问候、同轮补充；连接表 + 调度落盘           |
| **Planner**   | `app/planner/`                           | DeepSeek 意图卡、情感白名单；只读气候档位与姿态，不见 A/B/C 数字                  |
| **模型加载**      | `app/model_loader.py`                    | llama-cpp-python 加载 GGUF；启动时用 Renderer prompt 预热并复用前缀 KV  |
| **WebSocket** | `app/ws_handler.py`                      | 会话连接、上线欢迎、消息分发、ASR 过滤接入                                   |
| **非对话交互**    | `app/interact/`                          | 摸头等手势白名单与系统事件指令；编排走 `handle_interact`                       |
| **输入过滤**      | `app/input_filter.py`                    | 丢弃空串 / 腾讯云 ASR 错误模板，避免误触发对话                               |
| **协议**        | `app/protocol.py`                        | 客户端/服务端消息类型定义                                             |
| **对话历史**      | `app/conversation.py`                    | 多轮历史管理与截断                                                 |
| **知识 RAG**    | `app/knowledge.py`                       | ChromaDB 检索世界观知识                                          |
| **嵌入**        | `app/embeddings.py`                      | 本地 BGE 编码器（记忆 / 知识共用）                                     |
| **记忆存储**      | `app/memory/store.py`                    | SQLite + FTS5 + Chroma 混合长期记忆                             |
| **记忆抽取**      | `app/memory/extractor.py`                | DeepSeek 异步抽取（失败走正则）                                      |
| **Prompt**    | `app/prompt.py`、`app/planner/prompts.py` | Renderer / 本地回落消息组装；Planner system + user 模板。部件清单见下节      |




## 快速开始

终端用户请从 [Releases](https://github.com/xiahy456/AronaArchive/releases) 下载 `AronaArchive_Backend_v*_x64.zip`，解压后按包内 `README.txt` 配置并双击 `AronaArchive_Backend.bat`。不需要 conda / Python。维护者打包见下文「便携发布包」。

### 从源码启动

需要 conda 环境 `shittim-chest`（按 `requirements.txt` 安装依赖；若已装过 llama-cpp-python，一般不必重装）。

**1. 配置 `config.yaml`**

```bash
# 在 backend/ 目录下
copy config.example.yaml config.yaml   # Windows
cp config.example.yaml config.yaml   # Linux / macOS
```

按需填写：
- `model.enabled`：是否启用 Arona-Renderer 渲染修正；`true` 启用，`false` 不启用，只使用 Planner 草稿
- `model.gguf_path`：默认为 `AronaLM-Renderer-V2.4`，仅当启用 Arona-Renderer 时才有作用，若未启用则可以忽略
- `planner.enabled` / `planner.api_key`：默认开启双模型；填写 DeepSeek API Key。不填 Key 或关闭 `enabled` 则回落本地单模型
- `memory.extractor.api_key`：DeepSeek API Key（可选；不填则记忆抽取走正则降级）
- `knowledge.enabled`：是否启用世界观 RAG 知识库（默认 `false`，启用前请先灌库，相关指导见下文「世界观知识 RAG」）

**2. 放置模型**

如果启用了 Arona-Renderer 渲染修正，则需要放置 AronaLM-Renderer 模型文件；如果未启用则不需要放置。模型路径相对 `backend/`（示例为 `../models/...`），详见 [`models/README.md`](../models/README.md)。

**3. 启动服务**

工作目录必须是 `backend/`：

```bash
conda activate shittim-chest
cd backend
pip install -r requirements.txt   # 若缺 fastapi/httpx/chromadb 等再装；无需重装 llama-cpp-python
python -m app.main
# 或
uvicorn app.main:app --host 127.0.0.1 --port 20456
```

默认 WebSocket：`ws://127.0.0.1:20456/ws`（与 Qt 客户端一致）。健康检查：`http://127.0.0.1:20456/health`。

## 便携发布包（Windows x64）

给 GitHub Release 打的是解压即用的目录，**不是** PyInstaller 单文件。相对路径仍相对包根解析（`ARONA_BACKEND_DIR` 可覆盖）。

维护者在一台已能跑后端的 Windows 机器上：

```powershell
# 1) 最小运行时 conda 环境（CPU torch + CUDA llama-cpp；不要用含 Unsloth 的训练环境）
.\setup-backend-pack-env.ps1

# 2) 打目录 + zip（可选带上本机 BGE，并预灌知识库）
.\pack-backend.ps1
.\pack-backend.ps1 -IncludeBge -IngestKnowledge
```

产物：

- 目录：`backend/dist/AronaArchive_Backend/`（已 gitignore）
- zip：`release/AronaArchive_Backend_v<version>_x64.zip`

zip **不含** GGUF、**不含** 本机 `config.yaml` 里的真实 Key。用户解压后编辑包内 `config.yaml`，按 `models/README.txt` 放置 BGE / Renderer。启动：`AronaArchive_Backend.bat`。

## 联调脚本

```bash
python scripts/smoke_ws.py
python scripts/smoke_crisis_path.py        # 危机通路联调（真实 Planner；临时记忆库）
# 或对已启动的后端：python scripts/smoke_crisis_path.py --url ws://127.0.0.1:20456/ws
python scripts/test_input_filter.py        # ASR / 空串脏文本过滤断言
python scripts/test_taxonomy_unit.py       # P0 词汇表契约（不加载 GGUF）
python scripts/test_crisis_unit.py         # 危机检测 / 禁静音 / 禁抽取 / 跳过 Renderer
python scripts/test_episode_memory_unit.py # 情景/情绪记忆分栏、同日合并、抽取触发
python scripts/test_relationship_unit.py   # 关系公式 / 分区 / 分类 / 沉默（不加载 GGUF）
python scripts/test_life_unit.py           # 生命循环内状态 / 冲动效应器 / 墙钟缓回 / 快照与 interrupt（不加载 GGUF）
python scripts/test_skip_ack.py            # 沉默/拒绝仍发空 chat_response，并提交循环动作（不加载 GGUF）
python scripts/test_welcome_unit.py        # 欢迎时段与指令（不加载 GGUF）
python scripts/test_proactive_unit.py      # 冲动入队 / 听写不冻结 / 空闲照料回访闸门（不加载 GGUF）
python scripts/test_image_input_unit.py   # 截图解析 / 日志脱敏 / logs 目录保留最近 8 张
python scripts/test_interact_unit.py       # 非对话 interact 白名单 / 摸头指令 / touch Δ / reply_ok
python scripts/test_affect_unit.py         # 情感质量评测夹具 / 规则 / judge 解析（不调 API）
python scripts/eval_affect.py              # Planner 草稿情感质量：empathy / sycophancy / repair / boundary（需 planner Key；不达阈值非 0）
python scripts/eval_affect.py --json-out logs/affect_eval.json
```

确保服务已启动后再跑 `smoke_ws.py`。脚本会发送 `ping` / `chat` / `interact`，并打印响应。

## 对话链路

```
后端
├── planner可用
|   ├── 本地 AronaLM-Renderer-V2.x 模型可用
│   │   └── 使用双模型链路 Planner（DeepSeek）→ Renderer（AronaLM-Renderer-V2.x）
│   └── 本地 AronaLM-Renderer-V2.x 模型不可用
│       └── 使用 Planner 直接生成回复（默认）
└── planner不可用
    └── 使用本地单模型 AronaLM-Generator-V2.x 或 AronaLM-Renderer-V2.x，若无则无法回复
```

每条用户 `chat` / `transcript` / `interact` 先作为世界事件进入生命循环（**先快照内状态再 apply**），再过关系层决定是否开口：

```text
老师输入
  → 快照 InnerState（发呆 / 想事 / 休息 / 看老师）→ apply teacher_spoke|transcript|touched
  → 规则分类 user_act
  → 查表 Δ 更新信任 / 依赖 / 张力
  → 气候分区 + 姿态（action / stance / must_not）
  → silence / refuse：不调 Planner；提交 life_action=continue_activity；发空 content 的 chat_response
  → speak：本轮 query embedding 只算一次 → 记忆/知识检索（知识近义命中可复用）
       → Planner（用户栏【阿洛娜此刻】在【老师本轮消息】之前）或本地
       → reply_ok=false：提交 continue_activity 或 emotion_only，发空 chat_response
       → reply_ok=true：Renderer（复用 system 前缀 KV）→ 非空 chat_response（life_action=speak）
  → 规则为 other 且 Planner 给出非 other（且非 crisis / touch）时，按 Planner 的 user_act 补一次用户 Δ
  → 回写阿洛娜自身行动（followed_up / gave_space / teased / greeted）
```

`interrupt` 取消正在生成的台词，并投递 `teacher_interrupt`（继续当前活动，不改成看着老师）。危机通路必须开口，不经「想不想理」的动作选择。

墙钟 tick 无待处理冲动时只 `engine.tick` + `presence`，不调 Planner、不 `speak`。有冲动时循环可开口、只换脸、或继续做事。主动开口（上线 / 搭话 / 提醒 / 回访 / 节日）不再把那些标记写成近期对话里的老师句；她说的话仍留下。事件日志 `life_journal.json` 只记活动、心事摘要、开口和「老师开口」，不记老师原文，危机回合不入档。`arona.json` 是阿洛娜自己的短记忆，注入【阿洛娜的记忆】，不进老师抽取。

老师回合 `hub.set_busy` 时冲动只积压、不开口。听写打开不再把会话从空闲表摘掉：在场仍可变，冲动可入队；老师 `transcript` 仍优先。主动 30s tick 只 `pick_motive` 入队，不再自己 `handle_initiate`。

Planner 只看见【关系气候】档位与【建议姿态】，禁止下发 A/B/C 浮点或「提升信任度」。禁止把【阿洛娜此刻】或【未出口的心事】写进 draft。

`action` 目前实际用到的是 `speak`（开口）、`silence`（沉默）、`initiate`（欢迎 / 空闲 / 照料 / goal 回访 / 节日）与 `continue`（同轮补一句）。欢迎与节日回写 `greeted`，空闲与 goal 回写 `checked_in`，照料回写 `cared`（均不抬依赖）；同轮补充回写 `followed_up`。

## Prompt 部件

双模型路径最终拼出两条 prompt：Planner（DeepSeek）与 Renderer（AronaLM）。组装入口：


| 最终产物            | 组装函数                        | 文件                                               |
| --------------- | --------------------------- | ------------------------------------------------ |
| Planner prompt  | `PlannerClient.plan()`      | `[app/planner/client.py](app/planner/client.py)` |
| Renderer prompt | `build_renderer_messages()` | `[app/prompt.py](app/prompt.py)`                 |


调用方是 `[app/orchestrator.py](app/orchestrator.py)`：客户端用户输入走 `handle_chat()`；主动开口效应器走 `handle_initiate()`（欢迎 / 节日 / 照料 / 回访经冲动入队后同一条嘴）；同轮补充走 `_maybe_continue()`。Planner 关闭或失败时走 `build_messages()`（本地单模型），不拼 Renderer prompt。

```text
用户 chat / 系统 instruction
        │
        ├─【关系气候】policy.py 或 orchestrator._welcome_climate_block
        ├─ 记忆 / 知识 / 历史（运行时检索，非独立 prompt 文件）
        └─ 本轮文本：用户原话 或 6 套 build_*_instruction
                │
                ▼
     Planner prompt  (planner/prompts.py + client.py)
                │  JSON draft
                ▼
     Renderer prompt (prompt.py + renderer_*_v24.txt)
```



### Planner prompt

结构固定为两条 message：`system` 由 `select_planner_system()` 按 `model.enabled` 选择，`user = climate +【当前时间】+ 记忆 + 知识 + 历史 +「老师本轮消息」+ 收尾句`。


| 部件                                     | 位置                                                   |
| -------------------------------------- | ---------------------------------------------------- |
| `PLANNER_SYSTEM_BASE`（共享人设与硬性约束） | `[app/planner/prompts.py](app/planner/prompts.py)`   |
| `PLANNER_PREFIX_RENDERER`（planner → renderer 角色说明） | `[app/planner/prompts.py](app/planner/prompts.py)`   |
| `PLANNER_PREFIX_DIRECT`（draft 直出角色说明） | `[app/planner/prompts.py](app/planner/prompts.py)`   |
| `PLANNER_SYSTEM` = prefix + base（`model.enabled=true`） | `[app/planner/prompts.py](app/planner/prompts.py)`   |
| `PLANNER_SYSTEM_DIRECT` = prefix + base（`model.enabled=false`） | `[app/planner/prompts.py](app/planner/prompts.py)`   |
| `select_planner_system()`              | `[app/planner/prompts.py](app/planner/prompts.py)`   |
| `{EMOTION_WHITELIST_CSV}` 插值           | `[app/planner/emotions.py](app/planner/emotions.py)` |
| user 模板 `build_planner_user_message()` | `[app/planner/prompts.py](app/planner/prompts.py)`   |


`FIXED_MUST_NOT` 仍在 `prompts.py`，V2.4 **不再注入**。

`build_planner_user_message()` 按顺序拼：可选 `climate_block` → `【当前时间】`（与记忆抽取同一格式，如 `2026年8月24日 星期一 10:14`）→ `【长期记忆】` → `【相关知识】` → `【近期对话】` → `【老师本轮消息】` → 收尾「若有【关系气候】，按建议姿态写草稿」。`【近期对话】` 每条带本地年月日时分秒（如 `[2026年8月24日 10:14:05] 老师：…`），缺时间戳的旧消息仍按 `老师：` / `阿洛娜：` 原样输出。写入 Planner 的记忆按 key 冷却，默认 1 小时内不重复注入（`memory.inject_cooldown_sec`）；老师本轮对某条记忆强匹配（高分或词汇重叠）时绕过该冷却。抽取侧检索不受冷却影响。

`【老师本轮消息】` **按来源分套：**


| 场景        | 构建函数                                         | 文件                                                       |
| --------- | -------------------------------------------- | -------------------------------------------------------- |
| 客户端用户输入   | 原样写入，无额外 instruction                         | `Orchestrator.handle_chat()`                             |
| 上线欢迎      | `build_welcome_instruction()`                | `[app/proactive/welcome.py](app/proactive/welcome.py)`   |
| 空闲搭话      | `build_idle_instruction()`                   | `[app/proactive/idle.py](app/proactive/idle.py)`         |
| 早/午/晚饭 / 睡觉提醒 | `build_care_instruction()` + `_CARE_INTENTS` | `[app/proactive/care.py](app/proactive/care.py)`         |
| 节日 / 生日   | `build_festival_instruction()`               | `[app/proactive/festival.py](app/proactive/festival.py)` |
| goal 回访   | `build_goal_instruction()`                   | `[app/proactive/goal.py](app/proactive/goal.py)`         |
| 同轮补充      | `build_continue_instruction()`               | `[app/proactive/followup.py](app/proactive/followup.py)` |


欢迎时段文案还会用到 `[app/proactive/slots.py](app/proactive/slots.py)` 的 `SLOT_LABELS`。调度入口：`[app/proactive/scheduler.py](app/proactive/scheduler.py)`（idle / care / goal / festival）、`[app/proactive/loop.py](app/proactive/loop.py)`（festival / sleep 补发）。

`【关系气候】` **块：**


| 场景                            | 函数                         | 文件                                                         |
| ----------------------------- | -------------------------- | ---------------------------------------------------------- |
| 普通对话 / 主动事件（有 Decision）       | `planner_climate_block()`  | `[app/relationship/policy.py](app/relationship/policy.py)` |
| 欢迎（peek climate，无完整 Decision） | `_welcome_climate_block()` | `[app/orchestrator.py](app/orchestrator.py)`               |


`planner_climate_block` 的文案来自同文件：`CLIMATE_LABELS`（气候中文名）、`_POLICY`（对话姿态 / 禁区 / 语气）、`decide_proactive()`（idle / care / festival / goal 另一套姿态与禁区）。

### Renderer prompt

结构也是两条 message，**不拼接 yaml 人设、不带历史**：`system = RENDERER_SYSTEM`，`user = 【意图草稿】 + draft + RENDERER_USER_TAIL`。


| 部件                               | 加载 / 组装                             | 源                                                |
| -------------------------------- | ----------------------------------- | ------------------------------------------------ |
| `RENDERER_SYSTEM`                | `[app/prompt.py](app/prompt.py)` 常量 | 代码内编码                                            |
| `RENDERER_USER_TAIL`             | `[app/prompt.py](app/prompt.py)` 常量 | 代码内编码                                            |
| user 包装 `format_renderer_user()` | `[app/prompt.py](app/prompt.py)`    | `【意图草稿】` + tail                                  |
| draft 内容                         | `IntentCard.to_renderer_draft()`    | `[app/planner/schema.py](app/planner/schema.py)` |


后端不读取 `llm/aronaLM/finetune/prompts/`；该目录只给微调数据管线使用。

### 本地回落（非 dual）

`build_messages()`（`[app/prompt.py](app/prompt.py)`）：


| 部件                       | 位置                                                                                             |
| ------------------------ | ---------------------------------------------------------------------------------------------- |
| 本地人设                     | `config.yaml` 的 `prompt.local_system_prompt`（模板见 `[config.example.yaml](config.example.yaml)`） |
| 关系 hint                  | `local_system_hint()` → `[app/relationship/policy.py](app/relationship/policy.py)`             |
| 记忆 / 知识 / 历史 / user_text | 运行时拼进 system / user                                                                            |


`handle_initiate` 在 planner 失败时，系统 instruction 会直接当 `user_text` 送给本地模型。早/午/晚饭与睡觉照料若 Planner 判 `reply_ok=false`（老师已交代过该话题）则不回落、不发送，并把当天该项标为已处理。

### 不进这条链路

- 记忆抽取：`EXTRACT_SYSTEM` 在 `[app/memory/extractor.py](app/memory/extractor.py)`（另一路 DeepSeek）

改话术时：日常人设与硬性约束改 `PLANNER_SYSTEM_BASE`（两套架构共用）；planner → renderer 角色说明改 `PLANNER_PREFIX_RENDERER`；关闭 renderer、draft 直出时改 `PLANNER_PREFIX_DIRECT`；欢迎/空闲/照料等改对应 `build_*_instruction`；关系口吻改 `policy.py`；阿洛娜最终台词风格改 `app/prompt.py` 的 `RENDERER_SYSTEM`。

## 关系气候

三个慢变量，值域 `[-1, 1]`，默认 baseline 约 `(信任 0.55, 依赖 0.30, 张力 0.25)`：


| 维度   | 含义         |
| ---- | ---------- |
| 信任 A | 防备 ↔ 安心托付  |
| 依赖 B | 当工具 ↔ 过度黏着 |
| 张力 C | 死气 ↔ 对立/过激 |


更新公式（惯性 + 微弱回归 + 日封顶；张力高时正向信任修正放大）：

```text
new = clamp(old + α * Δ - β * (old - baseline), -1, 1)
```

Δ 由事件表给出，不让 LLM 发明浮点。用户侧事件包括 `fatigue` / `seek_validation` / `self_disclose` / `play_tease` / `reject` / `gratitude` / `affection` / `worry_bond` / `depart` / `instrumental` / `short_ack` / `other`。未识别为 `other`（Δ 为 0）。规则为 `other` 且 Planner 给出白名单内非 `other` / 非 `crisis` / 非 `touch` 的 `user_act` 时，按 Planner 结果补一次用户 Δ；本轮 silence / 气候提示仍以规则分类为准。

气候分区（连续若干轮保持同一姿态，紧急档可立即切换）：


| 气候            | 条件（概要）      | 姿态             |
| ------------- | ----------- | -------------- |
| `secure_play` | A 高、B 中、C 中 | 可轻松、可轻玩笑       |
| `cling_risk`  | B 高、C 低     | 短回应；短「嗯」或疲惫可沉默 |
| `rupture`     | C 高、A 尚可    | 先认情绪，不讲理       |
| `cold_tool`   | A/B/C 都低    | 先可靠办事，不硬亲密     |
| `fragile`     | A 低且 C 高    | 只稳住，不玩笑        |
| `steady`      | 其余          | 平稳接住本轮         |


离开 `fragile` / `rupture` / `cling_risk` 后有 `climate_stick_turns`（默认 3）轮恢复窗：Planner 的 `planner_climate_block` 增加【过渡】行（不写 A/B/C 数字），禁区取新旧带并集，姿态偏克制。`fragile` / `rupture` 恢复期内 idle / goal / mood_followup 仍沉默；`cling_risk` 恢复只约束话术。非紧急档之间切换只提示 1 轮、不并禁区。紧急档重新进入时立即切并清掉恢复窗。

沉默规则（当前实现）：

- `cling_risk` 且用户是 `short_ack` / `fatigue`
- 上一轮是 `depart`（失陪、先去忙），本轮是短「嗯」

状态落 `data/memory/relationship.json`，重启不重置。关闭：`proactive.relationship.enabled: false`。

## 上线欢迎

WebSocket 连接并发送 `connected` 后，若 `proactive.welcome.enabled` 为真，后端占用当前 `chat_task` 主动生成一句问候（普通 `chat_response`）。欢迎不检索记忆。

时段（本地时）：


| 时段  | 区间               | 同槽首次         |
| --- | ---------------- | ------------ |
| 凌晨  | `[0:00, 5:00)`   | 提醒休息，不说「早上好」 |
| 早上  | `[5:00, 9:00)`   | 早上好          |
| 上午  | `[9:00, 12:00)`  | 上午好          |
| 中午  | `[12:00, 14:00)` | 中午好，可提醒吃饭    |
| 下午  | `[14:00, 18:00)` | 下午好          |
| 晚上  | `[18:00, 23:00)` | 晚上好          |
| 深夜  | `[23:00, 24:00)` | 提醒休息         |


同一时段再次上线改为「老师好 / 欢迎回来」，不再重复时段问候。时段状态在内存中，进程重启后会再问候一次。失败不标记时段。历史写入短标记 `【上线】`，不把系统指令写进对话。欢迎以 50/50 在轻问开场与陈述句收尾之间二选一。

节日当天**第一次上线**会把欢迎换成节日祝福（见下），同日再连仍走普通欢迎。

## 空闲搭话、时刻照料与节日

进程级 tick（约 30 秒）查看已连接且未在生成中的会话，每 tick 最多选 1 条动机（节日 > 照料 > goal 回访 > 空闲），先过 `decide_proactive` 再生成。推普通 `chat_response`。忙时跳过，不排队。


| 触发      | 默认                                  | 要点                                                                                                                    |
| ------- | ----------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| 节日问候    | 公历节假日 / 农历年表 / 老师生日                 | 当天第一次上线欢迎直接换成祝福，整天只说一次；凌晨/深夜先祝福再跟一句休息提醒；tick 仅在欢迎没说过时兜底；`depart` 时 tick 不说、欢迎仍可换；历史 `【节日】`；回写 `greeted`               |
| 空闲轻搭话   | 老师安静 15 分钟；两次搭话间隔默认 30 分钟；每天最多 3 次  | 欢迎/照料之后只需再等 `after_sec`，不占用搭话冷却；深夜/凌晨不闲聊；上一轮是 `depart` 不闲聊；仅 `secure_play` / `steady` 可开口；历史 `【搭话】`；不检索记忆             |
| goal 回访 | 老师安静 5 分钟后；不重要的 goal 每条冷却 6 小时、每天最多 1 次；content 日期为当天、未来 36 小时内、或过期未超过 36 小时则视为重要，绕过 6 小时与每日上限，改走 30 分钟短间隔；任意两次回访（含不同 key）至少间隔 30 分钟；老师应过后当天不再提同一条（记忆仍保留）；带钟点且照料覆盖不到的事项可在约定前 `due_soon_sec`（默认 1 小时）再轻轻提一次；睡觉/早午晚饭类到点交给照料 | 扫记忆 `category=goal`，重要优先，否则轻轻提起最久未回访的一条；不催、不盘问、不编造进展；老师说「先别提」等则 mute 上一条 7 天；休息时段 / `depart` 不回访；气候闸与空闲相同；历史 `【回访】`；直接注入该条记忆 |
| 早饭照料    | 06:30–08:00，每天一次                    | 短提醒吃早饭，不催；`cling_risk` 更短；可检索作息记忆；欢迎（及任何已写入 `last_proactive_at` 的主动开口）之后再等 `idle.after_sec`；窗口内等待时不改发搭话或回访；Planner 见老师已交代过当前这餐则当天不再提醒（`reply_ok=false` 不回落本地）；Planner 不可用时仍会提醒 |
| 午饭照料    | 11:30–13:00，每天一次                    | 短提醒吃饭，不催；闸门与间隔同早饭照料 |
| 晚饭照料    | 17:30–19:00，每天一次                    | 短提醒吃晚饭，不催；闸门与间隔同早饭照料 |
| 睡觉照料    | 23:00–23:20，每天一次                    | 提醒休息；允许在休息时段触发；历史 `【提醒】`；与午饭相同，相对欢迎再等 `idle.after_sec`；节日欢迎里的休息补发仍同一轮发出、不等间隔；Planner 见老师已交代过今晚休息则当天不再提醒；Planner 不可用时仍会提醒 |
| 同轮补充    | Planner `followup_ok`（按「能否扩展」）      | 仅用户 chat 双模型路径、首句成功后最多再扩 1 句；本地回落 / 欢迎 / idle / care / goal / festival 不续说；历史 `【补充】`                                  |


调度状态落 `data/memory/proactive.json`（含 `festival_done`）。跨日清当日节日标记。节日成功才标记；失败可下次再试。关闭：`proactive.idle.enabled` / `proactive.care.enabled` / `proactive.goal.enabled` / `proactive.continue.enabled` / `proactive.festival.enabled`。

## ASR 脏文本过滤

腾讯云 ASR 空结果曾被前端误当成识别成功，把  
`[Tencent Speech Recognizer]Didnt recognize vailable content!` 整段发进 `chat`，从而误触发 Planner。

**后端兜底**（`[app/input_filter.py](app/input_filter.py)` + `[app/ws_handler.py](app/ws_handler.py)`）：

- 空串、仅空白，或匹配腾讯云 ASR / SDK 错误模板的 `content` 在 WS 入口直接丢弃
- **不**调用 Orchestrator / Planner / 记忆抽取，**不**写入 session history
- 回一条轻量 `chat_response`：`刚才没听清，请再说一次～`，`emotion=curious`，`context_used=asr_filter`

**前端根因修复**（需重编客户端）：`[TencentSpeechRecognizer.cpp](../frontend/AronaArchive_WindowsClient/QtUtils/TencentSpeechRecognizer.cpp)` 空结果改走 `errorOccurred`；`[MainController.cpp](../frontend/AronaArchive_WindowsClient/QtMainFile/MainController.cpp)` 对同类脏串不再 `sendChatMessage`。

## 世界观知识 RAG

1. 按 `[data/knowledge/WRITING.md](data/knowledge/WRITING.md)` 在 `data/knowledge/corpus/` 编写 Markdown（`##` 切块）
2. 嵌入模型默认使用本地目录 `../models/bge-small-zh-v1.5`（配置项 `knowledge.embedding_model_path`）
3. 灌库：

```bash
python scripts/ingest_knowledge.py
# 大幅改标题/结构后建议：
python scripts/ingest_knowledge.py --rebuild
```

1. 冒烟检索：`python scripts/test_knowledge_rag.py`；时间感知查询单测（不加载 BGE）：`python scripts/test_query_time.py`
2. 在 `config.yaml` 设 `knowledge.enabled: true` 后重启后端

对话主路径里记忆与知识检索共用一轮 BGE：同时编码老师原文和带当前时间的附带查询（相对日期会先展开成与记忆写入相同的绝对日期）。两路召回按 key / 标题合并后截断 `top_k`。写入 Planner 的记忆命中按 key 冷却，默认 `memory.inject_cooldown_sec: 3600` 内不重复注入，空缺由下一名候选补上；本轮强匹配（`inject_cooldown_bypass_score` 或与老师原文有词汇重叠）永久绕过该冷却。无词汇重叠时用更高的 `min_score_no_overlap`。抽取器对照已有记忆时不走该冷却，也不走注入用的分数门槛：按缓冲里每一轮老师消息做宽松召回后合并，并钉上全部 `goal` 与热 key（`user_name` / `preference_color` / `user_birthday`）。知识命中（过滤后的 lore 文本）可按 query 向量近义复用，默认 `query_cache_min_cosine: 0.92`，缓存按自然日区分以免跨日复用带日期的命中；`ingest` / `--rebuild` 会清空该缓存。不缓存 Planner 草稿或最终台词。当前时间同时用于检索附带查询，并以 `【当前时间】` 写入 Planner user 消息（不写入 Renderer）。

## 配置

由 `config.example.yaml` 复制为 `config.yaml`（已 gitignore）。相对路径均相对后端根目录解析（源码为 `backend/`；便携包为解压目录；可用环境变量 `ARONA_BACKEND_DIR` 覆盖）。下表默认值与示例文件一致。


| 配置段            | 说明                                              |
| -------------- | ----------------------------------------------- |
| `server`       | 监听地址、端口、WebSocket 路径                            |
| `model`        | 是否加载 Arona-Renderer GGUF、模型路径、上下文长度与采样参数        |
| `prompt`       | 本地单模型回落用 system prompt（双模型 Renderer 不读此项）       |
| `conversation` | 多轮历史保留轮数                                        |
| `knowledge`    | 世界观 RAG（语料、Chroma、嵌入模型、检索阈值、近义 query 缓存）        |
| `memory`       | SQLite + Chroma 记忆、混合检索、注入冷却、去重/调和、DeepSeek 抽取器 |
| `planner`      | 双模型 Planner（DeepSeek 意图卡）与轮次路由器                 |
| `listen`       | 连续听写的静音提交与接话窗口                                  |
| `life`         | 生命循环：内状态、自己的一天、阿洛娜侧记忆、低频瞥屏、电脑操作作为可打断活动 |
| `proactive`    | 上线欢迎、关系气候、空闲搭话、照料、goal 回访、节日、同轮补充               |
| `token_budget` | 注入 prompt 的 memory / knowledge / history 预算     |
| `logging`      | 日志目录、文件名、级别与滚动                                  |




### `server`


| 配置项       | 默认          | 说明                       |
| --------- | ----------- | ------------------------ |
| `host`    | `127.0.0.1` | HTTP / WebSocket 监听地址    |
| `port`    | `20456`     | 监听端口                     |
| `ws_path` | `/ws`       | WebSocket 路径，需与 Qt 客户端一致 |




### `model`


| 配置项              | 默认                   | 说明                                                                                                                |
| ---------------- | -------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `enabled`        | `false`              | 是否加载 Arona-Renderer GGUF。`true`：Planner + Renderer 双模型，Planner 失败时回落本地 GGUF 推理；`false`：不加载 GGUF，直接把 Planner 草稿当台词 |
| `gguf_path`      | Renderer V2.4 Q4_K_M | GGUF 路径。单模型回落可改成注释里的 AronaLM-Generator-V2.0                                                                       |
| `n_ctx`          | `2048`               | llama.cpp 上下文长度                                                                                                   |
| `n_gpu_layers`   | `-1`                 | 放到 GPU 的层数；`-1` 表示全部上 GPU                                                                                         |
| `max_new_tokens` | `72`                 | 单次生成的最大新 token 数                                                                                                  |
| `temperature`    | `0.7`                | 采样温度                                                                                                              |
| `top_p`          | `0.85`               | nucleus 采样                                                                                                        |
| `repeat_penalty` | `1.1`                | 重复惩罚                                                                                                              |




### `prompt`


| 配置项                   | 默认     | 说明                                                      |
| --------------------- | ------ | ------------------------------------------------------- |
| `local_system_prompt` | 示例人设长文 | 仅本地单模型路径（`build_messages()`）使用。Planner / Renderer 不拼接此项 |




### `conversation`


| 配置项                 | 默认   | 说明                            |
| ------------------- | ---- | ----------------------------- |
| `max_history_turns` | `12` | 会话保留的用户–助手轮数（消息条数约为 `2 ×` 该值） |




### `knowledge`


| 配置项                      | 默认                            | 说明                                      |
| ------------------------ | ----------------------------- | --------------------------------------- |
| `enabled`                | `false`                       | 是否启用世界观 RAG                             |
| `corpus_dir`             | `data/knowledge/corpus`       | Markdown 语料目录                           |
| `chroma_path`            | `data/knowledge/chroma`       | Chroma 向量库路径                            |
| `collection`             | `arona_lore`                  | Chroma collection 名                     |
| `embedding_model_path`   | `../models/bge-small-zh-v1.5` | 本地 BGE 嵌入模型（与记忆共用）                      |
| `retrieve_top_k`         | `3`                           | 最终注入的知识条数上限                             |
| `candidate_top_k`        | `8`                           | 过滤前召回的候选数                               |
| `max_inject_chars`       | `400`                         | 注入字符硬上限；与 `token_budget.knowledge` 取较小值 |
| `min_score`              | `0.45`                        | 与查询有词汇重叠时的相似度下限                         |
| `min_score_no_overlap`   | `0.62`                        | 无词汇重叠时的更高相似度下限                          |
| `score_margin`           | `0.08`                        | 只保留与最高分差距不超过该值的命中                       |
| `query_cache_enabled`    | `true`                        | 是否按 query 向量近义复用知识命中                    |
| `query_cache_size`       | `64`                          | 近义缓存条数                                  |
| `query_cache_min_cosine` | `0.92`                        | 复用缓存所需的 query 余弦相似度                     |




### `memory`


| 配置项                     | 默认                      | 说明                                       |
| ----------------------- | ----------------------- | ---------------------------------------- |
| `db_path`               | `data/memory/memory.db` | SQLite（含 FTS5）路径                         |
| `chroma_path`           | `data/memory/chroma`    | 记忆向量索引路径                                 |
| `collection`            | `arona_memory`          | Chroma collection 名                      |
| `retrieve_top_k`        | `3`                     | 对话注入的记忆条数上限                              |
| `candidate_top_k`       | `10`                    | 混合检索（FTS + 向量）的候选数                       |
| `min_score`             | `0.35`                  | 与查询有词汇重叠时的记忆召回相似度下限                     |
| `min_score_no_overlap`  | `0.60`                  | 无词汇重叠时的更高相似度下限                              |
| `max_inject_chars`      | `400`                   | 本地回落注入字符硬上限；与 `token_budget.memory` 取较小值 |
| `inject_cooldown_sec`   | `3600`                  | 同一 key 写入 Planner 的冷却秒数；`0` 关闭。抽取侧检索不受影响 |
| `inject_cooldown_bypass_score` | `0.55`           | 达到该分或与老师原文有词汇重叠时绕过注入冷却                    |
| `extract_context_top_k` | `8`                     | 抽取时每一轮老师消息的召回条数                          |
| `extract_context_max_items` | `24`                | 多轮召回合并后的对照集上限；`goal` 与热 key 不被截掉         |
| `extract_conflict_min_score` | `0.70`            | 仅清理对照集中未被模型点名的同主题冲突（含 goal）            |
| `reconcile_enabled`     | `true`                  | 写入后删除同类别、高相似的旧条目（`goal` 除外）              |
| `reconcile_min_score`   | `0.82`                  | 调和删除的相似度下限                               |
| `reconcile_top_k`       | `5`                     | 调和 / 去重时的相似检索条数                          |
| `dedup_enabled`         | `true`                  | 写入前合并同类别近重复条目（`goal` 除外）                 |
| `dedup_min_score`       | `0.88`                  | 去重合并的相似度下限                               |


`memory.extractor`：


| 配置项                    | 默认                         | 说明                          |
| ---------------------- | -------------------------- | --------------------------- |
| `enabled`              | `true`                     | 是否启用异步记忆抽取                  |
| `base_url`             | `https://api.deepseek.com` | OpenAI 兼容 API 根地址           |
| `api_key`              | `YOUR_DEEPSEEK_API_KEY`    | 未填写或仍为占位符时走 `fallback`      |
| `model`                | `deepseek-flash`           | 抽取模型名                       |
| `timeout_sec`          | `15`                       | 单次 HTTP 超时（秒）               |
| `max_calls_per_day`    | `512`                      | 每日抽取调用上限                    |
| `every_n_turns`        | `6`                        | 每 N 轮强制抽一次（另有「请记住」等启发式立即触发） |
| `extract_buffer_turns` | `6`                        | 抽取缓冲攒满该轮数也触发；老师刚回应【回访】/【心情回访】时绕过该门槛 |
| `fallback`             | `regex`                    | DeepSeek 失败或无 Key 时的降级方式    |




### `planner`


| 配置项                  | 默认                         | 说明                                                            |
| -------------------- | -------------------------- | ------------------------------------------------------------- |
| `enabled`            | `true`                     | 是否走 DeepSeek 意图卡。关闭、无 Key 或失败时回落本地 GGUF（若 `model.enabled`）或草稿 |
| `base_url`           | `https://api.deepseek.com` | OpenAI 兼容 API 根地址                                             |
| `api_key`            | `YOUR_DEEPSEEK_API_KEY`    | Planner 与轮次路由器共用                                              |
| `model`              | `deepseek-flash`           | Planner / 路由器模型名                                              |
| `timeout_sec`        | `20`                       | Planner 请求超时（秒）                                               |
| `temperature`        | `0.3`                      | Planner 采样温度                                                  |
| `max_tokens`         | `512`                      | Planner 输出上限                                                  |
| `vision_model`       | `deepseek-flash`           | 有截图或电脑操作时使用的多模态模型名；为空则回落 `model`                              |
| `router_enabled`     | `true`                     | 连续听写时，规则拿不准再调短超时 LLM 判断 ignore / wait / reply                 |
| `router_timeout_sec` | `3`                        | 路由器超时（秒）；不复用 Planner 的 20s 超时                                 |
| `router_max_tokens`  | `64`                       | 路由器输出上限                                                       |




### `listen`

连续听写的轮次切分（ASR 片段先入缓冲，静音后再提交）：


| 配置项                       | 默认     | 说明                         |
| ------------------------- | ------ | -------------------------- |
| `silence_commit_ms`       | `1000` | 完整句的静音提交等待（毫秒）             |
| `incomplete_commit_ms`    | `1800` | 半句（停在「然后 / 就是 / 那个」等）时加长等待 |
| `continuation_window_sec` | `8`    | 阿洛娜刚说完后的接话窗口；窗口内未点名也视为对她说  |

### `life`

墙钟驱动的阿洛娜内状态（教室发呆 / 看着老师 / 想事 / 休息 / 操作电脑）。老师的 `chat` / `transcript` / `interact` 是世界事件：投递前先快照，快照进 Planner 的【阿洛娜此刻】。墙钟 tick 无待处理冲动时只推进内状态并推 `presence`（Track 1），不调 Planner、不 `speak`。主动事件写入至多一条冲动，由循环决定开口或只换脸。听写打开不冻结生活。`interrupt` 投递 `teacher_interrupt`，不把活动改成看着老师。老师原文不写入 `life.json`。与关系气候分文件落盘。

她自己的一天写在 `life_journal.json`（约 48 条或 24 小时）：活动变化、心事出现或放下、开口短句、老师打断时只记「老师开口」。危机内容不入档。Planner 在【近期对话】旁看到【阿洛娜的记忆】。`arona.json` 最多三条短陈述（教室里做过什么、还没放下的担心、已经放下的担心），注入【阿洛娜的记忆】，和【长期记忆】分开，不进抽取 schema。

偶尔向客户端发 `glance_request`。客户端用现有截屏回一帧 `glance_frame`，不走电脑操作动作环。默认大约 20 分钟一次；看着老师、老师回合忙碌、正在操作电脑、气候为 fragile / rupture / cling_risk 时不瞥。听写打开不缩短间隔。看不清或不确定就丢掉，不编造窗口。结果只进日志。

电脑操作开始时活动变为 `using_computer`（在场脸用现有的 curious）。墙钟休息时段不会把这次操作立刻打回休息。老师 `chat` / `transcript` / `interrupt`（含 `Ctrl+Alt+S`）先把 `abort_check` 打真，停掉当前操作，再走老师回合。不等 `computer_use_done` 才恢复对话。

| 配置项 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 是否启动生命循环任务并向循环旁路投递世界事件 |
| `persist_path` | `data/memory/life.json` | 内状态落盘路径，与 `relationship.json` 分开 |
| `journal_path` | `data/memory/life_journal.json` | 她自己的一天，环形日志 |
| `arona_memory_path` | `data/memory/arona.json` | 阿洛娜侧短记忆，不进老师抽取 |
| `tick_sec` | `5` | 墙钟节拍（秒） |
| `look_hold_sec` | `60` | 老师相关事件后保持「看着老师」的秒数 |
| `think_hold_sec` | `120` | 「想某件事」活动最多持续秒数；心事条目本身保留 |
| `glance_interval_sec` | `1200` | 两次瞥屏的最短间隔（秒）；听写不缩短 |




### `proactive`



#### `welcome`


| 配置项            | 默认                         | 说明                                          |
| -------------- | -------------------------- | ------------------------------------------- |
| `enabled`      | `true`                     | WebSocket `connected` 后是否主动问候               |
| `persist_path` | `data/memory/welcome.json` | 本时段已问候标记落盘路径，重启后同一时段再次上线不再重复说「下午好」等时段问候 |




#### `relationship`


| 配置项                   | 默认                              | 说明                                                              |
| --------------------- | ------------------------------- | --------------------------------------------------------------- |
| `enabled`             | `true`                          | 是否启用关系气候。关闭后不分类、不更新、不按气候沉默                                      |
| `persist_path`        | `data/memory/relationship.json` | 状态落盘路径，重启不重置                                                    |
| `alpha`               | `0.3`                           | 事件 Δ 的惯性系数：`new = clamp(old + α·Δ − β·(old − baseline), −1, 1)` |
| `beta`                | `0.02`                          | 向 baseline 回归的系数                                                |
| `daily_abs_cap`       | `0.35`                          | 每个维度每日绝对变化上限                                                    |
| `makeup_tension`      | `0.7`                           | 张力高于该值时，正向信任修正放大                                                |
| `makeup_trust_scale`  | `1.5`                           | 上述放大倍数                                                          |
| `cling_dependence`    | `0.55`                          | 依赖高于该值且张力低 → `cling_risk`                                       |
| `high_dependence`     | `0.7`                           | 依赖高于该值时额外禁「增加依赖 / 追问还在不在」                                       |
| `climate_stick_turns` | `3`                             | 非紧急档需连续若干轮才切换气候；紧急档退出后的恢复窗也用此轮数 |
| `baseline_trust`      | `0.55`                          | 信任回归中心                                                          |
| `baseline_dependence` | `0.30`                          | 依赖回归中心                                                          |
| `baseline_tension`    | `0.25`                          | 张力回归中心                                                          |




#### `idle`


| 配置项            | 默认     | 说明                                          |
| -------------- | ------ | ------------------------------------------- |
| `enabled`      | `true` | 是否启用空闲轻搭话                                   |
| `after_sec`    | `900`  | 老师安静多久后可搭话（秒，默认 15 分钟）。欢迎/照料之后也按此间隔，不占用搭话冷却 |
| `cooldown_sec` | `1800` | 两次搭话最短间隔（秒，默认 30 分钟）                        |
| `max_per_day`  | `3`    | 每天最多搭话次数                                    |




#### `care`


| 配置项                         | 默认                           | 说明                                      |
| --------------------------- | ---------------------------- | --------------------------------------- |
| `enabled`                   | `true`                       | 是否启用早/午/晚饭与睡觉提醒                           |
| `persist_path`              | `data/memory/proactive.json` | 主动调度落盘（含节日标记），idle / goal / festival 共用 |
| `breakfast_start` / `breakfast_end` | `06:30` / `08:00`            | 早饭窗口                                    |
| `lunch_start` / `lunch_end` | `11:30` / `13:00`            | 午饭窗口                                    |
| `dinner_start` / `dinner_end` | `17:30` / `19:00`            | 晚饭窗口                                    |
吃饭| `sleep_start` / `sleep_end` | `23:00` / `23:20`            | 睡觉提醒窗口                                  |




#### `goal`


| 配置项                  | 默认       | 说明                        |
| -------------------- | -------- | ------------------------- |
| `enabled`            | `true`   | 是否回访记忆里的 `category=goal`  |
| `min_after_user_sec` | `300`    | 老师安静多久后才可回访（秒）            |
| `cooldown_sec`            | `21600`  | 不重要 goal 的回访冷却（秒，默认 6 小时） |
| `important_horizon_hours` | `36`     | content 日期为当天、未来该小时数内、或过期未超过该小时数则视为重要；更早的过期走普通冷却 |
| `important_cooldown_sec`  | `1800`   | 重要 goal 的短间隔，同时是任意两次回访的全局间隔（秒，默认 30 分钟） |
| `due_soon_sec`            | `3600`   | 老师应过后，带钟点的非照料事项可在约定前该秒数内再提一次；睡觉/早午晚饭类不走二次 goal |
| `mute_sec`                | `604800` | 老师说「先别提」后静音该条的秒数（默认 7 天）  |
| `max_per_day`        | `1`      | 每天最多回访次数                  |




#### `continue`


| 配置项         | 默认     | 说明                              |
| ----------- | ------ | ------------------------------- |
| `enabled`   | `true` | Planner 标 `followup_ok` 时是否再补一句 |
| `delay_sec` | `2`    | 首句发出后再补一句的延迟（秒）                 |




#### `festival`


| 配置项       | 默认     | 说明                       |
| --------- | ------ | ------------------------ |
| `enabled` | `true` | 是否在公历节假日 / 农历年表 / 老师生日问候 |




### `token_budget`

按约 `1.6` 字/token 换成字符后，与对应 `max_inject_chars` 取较小值再截断。


| 配置项         | 默认    | 说明                        |
| ----------- | ----- | ------------------------- |
| `memory`    | `250` | 本地回落注入长期记忆的 token 预算      |
| `knowledge` | `250` | 知识注入预算（Planner 与本地回落都会截断） |
| `history`   | `700` | 本地回落拼进 prompt 的历史字符预算     |




### `logging`


| 配置项            | 默认                  | 说明              |
| -------------- | ------------------- | --------------- |
| `dir`          | `logs`              | 日志目录            |
| `filename`     | `arona-backend.log` | 日志文件名           |
| `level`        | `INFO`              | 日志级别            |
| `max_bytes`    | `10485760`          | 单文件滚动大小（10 MiB） |
| `backup_count` | `5`                 | 保留的旧日志份数        |


关键项速查：

- 模型：`model.gguf_path`（示例默认 AronaLM-Renderer-V2.4；回落见注释中的 AronaLM-Generator-V2.0）
- 模板：`config.example.yaml` → 本地：`config.yaml`

本地数据路径（均已 gitignore）：

- 记忆库：`data/memory/memory.db`
- 记忆向量索引：`data/memory/chroma/`
- 关系气候：`data/memory/relationship.json`
- 阿洛娜内状态：`data/memory/life.json`
- 阿洛娜的一天：`data/memory/life_journal.json`
- 阿洛娜侧记忆：`data/memory/arona.json`
- 主动调度：`data/memory/proactive.json`
- 知识向量库：`data/knowledge/chroma/`（由 ingest 生成）
- 运行日志：`logs/arona-backend.log`



## 协议摘要

连接后服务端发送 `{"type":"connected","session_id":"..."}`，随即再推一条当前在场：`{"type":"presence","emotion":"...","activity":"..."}`（无台词、无 TTS；`emotion` 为 `arona_emotion` 白名单英文值；`activity` 仅调试，客户端不要用它切 Track 0）。生命循环在内状态映射的表情变化时继续推 `presence`。听写中也会收到；正在生成台词时推迟，生成结束后补发。`emotion_only`（沉默只换脸）会覆盖推一条 `presence`，不经过空 `chat_response.emotion`。

低频瞥屏：服务端 `{"type":"glance_request","request_id":"..."}`，客户端回 `{"type":"glance_frame","request_id":"...","image":{"mime":"image/jpeg","data":"..."}}`。看不清可以不带 `image`。这不是电脑操作动作环。

客户端 `chat`：

```json
{"type":"chat","content":"你好","options":{"use_rag":true,"use_memory":true}}
```

客户端 `interact`（非对话手势，第一期仅 `pat_head`；最短时长与冷却由前端过滤，后端只校验白名单）：

```json
{"type":"interact","action":"pat_head","duration_ms":2400}
```

正常回复：`{"type":"chat_response","content":"...","emotion":"...","context_used":"...","latency":...}`。

`interact` 的回复同样是 `chat_response`，`context_used` 含 `interact+pat_head`；Planner 标 `reply_ok=false` 时 `content` 为空且带 `silence`，但 `emotion` 仍可用于换脸。对话进行中到达的 `interact` 会被丢弃；`interact` 生成中到达的 `chat` 会取消前者。

连接后若欢迎开启，服务端会再推一条 `chat_response`（`context_used` 含 `welcome`，节日当天首次则为 `festival`；凌晨/深夜节日可能再跟一条 `sleep`）。空闲搭话 / 照料 / goal 回访同样推 `chat_response`（`context_used` 含 `idle` / `breakfast` / `lunch` / `dinner` / `sleep` / `goal`）。Planner 标 `followup_ok` 时，同一轮用户消息后可能再跟一条 `chat_response`（`context_used` 含 `continue`）。关系层决定沉默或 Planner 标 `reply_ok=false` 时仍发 `chat_response`，但 `content` 为空、`context_used` 为 `silence` / `refuse`，前端保持安静并解除等待。

若 `content` 被判定为 ASR 脏文本，仍返回 `chat_response`，但 `context_used` 为 `"asr_filter"`，且不会进入双模型链路。