@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "PORT=%~1"
if not defined PORT set "PORT=8000"

set "LOCAL_SCRIPT=%~dp0run-local.bat"
if not exist "%LOCAL_SCRIPT%" (
    rem Cho phep dung truc tiep voi ten file ban sua.
    set "LOCAL_SCRIPT=%~dp0run-local-fixed.bat"
)

if not exist "%LOCAL_SCRIPT%" (
    echo [LOI] Khong tim thay run-local.bat trong:
    echo       %~dp0
    pause
    exit /b 1
)

rem Tim cloudflared trong thu muc project truoc, sau do tim trong PATH.
set "CLOUDFLARED="
if exist "%~dp0cloudflared.exe" set "CLOUDFLARED=%~dp0cloudflared.exe"
if not defined CLOUDFLARED if exist "%~dp0cloudflared-windows-amd64.exe" set "CLOUDFLARED=%~dp0cloudflared-windows-amd64.exe"
if not defined CLOUDFLARED (
    for /f "delims=" %%F in ('where cloudflared.exe 2^>nul') do if not defined CLOUDFLARED set "CLOUDFLARED=%%F"
)

if not defined CLOUDFLARED (
    echo [LOI] Khong tim thay Cloudflared.
    echo.
    echo Dat mot trong hai file sau vao thu muc project:
    echo     cloudflared.exe
    echo     cloudflared-windows-amd64.exe
    echo Hoac cai cloudflared va them no vao PATH.
    pause
    exit /b 1
)

echo Dang mo server local tren cong %PORT%...
start "Teacher Timetable - Local Server" /D "%~dp0" cmd /k call "%LOCAL_SCRIPT%" "%PORT%"

echo Dang cho server khoi dong...
set "SERVER_READY="
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
echo Server local da san sang.
echo Dang tao Cloudflare Quick Tunnel toi http://127.0.0.1:%PORT%
echo Nhan Ctrl+C de dung tunnel.
echo.

"%CLOUDFLARED%" tunnel --url "http://127.0.0.1:%PORT%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Cloudflare Tunnel da dung. Server local van o cua so rieng.
if not "%EXIT_CODE%"=="0" pause

exit /b %EXIT_CODE%
