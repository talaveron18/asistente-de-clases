@echo off
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe main_v7.py
) else (
  python main_v7.py
)
pause
