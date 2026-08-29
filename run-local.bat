@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "PORT=%~1"
if not defined PORT set "PORT=8000"

rem Kiem tra cau truc project.
if not exist "%~dp0app\main.py" (
    echo [LOI] Khong tim thay app\main.py trong:
    echo       %~dp0
    echo Hay dat file nay trong thu muc goc cua project Teacher-timetable.
    pause
    exit /b 1
)

rem Uu tien venv, sau do .venv de tuong thich ca hai cach dat ten.
set "PYTHON="
if exist "%~dp0venv\Scripts\python.exe" set "PYTHON=%~dp0venv\Scripts\python.exe"
if not defined PYTHON if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not defined PYTHON (
    echo [LOI] Khong tim thay Python trong venv hoac .venv.
    echo.
    echo Tao moi moi truong ao bang mot trong cac lenh sau:
    echo     py -m venv venv
    echo     venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Moi truong ao dang bi hong.
    echo Hay xoa venv hoac .venv, tao lai va cai requirements.txt.
    pause
    exit /b 1
)

"%PYTHON%" -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo [LOI] Chua cai Uvicorn trong moi truong ao.
    echo Chay lenh:
    echo     "%PYTHON%" -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo Dang chay Smart TKB tai http://127.0.0.1:%PORT%
echo Nhan Ctrl+C de dung server.
echo.

"%PYTHON%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port %PORT%
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [LOI] Server da dung voi ma loi %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
