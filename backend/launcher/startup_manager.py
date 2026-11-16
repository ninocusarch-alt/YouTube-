import os
import sys
from pathlib import Path
from typing import Callable

from launcher.windows_shortcut import create_shortcut, remove_shortcut


STARTUP_SHORTCUT_NAME = 'Real-time AI Video Companion.lnk'


class StartupManager:
    def __init__(
        self,
        target_path: Path,
        *,
        arguments: str = '--minimized',
        startup_directory: Path | None = None,
        shortcut_creator: Callable[..., None] = create_shortcut,
        shortcut_remover: Callable[[Path], None] = remove_shortcut,
    ) -> None:
        self.target_path = target_path.resolve()
        self.arguments = arguments
        appdata = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        self.startup_directory = startup_directory or (
            appdata / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'
        )
        self.shortcut_creator = shortcut_creator
        self.shortcut_remover = shortcut_remover

    @property
    def shortcut_path(self) -> Path:
        return self.startup_directory / STARTUP_SHORTCUT_NAME

    def is_enabled(self) -> bool:
        return self.shortcut_path.exists()

    def enable(self) -> None:
        self.shortcut_creator(
            self.shortcut_path,
            self.target_path,
            arguments=self.arguments,
            working_directory=self.target_path.parent,
            description='开机后自动启动 Real-time AI Video Companion',
        )

    def disable(self) -> None:
        self.shortcut_remover(self.shortcut_path)

    def toggle(self) -> bool:
        if self.is_enabled():
            self.disable()
            return False
        self.enable()
        return True


def current_startup_manager() -> StartupManager:
    if getattr(sys, 'frozen', False):
        return StartupManager(Path(sys.executable))
    main_file = Path(__file__).resolve().parent / 'main.py'
    return StartupManager(Path(sys.executable), arguments=f'"{main_file}" --minimized')
