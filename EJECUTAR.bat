@echo off
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe main_v2.py
) else (
  python main_v2.py
)
pause
