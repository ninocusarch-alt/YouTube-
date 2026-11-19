import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from launcher.key_validator import validate_api_key


class ApiKeyValidatorTests(unittest.TestCase):
    def test_valid_key_connects_and_closes(self) -> None:
        asr_agent = AsyncMock()
        translation_agent = AsyncMock()
        translation_agent.translate.return_value = '验证成功'
        with patch('launcher.key_validator.create_asr_agent', return_value=asr_agent), patch(
            'launcher.key_validator.QwenTranslationAgent', return_value=translation_agent
        ):
            asyncio.run(validate_api_key('sk-' + ('a' * 113)))
        asr_agent.connect.assert_awaited_once()
        translation_agent.translate.assert_awaited_once()
        asr_agent.close.assert_awaited_once()
        translation_agent.close.assert_awaited_once()

    def test_http_401_becomes_clear_user_message(self) -> None:
        asr_agent = AsyncMock()
        translation_agent = AsyncMock()
        asr_agent.connect.side_effect = RuntimeError('server rejected WebSocket connection: HTTP 401')
        with patch('launcher.key_validator.create_asr_agent', return_value=asr_agent), patch(
            'launcher.key_validator.QwenTranslationAgent', return_value=translation_agent
        ):
            with self.assertRaisesRegex(ValueError, '鉴权失败'):
                asyncio.run(validate_api_key('invalid-key'))
        asr_agent.close.assert_awaited_once()
        translation_agent.close.assert_awaited_once()

    def test_text_model_failure_is_reported_before_saving(self) -> None:
        asr_agent = AsyncMock()
        translation_agent = AsyncMock()
        translation_agent.translate.side_effect = RuntimeError('千问免费额度已用完。')
        with patch('launcher.key_validator.create_asr_agent', return_value=asr_agent), patch(
            'launcher.key_validator.QwenTranslationAgent', return_value=translation_agent
        ):
            with self.assertRaisesRegex(ValueError, '免费额度已用完'):
                asyncio.run(validate_api_key('valid-asr-only-key'))


if __name__ == '__main__':
    unittest.main()
