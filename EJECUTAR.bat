@echo off
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe main_v6.py
) else (
  python main_v6.py
)
pause
