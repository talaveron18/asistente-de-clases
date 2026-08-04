@echo off
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe argos_app.py
) else (
  python argos_app.py
)
pause
