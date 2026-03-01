# PyInstaller spec for Layrd Sync Agent
# Build with: pyinstaller layrd_sync.spec

a = Analysis(
    ['layrd_sync/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pystray._win32',   # Windows tray backend
        'pystray._darwin',  # macOS tray backend (for dev)
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
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
    console=False,  # No console window — runs as tray app
    icon=None,      # TODO: add icon.ico
)
