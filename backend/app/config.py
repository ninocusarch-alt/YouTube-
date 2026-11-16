import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    dashscope_api_key: str = ''
    qwen_asr_ws_url: str = 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime'
    qwen_asr_model: str = 'qwen3-asr-flash-realtime'
    qwen_asr_language: str = 'en'
    qwen_asr_sample_rate: int = 16000
    qwen_vad_silence_ms: int = 400
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
