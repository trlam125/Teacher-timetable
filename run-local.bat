@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PORT=%~1"
if not defined PORT set "PORT=8000"

if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    echo [LOI] Khong tim thay Python trong venv hoac .venv.
    echo Hay tao/cai moi truong ao va cai requirements.txt truoc.
    exit /b 1
)

echo Dang kiem tra PostgreSQL...
"%PYTHON%" -m app.scripts.ensure_database
if errorlevel 1 exit /b 1

echo Dang khoi dong Teacher Timetable tren cong %PORT%...
"%PYTHON%" -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port %PORT%
