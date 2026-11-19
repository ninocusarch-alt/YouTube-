"""Silent in-place upgrade of the installed EXE.

Equivalent to running VideoCompanionSetup.exe and choosing "install without
autostart", but with no modal dialogs, no automatic program launch and no
browser window. Uses the project's own install_engine so the .env and data
directory are preserved by the same code path a real install would use.

Usage:  .venv\\Scripts\\python.exe scripts\\silent_install.py
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
PAYLOAD = BACKEND / 'build' / 'installer_payload'
SETUP = PROJECT / 'release' / 'installer' / 'VideoCompanionSetup.exe'
TARGET = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'RealTimeAIVideoCompanion'
BACKUP_HINT = 'VIDEO_COMPANION_BACKUP_DIR'


def load_install_engine():
    path = BACKEND / 'installer' / 'install_engine.py'
    spec = importlib.util.spec_from_file_location('_install_engine', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def top_level_backups(backup_dir: Path) -> list[Path]:
    if not backup_dir.is_dir():
        return []
    return [p for p in backup_dir.iterdir() if '.bak' in p.name]


def main() -> int:
    if not (PAYLOAD / 'VideoCompanionBackend.exe').is_file():
        print(f'FAIL: payload missing at {PAYLOAD}')
        return 1
    if not SETUP.is_file():
        print(f'FAIL: installer missing at {SETUP}')
        return 1

    engine = load_install_engine()
    env_before = (TARGET / '.env').read_bytes() if (TARGET / '.env').is_file() else b''
    data_before = sorted(p.name for p in (TARGET / 'data').iterdir()) if (TARGET / 'data').is_dir() else []

    backup_dir = Path(os.environ.get(BACKUP_HINT, '')).resolve() if os.environ.get(BACKUP_HINT) else None
    saved = top_level_backups(backup_dir) if backup_dir else []
    print(f'target       : {TARGET}')
    print(f'payload      : {PAYLOAD}')
    print(f'backup extras: {[p.name for p in saved]}')

    engine.install_payload(PAYLOAD, TARGET)
    print('payload installed')

    for item in saved:
        destination = TARGET / item.name
        if destination.exists():
            continue
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)
        print(f'restored {item.name}')

    shutil.copy2(SETUP, TARGET / 'Uninstall.exe')
    print('uninstaller refreshed')

    env_after = (TARGET / '.env').read_bytes() if (TARGET / '.env').is_file() else b''
    data_after = sorted(p.name for p in (TARGET / 'data').iterdir()) if (TARGET / 'data').is_dir() else []
    print(f'.env preserved : {bool(env_before) and env_before == env_after}')
    print(f'data preserved : {data_before == data_after} ({len(data_after)} entries)')
    print(f'new exe        : {(TARGET / "VideoCompanionBackend.exe").stat().st_size} bytes')
    print(f'live overlay   : {(TARGET / "live" / "web" / "overlay.html").is_file()}')
    print(f'live console   : {(TARGET / "live" / "web" / "console.html").is_file()}')
    return 0 if env_before == env_after and data_before == data_after else 1


if __name__ == '__main__':
    sys.exit(main())
