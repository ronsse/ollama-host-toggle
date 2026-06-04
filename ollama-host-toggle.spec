# PyInstaller spec — build a windowless ollama-host-toggle.exe.
#   pip install pyinstaller
#   pyinstaller ollama-host-toggle.spec
# Output: dist/ollama-host-toggle.exe  (reads config.toml from its working dir;
# creates one with a generated token on first run if missing)

# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ["ollama_host_toggle/__main__.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["pystray._win32"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ollama-host-toggle",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # windowless
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/ollama-host-toggle.ico",
)
