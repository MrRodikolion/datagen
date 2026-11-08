@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Create .venv and install requirements.txt first. See README.md.
    exit /b 1
)
".venv\Scripts\python.exe" main.py
