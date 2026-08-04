@echo off
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe main_v3.py
) else (
  python main_v3.py
)
pause
