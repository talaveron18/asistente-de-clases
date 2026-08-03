# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import imageio_ffmpeg
import os

ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

datas = []
binaries = [(ffmpeg_exe, ".")]
hiddenimports = []
for paquete in ("customtkinter", "faster_whisper", "ctranslate2", "tokenizers", "av"):
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h

analysis = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "torchaudio", "pyannote", "matplotlib", "scipy", "pandas"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="AsistenteDeClases",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="AsistenteDeClases",
)
