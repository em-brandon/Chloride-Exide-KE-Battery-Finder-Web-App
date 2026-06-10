# PyInstaller spec for the Pipeline App
# Usage (from pipeline_app/):
#   bun --cwd frontend run build
#   pyinstaller pipeline_app.spec

import os
from __version__ import __version__

block_cipher = None

a = Analysis(
    ['launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Bundle the compiled React frontend
        ('frontend/dist',   'frontend/dist'),
        # Seed cache files (pipeline writes updates next to the exe at runtime)
        ('cache',           'cache'),
        # Bundle shared project modules from one level up
        ('../models.py',    '.'),
        ('../db.py',        '.'),
        ('../admin_auth.py','.'),
        # pipeline.env is NOT bundled — it lives next to the exe (contains DATABASE_URL)
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'email.mime.text',
        'email.mime.multipart',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PipelineApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='../assets/icon.ico',  # swap for actual icon if available
    version_file=None,
)
