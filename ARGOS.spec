# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import shutil

import imageio_ffmpeg
from PyInstaller.utils.hooks import collect_data_files

# imageio-ffmpeg distribuye nombres versionados. ARGOS busca explícitamente
# ffmpeg.exe, por lo que se crea una copia estable antes de empaquetar.
vendor_dir = Path("build_vendor")
vendor_dir.mkdir(parents=True, exist_ok=True)
ffmpeg_bundled = vendor_dir / "ffmpeg.exe"
shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), ffmpeg_bundled)

datas = collect_data_files("customtkinter")
datas += collect_data_files("faster_whisper", includes=["assets/*"])
binaries = [(str(ffmpeg_bundled), ".")]
hiddenimports = [
    "pypdf",
    "docx",
    "sounddevice",
    "faster_whisper",
    "faster_whisper.audio",
    "faster_whisper.feature_extractor",
    "faster_whisper.tokenizer",
    "faster_whisper.transcribe",
    "faster_whisper.utils",
    "faster_whisper.vad",
    "ctranslate2",
    "tokenizers",
    "av",
]

analysis = Analysis(
    ["argos_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "torchaudio",
        "pyannote",
        "matplotlib",
        "scipy",
        "pandas",
        "pytest",
        "_pytest",
        "setuptools",
        "pip",
        "wheel",
        "numpy.testing",
    ],
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
    contents_directory=".",
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="ARGOS",
)
