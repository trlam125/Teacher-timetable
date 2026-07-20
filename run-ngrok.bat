@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "PORT=%~1"
if not defined PORT set "PORT=8000"

rem Tham so thu hai la URL ngrok co dinh, vi du:
rem run-ngrok.bat 8000 https://ten-cua-ban.ngrok.app
set "PUBLIC_URL=%~2"

set "LOCAL_SCRIPT=%~dp0run-local.bat"
if not exist "%LOCAL_SCRIPT%" (
    echo [LOI] Khong tim thay run-local.bat trong:
    echo       %~dp0
    pause
    exit /b 1
)

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

rem Neu server da chay tren PORT thi dung luon, khong mo them mot server moi.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$client = New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1', %PORT%); exit 0 } catch { exit 1 } finally { $client.Dispose() }" >nul 2>&1
if not errorlevel 1 goto server_ready

echo Dang mo server local tren cong %PORT%...
start "Teacher Timetable - Local Server" /D "%~dp0" cmd /k call "%LOCAL_SCRIPT%" "%PORT%"

echo Dang cho server khoi dong...
for /l %%I in (1,1,30) do (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$client = New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1', %PORT%); exit 0 } catch { exit 1 } finally { $client.Dispose() }" >nul 2>&1
    if not errorlevel 1 goto server_ready
    timeout /t 1 /nobreak >nul
)

echo [LOI] Server local khong khoi dong duoc tren cong %PORT%.
echo Hay xem loi trong cua so "Teacher Timetable - Local Server".
pause
exit /b 1

:server_ready
echo.
echo Server local da san sang tai http://127.0.0.1:%PORT%
echo Dang tao ngrok HTTPS tunnel...
echo Nhan Ctrl+C de dung tunnel.
echo.

if defined PUBLIC_URL (
    echo Su dung URL da chi dinh: %PUBLIC_URL%
    echo.
    "%NGROK%" http "%PORT%" --url "%PUBLIC_URL%"
) else (
    "%NGROK%" http "%PORT%"
)

set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Ngrok tunnel da dung. Server local co the van dang chay o cua so rieng.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Neu ngrok bao loi xac thuc, chay mot lan:
    echo     "%NGROK%" config add-authtoken YOUR_AUTHTOKEN
    pause
)

exit /b %EXIT_CODE%
