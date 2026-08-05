# 纯 DeepSeek 运行模式

后端现在采用：

```text
YouTube 音频 → 本地 faster-whisper → 英文文字 → DeepSeek → 中文字幕
```

不再调用 OpenAI API。配置和启动步骤请查看 `DEEPSEEK_SETUP.md`。
