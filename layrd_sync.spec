# PyInstaller spec for Layrd Sync Agent
# Build with: pyinstaller layrd_sync.spec
# Produces two executables: LayrdSync.exe (release, no console) and LayrdSyncDebug.exe (with console)

import os

block_cipher = None

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('layrd_sync/assets', 'layrd_sync/assets'),
    ],
    hiddenimports=[
        'pystray._win32',
        'pystray._darwin',
        'layrd_sync.settings_runner',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, cipher=block_cipher)

# Release build — no console window, runs silently in the tray
exe_release = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LayrdSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='layrd_sync/assets/icon.ico',
)

# Debug build — console window visible for troubleshooting
exe_debug = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LayrdSyncDebug',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon='layrd_sync/assets/icon.ico',
)
