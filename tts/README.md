# TTS 后端

语音合成有两套引擎，**同一时间只开一套**。默认使用官方引擎（GPT-SoVITS）。需要加速时，把客户端 `tts.backend` 改为 `minimal`，步骤见 [`gpt-sovits-minimal/DEPLOY.md`](gpt-sovits-minimal/DEPLOY.md)。

| 子目录 | 客户端 `tts.backend` | 端口 |
|--------|---------------------|------|
| [`gpt-sovits/`](gpt-sovits/DEPLOY.md) | `official` | 9880 |
| [`gpt-sovits-minimal/`](gpt-sovits-minimal/DEPLOY.md) | `minimal` | 8000 |

需要一块 **NVIDIA 显卡**（建议 8 GB 及以上显存）和 [VC++ x64 运行库](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)。

---

## 默认：官方引擎

### 1. 下载官方 GPT-SoVITS 整合包，解压到本仓库

打开（国内走第二条更快）：

- [Hugging Face 官方 Windows 整合包](https://huggingface.co/lj1995/GPT-SoVITS-windows-package)
- [语雀镜像说明](https://www.yuque.com/baicaigongchang1145haoyuangong/ib3g1e/dkxgpiy9zb96hob4#KTvnO)

把压缩包**里面的文件**解压到：

`（仓库根）\tts\gpt-sovits\`

解压完成后，这个文件夹里应能看到 `api_v2.py` 和 `runtime\python.exe`。

如果解压时提示覆盖 `go-apiv2.bat`、`DEPLOY.md`、`ref_audio`：**选跳过 / 不覆盖**。这些是本仓库的启动脚本和阿洛娜参考音频。

### 2. 放入阿洛娜声音模型（两个文件）

放到上一步那个文件夹里，路径必须是：

```
tts\gpt-sovits\GPT_weights_v2\ALuoNa_cn-e15.ckpt
tts\gpt-sovits\SoVITS_weights_v2\ALuoNa_cn_e16_s256.pth
```

没有这两个文件夹就自己新建。不要把它们放到仓库的 `models\` 里。

### 3. 启动

双击仓库根目录的 `start-all.bat`（或 PowerShell 里运行 `.\start-all.ps1`）。

第一次加载模型会等一两分钟。之后客户端说话应能出声。默认地址是本机 `127.0.0.1:9880`。

只开语音、不开后端时：进入 `tts\gpt-sovits` 双击 `go-apiv2.bat`。

仓库里如果还没有 `tts\gpt-sovits\go-apiv2.bat`（例如只下了客户端安装包），从 [Releases](https://github.com/xiahy456/AronaArchive/releases) 再下 `AronaArchive_GPTSoVITS_v*_x64.zip`，解压到仓库根（和 `start-all.ps1` 放在一起）。

---

## 可选：minimal

先完成上面官方三步（权重和预训练仍放在 `tts\gpt-sovits\`），再按 [`gpt-sovits-minimal/DEPLOY.md`](gpt-sovits-minimal/DEPLOY.md) 部署。客户端 `config.json` 里设 `"backend": "minimal"`，然后重新 `start-all`。不要和官方 TTS 同时开。

---

## 维护者

| 目的 | 命令 |
|------|------|
| 打包 TTS 脚本与参考音频 | 仓库根 `.\pack-tts.ps1` |
| 制作 minimal 便携 Python | `tts\gpt-sovits-minimal\pack-runtime.ps1` |
| 本机一键 | `.\start-all.ps1` |

异机、端口、故障表见各子目录 `DEPLOY.md`。日志在仓库根 `.start-logs\gpt-sovits.log`。不要修改上游 clone 里的源码。
