# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

liteparse_datas, liteparse_binaries, liteparse_hiddenimports = collect_all("liteparse")
pyaudio_datas, pyaudio_binaries, pyaudio_hiddenimports = collect_all("pyaudiowpatch")

analysis = Analysis(
    ["app/local_helper.py"],
    pathex=["."],
    binaries=[*liteparse_binaries, *pyaudio_binaries],
    datas=[*liteparse_datas, *pyaudio_datas],
    hiddenimports=[
        *liteparse_hiddenimports,
        *pyaudio_hiddenimports,
        "_portaudiowpatch",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "asyncpg",
        "fastapi",
        "groq",
        "openai",
        "ollama",
        "silero_vad",
        "uvicorn",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="copilot-local-helper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)