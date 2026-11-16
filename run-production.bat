@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "PYTHON="
if exist "%~dp0venv\Scripts\python.exe" set "PYTHON=%~dp0venv\Scripts\python.exe"
if not defined PYTHON if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON (
    echo Project virtual environment not found. Install requirements in the project venv first.
    exit /b 1
)
if not defined PORT set "PORT=8000"
if not defined FORWARDED_ALLOW_IPS set "FORWARDED_ALLOW_IPS=127.0.0.1"
rem Loopback binding: expose through a trusted reverse proxy or tunnel only.
rem FORWARDED_ALLOW_IPS must be set in the process environment, not only .env.
"%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --workers 1 --proxy-headers --forwarded-allow-ips "%FORWARDED_ALLOW_IPS%" --limit-concurrency 256 --backlog 128 --timeout-keep-alive 5 --ws-max-size 32768 --ws-max-queue 4
exit /b %errorlevel%
