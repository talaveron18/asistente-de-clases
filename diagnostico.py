import importlib.util, shutil, sys
print(f"Python: {sys.version.split()[0]}")
print(f"FFmpeg: {'OK' if shutil.which('ffmpeg') else 'NO ENCONTRADO'}")
for paquete in ['customtkinter','sounddevice','numpy','faster_whisper','torch','torchaudio','pyannote.audio']:
    print(f"{paquete}: {'OK' if importlib.util.find_spec(paquete) else 'FALTA'}")
try:
    import torch
    print(f"CUDA disponible: {torch.cuda.is_available()}")
    if torch.cuda.is_available(): print(f"GPU: {torch.cuda.get_device_name(0)}")
except Exception: pass
