@echo off
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe main_v4.py
) else (
  python main_v4.py
)
pause
