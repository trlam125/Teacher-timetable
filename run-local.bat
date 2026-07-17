@echo off
setlocal

cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "PORT=%~1"
if not defined PORT set "PORT=8000"

if not exist "%PYTHON%" (
    echo [LOI] Khong tim thay %PYTHON%
    echo Hay tao .venv va cai dat requirements.txt truoc.
    pause
    exit /b 1
)

"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Moi truong .venv dang bi hong hoac Python goc khong con truy cap duoc.
    echo Hay cai lai Python, tao lai .venv, sau do chay:
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

"%PYTHON%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port %PORT%
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Server da dung voi ma loi %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
