@echo off
chcp 65001 >nul
setlocal EnableExtensions

cd /d "%~dp0"

set "PORT=%~1"
if not defined PORT set "PORT=8000"

rem Tham số thứ hai là URL ngrok cố định, ví dụ:
rem run-ngrok.bat 8000 https://ten-cua-ban.ngrok.app
set "PUBLIC_URL=%~2"

rem Tìm ngrok.exe trong thư mục project trước, sau đó tìm trong PATH.
set "NGROK="
if exist "%~dp0ngrok.exe" set "NGROK=%~dp0ngrok.exe"
if not defined NGROK (
    for /f "delims=" %%F in ('where ngrok.exe 2^>nul') do if not defined NGROK set "NGROK=%%F"
)

if not defined NGROK (
    echo [LỖI] Không tìm thấy ngrok.exe.
    echo.
    echo Cách 1: Đặt ngrok.exe vào thư mục project:
    echo     %~dp0
    echo.
    echo Cách 2: Cài ngrok và thêm ngrok.exe vào PATH.
    echo.
    echo Sau khi đăng ký tại ngrok.com, cấu hình authtoken một lần:
    echo     ngrok config add-authtoken YOUR_AUTHTOKEN
    pause
    exit /b 1
)

"%NGROK%" version >nul 2>&1
if errorlevel 1 (
    echo [LỖI] Không thể chạy file ngrok:
    echo       %NGROK%
    pause
    exit /b 1
)

rem Chỉ mở tunnel. Server local do người dùng tự khởi động và quản lý.
echo.
echo Đang tạo ngrok HTTPS tunnel tới http://127.0.0.1:%PORT%
echo Hãy chạy server local riêng trên cổng %PORT% trước khi truy cập URL ngrok.
echo Nếu cần quên mật khẩu, đặt APP_BASE_URL trong .env của server local và khởi động lại server.
echo Nhấn Ctrl+C để dừng tunnel.
echo.

if defined PUBLIC_URL (
    echo Sử dụng URL đã chỉ định: %PUBLIC_URL%
    echo.
    "%NGROK%" http "http://127.0.0.1:%PORT%" --url "%PUBLIC_URL%"
) else (
    "%NGROK%" http "http://127.0.0.1:%PORT%"
)

set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Ngrok tunnel đã dừng. Server local được quản lý riêng.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Nếu ngrok báo lỗi xác thực, chạy một lần:
    echo     "%NGROK%" config add-authtoken YOUR_AUTHTOKEN
    pause
)

exit /b %EXIT_CODE%
