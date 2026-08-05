# 纯 DeepSeek 配置

本项目现在不再调用 OpenAI：

- 本地 faster-whisper：负责把 YouTube 英语语音转成英文文字
- DeepSeek API：负责把英文文字翻译成中文字幕

打开 `backend/.env`，确认至少包含：

```env
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
TRANSLATION_BASE_URL=https://api.deepseek.com
TRANSLATION_MODEL=deepseek-v4-flash
LOCAL_ASR_MODEL=base.en
LOCAL_ASR_DEVICE=cpu
LOCAL_ASR_COMPUTE_TYPE=int8
LOCAL_ASR_BEAM_SIZE=5
```

旧的 `OPENAI_API_KEY` 配置已经不会被程序读取，可以从 `.env` 中删除。

第一次启动或第一次处理音频时，faster-whisper 会下载 `base.en` 语音模型。模型下载完成后，语音识别在本地电脑执行，不会调用 OpenAI。

修改 `.env` 后，重新安装依赖并启动后端：

```powershell
cd "C:\Users\ninoc\Documents\YouTube视频智能翻译\backend"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

打开 `http://127.0.0.1:8000/api/health`，应看到：

```json
{
  "asr_provider": "local-faster-whisper",
  "translation_provider": "deepseek",
  "translation_configured": true
}
```

API Key 只放在后端 `.env`，不要放到 Chrome 插件代码中，也不要发给别人。
