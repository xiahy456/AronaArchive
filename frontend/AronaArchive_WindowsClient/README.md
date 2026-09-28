# AronaArchive Windows 桌面客户端

基于 Qt/C++ + Spine 2D 的 Windows 桌面客户端，经 WebSocket 对接后端，可接 GPT-SoVITS TTS 与腾讯云 ASR。

日常使用请从仓库 [Releases](https://github.com/xiahy456/AronaArchive/releases) 下载安装包或便携 zip，配置见下文。需要自行编译时，按本节构建。

## 客户端构建

Windows 客户端使用 Visual Studio 2026 和 Qt 构建：

1. 安装 [Qt 6.x](https://www.qt.io/download)（推荐 6.5.3）和 [Visual Studio 2026](https://visualstudio.microsoft.com/)，并在 VS 2026 中安装 `Qt VS Tools` 扩展
2. 确保你拥有 v143 (Visual Studio 2022) 平台工具集，在该项目中需要使用此平台工具集
3. 确保你拥有 Qt 6.5.3 的 `msvc2019_64`，该项目中需要使用此 Qt 版本（Qt Version 可在 `Qt VS Tools` 的设置中配置）
4. 打开本目录下的 `AronaArchive_WindowsClient.sln`
5. 配置 Qt 版本和编译选项
6. 编译运行

使用仓库根目录 `pack-client.ps1` 打包客户端，会自动写入与包内布局一致的相对路径，并输出两份文件：一份保留配置文件中的腾讯云 SecretId 和 SecretKey，另一份删除。

### 启动前准备

在启动客户端之前，请完成以下准备工作：

**配置 `config.json`**

将 [`Config/config.example.json`](Config/config.example.json) 复制并重命名，然后至少填写以下关键项：

```bash
# 复制并重命名配置文件
cp Config/config.example.json Config/config.json
```

```json
{
  "aronalm": {
    "websocket_url": "ws://your.aronalm.ip:20456/ws" // AronaLM 后端 WebSocket 地址
  },
  "tts": {
    "host": "your.gpt.sovits.ip" // GPT-SoVITS 服务地址
  },
  "tencent_speech_recognizer": {
    "secret_id": "${TENCENT_SECRET_ID}", // 腾讯云语音识别 SecretId（可用环境变量占位）
    "secret_key": "${TENCENT_SECRET_KEY}" // 腾讯云语音识别 SecretKey（可用环境变量占位）
  }
}
```

完整字段说明见下文「配置说明」。

> **注意**：
> - 资源路径相对**程序工作目录**解析；在 Visual Studio 中调试时默认为项目根目录，请勿直接双击 `x64/Debug` 或 `x64/Release` 下的 exe（工作目录会不对）。
> - 请将 AronaLM 后端服务、GPT-SoVITS 服务的地址、端口按实际情况填写。
> - `tts.request_timeout_ms` 仅改配置即可生效（dist 客户端同理）；`TTSManager` / `MainController` 源码改动需重新编译客户端后才有超时、预热与合成/播放解耦逻辑。
> - `tts.refs` 为表情到参考音频的扁平数组（`emotion` / `ref_audio_path` / `prompt_text`）。加音频或改某表情绑定只改该数组；路径相对官方 GPT-SoVITS 工作目录（`tts/gpt-sovits/`）。`backend=minimal` 时客户端自动加 `../gpt-sovits/` 前缀（相对 minimal 工作目录 `tts/gpt-sovits-minimal/`）。未列出的表情回退顶层 `ref_audio_path` / `prompt_text`。已有 `config.json` 需自行并入该数组，否则仍只用默认参考音频。
> - 本项目使用**腾讯云语音识别**（ASR），腾讯云 ASR 的 SecretId 和 SecretKey 可以在腾讯云控制台的 API 密钥管理中获取。
> - `config.json` 已在 `.gitignore` 中，不会被提交到版本控制，请放心修改。

## 配置说明

配置文件位于 `Config/`（由 [`Config/config.example.json`](Config/config.example.json) 复制为 `config.json`，已 gitignore）。完整示例如下：

```json
{
  "settings": {
    "frame_rate": 60, // 全局帧率
    "dict_path": "Dict/dict_zh.json", // 词典文件路径
    "zoom": 1.0, // 界面缩放比例
    "transparent": 1.0, // 主窗口整体不透明度（0.0~1.0）
    "offset_from_screen_bottom": -50, // 主窗口相对屏幕底部的向上偏移（像素）
    "offset_from_screen_left": 0, // 主窗口相对屏幕左侧的向右偏移（像素）
    "output_text_box_offset": -50, // 输出文本框相对默认位置的垂直偏移（像素；正值向上，负值向下）
    "mouse_event_transparent": true, // 是否启用鼠标穿透（点击穿透桌宠）
    "open_setting_widget": false, // 启动时是否自动打开设置窗口
    "image_input": true, // 聊天/语音是否附带屏幕截图
    "compress_screenshot": false, // 是否压缩聊天/语音截图；默认不压缩（原分辨率 JPEG 95）。true 时缩到 1280 宽、JPEG 70 以节省 IO
    "arona_ai_mode": 0, // 阿洛娜 AI 模式：0=日程模式，1=档案模式（待实现）
  },
  "aronalm": {
    "websocket_url": "ws://your.aronalm.ip:20456/ws", // AronaLM 后端 WebSocket 地址
    "heartbeat_interval": 30000, // 心跳发送间隔（毫秒）
    "heartbeat_timeout": 10000, // 心跳超时时间（毫秒）
    "reconnect_interval": 3000, // 断线重连间隔（毫秒）
    "max_reconnect_attempts": 5, // 最大重连次数
    "use_rag": true, // 是否启用知识库 RAG 检索
    "use_memory": true // 是否启用长期记忆
  },
  "computer_use": {
    "enabled": false, // 是否允许阿洛娜操作老师的电脑；需与后端 computer_use.enabled 同时打开
    "compress_screenshot": false, // 是否压缩电脑操作截图；默认不压缩（原分辨率 JPEG 95）。true 时缩到 1280 宽、JPEG 70 以节省 IO
    "click_settle_ms": 2000 // 点击后等待再截图的毫秒数；缺省或负值回退 2000，0 表示立即截图。需小于后端 observation_timeout_sec
  },
  "spine": {
    "skelOrJson_path": "Assets/AronaSpineAssets/arona_spr_full.json", // Spine 骨架文件（.skel / .json）路径（如果想要普拉娜可以改为Assets/AronaSpineAssets/NP0035_spr.skel）
    "atlas_path": "Assets/AronaSpineAssets/arona_spr_full.atlas", // Spine 图集 atlas 路径（如果想要普拉娜可以改为Assets/AronaSpineAssets/NP0035_spr.atlas）
    "animation_default_mix": 0.2 // 动画默认过渡混合时间（秒）
  },
  "tts": {
    "backend": "official", // official = 官方 api_v2（:9880）；minimal = GPT-SoVITS_minimal_inference（:8000）
    "host": "your.gpt.sovits.ip", // 官方 GPT-SoVITS 服务地址
    "port": 9880, // 官方 GPT-SoVITS 服务端口
    "minimal_host": "127.0.0.1", // minimal 后端地址（backend=minimal 时使用）
    "minimal_port": 8000, // minimal 后端端口
    "voice": "arona", // minimal 的 voices.json 条目名
    "gpt_path": "GPT_weights_v2/ALuoNa_cn-e15.ckpt", // 推荐的 GPT 模型权重路径（服务端侧；仅 official 热切权重）
    "sovits_path": "SoVITS_weights_v2/ALuoNa_cn_e16_s256.pth", // 推荐的 SoVITS 模型权重路径（服务端侧）
    "ref_audio_path": "ref_audio/Arona/arona_academy_in_1.ogg", // 预热与缺表回退用的参考音频路径（相对 GPT-SoVITS 工作目录）
    "prompt_text": "老师可以在这里做您的日程表哦!", // 上述默认参考音频对应的提示文本
    "prompt_lang": "zh", // 提示文本语言
    "top_k": 15, // Top-K 采样
    "top_p": 1.0, // Top-P 采样
    "temperature": 1.0, // 采样温度
    "text_split_method": "cut0", // 文本分割方法
    "batch_size": 1, // 批处理大小
    "batch_threshold": 0.75, // 批处理阈值
    "split_bucket": true, // 是否按桶分割推理
    "speed_factor": 1.0, // 语速因子
    "fragment_interval": 0.3, // 片段间隔（秒）
    "seed": -1, // 随机种子（-1 表示随机）
    "parallel_infer": true, // 是否启用并行推理（8GB 显卡建议 false）
    "reload_weights_on_start": false, // 启动时是否再调 /set_gpt_weights 与 /set_sovits_weights；默认 false，沿用 api 已从 yaml 加载的权重，避免打掉参考音频缓存
    "streaming": true, // 是否流式接收 TTS 并边收边播。true 时官方请求 streaming_mode=true；minimal 始终 chunked，此开关只控制客户端是否首包开播。缺省 false（整包返回）
    "request_timeout_ms": 45000, // 客户端等待 /tts 的超时（毫秒）；超时后仍显示字幕，不卡死 UI
    "repetition_penalty": 1.35, // 重复惩罚系数
    "sample_steps": 32, // 采样步数
    "super_sampling": false, // 是否启用超采样
    "refs": [ // 表情 → 参考音频；增删或改绑定只改本数组，不必重编译。完整 29 条见 Config/config.example.json
      {
        "emotion": "normal",
        "ref_audio_path": "ref_audio/Arona/arona_academy_in_1.ogg",
        "prompt_text": "老师可以在这里做您的日程表哦!"
      },
      {
        "emotion": "worried",
        "ref_audio_path": "ref_audio/Arona/arona_work_talk_6.ogg",
        "prompt_text": "呜哇哇...还有这么多工作需要处理啊."
      },
      {
        "emotion": "angry",
        "ref_audio_path": "ref_audio/Arona/arona_r53_2_worldraidmap_in_2.ogg",
        "prompt_text": "这就是最后的决斗了.老师,我们一起加油吧!"
      },
      {
        "emotion": "sleep",
        "ref_audio_path": "ref_audio/Arona/arona_work_sleep_talk_4.ogg",
        "prompt_text": "我才没有打瞌睡呢...唔喵."
      }
    ]
  },
  "audio_input": {
    "device": "" // 音频输入设备名（空字符串表示使用系统默认设备）
  },
  "short_cut_key": {
    "switch_audio_input": "Ctrl+Alt+V", // 切换 / 触发语音输入的快捷键
    "switch_mouse_transparent": "Ctrl+Alt+C", // 切换 / 触发鼠标穿透的快捷键
    "show_user_input": "Ctrl+Alt+T",// 显示用户输入的快捷键
    "switch_image_input": "Ctrl+Alt+X",// 切换 / 触发图像输入的快捷键
    "cancel_computer_use": "Ctrl+Alt+S"// 取消当前电脑操作（computer use）的快捷键
  },
  "tencent_speech_recognizer": {
    "secret_id": "${TENCENT_SECRET_ID}", // 腾讯云 SecretId（可用环境变量占位）
    "secret_key": "${TENCENT_SECRET_KEY}", // 腾讯云 SecretKey（可用环境变量占位）
    "app_id": "${TENCENT_APP_ID}", // 腾讯云应用 ID（可用环境变量占位）
  }
}
```

> **注意**：
> - 资源路径相对**程序工作目录**解析；在 Visual Studio 中调试时默认为项目根目录，请勿直接双击 `x64/Debug` 或 `x64/Release` 下的 exe（工作目录会不对）。
> - `tts.refs` 路径相对 **官方 GPT-SoVITS 工作目录**（`tts/gpt-sovits/`）。
> - `tts.backend` 为 `minimal` 时走 `POST /v1/audio/speech`（`minimal_host`/`minimal_port`）；缺省 `official` 仍走 `/tts`。同一时间只启动一套 TTS。部署步骤见仓库 [`tts/README.md`](../../tts/README.md)。
> - `config.json` 已在 `.gitignore` 中，不会被提交到版本控制。
