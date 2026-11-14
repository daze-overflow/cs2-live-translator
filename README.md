# CS2 Live Translator

用于 YouTube 英文 CS2 直播和回放的 Chrome 扩展。保留英文原声，在播放器内叠加中文字幕，可选显示英文识别文本。支持全屏、字幕样式调整，以及按当前标题或章节匹配队伍和选手词表。

**当前版本为 0.6.0 公开实验版。** 已在 Windows 11 的 Chrome 回放中验证一键启动与全屏字幕。队名、人名和短句仍可能误识别或误译，实际语音到屏幕的延迟仍待测量。

## 首次安装

需要 Windows 11 x64、Chrome 116 或以上、支持项目 CUDA 运行库的 NVIDIA 显卡及驱动、Python 3.12 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。首次安装会下载约 4.3 GB 的模型和运行库，另需为解压和转换保留磁盘空间。

1. 下载仓库源码并解压到固定目录，或通过 Git 克隆。
2. 打开 Chrome 的扩展管理页（`chrome://extensions`），开启“开发者模式”，选择“加载已解压的扩展程序”，指向项目中的 `extension` 目录。
3. 在项目根目录打开 PowerShell，运行：

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
   ```

安装脚本会创建项目虚拟环境，下载并校验固定版本的资源，生成本机连接令牌，并为当前 Windows 用户登记 Chrome 启动器。请使用平时观看 YouTube 的 Chrome 配置文件加载扩展。若脚本未找到扩展，可从扩展管理页复制扩展 ID，在模型准备完成后手动登记：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-native-host.ps1 -ExtensionId '<扩展 ID>'
```

## 使用

打开 YouTube 直播或回放，点击扩展里的“开始中文字幕”。首次使用会等待本机模型加载，弹窗会显示进度。结束时点“停止中文字幕”。字号、距底部距离、宽度、透明度及英文行开关可在弹窗调整。

日常使用由扩展通过 Chrome Native Messaging 启动后端。`start.ps1` 可用于手动诊断。移动项目目录后，需要在 Chrome 重新加载新位置的扩展，并执行一次 `install-launcher.cmd` 更新启动器登记。 [Chrome 本机通信文档](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)

## 本地处理

语音识别使用 Nemotron Speech Streaming EN 0.6B，翻译使用 Qwen3-4B Q4_K_M。模型和运行库从上游准备。翻译期间，音频通过本机 WebSocket 传送到本机模型。运行记录及识别和翻译文本会写入 `evidence/`。 [NeMo-Speech.cpp v0.3.0](https://github.com/NVIDIA/NeMo-Speech.cpp/releases/tag/v0.3.0) · [llama.cpp b11960](https://github.com/ggml-org/llama.cpp/releases/tag/b11960) · [Qwen3-4B-GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF/tree/bc640142c66e1fdd12af0bd68f40445458f3869b)

## 开发测试

安装 Python 依赖后可运行单元测试，JavaScript 测试需要 Node.js。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
npm test
```
