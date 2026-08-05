# Real-time AI Video Companion

这是一个给 YouTube 使用的 Chrome 实时双语理解助手。当前版本完全使用阿里云百炼千问：

```text
YouTube 声音
  -> Chrome 插件（每约 85 毫秒发送一小段 PCM 音频）
  -> 本机 FastAPI WebSocket
  -> 千问实时 ASR（英文立即显示）
  -> 短语切分器（标点 / 18 个词 / 最长 1.6 秒）
  -> 两路千问翻译并发处理
  -> YouTube 右侧双语记录 + 独立 AI 问答
```

OpenAI、DeepSeek 和本地 Whisper 均不再参与运行。API Key 只保存在 `backend/.env`，不会进入 Chrome 插件。

## 项目结构

```text
backend/
  app/main.py                 FastAPI 接口和实时 WebSocket
  app/services/agents.py      千问语音识别、翻译和聊天 Agent
  app/services/segmenter.py   实时短语切分，避免长句卡住
  app/services/session_store.py  完整双语记录和问答上下文
  .env                        本机密钥（不要分享）
extension/
  src/offscreen.ts            捕获声音、保留视频原声、生成 PCM
  src/background.ts           与后端保持 WebSocket 长连接
  src/content.ts              YouTube 右侧双语记录和聊天面板
  src/popup/                  插件控制面板
  dist/                       Chrome 实际加载的插件目录
```

## 第一次运行

### 1. 填写千问 API Key

用记事本打开：

```text
项目文件夹\backend\.env
```

找到下面这一行，把等号后面改成你自己的千问 Key：

```env
DASHSCOPE_API_KEY=你的千问APIKey
```

只改这一行，不要加引号，不要把 Key 发给别人。

`QWEN_ASR_MODEL` 必须是你的阿里云百炼账号中已开通的实时语音识别模型。如果控制台给出的模型名称不同，就把 `.env` 中这一项改成控制台显示的名称。中国内地和国际站的接口地址也可能不同，应以百炼控制台为准。

### 2. 启动后端

打开项目文件夹，在文件夹空白处按住 `Shift` 再点鼠标右键，选择“在终端中打开”。在打开的 PowerShell 窗口中，依次输入：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

最后一条命令运行后，这个 PowerShell 窗口不要关闭。浏览器打开下面地址：

```text
http://127.0.0.1:8000/api/health
```

看到 `"ok": true` 且 `"asr_configured": true`，说明 Key 已被读取。

### 3. 重新加载插件

1. 在 Chrome 地址栏输入 `chrome://extensions`。
2. 打开右上角“开发者模式”。
3. 如果插件已经存在，点击它下面的“重新加载”圆形箭头。
4. 如果还没有插件，点击“加载已解压的扩展程序”。
5. 选择项目中的 `extension\dist` 文件夹。

### 4. 使用

1. 打开一个 YouTube 英文视频并开始播放。
2. 点击 Chrome 右上角的扩展图标。
3. 点击“打开视频双语助手”。
4. 右侧面板会立即显示正在识别的英文。
5. 稳定的英文短语进入“双语记录”，中文完成后在原位置补上。
6. 点击任意英文记录，然后在“视频问答”中询问含义、语法或上下文。

暂停只会停止发送音频，不会让视频静音。按住面板顶部的“视频双语助手”标题栏即可自由拖动，位置会自动保存。关闭右侧面板后，页面右上角会保留一个 `AI` 按钮用于重新打开。插件面板仍可调整字体、透明度和中英文显示开关。

双语记录默认自动跟随最新内容。主动向上滚动、搜索或选择句子时会暂停跟随，并显示“回到最新”按钮；点击后立即恢复自动跟随。

## 常见问题

- `无法连接本地后端`：运行后端的 PowerShell 被关闭了，重新执行第 2 步。
- `Could not establish connection. Receiving end does not exist.`：通常发生在重新加载插件后继续使用旧 YouTube 标签页。新版会自动重新注入页面助手；请先在 `chrome://extensions` 重新加载最新构建，若仍出现再刷新一次 YouTube 页面。
- `DASHSCOPE_API_KEY` 未配置：`.env` 中等号后没有正确填写 Key，修改后重启后端。
- `model not found` 或 `model access denied`：当前账号没有开通 `.env` 中的 ASR 模型，按百炼控制台显示的实时 ASR 模型名称修改。
- 视频没有声音：在 `chrome://extensions` 重新加载插件，再刷新 YouTube 页面；音频节点会把原声送回扬声器。
- 中文仍比英文晚：这是一次云端翻译请求所需的时间。系统不会显示“翻译中”，也不会阻塞后续英文。
- 长句被拆成多条：这是低延迟策略。可以在 `.env` 调整 `SEGMENT_MAX_WORDS` 和 `SEGMENT_MAX_WAIT_SECONDS`。
- AI 问答不可用：问答要求实时会话仍处于运行或暂停状态；结束会话后只能查看已经保留在页面中的记录。

千问模型和地域端点会随百炼产品更新，请以[阿里云百炼官方文档](https://help.aliyun.com/zh/model-studio/)及你账号控制台显示的可用模型为准。
