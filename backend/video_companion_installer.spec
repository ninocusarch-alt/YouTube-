# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path


backend_root = Path(SPECPATH)
payload_root = Path(os.environ['VIDEO_COMPANION_INSTALLER_PAYLOAD']).resolve()

analysis = Analysis(
    [str(backend_root / 'installer' / 'main.py')],
    pathex=[str(backend_root)],
    binaries=[],
    datas=[(str(payload_root), 'payload')],
    hiddenimports=[],
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
    analysis.binaries,
    analysis.datas,
    [],
    name='VideoCompanionSetup',
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
