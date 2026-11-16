import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import get_settings
from launcher.config_store import ConfigStore, MAX_API_KEY_LENGTH
from launcher.runtime_paths import ENV_FILE_VARIABLE, resolve_env_file, resolve_runtime_dir


class RuntimePathsTests(unittest.TestCase):
    def test_source_runtime_dir_is_backend_folder(self) -> None:
        runtime_dir = resolve_runtime_dir(frozen=False)
        self.assertEqual(runtime_dir, Path(__file__).resolve().parents[1])

    def test_explicit_env_path_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            expected = Path(temp_dir) / 'custom.env'
            with patch.dict(os.environ, {ENV_FILE_VARIABLE: str(expected)}):
                self.assertEqual(resolve_env_file(), expected.resolve())

    def test_settings_read_explicit_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / '.env'
            env_file.write_text(
                'DASHSCOPE_API_KEY=sk-explicit-test\nQWEN_CHAT_MODEL=qwen-custom\n',
                encoding='utf-8',
            )
            with patch.dict(os.environ, {ENV_FILE_VARIABLE: str(env_file)}):
                get_settings.cache_clear()
                settings = get_settings()
                self.assertEqual(settings.dashscope_api_key, 'sk-explicit-test')
                self.assertEqual(settings.qwen_chat_model, 'qwen-custom')
            get_settings.cache_clear()


class ConfigStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.env_file = self.root / '.env'
        self.template_file = self.root / '.env.example'
        self.template_file.write_text(
            'DASHSCOPE_API_KEY=\nQWEN_ASR_MODEL=qwen-test\n',
            encoding='utf-8',
        )
        self.store = ConfigStore(self.env_file, self.template_file)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ensure_exists_copies_public_template(self) -> None:
        self.store.ensure_exists()
        self.assertTrue(self.env_file.exists())
        self.assertIn('QWEN_ASR_MODEL=qwen-test', self.env_file.read_text(encoding='utf-8'))

    def test_save_api_key_preserves_other_settings(self) -> None:
        self.store.ensure_exists()
        self.store.save_api_key('sk-test-secret-value')
        content = self.env_file.read_text(encoding='utf-8')
        self.assertIn('DASHSCOPE_API_KEY=sk-test-secret-value', content)
        self.assertIn('QWEN_ASR_MODEL=qwen-test', content)
        self.assertTrue(self.store.is_configured())

    def test_save_api_key_rejects_newlines(self) -> None:
        with self.assertRaises(ValueError):
            self.store.save_api_key('first-line\nSECOND_VARIABLE=leak')

    def test_long_api_key_is_saved_without_truncation(self) -> None:
        api_key = 'sk-' + ('a' * 113)
        self.store.save_api_key(api_key)
        self.assertEqual(self.store.read_value('DASHSCOPE_API_KEY'), api_key)

    def test_save_api_key_rejects_internal_whitespace_and_excessive_length(self) -> None:
        with self.assertRaises(ValueError):
            self.store.save_api_key('sk-invalid key')
        with self.assertRaises(ValueError):
            self.store.save_api_key('x' * (MAX_API_KEY_LENGTH + 1))

    def test_masked_api_key_never_returns_full_secret(self) -> None:
        self.store.ensure_exists()
        self.store.save_api_key('sk-test-secret-value')
        masked = self.store.masked_api_key()
        self.assertNotEqual(masked, 'sk-test-secret-value')
        self.assertTrue(masked.startswith('sk-t'))
        self.assertTrue(masked.endswith('alue'))


if __name__ == '__main__':
    unittest.main()
