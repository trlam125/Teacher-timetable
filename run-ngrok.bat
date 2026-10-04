@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "PORT=%~1"
if not defined PORT set "PORT=8000"

rem Tham so thu hai la URL ngrok co dinh, vi du:
rem run-ngrok.bat 8000 https://ten-cua-ban.ngrok.app
set "PUBLIC_URL=%~2"

rem Tim ngrok.exe trong thu muc project truoc, sau do tim trong PATH.
set "NGROK="
if exist "%~dp0ngrok.exe" set "NGROK=%~dp0ngrok.exe"
if not defined NGROK (
    for /f "delims=" %%F in ('where ngrok.exe 2^>nul') do if not defined NGROK set "NGROK=%%F"
)

if not defined NGROK (
    echo [LOI] Khong tim thay ngrok.exe.
    echo.
    echo Cach 1: Dat ngrok.exe vao thu muc project:
    echo     %~dp0
    echo.
    echo Cach 2: Cai ngrok va them ngrok.exe vao PATH.
    echo.
    echo Sau khi dang ky tai ngrok.com, cau hinh authtoken mot lan:
    echo     ngrok config add-authtoken YOUR_AUTHTOKEN
    pause
    exit /b 1
)

"%NGROK%" version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong the chay file ngrok:
    echo       %NGROK%
    pause
    exit /b 1
)

rem Chi mo tunnel. Server local do nguoi dung tu khoi dong va quan ly.
echo.
echo Dang tao ngrok HTTPS tunnel toi http://127.0.0.1:%PORT%
echo Hay chay server local rieng tren cong %PORT% truoc khi truy cap URL ngrok.
echo Neu can quen mat khau, dat APP_BASE_URL trong .env cua server local va khoi dong lai server.
echo Nhan Ctrl+C de dung tunnel.
echo.

if defined PUBLIC_URL (
    echo Su dung URL da chi dinh: %PUBLIC_URL%
    echo.
    "%NGROK%" http "http://127.0.0.1:%PORT%" --url "%PUBLIC_URL%"
) else (
    "%NGROK%" http "http://127.0.0.1:%PORT%"
)

set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Ngrok tunnel da dung. Server local duoc quan ly rieng.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Neu ngrok bao loi xac thuc, chay mot lan:
    echo     "%NGROK%" config add-authtoken YOUR_AUTHTOKEN
    pause
)

exit /b %EXIT_CODE%
