import asyncio

from app.config import get_settings
from app.services.agents import QwenRealtimeASRAgent, QwenTranslationAgent


async def validate_api_key(api_key: str) -> None:
    settings = get_settings().model_copy(update={'dashscope_api_key': api_key})
    asr_agent = QwenRealtimeASRAgent(settings)
    translation_agent = QwenTranslationAgent(settings)
    try:
        await asr_agent.connect()
        await translation_agent.translate('API key verification.', '')
    except Exception as exc:
        message = str(exc)
        if '401' in message:
            raise ValueError('API Key 鉴权失败，请确认 Key 完整、有效且已开通实时语音识别。') from exc
        raise ValueError(f'无法验证 API Key：{message}') from exc
    finally:
        await asr_agent.close()
        await translation_agent.close()


def validate_api_key_sync(api_key: str) -> None:
    asyncio.run(validate_api_key(api_key))
