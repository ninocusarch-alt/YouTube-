import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_COMPAT_SUFFIX = '/compatible-mode/v1'
_REALTIME_PATH = '/api-ws/v1/realtime'
_INFERENCE_PATH = '/api-ws/v1/inference'


class Settings(BaseSettings):
    # 阿里云百炼 MaaS 专属实例的兼容模式地址。设置后会同时用于
    # 翻译/问答的 HTTP 端点，并按实例规则推导实时 ASR 的 WebSocket 端点。
    # 用户显式配置的 QWEN_TRANSLATION_BASE_URL / QWEN_ASR_WS_URL 优先级更高。
    dashscope_base_url: str = ''
    dashscope_api_key: str = ''
    qwen_asr_ws_url: str = 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime'
    qwen_asr_model: str = 'qwen3-asr-flash-realtime'
    # auto（默认）：按模型名判断协议。可显式写 realtime / streaming 覆盖。
    qwen_asr_protocol: str = ''
    qwen_asr_language: str = 'en'
    qwen_asr_sample_rate: int = 16000
    qwen_vad_silence_ms: int = 400
    qwen_asr_vad_threshold: float = 0.0
    qwen_translation_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    qwen_translation_model: str = 'qwen-plus'
    qwen_translation_timeout_seconds: float = 12.0
    qwen_chat_model: str = 'qwen-plus'
    translation_workers: int = 2
    segment_min_words: int = 4
    segment_max_words: int = 18
    segment_max_wait_seconds: float = 1.6
    session_max_segments: int = 5000
    summary_batch_segments: int = 20
    session_database_path: str = ''
    backend_cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173,chrome-extension://*'

    model_config = SettingsConfigDict(extra='ignore')

    @model_validator(mode='after')
    def _apply_dashscope_base_url(self) -> 'Settings':
        """让 .env 里的 DASHSCOPE_BASE_URL 真正生效，并按 ASR 协议选端点。

        之前这个键被 extra='ignore' 静默丢弃，导致专属实例的 Key 被送到
        公共端点；而 qwen-audio-3.1-asr-flash-streaming 用的是
        /api-ws/v1/inference（run-task 协议），不是 /api-ws/v1/realtime。
        """
        base = self.dashscope_base_url.strip().rstrip('/')
        explicit = self.model_fields_set
        parts = urlsplit(base) if base else None

        if parts and 'qwen_translation_base_url' not in explicit:
            # 只给了 origin 时补齐兼容模式路径；已经带路径的保持原样。
            path = parts.path.rstrip('/')
            suffix = '' if path.endswith(_COMPAT_SUFFIX) else (
                _COMPAT_SUFFIX if path in ('', '/') else ''
            )
            self.qwen_translation_base_url = base + suffix

        if 'qwen_asr_ws_url' not in explicit:
            target_path = _INFERENCE_PATH if self.asr_is_streaming else _REALTIME_PATH
            if parts and parts.netloc:
                scheme = 'wss' if parts.scheme in ('https', 'wss') else 'ws'
                self.qwen_asr_ws_url = urlunsplit((scheme, parts.netloc, target_path, '', ''))
            elif self.asr_is_streaming:
                # 没配专属实例但用了 streaming 模型时，也要换 inference 路径。
                default_parts = urlsplit(self.qwen_asr_ws_url)
                scheme = 'wss' if default_parts.scheme in ('https', 'wss') else 'ws'
                self.qwen_asr_ws_url = urlunsplit(
                    (scheme, default_parts.netloc, _INFERENCE_PATH, '', '')
                )

        return self

    @property
    def asr_is_streaming(self) -> bool:
        protocol = self.qwen_asr_protocol.strip().lower()
        if protocol:
            return protocol in ('streaming', 'inference', 'dashscope')
        name = self.qwen_asr_model.lower()
        return 'asr-flash-streaming' in name or 'asr-flash-message' in name

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(',') if origin.strip()]

    @property
    def database_path(self) -> Path:
        if self.session_database_path.strip():
            return Path(self.session_database_path).expanduser().resolve()
        explicit_env = os.environ.get('VIDEO_COMPANION_ENV_FILE', '').strip()
        runtime_root = Path(explicit_env).expanduser().resolve().parent if explicit_env else Path(__file__).resolve().parents[1]
        return runtime_root / 'data' / 'video_companion.db'


@lru_cache
def get_settings() -> Settings:
    explicit_env = os.environ.get('VIDEO_COMPANION_ENV_FILE', '').strip()
    env_file = (
        Path(explicit_env).expanduser().resolve()
        if explicit_env
        else Path(__file__).resolve().parents[1] / '.env'
    )
    return Settings(_env_file=env_file, _env_file_encoding='utf-8')
