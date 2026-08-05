# 本地语音识别说明

语音识别使用 `faster-whisper`，不需要 OpenAI API。

模型建议：

- `tiny.en`：电脑较慢时使用，速度快但准确率较低
- `base.en`：默认推荐，速度和准确率比较平衡
- `small.en`：准确率更高，但占用更多内存和 CPU

如果电脑运行很慢，可以把 `.env` 中的模型改成：

```env
LOCAL_ASR_MODEL=tiny.en
```

字幕仍然会经过 DeepSeek 翻译，因此必须填写 `DEEPSEEK_API_KEY`。
