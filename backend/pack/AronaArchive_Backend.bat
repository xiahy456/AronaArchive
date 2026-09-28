@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "ARONA_BACKEND_DIR=%CD%"
set "PYTHONHOME=%CD%\python"
set "PYTHONPATH=%CD%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PATH=%CD%\python;%CD%\python\Scripts;%CD%\python\Library\bin;%CD%\python\DLLs;%PATH%"

if not exist "%CD%\python\python.exe" (
  echo Missing python\python.exe. This portable folder is incomplete.
  pause
  exit /b 1
)

echo Starting AronaArchive backend ...
echo Config:    %CD%\config.yaml
echo Health:    http://127.0.0.1:20456/health
echo WebSocket: ws://127.0.0.1:20456/ws
echo.
"%CD%\python\python.exe" -m app.main
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo Backend exited with code %ERR%.
  pause
)
endlocal
exit /b %ERR%
