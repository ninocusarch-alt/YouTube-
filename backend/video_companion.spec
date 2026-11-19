# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


backend_root = Path(SPECPATH)
datas = []
binaries = []
hiddenimports = collect_submodules('app') + collect_submodules('launcher')

package_names = [
    'anyio',
    'fastapi',
    'httpx',
    'pydantic',
    'pydantic_settings',
    'starlette',
    'uvicorn',
    'websockets',
]
try:
    import pyaudiowpatch  # noqa: F401 - optional WASAPI capture backend
    package_names.append('pyaudiowpatch')
except ImportError:
    pass

for package_name in package_names:
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports


analysis = Analysis(
    [str(backend_root / 'launcher' / 'main.py')],
    pathex=[str(backend_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name='VideoCompanionBackend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VideoCompanionBackend',
)
