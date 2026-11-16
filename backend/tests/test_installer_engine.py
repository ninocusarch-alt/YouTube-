import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from installer.install_engine import install_payload


class InstallEngineTests(unittest.TestCase):
    def _payload(self, root: Path, marker: str) -> Path:
        payload = root / f'payload-{marker}'
        payload.mkdir()
        (payload / 'VideoCompanionBackend.exe').write_text(marker, encoding='utf-8')
        (payload / '.env.example').write_text('DASHSCOPE_API_KEY=\n', encoding='utf-8')
        (payload / 'extension').mkdir()
        return payload

    def test_fresh_install_copies_payload(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'Programs' / 'VideoCompanion'
            install_payload(self._payload(root, 'v1'), target)
            self.assertEqual((target / 'VideoCompanionBackend.exe').read_text(encoding='utf-8'), 'v1')

    def test_upgrade_preserves_api_key_and_history(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'Programs' / 'VideoCompanion'
            install_payload(self._payload(root, 'v1'), target)
            (target / '.env').write_text('DASHSCOPE_API_KEY=private-value\n', encoding='utf-8')
            (target / 'data').mkdir()
            (target / 'data' / 'history.db').write_text('history', encoding='utf-8')

            install_payload(self._payload(root, 'v2'), target)

            self.assertEqual((target / 'VideoCompanionBackend.exe').read_text(encoding='utf-8'), 'v2')
            self.assertEqual((target / '.env').read_text(encoding='utf-8'), 'DASHSCOPE_API_KEY=private-value\n')
            self.assertEqual((target / 'data' / 'history.db').read_text(encoding='utf-8'), 'history')


if __name__ == '__main__':
    unittest.main()
