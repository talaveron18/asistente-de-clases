# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import imageio_ffmpeg

ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

datas = []
binaries = [(ffmpeg_exe, ".")]
hiddenimports = ["pypdf", "docx", "sounddevice"]

for paquete in (
    "customtkinter",
    "faster_whisper",
    "ctranslate2",
    "tokenizers",
    "av",
    "sounddevice",
):
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h

analysis = Analysis(
    ["argos_app.py"],
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
    name="ARGOS",
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
    name="ARGOS",
)
