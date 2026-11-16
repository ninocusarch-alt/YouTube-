import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from launcher.startup_manager import StartupManager
from launcher.windows_shortcut import create_shortcut


class StartupManagerTests(unittest.TestCase):
    def test_toggle_creates_and_removes_startup_shortcut(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'VideoCompanionBackend.exe'
            target.touch()
            calls: list[tuple[Path, Path, str]] = []

            def fake_create(shortcut: Path, executable: Path, **kwargs) -> None:
                calls.append((shortcut, executable, kwargs['arguments']))
                shortcut.parent.mkdir(parents=True, exist_ok=True)
                shortcut.touch()

            manager = StartupManager(
                target,
                startup_directory=root / 'Startup',
                shortcut_creator=fake_create,
            )
            self.assertFalse(manager.is_enabled())
            self.assertTrue(manager.toggle())
            self.assertTrue(manager.is_enabled())
            self.assertEqual(calls[0][2], '--minimized')
            self.assertFalse(manager.toggle())
            self.assertFalse(manager.is_enabled())

    def test_real_windows_shortcut_is_created_in_temporary_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target.exe'
            target.touch()
            shortcut = root / 'target.lnk'
            create_shortcut(shortcut, target, arguments='--minimized')
            self.assertTrue(shortcut.is_file())
            self.assertGreater(shortcut.stat().st_size, 100)


if __name__ == '__main__':
    unittest.main()
