@echo off
chcp 65001 >nul
setlocal EnableExtensions

cd /d "%~dp0"

set "PORT=%~1"
if not defined PORT set "PORT=8000"

rem Kiểm tra cấu trúc project.
if not exist "%~dp0app\main.py" (
    echo [LỖI] Không tìm thấy app\main.py trong:
    echo       %~dp0
    echo Hãy đặt file này trong thư mục gốc của project Teacher-timetable.
    pause
    exit /b 1
)

rem Ưu tiên venv, sau đó .venv để tương thích cả hai cách đặt tên.
set "PYTHON="
if exist "%~dp0venv\Scripts\python.exe" set "PYTHON=%~dp0venv\Scripts\python.exe"
if not defined PYTHON if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not defined PYTHON (
    echo [LỖI] Không tìm thấy Python trong venv hoặc .venv.
    echo.
    echo Tạo mới môi trường ảo bằng một trong các lệnh sau:
    echo     py -m venv venv
    echo     venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo [LỖI] Môi trường ảo đang bị hỏng.
    echo Hãy xóa venv hoặc .venv, tạo lại và cài requirements.txt.
    pause
    exit /b 1
)

"%PYTHON%" -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo [LỖI] Chưa cài Uvicorn trong môi trường ảo.
    echo Chạy lệnh:
    echo     "%PYTHON%" -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo Đang chạy Smart TKB tại http://127.0.0.1:%PORT%
echo Nhấn Ctrl+C để dừng server.
echo.

"%PYTHON%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port %PORT%
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [LỖI] Server đã dừng với mã lỗi %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
