@echo off
setlocal

cd /d "%~dp0"

set "CLOUDFLARED=%~dp0cloudflared-windows-amd64.exe"
set "LOCAL_SCRIPT=%~dp0run-local.bat"
set "PORT=%~1"
if not defined PORT set "PORT=8000"

if not exist "%LOCAL_SCRIPT%" (
    echo [LOI] Khong tim thay %LOCAL_SCRIPT%
    pause
    exit /b 1
)

if not exist "%CLOUDFLARED%" (
    echo [LOI] Khong tim thay %CLOUDFLARED%
    pause
    exit /b 1
)

echo Dang mo server local tren cong %PORT%...
start "Teacher Timetable - Local Server" cmd /k ""%LOCAL_SCRIPT%" %PORT%"

echo Dang cho server khoi dong...
set "SERVER_READY="
for /l %%I in (1,1,15) do (
    powershell.exe -NoProfile -Command "$client = New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1', %PORT%); exit 0 } catch { exit 1 } finally { $client.Dispose() }" >nul 2>&1
    if not errorlevel 1 goto server_ready
    timeout /t 1 /nobreak >nul
)

echo [LOI] Server local khong khoi dong duoc tren cong %PORT%.
echo Hay xem loi trong cua so "Teacher Timetable - Local Server".
pause
exit /b 1

:server_ready

echo.
echo Dang tao Cloudflare Quick Tunnel toi http://127.0.0.1:%PORT%
echo.

"%CLOUDFLARED%" tunnel --url http://127.0.0.1:%PORT%
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Cloudflare Tunnel da dung. Server local van o cua so rieng.
if not "%EXIT_CODE%"=="0" pause

exit /b %EXIT_CODE%
